#!/usr/bin/env python3
"""
1. Check Gmail for platform verification emails
2. Set up Bitrix24 webhook to MaxAI API
"""
import asyncio, json, logging, os, imaplib, email, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('email_setup')

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


def check_gmail_verification():
    """Check Gmail for platform verification emails via IMAP"""
    log.info('[Gmail] Checking for verification emails...')
    results = {}

    try:
        # Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(EMAIL1, PASSWORD)
        mail.select('INBOX')

        # Search for recent unread emails from platform providers
        status, messages = mail.search(None, 'UNSEEN')
        if status != 'OK':
            log.warning('[Gmail] Could not search inbox')
            mail.close()
            mail.logout()
            return {'error': 'search failed'}

        message_ids = messages[0].split() if messages[0] else []
        log.info('[Gmail] Found %d unread emails', len(message_ids))

        # Keywords to look for from platforms
        platform_keywords = {
            'n8n': 'n8n',
            'dify': 'dify',
            'relevance': 'relevance',
            'langflow': 'langflow',
            'vellum': 'vellum',
            'huggingface': 'huggingface',
            'zapier': 'zapier',
            'make': 'make.com',
            'bitrix24': 'bitrix24',
            'pipedream': 'pipedream',
        }

        # Check last 20 emails
        for msg_id in message_ids[-20:]:
            try:
                _, msg_data = mail.fetch(msg_id, '(RFC822)')
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                from_addr = msg.get('From', '').lower()
                subject = msg.get('Subject', '').lower()

                # Check which platform this is from
                for platform, keyword in platform_keywords.items():
                    if keyword in from_addr or keyword in subject:
                        results[platform] = {
                            'from': msg.get('From', ''),
                            'subject': msg.get('Subject', ''),
                            'date': msg.get('Date', ''),
                            'has_verification': any(x in subject for x in ['verify', 'confirm', 'activate', 'welcome'])
                        }
                        log.info('[Gmail] Found %s email: %s', platform, subject)
                        break

            except Exception as e:
                log.warning('[Gmail] Error reading email: %s', e)

        mail.close()
        mail.logout()
        log.info('[Gmail] Checked. Found emails for: %s', list(results.keys()))

    except imaplib.IMAP4.error as e:
        results['imap_error'] = str(e)
        log.error('[Gmail] IMAP error: %s', e)
        # This is likely because Gmail needs app password or has security restrictions
    except Exception as e:
        results['error'] = str(e)
        log.error('[Gmail] Error: %s', e)

    return results


async def setup_bitrix24_webhook(page):
    """Set up MaxAI webhook in Bitrix24 portal"""
    log.info('[Bitrix24] Setting up MaxAI webhook...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        # Navigate to Bitrix24 portal (bitrix24.de or .com)
        portal_urls = [
            'https://www.bitrix24.de/',
            'https://froggyinternet.bitrix24.de/',
            'https://maxai.bitrix24.de/',
        ]

        for portal_url in portal_urls:
            try:
                await page.goto(portal_url, wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(3)

                page_text = (await page.inner_text('body')).lower()
                current_url = page.url

                if any(x in page_text for x in ['crm', 'tasks', 'feed', 'calendar', 'chat']) and 'bitrix24' in current_url:
                    log.info('[Bitrix24] Found portal at: %s', current_url)
                    result['portal_url'] = current_url
                    break
            except:
                pass

        if not result.get('portal_url'):
            # Try login
            await page.goto('https://www.bitrix24.com/login/', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)

            for sel in ['input[name="USER_LOGIN"]', 'input[type="email"]', 'input[name="login"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL1)
                    break

            for sel in ['input[type="password"]', 'input[name="USER_PASSWORD"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break

            for sel in ['button[type="submit"]', 'input[type="submit"]']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break

            result['portal_url'] = page.url

        # Try to set up webhook - navigate to REST API settings
        current = result.get('portal_url', '')
        if current and 'bitrix24' in current:
            base = current.split('/')[0] + '//' + current.split('/')[2]
            webhook_url = base + '/devops/edit/webhook/add/'

            try:
                await page.goto(webhook_url, wait_until='domcontentloaded', timeout=15000)
                await asyncio.sleep(3)

                webhook_text = (await page.inner_text('body')).lower()
                if any(x in webhook_text for x in ['webhook', 'incoming', 'rest api']):
                    log.info('[Bitrix24] Found webhook creation page')
                    result['webhook_page'] = page.url
                    result['status'] = 'logged_in_webhook_found'
                else:
                    result['status'] = 'logged_in'
            except Exception as e:
                result['status'] = 'logged_in'
                log.warning('[Bitrix24] Webhook page error: %s', e)
        else:
            result['status'] = 'portal_not_found'

        log.info('[Bitrix24] Result: %s | Portal: %s', result['status'], result.get('portal_url', ''))

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Bitrix24] Error: %s', e)

    return result


async def setup_zapier_retry(page):
    """Retry Zapier login with different approach"""
    log.info('[Zapier] Retry login...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        # Try the actual login page
        await page.goto('https://zapier.com/app/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(4)

        current = page.url
        page_text = (await page.inner_text('body')).lower()

        if any(x in page_text for x in ['zap', 'dashboard', 'workflow']):
            result['status'] = 'logged_in'
            result['url'] = current
            log.info('[Zapier] Already logged in at: %s', current)
            return result

        # Look for "Continue with Google" - but we need Google login
        # Instead try direct email
        for sel in ['input[name="email"]', 'input[type="email"]', 'input[placeholder*="email" i]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(EMAIL1)
                log.info('[Zapier] Filled email')
                break

        # Click continue
        for sel in ['button:has-text("Continue")', 'button[type="submit"]', 'button:has-text("Log in")']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                break

        # Now should show password or 2FA
        page_text2 = (await page.inner_text('body')).lower()
        current2 = page.url

        if 'password' in page_text2:
            for sel in ['input[type="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break
            for sel in ['button[type="submit"]', 'button:has-text("Continue")', 'button:has-text("Log in")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break

        final_url = page.url
        final_text = (await page.inner_text('body')).lower()

        if any(x in final_url for x in ['zaps', 'dashboard', 'app/']):
            result['status'] = 'logged_in'
            result['url'] = final_url
        elif 'verify' in final_text or '2fa' in final_text or 'code' in final_text:
            result['status'] = 'needs_2fa'
            result['note'] = 'Check email for verification code'
        elif any(x in final_text for x in ['invalid', 'wrong', 'incorrect']):
            result['status'] = 'wrong_password'
        else:
            result['status'] = 'login_attempted'
            result['url'] = final_url

        log.info('[Zapier] Result: %s', result['status'])

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Zapier] Error: %s', e)

    return result


async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa
        USE_STEALTH = True
    except:
        USE_STEALTH = False

    status = load_status()
    results = {}

    # Check Gmail first
    gmail_results = check_gmail_verification()
    results['gmail_check'] = gmail_results
    status['gmail_verification_check'] = gmail_results
    save_status(status)

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

        # Bitrix24 setup
        r = await setup_bitrix24_webhook(page)
        results['bitrix24_setup'] = r
        status['bitrix24_setup'] = r
        save_status(status)
        await asyncio.sleep(5)

        # Zapier retry
        r = await setup_zapier_retry(page)
        results['zapier_retry'] = r
        status['zapier_retry'] = r
        save_status(status)

        await browser.close()

    report = 'MaxAI Setup Report\n\n'
    report += f'Gmail check: {len(gmail_results)} platform emails found\n'
    for platform, info in gmail_results.items():
        if isinstance(info, dict) and info.get('subject'):
            report += f'  {platform}: {info.get("subject","")[:40]}\n'
    report += f'\nBitrix24: {results.get("bitrix24_setup", {}).get("status", "?")}'
    if results.get("bitrix24_setup", {}).get("portal_url"):
        report += f' ({results["bitrix24_setup"]["portal_url"][:50]})'
    report += f'\nZapier: {results.get("zapier_retry", {}).get("status", "?")}\n'

    tg(report)
    print(report)


if __name__ == '__main__':
    asyncio.run(run())
