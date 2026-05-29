#!/usr/bin/env python3
"""
browser_key_harvester.py v2 — Playwright Chrome automation + IMAP OTP for GitHub device verification.
"""
import json, re, imaplib, email as emaillib, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout

ENV_FILE = Path('/root/my_personal_ai/.env')
SS_DIR = Path('/root/my_personal_ai/logs/harvester_screenshots')
SS_DIR.mkdir(parents=True, exist_ok=True)


def load_env():
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def save_key(name, value):
    src = ENV_FILE.read_text()
    if (name + '=') in src:
        import re as _re
        src = _re.sub(rf'^{name}=.*$', name + '=' + value, src, flags=_re.MULTILINE)
    else:
        src = src.rstrip() + '\n' + name + '=' + value + '\n'
    ENV_FILE.write_text(src)
    print(f'  SAVED: {name}')


def tg_send(token, chat_id, text):
    import urllib.request
    try:
        data = json.dumps({'chat_id': chat_id, 'text': text[:4096], 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(
            'https://api.telegram.org/bot' + token + '/sendMessage',
            data=data, headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f'TG error: {e}')


import email.utils as _eu


import email.utils as _eu

def fetch_github_otp_imap(gmail_user, gmail_pass, wait_secs=60, after_ts=None):
    if after_ts is None:
        after_ts = time.time() - 180
    print(f'  [IMAP] Watching fresh OTP (max {wait_secs}s)...')
    deadline = time.time() + wait_secs
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            conn = imaplib.IMAP4_SSL('imap.gmail.com', 993)
            conn.login(gmail_user, gmail_pass)
            conn.select('INBOX')
            _, data = conn.search(None, '(FROM "noreply@github.com")')
            ids = data[0].split() if data[0] else []
            best_code, best_ts = None, 0
            for msg_id in ids:
                _, raw = conn.fetch(msg_id, '(RFC822)')
                msg = emaillib.message_from_bytes(raw[0][1])
                subject = str(msg.get('Subject', ''))
                if 'verif' not in subject.lower() and 'device' not in subject.lower():
                    continue
                try:
                    import email.utils as eu2
                    email_ts = eu2.parsedate_to_datetime(msg.get('Date','')).timestamp()
                except Exception:
                    email_ts = 0
                if email_ts < after_ts:
                    continue
                body = ''
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == 'text/plain':
                            pl = part.get_payload(decode=True)
                            if pl:
                                body = pl.decode('utf-8', errors='ignore')
                                break
                else:
                    pl = msg.get_payload(decode=True)
                    body = pl.decode('utf-8', errors='ignore') if pl else str(msg.get_payload())
                m = re.search(r'\b(\d{6})\b', body)
                if m and email_ts > best_ts:
                    best_ts, best_code = email_ts, m.group(1)
            conn.logout()
            if best_code:
                print(f'  [IMAP] Fresh OTP: {best_code}')
                return best_code
            remaining = deadline - time.time()
            if remaining > 5:
                print(f'  [IMAP] attempt {attempt} ? retrying in 6s...')
                time.sleep(6)
        except imaplib.IMAP4.error as e:
            print(f'  [IMAP] Auth error: {e}')
            return None
        except Exception as e:
            print(f'  [IMAP] Error: {e}')
            time.sleep(3)
    print('  [IMAP] Timed out')
    return None


def make_page(pw):
    br = pw.chromium.launch(
        headless=True,
        executable_path='/usr/bin/google-chrome',
        args=['--no-sandbox', '--disable-setuid-sandbox',
              '--disable-dev-shm-usage', '--disable-gpu',
              '--disable-blink-features=AutomationControlled'],
    )
    ctx = br.new_context(
        viewport={'width': 1280, 'height': 800},
        locale='ru-RU',
        user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    )
    return br, ctx, ctx.new_page()


# ─── HuggingFace ─────────────────────────────────────────────────────────────
def harvest_huggingface(page, email_addr, password):
    print('  [HuggingFace] logging in...')
    try:
        page.goto('https://huggingface.co/login', timeout=25000)
        page.wait_for_load_state('networkidle', timeout=12000)
        page.screenshot(path=str(SS_DIR / 'hf_login.png'))

        try:
            page.wait_for_selector('input[name="username"]', timeout=8000)
        except PwTimeout:
            return None, 'login form not found'

        page.fill('input[name="username"]', email_addr)
        page.fill('input[name="password"]', password)
        page.click('button[type="submit"]')
        page.wait_for_load_state('networkidle', timeout=15000)
        page.screenshot(path=str(SS_DIR / 'hf_after_login.png'))

        if '/login' in page.url:
            return None, 'login failed (wrong credentials?)'

        print('  [HuggingFace] getting tokens page...')
        page.goto('https://huggingface.co/settings/tokens', timeout=20000)
        page.wait_for_load_state('networkidle', timeout=10000)
        page.screenshot(path=str(SS_DIR / 'hf_tokens.png'))

        content = page.content()
        m = re.search(r'hf_[a-zA-Z0-9]{20,}', content)
        if m:
            return m.group(0), 'found existing token'

        print('  [HuggingFace] creating new token...')
        try:
            new_btn = page.query_selector('button:has-text("New token"), a:has-text("New token")')
            if new_btn:
                new_btn.click()
                page.wait_for_timeout(2000)
                name_f = page.query_selector('input[placeholder*="name" i], input[name*="name" i]')
                if name_f:
                    name_f.fill('MaxAI-VPS')
                gen_btn = page.query_selector('button:has-text("Generate"), button:has-text("Create")')
                if gen_btn:
                    gen_btn.click()
                    page.wait_for_load_state('networkidle', timeout=10000)
                    page.screenshot(path=str(SS_DIR / 'hf_new_token.png'))
                    content2 = page.content()
                    m2 = re.search(r'hf_[a-zA-Z0-9]{20,}', content2)
                    if m2:
                        return m2.group(0), 'created new token'
        except Exception as e:
            print(f'    create error: {e}')

        return None, 'logged in but no token visible — visit huggingface.co/settings/tokens'
    except PwTimeout:
        return None, 'timeout'
    except Exception as e:
        return None, str(e)


# ─── Kwork ────────────────────────────────────────────────────────────────────
def harvest_kwork(page, email_addr, password):
    print('  [Kwork] logging in...')
    try:
        page.goto('https://kwork.ru/login', timeout=25000)
        page.wait_for_load_state('networkidle', timeout=12000)
        page.screenshot(path=str(SS_DIR / 'kwork_login.png'))

        page.fill('input[placeholder*="Электронная почта"]', email_addr)
        page.fill('input[type="password"]', password)
        page.click('button[type="submit"], input[type="submit"]')
        page.wait_for_load_state('networkidle', timeout=15000)
        page.screenshot(path=str(SS_DIR / 'kwork_after_login.png'))

        if 'login' in page.url.lower():
            return None, 'login failed'

        return 'CONFIRMED', 'account verified (Kwork has no public API token)'
    except PwTimeout:
        return None, 'timeout'
    except Exception as e:
        return None, str(e)


# ─── GitHub ───────────────────────────────────────────────────────────────────
def harvest_github(page, email_addr, password, gmail_user, gmail_pass):
    print('  [GitHub] checking...')
    try:
        page.goto('https://github.com/settings/tokens/new', timeout=25000)
        page.wait_for_load_state('networkidle', timeout=12000)
        page.screenshot(path=str(SS_DIR / 'github_check.png'))

        if 'login' in page.url or 'session' in page.url:
            print('  [GitHub] need to login...')
            page.goto('https://github.com/login', timeout=15000)
            page.wait_for_load_state('networkidle', timeout=10000)
            page.fill('#login_field', email_addr)
            page.fill('#password', password)
            page.click('[type="submit"]')
            page.wait_for_load_state('networkidle', timeout=15000)
            page.screenshot(path=str(SS_DIR / 'github_after_login.png'))
            print(f'  [GitHub] URL after login: {page.url}')

            # Device verification flow (/session page)
            if '/session' in page.url:
                print('  [GitHub] Device verification page — fetching OTP from Gmail...')
                login_ts = time.time() - 10  # 10s buffer
                otp = fetch_github_otp_imap(gmail_user, gmail_pass, wait_secs=90, after_ts=login_ts)
                if not otp:
                    return None, 'device verification OTP not fetched — check Gmail App Password or do manually'

                # Fill OTP — GitHub uses input[autocomplete="one-time-code"] on /session
                otp_selectors = [
                    'input[autocomplete="one-time-code"]',
                    'input[name="otp"]',
                    '#app_totp',
                    'input[type="text"][maxlength="6"]',
                    'input[inputmode="numeric"]',
                    'input.form-control[type="text"]',
                ]
                filled = False
                for sel in otp_selectors:
                    try:
                        page.wait_for_selector(sel, timeout=3000)
                        page.fill(sel, otp)
                        print(f'  [GitHub] OTP filled via: {sel}')
                        filled = True
                        break
                    except PwTimeout:
                        continue

                if not filled:
                    page.screenshot(path=str(SS_DIR / 'github_session_page.png'))
                    return None, f'OTP input not found on /session page (screenshot saved)'

                page.screenshot(path=str(SS_DIR / 'github_otp_filled.png'))
                submit = page.query_selector('input[type="submit"], button[type="submit"]')
                if submit:
                    submit.click()
                else:
                    page.keyboard.press('Enter')
                page.wait_for_load_state('networkidle', timeout=15000)
                page.screenshot(path=str(SS_DIR / 'github_after_otp.png'))
                print(f'  [GitHub] URL after OTP: {page.url}')

            if '2fa' in page.url or 'two-factor' in page.url:
                return None, '2FA required — login manually at github.com'
            if '/login' in page.url and '/session' not in page.url:
                return None, 'login failed — check credentials'

            page.goto('https://github.com/settings/tokens/new', timeout=15000)
            page.wait_for_load_state('networkidle', timeout=12000)

        if 'login' in page.url or 'session' in page.url:
            return None, f'could not establish session (url: {page.url})'

        print('  [GitHub] generating Personal Access Token...')
        try:
            page.wait_for_selector('#token_description', timeout=10000)
        except PwTimeout:
            page.screenshot(path=str(SS_DIR / 'github_token_page_fail.png'))
            return None, f'token form not loaded (url: {page.url})'

        page.fill('#token_description', 'MaxAI-VPS')
        page.wait_for_timeout(500)
        try:
            cb = page.query_selector('input#user_oauth_application_scopes_repo')
            if cb and not cb.is_checked():
                cb.check()
            cb2 = page.query_selector('input#user_oauth_application_scopes_workflow')
            if cb2 and not cb2.is_checked():
                cb2.check()
        except Exception:
            pass
        page.click('button:has-text("Generate token")', timeout=8000)
        page.wait_for_load_state('networkidle', timeout=15000)
        page.screenshot(path=str(SS_DIR / 'github_token.png'))
        content = page.content()
        m = re.search(r'ghp_[a-zA-Z0-9]{36}', content)
        if m:
            return m.group(0), 'generated PAT'
        return None, 'could not extract token (screenshot saved at github_token.png)'
    except PwTimeout:
        return None, 'timeout'
    except Exception as e:
        return None, str(e)


# ─── OpenRouter ───────────────────────────────────────────────────────────────
def harvest_openrouter(page):
    print('  [OpenRouter] checking session...')
    try:
        page.goto('https://openrouter.ai/keys', timeout=25000)
        page.wait_for_load_state('networkidle', timeout=12000)
        page.screenshot(path=str(SS_DIR / 'openrouter.png'))
        content = page.content()
        m = re.search(r'sk-or-[a-zA-Z0-9\-_]{20,}', content)
        if m:
            return m.group(0), 'found existing key'
        return None, 'not logged in — register at openrouter.ai then /addkey OPENROUTER_API_KEY=sk-or-...'
    except PwTimeout:
        return None, 'timeout'
    except Exception as e:
        return None, str(e)


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    env = load_env()
    tg_token  = env.get('TELEGRAM_BOT_TOKEN', '')
    tg_chat   = env.get('TELEGRAM_CHAT_ID', '')
    email_addr    = env.get('EMAIL_FROGGY', '')
    passwd        = env.get('EMAIL_FROGGY_PASS', '')
    gmail_app_pass = env.get('GMAIL_APP_PASSWORD', '') or passwd
    kw_email  = env.get('KWORK_EMAIL', '')
    kw_pass   = env.get('KWORK_PASSWORD', '')
    results   = []

    print('\n=== Browser Key Harvester v2 (Playwright + IMAP OTP) ===\n')
    print(f'  Using email: {email_addr}  pass len: {len(passwd)}')

    with sync_playwright() as pw:
        br, ctx, page = make_page(pw)

        # HuggingFace
        if email_addr and passwd:
            tok, msg = harvest_huggingface(page, email_addr, passwd)
            if tok:
                save_key('HUGGINGFACE_TOKEN', tok)
                results.append(('ok', 'HuggingFace: ' + tok[:12] + '***'))
            else:
                results.append(('warn', 'HuggingFace: ' + msg))
            print('  Result:', msg)

        # Kwork
        if kw_email and kw_pass:
            tok, msg = harvest_kwork(page, kw_email, kw_pass)
            if tok:
                results.append(('ok', 'Kwork: ' + msg))
            else:
                results.append(('warn', 'Kwork: ' + msg))
            print('  Result:', msg)

        # GitHub (with IMAP OTP)
        if email_addr and passwd:
            tok, msg = harvest_github(page, email_addr, passwd, email_addr, gmail_app_pass)
            if tok:
                save_key('GITHUB_TOKEN', tok)
                results.append(('ok', 'GitHub: ' + tok[:12] + '***'))
            else:
                results.append(('warn', 'GitHub: ' + msg))
            print('  Result:', msg)

        # OpenRouter
        tok, msg = harvest_openrouter(page)
        if tok:
            save_key('OPENROUTER_API_KEY', tok)
            results.append(('ok', 'OpenRouter: ' + tok[:12] + '***'))
        else:
            results.append(('warn', 'OpenRouter: ' + msg))
        print('  Result:', msg)

        br.close()

    lines = ['<b>Key Harvester v2 завершён</b>', '']
    for status, text in results:
        icon = '✅' if status == 'ok' else '⚠️'
        lines.append(icon + ' ' + text)

    missing = []
    if not env.get('OPENROUTER_API_KEY'):
        missing.append('/addkey OPENROUTER_API_KEY=sk-or-...')
    if not env.get('GITHUB_TOKEN'):
        missing.append('/addkey GITHUB_TOKEN=ghp_...')
    if missing:
        lines += ['', '<b>Добавь вручную:</b>'] + missing

    msg_text = '\n'.join(lines)
    print('\n' + msg_text.replace('<b>', '').replace('</b>', ''))

    if tg_token and tg_chat:
        tg_send(tg_token, tg_chat, msg_text)
        print('\nTelegram report sent.')

    import subprocess
    subprocess.run(['systemctl', 'restart', 'maxai-tgbot'], timeout=10)
    print('Bot restarted.')


if __name__ == '__main__':
    main()
