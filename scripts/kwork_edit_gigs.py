#!/usr/bin/env python3
"""Edit existing Kwork gigs at /manage_kworks"""
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
        tg("Opening /manage_kworks to edit your gigs...")
        page.goto("https://kwork.ru/manage_kworks", timeout=30000, wait_until="networkidle")
        time.sleep(6)
        page.screenshot(path="/root/my_personal_ai/data/kw_manage.png")

        url = page.url
        print("URL:", url[:60])
        tg(f"manage_kworks loaded: {page.title()[:40]}")

        # Get all links on this page
        all_links = page.eval_on_selector_all("a[href]", "els => els.map(e => ({href:e.href, text:e.innerText.trim().substring(0,50)}))")

        # Find gig-related links
        gig_links = [l for l in all_links if any(x in l["href"] for x in ["/wants/", "/edit/", "kwork"])]
        edit_links = [l for l in all_links if "edit" in l["href"].lower()]
        print(f"Total links: {len(all_links)}")
        print(f"Gig links: {len(gig_links)}")
        print(f"Edit links: {len(edit_links)}")

        for l in gig_links[:10]:
            print(f"  {l['text'][:40]} -> {l['href'][:60]}")
        for l in edit_links[:5]:
            print(f"  EDIT: {l['text'][:40]} -> {l['href'][:60]}")

        # Find "edit" or "изменить" buttons
        edit_btns = page.query_selector_all("a[href*='edit'], a[href*='kwork/edit'], button:has-text('Изменить'), a:has-text('Редактировать')")
        print(f"Edit buttons: {len(edit_btns)}")

        for btn in edit_btns[:5]:
            href = btn.get_attribute("href") or ""
            txt = btn.inner_text()
            if href and "kwork" in href.lower() or "edit" in href.lower():
                print(f"  Found: '{txt}' -> {href}")
                tg(f"Edit link: {href[:50]}")

        # Get page text to see structure
        body_text = page.inner_text("body")
        lines = [l.strip() for l in body_text.split("\n") if l.strip() and len(l.strip()) > 5]
        print("Page lines (first 30):")
        for l in lines[:30]:
            print(f"  {l[:80]}")

        # Look for the gig cards/items
        gig_cards = page.query_selector_all("[class*='kwork'], [class*='wants'], [class*='gig']")
        print(f"Gig cards: {len(gig_cards)}")
        for card in gig_cards[:5]:
            try:
                txt = card.inner_text()[:80]
                print(f"  Card: {txt}")
            except: pass

        # Click on one of the gig edit links if found
        # Check for "Создам прибыльного ИИ-бота" gig
        bybit_gig = page.locator("text=Bybit, text=ИИ-бот, [title*='Bybit']").first
        try:
            bybit_gig.wait_for(timeout=3000, state="visible")
            bybit_gig.click()
            time.sleep(4)
            print("Bybit gig clicked, URL:", page.url[:60])
        except: pass

        tg("Screenshots saved. Found gig management page.")

    except Exception as e:
        print("Error:", str(e)[:200])
        tg("Error: " + str(e)[:100])

    ctx.close()
    browser.close()
print("Done")
