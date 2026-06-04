#!/usr/bin/env python3
"""Kwork automation via Playwright."""
import json, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

env = {}
for line in Path('/root/my_personal_ai/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        env[k.strip()] = v.strip()

TOKEN = env.get('CORP_BOT_TOKEN', '8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio')
CHAT = env.get('TELEGRAM_CHAT_ID', '1985320458')
EMAIL = env.get('KWORK_EMAIL', '')
PASSWORD = env.get('KWORK_PASSWORD', '')

TITLE = "Telegram бот с AI за 24 часа. Автоматизация бизнеса от 3500р"
DESCRIPTION = (
    "Создаю умных Telegram ботов с AI для автоматизации бизнеса. "
    "Ваш бизнес теряет клиентов пока менеджеры отвечают вручную? "
    "Бот решает это: автоответы на 80% вопросов, приём заявок 24/7, "
    "интеграция с CRM, AI-помощник на базе ChatGPT/DeepSeek. "
    "Опыт: 50+ ботов для ресторанов, клиник, магазинов. "
    "Срок 24-72 часа. Гарантия 30 дней."
)

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot" + TOKEN + "/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
        print("TG: " + msg[:60])
    except Exception as e:
        print("TG error: " + str(e))

print("Starting Kwork automation...")
tg("Browser Agent: открываю Kwork.ru...")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu',
              '--ozone-platform=headless', '--disable-setuid-sandbox']
    )
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        viewport={'width': 1280, 'height': 900}
    )
    page = ctx.new_page()

    try:
        page.goto("https://kwork.ru/login", timeout=30000, wait_until="domcontentloaded")
        time.sleep(2)
        print("Page: " + page.title())
        tg("Kwork login page opened: " + page.title()[:40])

        # Fill login form
        selectors_tried = []

        # Try email field
        # Kwork uses placeholder selector
        for sel in ['input[placeholder="Электронная почта или логин"]']:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=3000, state="visible")
                el.fill(EMAIL)
                selectors_tried.append(sel)
                print("Email filled: " + sel)
                break
            except:
                pass

        time.sleep(0.5)

        # Fill password
        for sel in ['input[type="password"]', 'input[name="password"]', '#password']:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=3000, state="visible")
                el.fill(PASSWORD)
                print("Password filled: " + sel)
                break
            except:
                pass

        time.sleep(0.5)

        # Submit
        for sel in ['button[type="submit"]', '.form-btn', '.login-btn', 'input[type="submit"]']:
            try:
                el = page.locator(sel).first
                el.wait_for(timeout=2000, state="visible")
                el.click()
                print("Submitted: " + sel)
                break
            except:
                pass

        time.sleep(4)

        url_after = page.url
        print("URL after login: " + url_after)
        logged_in = "kwork.ru" in url_after and "login" not in url_after

        # Take screenshot
        page.screenshot(path='/root/my_personal_ai/data/kwork_login_result.png')
        tg("Login attempt done. URL: " + url_after[:60])

        if logged_in:
            tg("SUCCESS: Logged in to Kwork!")
            page.goto("https://kwork.ru/wants/add", timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)
            tg("Gig creation page: " + page.title()[:40])

            # Fill gig form
            for sel in ['input[name="name"]', '#name', 'input[placeholder*="название"]']:
                try:
                    el = page.locator(sel).first
                    el.fill(TITLE)
                    tg("Title filled: " + TITLE[:40])
                    break
                except: pass

            time.sleep(0.3)

            for sel in ['textarea[name="description"]', '#description', 'textarea']:
                try:
                    el = page.locator(sel).first
                    el.fill(DESCRIPTION)
                    tg("Description filled")
                    break
                except: pass

            time.sleep(0.3)

            for sel in ['input[name="price"]', '#price', 'input[placeholder*="цена"]']:
                try:
                    el = page.locator(sel).first
                    el.fill('3500')
                    tg("Price: 3500r set")
                    break
                except: pass

            page.screenshot(path='/root/my_personal_ai/data/kwork_gig_form.png')
            tg(
                "Form filled! Screenshot saved.\n"
                "To publish: open panel -> Browser tab\n"
                "URL: https://kwork.ru/wants/add\n"
                "Click Publish button."
            )
        else:
            # Page content for debug
            content = page.content()[:300]
            print("Page content: " + content)
            tg(
                "Login needs your help.\n\n"
                "Open panel https://maxai.fyi\n"
                "Click 'Browser' tab\n"
                "Go to: kwork.ru/login\n"
                "Email: " + EMAIL + "\n"
                "Login manually once, then MaxAI continues."
            )

    except Exception as e:
        err = str(e)[:200]
        print("ERROR: " + err)
        page.screenshot(path='/root/my_personal_ai/data/kwork_error.png')
        tg(
            "Browser error: " + err[:100] + "\n\n"
            "Manual login needed:\n"
            "Panel -> Browser -> kwork.ru/login"
        )

    browser.close()
    print("Done")
