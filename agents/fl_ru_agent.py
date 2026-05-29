#!/usr/bin/env python3
"""
fl_ru_agent.py — Автооткликик на FL.ru (freelance.ru) через Playwright
Cron: 11:00 и 17:00 UTC
"""
import asyncio, json, logging, os, time, random
from pathlib import Path
from datetime import datetime

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler('/root/my_personal_ai/logs/fl_ru_agent.log')])
log = logging.getLogger('fl')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')
EMAIL    = os.environ.get('FL_EMAIL', os.environ.get('KWORK_EMAIL', 'froggyinternet@gmail.com'))
PASSWORD = os.environ.get('FL_PASSWORD', os.environ.get('KWORK_PASSWORD', 'Internetinternet!2'))
STATE_FILE = Path('/root/my_personal_ai/data/fl_ru_state.json')

PROPOSALS = [
    "Здравствуйте! Python разработчик с опытом 5+ лет. Готов выполнить задачу в срок с полной документацией. Напишите в ЛС для обсуждения деталей.",
    "Привет! Вижу задачу — могу взяться. Опыт: Telegram боты, парсеры, автоматизация, API интеграции. Сдам вовремя, с тестированием.",
    "Рад помочь с вашим проектом! Выполнил 50+ подобных задач. Качество гарантирую. Готов начать после уточнения деталей.",
]

def tg(text):
    import urllib.request as ur
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type': 'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except:
        return {'logged_in': False, 'total_applied': 0, 'won': 0}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa; USE_STEALTH = True
    except:
        USE_STEALTH = False

    state = load_state()
    applied = 0

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
            locale='ru-RU',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await sa(page)

        # LOGIN
        log.info('Opening FL.ru login...')
        await page.goto('https://www.fl.ru/login/', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        email_sel = await page.query_selector('input[name="email"], input[type="email"], input[placeholder*="mail"]')
        pwd_sel = await page.query_selector('input[name="password"], input[type="password"]')

        if email_sel and pwd_sel:
            await email_sel.fill(EMAIL)
            await asyncio.sleep(0.3)
            await pwd_sel.fill(PASSWORD)
            await asyncio.sleep(0.3)
            btn = await page.query_selector('button[type="submit"], input[type="submit"]')
            if btn:
                await btn.click()
                await asyncio.sleep(4)

        log.info('After login: %s', page.url)
        await page.screenshot(path='/tmp/fl_login.png')

        logged_in = 'login' not in page.url and 'fl.ru' in page.url
        state['logged_in'] = logged_in

        if logged_in:
            log.info('FL.ru login SUCCESS')

            # Browse Python/automation projects
            await page.goto('https://www.fl.ru/projects/?kind=1&category%5B%5D=8',
                           wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)

            # Find project links
            project_links = await page.query_selector_all('a.b-post__link, h2.b-post__title a, .project-name a')
            log.info('Found %d project links', len(project_links))

            hrefs = []
            for lnk in project_links[:10]:
                href = await lnk.get_attribute('href')
                if href and '/projects/' in href:
                    full = f'https://www.fl.ru{href}' if href.startswith('/') else href
                    hrefs.append(full)

            for url in hrefs[:5]:
                try:
                    await page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    await asyncio.sleep(2)

                    # Find respond button
                    respond_btn = await page.query_selector(
                        'a:has-text("Откликнуться"), button:has-text("Откликнуться"), '
                        '.b-respond, [class*="respond"]'
                    )
                    if respond_btn:
                        await respond_btn.click()
                        await asyncio.sleep(2)

                        textarea = await page.query_selector('textarea')
                        if textarea:
                            proposal = PROPOSALS[applied % len(PROPOSALS)]
                            await textarea.fill(proposal)
                            await asyncio.sleep(0.5)

                            submit = await page.query_selector('button[type="submit"], input[type="submit"]')
                            if submit:
                                await submit.click()
                                await asyncio.sleep(2)
                                applied += 1
                                log.info('Applied to: %s', url)

                    await asyncio.sleep(random.uniform(3, 6))
                except Exception as e:
                    log.warning('Project %s: %s', url, e)

            state['total_applied'] = state.get('total_applied', 0) + applied
            tg(f"FL.ru отчёт {datetime.utcnow().strftime('%H:%M UTC')}\n"
               f"Логин: OK\nОткликов: {applied}\nВсего: {state['total_applied']}")
        else:
            # Check for CAPTCHA
            body = (await page.inner_text('body'))[:200]
            log.warning('FL.ru login failed. Page: %s', body[:100])

            # Check if account needs registration
            if 'register' in page.url or 'signup' in page.url or 'регистрация' in body.lower():
                tg('FL.ru: нужна регистрация нового аккаунта.\n'
                   'Зайди на fl.ru и зарегистрируйся с froggyinternet@gmail.com')
            else:
                tg(f'FL.ru: вход не удался.\nURL: {page.url}\nПроверь логин/пароль.')

        await browser.close()

    state['last_run'] = datetime.utcnow().isoformat()
    save_state(state)

if __name__ == '__main__':
    asyncio.run(run())
