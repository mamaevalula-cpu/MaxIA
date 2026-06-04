#!/usr/bin/env python3
"""Kwork login via nodriver - best anti-detection browser."""
import asyncio, json, time, urllib.request
from pathlib import Path

env = {}
for line in Path('/root/my_personal_ai/.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, _, v = line.partition('=')
        env[k.strip()] = v.strip()

TOKEN = env.get('CORP_BOT_TOKEN','8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio')
CHAT = env.get('TELEGRAM_CHAT_ID','1985320458')
EMAIL = env.get('KWORK_EMAIL','froggyinternet@gmail.com')
PASS = env.get('KWORK_PASSWORD','Internet!2345')

def tg(msg):
    try:
        data = json.dumps({"chat_id":CHAT,"text":msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data,headers={"Content-Type":"application/json"}),timeout=8)
        print("TG:",msg[:50])
    except: pass

async def run():
    import nodriver as uc

    print("Starting nodriver...")
    tg("Kwork login via nodriver (advanced anti-detection)...")

    browser = await uc.start(
        headless=True,
        browser_args=[
            '--no-sandbox','--disable-dev-shm-usage',
            '--disable-gpu','--ozone-platform=headless',
        ]
    )

    try:
        page = await browser.get("https://kwork.ru/login")
        await asyncio.sleep(3)
        print("Page:", page.url[:60])

        # Fill email
        email_el = await page.find('input[placeholder="Электронная почта или логин"]', timeout=8)
        if email_el:
            await email_el.send_keys(EMAIL)
            await asyncio.sleep(0.5)
            print("Email filled")

        # Fill password
        pass_el = await page.find('input[type="password"]', timeout=5)
        if pass_el:
            await pass_el.send_keys(PASS)
            await asyncio.sleep(0.5)
            print("Password filled")

        # Click submit
        btn = await page.find('button.auth-form__button', timeout=5)
        if btn:
            await btn.click()
            await asyncio.sleep(5)

        url_after = page.url
        print("After login:", url_after[:70])
        logged_in = 'login' not in url_after and 'kwork.ru' in url_after

        if logged_in:
            print("LOGGED IN!")
            tg("Kwork logged in via nodriver!")

            # Save cookies
            cookies = await page.browser.cookies()
            kwork_cookies = [c for c in cookies if 'kwork' in c.get('domain','')]
            cookies_str = '; '.join([f"{c['name']}={c['value']}" for c in kwork_cookies])
            Path('/root/my_personal_ai/data/kwork_cookies.txt').write_text(cookies_str)
            print("Cookies saved:", len(kwork_cookies))

            # Check gigs
            await page.get("https://kwork.ru/my-work/kworks")
            await asyncio.sleep(3)
            content = await page.get_content()
            import re
            gigs = re.findall(r'kwork-id="(\d+)"', content)
            tg(f"Kwork gigs found: {len(gigs)}. Session saved!")
        else:
            # Check for captcha
            content = await page.get_content()
            has_captcha = 'robot' in content.lower() or 'recaptcha' in content.lower() or 'captcha' in content.lower()
            print("Captcha:", has_captcha)
            await page.save_screenshot('/root/my_personal_ai/data/kwork_nodriver.png')
            tg("Kwork: " + ("captcha required - need cookie transfer" if has_captcha else "login failed"))

    except Exception as e:
        print("Error:", str(e)[:200])
        tg("nodriver error: " + str(e)[:100])

    finally:
        browser.stop()

asyncio.run(run())
print("Done")
