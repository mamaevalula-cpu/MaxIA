#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Telegram Bot - 24/7
Sends/receives messages, connects to AI via localhost:8090/api/chat
Single instance enforced by systemd (Restart=always, one process)
"""
import json
import logging
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = Path("/root/my_personal_ai")

def load_env():
    env = {}
    try:
        for line in (BASE / ".env").read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return env

ENV = load_env()
BOT_TOKEN = ENV.get("TELEGRAM_BOT_TOKEN", "")
OWNER_ID  = int(ENV.get("TELEGRAM_CHAT_ID", "1985320458"))
TG_API    = f"https://api.telegram.org/bot{BOT_TOKEN}"

# stdout only — systemd redirects to log file (no duplicate entries)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("tg")


# ── Telegram helpers ──────────────────────────────────────────────────────────

def tg(method, payload=None, timeout=15):
    data = json.dumps(payload or {}).encode() if payload else None
    req  = urllib.request.Request(
        f"{TG_API}/{method}", data=data,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        log.error("TG %s HTTP %s: %s", method, e.code, body[:150])
        return {"ok": False, "error": body}
    except Exception as e:
        log.error("TG %s: %s", method, e)
        return {"ok": False, "error": str(e)}


def send(chat_id, text):
    """Send plain text — no parse_mode to avoid HTML errors."""
    return tg("sendMessage", {"chat_id": chat_id, "text": text[:4096]})


def send_html(chat_id, text):
    """Send HTML; fall back to plain on parse error."""
    r = tg("sendMessage", {"chat_id": chat_id, "text": text[:4096], "parse_mode": "HTML"})
    if not r.get("ok") and ("parse" in str(r.get("error","")) or "unsupported" in str(r.get("error",""))):
        r = tg("sendMessage", {"chat_id": chat_id, "text": text[:4096]})
    return r


def typing(chat_id):
    tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})


def get_updates(offset=None, timeout=30):
    p = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset:
        p["offset"] = offset
    return tg("getUpdates", p, timeout=timeout + 10)


# ── AI helper ─────────────────────────────────────────────────────────────────

def ask_ai(text, user_id=None):
    """Query AI via panel API. Falls back to direct LLM call."""
    try:
        d = json.dumps({
            "message": text,
            "user_id": str(user_id or OWNER_ID),
            "session_id": f"tg_{user_id or OWNER_ID}",
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8090/api/chat", data=d,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            res = json.loads(r.read())
            return (res.get("response") or res.get("reply") or res.get("message") or "").strip()
    except Exception as e:
        log.warning("Panel API error: %s — fallback", e)
        return ask_direct(text)


def ask_direct(text):
    """Direct DeepSeek/OpenAI fallback."""
    key = ENV.get("DEEPSEEK_API_KEY") or ENV.get("OPENAI_API_KEY", "")
    if not key:
        return "AI временно недоступен. Панель: http://77.90.2.171"
    url   = "https://api.deepseek.com/v1/chat/completions" if ENV.get("DEEPSEEK_API_KEY") else "https://api.openai.com/v1/chat/completions"
    model = "deepseek-chat" if ENV.get("DEEPSEEK_API_KEY") else "gpt-3.5-turbo"
    try:
        d = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "Ты персональный AI-ассистент. Отвечай кратко по делу на русском."},
                {"role": "user",   "content": text},
            ],
            "max_tokens": 800,
        }).encode()
        req = urllib.request.Request(url, data=d, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        })
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error("Direct AI error: %s", e)
        return "AI временно недоступен. Панель: http://77.90.2.171"


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_start(chat_id, name=""):
    send_html(chat_id,
        f"Привет, {name}!\n\n"
        "<b>Я твой персональный AI-ассистент.</b>\n\n"
        "/status - статус системы\n"
        "/subscribe - подписки и оплата\n"
        "/balance - баланс Bybit\n"
        "/help - помощь\n\n"
        "Или напиши любое сообщение - отвечу!")


def cmd_status(chat_id):
    try:
        req = urllib.request.Request("http://localhost:8090/api/status",
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        agents = d.get("agents_count", d.get("agents", "?"))
        send_html(chat_id,
            "<b>Система работает</b>\n\n"
            f"Агентов: {agents}\n"
            "Telegram бот: 24/7\n"
            "Панель: http://77.90.2.171")
    except Exception:
        send(chat_id, "Система работает\nТelegram: OK\nПанель: http://77.90.2.171")


def cmd_subscribe(chat_id):
    try:
        links = json.loads((BASE / "data" / "payment_links.json").read_text())
        lines = ["<b>Подписки Crypto Signals</b>\n"]
        for lnk in links:
            lines.append(f"<b>${lnk['amount']} USDT/мес</b> - {lnk['desc']}")
            lines.append(f'<a href="{lnk["link"]}">Оплатить через @CryptoBot</a>\n')
        lines.append("После оплаты доступ активируется автоматически.")
        send_html(chat_id, "\n".join(lines))
    except Exception:
        send(chat_id,
             "Подписки:\n"
             "$9/мес Basic: https://t.me/CryptoBot?start=IVFJXrKVDgBs\n"
             "$29/мес Pro: https://t.me/CryptoBot?start=IVVAA3ZMFcHv\n"
             "$49/мес AI: https://t.me/CryptoBot?start=IVGAU7NMlgxg")


def cmd_help(chat_id):
    send_html(chat_id,
        "<b>Команды:</b>\n"
        "/start - главное меню\n"
        "/status - статус AI системы\n"
        "/subscribe - ссылки оплаты\n"
        "/balance - баланс Bybit\n\n"
        "Напиши любое сообщение - AI ответит!\n"
        "Панель: http://77.90.2.171")


def cmd_balance(chat_id):
    try:
        import hmac, hashlib
        key    = ENV.get("BYBIT_API_KEY", "")
        secret = ENV.get("BYBIT_API_SECRET", "")
        if not key:
            send(chat_id, "Bybit API ключи не настроены"); return
        ts     = str(int(time.time() * 1000))
        params = "accountType=UNIFIED"
        sig    = hmac.new(secret.encode(), (ts + key + "5000" + params).encode(), hashlib.sha256).hexdigest()
        req    = urllib.request.Request(
            f"https://api.bybit.com/v5/account/wallet-balance?{params}",
            headers={"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts,
                     "X-BAPI-SIGN": sig, "X-BAPI-RECV-WINDOW": "5000"})
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        eq = float(d["result"]["list"][0].get("totalEquity", 0))
        wb = float(d["result"]["list"][0].get("totalWalletBalance", 0))
        send_html(chat_id,
            f"<b>Bybit Баланс</b>\n"
            f"Equity: <b>${eq:.2f} USDT</b>\n"
            f"Wallet: ${wb:.2f} USDT")
    except Exception as e:
        send(chat_id, f"Ошибка баланса: {e}")


# ── Message handler ───────────────────────────────────────────────────────────

def handle(update):
    msg = update.get("message")
    if not msg:
        return
    chat_id  = msg["chat"]["id"]
    user_id  = msg.get("from", {}).get("id", chat_id)
    name     = msg.get("from", {}).get("first_name", "")
    text     = msg.get("text", "").strip()
    if not text:
        return
    log.info("MSG %s: %s", user_id, text[:80])
    if   text.startswith("/start"):     cmd_start(chat_id, name)
    elif text.startswith("/status"):    cmd_status(chat_id)
    elif text.startswith("/subscribe"): cmd_subscribe(chat_id)
    elif text.startswith("/help"):      cmd_help(chat_id)
    elif text.startswith("/balance"):   cmd_balance(chat_id)
    else:
        # Strip leading slash if unknown command
        query = text.lstrip("/").strip() if text.startswith("/") else text
        typing(chat_id)
        reply = ask_ai(query, user_id)
        if reply:
            r = send(chat_id, reply)
            if r.get("ok"):
                log.info("SENT to %s: %s...", chat_id, reply[:60])
            else:
                log.error("SEND failed: %s", r.get("error","")[:100])
        else:
            send(chat_id, "Не получил ответ от AI. Попробуй ещё раз.")


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN missing in .env"); sys.exit(1)

    # Clear webhook & pending updates
    tg("deleteWebhook", {"drop_pending_updates": True})
    time.sleep(1)

    me = tg("getMe")
    if not me.get("ok"):
        log.error("getMe failed: %s", me); sys.exit(1)
    bot_name = me["result"].get("username", "?")
    log.info("Connected: @%s", bot_name)

    # Notify owner
    send(OWNER_ID, f"@{bot_name} запущен — работает 24/7\nПанель: http://77.90.2.171")

    offset     = None
    fail_count = 0
    log.info("Polling started")

    while True:
        try:
            res = get_updates(offset=offset, timeout=30)

            if not res.get("ok"):
                err = str(res.get("error", ""))
                if "Conflict" in err:
                    log.warning("Conflict — waiting 30s")
                    time.sleep(30)
                    tg("deleteWebhook", {"drop_pending_updates": True})
                    time.sleep(2)
                    fail_count = 0
                    continue
                fail_count += 1
                time.sleep(min(fail_count * 5, 60))
                continue

            fail_count = 0
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    handle(upd)
                except Exception as e:
                    log.error("handle error: %s", e)

        except KeyboardInterrupt:
            log.info("Stopped"); break
        except Exception as e:
            fail_count += 1
            wait = min(fail_count * 10, 120)
            log.error("Loop error: %s — retry in %ds", e, wait)
            time.sleep(wait)


if __name__ == "__main__":
    main()
