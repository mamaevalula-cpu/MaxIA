#!/usr/bin/env python3
"""
kwork_api_agent.py — Kwork через REST API (mobile API, без браузера, без CAPTCHA)
Cron: 10:00 и 16:00 UTC
"""
import json, logging, os, time, random
from pathlib import Path
from datetime import datetime

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s',
    handlers=[logging.StreamHandler(),
              logging.FileHandler('/root/my_personal_ai/logs/kwork_api.log')])
log = logging.getLogger('kwork_api')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')
EMAIL    = os.environ.get('KWORK_EMAIL', 'froggyinternet@gmail.com')
PASSWORD = os.environ.get('KWORK_PASSWORD', 'Internetinternet!2')
STATE_FILE = Path('/root/my_personal_ai/data/kwork_api_state.json')

# Шаблоны предложений
PROPOSALS = [
    "Привет! Выполню задачу быстро и качественно. Python/API опыт 5+ лет. Начну сразу после согласования.",
    "Вижу задачу — готов взяться. Имею опыт с похожими проектами. Напишите в ЛС для уточнения деталей.",
    "Отличное ТЗ! Сделаю в срок с тестированием и документацией. Опыт 50+ реализованных проектов.",
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
        return {'token': None, 'total_applied': 0, 'won': 0, 'errors': []}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

def api_call(method, endpoint, data=None, token=None):
    """Call Kwork mobile API."""
    import urllib.request as ur
    url = f'https://api.kwork.ru/{endpoint}'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'okhttp/4.9.0',
        'Accept': 'application/json',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'

    body = None
    if data:
        body = '&'.join(f'{k}={v}' for k, v in data.items()).encode()

    try:
        req = ur.Request(url, data=body, headers=headers, method=method)
        with ur.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        log.warning('API call %s %s: %s', method, endpoint, e)
        return None

def api_call_v2(endpoint, data=None, token=None):
    """Kwork REST API v2 (main site)."""
    import requests
    url = f'https://kwork.ru/api/{endpoint}'
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        if data:
            r = requests.post(url, json=data, headers=headers, timeout=15)
        else:
            r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
        log.warning('API v2 %s: status %s', endpoint, r.status_code)
        return None
    except Exception as e:
        log.warning('API v2 %s: %s', endpoint, e)
        return None

def login_kwork():
    """Try to login via Kwork mobile/REST API."""
    import requests

    # Method 1: mobile API
    url = 'https://api.kwork.ru/user/login'
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'kwork/5.0 (Android 11)',
        'Accept': 'application/json',
    }
    data = f'login={EMAIL}&password={PASSWORD}'
    try:
        r = requests.post(url, data=data, headers=headers, timeout=15)
        log.info('Login mobile API: %s %s', r.status_code, r.text[:200])
        if r.status_code == 200:
            d = r.json()
            if d.get('success') and d.get('response', {}).get('token'):
                return d['response']['token']
    except Exception as e:
        log.warning('Mobile API login: %s', e)

    # Method 2: web API with session
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'ru-RU,ru;q=0.9',
    })
    try:
        # Get CSRF token first
        r0 = session.get('https://kwork.ru/login', timeout=10)
        import re
        csrf_match = re.search(r'csrf[_-]token["\s:=]+(["\s]*)([a-zA-Z0-9_-]{20,})', r0.text)
        csrf = csrf_match.group(2) if csrf_match else ''

        r = session.post('https://kwork.ru/api/auth/login', json={
            'login': EMAIL,
            'password': PASSWORD,
            'csrf': csrf
        }, timeout=15)
        log.info('Web API login: %s %s', r.status_code, r.text[:200])
        if r.status_code == 200:
            d = r.json()
            if d.get('success') or d.get('token'):
                return d.get('token', 'session_based')
    except Exception as e:
        log.warning('Web API login: %s', e)

    return None

def get_projects_page(category_id=41, page=1):
    """Scrape projects list via API."""
    import requests
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/javascript, */*',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': 'https://kwork.ru/projects',
    }
    params = {
        'c': category_id,   # Python
        'attr': '0',
        'page': page,
    }
    try:
        r = requests.get('https://kwork.ru/projects', params=params,
                        headers=headers, timeout=15)
        if r.status_code == 200:
            # Parse project IDs from HTML
            import re
            ids = re.findall(r'/projects/(\d+)/', r.text)
            titles = re.findall(r'class="wants-card__title[^"]*"[^>]*>([^<]+)', r.text)
            return list(set(ids))[:10], titles[:10]
    except Exception as e:
        log.warning('Get projects: %s', e)
    return [], []

def run():
    state = load_state()
    applied = 0

    log.info('Starting Kwork API agent...')

    # Try login
    token = login_kwork()
    if token:
        log.info('Logged in: token=%s...', str(token)[:20])
        state['token'] = token
        state['logged_in'] = True
    else:
        log.warning('Login failed — trying without auth (read-only)')
        state['logged_in'] = False

    # Get projects
    project_ids, titles = get_projects_page(category_id=41)
    log.info('Found %d projects: %s', len(project_ids), project_ids[:5])

    if project_ids:
        for pid in project_ids[:5]:
            try:
                log.info('Checking project %s', pid)
                # Try to apply
                import requests
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                if token and token != 'session_based':
                    headers['Authorization'] = f'Bearer {token}'

                r = requests.post(
                    f'https://kwork.ru/api/wants/{pid}/offer',
                    json={'description': random.choice(PROPOSALS), 'price': 3000, 'kworktime': 3},
                    headers=headers, timeout=10
                )
                log.info('Apply to %s: %s %s', pid, r.status_code, r.text[:100])
                if r.status_code == 200 and r.json().get('success'):
                    applied += 1
                time.sleep(random.uniform(2, 4))
            except Exception as e:
                log.warning('Apply %s: %s', pid, e)
    else:
        log.warning('No projects found — API blocked or requires auth')

    state['total_applied'] = state.get('total_applied', 0) + applied
    state['last_run'] = datetime.utcnow().isoformat()
    save_state(state)

    msg = (
        f"Kwork API отчёт {datetime.utcnow().strftime('%H:%M UTC')}\n"
        f"Логин: {'OK' if state.get('logged_in') else 'FAIL'}\n"
        f"Проектов найдено: {len(project_ids)}\n"
        f"Откликов сегодня: {applied}\n"
        f"Всего откликов: {state.get('total_applied', 0)}\n"
    )
    tg(msg)
    log.info('Done. Applied: %d', applied)

if __name__ == '__main__':
    run()
