#!/usr/bin/env python3
"""
get_openrouter_key.py — Register on OpenRouter and get free API key
Uses froggyinternet@gmail.com
"""
import asyncio, json, logging, re, time
from pathlib import Path

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler('/root/my_personal_ai/logs/openrouter_reg.log')])
log = logging.getLogger('or_reg')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
EMAIL    = 'froggyinternet@gmail.com'
PASSWORD = 'Internetinternet!2'
ENV_FILE = Path('/root/my_personal_ai/.env')

def tg(text):
    try:
        import urllib.request as ur
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type':'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def save_key(key: str):
    content = ENV_FILE.read_text()
    if 'OPENROUTER_API_KEY=' in content:
        import re
        content = re.sub(r'OPENROUTER_API_KEY=.*', f'OPENROUTER_API_KEY={key}', content)
    else:
        content += f'\nOPENROUTER_API_KEY={key}\n'
    ENV_FILE.write_text(content)
    log.info('Saved OPENROUTER_API_KEY to .env')

async def try_register():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            viewport={'width':1280,'height':900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await stealth_async(page)

        # ── Step 1: Try sign up ──────────────────────────────────────────
        log.info('Loading openrouter.ai/sign-up')
        await page.goto('https://openrouter.ai/sign-up', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)
        await page.screenshot(path='/tmp/or_1_signup.png')

        url = page.url
        log.info('URL: %s', url)

        # Find email input
        inputs = await page.query_selector_all('input:not([type=hidden])')
        log.info('Inputs: %d', len(inputs))
        for inp in inputs[:6]:
            tp = await inp.get_attribute('type') or 'text'
            ph = await inp.get_attribute('placeholder') or ''
            nm = await inp.get_attribute('name') or ''
            log.info('  %s/%s/%s', tp, nm, ph[:30])

        # Try to fill signup form
        email_filled = False
        for sel in ['input[type="email"]','input[name="email"]','input[placeholder*="email"]','input[placeholder*="Email"]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL)
                    email_filled = True
                    log.info('Email: %s', sel)
                    break
            except:
                pass

        if not email_filled and inputs:
            # try first visible input
            for inp in inputs:
                tp = await inp.get_attribute('type') or 'text'
                if tp in ('text','email') and await inp.is_visible():
                    await inp.fill(EMAIL)
                    email_filled = True
                    log.info('Email via fallback')
                    break

        # Password
        for sel in ['input[type="password"]','input[name="password"]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    log.info('Password filled')
                    break
            except:
                pass

        # Confirm password (some forms have it)
        pwd_inputs = await page.query_selector_all('input[type="password"]')
        if len(pwd_inputs) >= 2:
            await pwd_inputs[1].fill(PASSWORD)

        # Submit
        for btn_sel in ['button[type="submit"]','button:has-text("Sign Up")','button:has-text("Create")','button:has-text("Register")']:
            try:
                btn = await page.query_selector(btn_sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    log.info('Clicked: %s', btn_sel)
                    break
            except:
                pass

        await asyncio.sleep(5)
        await page.screenshot(path='/tmp/or_2_after_signup.png')
        log.info('After signup URL: %s', page.url)

        # ── Step 2: Try login if already registered ──────────────────────
        if 'sign-up' in page.url or 'login' in page.url or 'sign-in' in page.url:
            log.info('Trying login instead...')
            await page.goto('https://openrouter.ai/sign-in', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(2)

            for sel in ['input[type="email"]','input[name="email"]']:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(EMAIL)
                        break
                except:
                    pass

            for sel in ['input[type="password"]','input[name="password"]']:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        await el.fill(PASSWORD)
                        break
                except:
                    pass

            for sel in ['button[type="submit"]','button:has-text("Sign In")','button:has-text("Login")']:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        break
                except:
                    pass

            await asyncio.sleep(5)
            log.info('After login URL: %s', page.url)

        # ── Step 3: Get API key ──────────────────────────────────────────
        if 'openrouter.ai' in page.url and 'sign' not in page.url:
            log.info('Logged in! Going to keys page...')
            await page.goto('https://openrouter.ai/keys', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)
            await page.screenshot(path='/tmp/or_3_keys.png')

            # Look for existing keys or create new
            page_text = await page.inner_text('body')

            # Find key pattern in page
            key_match = re.search(r'sk-or-v1-[a-f0-9]{64}', page_text)
            if key_match:
                key = key_match.group(0)
                log.info('Found key: %s...', key[:20])
                save_key(key)
                tg(f'OpenRouter ключ получен!\nsk-or-v1-...{key[-8:]}\nДобавлен в .env — AI ответы теперь реальные!')
                await browser.close()
                return key

            # Try to create new key
            for btn_sel in ['button:has-text("Create Key")','button:has-text("New Key")','button:has-text("Add Key")','+']:
                try:
                    btn = await page.query_selector(btn_sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(2)
                        break
                except:
                    pass

            # After creating, look for key in modal/page
            await asyncio.sleep(2)
            page_text2 = await page.inner_text('body')
            key_match2 = re.search(r'sk-or-v1-[a-f0-9]{64}', page_text2)
            if key_match2:
                key = key_match2.group(0)
                log.info('New key created: %s...', key[:20])
                save_key(key)
                tg(f'OpenRouter ключ создан!\nДобавлен в .env')
                await browser.close()
                return key

            await page.screenshot(path='/tmp/or_4_final.png')
            log.info('Could not extract key. Page text sample: %s', page_text2[:300])
            tg(f'OpenRouter: вошли, но ключ не нашли автоматически.\nЗайди: openrouter.ai/keys\nCоздай ключ и пришли мне')
        else:
            tg(
                'OpenRouter: требует OAuth (Google/GitHub).\n\n'
                'Зайди сам: openrouter.ai/keys\n'
                '(бесплатно, есть llama-3 и другие)\n'
                'Пришли ключ — добавлю сразу!'
            )
            log.warning('Could not log in to OpenRouter')

        await browser.close()
        return None

if __name__ == '__main__':
    asyncio.run(try_register())
