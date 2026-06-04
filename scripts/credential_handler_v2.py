#!/usr/bin/env python3
# credential_handler_v2.py — Universal key receiver via Telegram
# Handles ANY API key sent to corp bot in any format
import json, re, time, urllib.request, subprocess, os
from pathlib import Path

import os as _chv2os
TOKEN = _chv2os.environ.get("TELEGRAM_BOT_TOKEN", "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio")
CHAT  = "1985320458"
ENV   = Path("/root/my_personal_ai/.env")
OFFSET_FILE = Path("/root/my_personal_ai/data/cred_v2_offset.txt")

KEY_DETECT = [
    (r"gsk_[A-Za-z0-9]{40,}",             "GROQ_API_KEY"),
    (r"sk-ant-api[A-Za-z0-9\-_]{50,}",   "ANTHROPIC_API_KEY"),
    (r"sk-or-v1-[A-Za-z0-9]{50,}",        "OPENROUTER_API_KEY"),
    (r"hf_[A-Za-z0-9]{30,}",              "HUGGINGFACE_TOKEN"),
]

SVC_MAP = {
    "GROQ_API_KEY":          "maxai-tgbot",
    "WILDBERRIES_API_KEY":   "maxai-core",
    "PST_API_KEY":           "maxai-core",
    "PYNTAPAY_API_KEY":      "maxai-core",
}

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg[:4000]}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data, headers={"Content-Type": "application/json"}), timeout=8)
    except: pass

def save_key(name, value):
    src = ENV.read_text()
    if (name+"=") in src:
        src = re.sub(rf"^{name}=.*$", name+"="+value, src, flags=re.MULTILINE)
    else:
        src = src.rstrip()+chr(10)+name+"="+value+chr(10)
    ENV.write_text(src)
    os.environ[name] = value
    print(f"SAVED: {name}={value[:8]}***")
    svc = SVC_MAP.get(name)
    if svc:
        subprocess.Popen(["systemctl","restart",svc], start_new_session=True)

def parse_and_save(text):
    text = text.strip(); saved = []
    # Explicit: NAME=value or /setkey NAME=value
    m = re.search(r"(?:/setkey\s+)?([A-Z][A-Z0-9_]{3,})\s*=\s*(\S{8,})", text)
    if m:
        save_key(m.group(1), m.group(2))
        saved.append(m.group(1)+"="+m.group(2)[:8]+"***")
    # Auto-detect key format
    if not saved:
        for pattern, key_name in KEY_DETECT:
            m2 = re.search(pattern, text)
            if m2:
                save_key(key_name, m2.group(0))
                saved.append(key_name+"="+m2.group(0)[:8]+"***")
                break
    # WB key (long base64-like string)
    if not saved:
        m3 = re.search(r"[A-Za-z0-9.]{100,}", text)
        if m3 and ("wildberries" in text.lower() or "wb" in text.lower() or "WILDBERRIES" in text):
            save_key("WILDBERRIES_API_KEY", m3.group(0))
            saved.append("WILDBERRIES_API_KEY")
    # Legacy kwork password
    m4 = re.search(r"(?:kwork.{0,15}pass(?:word)?)[:\s]+(\S+)", text, re.I)
    if m4: save_key("KWORK_PASSWORD", m4.group(1)); saved.append("KWORK_PASSWORD")
    return saved

def main():
    # NOTE: getUpdates polling removed from this script to prevent 409 conflict
    # with corp_tgbot.py. Credential detection is now handled by corp_tgbot.py directly.
    # This script remains for manual key injection via command line:
    # python3 credential_handler_v2.py "GROQ_API_KEY=gsk_xxx"
    import sys as _sys2
    if len(_sys2.argv) > 1:
        text = " ".join(_sys2.argv[1:])
        saved = parse_and_save(text)
        if saved:
            tg("Keys saved:" + chr(10) + chr(10).join(saved) + chr(10) + chr(10) + "Validating...")
            subprocess.Popen(["/root/venv/bin/python3",
                              "/root/my_personal_ai/scripts/maxai_key_orchestrator.py"],
                             start_new_session=True)
        else:
            print("No keys recognized in input:", text[:80])
    else:
        print("credential_handler_v2: passive mode (no getUpdates). Use: script.py KEY=value")

if __name__ == "__main__":
    main()
