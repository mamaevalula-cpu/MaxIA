#!/usr/bin/env python3
"""Kwork Session Agent v4 - uses browser cookies, checks orders"""
import requests, json, time, re, urllib.request
from pathlib import Path

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"
COOKIES_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")
GIG_IDS = ["52124937", "52124410"]

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data, headers={"Content-Type":"application/json"}), timeout=8)
    except: pass

def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"
    for p in COOKIES_FILE.read_text().strip().split("; "):
        if "=" in p:
            k, _, v = p.partition("=")
            session.cookies.set(k.strip(), v.strip(), domain=".kwork.ru")
    return session

session = make_session()

# Check if session is valid
resp = session.get("https://kwork.ru/seller", timeout=10)
logged = "seller" in resp.url
print("Session:", "OK" if logged else "EXPIRED")

if not logged:
    tg("Kwork session expired. Please provide new cookies.")
    exit()

# Check for new orders
resp_orders = session.get("https://kwork.ru/manage_orders", timeout=10)
new_orders = re.findall(r"(new|pending|awaiting)", resp_orders.text.lower())
print("Orders signals:", len(new_orders))

# Check gig stats
for gid in GIG_IDS:
    resp_gig = session.get(f"https://kwork.ru/wants/{gid}", timeout=8)
    title_m = re.search(r"<title>([^<]+)</title>", resp_gig.text)
    print(f"Gig {gid}: {resp_gig.status_code} | {title_m.group(1)[:50] if title_m else '?'}")

# Save state
state = {
    "logged_in": logged,
    "gig_ids": GIG_IDS,
    "last_check": time.time(),
    "session_active": True
}
Path("/root/my_personal_ai/data/kwork_state.json").write_text(json.dumps(state, indent=2))
print("Done")
