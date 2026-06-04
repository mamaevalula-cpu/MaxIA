#!/usr/bin/env python3
"""Kwork Manual Assist — finds top projects and sends formatted proposals to Telegram."""
import urllib.request, json, os, re, time
from pathlib import Path
from playwright.sync_api import sync_playwright

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT  = os.getenv('TELEGRAM_CHAT_ID', '1985320458')
STATE = Path('/root/my_personal_ai/data/kwork_manual_state.json')
COOKIES_FILE = Path('/root/my_personal_ai/data/kwork_cookies.txt')

PROPOSALS = [
    "MaxAI Corporation готова выполнить ваш проект! Специализируемся именно на таких задачах. Готовы приступить сегодня!",
    "Команда MaxAI — эксперты Python/AI/Telegram. Гарантия качества, срок от 1 дня. Готовы взяться прямо сейчас!",
    "Привет! MaxAI Corp. Ваш проект — наша специализация. 50+ аналогичных задач. Напишите в ЛС!",
]

try:
    import redis as _rp, json as _jr
    _rdb = _rp.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
    _saved = _rdb.get('maxai:kwork:proposals')
    if _saved: PROPOSALS = _jr.loads(_saved)
except: pass

def tg(msg):
    if not TOKEN: return
    try:
        data = json.dumps({'chat_id': CHAT, 'text': msg, 'parse_mode': 'HTML', 'disable_web_page_preview': True}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'}), timeout=5)
    except: pass

def load_state():
    try: return json.loads(STATE.read_text())
    except: return {'sent_ids': [], 'total': 0}

def save_state(s): STATE.write_text(json.dumps(s, indent=2))

state = load_state()
cookie_str = COOKIES_FILE.read_text().strip() if COOKIES_FILE.exists() else ''
cookies_list = [{'name':k.strip(),'value':v.strip(),'domain':'.kwork.ru','path':'/'}
                for part in cookie_str.split('; ') if '=' in part
                for k,_,v in [part.partition('=')]]

projects_found = []

print('Scanning Kwork for hot projects...')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    ctx = browser.new_context(user_agent='Mozilla/5.0 (Windows NT 10.0) Chrome/120', locale='ru-RU')
    if cookies_list:
        ctx.add_cookies(cookies_list)
    page = ctx.new_page()
    
    # Scan multiple categories
    searches = [
        ('https://kwork.ru/projects?c=41&q=telegram+bot', 'Telegram Bot'),
        ('https://kwork.ru/projects?c=67&q=gpt+ai', 'AI/GPT'),
        ('https://kwork.ru/projects?c=41&q=python+automation', 'Python Auto'),
    ]
    
    for url, label in searches:
        try:
            page.goto(url, timeout=20000, wait_until='networkidle')
            time.sleep(3)
            
            # Get all project IDs
            links = page.evaluate("""
                () => {
                    const ids = new Set();
                    document.querySelectorAll('a[href]').forEach(a => {
                        const m = a.href.match(/projects\/([0-9]+)/);
                        if (m) ids.add(m[1]);
                    });
                    return Array.from(ids);
                }
            """)
            
            for pid in links[:5]:
                if pid in state['sent_ids']:
                    continue
                try:
                    page.goto(f'https://kwork.ru/projects/{pid}/view', timeout=12000, wait_until='networkidle')
                    time.sleep(2)
                    title = page.title()[:80]
                    body = page.inner_text('body')[:1000]
                    has_btn = 'Откликнуться' in body or 'Предложить' in body
                    price_m = re.search(r'(\d[\d\s]+)\s*руб', body)
                    price = price_m.group(0) if price_m else 'цена не указана'
                    
                    projects_found.append({
                        'id': pid,
                        'title': title.replace(' - Kwork', '').strip(),
                        'url': f'https://kwork.ru/projects/{pid}/view',
                        'can_apply': has_btn,
                        'price': price,
                        'label': label
                    })
                except: pass
        except: pass
    
    browser.close()

print(f'Found {len(projects_found)} new projects')

if not projects_found:
    tg('⚠️ Kwork: новых проектов не найдено')
else:
    # Send to Telegram formatted for easy manual apply
    import random
    proposal = random.choice(PROPOSALS)
    
    msg = f'🔥 <b>Kwork: {len(projects_found)} проектов для отклика!</b>\n\n'
    
    for p in projects_found[:5]:
        status = '✅' if p['can_apply'] else '🔗'
        msg += f'{status} <a href="{p["url"]}">{p["title"][:60]}</a>\n'
        msg += f'   💰 {p["price"]} | {p["label"]}\n\n'
    
    msg += f'📝 <b>Скопируй и вставь на каждой странице:</b>\n\n'
    msg += f'<code>{proposal}</code>\n\n'
    msg += '💡 Шаги: 1) Открой ссылку 2) Нажми «Откликнуться» 3) Вставь текст 4) Отправь'
    
    tg(msg)
    
    # Update state
    state['sent_ids'].extend([p['id'] for p in projects_found])
    state['sent_ids'] = state['sent_ids'][-500:]
    state['total'] = state.get('total', 0) + len(projects_found)
    save_state(state)
    print(f'Sent {len(projects_found)} projects to Telegram')

print('Done!')
