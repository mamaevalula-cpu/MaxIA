#!/usr/bin/env python3
"""
groq_key_fetcher.py — Автоматическое получение GROQ API ключа через браузер
Логинится на console.groq.com через Google OAuth, создаёт/копирует ключ, сохраняет в .env
"""
import asyncio, json, logging, re, sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('groq_fetcher')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
GOOGLE_EMAIL    = 'jimmorrisoninlove@gmail.com'
GOOGLE_PASSWORD = 'Fukcyoubithc48'
ENV_FILE = Path('/root/my_personal_ai/.env')

def tg(text):
    try:
        import urllib.request as ur
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        req = ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                         data=data, headers={'Content-Type': 'application/json'})
        ur.urlopen(req, timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def save_key_to_env(key: str):
    content = ENV_FILE.read_text() if ENV_FILE.exists() else ''
    if 'GROQ_API_KEY=' in content:
        content = re.sub(r'GROQ_API_KEY=.*', f'GROQ_API_KEY={key}', content)
    else:
        content += f'\nGROQ_API_KEY={key}\n'
    ENV_FILE.write_text(content)
    log.info('Saved GROQ_API_KEY to .env')

async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    groq_key = None

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
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await stealth_async(page)

        # ── Step 1: Go to Groq Console ──────────────────────────────────────
        log.info('Going to console.groq.com')
        await page.goto('https://console.groq.com/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        # ── Step 2: Click "Continue with Google" ───────────────────────────
        try:
            google_btn = await page.query_selector(
                'button:has-text("Google"), a:has-text("Google"), '
                '[data-provider="google"], .social-login-google'
            )
            if google_btn:
                await google_btn.click()
                await asyncio.sleep(3)
                log.info('Clicked Google login, URL: %s', page.url)
            else:
                log.warning('No Google button found, trying direct Google auth')
                await page.goto('https://accounts.google.com/o/oauth2/auth?'
                               'client_id=406099880067-8c1j08u5t4rvnm7v9t3u4nkco7rr0e77.apps.googleusercontent.com'
                               '&redirect_uri=https://console.groq.com/auth/callback'
                               '&response_type=code&scope=email+profile',
                               wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(2)
        except Exception as e:
            log.error('Google button error: %s', e)

        # ── Step 3: Google login ────────────────────────────────────────────
        if 'accounts.google.com' in page.url:
            log.info('On Google login page')
            try:
                # Enter email
                email_input = await page.query_selector('input[type="email"]')
                if email_input:
                    await email_input.fill(GOOGLE_EMAIL)
                    await page.click('#identifierNext, button:has-text("Next"), button:has-text("Далее")')
                    await asyncio.sleep(2)

                # Enter password
                pwd_input = await page.query_selector('input[type="password"]')
                if pwd_input:
                    await pwd_input.fill(GOOGLE_PASSWORD)
                    await page.click('#passwordNext, button:has-text("Next"), button:has-text("Далее")')
                    await asyncio.sleep(3)

                log.info('Google login submitted, URL: %s', page.url)

                # Wait for redirect back to groq
                for _ in range(10):
                    if 'groq.com' in page.url:
                        break
                    await asyncio.sleep(2)

            except Exception as e:
                log.error('Google login error: %s', e)
                try:
                    await page.screenshot(path='/tmp/groq_google_login.png')
                except Exception:
                    pass

        # ── Step 4: Navigate to API Keys ────────────────────────────────────
        log.info('At groq, URL: %s', page.url)
        await asyncio.sleep(2)

        try:
            await page.goto('https://console.groq.com/keys', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(2)
            log.info('Keys page URL: %s', page.url)

            # Check if on keys page
            if 'keys' in page.url or 'console' in page.url:
                # Look for existing keys or create new
                create_btn = await page.query_selector(
                    'button:has-text("Create"), button:has-text("New"), '
                    'button:has-text("Generate"), button[data-testid*="create"]'
                )
                if create_btn:
                    await create_btn.click()
                    await asyncio.sleep(2)

                    # Enter key name
                    name_input = await page.query_selector('input[placeholder*="name"], input[name*="name"]')
                    if name_input:
                        await name_input.fill('MaxAI-Corporation')
                        await asyncio.sleep(0.5)

                    confirm_btn = await page.query_selector(
                        'button:has-text("Submit"), button:has-text("Create"), '
                        'button[type="submit"]'
                    )
                    if confirm_btn:
                        await confirm_btn.click()
                        await asyncio.sleep(2)

                # Extract key from page (it's shown once after creation)
                page_text = await page.content()
                key_match = re.search(r'gsk_[A-Za-z0-9]{40,60}', page_text)
                if key_match:
                    groq_key = key_match.group(0)
                    log.info('Found GROQ key: %s...', groq_key[:15])
                else:
                    # Try to get from visible text/input
                    key_input = await page.query_selector('input[value*="gsk_"], code:has-text("gsk_")')
                    if key_input:
                        groq_key = await key_input.get_attribute('value') or await key_input.inner_text()
                        groq_key = groq_key.strip() if groq_key else None
        except Exception as e:
            log.error('Keys page error: %s', e)
            try:
                await page.screenshot(path='/tmp/groq_keys_page.png')
            except Exception:
                pass

        await browser.close()

    if groq_key and groq_key.startswith('gsk_'):
        save_key_to_env(groq_key)
        # Restart personal-ai to pick up new key
        import subprocess
        subprocess.run(['systemctl', 'restart', 'personal-ai'], timeout=10)
        tg(f'GROQ API ключ получен и сохранён!\nКлюч: {groq_key[:20]}...\nPersonal-AI перезапущен.')
        log.info('Success! GROQ key saved.')
    else:
        tg('Groq: не удалось автоматически получить ключ.\nПерейди: https://console.groq.com/keys\nСоздай ключ вручную и добавь в .env:\nGROQ_API_KEY=gsk_...')
        log.warning('Could not extract GROQ key automatically')
        # Save screenshots if available
        for f in ['/tmp/groq_google_login.png', '/tmp/groq_keys_page.png']:
            if Path(f).exists():
                log.info('Screenshot: %s', f)


if __name__ == '__main__':
    asyncio.run(run())
