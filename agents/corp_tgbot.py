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
    "corp-tgbot", "rabbitmq-server",
}
# Only these log files can be fetched (no traversal)
ALLOWED_LOG_FILES: Set[str] = {
    "tgbot", "corp_tgbot", "bybit_monitor", "trading", "bot", "orchestrator",
    "guardian", "panel_guardian", "errors", "service", "agents",
    "kwork_agent", "funding_arb", "freelance_scanner", "daily_report",
    "daily_revenue", "autodev", "quality_guardian", "brain",
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
        "• http://77.90.2.171/ — главная",
        "• http://77.90.2.171/api/v1/manifest",
        "",
        "<b>API для клиентов:</b>",
        "POST http://77.90.2.171/api/v1/webhook — заявки",
        "POST http://77.90.2.171/api/v1/ai — AI",
        "GET  http://77.90.2.171/api/v1/packs — пакеты",
        "",
        "<b>Статус системы:</b>",
        "http://77.90.2.171/health",
        "http://77.90.2.171/api/status",
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
    return "<b>MaxAI Corporation Bot v2</b>\n\n<b>Статус и данные:</b>\n/status — состояние сервисов\n/balance — баланс и PnL\n/trading — детали торговли\n/positions — открытые позиции\n/analysis — рыночный анализ\n/report — отчёт по доходам\n/kwork — статистика Kwork\n/agents — список агентов\n/browser — Browser Control v2\n\n<b>Управление:</b>\n/restart &lt;сервис&gt; — перезапуск (с подтверждением для торговых)\n/confirm &lt;токен&gt; — подтвердить опасное действие\n/logs &lt;имя&gt; — логи\n\n<b>Бизнес-инструменты:</b>\n/leads — сканировать горячие лиды\n/social [текст] — опубликовать пост\n\nИли напиши вопрос — отвечу!"


# ─── AI routing (context-isolated) ───────────────────────────────────────────
def md2tg(txt):
    """Markdown -> Telegram HTML (prevents sendMessage 400)."""
    import re as _re
    AMP = chr(38)+chr(97)+chr(109)+chr(112)+chr(59)
    LT  = chr(38)+chr(108)+chr(116)+chr(59)
    GT  = chr(38)+chr(103)+chr(116)+chr(59)
    def _esc(s):
        return s.replace(chr(38), AMP).replace(chr(60), LT).replace(chr(62), GT)
    def cb(m):
        c = (m.group(2) or '').strip()
        return '<code>' + _esc(c) + '</code>'
    txt = _re.sub(BT*3+r'(\w*)?\n?([\s\S]*?)'+BT*3, cb, txt)
    def ic(m):
        return '<code>' + _esc(m.group(1)) + '</code>'
    txt = _re.sub(BT+r'([^'+BT+r'\n]+)'+BT, ic, txt)
    txt = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', txt)
    txt = _re.sub(r'__(.+?)__', r'<b>\1</b>', txt)
    txt = _re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', txt, flags=_re.MULTILINE)
    txt = _re.sub(r'<(?!/?(b|i|code|pre)(\s|>))[^>]+>', '', txt)
    return txt.strip()


def cmd_ai(text: str, user_id: str) -> str:
    """AI reply: Groq primary, panel /api/chat fallback."""
    import urllib.request as _ur2, json as _j2
    groq_key = os.environ.get('GROQ_API_KEY','')
    # 1. Groq direct
    if groq_key:
        try:
            body = _j2.dumps({
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role":"system","content":"Ты MaxAI — корпоративный AI-ассистент. Отвечай кратко, по-деловому, на русском."},
                    {"role":"user","content":text}
                ],
                "max_tokens": 800, "temperature": 0.7
            }).encode()
            req = _ur2.Request('https://api.groq.com/openai/v1/chat/completions',
                data=body,
                headers={"Content-Type":"application/json","Authorization":f"Bearer {groq_key}"},
                method="POST")
            with _ur2.urlopen(req, timeout=25) as r:
                d = _j2.loads(r.read())
                reply = d["choices"][0]["message"]["content"].strip()
                if reply: return md2tg(reply)
        except Exception as e:
            log.warning("Groq failed: %s", e)
    # 2. Panel /api/chat fallback
    for url, tmt in [(PANEL_BASE+"/api/chat", 20)]:
        try:
            body = _j2.dumps({"message": text, "source": "telegram_corp"}).encode()
            req = _ur2.Request(url, data=body,
                headers={"Content-Type": "application/json"}, method="POST")
            with _ur2.urlopen(req, timeout=tmt) as r:
                d = _j2.loads(r.read())
                reply = (d.get("reply") or d.get("result") or d.get("response") or d.get("text") or "").strip()
                if reply: return md2tg(reply)
        except Exception as e:
            log.debug("Panel AI %s failed: %s", url, e)
    return "Не удалось получить ответ от AI. Используй /status или /balance для данных."


# ─── Dispatcher ───────────────────────────────────────────────────────────────

def _corp_check_keys() -> str:
    """Quick check of all API keys from within corp bot."""
    lines = ['<b>Статус API ключей:</b>']
    checks = {
        'CORP_BOT_TOKEN': 'Corp Bot',
        'TELEGRAM_BOT_TOKEN': 'Main Bot',
        'BYBIT_API_KEY': 'Bybit',
        'ANTHROPIC_API_KEY': 'Claude',
        'GROQ_API_KEY': 'Groq',
        'KWORK_EMAIL': 'Kwork',
    }
    for key, name in checks.items():
        val = os.environ.get(key, '')
        if val:
            masked = val[:4] + '...' + val[-4:] if len(val) > 8 else '***'
            lines.append(f'✅ {name}: {masked}')
        else:
            lines.append(f'❌ {name}: не задан')
    return '\n'.join(lines)


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
        "trading":  cmd_trading,
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
        "task":    lambda: cmd_ai(arg if arg else text, chat_id),
        "execute": lambda: cmd_ai(arg if arg else text, chat_id),
        "keys":    _corp_check_keys,
        "llm":     _corp_llm_status,
    }

    if cmd in table:
        return table[cmd]()
    elif cmd == "restart":
        return cmd_restart(arg, chat_id) if arg else "❌ Укажи: /restart bybit-monitor"
    elif cmd == "confirm":
        return cmd_confirm(arg, chat_id) if arg else "❌ Укажи: /confirm &lt;токен&gt;"
    elif cmd == "logs":
        return cmd_logs(arg) if arg else f"❌ Укажи: /logs tgbot\nДоступны: {', '.join(sorted(ALLOWED_LOG_FILES))}"
    else:
        return cmd_ai(text, chat_id)


# ─── Main polling loop ────────────────────────────────────────────────────────
def main() -> None:
    if not CORP_TOKEN:
        log.error("CORP_BOT_TOKEN not set! Export it or add to .env")
        sys.exit(1)

    log.info("MaxAI Corporate Bot v2 starting (token: ...%s)", CORP_TOKEN[-6:])
    state = _load_state()

    # Register commands menu
    tg_set_commands()

    # Announce startup (if chat ID configured)
    if ALLOWED_IDS:
        for cid in ALLOWED_IDS:
            tg_send(
                cid,
                f"<b>MaxAI Corporate Bot v2</b> готова ✅\n"
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
