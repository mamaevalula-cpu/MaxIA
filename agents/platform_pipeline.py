#!/usr/bin/env python3
"""
platform_pipeline.py — Регистрация и публикация на 20 платформах
Порядок: n8n → Dify → Relevance AI → Pipedream → Vellum → HF → GitHub → ...
Запуск: один раз, результаты в /root/my_personal_ai/data/platform_status.json
"""
import asyncio, json, logging, os, time, random
from pathlib import Path
from datetime import datetime

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler('/root/my_personal_ai/logs/platform_pipeline.log')])
log = logging.getLogger('platform')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')
EMAIL1   = 'froggyinternet@gmail.com'
EMAIL2   = 'jimmorrisoninlove@gmail.com'
PASSWORD = 'Internetinternet!2'
PASSWORD2 = 'Fukcyoubithc48'

STATUS_FILE = Path('/root/my_personal_ai/data/platform_status.json')

PACK_DESC = (
    "MaxAI provides AI automation services: "
    "Telegram bot development, data parsing, business automation, AI assistant integration. "
    "API: http://77.90.2.171:8090/api/v1/packs"
)

PACK_DESC_RU = (
    "Корпорация MaxAI — AI автоматизация: "
    "Telegram боты, парсеры, автоматизация бизнеса, AI-ассистенты. "
    "От 3000 руб. Контакт: @maxai_corp"
)

def tg(text):
    import urllib.request as ur
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type': 'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except:
        return {}

def save_status(s):
    STATUS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

async def try_register_platform(page, platform_name, url, email, password, extra=None):
    """Generic registration attempt for a platform."""
    result = {'status': 'unknown', 'url': url, 'email': email, 'ts': time.time()}
    try:
        log.info('[%s] Loading %s...', platform_name, url)
        await page.goto(url, wait_until='domcontentloaded', timeout=25000)
        await asyncio.sleep(3)

        page_text = (await page.inner_text('body'))[:500]

        # Detect if already logged in
        if any(x in page_text.lower() for x in ['dashboard', 'workspace', 'logout', 'sign out', 'выйти']):
            result['status'] = 'logged_in'
            log.info('[%s] Already logged in!', platform_name)
            return result

        # Find email input
        email_filled = False
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="mail"]',
                    'input[placeholder*="Email"]', 'input[name="username"]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(email)
                email_filled = True
                break

        # Find password input
        for sel in ['input[type="password"]', 'input[name="password"]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(password)
                break

        # Fill name if present
        for sel in ['input[name="name"]', 'input[placeholder*="Name"]', 'input[placeholder*="name"]',
                    'input[name="firstName"]', 'input[name="first_name"]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill('MaxAI Corp')
                break

        # Check for TOS checkbox
        for sel in ['input[type="checkbox"]', '[class*="terms"], [class*="agree"]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible() and not await el.is_checked():
                    await el.click()
            except:
                pass

        # Click submit/register button
        for btn_sel in ['button[type="submit"]', 'button:has-text("Sign Up")', 'button:has-text("Register")',
                        'button:has-text("Create")', 'button:has-text("Get Started")',
                        'button:has-text("Зарегистрироваться")', 'button:has-text("Создать аккаунт")']:
            try:
                btn = await page.query_selector(btn_sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    break
            except:
                pass

        await asyncio.sleep(5)
        new_url = page.url
        new_text = (await page.inner_text('body'))[:500]

        # Analyze result
        if any(x in new_url.lower() for x in ['dashboard', 'workspace', 'home', 'app']):
            result['status'] = 'registered'
            log.info('[%s] REGISTERED! URL: %s', platform_name, new_url)
        elif any(x in new_text.lower() for x in ['verify', 'confirm', 'email sent', 'check your email']):
            result['status'] = 'verify_email'
            result['note'] = 'Email verification required'
            log.info('[%s] Needs email verification', platform_name)
        elif any(x in new_text.lower() for x in ['captcha', 'robot', 'human', 'cloudflare']):
            result['status'] = 'captcha_blocked'
            log.warning('[%s] CAPTCHA blocked', platform_name)
        elif any(x in new_text.lower() for x in ['already exists', 'already registered', 'email taken']):
            result['status'] = 'already_exists'
            log.info('[%s] Account already exists', platform_name)
        elif not email_filled:
            result['status'] = 'no_form_found'
            log.warning('[%s] No registration form found', platform_name)
        else:
            result['status'] = 'unknown'
            result['page_url'] = new_url
            log.info('[%s] Unknown result. URL: %s', platform_name, new_url)

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[%s] Error: %s', platform_name, e)

    return result

async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa; USE_STEALTH = True
    except:
        USE_STEALTH = False

    status = load_status()

    # Platform list with registration URLs
    platforms = [
        # (name, url, email, password)
        ('n8n_cloud',      'https://app.n8n.cloud/register',           EMAIL1, PASSWORD),
        ('dify',           'https://cloud.dify.ai/sign-up',             EMAIL1, PASSWORD),
        ('relevance_ai',   'https://app.relevanceai.com/signup',        EMAIL1, PASSWORD),
        ('pipedream',      'https://pipedream.com/auth/signup',         EMAIL1, PASSWORD),
        ('vellum',         'https://app.vellum.ai/signup',              EMAIL1, PASSWORD),
        ('coze',           'https://www.coze.com/signup',               EMAIL2, PASSWORD2),
        ('flowise_cloud',  'https://flowiseai.com/',                     EMAIL1, PASSWORD),
        ('langflow_cloud', 'https://app.langflow.org/',                  EMAIL1, PASSWORD),
        ('nodul',          'https://nodul.com/signup',                   EMAIL1, PASSWORD),
        ('targetai',       'https://app.targetai.ru/register',           EMAIL1, PASSWORD),
        ('wikibot',        'https://wikibot.pro/signup',                 EMAIL1, PASSWORD),
    ]

    results = {}
    failed = []
    verified = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            viewport={'width': 1366, 'height': 768},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await sa(page)

        for name, url, email, pwd in platforms:
            # Skip if already successfully registered
            if status.get(name, {}).get('status') in ('registered', 'logged_in', 'verify_email'):
                log.info('[%s] Already done: %s', name, status[name]['status'])
                results[name] = status[name]
                continue

            result = await try_register_platform(page, name, url, email, pwd)
            results[name] = result
            status[name] = result

            if result['status'] in ('registered', 'logged_in'):
                verified.append(name)
            elif result['status'] == 'verify_email':
                verified.append(f"{name}(verify)")
            else:
                failed.append(f"{name}:{result['status']}")

            save_status(status)
            await asyncio.sleep(random.uniform(3, 6))

        await browser.close()

    # Summary report
    success_count = sum(1 for r in results.values() if r.get('status') in ('registered', 'logged_in', 'verify_email', 'already_exists'))
    msg = (
        f"Платформы — отчёт {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
        f"Попытки: {len(results)}\n"
        f"Успешно/на проверке: {success_count}\n\n"
        f"✅ OK: {', '.join(verified)}\n"
        f"❌ Fail: {', '.join(failed)}\n\n"
        f"Статусы:\n"
    )
    for name, r in results.items():
        emoji = '✅' if r.get('status') in ('registered','logged_in') else '📧' if r.get('status') == 'verify_email' else '❌'
        msg += f"{emoji} {name}: {r.get('status')}\n"
    tg(msg[:4000])
    log.info('Platform pipeline done. Success: %d/%d', success_count, len(results))

if __name__ == '__main__':
    asyncio.run(run())
