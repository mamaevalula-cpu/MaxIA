#!/usr/bin/env python3
"""Credential Handler - processes password updates from Telegram"""
import json, time, urllib.request, re, subprocess
from pathlib import Path

import os as _os
TOKEN = _os.environ.get("TELEGRAM_BOT_TOKEN", "8849616091:AAEReIChr8WS4cC1sdqOXrvFdEwf3syu8YM")
CHAT = "1985320458"
ENV = "/root/my_personal_ai/.env"
OFFSET_FILE = Path("/root/my_personal_ai/data/cred_tg_offset.txt")


def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data, headers={"Content-Type": "application/json"}), timeout=8)
    except Exception as e:
        print("TG err:", e)


def save_env(key, value):
    env_text = Path(ENV).read_text()
    lines = [l for l in env_text.splitlines() if not l.startswith(key+"=")]
    lines.append(key + "=" + value)
    Path(ENV).write_text("\n".join(lines) + "\n")
    print("Saved", key, "=", value[:6] + "***")


def handle(text):
    text = text.strip()

    # /setpass NewPassword or kwork password NewPassword
    m = re.search(r"(?:setpass|kwork.{0,15}pass(?:word)?)[:\s]+(\S+)", text, re.I)
    if m:
        pwd = m.group(1).strip()
        save_env("KWORK_PASSWORD", pwd)
        subprocess.Popen(["/root/venv/bin/python3",
                          "/root/my_personal_ai/scripts/kwork_autonomous_v3.py"],
                         start_new_session=True)
        return "Kwork password saved: " + pwd[:3] + "***. Kwork agent started!"

    # 2captcha key
    m2 = re.search(r"2captcha.{0,5}(?:key|KEY)[=:\s]+([A-Za-z0-9]{10,})", text, re.I)
    if m2:
        key = m2.group(1).strip()
        save_env("TWOCAPTCHA_KEY", key)
        return "2captcha key saved: " + key[:6] + "... Kwork will use it!"

    # kwork cookies/session
    m3 = re.search(r"kwork.{0,10}(?:session|cookie)[=:\s]+(.{20,})", text, re.I)
    if m3:
        cookies = m3.group(1).strip()
        Path("/root/my_personal_ai/data/kwork_cookies.txt").write_text(cookies)
        subprocess.Popen(["/root/venv/bin/python3",
                          "/root/my_personal_ai/scripts/kwork_with_cookies.py"],
                         start_new_session=True)
        return "Kwork session saved! Testing login..."

    return None


# NOTE: getUpdates removed — corp_tgbot.py handles incoming messages.
# This script only processes messages via command-line args.
import sys as _ch1sys
if len(_ch1sys.argv) > 1:
    text = " ".join(_ch1sys.argv[1:])
    result = handle(text)
    if result:
        tg(result)
else:
    print("credential_handler: passive mode (no getUpdates polling)")
