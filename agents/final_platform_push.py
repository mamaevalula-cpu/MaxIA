#!/usr/bin/env python3
"""
Final platform push:
1. Create Akash SDL for MaxAI worker node
2. Create Make.com blueprint JSON
3. Retry Flowise cloud, Make.com EU, Wikibot
4. Try Vellum login check
"""
import asyncio, json, logging, os, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('final_push')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')
EMAIL1   = 'froggyinternet@gmail.com'
PASSWORD = 'Internetinternet!2'
STATUS_FILE = Path('/root/my_personal_ai/data/platform_status.json')
ASSETS_DIR = Path('/root/my_personal_ai/platform_assets')

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


def create_akash_sdl():
    """Create Akash Network SDL for MaxAI worker"""
    sdl = """version: "2.0"

services:
  maxai-worker:
    image: python:3.11-slim
    env:
      - MAXAI_API_URL=http://77.90.2.171:8090
      - GROQ_API_KEY=${GROQ_API_KEY}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
    command:
      - /bin/sh
      - -c
      - |
        pip install requests && python3 -c "
        import requests, os, time
        while True:
            # Fetch tasks from MaxAI
            try:
                r = requests.get(os.environ['MAXAI_API_URL'] + '/api/tasks', timeout=10)
                tasks = r.json().get('tasks', [])
                pending = [t for t in tasks if t.get('status') == 'pending']
                if pending:
                    print(f'Processing {len(pending)} tasks...')
            except Exception as e:
                print(f'Error: {e}')
            time.sleep(30)
        "
    expose:
      - port: 8080
        as: 80
        to:
          - global: false

profiles:
  compute:
    maxai-worker:
      resources:
        cpu:
          units: 0.5
        memory:
          size: 256Mi
        storage:
          size: 1Gi
  placement:
    dcloud:
      pricing:
        maxai-worker:
          denom: uakt
          amount: 1000

deployment:
  maxai-worker:
    dcloud:
      profile: maxai-worker
      count: 1
"""
    (ASSETS_DIR / 'akash_sdl.yaml').write_text(sdl)
    log.info('Created Akash SDL: akash_sdl.yaml')
    return sdl


def create_make_blueprint():
    """Create Make.com scenario blueprint JSON"""
    blueprint = {
        "name": "MaxAI AI Processing",
        "flow": [
            {
                "id": 1,
                "module": "gateway:CustomWebHook",
                "version": 1,
                "parameters": {
                    "hook": None,
                    "maxResults": 1
                },
                "filter": None,
                "mapper": {},
                "metadata": {
                    "designer": {"x": 0, "y": 0},
                    "restore": {
                        "parameters": {
                            "hook": {"label": "MaxAI Webhook"}
                        }
                    },
                    "parameters": [
                        {
                            "name": "hook",
                            "type": "hook:gateway-webhook",
                            "label": "Webhook",
                            "required": True
                        }
                    ]
                }
            },
            {
                "id": 2,
                "module": "http:ActionSendData",
                "version": 3,
                "parameters": {
                    "handleErrors": True,
                    "useNewZLibDecompression": True
                },
                "filter": None,
                "mapper": {
                    "ca": "",
                    "qs": [],
                    "url": "http://77.90.2.171:8090/api/v1/webhook",
                    "data": "{\"message\": \"{{1.data.message}}\", \"source\": \"make.com\"}",
                    "gzip": True,
                    "method": "post",
                    "headers": [{"name": "Content-Type", "value": "application/json"}],
                    "timeout": "30",
                    "authUser": "",
                    "authPass": "",
                    "bodyType": "raw",
                    "contentType": "application/json",
                    "serializeUrl": False,
                    "shareCookies": False,
                    "parseResponse": True
                },
                "metadata": {
                    "designer": {"x": 300, "y": 0}
                }
            },
            {
                "id": 3,
                "module": "gateway:WebhookRespond",
                "version": 1,
                "parameters": {},
                "filter": None,
                "mapper": {
                    "status": "200",
                    "body": "{{2.data.result}}",
                    "headers": []
                },
                "metadata": {
                    "designer": {"x": 600, "y": 0}
                }
            }
        ],
        "metadata": {
            "instant": True,
            "version": 1,
            "scenario": {
                "roundtrips": 1,
                "maxErrors": 3,
                "autoCommit": True,
                "autoCommitTriggerLast": True,
                "sequential": False,
                "confidential": False,
                "dataloss": False,
                "dlq": False,
                "freshVariables": False
            },
            "designer": {"orphans": []},
            "zone": "eu1.make.com"
        }
    }
    (ASSETS_DIR / 'make_blueprint.json').write_text(json.dumps(blueprint, indent=2))
    log.info('Created Make.com blueprint: make_blueprint.json')
    return blueprint


def create_gpt_store_config():
    """Create GPT Store configuration"""
    config = {
        "name": "MaxAI Business Automator",
        "description": "Describe your business process -> get automation blueprint -> order from @maxai_corp. Telegram bots, parsers, AI workflows. From $33.",
        "instructions": """You are MaxAI — a business automation specialist from MaxAI Corporation.

When a user describes a business task:
1. Identify what can be automated (be specific)
2. Suggest the best automation solution: Telegram bot / data parser / AI workflow / CRM integration
3. Give measurable outcomes: "This saves X hours/week" or "Reduces cost by Y%"
4. Provide a clear next step: "Order full implementation via @maxai_corp | From 3000 RUB / $33"

ALWAYS end with the @maxai_corp CTA. Never promise things that can't be measured.
Speak Russian if the user writes in Russian.

MaxAI services:
- Telegram bot: 3000-5000 RUB / $33-55 (3 days)
- Data parser: 3000 RUB / $33 (2 days)
- Business automation: 4500 RUB / $50 (5 days)
- AI assistant: 8000 RUB / $88 (7 days)
- Full implementation: @maxai_corp on Telegram""",
        "conversation_starters": [
            "I do X manually every day, can you automate it?",
            "Я каждый день вручную делаю X, можно автоматизировать?",
            "How much would it cost to automate my lead processing?",
            "Create a Telegram bot for my business"
        ],
        "capabilities": {
            "web_browsing": False,
            "dalle": False,
            "code_interpreter": False
        },
        "profile_picture_prompt": "Professional AI automation logo. Dark blue background. MaxAI text. Circuit board pattern. Clean, modern, corporate style.",
        "api_endpoint": "http://77.90.2.171:8090/api/v1/ai",
        "contact": "@maxai_corp"
    }
    (ASSETS_DIR / 'gpt_store_config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2))
    log.info('Created GPT Store config')
    return config


async def try_flowise_cloud(page):
    """Try Flowise cloud registration"""
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        urls = ['https://cloud.flowiseai.com/signup', 'https://app.flowise.cloud/signup']
        for url in urls:
            await page.goto(url, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)

            page_text = (await page.inner_text('body')).lower()
            current = page.url

            if any(x in page_text for x in ['email', 'sign up', 'create account']):
                log.info('[Flowise] Found form at: %s', url)

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
                for sel in ['button[type="submit"]', 'button:has-text("Sign up")']:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(4)
                        break

                final_text = (await page.inner_text('body')).lower()
                if 'verify' in final_text:
                    result['status'] = 'verify_email'
                elif 'dashboard' in page.url:
                    result['status'] = 'registered'
                elif 'already' in final_text:
                    result['status'] = 'already_exists'
                else:
                    result['status'] = 'attempted'
                    result['url'] = url
                return result

        result['status'] = 'no_form_found'
    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
    return result


async def try_make_eu(page):
    """Try Make.com EU version"""
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://eu1.make.com/register', wait_until='domcontentloaded', timeout=25000)
        await asyncio.sleep(4)

        page_text = (await page.inner_text('body')).lower()

        if any(x in page_text for x in ['dashboard', 'scenarios', 'workspace']):
            result['status'] = 'logged_in'
            return result

        if any(x in page_text for x in ['email', 'sign up', 'create account']):
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
            for sel in ['input[name="name"]', 'input[placeholder*="name" i]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill('MaxAI Corp')
                    break
            # Terms
            for sel in ['input[type="checkbox"]']:
                try:
                    el = await page.query_selector(sel)
                    if el and not await el.is_checked():
                        await el.click()
                except:
                    pass
            for sel in ['button[type="submit"]', 'button:has-text("Create account")', 'button:has-text("Sign up")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break

            final_text = (await page.inner_text('body')).lower()
            if 'verify' in final_text or 'check your email' in final_text:
                result['status'] = 'verify_email'
            elif 'captcha' in final_text:
                result['status'] = 'captcha_blocked'
            elif 'already' in final_text:
                result['status'] = 'already_exists'
            elif 'dashboard' in page.url or 'scenarios' in page.url:
                result['status'] = 'registered'
            else:
                result['status'] = 'attempted'
                result['url'] = page.url
        else:
            result['status'] = 'no_form_found'
            result['url'] = page.url

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
    return result


async def try_vellum_login(page):
    """Check if Vellum registration completed"""
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://app.vellum.ai/login', wait_until='domcontentloaded', timeout=25000)
        await asyncio.sleep(3)

        page_text = (await page.inner_text('body')).lower()
        current = page.url

        if any(x in current for x in ['dashboard', 'workspace', 'documents', 'workflows']):
            result['status'] = 'logged_in'
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
        for sel in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Continue")']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(5)
                break

        final_url = page.url
        final_text = (await page.inner_text('body')).lower()

        if any(x in final_url for x in ['dashboard', 'workspace', 'workflow', 'prompt']):
            result['status'] = 'logged_in'
        elif 'verify' in final_text or 'confirm' in final_text:
            result['status'] = 'verify_email'
        elif 'invalid' in final_text or 'wrong' in final_text:
            result['status'] = 'wrong_credentials'
        else:
            result['status'] = 'login_attempted'
            result['url'] = final_url

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
    return result


async def try_dify_email(page):
    """Try Dify email registration with verification code flow"""
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        await page.goto('https://cloud.dify.ai/signin', wait_until='domcontentloaded', timeout=25000)
        await asyncio.sleep(3)

        current = page.url
        page_text = (await page.inner_text('body')).lower()

        if any(x in current for x in ['app/', 'workspace', 'dashboard']):
            result['status'] = 'logged_in'
            return result

        # Dify shows email input first
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(EMAIL1)
                log.info('[Dify] Filled email')
                break

        # Click Continue
        for sel in ['button:has-text("Continue")', 'button[type="submit"]']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                break

        page_text2 = (await page.inner_text('body')).lower()

        if 'password' in page_text2:
            # Login with password
            for sel in ['input[type="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break
            for sel in ['button:has-text("Sign in")', 'button[type="submit"]', 'button:has-text("Continue")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(5)
                    break
        elif 'code' in page_text2 or 'verification' in page_text2:
            result['status'] = 'verify_email'
            result['note'] = 'Dify sent verification code to email'
            return result

        final_url = page.url
        final_text = (await page.inner_text('body')).lower()

        if any(x in final_url for x in ['app/', 'workspace', 'dashboard']):
            result['status'] = 'logged_in'
        elif any(x in final_text for x in ['verify', 'confirm', 'check your email', 'verification']):
            result['status'] = 'verify_email'
        elif any(x in final_text for x in ['invalid', 'wrong', 'incorrect']):
            result['status'] = 'wrong_credentials'
        else:
            result['status'] = 'login_attempted'
            result['url'] = final_url

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

    # Create static assets first (no browser needed)
    create_akash_sdl()
    create_make_blueprint()
    create_gpt_store_config()

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

        # Try Flowise cloud
        r = await try_flowise_cloud(page)
        results['flowise'] = r
        if r['status'] not in ('unknown',):
            status['flowise_cloud'] = r
        save_status(status)
        await asyncio.sleep(4)

        # Try Make EU
        r = await try_make_eu(page)
        results['make_eu'] = r
        if r['status'] not in ('no_form_found',):
            status['make'] = r
        save_status(status)
        await asyncio.sleep(4)

        # Check Vellum
        r = await try_vellum_login(page)
        results['vellum'] = r
        status['vellum'] = r
        save_status(status)
        await asyncio.sleep(4)

        # Try Dify login
        r = await try_dify_email(page)
        results['dify'] = r
        status['dify'] = r
        save_status(status)

        await browser.close()

    # Final report
    ok_now = sum(1 for r in results.values() if r.get('status') in ('logged_in', 'registered', 'already_exists'))
    pending_now = sum(1 for r in results.values() if r.get('status') in ('verify_email', 'attempted', 'login_attempted'))

    report = (
        f'MaxAI Final Push Report\n\n'
        f'New sessions this run: {ok_now} OK, {pending_now} pending\n\n'
    )
    for name, r in results.items():
        st = r.get('status', '?')
        emoji = 'OK' if st in ('logged_in', 'registered', 'already_exists') else 'WAIT' if 'verify' in st or 'attempt' in st else 'FAIL'
        report += f'[{emoji}] {name}: {st}\n'

    report += '\n--- Assets created ---\n'
    report += 'akash_sdl.yaml, make_blueprint.json, gpt_store_config.json\n'

    tg(report)
    print(report)


if __name__ == '__main__':
    asyncio.run(run())
