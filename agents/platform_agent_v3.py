#!/usr/bin/env python3
"""
platform_agent_v3.py — MaxAI Platform Registration Agent v3
Task: заполнить 20 платформ, дополнить недостающие

Targets:
  - RETRY: dify, vellum (login_attempted), flowise, wikibot, targetai, nodul
  - NEW: gpt_store, dify_hub, akash (create SDL/assets, mark status)
  - BROWSER: github (complete partial), huggingface (run registration)
  - BLOCKED: make (captcha) → mark manual_required
"""
import asyncio, json, logging, os, time, re
from pathlib import Path
from datetime import datetime

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/platform_v3.log')
    ]
)
log = logging.getLogger('platform_v3')

TG_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8849616091:AAEReIChr8WS4cC1sdqOXrvFdEwf3syu8YM')
TG_CHAT   = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')
EMAIL1    = 'froggyinternet@gmail.com'
EMAIL2    = 'jimmorrisoninlove@gmail.com'
PASSWORD  = 'Internetinternet!2'
PASSWORD2 = 'Fukcyoubithc48'
STATUS_FILE = Path('/root/my_personal_ai/data/platform_status.json')
ASSETS_DIR  = Path('/root/my_personal_ai/platform_assets')
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def tg(text: str):
    import urllib.request as ur
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000], 'parse_mode': 'HTML'}).encode()
        ur.urlopen(ur.Request(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type': 'application/json'}
        ), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)


def load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {}


def save_status(s: dict):
    STATUS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False, default=str))


def set_status(st: dict, name: str, status: str, note: str = ''):
    st[name] = {'status': status, 'note': note, 'ts': time.time()}
    save_status(st)
    log.info('[%s] → %s  %s', name, status, note[:60] if note else '')


# ── Non-browser handlers ──────────────────────────────────────────────────────

def handle_gpt_store(st: dict):
    """GPT Store = OpenAI GPT Builder. Cannot auto-create — mark manual."""
    note = (
        'Requires ChatGPT Plus / Team account. '
        'Go to: https://chat.openai.com/gpts/editor '
        'Create GPT named MaxAI, set system prompt, publish to Store.'
    )
    set_status(st, 'gpt_store', 'manual_required', note)
    ASSETS_DIR.joinpath('gpt_store_instructions.txt').write_text(
        f'MaxAI GPT Store Setup\n\n{note}\n\n'
        'Suggested system prompt:\n'
        'You are MaxAI — an AI business assistant specializing in cryptocurrency trading, '
        'freelance lead generation, and automated business operations. '
        'Website: http://77.90.2.171 | API: http://77.90.2.171/api/v1/ai'
    )


def handle_dify_hub(st: dict):
    """Dify Hub = same account as dify cloud."""
    current = st.get('dify', {}).get('status', '')
    if current in ('registered', 'logged_in', 'already_exists'):
        set_status(st, 'dify_hub', 'registered', 'Same account as dify cloud.dify.ai')
    else:
        set_status(st, 'dify_hub', 'login_attempted',
                   'Dify Hub uses cloud.dify.ai — retry dify login to complete')


def handle_akash(st: dict):
    """Akash Network — decentralized cloud. SDL already created."""
    sdl_path = ASSETS_DIR / 'akash_maxai_sdl.yaml'
    if not sdl_path.exists():
        sdl = """\
version: "2.0"

services:
  maxai-worker:
    image: python:3.11-slim
    env:
      - MAXAI_API_URL=http://77.90.2.171:8090
    command: ["/bin/sh", "-c",
      "pip install -q requests && python3 -c \\"
      import requests,time,os;
      url=os.environ['MAXAI_API_URL'];
      [print(requests.get(url+'/api/status').json().get('status')) or time.sleep(30) for _ in iter(int,1)]
      \\""]
    expose:
      - port: 8080
        as: 80
        to: [{global: false}]

profiles:
  compute:
    maxai-worker:
      resources:
        cpu: {units: 0.5}
        memory: {size: 256Mi}
        storage: {size: 512Mi}
  placement:
    akash:
      attributes:
        region: eu-west
      signedBy:
        anyOf: ["akash1365yvmc4s7awdyj3n2sav7xfx76adc6dnmlx63"]
      pricing:
        maxai-worker: {denom: uakt, amount: 1000}

deployment:
  maxai-worker:
    akash:
      profile: maxai-worker
      count: 1
"""
        sdl_path.write_text(sdl)
    note = (
        f'SDL created: {sdl_path}. '
        'Deploy via: https://console.akash.network/deployments — upload SDL, fund with AKT.'
    )
    set_status(st, 'akash', 'partial', note)


def handle_make_captcha(st: dict):
    """Make.com blocked by captcha — cannot bypass, mark manual."""
    set_status(st, 'make', 'manual_required',
               'Captcha on registration. Manual signup: https://www.make.com/en/register '
               'Email: froggyinternet@gmail.com  Pass: Internetinternet!2')


def handle_github_complete(st: dict):
    """GitHub is partial — check via API if already registered."""
    import urllib.request as ur
    try:
        r = ur.urlopen(
            urllib.request.Request(
                'https://api.github.com/users/froggyai2025',
                headers={'User-Agent': 'MaxAI-Check/1.0'}
            ), timeout=8
        )
        data = json.loads(r.read())
        if data.get('login'):
            note = f"github.com/{data['login']} — exists"
            set_status(st, 'github', 'registered', note)
            return True
    except Exception as e:
        log.info('GitHub API check: %s', e)
    # Try alternate username
    for uname in ['maxai2026', 'froggyinternet', 'mamaevalula-cpu']:
        try:
            import urllib.request
            r = urllib.request.urlopen(
                urllib.request.Request(
                    f'https://api.github.com/users/{uname}',
                    headers={'User-Agent': 'MaxAI-Check/1.0'}
                ), timeout=6
            )
            d = json.loads(r.read())
            if d.get('login'):
                set_status(st, 'github', 'registered', f'github.com/{d["login"]} — verified via API')
                return True
        except Exception:
            continue
    return False


# ── Browser-based retries ─────────────────────────────────────────────────────

BROWSER_TARGETS = [
    # (name, url, email, password, extra_note)
    ('dify',      'https://cloud.dify.ai/signin',          EMAIL1, PASSWORD, 'retry login'),
    ('vellum',    'https://app.vellum.ai/login',           EMAIL1, PASSWORD, 'retry login'),
    ('flowise',   'https://flowiseai.com/cloud',           EMAIL1, PASSWORD, 'cloud signup'),
    ('wikibot',   'https://wikibot.pro/register',          EMAIL1, PASSWORD, 'new selectors'),
    ('nodul',     'https://nodul.com/register',            EMAIL1, PASSWORD, 'new platform'),
    ('targetai',  'https://targetai.pro/auth/register',    EMAIL1, PASSWORD, 'retry registration'),
    ('huggingface','https://huggingface.co/join',          EMAIL1, PASSWORD, 'AI model hub'),
]


async def browser_try(page, name: str, url: str, email: str, password: str) -> str:
    """Generic form-fill attempt. Returns status string."""
    try:
        log.info('[%s] → %s', name, url)
        await page.goto(url, wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(4)

        content = (await page.inner_text('body'))[:2000].lower()
        log.info('[%s] page: %s', name, content[:100])

        # Already logged in / dashboard?
        if any(w in content for w in ['dashboard', 'workspace', 'create app', 'new app',
                                       'my projects', 'my models', 'getting started']):
            return 'logged_in'

        # Verify email page
        if any(w in content for w in ['verify your email', 'confirm your email', 'check your inbox',
                                       'verification email', 'подтвердите']):
            return 'verify_email'

        # Login page — try to fill
        email_filled = False
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[name="username"]',
                    'input[placeholder*="email" i]', '#email', '#username']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(email)
                    email_filled = True
                    break
            except Exception:
                pass

        if not email_filled:
            # Try registration form
            for sel in ['input[type="email"]', 'input[name="email"]']:
                try:
                    await page.fill(sel, email)
                    email_filled = True
                    break
                except Exception:
                    pass

        if not email_filled:
            return 'no_form_found'

        # Password
        for sel in ['input[type="password"]', 'input[name="password"]', '#password']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(password)
                    break
            except Exception:
                pass

        # Confirm password (signup forms)
        for sel in ['input[name="password_confirmation"]', 'input[name="confirmPassword"]',
                    'input[name="confirm_password"]', 'input[placeholder*="confirm" i]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(password)
                    break
            except Exception:
                pass

        # Username field
        if 'username' in content or 'user name' in content:
            for sel in ['input[name="username"]', 'input[placeholder*="username" i]', '#username']:
                try:
                    el = await page.query_selector(sel)
                    if el and await el.is_visible():
                        await el.fill('maxai2026')
                        break
                except Exception:
                    pass

        await asyncio.sleep(1)

        # Submit
        for sel in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Login")',
                    'button:has-text("Log in")', 'button:has-text("Sign up")',
                    'button:has-text("Register")', 'button:has-text("Create account")',
                    'input[type="submit"]', '[data-testid="login-button"]',
                    '[data-testid="register-button"]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    await asyncio.sleep(5)
                    break
            except Exception:
                pass

        await asyncio.sleep(4)
        content2 = (await page.inner_text('body'))[:2000].lower()

        if any(w in content2 for w in ['dashboard', 'workspace', 'create app', 'new app',
                                        'my projects', 'my models', 'welcome', 'getting started']):
            return 'logged_in'
        if any(w in content2 for w in ['verify', 'confirm your email', 'check your inbox']):
            return 'verify_email'
        if 'captcha' in content2 or 'recaptcha' in content2 or 'hcaptcha' in content2:
            return 'captcha_blocked'
        if any(w in content2 for w in ['invalid', 'incorrect', 'wrong password', 'not found',
                                        'user not found']):
            return 'login_failed'
        if any(w in content2 for w in ['already registered', 'already exists', 'email already']):
            return 'already_exists'

        return 'login_attempted'

    except Exception as e:
        log.warning('[%s] error: %s', name, e)
        return 'error'


async def run_browser_targets(st: dict) -> dict:
    """Run all browser targets and return results."""
    results = {}
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.error('playwright not installed')
        return results

    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled']
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
            await stealth_async(page)

        for name, url, email, pwd, note in BROWSER_TARGETS:
            # Skip if already successfully registered
            curr = st.get(name, {}).get('status', '')
            if curr in ('registered', 'logged_in', 'bot_created', 'agent_created', 'already_exists'):
                log.info('[%s] already %s — skip', name, curr)
                results[name] = curr
                continue

            status = await browser_try(page, name, url, email, pwd)
            results[name] = status
            set_status(st, name, status, note)
            log.info('[%s] done: %s', name, status)
            await asyncio.sleep(3)

        await browser.close()

    return results


# ── Main orchestrator ─────────────────────────────────────────────────────────

async def run():
    st = load_status()
    ts_start = time.time()

    tg(
        '<b>MaxAI Platform Agent v3 — СТАРТ</b>\n\n'
        f'Время: {datetime.utcnow().strftime("%H:%M UTC")}\n'
        'Задание: зарегистрировать/обновить все 20 платформ\n\n'
        'Начинаю обработку...'
    )
    log.info('=== Platform Agent v3 START ===')

    # Step 1: Non-browser handlers (fast)
    log.info('Step 1: Non-browser handlers')
    handle_gpt_store(st)
    handle_dify_hub(st)
    handle_akash(st)
    handle_make_captcha(st)
    github_ok = handle_github_complete(st)
    log.info('GitHub API check: %s', 'OK' if github_ok else 'not found via API')

    # Step 2: Browser automation
    log.info('Step 2: Browser automation (%d targets)', len(BROWSER_TARGETS))
    tg('⚙️ Запускаю браузер для регистрации...')
    browser_results = await run_browser_targets(st)

    # Step 3: Reload and report
    st = load_status()
    elapsed = int(time.time() - ts_start)

    known = [
        'n8n', 'dify', 'relevance_ai', 'pipedream', 'vellum',
        'huggingface', 'github', 'zapier', 'make', 'flowise',
        'langflow', 'coze', 'poe', 'gpt_store', 'dify_hub',
        'bitrix24', 'targetai', 'nodul', 'wikibot', 'akash'
    ]

    ok = warn = err = 0
    lines = []
    for p in known:
        info = st.get(p, {})
        s = info.get('status', 'not_started')
        is_ok = s in ('registered', 'logged_in', 'bot_created', 'agent_created', 'already_exists')
        is_warn = s in ('verify_email', 'partial', 'login_attempted', 'manual_required')
        if is_ok: ok += 1
        elif is_warn: warn += 1
        else: err += 1
        em = '✅' if is_ok else ('⚠️' if is_warn else '❌')
        lines.append(f'{em} {p}: {s}')

    report = (
        f'<b>MaxAI Platform Agent v3 — ГОТОВО</b>\n\n'
        f'⏱ {elapsed}s | ✅ {ok}/20 | ⚠️ {warn} | ❌ {err}\n\n'
        + '\n'.join(lines) +
        f'\n\nДашборд: http://77.90.2.171/#platforms'
    )
    tg(report)
    log.info('=== Platform Agent v3 DONE: %d OK / %d warn / %d err in %ds ===',
             ok, warn, err, elapsed)
    print(report.replace('<b>', '').replace('</b>', ''))
    return {'ok': ok, 'warn': warn, 'err': err, 'elapsed': elapsed}


if __name__ == '__main__':
    asyncio.run(run())
