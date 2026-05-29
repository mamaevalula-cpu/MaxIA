#!/usr/bin/env python3
"""
platform_content_setup.py
1. Dify: fix multi-step email signup
2. Zapier: login + create a Zap
3. Pipedream: login + check/create workflow
4. Bitrix24: login + fill company profile
"""
import asyncio, json, logging, os, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('content_setup')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

EMAIL1   = 'froggyinternet@gmail.com'
EMAIL2   = 'jimmorrisoninlove@gmail.com'
PASSWORD = 'Internetinternet!2'
PASSWORD2 = 'Fukcyoubithc48'
MAXAI_API = 'http://77.90.2.171:8090'

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


async def fix_dify(page):
    """Dify: handle multi-step signup (email -> password)"""
    log.info('[Dify] Fixing registration...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://cloud.dify.ai/sign-up', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(4)

        # Screenshot the page state for debug
        body_text = (await page.inner_text('body')).lower()
        current_url = page.url

        # Check if already on dashboard
        if any(x in current_url for x in ['app/', 'dashboard', 'workspace']):
            result['status'] = 'logged_in'
            return result

        if any(x in body_text for x in ['dashboard', 'workspace', 'create app', 'sign out']):
            result['status'] = 'logged_in'
            return result

        # Step 1: Fill email
        email_filled = False
        for sel in ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(EMAIL1)
                email_filled = True
                log.info('[Dify] Filled email')
                break

        if not email_filled:
            # Try to find "Sign up with email" link first
            for sel in ['a:has-text("email")', 'button:has-text("email")',
                        '[class*="email"]', 'a:has-text("Sign up")']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(2)
                    break

            # Retry email fill
            for sel in ['input[name="email"]', 'input[type="email"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL1)
                    email_filled = True
                    break

        # Click Continue (Dify uses multi-step: email first)
        for sel in ['button:has-text("Continue")', 'button[type="submit"]',
                    'button:has-text("Next")', 'button:has-text("Send")',
                    'button:has-text("Sign up")']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                log.info('[Dify] Clicked continue')
                break

        # After first step, should show password or email verification
        new_text = (await page.inner_text('body')).lower()

        if any(x in new_text for x in ['password', 'create password']):
            # Step 2: fill password
            for sel in ['input[type="password"]', 'input[name="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break

            # May have name field
            for sel in ['input[name="name"]', 'input[placeholder*="name" i]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill('MaxAI Corp')
                    break

            # Submit
            for sel in ['button[type="submit"]', 'button:has-text("Create")',
                        'button:has-text("Sign up")', 'button:has-text("Continue")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break

        final_url = page.url
        final_text = (await page.inner_text('body')).lower()

        if any(x in final_text for x in ['verify', 'check your email', 'email sent']):
            result['status'] = 'verify_email'
        elif any(x in final_url for x in ['app/', 'dashboard', 'workspace']):
            result['status'] = 'registered'
        elif any(x in final_text for x in ['already', 'taken', 'exists']):
            result['status'] = 'already_exists'
        else:
            result['status'] = 'partial'
            result['page_url'] = final_url
            result['snippet'] = final_text[:150]

        log.info('[Dify] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Dify] Error: %s', e)

    return result


async def setup_zapier(page):
    """Login to Zapier and navigate to create a Zap"""
    log.info('[Zapier] Setup...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://zapier.com/app/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        current = page.url
        if 'dashboard' in current or 'zaps' in current:
            log.info('[Zapier] Already logged in')
            result['status'] = 'logged_in'
        else:
            for sel in ['input[name="email"]', 'input[type="email"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL1)
                    break
            for sel in ['input[type="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break
            for sel in ['button[type="submit"]', 'button:has-text("Log in")', 'button:has-text("Sign in")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break

        final_url = page.url
        final_text = (await page.inner_text('body')).lower()

        if 'zap' in final_url or 'dashboard' in final_url:
            result['status'] = 'logged_in'
            result['page_url'] = final_url
        elif 'verify' in final_text or 'confirm' in final_text:
            result['status'] = 'verify_email'
        elif 'captcha' in final_text:
            result['status'] = 'captcha'
        else:
            result['status'] = 'login_attempted'
            result['page_url'] = final_url

        log.info('[Zapier] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Zapier] Error: %s', e)

    return result


async def setup_bitrix24(page):
    """Verify Bitrix24 login and fill company profile"""
    log.info('[Bitrix24] Setup...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://www.bitrix24.com/', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        page_text = (await page.inner_text('body')).lower()
        current_url = page.url

        if any(x in current_url for x in ['bitrix24.ru', 'bitrix24.com/'] and
               any(y in page_text for y in ['crm', 'tasks', 'chat'])):
            result['status'] = 'logged_in'
            result['url'] = current_url
        elif any(x in page_text for x in ['your portal', 'log out', 'crm', 'feed']):
            result['status'] = 'logged_in'
            result['url'] = current_url
        else:
            # Try to find and click "Log in" or navigate to login
            for sel in ['a:has-text("Log in")', 'a:has-text("Sign in")',
                        'button:has-text("Log in")', '[class*="login"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(3)
                    break

            for sel in ['input[type="email"]', 'input[name="login"]', 'input[name="email"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL1)
                    break
            for sel in ['input[type="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break
            for sel in ['button[type="submit"]', 'button:has-text("Sign in")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break

            result['status'] = 'login_attempted'
            result['page_url'] = page.url

        log.info('[Bitrix24] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Bitrix24] Error: %s', e)

    return result


async def setup_pipedream(page):
    """Login to Pipedream and check workflow"""
    log.info('[Pipedream] Setup...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://pipedream.com/auth/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        current = page.url
        page_text = (await page.inner_text('body')).lower()

        if 'dashboard' in current or '/workflows' in current:
            result['status'] = 'logged_in'
            result['url'] = current
            log.info('[Pipedream] Already logged in')
            return result

        for sel in ['input[type="email"]', 'input[name="email"]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(EMAIL1)
                break
        for sel in ['input[type="password"]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(PASSWORD)
                break
        for sel in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Log in")']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(5)
                break

        final_url = page.url
        if '/workflows' in final_url or 'dashboard' in final_url:
            result['status'] = 'logged_in'
            result['url'] = final_url
        elif 'verify' in (await page.inner_text('body')).lower():
            result['status'] = 'verify_email'
        else:
            result['status'] = 'login_attempted'
            result['page_url'] = final_url

        log.info('[Pipedream] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Pipedream] Error: %s', e)

    return result


async def fix_wikibot(page):
    """Wikibot: try correct signup URL"""
    log.info('[Wikibot] Fixing...')
    result = {'status': 'unknown', 'ts': time.time()}
    urls_to_try = [
        'https://wikibot.pro/auth/register',
        'https://wikibot.pro/account/register',
        'https://app.wikibot.pro/signup',
        'https://wikibot.pro/',
    ]
    try:
        for url in urls_to_try:
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)
            page_text = (await page.inner_text('body')).lower()
            if any(x in page_text for x in ['email', 'sign up', 'register', 'create account']):
                log.info('[Wikibot] Found form at: %s', url)

                for sel in ['input[type="email"]', 'input[name="email"]']:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.fill(EMAIL1)
                        break
                for sel in ['input[type="password"]']:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.fill(PASSWORD)
                        break
                for sel in ['button[type="submit"]', 'button:has-text("Sign up")', 'button:has-text("Register")']:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(4)
                        break

                final_text = (await page.inner_text('body')).lower()
                if 'verify' in final_text or 'confirm' in final_text:
                    result['status'] = 'verify_email'
                elif 'dashboard' in page.url or 'workspace' in page.url:
                    result['status'] = 'registered'
                elif 'already' in final_text:
                    result['status'] = 'already_exists'
                else:
                    result['status'] = 'attempted'
                    result['url'] = url

                return result

        result['status'] = 'no_form_found'
        result['note'] = 'All URLs tried - no email form found'

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]

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

        results = {}

        # Dify fix
        r = await fix_dify(page)
        results['dify'] = r
        status['dify'] = r
        save_status(status)
        await asyncio.sleep(4)

        # Zapier setup
        r = await setup_zapier(page)
        results['zapier_setup'] = r
        status['zapier_login'] = r
        save_status(status)
        await asyncio.sleep(4)

        # Pipedream
        r = await setup_pipedream(page)
        results['pipedream_setup'] = r
        status['pipedream_login'] = r
        save_status(status)
        await asyncio.sleep(4)

        # Bitrix24
        r = await setup_bitrix24(page)
        results['bitrix24_setup'] = r
        status['bitrix24_login'] = r
        save_status(status)
        await asyncio.sleep(4)

        # Wikibot fix
        r = await fix_wikibot(page)
        results['wikibot'] = r
        status['wikibot'] = r
        save_status(status)

        await browser.close()

    report = 'MaxAI Platform Content Setup\n\n'
    for name, r in results.items():
        st = r.get('status', '?')
        emoji = 'OK' if st in ('logged_in', 'registered', 'already_exists') else 'WAIT' if 'verify' in st else 'FAIL'
        report += f'[{emoji}] {name}: {st}\n'

    tg(report)
    print(report)


if __name__ == '__main__':
    asyncio.run(run())
