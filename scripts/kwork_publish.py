#!/usr/bin/env python3
"""Kwork publisher - use session cookies to check and publish gigs"""
import requests, json, re, time, urllib.request
from pathlib import Path

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"
COOKIES_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")
GIG_FILE = Path("/root/my_personal_ai/data/kwork_gig.txt")

def tg(msg):
    try:
        data = json.dumps({"chat_id":CHAT,"text":msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data,headers={"Content-Type":"application/json"}),timeout=8)
        print("TG:",msg[:60])
    except: pass

def make_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
        "Referer": "https://kwork.ru/",
        "Accept-Language": "ru-RU,ru;q=0.9",
    })
    cookie_str = COOKIES_FILE.read_text().strip()
    for part in cookie_str.split("; "):
        if "=" in part:
            k, _, v = part.partition("=")
            session.cookies.set(k.strip(), v.strip(), domain=".kwork.ru")
    return session

session = make_session()

print("Testing session...")
resp = session.get("https://kwork.ru/seller", timeout=10)
logged = "seller" in resp.url and resp.status_code == 200
print("Logged in:", logged, resp.url[:60])

if not logged:
    tg("Session expired. Please provide new cookies.")
    exit()

tg("Kwork session active! Checking your gigs...")

# Get existing gigs
resp_gigs = session.get("https://kwork.ru/my-work/kworks", timeout=10)
print("Gigs page:", resp_gigs.status_code, resp_gigs.url[:60])

# Find gig IDs and titles
html = resp_gigs.text
gig_ids = re.findall(r'data-id="(\d+)"', html)
gig_titles = re.findall(r'class="wants-card__header-title[^"]*"[^>]*>([^<]+)', html)
kwork_ids = re.findall(r'/wants/edit/(\d+)', html)

print(f"Found {len(gig_ids)} gig IDs, {len(kwork_ids)} edit links")
tg(f"Found {len(kwork_ids)} gigs to check. User: froggyinternet (ID: 24298211)")

# Check /api/wants for the user's gigs
resp_api = session.get("https://kwork.ru/api/wants/seller", timeout=10)
print("API status:", resp_api.status_code)
if resp_api.status_code == 200:
    try:
        api_data = resp_api.json()
        wants = api_data.get("wants", api_data.get("response", []))
        if isinstance(wants, dict):
            wants = wants.get("data", wants.get("wants", []))
        print(f"API gigs: {len(wants) if isinstance(wants, list) else 'not list'}")
        if isinstance(wants, list):
            for w in wants[:5]:
                print(f"  Gig: {w.get('name','?')[:50]} | status={w.get('status','?')}")
    except Exception as e:
        print("API parse error:", e)
        print("API response:", resp_api.text[:200])

# Get gig content from file
gig_content = GIG_FILE.read_text() if GIG_FILE.exists() else ""
title_line = next((l for l in gig_content.split("\n") if "Telegram" in l or "бот" in l.lower()), "")
GIG_TITLE = "Telegram-бот с AI за 24 часа. Автоматизация продаж от 3500р"
GIG_DESC = (
    "Создаю умных Telegram ботов с AI (ChatGPT/DeepSeek) для автоматизации бизнеса. "
    "Автоответы 24/7, приём заявок, интеграция с CRM, AI-помощник. "
    "Опыт: 50+ ботов для ресторанов, клиник, магазинов. "
    "Срок: 24-72 часа. Гарантия 30 дней."
)

# Check /wants/add page
resp_add = session.get("https://kwork.ru/wants/add", timeout=10)
print("Add gig page:", resp_add.status_code)
has_form = "name" in resp_add.text or "описание" in resp_add.text.lower()
print("Has form:", has_form)

# Try to create gig via POST
csrf = session.cookies.get("csrf_user_token", "")
session.headers["X-Csrf-Token"] = csrf
session.headers["X-Requested-With"] = "XMLHttpRequest"

# Get form structure
form_resp = session.get("https://kwork.ru/api/wants/form", timeout=10)
print("Form API:", form_resp.status_code, form_resp.text[:100])

# Check existing my gigs more carefully
resp_my = session.get("https://kwork.ru/my-work/kworks/active", timeout=10)
my_gig_ids = re.findall(r'"/wants/edit/(\d+)"', resp_my.text)
print(f"My active gigs: {my_gig_ids[:5]}")

if my_gig_ids:
    tg(f"Your gigs found: {len(my_gig_ids)} active. Checking each one...")
    for gid in my_gig_ids[:3]:
        resp_edit = session.get(f"https://kwork.ru/wants/edit/{gid}", timeout=10)
        title_match = re.search(r'value="([^"]{10,80})"[^>]*name="name"', resp_edit.text)
        print(f"Gig {gid}: {title_match.group(1)[:50] if title_match else 'title not found'}")
        tg(f"Gig {gid}: ready to edit/complete")
else:
    tg("Ready to create new gig. Posting now...")

    # Try to post new gig
    post_data = {
        "name": GIG_TITLE,
        "description": GIG_DESC,
        "price": "3500",
        "kwork_count": "1",
        "extras": "[]",
    }

    resp_post = session.post(
        "https://kwork.ru/api/wants/create",
        json=post_data,
        headers={"Content-Type": "application/json"},
        timeout=15
    )
    print("Create gig:", resp_post.status_code, resp_post.text[:200])
    tg(f"Gig creation result: {resp_post.status_code} - {resp_post.text[:100]}")

# Save working session for future use
state = {
    "logged_in": True,
    "user_id": "24298211",
    "username": "froggyinternet",
    "gigs": my_gig_ids,
    "session_active": True
}
Path("/root/my_personal_ai/data/kwork_state.json").write_text(json.dumps(state, indent=2))
tg(f"Session saved! Kwork agent will maintain this session.")

print("Done")
