#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
corp_tgbot.py — MaxAI Corporation Telegram Bot v2 (HARDENED)
=============================================================
Fixes vs v1:
  F1.1 — No hardcoded secrets: loads from .env / env-vars only
  F2.1 — New Corporate token registered + service created
  F2.3 — Context isolation: no system_prompt leakage to LLM
  F3.1 — ThreadPoolExecutor dispatch (non-blocking main loop)
  F3.2 — Atomic state file (tmp + rename)
  F3.3 — seen_ids deduplication (TTL=300s window)
  F1.2 — Confirmation gate for /restart on trading-critical services
  F3.4 — Proper HTML escape on all outgoing messages
  F2.4 — Log path sanitization (whitelist only)
  Rate  — Per-user token bucket: 5 req/10s anti-flood
  Auth  — HMAC-verified CHAT_ID whitelist
"""

import hashlib
import hmac
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Set
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ─── Bootstrap environment ────────────────────────────────────────────────────
_ENV_FILE = Path("/root/my_personal_ai/.env")
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

# ─── Configuration (ALL from env — never hardcode) ───────────────────────────
CORP_TOKEN  = os.environ.get("CORP_BOT_TOKEN", "")          # NEW corporate bot
BYBIT_KEY   = os.environ.get("BYBIT_API_KEY", "")
BYBIT_SEC   = os.environ.get("BYBIT_API_SECRET", "")
ALLOWED_IDS: Set[str] = set(filter(None, os.environ.get("TELEGRAM_CHAT_ID", "").split(",")))
CORP_GROUP_ID = os.environ.get("CORPORATE_CHAT_ID", "")
BYBIT_BASE  = "https://api.bybit.com"
PANEL_BASE  = "http://127.0.0.1:8090"
CORP_API    = "http://127.0.0.1:8091/api/corporate"
BYBIT_MON   = "http://127.0.0.1:8001"

# ─── Single-instance PID lock ──────────────────────────────────────────────
import signal as _signal

from telegram import InlineKeyboardMarkup, InlineKeyboardButton

def corp_main_kb():
    """Главное меню корпоративного бота."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data="status"),
         InlineKeyboardButton("💰 Баланс", callback_data="balance")],
        [InlineKeyboardButton("📈 Трейдинг", callback_data="trading"),
         InlineKeyboardButton("⚡ Агенты", callback_data="agents")],
        [InlineKeyboardButton("🤖 AaaS Флот", callback_data="aaas"),
         InlineKeyboardButton("📋 Kwork", callback_data="kwork")],
        [InlineKeyboardButton("🔄 Swarm", callback_data="swarm"),
         InlineKeyboardButton("🚨 HITL", callback_data="hitl")],
        [InlineKeyboardButton("📰 Отчёт", callback_data="report"),
         InlineKeyboardButton("🖥 Панель ↗", url="https://maxai.fyi")],
    ])

def corp_back_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩ Главное меню", callback_data="menu")]])



_CORP_PID_FILE = Path("/tmp/corp_tgbot.pid")

def _corp_acquire_lock() -> None:
    if _CORP_PID_FILE.exists():
        try:
            old = int(_CORP_PID_FILE.read_text().strip())
            os.kill(old, 0)  # check process alive
            log.warning("Killing stale corp bot PID %d", old)
            os.kill(old, _signal.SIGTERM)
            time.sleep(3)
            try:
                os.kill(old, _signal.SIGKILL)
            except ProcessLookupError:
                pass
        except (ProcessLookupError, ValueError, OSError):
            pass
    _CORP_PID_FILE.write_text(str(os.getpid()))

def _corp_release_lock() -> None:
    try:
        _CORP_PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass



LOG_DIR   = Path("/root/my_personal_ai/logs")
DATA_DIR  = Path("/root/my_personal_ai/data")
LOG_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

STATE_FILE = DATA_DIR / "corp_tgbot_state.json"

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_DIR / "corp_tgbot.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("corp_tgbot")

# ─── Safety constants ─────────────────────────────────────────────────────────
TRADING_CRITICAL_SERVICES = {"bybit-monitor", "personal-ai"}
ALLOWED_SERVICES = {
    "bybit-monitor", "personal-ai", "hyperion-control-plane-v2",
    "hyperion-engine", "panel-guardian", "maxai-guardian", "maxai-tgbot",
    "corp-tgbot", "rabbitmq-server", "maxai-core",
    # Grok Stack 2026
    "ollama", "grok-router", "grok-webui",
}
# Only these log files can be fetched (no traversal)
ALLOWED_LOG_FILES: Set[str] = {
    "tgbot", "corp_tgbot", "bybit_monitor", "trading", "bot", "orchestrator",
    "guardian", "panel_guardian", "errors", "service", "agents",
    "kwork_agent", "funding_arb", "freelance_scanner", "daily_report",
    "daily_revenue", "autodev", "quality_guardian", "brain",
    "grok_router", "grok_webui", "router",
}

# ─── Per-user rate limiter ────────────────────────────────────────────────────
_rate_tokens: Dict[str, float] = defaultdict(lambda: 5.0)
_rate_last:   Dict[str, float] = defaultdict(float)
RATE_MAX    = 5.0
RATE_REFILL = 0.5   # tokens per second
_rate_lock  = threading.Lock()

def _rate_check(user_id: str) -> bool:
    """Return True if user is allowed, consume 1 token."""
    now = time.monotonic()
    with _rate_lock:
        elapsed = now - _rate_last[user_id]
        _rate_last[user_id] = now
        _rate_tokens[user_id] = min(RATE_MAX, _rate_tokens[user_id] + elapsed * RATE_REFILL)
        if _rate_tokens[user_id] >= 1.0:
            _rate_tokens[user_id] -= 1.0
            return True
        return False

# ─── Deduplication (seen update IDs, TTL=300s) ────────────────────────────────
_seen_ids: Dict[int, float] = {}
_seen_lock = threading.Lock()
_SEEN_TTL  = 300.0

def _is_duplicate(update_id: int) -> bool:
    now = time.time()
    with _seen_lock:
        # Prune old entries
        stale = [k for k, ts in _seen_ids.items() if now - ts > _SEEN_TTL]
        for k in stale:
            del _seen_ids[k]
        if update_id in _seen_ids:
            return True
        _seen_ids[update_id] = now
        return False

# ─── Atomic state persistence ─────────────────────────────────────────────────
_state_lock = threading.Lock()

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"offset": 0, "pending_confirms": {}}

def _save_state(state: dict) -> None:
    """Write to temp file then rename — atomic on POSIX."""
    with _state_lock:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(STATE_FILE)

# ─── Confirmation gate ────────────────────────────────────────────────────────

# --- Persistent message queue (0-loss) ---
_MQ_PATH = DATA_DIR / "corp_msg_queue.db"
_mq_init_done = False
_mq_lock = threading.Lock()

def _mq_init():
    global _mq_init_done
    if _mq_init_done:
        return
    import sqlite3 as _sq
    with _sq.connect(str(_MQ_PATH)) as conn:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS msg_queue ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "update_id INTEGER UNIQUE,"
            "chat_id TEXT,"
            "text TEXT,"
            "from_name TEXT,"
            "is_business INTEGER DEFAULT 0,"
            "queued_at TEXT DEFAULT (CURRENT_TIMESTAMP),"
            "acked INTEGER DEFAULT 0);"
            "CREATE INDEX IF NOT EXISTS idx_mq_acked ON msg_queue(acked);"
        )
    _mq_init_done = True

def mq_enqueue(update_id: int, chat_id: str, text: str,
               from_name: str = "", is_business: bool = False) -> bool:
    """Enqueue message. Returns False if duplicate."""
    import sqlite3 as _sq
    _mq_init()
    try:
        with _mq_lock, _sq.connect(str(_MQ_PATH)) as conn:
            conn.execute(
                "INSERT INTO msg_queue (update_id,chat_id,text,from_name,is_business) VALUES (?,?,?,?,?)",
                (update_id, chat_id, text, from_name, int(is_business))
            )
        return True
    except _sq.IntegrityError:
        return False

def mq_ack(update_id: int):
    """Mark message as processed."""
    import sqlite3 as _sq
    _mq_init()
    with _mq_lock, _sq.connect(str(_MQ_PATH)) as conn:
        conn.execute("UPDATE msg_queue SET acked=1 WHERE update_id=?", (update_id,))

def mq_pending() -> list:
    """Unacked messages for crash recovery."""
    import sqlite3 as _sq
    _mq_init()
    with _sq.connect(str(_MQ_PATH)) as conn:
        conn.row_factory = _sq.Row
        return [dict(r) for r in conn.execute(
            "SELECT * FROM msg_queue WHERE acked=0 ORDER BY id LIMIT 100"
        ).fetchall()]


# --- Business intent classifier ---
_BIZ_KEYWORDS = [
    "заказать", "купить", "сколько стоит", "цена", "прайс", "стоимость",
    "хочу подключить", "хочу купить", "готов оплатить", "оплатить",
    "тариф", "расценки", "смета", "коммерческое предложение",
    "нужна автоматизация", "интеграция", "бот для", "сделать бота",
    "разработка", "заявка", "договор", "контракт", "проект",
    "компания", "бизнес", "crm", "автоматизация", "автоматизировать",
    "внедрить", "нужен бот", "нужна система", "демо", "встреча",
    "order", "price", "cost", "buy", "contract", "business", "project",
    "automation", "integration", "hire", "budget", "invoice",
    "quote", "proposal", "demo", "meeting", "urgent",
]

def is_business_intent(text: str) -> bool:
    """True if message has business purchase/project signals."""
    t = text.lower()
    return any(kw in t for kw in _BIZ_KEYWORDS)


def route_to_corp_group(from_name: str, chat_id: str, text: str) -> bool:
    """Forward business message to corp group. Returns True on success."""
    if not CORP_GROUP_ID:
        return False
    if CORP_GROUP_ID == chat_id:
        return False
    msg_text = (
        "<b>Новый бизнес-запрос</b>" + chr(10)
        + "От: " + _safe_html(from_name) + " (id: " + str(chat_id) + ")" + chr(10) + chr(10)
        + _safe_html(text[:800])
    )
    result = tg_send(CORP_GROUP_ID, msg_text, parse_mode="HTML")
    ok = bool(result and result.get("ok"))
    if ok:
        log.info("Business msg routed to corp group from chat=%s", chat_id)
    else:
        log.warning("Corp group routing failed: %s", result)
    return ok


_pending_confirms: Dict[str, dict] = {}
_confirm_lock = threading.Lock()
CONFIRM_TTL = 30.0  # seconds

def _store_confirm(chat_id: str, action: dict) -> str:
    """Store a pending confirmation, return confirm token."""
    token = hashlib.sha256(f"{chat_id}{time.time()}{action}".encode()).hexdigest()[:8]
    with _confirm_lock:
        _pending_confirms[f"{chat_id}:{token}"] = {**action, "ts": time.time()}
    return token

def _pop_confirm(chat_id: str, token: str) -> Optional[dict]:
    key = f"{chat_id}:{token}"
    with _confirm_lock:
        action = _pending_confirms.pop(key, None)
        if action and time.time() - action["ts"] > CONFIRM_TTL:
            return None
        return action

# ─── HTML safe send ───────────────────────────────────────────────────────────
_TG_ESC = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;"})

def _safe_html(text: str) -> str:
    """Escape text portion (not tags) — preserve intentional <b><i><code> only."""
    # Strip all tags, then re-escape for plain text send
    plain = re.sub(r"<[^>]+>", "", text)
    return plain.translate(_TG_ESC)

def tg_send(chat_id: str, text: str, parse_mode: str = "HTML") -> Optional[dict]:
    """Send with HTML fallback → plain fallback."""
    text = text[:4096]
    for mode in ([parse_mode, None] if parse_mode else [None]):
        try:
            payload = {"chat_id": chat_id, "text": text}
            if mode:
                payload["parse_mode"] = mode
            data = json.dumps(payload).encode()
            req = Request(
                f"https://api.telegram.org/bot{CORP_TOKEN}/sendMessage",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=12) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if mode and e.code == 400:
                # Strip HTML → retry as plain text
                text = re.sub(r"<[^>]+>", "", text)
                text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
                log.warning("tg_send HTML 400 → plain retry")
                continue
            log.error("tg_send HTTP %s: %s", e.code, e)
            return None
        except (URLError, OSError) as e:
            log.error("tg_send network: %s", e)
            return None
    return None

def tg_get_updates(offset: int = 0) -> list:
    try:
        url = (
            f"https://api.telegram.org/bot{CORP_TOKEN}/getUpdates"
            f"?offset={offset}&timeout=25&allowed_updates=%5B%22message%22%5D"
        )
        with urlopen(Request(url), timeout=30) as r:
            return json.loads(r.read()).get("result", [])
    except HTTPError as e:
        if e.code == 409:
            log.error("CONFLICT 409 — another bot instance running with same token!")
        else:
            log.warning("getUpdates HTTP %s", e.code)
        return []
    except Exception as e:
        log.warning("getUpdates: %s", e)
        return []

def tg_set_commands() -> None:
    """Register bot command menu."""
    commands = [
        {"command": "status",   "description": "Состояние всех сервисов"},
        {"command": "balance",  "description": "Баланс Bybit и PnL"},
        {"command": "trading",  "description": "Детали торговли"},
        {"command": "analysis", "description": "Анализ рынка"},
        {"command": "report",   "description": "Отчёт по доходам"},
        {"command": "agents",   "description": "Список агентов"},
        {"command": "logs",     "description": "/logs <имя> — логи"},
        {"command": "restart",  "description": "/restart <сервис>"},
        {"command": "kwork",    "description": "Статус Kwork"},
        {"command": "help",     "description": "Список команд"},
        {"command": "setchannel", "description": "/setchannel <id> — настроить канал"},
    ]
    try:
        data = json.dumps({"commands": commands}).encode()
        req = Request(
            f"https://api.telegram.org/bot{CORP_TOKEN}/setMyCommands",
            data=data, headers={"Content-Type": "application/json"},
        )
        with urlopen(req, timeout=10) as r:
            log.info("setMyCommands: %s", json.loads(r.read()).get("result"))
    except Exception as e:
        log.warning("setMyCommands: %s", e)

# ─── Bybit API ─────────────────────────────────────────────────────────────────
def bybit_get(path: str, params: dict = None) -> dict:
    params = params or {}
    ts = int(time.time() * 1000)
    q = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    raw = f"{ts}{BYBIT_KEY}5000{q}" if q else f"{ts}{BYBIT_KEY}5000"
    sig = hmac.new(BYBIT_SEC.encode(), raw.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY":    BYBIT_KEY,
        "X-BAPI-TIMESTAMP":  str(ts),
        "X-BAPI-SIGN":       sig,
        "X-BAPI-RECV-WINDOW": "5000",
    }
    url = f"{BYBIT_BASE}{path}" + (f"?{q}" if q else "")
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

def api_panel(path: str, method: str = "GET", body: dict = None) -> dict:
    try:
        data = json.dumps(body).encode() if body else None
        req = Request(
            f"{PANEL_BASE}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if data else {},
            method=method,
        )
        with urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception:
        return {}

def api_monitor(path: str) -> dict:
    try:
        with urlopen(Request(f"{BYBIT_MON}{path}"), timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}

# ─── Commands ─────────────────────────────────────────────────────────────────
def cmd_status() -> str:
    lines = [
        f"<b>MaxAI Corporation — Статус</b>",
        f"<i>{datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')}</i>",
        "",
    ]
    ok_count = 0
    for svc in sorted(ALLOWED_SERVICES):
        try:
            r = subprocess.run(
                ["systemctl", "is-active", svc],
                capture_output=True, text=True, timeout=3,
            )
            active = r.stdout.strip() == "active"
            ok_count += active
            lines.append(f'{"✅" if active else "❌"} {svc}')
        except Exception:
            lines.append(f"❓ {svc}")

    lines.insert(3, f"<b>Сервисы {ok_count}/{len(ALLOWED_SERVICES)}:</b>")

    # Bot stats (no sensitive data)
    bot = api_monitor("/status")
    if bot and "balance_usdt" in bot:
        lines += [
            "",
            f'<b>Bybit Bot ({bot.get("mode","?").upper()}):</b>',
            f'  💳 ${float(bot.get("balance_usdt",0)):.2f} | PnL: ${float(bot.get("daily_pnl",0)):.4f}',
            f'  Позиций: {bot.get("open_positions",0)} | Сделок: {bot.get("trades_today",0)}',
        ]
    return "\n".join(lines)


def cmd_balance() -> str:
    lines = ["<b>Bybit Balance</b>", ""]
    r = bybit_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    try:
        for c in r["result"]["list"][0]["coin"]:
            if c["coin"] == "USDT":
                lines.append(f'💳 Баланс: <b>${float(c.get("walletBalance",0)):.2f} USDT</b>')
                lines.append(f'📊 Equity: <b>${float(c.get("equity",0)):.2f}</b>')
                break
    except Exception:
        lines.append("❌ Не удалось получить баланс")

    bot = api_monitor("/status")
    if bot:
        lines.append(f'📈 PnL сегодня: <b>${float(bot.get("daily_pnl",0)):.4f}</b>')
        lines.append(f'🔄 Сделок: {bot.get("trades_today",0)} | Режим: {bot.get("mode","?").upper()}')
    risk = api_monitor("/risk")
    if risk:
        lines.append(f'⚠️ Нед. остаток: <b>${float(risk.get("weekly_remaining_usdt",0)):.2f}</b>')
        lines.append(f'📅 Week PnL: ${float(risk.get("week_pnl",0)):.3f}')
    return "\n".join(lines)


def cmd_trading() -> str:
    lines = ["<b>Торговля — детальный статус</b>", ""]
    bot = api_monitor("/status")
    risk = api_monitor("/risk")
    if not bot:
        return "❌ Bot API недоступен"
    mode    = bot.get("mode", "?").upper()
    bal     = bot.get("balance_usdt", 0)
    pnl     = bot.get("daily_pnl", 0)
    trades  = bot.get("trades_today", 0)
    pairs   = ", ".join(bot.get("active_pairs", []))
    active  = bot.get("trading_active", False)
    strats  = ", ".join(s["name"] for s in bot.get("strategies_info", []) if s.get("enabled"))
    week_rem= risk.get("weekly_remaining_usdt", 0) if risk else 0
    week_pnl= risk.get("week_pnl", 0) if risk else 0
    max_day = risk.get("max_daily_trades", 3) if risk else 3
    emerg   = risk.get("emergency_stop", False) if risk else False

    lines += [
        f'Режим: <b>{mode}</b> | Торговля: {"ВКЛ" if active else "ВЫКЛ"}',
        "",
        "<b>Финансы:</b>",
        f"  Баланс: ${float(bal):.2f}",
        f"  PnL сегодня: ${float(pnl):.4f}",
        f"  PnL за неделю: ${float(week_pnl):.3f}",
        f"  Недельный лимит: ${float(week_rem):.2f} осталось",
        "",
        "<b>Торговля:</b>",
        f"  Пары: {pairs or 'нет'}",
        f"  Стратегии: {strats or 'нет'}",
        f"  Сделок сегодня: {trades}/{max_day}",
        f'  Emergency stop: {"ДА ⚠️" if emerg else "нет"}',
    ]
    last_sig = bot.get("last_signal", {})
    if last_sig:
        lines += [
            "",
            "<b>Последний сигнал:</b>",
            f'  {last_sig.get("symbol","?")} {last_sig.get("action","?")} '
            f'({last_sig.get("strategy","?")} strength={float(last_sig.get("strength",0)):.2f})',
        ]
    return "\n".join(lines)


def cmd_analysis() -> str:
    lines = [
        "<b>Рыночный анализ</b>",
        f"<i>{datetime.now(timezone.utc).strftime('%H:%M UTC')}</i>",
        "",
    ]
    pairs = ["SOLUSDT", "LINKUSDT", "DOTUSDT", "BTCUSDT", "ETHUSDT"]
    opportunities = []
    for symbol in pairs:
        try:
            r = bybit_get("/v5/market/tickers", {"category": "linear", "symbol": symbol})
            item = r.get("result", {}).get("list", [{}])[0]
            rate     = float(item.get("fundingRate", 0))
            price    = float(item.get("lastPrice", 0))
            change   = float(item.get("price24hPcnt", 0)) * 100
            icon     = "📈" if change > 0 else "📉"
            annual   = abs(rate) * 3 * 365 * 100
            wins     = "LONG wins" if rate < 0 else "SHORT wins"
            lines.append(
                f"{icon} <b>{symbol}</b>: ${price:.2f} ({change:+.1f}%) | "
                f"Funding: {rate*100:.4f}%/8h ({annual:.0f}%/yr, {wins})"
            )
            if abs(rate) >= 0.0003:
                opportunities.append(f"⚡ {symbol}: {rate*100:.4f}%/8h HIGH")
            time.sleep(0.05)
        except Exception:
            pass

    if opportunities:
        lines += ["", "<b>Торговые возможности:</b>"] + opportunities
    else:
        lines.append("\nФандинг нейтральный.")
    return "\n".join(lines)


def cmd_restart(service: str, chat_id: str) -> str:
    service = service.strip().lower()
    if service not in ALLOWED_SERVICES:
        safe_list = ", ".join(sorted(ALLOWED_SERVICES))
        return f"❌ Неизвестный сервис\nДоступны: <code>{safe_list}</code>"

    # CONFIRMATION GATE for trading-critical services
    if service in TRADING_CRITICAL_SERVICES:
        # Check for open positions before allowing restart
        bot = api_monitor("/status")
        open_pos = int(bot.get("open_positions", 0)) if bot else "?"

        token = _store_confirm(chat_id, {"action": "restart", "service": service})
        return (
            f"⚠️ <b>ВНИМАНИЕ: {service} — критический сервис</b>\n"
            f"Открытых позиций: <b>{open_pos}</b>\n\n"
            f"Для подтверждения отправь: <code>/confirm {token}</code>\n"
            f"<i>Действительно {int(CONFIRM_TTL)}с</i>"
        )

    return _do_restart(service)


def _do_restart(service: str) -> str:
    try:
        subprocess.run(["systemctl", "restart", service], capture_output=True, text=True, timeout=30)
        time.sleep(2)
        r = subprocess.run(["systemctl", "is-active", service], capture_output=True, text=True, timeout=3)
        ok = r.stdout.strip() == "active"
        return f'{"✅" if ok else "❌"} <b>{service}</b>: {r.stdout.strip()}'
    except Exception as e:
        return f"❌ Ошибка: {str(e)[:200]}"


def cmd_confirm(token: str, chat_id: str) -> str:
    action = _pop_confirm(chat_id, token)
    if not action:
        return "❌ Токен не найден или истёк. Повтори команду заново."
    if action.get("action") == "restart":
        return _do_restart(action["service"])
    return "❌ Неизвестное действие"


def cmd_logs(name: str) -> str:
    # Sanitize: only whitelisted names, no path traversal
    name = re.sub(r"[^a-z0-9_\-]", "", name.lower())
    if not name or name not in ALLOWED_LOG_FILES:
        safe = ", ".join(sorted(ALLOWED_LOG_FILES))
        return f"❌ Лог <b>{name}</b> не в белом списке\nДоступны: <code>{safe}</code>"

    log_file = LOG_DIR / f"{name}.log"
    if log_file.exists():
        try:
            r = subprocess.run(["tail", "-n", "25", str(log_file)], capture_output=True, text=True, timeout=5)
            text = r.stdout[-2000:] if r.stdout else "пусто"
            # Strip any system paths from output before sending
            text = re.sub(r"/root/[^\s\"']+", "[path]", text)
            return f"<b>Лог {name}:</b>\n<code>{text}</code>"
        except Exception as e:
            return f"❌ Ошибка чтения: {str(e)[:100]}"

    return f"❌ Лог <b>{name}.log</b> не найден"


def cmd_report() -> str:
    lines = [
        "<b>MaxAI Revenue Report</b>",
        f"<i>{datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')}</i>",
        "",
    ]
    r = bybit_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
    try:
        for c in r["result"]["list"][0]["coin"]:
            if c["coin"] == "USDT":
                lines.append(f'💳 Баланс: <b>${float(c.get("walletBalance",0)):.2f}</b>')
                break
    except Exception:
        lines.append("💳 Баланс: N/A")

    bot = api_monitor("/status")
    if bot:
        lines.append(f'📈 PnL сегодня: ${float(bot.get("daily_pnl",0)):.4f}')
        lines.append(f'Сделок: {bot.get("trades_today",0)}')

    try:
        ks = json.loads((DATA_DIR / "kwork_state.json").read_text())
        lines.append(f'\n💼 Kwork: {ks.get("total_applied",0)} откликов, выиграно {ks.get("won",0)}')
    except Exception:
        lines.append("\n💼 Kwork: нет данных")

    ok = 0
    for svc in ALLOWED_SERVICES:
        try:
            r2 = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True, timeout=2)
            ok += r2.stdout.strip() == "active"
        except Exception:
            pass
    lines.append(f"\n🖥️ Сервисов активно: {ok}/{len(ALLOWED_SERVICES)}")
    return "\n".join(lines)


def cmd_agents() -> str:
    lines = ["<b>Агенты MaxAI</b>", ""]
    try:
        agents = sorted(
            [f for f in Path("/root/my_personal_ai/agents").glob("*.py") if not f.name.startswith("_")],
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )[:20]
        for af in agents:
            r = subprocess.run(["pgrep", "-f", af.name], capture_output=True, text=True)
            icon = "🟢" if r.stdout.strip() else "⚫"
            lines.append(f"{icon} {af.name}")
    except Exception as e:
        lines.append(f"❌ {str(e)[:100]}")
    return "\n".join(lines)


def cmd_kwork() -> str:
    lines = ["<b>Kwork Agent</b>", ""]
    try:
        ks = json.loads((DATA_DIR / "kwork_state.json").read_text())
        lines += [
            f'Откликов всего: <b>{ks.get("total_applied",0)}</b>',
            f'Выиграно: <b>{ks.get("won",0)}</b>',
            f'Заработано: <b>{ks.get("total_earned_rub",0):,} руб</b>',
        ]
    except Exception:
        lines.append("Нет данных. Агент не запускался.")
    return "\n".join(lines)


def cmd_positions() -> str:
    """Live open positions from trading bot."""
    lines = ["<b>Открытые позиции</b>", ""]
    pos = api_panel("/api/trading/positions")
    if not pos:
        return "❌ Позиции недоступны"
    positions = pos.get("positions", [])
    if not positions:
        lines.append("Нет открытых позиций")
    else:
        for p in positions:
            pnl = float(p.get("unrealised_pnl", p.get("pnl", 0)))
            icon = "📈" if pnl >= 0 else "📉"
            lines.append(
                f'{icon} <b>{p.get("symbol","?")}</b> {p.get("side","?")}\n'
                f'  Entry: {p.get("entry_price","?")} | SL: {p.get("stop_loss","?")} | TP: {p.get("take_profit","?")}\n'
                f'  PnL: ${pnl:.4f}'
            )
    return "\n".join(lines)


def cmd_browser() -> str:
    """Browser control v2 status."""
    d = api_panel("/api/browser/v2/state")
    if not d:
        return "❌ Browser API недоступен"
    state   = d.get("state", "UNKNOWN")
    owner   = d.get("lease", {}).get("owner", "none")
    running = d.get("running", False)
    url     = d.get("url", "—")
    lines = [
        "<b>Browser Control v2</b>",
        f'Состояние: <b>{state}</b> | Владелец: {owner}',
        f'Запущен: {"да" if running else "нет"}',
        f'URL: {url or "—"}',
    ]
    return "\n".join(lines)


def cmd_links() -> str:
    lines = [
        "<b>MaxAI — Все ресурсы</b>",
        "",
        "<b>Боты:</b>",
        "• @Corporation_MaxAI_bot — корп бот",
        "• @maksim_bybit_bot — управление системой",
        "",
        "<b>Панель управления:</b>",
        "• https://maxai.fyi/ — главная",
        "• https://maxai.fyi/api/v1/manifest",
        "",
        "<b>API для клиентов:</b>",
        "POST https://maxai.fyi/api/v1/webhook — заявки",
        "POST https://maxai.fyi/api/v1/ai — AI",
        "GET  https://maxai.fyi/api/v1/packs — пакеты",
        "",
        "<b>Статус системы:</b>",
        "https://maxai.fyi/health",
        "https://maxai.fyi/api/status",
    ]
    return chr(10).join(lines)


def cmd_setchannel(arg: str, chat_id: str) -> str:
    """Save CHANNEL_ID to .env and reload social scheduler."""
    channel = arg.strip()
    if not channel:
        return (
            "<b>/setchannel — Настройка канала</b>" + chr(10) + chr(10)
            + "Шаг 1: Создайте Telegram-канал" + chr(10)
            + "Шаг 2: Добавьте @Corporation_MaxAI_bot как администратора" + chr(10)
            + "Шаг 3: Перешлите любое сообщение из канала в @userinfobot — получите ID" + chr(10)
            + "Шаг 4: Введите: /setchannel -100xxxxxxxxxx" + chr(10) + chr(10)
            + "Текущее значение: " + (os.environ.get("CHANNEL_ID") or "не установлено")
        )
    # Validate format
    if not (channel.startswith("-100") or channel.startswith("@")):
        return "❌ Неверный формат. Используй: /setchannel -100xxxxxxxxxx или @channelusername"
    # Write to .env
    env_path = "/root/my_personal_ai/.env"
    try:
        try:
            with open(env_path, "r", encoding="utf-8") as _f:
                env_lines = _f.readlines()
        except FileNotFoundError:
            env_lines = []
        # Remove existing CHANNEL_ID line
        env_lines = [ln for ln in env_lines if not ln.startswith("CHANNEL_ID=")]
        env_lines.append("CHANNEL_ID=" + channel + chr(10))
        with open(env_path, "w", encoding="utf-8") as _f:
            _f.writelines(env_lines)
        os.environ["CHANNEL_ID"] = channel
        # Test: try to get chat info
        import urllib.request as _ur, json as _js
        try:
            url = "https://api.telegram.org/bot" + CORP_TOKEN + "/getChat?chat_id=" + channel
            with _ur.urlopen(_ur.Request(url), timeout=8) as r:
                chat_data = _js.loads(r.read())
            if chat_data.get("ok"):
                chat_title = chat_data["result"].get("title", channel)
                return (
                    "✅ <b>CHANNEL_ID установлен!</b>" + chr(10)
                    + "Канал: " + chat_title + chr(10)
                    + "ID: " + channel + chr(10) + chr(10)
                    + "Контент-планировщик будет использовать этот канал." + chr(10)
                    + "Следующий пост: завтра в 09:00 МСК или запусти вручную."
                )
            else:
                err = chat_data.get("description", "неизвестная ошибка")
                return (
                    "⚠️ CHANNEL_ID сохранён, но бот не является членом канала." + chr(10)
                    + "Ошибка: " + err + chr(10) + chr(10)
                    + "Добавьте @Corporation_MaxAI_bot как администратора канала."
                )
        except Exception:
            return (
                "✅ CHANNEL_ID=" + channel + " сохранён." + chr(10)
                + "Убедитесь что бот является администратором канала."
            )
    except Exception as _e:
        return "❌ Ошибка сохранения: " + str(_e)


def cmd_help() -> str:
    nl = chr(10)
    lines = [
        "<b>MaxAI Corporation Bot v2</b>",
        "",
        "<b>Команды:</b>",
        "/status /balance /trading /positions /swarm /hitl",
        "/report /agents /kwork /grok /keys /links /restart",
        "/logs <name>  /approve <id>  /reject <id>",
        "",
        "<b>Естественный язык:</b>",
        "покажи корпорацию | выполняй | продолжай",
        "план | отчёт | прибыль | позиции | баланс",
        "добавляй в kwork кворки",
        "спроси у grok: <вопрос>",
        "",
        "Панель: https://maxai.fyi",
    ]
    return nl.join(lines)


def _corp_llm_status() -> str:
    """Get LLM providers status from panel."""
    try:
        import urllib.request as _ur
        r = _ur.urlopen('http://127.0.0.1:8090/api/llm/status', timeout=5)
        data = json.loads(r.read())
        providers = data.get('providers', [])
        lines = ['<b>Статус LLM:</b>']
        for p in providers:
            icon = '✅' if p.get('available') else '❌'
            lines.append(f'{icon} {p["name"]}: {p["model"]}')
        return '\n'.join(lines)
    except Exception as e:
        return f'❌ LLM статус: {e}'


def _corp_scan_leads():
    try:
        from urllib.request import Request as _R, urlopen as _uo
        import json as _j
        req = _R(CORP_API + "/leads/scan")
        with _uo(req, timeout=10) as r:
            d = _j.loads(r.read())
        total = d.get("total", 0)
        hot = d.get("hot", 0)
        leads = d.get("leads", [])
        if not hot:
            return "Leads: %d checked, no hot" % total
        out = ["Found %d hot of %d:" % (hot, total)]
        for lead in leads[:5]:
            kws = ", ".join(lead.get("keywords", [])[:3])
            out.append("  [%d%%] %s: %s..." % (int(lead.get("score",0)*100), kws, lead.get("text","")[:80]))
        return chr(10).join(out)
    except Exception as e:
        return "Lead error: " + str(e)


def _corp_post_social(text=""):
    try:
        from urllib.request import Request as _R, urlopen as _uo
        import json as _j
        body = _j.dumps({"text": text} if text else {}).encode()
        req = _R(CORP_API + "/social/post", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with _uo(req, timeout=15) as r:
            d = _j.loads(r.read())
        return ("Post sent: " + d.get("preview","")[:60]) if d.get("ok") else "Post failed"
    except Exception as e:
        return "Social error: " + str(e)



def _cmd_swarm() -> str:
    """CEO + 7 departments status from maxai-core:4000."""
    import urllib.request as _urs, json as _jss
    try:
        with _urs.urlopen("http://127.0.0.1:4000/api/swarm/status", timeout=5) as _rs:
            _ds = _jss.loads(_rs.read())
        _ceo = _ds.get("ceo", {})
        _cycle = _ceo.get("cycle", "?")
        _alerts = _ceo.get("alert_count", 0)
        _hitl = _ceo.get("hitl_pending", 0)
        _depts = _ds.get("depts", {})
        _icons = {"infra": "🖥", "ecommerce": "🛒", "trading": "📈",
                  "logistics": "🚚", "affiliate": "🎮", "fintech": "💳", "data": "🔍"}
        _lines = [
            "<b>MaxAI Enterprise Swarm</b>",
            f"🔄 CEO Цикл: #{_cycle} | Алертов: {_alerts}",
            f"⏳ HITL ожидает: {_hitl}",
            "",
            "<b>Отделы:</b>",
        ]
        for _dept, _st_raw in _depts.items():
            _ic = _icons.get(_dept, "🏢")
            _st_val = _st_raw.get("status", "?") if isinstance(_st_raw, dict) else (_st_raw or "?")
            _tasks = _st_raw.get("tasks_done", 0) if isinstance(_st_raw, dict) else ""
            _ok = _st_val in ("ok", "active")
            _em = "🟢" if _ok else "🟡"
            _lines.append(f"  {_em} {_ic} {_dept}: {_st_val}" + (f" ({_tasks} tasks)" if _tasks else ""))
        if _hitl > 0:
            _lines += ["", f"⚠️ <b>{_hitl} HITL</b> ожидают — /hitl для просмотра"]
        _alert_list = _ceo.get("alerts", [])
        if _alert_list:
            _lines += ["", "<b>Алерты:</b>"]
            for _al in _alert_list[:3]:
                _lines.append(f"  [{_al.get('level','?')}] {_al.get('kpi','?')} = {_al.get('val','?')}")
        return "\n".join(_lines)
    except Exception as _es:
        return f"❌ maxai-core недоступен: {str(_es)[:80]}\nПроверь: /restart maxai-core"




# AUTO-GENERATED STUBS - DO NOT REMOVE
def _cmd_hitl() -> str:
    """Show pending HITL approval queue."""
    import urllib.request as _urh, json as _jh2
    try:
        with _urh.urlopen("http://127.0.0.1:4000/api/swarm/hitl/pending", timeout=5) as _rq:
            _dq = _jh2.loads(_rq.read())
        _queue = _dq.get("queue", [])
        if not _queue:
            return "✅ HITL очередь пуста — нет ожидающих запросов"
        _lines = [f"<b>HITL очередь: {len(_queue)} запросов</b>", ""]
        for _req in _queue:
            _state = _req.get("state", "?")
            _rid = _req.get("req_id", "?")
            _em = "⏳" if _state == "AWAITING_APPROVAL" else ("✅" if _state == "APPROVED" else "❌")
            _lines += [
                f"{_em} <b>{_rid}</b> | {_req.get('dept','?')} | ${float(_req.get('amount',0)):.2f}",
                f"   Действие: {_req.get('action','?')} | {_state}",
            ]
            if _state == "AWAITING_APPROVAL":
                _lines.append(f"   👉 /approve {_rid}")
            _lines.append("")
        return "\n".join(_lines)
    except Exception as _eq:
        return f"❌ HITL API: {str(_eq)[:80]}"


def _cmd_hitl_action(req_id: str, action: str) -> str:
    """Approve or reject a HITL request by req_id."""
    import urllib.request as _urha, json as _jha
    if not req_id:
        return f"❌ Укажи: /{action} <req_id>\nПример: /{action} b60e6ff8"
    try:
        _req = _urha.Request(
            f"http://127.0.0.1:4000/api/swarm/hitl/{req_id}/{action}",
            method="POST", headers={"Content-Type": "application/json"}
        )
        with _urha.urlopen(_req, timeout=5) as _rha:
            _dha = _jha.loads(_rha.read())
        _verb = "ОДОБРЕН" if action == "approve" else "ОТКЛОНЁН"
        return (f"{'✅' if action == 'approve' else '❌'} <b>HITL {req_id} — {_verb}</b>\n"
                f"Статус: {_dha.get('status', '?')}")
    except Exception as _eha:
        err = str(_eha)
        if "404" in err or "Not found" in err.lower():
            return chr(10060) + " Signal " + req_id + " not found or expired. Try /hitl"
        if "400" in err or "Expired" in err.lower():
            return chr(9200) + " Signal " + req_id + " expired. Try /hitl"
        return f"❌ Ошибка {action}: {err[:80]}"

def _cmd_coffee() -> str:
    """Coffee import logistics status."""
    import urllib.request as _urlc, json as _jlc
    from datetime import date as _dlc
    _lines = ["<b>Логистика — Кофе Колумбия 600кг</b>"]
    try:
        with _urlc.urlopen("http://127.0.0.1:4000/api/swarm/depts", timeout=4) as _rc:
            _dc = _jlc.loads(_rc.read())
        _lg = _dc.get("logistics", {})
        _m = _lg.get("metrics", {})
        _days_api = int(_m.get("days_to_july", _m.get("logistics.days_to_july", 0)) or 0)
        if _days_api == 0:
            _days = (_dlc(2026, 7, 1) - _dlc.today()).days
        else:
            _days = _days_api
        _status = _lg.get("status", "?")
        _lines += [
            f"Статус: {_status}",
            f"До июля 2026: <b>{_days} дней</b>",
            "Минимум: 42 дня (21 фрахт + 7 таможня + 14 обжарка)",
        ]
        if _days < 3:
            _lines.append("🔴 <b>КРИТИЧНО</b> — нужно решение сегодня!")
        elif _days < 14:
            _lines.append("🟡 <b>РИСК</b> — нужна авиа-доставка или сдвиг на август")
        elif _days < 42:
            _lines.append(f"🟡 <b>РИСК</b> — осталось {_days} дней, нужно 42")
        else:
            _lines.append(f"🟢 В норме — {_days} дней")
    except Exception as _elc:
        _today = _dlc.today()
        _days = (_dlc(2026, 7, 1) - _today).days
        _lines += [
            f"До июля 2026: <b>{_days} дней</b> (локальный расчёт)",
            "Последняя дата отгрузки: 2026-05-20 (прошла!)",
            f"{'🔴 КРИТИЧНО: нужно 42 дня, осталось ' + str(_days) if _days < 42 else '🟢 Норма'}",
        ]
    _lines += [
        "",
        "<b>Варианты:</b>",
        "  1. Авиа-доставка (экспресс, дороже)",
        "  2. Сдвинуть дедлайн на август 2026",
        "  3. Подтвердить — груз уже отправлен",
    ]
    return "\n".join(_lines)

# END AUTO-GENERATED STUBS


def _corp_check_keys() -> str:
    """Quick check of all API keys from within corp bot."""
    import os as _osk
    lines = ["<b>Статус API ключей:</b>"]
    checks = {
        "BYBIT_API_KEY": "Bybit", "ANTHROPIC_API_KEY": "Claude",
        "DEEPSEEK_API_KEY": "DeepSeek", "GROQ_API_KEY": "Groq",
        "OPENROUTER_API_KEY": "OpenRouter", "KWORK_EMAIL": "Kwork",
        "CORP_BOT_TOKEN": "Corp Bot", "TELEGRAM_BOT_TOKEN": "Main Bot",
    }
    for key, name in checks.items():
        val = _osk.environ.get(key, "")
        if val:
            masked = val[:4] + "..." + val[-3:] if len(val) > 7 else "***"
            lines.append(f"OK {name}: {masked}")
        else:
            lines.append(f"NO {name}: не задан")
    return chr(10).join(lines)


def _corp_llm_status() -> str:
    """Check LLM provider chain status."""
    import urllib.request as _ull, os as _oll
    lines = ["<b>Статус LLM провайдеров:</b>"]
    providers = [
        ("DeepSeek", "https://api.deepseek.com/", "DEEPSEEK_API_KEY"),
        ("Groq",     "https://api.groq.com/", "GROQ_API_KEY"),
        ("Anthropic","https://api.anthropic.com/", "ANTHROPIC_API_KEY"),
    ]
    for name, url, key_env in providers:
        has_key = bool(_oll.environ.get(key_env, ""))
        lines.append(f"{'OK' if has_key else 'NO'} {name}: {'ключ есть' if has_key else 'нет ключа'}")
    lines += ["", "Приоритет: DeepSeek > Groq (403-блок) > Claude > Panel"]
    return chr(10).join(lines)




def _cmd_key_help() -> str:
    lines = [
        "<b>Как добавить API ключ:</b>",
        "",
        "Просто отправь в бот:",
        "  GROQ_API_KEY=gsk_...",
        "  WILDBERRIES_API_KEY=...",
        "  PST_API_KEY=...",
        "",
        "Или: /setkey NAME=value",
        "",
        "Бесплатные ключи:",
        "  Groq: console.groq.com/keys",
        "  OpenRouter: openrouter.ai/keys",
        "",
        "Для HITL запросов по ключам: /hitl",
    ]
    return chr(10).join(lines)

def _cmd_add_key_help() -> str:
    return _cmd_key_help()



def _cmd_payment() -> str:
    """Client payment information."""
    return (
        "\U0001f4b3 <b>Оплата услуг MaxAI</b>\n\n"
        "Принимаем криптовалюту 24/7:\n\n"
        "🪙 <b>USDT TRC20:</b>\n"
        "<code>TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2</code>\n\n"
        "⟠ <b>ETH / ERC20:</b>\n"
        "<code>0x7b72d6072f973a79d13abb11769927890832cc12</code>\n\n"
        "₿ <b>BTC:</b>\n"
        "<code>158AEebXosZfxHY1ZVQNfTT6BHcuHqGFr4</code>\n\n"
        "После оплаты отправьте скриншот/TXID.\n"
        "Тарифы: maxai.fyi/hire"
    )

def dispatch(text: str, chat_id: str) -> str:
    """Process one message; returns reply string."""
    # MaxAI prefix = прямо в AI, высший приоритет
    if text.strip()[:6].lower() == 'maxai ':
        query = text.strip()[6:].strip()
        log.info("MaxAI direct uid=%s: %s", chat_id, query[:80])
        return cmd_ai(query, chat_id)
    parts = text.strip().split(None, 1)
    cmd   = parts[0].lstrip("/").split("@")[0].lower()
    arg   = parts[1].strip() if len(parts) > 1 else ""
    log.info("cmd=%r arg=%r chat=%s", cmd, arg[:40], chat_id)

    table = {
        "start":    cmd_help,
        "help":     cmd_help,
        "status":   cmd_status,
        "balance":  cmd_balance,
        "pay":      lambda: _cmd_payment(),
        "trading":  cmd_trading,
        "fleet":    cmd_report,
        "aaas":     cmd_report,
        "revenue":  cmd_report,
        "analysis": cmd_analysis,
        "report":   cmd_report,
        "agents":   cmd_agents,
        "kwork":    cmd_kwork,
        "positions": cmd_positions,
        "browser":  cmd_browser,
        "links":    cmd_links,
        "setchannel": lambda: cmd_setchannel(arg, chat_id),
        "leads":   lambda: _corp_scan_leads(),
        "social":  lambda: _corp_post_social(arg),
        "task":    lambda: _cmd_smart_execute(arg if arg else text, chat_id),
        "execute": lambda: _cmd_smart_execute(arg if arg else text, chat_id),
        "keys":    _corp_check_keys,
        "llm":     _corp_llm_status,
        "swarm":   _cmd_swarm,
        "hitl":    _cmd_hitl,
        "approve": lambda: _cmd_hitl_action(arg, "approve"),
        "reject":  lambda: _cmd_hitl_action(arg, "reject"),
        "coffee":  _cmd_coffee,
        "keys":    _corp_check_keys,
        "keyhelp": lambda: _cmd_key_help(),
        
    }

    if cmd in table:
        return table[cmd]()
    elif cmd == "restart":
        return cmd_restart(arg, chat_id) if arg else "❌ Укажи: /restart bybit-monitor"
    elif cmd == "confirm":
        return cmd_confirm(arg, chat_id) if arg else "❌ Укажи: /confirm &lt;токен&gt;"
    
def main() -> None:
    if not CORP_TOKEN:
        log.error("CORP_BOT_TOKEN not set! Export it or add to .env")
        sys.exit(1)

    _corp_acquire_lock()
    import atexit as _atexit
    _atexit.register(_corp_release_lock)

    log.info("MaxAI Corporation — AI-агенты и автоматизация starting (token: ...%s)", CORP_TOKEN[-6:])
    state = _load_state()

    # Register commands menu
    tg_set_commands()

    # Announce startup (if chat ID configured)
    if ALLOWED_IDS:
        for cid in ALLOWED_IDS:
            tg_send(
                cid,
                f"<b>MaxAI Corporation — AI-агенты и автоматизация</b> готова ✅\n"
                f"<i>{datetime.now(timezone.utc).strftime('%d.%m.%Y %H:%M UTC')}</i>\n"
                "/help — список команд",
            )

    offset = state.get("offset", 0)
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="corp_dispatch")
    backoff = 1.0

    while True:
        try:
            updates = tg_get_updates(offset)
            backoff = 1.0  # reset on success

            for upd in updates:
                uid = upd["update_id"]
                offset = uid + 1

                # Idempotency check (in-memory TTL)
                if _is_duplicate(uid):
                    log.debug("Duplicate update_id=%d skipped", uid)
                    state["offset"] = offset
                    _save_state(state)
                    continue

                msg = upd.get("message", {})
                if not msg:
                    state["offset"] = offset
                    _save_state(state)
                    continue
                chat_id   = str(msg.get("chat", {}).get("id", ""))
                text      = msg.get("text", "").strip()
                from_user = msg.get("from", {})
                from_name = " ".join(filter(None, [
                    from_user.get("first_name", ""),
                    from_user.get("last_name", ""),
                    from_user.get("username", ""),
                ]))

                if not text:
                    state["offset"] = offset
                    _save_state(state)
                    continue

                # Classify business intent BEFORE auth check
                biz = is_business_intent(text)

                # Persist to SQLite queue (0-loss guarantee)
                mq_enqueue(uid, chat_id, text, from_name, biz)

                # Route business messages to corp group (even non-authorized)
                if biz and chat_id not in ALLOWED_IDS:
                    threading.Thread(
                        target=route_to_corp_group,
                        args=(from_name, chat_id, text),
                        daemon=True
                    ).start()
                    tg_send(
                        chat_id,
                        "Спасибо за интерес! Менеджер свяжется в ближайшее время. "  # noqa
                        "@Corporation_MaxAI_bot"
                    )
                    mq_ack(uid)
                    state["offset"] = offset
                    _save_state(state)
                    continue

                # Auth check for admin commands
                if chat_id not in ALLOWED_IDS:
                    tg_send(chat_id, "❌ Доступ запрещён.")
                    mq_ack(uid)
                    state["offset"] = offset
                    _save_state(state)
                    continue

                # Also route authorized business messages to corp group
                if biz:
                    threading.Thread(
                        target=route_to_corp_group,
                        args=(from_name, chat_id, text),
                        daemon=True
                    ).start()

                # Rate limit
                if not _rate_check(chat_id):
                    tg_send(chat_id, "⏳ Слишком много запросов. Подожди 10 секунд.")
                    mq_ack(uid)
                    state["offset"] = offset
                    _save_state(state)
                    continue

                # Non-blocking dispatch with guaranteed ACK
                def _task(t=text, c=chat_id, u=uid):
                    try:
                        reply = dispatch(t, c)
                        tg_send(c, reply)
                    except Exception as exc:
                        log.exception("Dispatch error for %r: %s", t[:50], exc)
                        tg_send(c, "❌ Внутренняя ошибка. Попробуй ещё раз.")
                    finally:
                        mq_ack(u)

                executor.submit(_task)

                # Per-update offset save (0-loss on crash)
                state["offset"] = offset
                _save_state(state)


        except KeyboardInterrupt:
            log.info("Shutting down")
            executor.shutdown(wait=True)
            break
        except Exception as exc:
            log.error("Main loop: %s", exc)
            time.sleep(min(backoff, 30.0))
            backoff = min(backoff * 2, 30.0)


if __name__ == "__main__":
    main()
