#!/usr/bin/env python3
"""Submit Kwork gig - optimized for Vue.js form"""
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
        print("TG:",msg[:60])
    except: pass

cookie_str = Path("/root/my_personal_ai/data/kwork_cookies.txt").read_text().strip()
cookies_list = [{"name":k.strip(),"value":v.strip(),"domain":".kwork.ru","path":"/"}
                for part in cookie_str.split("; ") if "=" in part
                for k,_,v in [part.partition("=")]]

GIG_TITLE = "Telegram bot s AI za 24 chasa. Avtomatizatsiya biznesa ot 3500r"
GIG_DESC = (
    "Sozdayu Telegram botov s AI dlya biznesa. "
    "Avtootvety 24/7, priem zayavok, integraciya s CRM. "
    "ChatGPT/DeepSeek pod klyuch. Srok 24-72 chasa. "
    "Opyt 50+ botov dlya restoranov, klinik, magazinov. "
    "Garantiya 30 dney."
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--ozone-platform=headless"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120", viewport={"width":1280,"height":900})
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    tg("Opening Kwork gig creation with your session...")

    try:
        page.goto("https://kwork.ru/wants/add", timeout=30000, wait_until="networkidle")
        time.sleep(5)

        url = page.url
        title = page.title()
        print(f"URL: {url[:70]}")
        print(f"Title: {title[:50]}")
        tg(f"Page: {title[:40]}")

        # Take screenshot to see what loaded
        page.screenshot(path="/root/my_personal_ai/data/kwork_add_loaded.png")

        # Check all form inputs
        all_inputs = page.query_selector_all("input, textarea, select")
        print(f"Form fields: {len(all_inputs)}")

        # Get input names/placeholders
        for inp in all_inputs[:10]:
            try:
                name = inp.get_attribute("name") or ""
                ph = inp.get_attribute("placeholder") or ""
                typ = inp.get_attribute("type") or "text"
                print(f"  input: name={name} placeholder={ph[:30]} type={typ}")
            except: pass

        # Fill form using Vue-compatible method
        # For Vue.js forms, we need to use fill() and then trigger input events

        # Try name field
        filled = []
        for sel in ['input[name="name"]', 'input[placeholder*="назван"]', 'input[placeholder*="name"]', '#name']:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=3000, state="visible")
                el.fill(GIG_TITLE)
                el.dispatch_event("input")
                el.dispatch_event("change")
                filled.append("name")
                print("Name filled!")
                break
            except: pass

        time.sleep(0.5)

        # Description
        for sel in ['textarea[name="description"]', 'textarea[placeholder*="описан"]', 'textarea']:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=3000, state="visible")
                el.fill(GIG_DESC)
                el.dispatch_event("input")
                filled.append("desc")
                print("Description filled!")
                break
            except: pass

        time.sleep(0.5)

        # Price
        for sel in ['input[name="price"]', 'input[placeholder*="цена"]', 'input[placeholder*="price"]']:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=3000, state="visible")
                el.fill("3500")
                el.dispatch_event("input")
                filled.append("price")
                print("Price filled!")
                break
            except: pass

        if filled:
            tg(f"Form filled: {filled}. Taking screenshot...")
            page.screenshot(path="/root/my_personal_ai/data/kwork_form_ready.png")

            # Try submit
            for btn_sel in [
                'button:has-text("Опубликовать")',
                'button:has-text("Создать")',
                'button:has-text("Сохранить")',
                'button[type="submit"]',
                'input[type="submit"]',
            ]:
                try:
                    btn = page.locator(btn_sel).first
                    btn.wait_for(timeout=3000, state="visible")
                    btn.click()
                    time.sleep(5)
                    new_url = page.url
                    print(f"After submit: {new_url[:60]}")
                    page.screenshot(path="/root/my_personal_ai/data/kwork_after_submit.png")

                    if "wants/add" not in new_url and "kwork.ru" in new_url:
                        tg(f"GIG PUBLISHED! New URL: {new_url[:50]}")
                    else:
                        tg(f"Submitted. URL: {new_url[:50]}")
                    break
                except: pass
        else:
            tg("Could not find form fields. Page might need more time to render.")
            # Get all page text
            body_text = page.inner_text("body")[:500]
            print("Page content:", body_text[:200])

        # Also check and edit existing gigs
        tg("Checking your existing gigs...")
        page.goto("https://kwork.ru/seller", timeout=30000, wait_until="networkidle")
        time.sleep(5)
        html = page.content()
        edit_links = re.findall(r'(/wants/edit/\d+)', html)
        print(f"Edit links found: {edit_links[:5]}")
        if edit_links:
            tg(f"Your existing gigs: {len(edit_links)}")
            for link in edit_links[:2]:
                page.goto("https://kwork.ru" + link, timeout=20000, wait_until="networkidle")
                time.sleep(4)
                page.screenshot(path=f"/root/my_personal_ai/data/kwork_existing_{link.split('/')[-1]}.png")
                tg(f"Checking gig: {page.title()[:30]}")

    except Exception as e:
        print(f"Error: {str(e)[:200]}")
        tg(f"Error: {str(e)[:100]}")
        try: page.screenshot(path="/root/my_personal_ai/data/kwork_final_err.png")
        except: pass

    ctx.close()
    browser.close()
print("Done")
