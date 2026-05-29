#!/usr/bin/env python3
"""
kwork_full_agent.py — Полный цикл Kwork: логин → профиль → услуги → отклики
Запуск: cron 10:00 и 16:00 UTC
"""
import asyncio, json, logging, re, os, time
from pathlib import Path
from datetime import datetime

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler('/root/my_personal_ai/logs/kwork_full.log')])
log = logging.getLogger('kwork')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
EMAIL    = os.environ.get('KWORK_EMAIL', 'froggyinternet@gmail.com')
PASSWORD = os.environ.get('KWORK_PASSWORD', 'Internetinternet!2')
STATE_FILE = Path('/root/my_personal_ai/data/kwork_state.json')

# Услуги которые будем предлагать
SERVICES = [
    {
        'title': 'Разработка Telegram бота на Python',
        'description': 'Создам профессионального Telegram бота: команды, кнопки, БД, API интеграции. Чистый код, документация, поддержка.',
        'price': 3000,
        'delivery': 3,
        'category': 'Разработка ботов'
    },
    {
        'title': 'Парсер данных с любого сайта',
        'description': 'Соберу данные с любого сайта: товары, цены, контакты, объявления. Python + Selenium/Playwright. Обход защит.',
        'price': 2500,
        'delivery': 2,
        'category': 'Парсинг данных'
    },
    {
        'title': 'Автоматизация бизнес-процессов Python',
        'description': 'Автоматизирую рутину: рассылки, отчёты, выгрузки, обработка файлов. Экономит часы ручного труда ежедневно.',
        'price': 4000,
        'delivery': 5,
        'category': 'Автоматизация'
    },
    {
        'title': 'AI-ассистент для вашего бизнеса',
        'description': 'Внедрю ChatGPT/Claude в ваш бизнес: ответы на вопросы клиентов, анализ данных, генерация контента.',
        'price': 8000,
        'delivery': 7,
        'category': 'AI-решения'
    }
]

# Шаблоны откликов для автоматической подачи
PROPOSAL_TEMPLATES = [
    "Отличная задача! Имею опыт с подобными проектами. Готов выполнить быстро и качественно. Начну немедленно после согласования деталей.",
    "Вижу чёткое ТЗ — смогу сделать именно так. Python/API опыт 5+ лет. Сдам в срок с тестированием.",
    "Интересный проект. Уточните пару деталей в ЛС — предложу оптимальное решение и точную стоимость.",
]

def tg(text):
    import urllib.request as ur
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:3000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type':'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except:
        return {'logged_in': False, 'profile_created': False, 'services_posted': 0,
                'total_applied': 0, 'won': 0, 'total_earned_rub': 0}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa; USE_STEALTH = True
    except:
        USE_STEALTH = False

    state = load_state()
    results = {'login': False, 'profile': False, 'applied': 0, 'errors': []}

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            viewport={'width':1280,'height':900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='ru-RU',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await sa(page)

        # ── LOGIN ────────────────────────────────────────────────────────
        log.info('Logging in to Kwork...')
        await page.goto('https://kwork.ru/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        # Dismiss cookies
        try:
            cb = await page.query_selector('button:has-text("Окей"), button:has-text("OK")')
            if cb: await cb.click(); await asyncio.sleep(0.5)
        except: pass

        # Fill login form
        try:
            email_el = await page.query_selector('input[placeholder="Электронная почта или логин"]')
            if not email_el:
                email_el = await page.query_selector('input[type="email"], input[name="email"]')
            if email_el:
                await email_el.fill(EMAIL)
                await asyncio.sleep(0.3)

            pwd_el = await page.query_selector('input[type="password"]')
            if pwd_el:
                await pwd_el.fill(PASSWORD)
                await asyncio.sleep(0.3)

            btn = await page.query_selector('button.auth-form__button, button[type="submit"]')
            if btn:
                await btn.click()
                await asyncio.sleep(4)
        except Exception as e:
            log.error('Login error: %s', e)
            results['errors'].append(f'login: {e}')

        await page.screenshot(path='/tmp/kwork_login.png')
        log.info('After login URL: %s', page.url)

        # Check if logged in
        if 'login' not in page.url and 'kwork.ru' in page.url:
            results['login'] = True
            state['logged_in'] = True
            log.info('Login SUCCESS')

            # ── CHECK/UPDATE PROFILE ─────────────────────────────────────
            try:
                await page.goto('https://kwork.ru/dashboard', wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(2)
                page_text = await page.inner_text('body')

                # Get username/balance info
                username_match = re.search(r'Привет,\s+(\S+)', page_text)
                balance_match = re.search(r'(\d+[\s\d]*)\s*₽', page_text)
                if username_match:
                    state['username'] = username_match.group(1)
                    log.info('Username: %s', state['username'])

                results['profile'] = True
                log.info('Dashboard accessible')
            except Exception as e:
                log.warning('Dashboard: %s', e)

            # ── APPLY TO PROJECTS ─────────────────────────────────────────
            try:
                await page.goto('https://kwork.ru/projects?c=41&attr=0',  # Python category
                               wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(3)

                # Find projects
                projects = await page.query_selector_all('.project-card, .wants-card, [class*="project"], article')
                log.info('Found %d projects', len(projects))

                applied_this_run = 0
                for proj in projects[:5]:  # Apply to first 5
                    try:
                        # Get project title for context
                        title_el = await proj.query_selector('h2, h3, .project-title, .wants-title')
                        title = await title_el.inner_text() if title_el else 'Project'
                        title = title.strip()[:50]

                        # Click on project
                        link = await proj.query_selector('a')
                        if not link:
                            continue
                        href = await link.get_attribute('href')
                        if not href:
                            continue

                        full_url = f'https://kwork.ru{href}' if href.startswith('/') else href

                        await page.goto(full_url, wait_until='domcontentloaded', timeout=15000)
                        await asyncio.sleep(2)

                        # Find "Respond" button
                        respond_btn = await page.query_selector(
                            'button:has-text("Откликнуться"), button:has-text("Предложить"), '
                            '.want-send-offer, [class*="respond"], [class*="offer-btn"]'
                        )
                        if respond_btn:
                            await respond_btn.click()
                            await asyncio.sleep(2)

                            # Fill proposal
                            msg_area = await page.query_selector('textarea')
                            if msg_area:
                                template = PROPOSAL_TEMPLATES[applied_this_run % len(PROPOSAL_TEMPLATES)]
                                await msg_area.fill(template)
                                await asyncio.sleep(0.5)

                                # Submit
                                submit = await page.query_selector('button[type="submit"], button:has-text("Отправить")')
                                if submit:
                                    await submit.click()
                                    await asyncio.sleep(2)
                                    applied_this_run += 1
                                    log.info('Applied to: %s', title)

                        await page.go_back()
                        await asyncio.sleep(1)

                    except Exception as e:
                        log.warning('Project apply error: %s', e)
                        continue

                results['applied'] = applied_this_run
                state['total_applied'] = state.get('total_applied', 0) + applied_this_run
                log.info('Applied to %d projects this run', applied_this_run)

            except Exception as e:
                log.error('Projects section: %s', e)
                results['errors'].append(f'projects: {e}')

        else:
            # Login failed
            log.warning('Login FAILED. URL: %s', page.url)
            body_text = (await page.inner_text('body'))[:300]
            log.info('Page text: %s', body_text)

            # Check for error message
            errors = await page.query_selector_all('.error, .alert, [class*="error"]')
            err_texts = []
            for e in errors[:3]:
                try:
                    t = await e.inner_text()
                    if t.strip():
                        err_texts.append(t.strip()[:80])
                except: pass

            if err_texts:
                log.info('Login errors: %s', err_texts)
                tg(f'Kwork логин не удался:\n{chr(10).join(err_texts)}\n\nПроверь: {EMAIL} / {PASSWORD}')
            else:
                tg(f'Kwork: логин не удался (неизвестная причина).\nEmail: {EMAIL}\nПроверь правильность пароля.')

        await browser.close()

    # Save state and report
    state['last_run'] = datetime.utcnow().isoformat()
    save_state(state)

    if results['login']:
        msg = (
            f"Kwork отчёт {datetime.utcnow().strftime('%H:%M UTC')}\n\n"
            f"Логин: OK\n"
            f"Откликов сегодня: {results['applied']}\n"
            f"Всего откликов: {state.get('total_applied', 0)}\n"
            f"Выигранных: {state.get('won', 0)}\n"
            f"Заработано: {state.get('total_earned_rub', 0):,} руб\n\n"
        )
        if results['errors']:
            msg += f"Ошибки: {', '.join(results['errors'][:2])}"
        tg(msg)
    else:
        log.info('Login failed — no Telegram report sent (already notified)')

if __name__ == '__main__':
    asyncio.run(run())
