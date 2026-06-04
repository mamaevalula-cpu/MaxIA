#!/usr/bin/env python3
"""Kwork Fixed Scanner v3 — properly applies to projects via Предложить услугу form."""
import urllib.request, json, time, logging, os
import logging
log = logging.getLogger('kwork_scan')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [KWORK] %(message)s',
    handlers=[logging.FileHandler('/root/my_personal_ai/logs/kwork_scan.log'),
              logging.StreamHandler()])

from pathlib import Path

BROWSER = "http://127.0.0.1:8096"
ENV = Path("/root/my_personal_ai/.env")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT = os.getenv("TELEGRAM_CHAT_ID", "1985320458")
COOKIES_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")

def _check_kwork_cookies():
    """Check if Kwork session cookies are valid."""
    import os as _os
    f_path = '/root/my_personal_ai/data/kwork_cookies.txt'
    try:
        with open(f_path) as _f:
            content = _f.read().strip()
        if len(content) < 100:
            return False
        # Valid cookies contain session identifiers
        return any(k in content for k in ['session', '_ym', 'kwork', 'PHPSESS'])
    except Exception:
        return False


def env_get(k):
    if not ENV.exists(): return ''
    for l in ENV.read_text().splitlines():
        if '=' in l and l.startswith(k+'='): return l.split('=',1)[1].strip()
    return ''

def b(path, data=None):
    m = 'POST' if data is not None else 'GET'
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BROWSER+path, data=body,
          headers={'Content-Type':'application/json'}, method=m)
    try:
        with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())
    except Exception as e: return {'error': str(e)[:80]}

def get_project_links():
    code = ("var r=[]; document.querySelectorAll('a').forEach(function(a){"
            "if(a.href.match(/\\/projects\\/\\d+/) && a.textContent.trim().length>5){"
            "r.push({t:a.textContent.trim().slice(0,120),h:a.href})}});"
            "return JSON.stringify(r.slice(0,25));")
    result = b('/execute', {'code': code})
    if result.get('result') and result['result'] not in ('null', '[]', None):
        try: return json.loads(result['result'])
        except: pass
    return []

def groq_proposal(title, budget=''):
    """Generate personalized proposal — OpenRouter → fallback text."""
    FALLBACKS = [
        (
            f"Здравствуйте! Изучил задачу по теме «{title[:40]}». "
            "Готов реализовать — опыт 5+ лет в Python, Telegram-ботах и AI-интеграциях. "
            "Предлагаю: обсудить детали → быстрый прототип → итерация. "
            "Сроки и стоимость уточним после разговора."
        ),
        (
            f"Добрый день! Ваш проект «{title[:40]}» — именно моя специализация. "
            "Делал подобные задачи: боты, автоматизация, AI. "
            "Работаю быстро, с обратной связью. Готов обсудить сейчас."
        ),
        (
            f"Привет! Вижу задачу по {title[:30]} — разберусь быстро. "
            "Python/AI/бот разработчик, 5 лет опыта. "
            "Начну сразу после уточнения ТЗ."
        ),
    ]
    import hashlib
    fallback = FALLBACKS[int(hashlib.md5(title.encode()).hexdigest(), 16) % len(FALLBACKS)]

    or_key = env_get('OPENROUTER_API_KEY')
    if not or_key:
        return fallback
    try:
        import httpx
        r = httpx.post('https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Authorization': f'Bearer {or_key}',
                'Content-Type': 'application/json',
                'HTTP-Referer': 'http://77.90.2.171',
                'X-Title': 'MaxAI Kwork Bot',
            },
            json={'model': 'openai/gpt-3.5-turbo', 'messages': [
                {'role': 'system', 'content': (
                    'Ты Python/AI разработчик отвечаешь на проект на Kwork.ru. '
                    'Пиши КОРОТКИЙ персональный отклик на русском (3-4 предложения). '
                    'Упомяни конкретно задачу клиента. Никаких шаблонов. '
                    'Профессионально, конкретно, без лишних слов.'
                )},
                {'role': 'user', 'content': f'Проект: {title}\nБюджет: {budget}\nОтклик (3-4 предложения):'}
            ], 'max_tokens': 200}, timeout=15)
        if r.status_code == 200:
            text = r.json()['choices'][0]['message']['content'].strip()
            if len(text) > 30:
                return text
    except Exception as e:
        log.debug(f'OpenRouter error: {e}')
    return fallback

def tg_send(msg):
    tok = env_get('TELEGRAM_BOT_TOKEN')
    cid = env_get('TELEGRAM_OWNER_ID').strip()
    if not tok or not cid: return
    try:
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{tok}/sendMessage',
            data=json.dumps({'chat_id': cid, 'text': msg, 'parse_mode': 'HTML'}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        log.debug(f'TG send error: {e}')

def redis_conn():
    try:
        import redis as _r
        return _r.from_url(REDIS, decode_responses=True)
    except:
        return None

def redis_get(key):
    r = redis_conn()
    if not r: return None
    try:
        v = r.get(key)
        return json.loads(v) if v else None
    except: return None

def redis_set(key, val, ex=None):
    r = redis_conn()
    if not r: return
    try:
        kwargs = {'ex': ex} if ex else {}
        r.set(key, json.dumps(val, ensure_ascii=False), **kwargs)
    except: pass

def redis_incr(key, amount):
    r = redis_conn()
    if not r: return
    try: r.incrbyfloat(key, float(amount))
    except: pass

HOT_KW = [
    'python', 'бот', 'bot', 'ai', 'ml', 'автоматиза', 'парсинг', 'scraping', 'парсер',
    'gpt', 'telegram', 'api', 'fastapi', 'django', 'flask', 'selenium', 'playwright',
    'excel', 'таблиц', 'data', 'данных', 'скрипт', 'интеграц', 'openai',
    'агент', 'agent', 'чатбот', 'chatbot', 'нейросет', 'n8n', 'автоматическ'
]

def apply_to_project(proj, proposal):
    """Apply to a Kwork project. Returns True if successful."""
    url   = proj['url']
    title = proj['title']

    log.info(f"Applying to: {title[:60]}")

    nav = b('/navigate', {'url': url})
    if 'error' in nav:
        log.warning(f"  Navigate failed: {nav['error']}")
        return False
    time.sleep(3)

    # Click "Предложить услугу" if button exists
    btn = b('/find', {'text': 'Предложить услугу'})
    if 'error' in btn or not btn.get('x'):
        log.warning(f"  Apply button not found: {btn}")
        return False

    b('/click', {'x': int(btn['x']), 'y': int(btn['y'])})
    time.sleep(2)

    # Fill description via JS (handles rich text editor)
    proposal_js = proposal.replace('\\', '\\\\').replace("'", "\\'").replace('\n', '\\n')
    fill_js = f"""
var ta = document.querySelector('textarea[name="description"]');
if (ta) {{
    ta.value = '{proposal_js}';
    ta.dispatchEvent(new Event('input', {{bubbles:true}}));
    ta.dispatchEvent(new Event('change', {{bubbles:true}}));
    var box = ta.closest('.trumbowyg-box');
    if (box) {{
        var ed = box.querySelector('.trumbowyg-editor');
        if (ed) {{ ed.innerText = '{proposal_js}'; ed.dispatchEvent(new Event('input', {{bubbles:true}})); }}
    }}
    return 'filled';
}}
return 'not_found';
"""
    fill_result = b('/execute', {'code': fill_js})
    if fill_result.get('result') != 'filled':
        log.warning(f"  Description fill failed: {fill_result}")
        return False
    log.info("  Description filled OK")
    time.sleep(1)

    # Set price to minimum
    b('/execute', {'code': """
var pi = document.getElementById('offer-custom-price');
if (pi) {
    var ph = pi.placeholder || '1000';
    var m = ph.replace(/[^0-9 -]/g,'').trim().split(' - ')[0].trim() || '1000';
    pi.value = m;
    pi.dispatchEvent(new Event('input', {bubbles:true}));
    pi.dispatchEvent(new Event('change', {bubbles:true}));
}
"""})
    time.sleep(0.5)

    # Set deadline
    b('/execute', {'code': """
var dl = document.querySelector('input[placeholder*="рок"]');
if (dl) {
    dl.value = '3';
    dl.dispatchEvent(new Event('input', {bubbles:true}));
}
"""})
    time.sleep(0.5)

    # Submit
    submit_js = """
var found = null;
document.querySelectorAll('button,input[type=submit]').forEach(function(btn) {
    var t = btn.textContent.trim();
    if ((t === 'Предложить' || t === 'Отправить предложение') && !found) {
        found = btn;
    }
});
if (found) { found.click(); return 'clicked:' + found.textContent.trim(); }
return 'not_found';
"""
    submit_result = b('/execute', {'code': submit_js})
    if 'clicked' not in str(submit_result.get('result', '')):
        # Try /find as fallback
        sbtn = b('/find', {'text': 'Предложить'})
        if sbtn.get('x'):
            b('/click', {'x': int(sbtn['x']), 'y': int(sbtn['y'])})
            time.sleep(2)
            return True
        log.warning(f"  Submit not found: {submit_result}")
        return False

    time.sleep(2)
    log.info(f"  Submitted: {submit_result.get('result')}")
    return True

def scan():
    log.info("=== Kwork Scan v3 Start ===")
    b('/stealth', {})

    all_found = []
    seen = set()

    scan_urls = [
        # Разработка и IT (c=41)
        ('https://kwork.ru/projects?c=41',                'Scripts'),
        ('https://kwork.ru/projects?c=41&q=python',       'Python'),
        ('https://kwork.ru/projects?c=41&q=telegram',     'Telegram'),
        ('https://kwork.ru/projects?c=41&q=bot',          'Bot'),
        ('https://kwork.ru/projects?c=41&q=автоматизация','Automation'),
        ('https://kwork.ru/projects?c=41&q=парсинг',      'Parsing'),
        ('https://kwork.ru/projects?c=41&q=api',          'API'),
        # AI / Data Science (c=67)
        ('https://kwork.ru/projects?c=67',                'AI/Data'),
        ('https://kwork.ru/projects?c=67&q=gpt',          'GPT'),
        ('https://kwork.ru/projects?c=67&q=chatgpt',      'ChatGPT'),
        # Web dev (c=33)
        ('https://kwork.ru/projects?c=33&q=fastapi',      'FastAPI'),
        ('https://kwork.ru/projects?c=33&q=django',       'Django'),
        # Marketing / SMM (c=66)  
        ('https://kwork.ru/projects?c=66&q=бот',          'SMM Bot'),
        ('https://kwork.ru/projects?c=66&q=telegram',     'SMM Tg'),
        ('https://kwork.ru/projects?c=41&q=scraper', 'Scraper'),
        ('https://kwork.ru/projects?c=41&q=openai', 'OpenAI'),
        ('https://kwork.ru/projects?c=41&q=нейросеть', 'Neural'),
        # New categories for more discovery
        ('https://kwork.ru/projects?c=41&q=1с', '1C'),
        ('https://kwork.ru/projects?c=41&q=интеграция', 'Integration'),
        ('https://kwork.ru/projects?c=41&q=excel+python', 'Excel'),
        ('https://kwork.ru/projects?c=67&q=нейронная+сеть', 'Neural2'),
        ('https://kwork.ru/projects?c=67&q=llm', 'LLM'),
        ('https://kwork.ru/projects?c=41&q=crm', 'CRM'),
        ('https://kwork.ru/projects?c=41&q=bitrix', 'Bitrix24'),
        ('https://kwork.ru/projects?c=33&q=бот', 'WebBot'),
    ]

    for url, tag in scan_urls:
        log.info(f"[{tag}] {url}")
        b('/navigate', {'url': url})
        time.sleep(4)

        links = get_project_links()
        log.info(f"  Got {len(links)} links")

        for lnk in links:
            title = lnk.get('t', '').strip()
            href  = lnk.get('h', '')
            pid_part = href.rstrip('/').split('/projects/')[-1].split('/')[0]
            if not title or len(title) < 10 or not pid_part.isdigit() or pid_part in seen:
                continue
            seen.add(pid_part)
            tl = title.lower()
            hot = any(k in tl for k in HOT_KW)
            all_found.append({'title': title, 'url': href, 'id': pid_part, 'hot': hot, 'cat': tag})

        time.sleep(1)

    hot = [p for p in all_found if p['hot']]
    log.info(f"Total: {len(all_found)}, Hot: {len(hot)}")

    redis_set('kwork:scan:last', {
        'ts': time.time(), 'total': len(all_found),
        'hot': len(hot), 'projects': [p['title'] for p in all_found[:10]]
    })

    # Load applied with timestamps, clear entries older than 48h
    applied_raw = redis_get('kwork:applied_ts') or {}
    now_ts = time.time()
    ttl_48h = 48 * 3600
    # Clean stale entries (> 48h old)
    applied_raw = {pid: ts for pid, ts in applied_raw.items()
                   if (now_ts - float(ts)) < ttl_48h}
    applied_ids = set(applied_raw.keys())
    log.info(f"Applied cache: {len(applied_ids)} active IDs (< 48h old)")

    # Fallback: also check old plain list for backwards compat
    old_applied = redis_get('kwork:applied') or []
    for pid in old_applied:
        applied_ids.add(str(pid))

    sent = 0
    failed = 0

    for proj in hot[:5]:
        proj_id = str(proj['id'])
        if proj_id in applied_ids:
            log.info(f"  Skip (already applied): {proj['title'][:50]}")
            continue

        proposal = groq_proposal(proj['title'])
        log.info(f"  Proposal ({len(proposal)} chars): {proposal[:80]}...")

        ok = apply_to_project(proj, proposal)

        if ok:
            sent += 1
            applied_raw[proj_id] = now_ts
            redis_set('kwork:applied_ts', applied_raw)
            # Also update legacy list
            old_applied_upd = redis_get('kwork:applied') or []
            if proj_id not in old_applied_upd:
                old_applied_upd.append(proj_id)
            redis_set('kwork:applied', old_applied_upd[-100:])
            # Per-project timestamp
            r_conn = redis_conn()
            if r_conn:
                r_conn.set(f'kwork:proposal:{proj_id}:ts', now_ts)
                r_conn.incr('kwork:proposals:total')
            log.info(f"  SUCCESS applied to: {proj['title'][:60]}")
        else:
            failed += 1
            log.warning(f"  FAILED to apply: {proj['title'][:60]}")

        # Notify owner regardless of outcome
        tg_send(
            f"{'✅' if ok else '❌'} <b>Kwork</b>: {proj['title'][:80]}\n"
            f"<a href='{proj['url']}'>{proj['url'][:60]}</a>\n"
            f"{'Отклик отправлен!' if ok else 'Ошибка отправки'}"
        )
        time.sleep(3)

    # Get total proposals counter
    r_conn2 = redis_conn()
    total_props = int(r_conn2.get('kwork:proposals:total') or 0) if r_conn2 else 0

    log.info(f"Done: scanned={len(all_found)} hot={len(hot)} sent={sent} failed={failed} total_proposals={total_props}")
    return {'scanned': len(all_found), 'hot': len(hot), 'sent': sent, 'failed': failed, 'total_proposals': total_props}

if __name__ == '__main__':
    result = scan()
    print(json.dumps(result))
