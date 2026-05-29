#!/usr/bin/env python3
"""
kwork_browser_agent.py — Kwork.ru через браузер (Playwright stealth)
Логинится на kwork.ru, ищет Python/AI проекты, отправляет отклики.
"""
import asyncio, json, logging, os, random, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/root/my_personal_ai')
Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
Path('/root/my_personal_ai/data').mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/kwork_browser.log'),
    ]
)
log = logging.getLogger('kwork_browser')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
STATE_FILE = Path('/root/my_personal_ai/data/kwork_state.json')

KWORK_EMAIL    = 'jimmorrisoninlove@gmail.com'
KWORK_PASSWORD = 'Fukcyoubithc48'

PROPOSALS = [
    "Специализируюсь на Python, Telegram-ботах и AI-автоматизации. "
    "Выполню ваш проект качественно и в срок. Использую asyncio, FastAPI, aiogram, OpenAI API. "
    "Готов приступить немедленно. Пишите — обсудим детали и покажу примеры работ.",

    "3+ года разрабатываю Python-боты и AI-агенты для бизнеса. "
    "Ваш проект — точно в моей зоне экспертизы. "
    "Современный стек: Python 3.11, FastAPI, PostgreSQL, Docker. Сроки 1-3 дня.",

    "Занимаюсь автоматизацией и разработкой ботов для Telegram/VK. "
    "Отличное понимание вашей задачи. Реализую с нуля или улучшу существующее. "
    "Покажу живые примеры по теме вашего заказа.",
]

def tg(text: str):
    try:
        import urllib.request as ur
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000], 'parse_mode': 'HTML'}).encode()
        req = ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                         data=data, headers={'Content-Type': 'application/json'})
        ur.urlopen(req, timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {'applied': [], 'total_applied': 0, 'won': 0, 'total_earned_rub': 0, 'last_run': ''}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))

async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    state = load_state()
    applied_ids = set(str(x) for x in state.get('applied', []))
    new_applied = 0
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled',
                  '--disable-dev-shm-usage', '--window-size=1280,900']
        )
        ctx = await browser.new_context(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ru-RU',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await stealth_async(page)

        log.info('Navigating to kwork.ru/login')
        await page.goto('https://kwork.ru/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        # Dismiss cookies banner if present
        try:
            cookie_btn = await page.query_selector('button:has-text("Окей"), button:has-text("Принять")')
            if cookie_btn:
                await cookie_btn.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

        # Login with correct selectors (confirmed via page inspection)
        try:
            email_sel = 'input[placeholder="Электронная почта или логин"]'
            pwd_sel   = 'input[type="password"][placeholder="Пароль"]'
            btn_sel   = 'button.auth-form__button, button.kw-button--green:has-text("Войти")'

            await page.fill(email_sel, KWORK_EMAIL, timeout=10000)
            await asyncio.sleep(0.5)
            await page.fill(pwd_sel, KWORK_PASSWORD, timeout=10000)
            await asyncio.sleep(0.5)
            await page.click(btn_sel, timeout=10000)
            await page.wait_for_load_state('networkidle', timeout=20000)
            log.info('Login submitted, URL: %s', page.url)
        except Exception as e:
            log.error('Login step failed: %s', e)
            try:
                await page.screenshot(path='/tmp/kwork_login_fail.png')
            except Exception:
                pass

        # Check if logged in
        is_logged = 'kwork.ru' in page.url and 'login' not in page.url
        if not is_logged:
            # Try checking for user avatar/menu
            try:
                await page.wait_for_selector('.user-header, .header-user, .want-nav__user', timeout=5000)
                is_logged = True
            except Exception:
                pass

        if not is_logged:
            log.warning('Login may have failed. URL: %s', page.url)
            tg('<b>Kwork</b>: Ошибка логина — проверь учётные данные на kwork.ru')
            await browser.close()
            return

        log.info('Logged in to Kwork!')

        # Search for projects — Kwork calls them "wants" (хотелки)
        keywords = ['python бот', 'telegram бот', 'python автоматизация', 'ai', 'парсер']
        for kw in keywords[:3]:
            try:
                import urllib.parse
                kw_enc = urllib.parse.quote(kw)
                search_url = f'https://kwork.ru/projects?c=11&keyword={kw_enc}'
                await page.goto(search_url, wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(2)

                # Get project cards
                cards = await page.query_selector_all('.want-card, .wantCard, [class*="want-card"]')
                log.info('Keyword "%s": %d cards found', kw, len(cards))

                for card in cards[:5]:
                    try:
                        # Get project ID from link
                        link = await card.query_selector('a[href*="/projects/"]')
                        if not link:
                            continue
                        href = await link.get_attribute('href')
                        if not href:
                            continue

                        # Extract ID
                        import re
                        pid_match = re.search(r'/projects/(\d+)', href)
                        if not pid_match:
                            continue
                        pid = pid_match.group(1)

                        if pid in applied_ids:
                            continue

                        # Get title and budget
                        title_el = await card.query_selector('h2, .want-card__name, [class*="title"]')
                        title = await title_el.inner_text() if title_el else 'Проект'
                        title = title.strip()[:80]

                        budget_el = await card.query_selector('[class*="price"], [class*="budget"]')
                        budget_text = await budget_el.inner_text() if budget_el else '0'
                        budget = int(re.sub(r'[^\d]', '', budget_text) or '2000')

                        if budget < 1500:
                            continue

                        log.info('Applying to #%s "%s" budget=%d', pid, title, budget)

                        # Open project page
                        proj_url = f'https://kwork.ru{href}' if href.startswith('/') else href
                        await page.goto(proj_url, wait_until='domcontentloaded', timeout=20000)
                        await asyncio.sleep(1.5)

                        # Click "Respond" button
                        respond_btn = await page.query_selector(
                            '.want-btn-respond, .btn-respond, button:has-text("Откликнуться"), '
                            'a:has-text("Откликнуться"), button:has-text("Предложить")'
                        )
                        if not respond_btn:
                            log.warning('No respond button for #%s', pid)
                            await page.go_back()
                            continue

                        await respond_btn.click()
                        await asyncio.sleep(1.5)

                        # Fill proposal
                        proposal = random.choice(PROPOSALS)
                        textarea = await page.query_selector(
                            'textarea[name*="message"], textarea[name*="descr"], '
                            '.respond-form textarea, form textarea'
                        )
                        if not textarea:
                            log.warning('No textarea for #%s', pid)
                            await page.go_back()
                            continue

                        await textarea.fill(proposal)
                        await asyncio.sleep(0.5)

                        # Set price if input exists
                        price_input = await page.query_selector(
                            'input[name*="price"], input[name*="kwork_price"]'
                        )
                        if price_input:
                            offer_price = str(int(budget * 0.85) if budget > 2000 else budget)
                            await price_input.fill(offer_price)

                        # Submit
                        submit_btn = await page.query_selector(
                            'button[type="submit"], .modal-footer .btn-primary, '
                            'button:has-text("Отправить"), button:has-text("Откликнуться")'
                        )
                        if submit_btn:
                            await submit_btn.click()
                            await asyncio.sleep(2)
                            applied_ids.add(pid)
                            new_applied += 1
                            results.append(f'OK #{pid} "{title}" {budget}r')
                            log.info('Applied to #%s OK', pid)
                        else:
                            log.warning('No submit button for #%s', pid)

                        await page.go_back()
                        await asyncio.sleep(random.uniform(2, 4))

                    except Exception as e:
                        log.warning('Error on card: %s', e)
                        try:
                            await page.go_back()
                        except Exception:
                            pass
                        continue

            except Exception as e:
                log.error('Keyword "%s" error: %s', kw, e)

        await browser.close()

    # Save state
    state['applied'] = list(applied_ids)[-500:]
    state['total_applied'] = state.get('total_applied', 0) + new_applied
    state['last_run'] = datetime.utcnow().isoformat()
    save_state(state)

    # Report
    if new_applied > 0:
        msg = (f'<b>Kwork Browser Agent</b>\n'
               f'Отправлено откликов: <b>{new_applied}</b>\n\n' +
               '\n'.join(results[:10]) +
               f'\n\nВсего с начала: {state["total_applied"]}')
    else:
        msg = (f'<b>Kwork</b>: Новых проектов не найдено.\n'
               f'Всего откликов: {state["total_applied"]}')

    tg(msg)
    log.info('Done: %d applied', new_applied)


if __name__ == '__main__':
    asyncio.run(run())
