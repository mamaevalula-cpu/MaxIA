#!/usr/bin/env python3
"""
key_harvester.py — авто-получение API ключей с платформ по логину/паролю.
Запуск: python3 key_harvester.py
"""
import json, os, re, time, urllib.request, urllib.parse, http.cookiejar
from pathlib import Path

ENV_FILE = Path('/root/my_personal_ai/.env')

def load_env():
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            k, _, v = line.partition('=')
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def save_key(name, value):
    src = ENV_FILE.read_text()
    if f'\n{name}=' in src or src.startswith(f'{name}='):
        # update existing
        import re as _re
        src = _re.sub(rf'^{name}=.*$', f'{name}={value}', src, flags=re.MULTILINE)
    else:
        src += f'\n{name}={value}'
    ENV_FILE.write_text(src)
    print(f'  ✅ Saved {name}={value[:8]}***')

def tg_notify(token, chat_id, text):
    try:
        data = json.dumps({'chat_id': chat_id, 'text': text[:4096], 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f'TG notify error: {e}')

def try_kwork(env):
    """Kwork.ru — login and get API token."""
    email = env.get('KWORK_EMAIL', '')
    passwd = env.get('KWORK_PASSWORD', '')
    if not email or not passwd:
        return None, 'No Kwork credentials'

    print('  Trying Kwork login...')
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')]

    try:
        # Get CSRF token first
        resp = opener.open('https://kwork.ru/login', timeout=15)
        html = resp.read().decode('utf-8', errors='ignore')
        csrf = re.search(r'name="_token"\s+value="([^"]+)"', html)
        csrf_token = csrf.group(1) if csrf else ''

        # Login
        login_data = urllib.parse.urlencode({
            'email': email,
            'password': passwd,
            '_token': csrf_token,
        }).encode()
        req = urllib.request.Request(
            'https://kwork.ru/login',
            data=login_data,
            headers={'Referer': 'https://kwork.ru/login', 'Content-Type': 'application/x-www-form-urlencoded'},
        )
        resp2 = opener.open(req, timeout=15)
        html2 = resp2.read().decode('utf-8', errors='ignore')

        # Check if logged in — look for API token in profile/settings
        resp3 = opener.open('https://kwork.ru/settings/api', timeout=15)
        html3 = resp3.read().decode('utf-8', errors='ignore')
        token_match = re.search(r'["\']token["\']\s*[:\s]+["\']([a-zA-Z0-9_\-]{20,})["\']', html3)
        if not token_match:
            token_match = re.search(r'API[^"]*token[^"]*["\']([a-zA-Z0-9_\-]{20,})["\']', html3, re.I)
        if token_match:
            return token_match.group(1), 'OK'

        # Try /profile/api
        resp4 = opener.open('https://kwork.ru/profile/api', timeout=15)
        html4 = resp4.read().decode('utf-8', errors='ignore')
        token_match2 = re.search(r'["\']([a-zA-Z0-9]{32,64})["\']', html4)
        if token_match2:
            return token_match2.group(1), 'OK from profile'

        return None, f'Logged in but no token found (check manually: kwork.ru/settings)'
    except Exception as e:
        return None, f'Error: {e}'

def try_huggingface(env):
    """HuggingFace — check for existing token or get from profile."""
    email = env.get('EMAIL_FROGGY', '')
    passwd = env.get('EMAIL_FROGGY_PASS', '')
    if not email or not passwd:
        return None, 'No email credentials'

    print('  Trying HuggingFace login...')
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')]

    try:
        # HuggingFace login via form
        resp = opener.open('https://huggingface.co/login', timeout=15)
        html = resp.read().decode('utf-8', errors='ignore')
        csrf = re.search(r'name="csrf"\s+value="([^"]+)"', html)
        csrf_token = csrf.group(1) if csrf else ''

        login_data = urllib.parse.urlencode({
            'email': email,
            'password': passwd,
            'csrf': csrf_token,
        }).encode()
        req = urllib.request.Request(
            'https://huggingface.co/login',
            data=login_data,
            headers={'Referer': 'https://huggingface.co/login',
                     'Content-Type': 'application/x-www-form-urlencoded'},
        )
        opener.open(req, timeout=15)

        # Get access tokens
        resp2 = opener.open('https://huggingface.co/settings/tokens', timeout=15)
        html2 = resp2.read().decode('utf-8', errors='ignore')
        # Look for existing tokens
        token_match = re.search(r'hf_[a-zA-Z0-9]{20,}', html2)
        if token_match:
            return token_match.group(0), 'Found existing token'
        return None, 'Logged in but no token found — create at huggingface.co/settings/tokens'
    except Exception as e:
        return None, f'Error: {e}'

def main():
    env = load_env()
    tg_token = env.get('TELEGRAM_BOT_TOKEN', '')
    tg_chat = env.get('TELEGRAM_CHAT_ID', '')
    results = []

    print('\n=== Key Harvester ===\n')

    # Kwork
    print('[ Kwork ]')
    kw_token, kw_msg = try_kwork(env)
    if kw_token:
        save_key('KWORK_API_TOKEN', kw_token)
        results.append(f'✅ Kwork: получен токен')
    else:
        results.append(f'⚠️ Kwork: {kw_msg}')
    print(f'  → {kw_msg}')

    # HuggingFace
    print('[ HuggingFace ]')
    hf_token, hf_msg = try_huggingface(env)
    if hf_token:
        save_key('HUGGINGFACE_TOKEN', hf_token)
        results.append(f'✅ HuggingFace: {hf_token[:8]}***')
    else:
        results.append(f'⚠️ HuggingFace: {hf_msg}')
    print(f'  → {hf_msg}')

    # Report via Telegram
    msg = '<b>🔑 Key Harvester результаты</b>\n\n' + '\n'.join(results)
    msg += '\n\n<b>Нужна ручная регистрация:</b>\n'
    msg += '• OpenRouter: openrouter.ai/keys\n'
    msg += '• DeepSeek: platform.deepseek.com/api_keys\n'
    msg += '• GitHub: github.com/settings/tokens\n\n'
    msg += 'После получения ключа пиши боту:\n<code>/addkey OPENROUTER_API_KEY=sk-or-...</code>'

    if tg_token and tg_chat:
        tg_notify(tg_token, tg_chat, msg)
        print('\nTelegram report sent.')
    print('\nDone.')

if __name__ == '__main__':
    main()
