#!/usr/bin/env python3
"""Watchdog - restarts failed services automatically"""
import subprocess, time, json, urllib.request as ur, os

SERVICES = ['personal-ai', 'bybit-monitor', 'defai-agent']
ENDPOINTS = {
    'personal-ai': 'http://localhost:8090/api/status',
    'bybit-monitor': 'http://localhost:8090/api/status',
    'defai-agent': None,  # Check via systemctl only
}

def _get_token():
    try:
        env_path = '/root/my_personal_ai/.env'
        with open(env_path) as f:
            for line in f:
                if line.startswith('TELEGRAM_BOT_TOKEN='):
                    return line.split('=', 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.getenv('TELEGRAM_BOT_TOKEN', '')

TOKEN = _get_token()
CHAT_ID = '1985320458'

def notify(msg):
    try:
        data = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}).encode()
        req = ur.Request(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with ur.urlopen(req, timeout=5):
            pass
    except Exception as e:
        print(f"Notify failed: {e}")

def check_and_restart():
    for svc in SERVICES:
        result = subprocess.run(['systemctl', 'is-active', svc], capture_output=True, text=True)
        if result.stdout.strip() != 'active':
            print(f"[watchdog] {svc} is {result.stdout.strip()!r} — restarting...")
            subprocess.run(['systemctl', 'restart', svc])
            time.sleep(5)
            result2 = subprocess.run(['systemctl', 'is-active', svc], capture_output=True, text=True)
            status = result2.stdout.strip()
            notify(f"⚠️ <b>Watchdog</b>: {svc} was stopped → restarted → {status}")
            print(f"Restarted {svc}: {status}")
        else:
            print(f"{svc}: OK")

if __name__ == '__main__':
    check_and_restart()
