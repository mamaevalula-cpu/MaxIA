#!/usr/bin/env python3
"""Use Playwright with real session cookies to manage Kwork gigs"""
import json, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"
COOKIES_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")

def tg(msg):
    try:
        data = json.dumps({"chat_id":CHAT,"text":msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data,headers={"Content-Type":"application/json"}),timeout=8)
        print("TG:",msg[:60])
    except: pass

# Parse cookies
cookie_str = COOKIES_FILE.read_text().strip()
cookies_list = []
for part in cookie_str.split("; "):
    if "=" in part:
        k, _, v = part.partition("=")
        cookies_list.append({
            "name": k.strip(),
            "value": v.strip(),
            "domain": ".kwork.ru",
            "path": "/",
        })

print(f"Loaded {len(cookies_list)} cookies")
tg(f"Starting Kwork with your session ({len(cookies_list)} cookies)...")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--ozone-platform=headless"]
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120",
        viewport={"width":1280,"height":900}
    )

    # Set cookies BEFORE navigating
    ctx.add_cookies(cookies_list)
    print("Cookies set in browser")

    page = ctx.new_page()

    try:
        # Navigate to seller page
        page.goto("https://kwork.ru/seller", timeout=30000, wait_until="networkidle")
        time.sleep(3)

        url = page.url
        title = page.title()
        print(f"URL: {url[:60]}")
        print(f"Title: {title[:50]}")

        logged_in = "seller" in url
        tg(f"Kwork {'logged in!' if logged_in else 'NOT logged in'} URL: {url[:50]}")

        if logged_in:
            page.screenshot(path="/root/my_personal_ai/data/kwork_seller.png")

            # Wait for Vue.js to render
            page.wait_for_selector("[class*='wants-card'], [class*='kwork-card'], .seller-kworks", timeout=10000)
            time.sleep(2)

            # Get gig info from rendered page
            gigs = page.query_selector_all("[class*='wants-card']")
            print(f"Gigs found: {len(gigs)}")
            tg(f"Your Kwork gigs: {len(gigs)} found!")

            for gig in gigs[:5]:
                try:
                    title_el = gig.query_selector("[class*='title'], h2, h3")
                    title_text = title_el.inner_text() if title_el else "?"
                    edit_btn = gig.query_selector("a[href*='edit']")
                    edit_url = edit_btn.get_attribute("href") if edit_btn else None
                    print(f"  Gig: {title_text[:50]} | Edit: {edit_url}")
                    tg(f"Gig: {title_text[:40]} | {edit_url or 'no edit link'}")
                except Exception as e:
                    print(f"  Gig read error: {e}")

            # Navigate to create new gig
            page.goto("https://kwork.ru/wants/add", timeout=20000, wait_until="domcontentloaded")
            time.sleep(3)
            add_url = page.url
            print(f"Add gig page: {add_url[:60]}")
            page.screenshot(path="/root/my_personal_ai/data/kwork_add.png")
            tg(f"Gig creation page: {page.title()[:40]}")

            # Check if we can fill the form
            form_fields = page.query_selector_all("input, textarea")
            print(f"Form fields: {len(form_fields)}")

            if len(form_fields) > 0:
                # Try to fill name field
                name_field = page.locator('input[name="name"], input[placeholder*="назван"]').first
                try:
                    name_field.fill("Telegram-bot s AI za 24 chasa ot 3500r")
                    tg("Gig title filled!")
                except: pass

                page.screenshot(path="/root/my_personal_ai/data/kwork_form.png")
                tg("Screenshots saved. Ready to publish!")
        else:
            tg("Not logged in. Session may have expired.")
            page.screenshot(path="/root/my_personal_ai/data/kwork_notlogged.png")

    except Exception as e:
        err = str(e)[:200]
        print(f"Error: {err}")
        tg(f"Error: {err[:100]}")
        try:
            page.screenshot(path="/root/my_personal_ai/data/kwork_error.png")
        except: pass

    ctx.close()
    browser.close()

print("Done")
