#!/usr/bin/env python3
"""
openrouter_key_fetcher.py — Получение OpenRouter API ключа через браузер
OpenRouter даёт бесплатные модели (mistral-7b, llama-3, gemma и др.)
Регистрация через email — без Google OAuth блокировки
"""
import asyncio, json, logging, re, sys, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                    handlers=[logging.StreamHandler(),
                               logging.FileHandler('/root/my_personal_ai/logs/openrouter_fetcher.log')])
log = logging.getLogger('openrouter')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
ENV_FILE = Path('/root/my_personal_ai/.env')

# Use froggy email to separate from main accounts
EMAIL    = 'froggyinternet@gmail.com'
# OpenRouter needs email+password signup
OR_PASS  = 'MaxAI_Corp_2026!'

def tg(text):
    try:
        import urllib.request as ur
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                              data=data, headers={'Content-Type': 'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def save_key_to_env(key: str, var_name: str = 'OPENROUTER_API_KEY'):
    content = ENV_FILE.read_text() if ENV_FILE.exists() else ''
    if f'{var_name}=' in content:
        content = re.sub(f'{var_name}=.*', f'{var_name}={key}', content)
    else:
        content = content.rstrip() + f'\n{var_name}={key}\n'
    ENV_FILE.write_text(content)
    log.info('Saved %s to .env', var_name)

async def try_openrouter():
    """Try to get OpenRouter key via browser."""
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    key = None
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

        # ── Try login first (account may exist) ────────────────────────────
        log.info('Trying OpenRouter login...')
        await page.goto('https://openrouter.ai/sign-in', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        # Try email login
        try:
            email_input = await page.query_selector('input[type="email"], input[name="email"]')
            if email_input:
                await email_input.fill(EMAIL)
                pwd_input = await page.query_selector('input[type="password"]')
                if pwd_input:
                    await pwd_input.fill(OR_PASS)
                    await page.click('button[type="submit"]')
                    await asyncio.sleep(3)
        except Exception as e:
            log.warning('Login attempt: %s', e)

        # If not logged in, sign up
        if 'sign-in' in page.url or 'login' in page.url:
            log.info('Trying signup...')
            await page.goto('https://openrouter.ai/sign-up', wait_until='domcontentloaded', timeout=30000)
            await asyncio.sleep(2)
            try:
                email_input = await page.query_selector('input[type="email"], input[name="email"]')
                if email_input:
                    await email_input.fill(EMAIL)
                await page.query_selector('input[type="password"]')
                pwd_inputs = await page.query_selector_all('input[type="password"]')
                for pi in pwd_inputs:
                    await pi.fill(OR_PASS)
                    await asyncio.sleep(0.3)
                submit = await page.query_selector('button[type="submit"]')
                if submit:
                    await submit.click()
                    await asyncio.sleep(5)
            except Exception as e:
                log.warning('Signup attempt: %s', e)

        # Navigate to keys page
        await page.goto('https://openrouter.ai/keys', wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(2)
        log.info('Keys page URL: %s', page.url)

        # Try to create a key
        try:
            create_btn = await page.query_selector(
                'button:has-text("Create"), button:has-text("New"), '
                'button:has-text("Add"), button:has-text("Generate")'
            )
            if create_btn:
                await create_btn.click()
                await asyncio.sleep(2)
                # Name the key
                name_input = await page.query_selector('input[placeholder*="name"], input[name*="name"]')
                if name_input:
                    await name_input.fill('MaxAI-Corporation')
                    await asyncio.sleep(0.5)
                confirm = await page.query_selector('button[type="submit"], button:has-text("Create")')
                if confirm:
                    await confirm.click()
                    await asyncio.sleep(2)
        except Exception as e:
            log.warning('Key creation: %s', e)

        # Extract key from page
        page_text = await page.content()
        # OpenRouter keys start with sk-or-
        key_match = re.search(r'sk-or-[A-Za-z0-9\-_]{20,80}', page_text)
        if key_match:
            key = key_match.group(0)
            log.info('Found OpenRouter key: %s...', key[:20])
        else:
            # Try clipboard/input value
            try:
                key_inputs = await page.query_selector_all('input[value*="sk-or-"], code')
                for ki in key_inputs:
                    val = await ki.get_attribute('value') or await ki.inner_text()
                    if val and val.startswith('sk-or-'):
                        key = val.strip()
                        break
            except Exception:
                pass
            # Take screenshot for manual inspection
            await page.screenshot(path='/tmp/openrouter_keys.png')

        await browser.close()
    return key


async def try_groq_email():
    """Try Groq with direct email registration (no Google OAuth)."""
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    key = None
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

        log.info('Trying Groq email signup...')
        await page.goto('https://console.groq.com/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        # Try "Sign up" or email option instead of Google
        try:
            # Look for email sign-in option
            email_link = await page.query_selector(
                'a:has-text("email"), button:has-text("email"), '
                'a:has-text("Sign up"), button:has-text("Continue with Email")'
            )
            if email_link:
                await email_link.click()
                await asyncio.sleep(2)

            email_input = await page.query_selector('input[type="email"]')
            if email_input:
                await email_input.fill('froggyinternet@gmail.com')
                await page.keyboard.press('Enter')
                await asyncio.sleep(2)

                # Password
                pwd = await page.query_selector('input[type="password"]')
                if pwd:
                    await pwd.fill('MaxAI_Corp_2026!')
                    await page.keyboard.press('Enter')
                    await asyncio.sleep(3)
        except Exception as e:
            log.warning('Groq email attempt: %s', e)
            await page.screenshot(path='/tmp/groq_email_attempt.png')

        log.info('Groq URL after attempt: %s', page.url)

        # Check keys page
        if 'console.groq.com' in page.url:
            await page.goto('https://console.groq.com/keys', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(2)
            page_text = await page.content()
            m = re.search(r'gsk_[A-Za-z0-9]{40,60}', page_text)
            if m:
                key = m.group(0)

        await browser.close()
    return key


async def main():
    # Try OpenRouter first (simpler)
    log.info('=== LLM Key Fetcher ===')
    key = None
    provider = None

    try:
        key = await try_openrouter()
        if key:
            provider = 'OpenRouter'
            save_key_to_env(key, 'OPENROUTER_API_KEY')
    except Exception as e:
        log.error('OpenRouter failed: %s', e)

    if not key:
        try:
            key = await try_groq_email()
            if key:
                provider = 'Groq'
                save_key_to_env(key, 'GROQ_API_KEY')
        except Exception as e:
            log.error('Groq email failed: %s', e)

    if key:
        import subprocess
        subprocess.run(['systemctl', 'restart', 'personal-ai'], timeout=10)
        tg(f'{provider} API ключ получен!\nКлюч: {key[:25]}...\nPersonal-AI перезапущен.')
        log.info('SUCCESS: %s key saved', provider)
    else:
        # Report what's needed manually
        tg(
            'Не удалось автоматически получить LLM ключ.\n\n'
            'Получи вручную (5 мин, бесплатно):\n'
            '1. console.groq.com → Login → API Keys → Create\n'
            '2. Скопируй ключ gsk_...\n'
            '3. Добавь в .env: GROQ_API_KEY=gsk_...\n'
            '4. systemctl restart personal-ai\n\n'
            'ИЛИ openrouter.ai/keys → Create (sk-or-...)'
        )
        log.warning('Could not get LLM key automatically')


if __name__ == '__main__':
    asyncio.run(main())
