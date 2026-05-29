#!/usr/bin/env python3
"""
avito_agent.py — Размещение объявлений на Avito (IT-услуги, автоматизация, боты)
Запуск: ежедневно 09:00 UTC
"""
import asyncio, json, logging, re, os, time
from pathlib import Path
from datetime import datetime

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler('/root/my_personal_ai/logs/avito_agent.log')])
log = logging.getLogger('avito')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
STATE_FILE = Path('/root/my_personal_ai/data/avito_state.json')

# Объявления для публикации
ADS = [
    {
        'title': 'Разработка Telegram бота — профессионально',
        'description': (
            'Создам Telegram бота любой сложности:\n'
            '• Боты для бизнеса и продаж\n'
            '• Интеграция с CRM, 1С, Google Sheets\n'
            '• Автоответчики, рассылки, оплата\n'
            '• Парсеры, агрегаторы данных\n\n'
            'Опыт 5+ лет, более 50 реализованных проектов.\n'
            'Гарантия качества, поддержка после сдачи.\n'
            'Ответ в течение 1 часа.'
        ),
        'price': 5000,
        'category': 'Программирование'
    },
    {
        'title': 'Парсер данных с любого сайта — быстро',
        'description': (
            'Соберу данные с любого сайта:\n'
            '• Товары и цены с маркетплейсов\n'
            '• Контакты, объявления, вакансии\n'
            '• Обход Cloudflare, капч, защит\n'
            '• Экспорт в Excel, JSON, БД\n\n'
            'Python + Selenium/Playwright.\n'
            'Результат от 24 часов.'
        ),
        'price': 3000,
        'category': 'Программирование'
    },
    {
        'title': 'Автоматизация бизнеса — Python, Excel, 1С',
        'description': (
            'Автоматизирую рутинные процессы:\n'
            '• Автоматические отчёты и выгрузки\n'
            '• Интеграция сервисов через API\n'
            '• Рассылки Email/WhatsApp/Telegram\n'
            '• Обработка данных в Excel/Google Sheets\n\n'
            'Сэкономлю вам 2-5 часов ежедневно.\n'
            'Консультация бесплатно.'
        ),
        'price': 4500,
        'category': 'Программирование'
    },
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
        return {'logged_in': False, 'ads_posted': 0, 'leads': 0, 'orders': 0, 'revenue_rub': 0}

async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa; USE_STEALTH = True
    except:
        USE_STEALTH = False

    state = load_state()
    posted = 0

    # Avito requires phone verification for new accounts
    # Strategy: use existing account OR check if phone in .env
    email = os.environ.get('AVITO_EMAIL', os.environ.get('KWORK_EMAIL', 'froggyinternet@gmail.com'))
    password = os.environ.get('AVITO_PASSWORD', os.environ.get('KWORK_PASSWORD', 'Internetinternet!2'))

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

        # ── CHECK AVITO ACCESS ────────────────────────────────────────────
        log.info('Loading Avito...')
        await page.goto('https://www.avito.ru/profile/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)
        await page.screenshot(path='/tmp/avito_1.png')
        log.info('Avito URL: %s', page.url)

        # Check if login page has email/password
        inputs = await page.query_selector_all('input:not([type=hidden])')
        log.info('Inputs found: %d', len(inputs))
        for inp in inputs[:5]:
            tp = await inp.get_attribute('type') or 'text'
            ph = await inp.get_attribute('placeholder') or ''
            log.info('  %s: %s', tp, ph[:30])

        # Avito requires phone number, not email — note this
        phone_input = await page.query_selector('input[type="tel"], input[placeholder*="телефон"], input[placeholder*="Телефон"], input[name="login"]')
        email_input = await page.query_selector('input[type="email"], input[placeholder*="почт"], input[placeholder*="email"]')

        if phone_input:
            log.warning('Avito requires phone number for login')
            phone = os.environ.get('AVITO_PHONE', os.environ.get('PHONE_RU', ''))
            if phone:
                await phone_input.fill(phone)
                await asyncio.sleep(0.5)
                btn = await page.query_selector('button[type="submit"]')
                if btn:
                    await btn.click()
                    await asyncio.sleep(3)
                    log.info('Phone submitted, URL: %s', page.url)
            else:
                log.warning('No phone number in .env. Set AVITO_PHONE=+7XXXXXXXXXX')
                tg(
                    'Avito: требует номер телефона для входа.\n\n'
                    'Добавь в .env:\n'
                    'AVITO_PHONE=+7XXXXXXXXXX\n\n'
                    'Пока работаем только через Kwork!'
                )
                await browser.close()

                # Save state with instructions
                state['status'] = 'needs_phone'
                state['last_run'] = datetime.utcnow().isoformat()
                STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                return

        elif email_input:
            await email_input.fill(email)
            pwd = await page.query_selector('input[type="password"]')
            if pwd:
                await pwd.fill(password)
            btn = await page.query_selector('button[type="submit"]')
            if btn:
                await btn.click()
                await asyncio.sleep(4)
                log.info('Email login submitted, URL: %s', page.url)

        await page.screenshot(path='/tmp/avito_2_login.png')

        if 'avito.ru' in page.url and '/profile/login' not in page.url:
            log.info('Logged in to Avito!')
            state['logged_in'] = True

            # Navigate to post ad
            await page.goto('https://www.avito.ru/additem', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)
            log.info('Add item page: %s', page.url)
            await page.screenshot(path='/tmp/avito_3_additem.png')
            tg('Avito: вошли в аккаунт! Готов размещать объявления.')
        else:
            log.warning('Avito login failed or requires phone')

        await browser.close()

    state['last_run'] = datetime.utcnow().isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    asyncio.run(run())
