#!/usr/bin/env python3
"""Manage Kwork gigs - find and edit existing ones"""
import json, time, urllib.request, re
from pathlib import Path
from playwright.sync_api import sync_playwright

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"

def tg(msg):
    try:
        data = json.dumps({"chat_id":CHAT,"text":msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data,headers={"Content-Type":"application/json"}),timeout=8)
    except: pass

cookie_str = Path("/root/my_personal_ai/data/kwork_cookies.txt").read_text().strip()
cookies_list = [{"name":k.strip(),"value":v.strip(),"domain":".kwork.ru","path":"/"}
                for part in cookie_str.split("; ") if "=" in part
                for k,_,v in [part.partition("=")]]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--ozone-platform=headless"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120", viewport={"width":1280,"height":900})
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    try:
        # Load seller page
        page.goto("https://kwork.ru/seller", timeout=30000, wait_until="networkidle")
        time.sleep(5)
        tg("Logged into Kwork! Finding gigs...")

        # Click "Посмотреть все" link for kworks
        try:
            see_all = page.locator("a:has-text('Посмотреть все'), a:has-text('посмотреть все')").first
            href = see_all.get_attribute("href")
            print("See all href:", href)
            if href:
                page.goto("https://kwork.ru" + href if not href.startswith("http") else href, timeout=20000, wait_until="networkidle")
                time.sleep(4)
                page.screenshot(path="/root/my_personal_ai/data/kw_gigs_list.png")
                tg(f"Gigs list: {page.title()[:40]} | {page.url[:50]}")
        except Exception as e:
            print("See all error:", e)

        # Get page content
        html = page.content()

        # Find gig IDs and links
        gig_numbers = re.findall(r'"id":(\d+),"name":"([^"]+)"', html)
        kwork_ids = re.findall(r'kwork\.ru/wants/(\d+)', html)
        edit_ids = re.findall(r'kwork\.ru/(?:wants/)?edit/(\d+)', html)

        print(f"Gig data: {gig_numbers[:3]}")
        print(f"Kwork IDs: {kwork_ids[:5]}")
        print(f"Edit IDs: {edit_ids[:5]}")

        # Try the "Кворки" nav item
        page.goto("https://kwork.ru/seller", timeout=20000, wait_until="networkidle")
        time.sleep(3)

        # Click Кворки in nav
        try:
            kwork_nav = page.locator("a:has-text('Кворки')").first
            kwork_href = kwork_nav.get_attribute("href")
            print("Kworki nav href:", kwork_href)
            kwork_nav.click()
            time.sleep(4)
            kworks_url = page.url
            print("After click:", kworks_url[:60])
            page.screenshot(path="/root/my_personal_ai/data/kw_kworks_nav.png")
            tg(f"Кворки page: {kworks_url[:50]}")
        except Exception as e:
            print("Nav click:", e)

        # Now check the kworks section specifically
        page_text = page.inner_text("body")

        # Find gig titles
        lines = [l.strip() for l in page_text.split("\n") if l.strip()]
        gig_lines = [l for l in lines if any(x in l.lower() for x in ["ai-бот", "telegram-бот", "бот", "автоматиз", "telegram", "bot"])]
        print("Gig-related lines:", gig_lines[:5])
        tg(f"Found gigs: {gig_lines[:3]}")

        # Try to find and click edit button for existing gigs
        edit_btns = page.query_selector_all("a[href*='edit'], button:has-text('Изменить'), button:has-text('Редактировать')")
        print(f"Edit buttons: {len(edit_btns)}")
        for btn in edit_btns[:3]:
            href = btn.get_attribute("href") or ""
            txt = btn.inner_text()
            print(f"  Edit btn: '{txt}' -> {href}")
            if href:
                tg(f"Edit URL found: {href[:50]}")

        # Final screenshot
        page.screenshot(path="/root/my_personal_ai/data/kw_final_state.png")
        tg("Done! Check screenshots. Session is active and working.")

    except Exception as e:
        print("Error:", str(e)[:200])
        tg("Error: " + str(e)[:100])

    ctx.close()
    browser.close()
print("Done")
