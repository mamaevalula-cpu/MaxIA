#!/usr/bin/env python3
"""Navigate Kwork seller page to find correct gig management URLs"""
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

    # Track all navigation
    navigations = []
    page.on("response", lambda r: navigations.append((r.status, r.url[:80])) if "kwork.ru" in r.url else None)

    try:
        tg("Loading seller page...")
        page.goto("https://kwork.ru/seller", timeout=30000, wait_until="networkidle")
        time.sleep(5)
        page.screenshot(path="/root/my_personal_ai/data/kw_nav1.png")

        # Get ALL hrefs from the page
        all_hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        kwork_hrefs = list(set([h for h in all_hrefs if "kwork.ru" in h]))
        print(f"Found {len(kwork_hrefs)} kwork links")

        # Find "create" or "add" related links
        create_links = [h for h in kwork_hrefs if any(x in h for x in ["add","creat","new","создать","новую","доб"])]
        print("Create links:", create_links[:5])

        # Find "edit" related links
        edit_links = [h for h in kwork_hrefs if any(x in h for x in ["edit","редак","изменить"])]
        print("Edit links:", edit_links[:5])

        # Print all unique path patterns
        paths = list(set([h.replace("https://kwork.ru","") for h in kwork_hrefs]))[:30]
        print("Paths:", paths[:20])
        tg(f"Links found: {len(kwork_hrefs)} total, {len(edit_links)} edit, {len(create_links)} create")

        # Find "Create kwork" button
        btns = page.query_selector_all("button, a.btn, a.button, [class*='btn'][class*='create']")
        for btn in btns[:20]:
            try:
                txt = btn.inner_text()
                href = btn.get_attribute("href") or ""
                if any(x in txt.lower() for x in ["создать","добавить","новую","create","add"]):
                    print(f"Button: '{txt}' href={href}")
                    tg(f"Found create button: {txt[:30]} -> {href[:40]}")
            except: pass

        # Click "create new kwork" if found
        create_btn = None
        for sel in [
            "a:has-text('Создать кворк')",
            "a:has-text('Добавить кворк')",
            "a:has-text('Новый кворк')",
            "button:has-text('Создать')",
            "[class*='create']:not([class*='account'])",
        ]:
            try:
                btn = page.locator(sel).first
                btn.wait_for(timeout=2000, state="visible")
                href = btn.get_attribute("href") or ""
                txt = btn.inner_text()
                print(f"Found: {sel} -> {txt[:30]} {href[:40]}")
                if href:
                    tg(f"Kwork gig creation URL: {href}")
                    create_btn = btn
                    break
            except: pass

        if create_btn:
            create_btn.click()
            time.sleep(5)
            page.screenshot(path="/root/my_personal_ai/data/kw_nav2_create.png")
            tg(f"Opened: {page.url[:60]}")

        # Show page structure
        page_text = page.inner_text("body")[:1000]
        print("Page text sample:", page_text[:500])

    except Exception as e:
        print("Error:", str(e)[:200])
        tg("Error: " + str(e)[:100])

    ctx.close()
    browser.close()
print("Done")
