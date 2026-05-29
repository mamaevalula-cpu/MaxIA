#!/usr/bin/env python3
"""kwork_register_v2.py - регистрация через radio tab на login странице"""
import asyncio, json, logging, re, sys
from pathlib import Path

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/kwork_register.log'),
    ]
)
log = logging.getLogger('kwork_reg')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
EMAIL    = 'jimmorrisoninlove@gmail.com'
NEW_PWD  = 'MaxAI_2026_kwork!'
ENV_FILE = Path('/root/my_personal_ai/.env')

def tg(text):
    import urllib.request as ur
    try:
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                              data=data, headers={'Content-Type': 'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)


async def main():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
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

        await page.goto('https://kwork.ru/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        # Dismiss cookies
        try:
            cb = await page.query_selector('button:has-text("Окей")')
            if cb:
                await cb.click()
                await asyncio.sleep(0.3)
        except Exception:
            pass

        # Click REGISTER radio (2nd radio = register tab)
        radios = await page.query_selector_all('input[type=radio]')
        log.info('Radios found: %d', len(radios))
        if len(radios) >= 2:
            await radios[1].click()
            await asyncio.sleep(1.5)
            log.info('Clicked register radio')

        # Get visible inputs
        inputs = await page.query_selector_all('input:not([type=hidden]):not([type=radio]):not([type=checkbox])')
        log.info('Inputs after tab: %d', len(inputs))
        for inp in inputs:
            ph = await inp.get_attribute('placeholder') or ''
            tp = await inp.get_attribute('type') or 'text'
            log.info('  type=%s placeholder=%s', tp, ph)

        # Fill email
        email_filled = False
        for inp in inputs:
            ph = (await inp.get_attribute('placeholder') or '').lower()
            tp = await inp.get_attribute('type') or 'text'
            if tp == 'email' or 'почта' in ph or 'email' in ph:
                await inp.fill(EMAIL)
                email_filled = True
                log.info('Filled email field')
                await asyncio.sleep(0.3)
                break

        if not email_filled:
            # Try the registration-specific email input (not the login one)
            all_inputs = await page.query_selector_all('input[type=email], input[placeholder*="Электронная почта"]')
            for inp in all_inputs:
                ph = await inp.get_attribute('placeholder') or ''
                # The registration email has placeholder "Электронная почта" (no "или логин")
                if 'или логин' not in ph:
                    await inp.fill(EMAIL)
                    email_filled = True
                    log.info('Filled reg email field: %s', ph)
                    await asyncio.sleep(0.3)
                    break

        # Fill password(s)
        pwd_inputs = await page.query_selector_all('input[type=password]')
        log.info('Password inputs: %d', len(pwd_inputs))
        for pi in pwd_inputs:
            await pi.fill(NEW_PWD)
            await asyncio.sleep(0.2)

        # Check username/name field
        for inp in inputs:
            ph = (await inp.get_attribute('placeholder') or '').lower()
            if 'имя' in ph or 'name' in ph or 'логин' in ph:
                await inp.fill('MaxAI_Developer')
                await asyncio.sleep(0.2)
                break

        # Screenshot before submit
        await page.screenshot(path='/tmp/kwork_reg_before.png')

        # Submit
        btn = await page.query_selector('button.auth-form__button, button[type=submit]')
        if btn:
            btn_text = await btn.inner_text()
            log.info('Clicking: %s', btn_text.strip())
            await btn.click()
            await asyncio.sleep(5)
        else:
            log.warning('No submit button found')
            await page.screenshot(path='/tmp/kwork_no_btn.png')

        log.info('URL after submit: %s', page.url)
        await page.screenshot(path='/tmp/kwork_reg_after.png')

        # Check result
        page_text = await page.inner_text('body')

        if 'login' not in page.url:
            log.info('SUCCESS - registered or logged in')
            content = ENV_FILE.read_text()
            content = re.sub(r'KWORK_PASSWORD=.*', f'KWORK_PASSWORD={NEW_PWD}', content)
            ENV_FILE.write_text(content)
            tg(f'Kwork: аккаунт готов!\nEmail: {EMAIL}\nПароль: {NEW_PWD}')
        else:
            # Check for specific errors
            errs = await page.query_selector_all('.error, .alert, [class*="error"], [class*="alert"]')
            err_texts = []
            for e in errs[:5]:
                try:
                    t = await e.inner_text()
                    if t.strip():
                        err_texts.append(t.strip()[:100])
                except Exception:
                    pass

            log.info('Errors: %s', err_texts)

            if any('зарегистрирован' in t.lower() or 'занят' in t.lower() or 'exists' in t.lower()
                   for t in err_texts):
                # Email already registered - try password recovery
                log.info('Email already registered - trying password recovery')
                await page.goto('https://kwork.ru/forgot-password',
                               wait_until='domcontentloaded', timeout=20000)
                await asyncio.sleep(1)
                try:
                    forgot_email = await page.query_selector('input[type=email], input[placeholder*="почта"]')
                    if forgot_email:
                        await forgot_email.fill(EMAIL)
                        await asyncio.sleep(0.3)
                        sub = await page.query_selector('button[type=submit], button.auth-form__button')
                        if sub:
                            await sub.click()
                            await asyncio.sleep(3)
                            log.info('Recovery email sent')
                            tg(f'Kwork: письмо для сброса пароля отправлено на {EMAIL}.\nПосле сброса обновим пароль в .env')
                except Exception as fe:
                    log.error('Recovery: %s', fe)
            elif not err_texts:
                tg(f'Kwork: неизвестный результат регистрации.\nURL: {page.url[:60]}\nСкриншот: /tmp/kwork_reg_after.png')
            else:
                tg(f'Kwork регистрация:\n{chr(10).join(err_texts[:3])}\n\nURL: {page.url[:60]}')

        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
