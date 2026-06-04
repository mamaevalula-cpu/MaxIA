#!/usr/bin/env python3
"""Kwork with session - no timeouts, screenshots for verification"""
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

GIG_TITLE = "Telegram-bot s AI za 24 chasa ot 3500r"
GIG_DESC = "Sozdayu Telegram botov s AI dlya biznesa. Avtootvety, priem zayavok, CRM. Srok 24 chasa."

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--ozone-platform=headless"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120", viewport={"width":1280,"height":900})
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    try:
        # 1. Check seller page
        page.goto("https://kwork.ru/seller", timeout=30000, wait_until="domcontentloaded")
        time.sleep(5)
        page.screenshot(path="/root/my_personal_ai/data/kwork_s1.png")
        print("Seller page:", page.url[:60])

        # Get page HTML to find gigs
        html = page.content()
        gig_links = re.findall(r'href="(/wants/\d+[^"]*)"', html)
        print("Gig links:", gig_links[:5])

        # Look for edit buttons
        edit_links = re.findall(r'href="(/wants/edit/\d+)"', html)
        print("Edit links:", edit_links[:5])
        tg(f"Session works! Found {len(edit_links)} edit links")

        # 2. Navigate to gig creation
        page.goto("https://kwork.ru/wants/add", timeout=30000, wait_until="domcontentloaded")
        time.sleep(5)
        page.screenshot(path="/root/my_personal_ai/data/kwork_s2.png")
        print("Add page:", page.url[:60], page.title()[:40])

        add_html = page.content()
        has_form = any(x in add_html.lower() for x in ["name", "description", "price", "форм"])
        print("Has form:", has_form)

        if "wants/add" in page.url or has_form:
            # Fill form fields
            try:
                # Name field
                name = page.locator("input[name='name'], input[placeholder*='назван']").first
                name.fill(GIG_TITLE)
                time.sleep(0.3)
                tg("Title filled!")
            except Exception as e:
                print("Name field:", e)

            try:
                desc = page.locator("textarea[name='description'], textarea").first
                desc.fill(GIG_DESC)
                time.sleep(0.3)
                tg("Description filled!")
            except Exception as e:
                print("Desc field:", e)

            try:
                price = page.locator("input[name='price'], input[placeholder*='цен']").first
                price.fill("3500")
                tg("Price set!")
            except Exception as e:
                print("Price field:", e)

            page.screenshot(path="/root/my_personal_ai/data/kwork_s3_form.png")

            # Find and click submit
            try:
                page.locator("button[type='submit'], button:has-text('Создать'), button:has-text('Опубликовать')").first.click()
                time.sleep(4)
                page.screenshot(path="/root/my_personal_ai/data/kwork_s4_submit.png")
                result_url = page.url
                print("After submit:", result_url[:60])
                if "wants/add" not in result_url:
                    tg(f"GIG CREATED! URL: {result_url[:50]}")
                else:
                    tg("Submitted - check screenshot kwork_s4_submit.png")
            except Exception as e:
                print("Submit:", e)
                tg("Form filled, ready to submit. Check screenshots.")

        else:
            tg("Navigated to add page: " + page.title()[:40])

        # 3. Check existing gigs for editing
        page.goto("https://kwork.ru/seller", timeout=30000, wait_until="domcontentloaded")
        time.sleep(5)
        html2 = page.content()
        edit_links2 = re.findall(r'href="(/wants/edit/(\d+))"', html2)
        print("Edit links:", edit_links2[:5])

        if edit_links2:
            tg(f"Found {len(edit_links2)} gigs to edit!")
            for link, gid in edit_links2[:2]:
                page.goto("https://kwork.ru" + link, timeout=20000, wait_until="domcontentloaded")
                time.sleep(3)
                page.screenshot(path=f"/root/my_personal_ai/data/kwork_edit_{gid}.png")
                tg(f"Edit page for gig {gid}: {page.title()[:30]}")

    except Exception as e:
        print("Error:", str(e)[:200])
        tg("Error: " + str(e)[:100])
        try: page.screenshot(path="/root/my_personal_ai/data/kwork_err.png")
        except: pass

    ctx.close()
    browser.close()

print("Done")
