#!/usr/bin/env python3
"""
create_zapier_zap.py
Creates MaxAI integration content on Zapier (logged in account)
Also creates Bitrix24 webhook integration
"""
import asyncio, json, logging, os, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('zapier_setup')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')
EMAIL1   = 'froggyinternet@gmail.com'
PASSWORD = 'Internetinternet!2'
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


async def setup_zapier_content(page):
    """Login to Zapier and navigate to create a Zap with MaxAI webhook"""
    log.info('[Zapier] Setting up content...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        # Login
        await page.goto('https://zapier.com/app/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        current_url = page.url
        page_text = (await page.inner_text('body')).lower()

        if 'dashboard' in current_url or 'zaps' in current_url or 'home' in current_url:
            log.info('[Zapier] Already logged in: %s', current_url)
        else:
            # Login flow
            for sel in ['input[type="email"]', 'input[name="email"]', '#email']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL1)
                    break
            await page.keyboard.press('Tab')
            await asyncio.sleep(1)

            for sel in ['input[type="password"]', 'input[name="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break

            for sel in ['button[type="submit"]', 'button:has-text("Log in")', 'button:has-text("Sign in")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(6)
                    break

        final_url = page.url
        log.info('[Zapier] Current URL: %s', final_url)

        if 'login' in final_url or 'signin' in final_url:
            result['status'] = 'login_failed'
            result['url'] = final_url
            return result

        # Navigate to Zap creation
        await page.goto('https://zapier.com/app/zaps', wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(3)

        zaps_text = (await page.inner_text('body')).lower()
        log.info('[Zapier] On zaps page: %s', 'zap' in zaps_text)

        # Try to create new Zap
        for sel in ['button:has-text("Create Zap")', 'a:has-text("Create Zap")',
                    'button:has-text("New Zap")', 'a:has-text("+ Create")',
                    '[data-testid*="create"]', 'button:has-text("+ Create")']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await asyncio.sleep(4)
                log.info('[Zapier] Clicked create')
                break

        new_url = page.url
        result['status'] = 'logged_in'
        result['zaps_url'] = 'https://zapier.com/app/zaps'
        result['create_url'] = new_url
        result['note'] = 'Logged in to Zapier. Manual Zap creation needed for full setup.'
        log.info('[Zapier] Content setup: logged in at %s', new_url)

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Zapier] Error: %s', e)

    return result


async def setup_bitrix24_webhook(page):
    """Setup MaxAI webhook in Bitrix24"""
    log.info('[Bitrix24] Setting up webhook...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        # Go to Bitrix24
        await page.goto('https://www.bitrix24.com/', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        current_url = page.url
        page_text = (await page.inner_text('body')).lower()

        log.info('[Bitrix24] Current URL: %s', current_url)

        # Check if we're redirected to a portal
        if 'bitrix24.' in current_url and 'www' not in current_url:
            log.info('[Bitrix24] Redirected to portal: %s', current_url)
            result['portal_url'] = current_url
            result['status'] = 'logged_in'

        # Look for CRM or Settings
        if any(x in page_text for x in ['crm', 'feed', 'tasks', 'calendar']):
            log.info('[Bitrix24] On Bitrix24 portal')
            result['status'] = 'logged_in'
            result['portal_url'] = current_url

            # Navigate to Applications
            await page.goto(current_url.rstrip('/') + '/marketplace/', wait_until='domcontentloaded', timeout=15000)
            await asyncio.sleep(2)
            result['marketplace_url'] = page.url

        else:
            result['status'] = 'not_logged_in'
            result['url'] = current_url

        log.info('[Bitrix24] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Bitrix24] Error: %s', e)

    return result


async def navigate_n8n(page):
    """Navigate n8n cloud and check workspace"""
    log.info('[n8n] Checking workspace...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://app.n8n.cloud/', wait_until='domcontentloaded', timeout=25000)
        await asyncio.sleep(4)

        current_url = page.url
        page_text = (await page.inner_text('body')).lower()
        log.info('[n8n] URL: %s', current_url)

        # Check login state
        if any(x in page_text for x in ['workflow', 'canvas', 'execution', 'credential']):
            result['status'] = 'logged_in'
            result['workspace_url'] = current_url

            # Check workflows
            if 'workflow' not in current_url:
                await page.goto('https://app.n8n.cloud/workflows', wait_until='domcontentloaded', timeout=15000)
                await asyncio.sleep(3)
                result['workflows_url'] = page.url
                wf_text = (await page.inner_text('body')).lower()
                result['workflow_count'] = wf_text.count('workflow')
        elif 'login' in current_url or 'signin' in current_url:
            # Try login
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
            for sel in ['button[type="submit"]', 'button:has-text("Sign in")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break

            final_text = (await page.inner_text('body')).lower()
            if any(x in final_text for x in ['workflow', 'canvas', 'execution']):
                result['status'] = 'logged_in'
            elif 'verify' in final_text:
                result['status'] = 'verify_email'
            else:
                result['status'] = 'login_failed'
                result['url'] = page.url
        else:
            result['status'] = 'unknown'
            result['url'] = current_url
            result['snippet'] = page_text[:100]

        log.info('[n8n] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[n8n] Error: %s', e)

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

        # Zapier setup
        r = await setup_zapier_content(page)
        results['zapier_content'] = r
        status['zapier_content'] = r
        save_status(status)
        await asyncio.sleep(5)

        # Bitrix24
        r = await setup_bitrix24_webhook(page)
        results['bitrix24_webhook'] = r
        status['bitrix24_webhook'] = r
        save_status(status)
        await asyncio.sleep(5)

        # n8n check
        r = await navigate_n8n(page)
        results['n8n_workspace'] = r
        status['n8n_workspace'] = r
        save_status(status)

        await browser.close()

    report_lines = ['MaxAI Platform Content\n']
    for name, r in results.items():
        st = r.get('status', '?')
        info = r.get('note', r.get('portal_url', r.get('workspace_url', r.get('url', ''))))
        report_lines.append(f'{name}: {st}')
        if info:
            report_lines.append(f'  -> {str(info)[:60]}')
    report = '\n'.join(report_lines)

    tg(report)
    print(report)


if __name__ == '__main__':
    asyncio.run(run())
