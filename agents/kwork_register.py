#!/usr/bin/env python3
"""
kwork_register.py — Регистрация нового аккаунта на Kwork.ru
Email: jimmorrisoninlove@gmail.com
Верификация через Gmail IMAP
"""
import asyncio, imaplib, email, json, logging, re, sys, time
from datetime import datetime
from pathlib import Path

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/kwork_register.log'),
    ]
)
log = logging.getLogger('kwork_register')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'

KWORK_EMAIL    = 'jimmorrisoninlove@gmail.com'
KWORK_PASSWORD = 'MaxAI_kwork_2026!'  # New password for Kwork account
KWORK_USERNAME = 'MaxAI_Dev'

# Gmail IMAP — try with direct password (works if 2FA disabled)
GMAIL_PASS = 'Fukcyoubithc48'

ENV_FILE = Path('/root/my_personal_ai/.env')

def tg(text):
    try:
        import urllib.request as ur
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                              data=data, headers={'Content-Type': 'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def save_kwork_creds(email: str, password: str):
    """Update .env with new Kwork credentials."""
    content = ENV_FILE.read_text() if ENV_FILE.exists() else ''
    content = re.sub(r'KWORK_PASSWORD=.*', f'KWORK_PASSWORD={password}', content)
    if 'KWORK_PASSWORD=' not in content:
        content += f'\nKWORK_PASSWORD={password}\n'
    ENV_FILE.write_text(content)
    log.info('Updated KWORK_PASSWORD in .env')

def read_verification_email() -> str | None:
    """Try to read Kwork verification link from Gmail."""
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        mail.login(KWORK_EMAIL, GMAIL_PASS)
        mail.select('INBOX')

        # Search for recent Kwork emails
        _, msgs = mail.search(None, 'FROM "kwork" UNSEEN')
        if not msgs[0]:
            # Try all recent emails
            _, msgs = mail.search(None, 'FROM "kwork"')

        ids = msgs[0].split()
        if not ids:
            log.warning('No Kwork emails found')
            return None

        # Get last email
        _, data = mail.fetch(ids[-1], '(RFC822)')
        msg = email.message_from_bytes(data[0][1])

        # Extract text
        body = ''
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ('text/plain', 'text/html'):
                    body += part.get_payload(decode=True).decode('utf-8', errors='replace')
        else:
            body = msg.get_payload(decode=True).decode('utf-8', errors='replace')

        # Find verification link
        links = re.findall(r'https://kwork\.ru[^\s"<>]+confirm[^\s"<>]+', body)
        if links:
            log.info('Found verification link: %s', links[0][:60])
            return links[0]

        mail.close()
        mail.logout()
    except Exception as e:
        log.error('Gmail IMAP error: %s', e)
    return None


async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled',
                  '--disable-dev-shm-usage']
        )
        ctx = await browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ru-RU',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await stealth_async(page)

        # ── Step 1: Try login with new password first ──────────────────────
        log.info('Trying login with new password...')
        await page.goto('https://kwork.ru/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        # Dismiss cookies
        try:
            cb = await page.query_selector('button:has-text("Окей")')
            if cb: await cb.click(); await asyncio.sleep(0.5)
        except Exception: pass

        # Try to fill login form
        await page.fill('input[placeholder="Электронная почта или логин"]', KWORK_EMAIL)
        await asyncio.sleep(0.3)
        await page.fill('input[type="password"]', KWORK_PASSWORD)
        await asyncio.sleep(0.3)
        await page.click('button.auth-form__button')
        await asyncio.sleep(4)

        if 'login' not in page.url:
            log.info('Login with new password worked!')
            tg(f'Kwork: успешный вход!\nEmail: {KWORK_EMAIL}\nПароль: {KWORK_PASSWORD}')
            save_kwork_creds(KWORK_EMAIL, KWORK_PASSWORD)
            await browser.close()
            return

        # ── Step 2: Registration ───────────────────────────────────────────
        log.info('Registration attempt...')
        await page.goto('https://kwork.ru/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        # Look for "Sign Up" link
        try:
            signup_link = await page.query_selector(
                'a:has-text("Зарегистрироваться"), a:has-text("Регистрация"), '
                '.register-link, [href*="register"]'
            )
            if signup_link:
                await signup_link.click()
                await asyncio.sleep(2)
            else:
                await page.goto('https://kwork.ru/register', wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(2)
        except Exception as e:
            log.warning('Navigation to register: %s', e)
            await page.goto('https://kwork.ru/register', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(2)

        log.info('Register page URL: %s', page.url)

        # Check what inputs are on register page
        inputs = await page.query_selector_all('input:not([type="hidden"])')
        for inp in inputs:
            placeholder = await inp.get_attribute('placeholder') or ''
            name = await inp.get_attribute('name') or ''
            type_ = await inp.get_attribute('type') or 'text'
            log.info('Input: type=%s name=%s placeholder=%s', type_, name, placeholder)

        try:
            # Fill registration form
            # Email
            email_inp = await page.query_selector(
                'input[placeholder*="почта"], input[placeholder*="email"], input[name*="email"], input[type="email"]'
            )
            if email_inp:
                await email_inp.fill(KWORK_EMAIL)
                await asyncio.sleep(0.3)

            # Username/name
            name_inp = await page.query_selector(
                'input[placeholder*="имя"], input[placeholder*="логин"], '
                'input[name*="username"], input[name*="login"], input[name*="name"]'
            )
            if name_inp:
                await name_inp.fill(KWORK_USERNAME)
                await asyncio.sleep(0.3)

            # Password
            pwd_inputs = await page.query_selector_all('input[type="password"]')
            for pi in pwd_inputs:
                await pi.fill(KWORK_PASSWORD)
                await asyncio.sleep(0.2)

            # Submit
            submit = await page.query_selector(
                'button[type="submit"], button.auth-form__button, button:has-text("Зарегистрироваться")'
            )
            if submit:
                await submit.click()
                await asyncio.sleep(4)
                log.info('Registration submitted, URL: %s', page.url)

                # Check for success
                if 'login' not in page.url:
                    log.info('Registration may have succeeded!')
                    await page.screenshot(path='/tmp/kwork_reg_success.png')

                    # Try to read verification email
                    log.info('Waiting 15s for verification email...')
                    await asyncio.sleep(15)
                    verify_link = read_verification_email()

                    if verify_link:
                        log.info('Got verification link, confirming...')
                        await page.goto(verify_link, wait_until='domcontentloaded', timeout=20000)
                        await asyncio.sleep(3)
                        log.info('Verified! URL: %s', page.url)

                    save_kwork_creds(KWORK_EMAIL, KWORK_PASSWORD)
                    tg(
                        f'Kwork: аккаунт зарегистрирован!\n'
                        f'Email: {KWORK_EMAIL}\n'
                        f'Password: {KWORK_PASSWORD}\n'
                        f'Верификация: {"выполнена" if verify_link else "нужна вручную"}'
                    )
                else:
                    errors = await page.query_selector_all('.error, .alert-danger, [class*="error"]')
                    err_texts = []
                    for e in errors:
                        try:
                            t = await e.inner_text()
                            if t.strip(): err_texts.append(t.strip()[:100])
                        except Exception: pass
                    log.warning('Registration errors: %s', err_texts)
                    tg(
                        f'Kwork: регистрация не удалась.\n'
                        f'Ошибки: {", ".join(err_texts) or "неизвестно"}\n\n'
                        f'Возможно email уже занят или нужна другая почта.\n'
                        f'Зарегистрируй вручную: kwork.ru/register'
                    )
        except Exception as e:
            log.error('Registration error: %s', e)
            await page.screenshot(path='/tmp/kwork_reg_fail.png')
            tg(f'Kwork регистрация: ошибка {e}')

        await browser.close()


if __name__ == '__main__':
    asyncio.run(run())
