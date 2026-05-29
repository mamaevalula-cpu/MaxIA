#!/usr/bin/env python3
"""
register_hf_github.py — Register on HuggingFace and prepare GitHub
HuggingFace: email registration
GitHub: email registration (for Marketplace later)
"""
import asyncio, json, logging, os, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('hf_github')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

EMAIL1   = 'froggyinternet@gmail.com'
EMAIL2   = 'jimmorrisoninlove@gmail.com'
PASSWORD = 'Internetinternet!2'
PASSWORD2 = 'Fukcyoubithc48'

STATUS_FILE = Path('/root/my_personal_ai/data/platform_status.json')

def tg(text):
    import urllib.request as ur
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type': 'application/json'}
        ), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except:
        return {}

def save_status(s):
    STATUS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))


async def register_huggingface(page):
    """Register on HuggingFace"""
    log.info('[HuggingFace] Starting registration...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://huggingface.co/join', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        page_text = (await page.inner_text('body')).lower()

        # Check if logged in
        if 'profile' in page_text or 'logout' in page_text or 'new model' in page_text:
            result['status'] = 'logged_in'
            log.info('[HuggingFace] Already logged in')
            return result

        # Fill email
        for sel in ['input[name="email"]', 'input[type="email"]', '#email']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(EMAIL1)
                log.info('[HF] Filled email')
                break

        # Fill username
        for sel in ['input[name="username"]', 'input[placeholder*="username" i]', '#username']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill('maxai-corp')
                log.info('[HF] Filled username')
                break

        # Fill password
        for sel in ['input[type="password"]', 'input[name="password"]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(PASSWORD)
                break

        # Accept terms
        for sel in ['input[type="checkbox"]', 'input[name="terms"]']:
            try:
                el = await page.query_selector(sel)
                if el and not await el.is_checked():
                    await el.click()
            except:
                pass

        # Submit
        for sel in ['button[type="submit"]', 'button:has-text("Register")',
                    'button:has-text("Create account")', 'button:has-text("Sign up")']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(5)
                break

        new_url = page.url
        new_text = (await page.inner_text('body')).lower()

        if any(x in new_text for x in ['verify', 'confirm your email', 'check your email', 'email sent']):
            result['status'] = 'verify_email'
            result['note'] = 'Check froggyinternet@gmail.com'
        elif 'profile' in new_url or 'settings' in new_url or 'maxai-corp' in new_url:
            result['status'] = 'registered'
            result['profile_url'] = 'https://huggingface.co/maxai-corp'
        elif 'already' in new_text or 'taken' in new_text:
            result['status'] = 'already_exists'
        else:
            result['status'] = 'unknown'
            result['page_url'] = new_url
            result['snippet'] = new_text[:200]

        log.info('[HF] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[HF] Error: %s', e)

    return result


async def register_github(page):
    """Register on GitHub (for GitHub Marketplace)"""
    log.info('[GitHub] Starting registration...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://github.com/signup', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        page_text = (await page.inner_text('body')).lower()

        if 'dashboard' in page.url or 'feed' in page.url:
            result['status'] = 'logged_in'
            log.info('[GitHub] Already logged in')
            return result

        # GitHub signup is a multi-step form
        # Step 1: Email
        for sel in ['input[name="user[email]"]', 'input[type="email"]', '#email']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(EMAIL1)
                await page.keyboard.press('Tab')
                await asyncio.sleep(2)
                log.info('[GitHub] Filled email')
                break

        # Step 2: Password
        for sel in ['input[name="user[password]"]', 'input[type="password"]', '#password']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(PASSWORD + 'Gh1')
                await page.keyboard.press('Tab')
                await asyncio.sleep(2)
                break

        # Step 3: Username
        for sel in ['input[name="user[login]"]', 'input[placeholder*="username" i]', '#login_field']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill('maxai-corporation')
                await page.keyboard.press('Tab')
                await asyncio.sleep(2)
                break

        # Click "Continue" or submit
        for sel in ['button[type="submit"]', 'button:has-text("Continue")',
                    'button:has-text("Create account")', 'input[type="submit"]']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                break

        new_url = page.url
        new_text = (await page.inner_text('body')).lower()

        if any(x in new_text for x in ['verify', 'check your email', 'confirm']):
            result['status'] = 'verify_email'
            result['note'] = 'Check froggyinternet@gmail.com'
        elif 'dashboard' in new_url or '/maxai' in new_url:
            result['status'] = 'registered'
        elif 'captcha' in new_text or 'puzzle' in new_text:
            result['status'] = 'captcha_blocked'
        elif 'already' in new_text or 'taken' in new_text:
            result['status'] = 'already_exists'
        else:
            result['status'] = 'partial'
            result['page_url'] = new_url
            result['note'] = 'May need manual completion (CAPTCHA)'

        log.info('[GitHub] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[GitHub] Error: %s', e)

    return result


async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa
        USE_STEALTH = True
    except:
        USE_STEALTH = False

    status = load_status()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await sa(page)

        # HuggingFace
        if status.get('huggingface', {}).get('status') not in ('registered', 'logged_in', 'verify_email'):
            hf_result = await register_huggingface(page)
            status['huggingface'] = hf_result
            save_status(status)
        else:
            log.info('[HuggingFace] Already done: %s', status['huggingface']['status'])

        await asyncio.sleep(5)

        # GitHub
        if status.get('github', {}).get('status') not in ('registered', 'logged_in', 'verify_email'):
            gh_result = await register_github(page)
            status['github'] = gh_result
            save_status(status)
        else:
            log.info('[GitHub] Already done: %s', status['github']['status'])

        await browser.close()

    hf_s = status.get('huggingface', {}).get('status', '?')
    gh_s = status.get('github', {}).get('status', '?')
    msg = f'MaxAI — HF + GitHub\nHuggingFace: {hf_s}\nGitHub: {gh_s}'
    tg(msg)
    print(msg)


if __name__ == '__main__':
    asyncio.run(run())
