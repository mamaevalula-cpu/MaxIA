#!/usr/bin/env python3
import json, time, urllib.request, re
from pathlib import Path

env = {}
for line in Path('/root/my_personal_ai/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        env[k.strip()] = v.strip()

TOKEN = env.get('CORP_BOT_TOKEN', '8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio')
CHAT = env.get('TELEGRAM_CHAT_ID', '1985320458')
COOKIES_FILE = Path('/root/my_personal_ai/data/kwork_cookies.txt')

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data, headers={"Content-Type":"application/json"}), timeout=8)
    except: pass

if not COOKIES_FILE.exists():
    tg("No Kwork cookies found. Run copy(document.cookie) on kwork.ru")
    exit()

cookies_str = COOKIES_FILE.read_text().strip()
tg("Testing Kwork session with your cookies...")

import requests
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120'})

# Parse and add cookies
for part in cookies_str.split(';'):
    part = part.strip()
    if '=' in part:
        name, _, val = part.partition('=')
        session.cookies.set(name.strip(), val.strip(), domain='.kwork.ru')

resp = session.get('https://kwork.ru/my-work/kworks', timeout=10)
logged_in = 'my-work' in resp.url and resp.status_code == 200
print("Logged in:", logged_in)

if logged_in:
    tg("Kwork session works! Checking gigs...")
    gigs = re.findall(r'kwork-id="(\d+)"', resp.text)
    tg("Found " + str(len(gigs)) + " gigs. Kwork agent is active!")
    # Save valid cookies for future use
    COOKIES_FILE.write_text(cookies_str)
    tg("Session saved. Kwork will work autonomously now!")
else:
    tg("Cookies expired. Please export new ones from kwork.ru")

