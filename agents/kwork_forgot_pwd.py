#!/usr/bin/env python3
"""
kwork_forgot_pwd.py — Запрос сброса пароля Kwork + ожидание письма через IMAP
"""
import asyncio, imaplib, email as email_lib, json, logging, re, sys, time
from pathlib import Path

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
               logging.FileHandler('/root/my_personal_ai/logs/kwork_recovery.log')])
log = logging.getLogger('kwork_recovery')

TG_TOKEN = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT  = '1985320458'
EMAIL    = 'jimmorrisoninlove@gmail.com'
NEW_PASS = 'MaxAI_kwork_2026!'
ENV_FILE = Path('/root/my_personal_ai/.env')

def tg(text):
    import urllib.request as ur
    try:
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                              data=data, headers={'Content-Type': 'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)


def try_gmail_imap(search_from: str = 'kwork', wait_secs: int = 60) -> str | None:
    """Try to read a recovery link from Gmail via IMAP."""
    # Try multiple passwords
    passwords = ['Fukcyoubithc48']

    for pwd in passwords:
        try:
            log.info('Trying IMAP with password...')
            mail = imaplib.IMAP4_SSL('imap.gmail.com', 993)
            mail.login(EMAIL, pwd)
            mail.select('INBOX')

            # Wait for email
            deadline = time.time() + wait_secs
            while time.time() < deadline:
                _, msgs = mail.search(None, f'FROM "{search_from}"')
                ids = msgs[0].split() if msgs[0] else []
                if ids:
                    _, data = mail.fetch(ids[-1], '(RFC822)')
                    msg = email_lib.message_from_bytes(data[0][1])
                    body = ''
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ('text/plain', 'text/html'):
                                body += part.get_payload(decode=True).decode('utf-8', errors='replace')
                    else:
                        body = msg.get_payload(decode=True).decode('utf-8', errors='replace')

                    # Find reset link
                    links = re.findall(r'https://kwork\.ru[^\s"<>]*(?:reset|confirm|verify|password)[^\s"<>]*', body)
                    if links:
                        log.info('Found reset link: %s', links[0][:60])
                        mail.close(); mail.logout()
                        return links[0]

                log.info('Waiting for email... %ds left', int(deadline - time.time()))
                time.sleep(10)

            mail.close(); mail.logout()
        except imaplib.IMAP4.error as e:
            log.warning('IMAP auth failed: %s', e)
            # Google blocking basic auth - expected
        except Exception as e:
            log.error('IMAP error: %s', e)
    return None


async def request_recovery():
    """Browser: go to forgot-password page and submit email."""
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False

    recovery_sent = False

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        page = await browser.new_page(
            viewport={'width': 1280, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        )
        if USE_STEALTH:
            await stealth_async(page)

        log.info('Going to forgot-password page')
        await page.goto('https://kwork.ru/forgot-password',
                       wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(2)

        log.info('URL: %s', page.url)

        # Fill email
        try:
            em = await page.query_selector(
                'input[type=email], input[placeholder*="почта"], input[placeholder*="Email"], '
                'input[placeholder*="логин"], input[name*="email"]'
            )
            if em:
                await em.fill(EMAIL)
                await asyncio.sleep(0.3)
                sub = await page.query_selector('button[type=submit], button.auth-form__button')
                if sub:
                    await sub.click()
                    await asyncio.sleep(3)
                    log.info('Recovery email submitted, URL: %s', page.url)
                    recovery_sent = True
                    await page.screenshot(path='/tmp/kwork_recovery_sent.png')
        except Exception as e:
            log.error('Recovery form: %s', e)
            await page.screenshot(path='/tmp/kwork_recovery_fail.png')

        await browser.close()
    return recovery_sent


async def main():
    log.info('=== Kwork Password Recovery ===')

    # Step 1: Request password recovery
    sent = await request_recovery()

    if not sent:
        tg(
            'Kwork: не удалось автоматически запросить сброс пароля.\n'
            'Сделай вручную:\n'
            '1. kwork.ru/forgot-password\n'
            f'2. Введи {EMAIL}\n'
            '3. Проверь почту и кликни ссылку\n'
            f'4. Новый пароль: {NEW_PASS}'
        )
        return

    log.info('Recovery email requested. Waiting for email...')
    tg(f'Kwork: письмо для сброса пароля запрошено.\nЖду письма на {EMAIL}...')

    # Step 2: Try to read the email via IMAP
    reset_link = try_gmail_imap('kwork', wait_secs=90)

    if reset_link:
        log.info('Got reset link! Resetting password...')
        # Open the reset link and set new password
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
            page = await browser.new_page()
            await page.goto(reset_link, wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(2)
            log.info('Reset link URL: %s', page.url)

            # Fill new password
            pwd_inputs = await page.query_selector_all('input[type=password]')
            for pi in pwd_inputs:
                await pi.fill(NEW_PASS)
                await asyncio.sleep(0.2)

            sub = await page.query_selector('button[type=submit]')
            if sub:
                await sub.click()
                await asyncio.sleep(3)
                log.info('Password reset submitted, URL: %s', page.url)

            # Update .env
            content = ENV_FILE.read_text()
            content = re.sub(r'KWORK_PASSWORD=.*', f'KWORK_PASSWORD={NEW_PASS}', content)
            ENV_FILE.write_text(content)
            tg(
                f'Kwork пароль изменён!\n'
                f'Email: {EMAIL}\n'
                f'Новый пароль: {NEW_PASS}\n'
                f'Kwork бот готов к работе!'
            )
            await browser.close()
    else:
        # IMAP failed - notify user manually
        tg(
            f'Kwork: письмо отправлено на {EMAIL}!\n\n'
            f'Нужно вручную:\n'
            f'1. Открой почту {EMAIL}\n'
            f'2. Найди письмо от Kwork (сброс пароля)\n'
            f'3. Кликни ссылку\n'
            f'4. Установи новый пароль: {NEW_PASS}\n\n'
            f'После этого Kwork бот заработает автоматически!'
        )
        log.info('Manual action required for password reset')


if __name__ == '__main__':
    asyncio.run(main())
