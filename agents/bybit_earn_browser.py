#!/usr/bin/env python3
"""
bybit_earn_v2.py — Bybit Earn deposit via browser (fixed selectors)
"""
import asyncio, json, logging, re
from pathlib import Path

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler('/root/my_personal_ai/logs/bybit_earn_browser.log')])
log = logging.getLogger('earn')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
EMAIL    = 'jimmorrisoninlove@gmail.com'
PASSWORD = 'Fukcyoubithc48'

def tg(text):
    try:
        import urllib.request as ur
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type':'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            viewport={'width':1366,'height':768},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await stealth_async(page)

        log.info('Loading Bybit login page...')
        await page.goto('https://www.bybit.com/en/login', wait_until='networkidle', timeout=40000)
        await asyncio.sleep(3)
        await page.screenshot(path='/tmp/bybit_1_loaded.png')
        log.info('Page loaded: %s', page.url)

        # Find any visible input fields
        inputs = await page.query_selector_all('input:not([type=hidden])')
        log.info('Inputs found: %d', len(inputs))
        for inp in inputs[:8]:
            tp = await inp.get_attribute('type') or 'text'
            ph = await inp.get_attribute('placeholder') or ''
            nm = await inp.get_attribute('name') or ''
            log.info('  input type=%s name=%s ph=%s', tp, nm, ph[:40])

        # Try multiple email selectors
        email_filled = False
        for sel in [
            'input[name="email"]',
            'input[name="account"]',
            'input[name="username"]',
            'input[type="email"]',
            'input[placeholder*="mail"]',
            'input[placeholder*="Mail"]',
            'input[placeholder*="email"]',
            'input[placeholder*="Email"]',
            'input[placeholder*="account"]',
            'input[placeholder*="Account"]',
        ]:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL)
                    email_filled = True
                    log.info('Email filled via: %s', sel)
                    break
            except:
                pass

        if not email_filled:
            # Try first visible text/email input
            for inp in inputs:
                tp = await inp.get_attribute('type') or 'text'
                if tp in ('text', 'email') and await inp.is_visible():
                    await inp.fill(EMAIL)
                    email_filled = True
                    log.info('Email filled via fallback input')
                    break

        if not email_filled:
            await page.screenshot(path='/tmp/bybit_no_email.png')
            tg('Bybit Earn: не нашли поле email. Нужно включить Earn вручную:\nbybit.com → API → O8NZsb1QOlQET3c3kH → Edit → Earn')
            await browser.close()
            return

        await asyncio.sleep(0.5)

        # Fill password
        pwd_filled = False
        for sel in ['input[type="password"]', 'input[name="password"]']:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    pwd_filled = True
                    log.info('Password filled')
                    break
            except:
                pass

        await page.screenshot(path='/tmp/bybit_2_filled.png')

        # Click login button
        for btn_sel in [
            'button[type="submit"]',
            'button:has-text("Log In")',
            'button:has-text("Sign In")',
            'button:has-text("Login")',
            '.login-btn',
            '[data-testid="login"]',
        ]:
            try:
                btn = await page.query_selector(btn_sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    log.info('Clicked login via: %s', btn_sel)
                    break
            except:
                pass

        await asyncio.sleep(6)
        await page.screenshot(path='/tmp/bybit_3_after_login.png')
        log.info('After login URL: %s', page.url)

        # Check if logged in
        if 'login' not in page.url and 'bybit.com' in page.url:
            log.info('Logged in!')
            tg(f'Bybit: успешный вход! Иду в Earn...')

            # Navigate to Earn
            await page.goto('https://www.bybit.com/en/earn/flexible-saving',
                           wait_until='domcontentloaded', timeout=25000)
            await asyncio.sleep(4)
            await page.screenshot(path='/tmp/bybit_4_earn.png')

            # Try to find and click USDT flexible savings
            subscribed = False
            for sub_sel in [
                'button:has-text("Subscribe")',
                'button:has-text("Deposit")',
                'a:has-text("Earn Now")',
                'button:has-text("Stake")',
            ]:
                try:
                    btn = await page.query_selector(sub_sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(2)
                        # Enter amount
                        for amt_sel in ['input[type="number"]', 'input[placeholder*="amount"]', 'input[placeholder*="Amount"]']:
                            try:
                                inp = await page.query_selector(amt_sel)
                                if inp:
                                    await inp.fill('150')
                                    break
                            except:
                                pass
                        # Confirm
                        for conf_sel in ['button:has-text("Confirm")', 'button[type="submit"]']:
                            try:
                                cbtn = await page.query_selector(conf_sel)
                                if cbtn:
                                    await cbtn.click()
                                    await asyncio.sleep(3)
                                    subscribed = True
                                    break
                            except:
                                pass
                        if subscribed:
                            break
                except:
                    pass

            await page.screenshot(path='/tmp/bybit_5_result.png')

            if subscribed:
                tg('Bybit Earn: задеплоено $150 USDT! Пассивный доход ~$0.026/день')
            else:
                tg(
                    'Bybit: вошли в аккаунт!\n\n'
                    'Для Earn нужно включить permission:\n'
                    'bybit.com → API Management\n'
                    '→ O8NZsb1QOlQET3c3kH → Edit → Earn\n'
                    'Скриншоты: /tmp/bybit_*.png'
                )
        elif 'verify' in page.url or 'security' in page.url.lower() or '2fa' in page.url.lower():
            tg(
                'Bybit: требует 2FA верификацию.\n'
                'Войди вручную: bybit.com\n'
                '→ API → O8NZsb1QOlQET3c3kH → Edit → Earn'
            )
            log.warning('2FA required, URL: %s', page.url)
        else:
            log.warning('Login uncertain. URL: %s', page.url)
            tg(
                'Bybit Earn: браузерный вход не удался.\n\n'
                'Включи Earn вручную:\n'
                'bybit.com → API Management\n'
                '→ O8NZsb1QOlQET3c3kH → Edit → поставь Earn'
            )

        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
