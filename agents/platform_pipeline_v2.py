#!/usr/bin/env python3
"""
platform_pipeline_v2.py — Расширенная регистрация на платформах
Добавлены: Zapier, Make, Bitrix24, Poe
Исправлены: Dify, Pipedream, Flowise, Wikibot (новые селекторы)
"""
import asyncio, json, logging, os, time, random
from pathlib import Path
from datetime import datetime

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/platform_pipeline_v2.log')
    ]
)
log = logging.getLogger('platform_v2')

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

async def try_register(page, name, url, email, password, extra_selectors=None):
    result = {'status': 'unknown', 'url': url, 'email': email, 'ts': time.time()}
    try:
        log.info('[%s] Opening %s', name, url)
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(4)

        page_text = (await page.inner_text('body'))[:1000].lower()

        # Already logged in?
        if any(x in page_text for x in ['dashboard', 'workspace', 'logout', 'sign out', 'welcome back']):
            result['status'] = 'logged_in'
            log.info('[%s] Already logged in', name)
            return result

        # Try email input (extended selectors)
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[name="username"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="mail" i]',
            'input[id*="email" i]',
            '#email', '#Email', '#user_email',
        ]
        email_filled = False
        for sel in email_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.clear()
                    await el.fill(email)
                    email_filled = True
                    log.info('[%s] Filled email with: %s', name, sel)
                    break
            except:
                pass

        # Fill password
        pass_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            'input[id*="pass" i]',
            '#password',
        ]
        for sel in pass_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.clear()
                    await el.fill(password)
                    break
            except:
                pass

        # Fill name if present
        for sel in ['input[name="name"]', 'input[name="firstName"]', 'input[name="first_name"]',
                    'input[placeholder*="name" i]', 'input[placeholder*="Name"]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill('MaxAI Corp')
                    break
            except:
                pass

        # Checkbox (TOS)
        for sel in ['input[type="checkbox"]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and not await el.is_checked():
                    await el.click()
            except:
                pass

        # Submit button (extended list)
        btn_selectors = [
            'button[type="submit"]',
            'button:has-text("Sign up")',
            'button:has-text("Sign Up")',
            'button:has-text("Register")',
            'button:has-text("Create account")',
            'button:has-text("Create Account")',
            'button:has-text("Get started")',
            'button:has-text("Get Started")',
            'button:has-text("Continue")',
            'button:has-text("Next")',
            'input[type="submit"]',
            '[data-testid*="signup"]',
            '[data-testid*="register"]',
        ]
        clicked = False
        for btn_sel in btn_selectors:
            try:
                btn = await page.query_selector(btn_sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    clicked = True
                    log.info('[%s] Clicked: %s', name, btn_sel)
                    break
            except:
                pass

        if not clicked and email_filled:
            # Try pressing Enter
            await page.keyboard.press('Enter')

        await asyncio.sleep(6)

        new_url = page.url
        new_text = (await page.inner_text('body'))[:1000].lower()

        if any(x in new_url.lower() for x in ['dashboard', 'workspace', 'home', 'app', 'onboard']):
            result['status'] = 'registered'
            log.info('[%s] REGISTERED! URL: %s', name, new_url)
        elif any(x in new_text for x in ['verify your email', 'check your email', 'confirmation email',
                                          'email sent', 'verify email', 'confirm your email']):
            result['status'] = 'verify_email'
            result['note'] = 'Check email for verification'
            log.info('[%s] Needs email verification', name)
        elif any(x in new_text for x in ['captcha', 'robot', 'cloudflare', 'access denied']):
            result['status'] = 'captcha_blocked'
            log.warning('[%s] CAPTCHA blocked', name)
        elif any(x in new_text for x in ['already exists', 'already registered', 'email taken',
                                          'already have an account', 'email is already']):
            result['status'] = 'already_exists'
            log.info('[%s] Account already exists', name)
        elif not email_filled:
            result['status'] = 'no_form_found'
            result['note'] = 'No email input found - likely OAuth-only'
            log.warning('[%s] No registration form found', name)
        else:
            result['status'] = 'unknown'
            result['page_url'] = new_url
            result['page_snippet'] = new_text[:200]
            log.info('[%s] Unknown. URL: %s', name, new_url)

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[%s] Error: %s', name, e)

    return result


async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa
        USE_STEALTH = True
        log.info('Stealth mode enabled')
    except:
        USE_STEALTH = False

    status = load_status()

    # NEW + RETRY platforms (skip already successful)
    # Format: (name, url, email, password)
    platforms = [
        # RETRY: failed ones with better selectors
        ('dify', 'https://cloud.dify.ai/signin', EMAIL1, PASSWORD),
        ('pipedream', 'https://pipedream.com/auth/signup', EMAIL1, PASSWORD),
        ('flowise_cloud', 'https://flowiseai.com/cloud', EMAIL1, PASSWORD),
        ('wikibot', 'https://wikibot.pro/register', EMAIL1, PASSWORD),
        ('vellum_check', 'https://app.vellum.ai/login', EMAIL1, PASSWORD),
        # NEW platforms
        ('zapier', 'https://zapier.com/sign-up', EMAIL1, PASSWORD),
        ('make', 'https://www.make.com/en/register', EMAIL1, PASSWORD),
        ('bitrix24', 'https://www.bitrix24.com/create.php', EMAIL1, PASSWORD),
        ('poe', 'https://poe.com/login', EMAIL2, PASSWORD2),
    ]

    results = {}
    verified = []
    failed = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled',
                  '--disable-web-security']
        )
        ctx = await browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent=(
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/122.0.0.0 Safari/537.36'
            ),
            locale='en-US',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await sa(page)

        for name, url, email, pwd in platforms:
            # Skip if already done successfully
            current_status = status.get(name, {}).get('status', '')
            if current_status in ('registered', 'logged_in', 'verify_email', 'already_exists'):
                log.info('[%s] Already done: %s — skip', name, current_status)
                results[name] = status[name]
                verified.append(f'{name}({current_status})')
                continue

            result = await try_register(page, name, url, email, pwd)
            results[name] = result
            status[name] = result

            if result['status'] in ('registered', 'logged_in', 'already_exists'):
                verified.append(name)
            elif result['status'] == 'verify_email':
                verified.append(f'{name}(email)')
            else:
                failed.append(f'{name}:{result["status"]}')

            save_status(status)
            await asyncio.sleep(random.uniform(4, 8))

        await browser.close()

    # Build final report
    all_ok = sum(1 for r in status.values() if r.get('status') in ('registered', 'logged_in', 'verify_email', 'already_exists'))
    total = len(status)

    msg = (
        f'MaxAI Platforms v2 — {datetime.utcnow().strftime("%H:%M UTC")}\n\n'
        f'Total tracked: {total}\n'
        f'OK/Pending verify: {all_ok}\n\n'
        f'This run:\n'
        f'OK: {", ".join(verified) or "none"}\n'
        f'Fail: {", ".join(failed) or "none"}\n\n'
        f'Full status:\n'
    )
    for pname, r in sorted(status.items()):
        st = r.get('status', '?')
        emoji = ('✅' if st in ('registered', 'logged_in')
                 else '📧' if st == 'verify_email'
                 else '♻️' if st == 'already_exists'
                 else '❌')
        msg += f'{emoji} {pname}: {st}\n'

    tg(msg[:4000])
    log.info('v2 done. OK: %d/%d', all_ok, total)
    print(msg)


if __name__ == '__main__':
    asyncio.run(run())
