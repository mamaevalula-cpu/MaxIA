#!/usr/bin/env python3
"""Fill Kwork /new wizard form properly"""
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

GIG_TITLE = "Telegram-bot s AI za 24 chasa. Avtomatizatsiya biznesa ot 3500r"
GIG_DESC = (
    "Sozdayu Telegram botov s AI (ChatGPT/DeepSeek) dlya biznesa. "
    "Avtootvety na voprosy klientov 24/7. Priem zayavok. "
    "Integraciya s CRM. Srok 24-72 chasa. Opyt 50+ botov. "
    "Garantiya 30 dney."
)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--ozone-platform=headless"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120", viewport={"width":1280,"height":900})
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    try:
        page.goto("https://kwork.ru/new", timeout=30000, wait_until="networkidle")
        time.sleep(6)
        page.screenshot(path="/root/my_personal_ai/data/kw_new1.png")
        tg(f"Kwork /new wizard: {page.title()[:40]}")
        print("URL:", page.url[:60])

        # Get page text to understand wizard steps
        page_text = page.inner_text("body")[:2000]
        print("Page text:", page_text[:500])

        # Step 1: Select category if needed
        # Look for category selection
        selects = page.query_selector_all("select")
        for sel in selects[:5]:
            name = sel.get_attribute("name") or ""
            opts = sel.query_selector_all("option")
            print(f"Select {name}: {len(opts)} options")
            for opt in opts[:5]:
                print(f"  {opt.get_attribute('value')} = {opt.inner_text()[:40]}")

        # Try to select "Разработка и IT" category
        for sel_name in ["parentCategories", "categories"]:
            try:
                sel_el = page.locator(f"select[name='{sel_name}']").first
                # Get options
                options = page.eval_on_selector(f"select[name='{sel_name}']",
                    "el => Array.from(el.options).map(o => ({value: o.value, text: o.text}))")
                print(f"Select '{sel_name}' options:", options[:5])

                # Find programming/development option
                dev_opt = next((o for o in options if any(x in o["text"].lower()
                    for x in ["разраб", "it", "program", "скрипт", "бот"])), None)
                if dev_opt:
                    sel_el.select_option(dev_opt["value"])
                    time.sleep(1)
                    print(f"Selected: {dev_opt['text']}")
                    tg(f"Category selected: {dev_opt['text'][:30]}")
            except Exception as e:
                print(f"Select {sel_name} error:", e)

        time.sleep(2)
        page.screenshot(path="/root/my_personal_ai/data/kw_new2_cat.png")

        # Fill title (textarea[name='title'])
        for sel in ["textarea[name='title']", "input[name='title']", "textarea:first-of-type"]:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=3000, state="visible")
                el.fill(GIG_TITLE)
                el.dispatch_event("input")
                el.dispatch_event("change")
                print(f"Title filled via {sel}!")
                tg("Title filled!")
                break
            except: pass

        time.sleep(0.5)

        # Fill description
        for sel in ["textarea[name='description']", "textarea:not([name='title'])"]:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=3000, state="visible")
                el.fill(GIG_DESC)
                el.dispatch_event("input")
                print(f"Description filled via {sel}!")
                tg("Description filled!")
                break
            except: pass

        time.sleep(0.5)

        # Set price
        for sel in ["input[name='price']", "input[placeholder*='цен']", "input[type='number']"]:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=2000, state="visible")
                el.fill("3500")
                el.dispatch_event("input")
                print("Price: 3500")
                break
            except: pass

        page.screenshot(path="/root/my_personal_ai/data/kw_new3_filled.png")

        # Find and click submit/next
        for btn_sel in [
            "button:has-text('Далее')",
            "button:has-text('Продолжить')",
            "button:has-text('Создать')",
            "button:has-text('Опубликовать')",
            "button[type='submit']",
        ]:
            try:
                btn = page.locator(btn_sel).first
                btn.wait_for(timeout=2000, state="visible")
                txt = btn.inner_text()
                print(f"Clicking: '{txt}'")
                tg(f"Clicking: {txt}")
                btn.click()
                time.sleep(5)
                new_url = page.url
                print(f"After: {new_url[:60]}")
                page.screenshot(path="/root/my_personal_ai/data/kw_new4_result.png")
                tg(f"Result: {page.title()[:30]} | {new_url[:50]}")
                break
            except: pass

        # Also try editing existing gig by ID
        # From screenshot we know gig titles, let me find their IDs
        page.goto("https://kwork.ru/manage_kworks", timeout=20000, wait_until="networkidle")
        time.sleep(5)
        html = page.content()
        # Find any numeric IDs in the page
        all_ids = re.findall(r'(?:kwork_id|wantId|want-id|data-want)["\s]*[=:]\s*["\s]*(\d+)', html)
        print("Found IDs:", all_ids[:5])

        # Find gig card links
        gig_hrefs = re.findall(r'href="(https://kwork\.ru/[^"]+)"', html)
        gig_hrefs = [h for h in gig_hrefs if any(x in h for x in ["/wants/", "kwork.ru/v2", "preview"])]
        print("Gig hrefs:", gig_hrefs[:5])

        tg("Kwork wizard filled. Check screenshots kw_new*.png")

    except Exception as e:
        print("Error:", str(e)[:200])
        tg("Error: " + str(e)[:100])

    ctx.close()
    browser.close()
print("Done")
