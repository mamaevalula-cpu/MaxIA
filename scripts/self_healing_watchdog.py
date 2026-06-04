#!/usr/bin/env python3
"""MaxAI Self-Healing Watchdog - runs every 2 minutes via cron"""
import subprocess, json, time, urllib.request, os, sys
from pathlib import Path

CORP_TOKEN = os.environ.get("CORP_BOT_TOKEN", "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "1985320458")
LOG = Path("/root/my_personal_ai/logs/self_healing.log")

def tg(msg):
    """Send Telegram alert."""
    try:
        url = f"https://api.telegram.org/bot{CORP_TOKEN}/sendMessage"
        data = json.dumps({"chat_id": CHAT_ID, "text": msg}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log(f"TG error: {e}")

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def check_service(name):
    try:
        out = subprocess.check_output(
            ["systemctl", "is-active", f"{name}.service"],
            text=True, timeout=5
        ).strip()
        return out == "active"
    except:
        return False

def restart_service(name):
    try:
        subprocess.run(["systemctl", "restart", f"{name}.service"], timeout=15, check=True)
        time.sleep(3)
        return check_service(name)
    except:
        return False

def check_http(url, expected_code=200, timeout=5):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == expected_code
    except:
        return False

# Services to monitor
SERVICES = [
    "personal-ai",       # Main panel
    "bybit-monitor",     # Trading bot
    "corp-tgbot",        # Corp Telegram bot
    "maxai-tgbot",       # Personal Telegram bot
    "nginx",             # Web server
    "maxai-core",        # Swarm engine
    "hyperion-engine",   # L3 management
    "panel-guardian",    # Self-healing (meta)
    # Grok Stack 2026 (добавлено 2026-05-31)
    "ollama",            # LLM inference :11434
    "grok-router",       # Smart router + memory :8088
    "grok-webui",        # OpenWebUI :3003
    "maxai-aaas",       # AaaS Revenue Engine
    "maxai-tgbot",      # Telegram Bot
    "maxai-core",      # Core API
]

ENDPOINTS = [
    ("http://127.0.0.1:8090/api/status", "Panel API"),
    ("http://127.0.0.1:8001/status", "Trading Bot"),
    ("http://127.0.0.1:4000/health", "Swarm Engine"),
    # Grok Stack
    ("http://127.0.0.1:8088/health", "Grok Router"),
    ("http://127.0.0.1:11434/api/tags", "Ollama"),
]

fixes = []

# Check services
for svc in SERVICES:
    if not check_service(svc):
        log(f"SERVICE DOWN: {svc} - restarting...")
        if restart_service(svc):
            fixes.append(f"✅ {svc} — перезапущен успешно")
            log(f"FIXED: {svc} restarted OK")
        else:
            fixes.append(f"❌ {svc} — НЕ ЗАПУСТИЛСЯ")
            log(f"FAILED: {svc} could not restart")

# Check HTTP endpoints
for url, name in ENDPOINTS:
    if not check_http(url):
        log(f"ENDPOINT DOWN: {name} ({url})")
        # Try to fix by restarting the service
        svc_map = {
            "Panel API": "personal-ai",
            "Trading Bot": "bybit-monitor",
            "Swarm Engine": "maxai-core"
        }
        svc = svc_map.get(name)
        if svc and not check_service(svc):
            if restart_service(svc):
                fixes.append(f"✅ {name} — восстановлен")
            else:
                fixes.append(f"❌ {name} — недоступен")

# Send alert only if something was fixed or broken
if fixes:
    msg = "🔧 MaxAI Self-Healing — обнаружены и исправлены проблемы:\n\n" + "\n".join(fixes)
    tg(msg)
    log(f"Alert sent: {len(fixes)} fixes")

if not fixes:
    log("All systems OK")
