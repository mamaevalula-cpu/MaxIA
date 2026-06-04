#!/usr/bin/env python3
"""Kwork Real Scanner v3 ? page/info + execute for project extraction."""
import urllib.request, json, time, logging, os
from pathlib import Path

LOG = Path('/root/my_personal_ai/logs/kwork_scan.log')
logging.basicConfig(level=logging.INFO, format='%(asctime)s [KWORK] %(message)s',
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
log = logging.getLogger()

ENV     = Path('/root/my_personal_ai/.env')
REDIS   = 'redis://127.0.0.1:6379/0'
BROWSER = 'http://127.0.0.1:8096'

def env_get(k):
    if not ENV.exists(): return ''
    for l in ENV.read_text().splitlines():
        if '=' in l and l.startswith(k+'='): return l.split('=',1)[1].strip()
    return ''

def b(path, data=None):
    m = 'POST' if data else 'GET'
    body = json.dumps(data).encode() if data else b''
    req = urllib.request.Request(BROWSER+path, data=body,
          headers={'Content-Type':'application/json'}, method=m)
    try:
        with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())
    except Exception as e: return {'error': str(e)[:60]}

def get_project_links():
    code = (
        "JSON.stringify([...document.querySelectorAll(\"a[href*='/projects/']\")]"
        ".slice(0,25).map(a=>({t:a.textContent.trim().slice(0,120),h:a.href})))"
        ".filter ? JSON.stringify([...document.querySelectorAll(\"a[href*='/projects/']\")]"
        ".slice(0,25).map(a=>({t:a.textContent.trim().slice(0,120),h:a.href}))) : '[]'"
    )
    # Simpler version
    code2 = "var r=[]; document.querySelectorAll('a').forEach(function(a){if(a.href.indexOf('/projects/')>-1&&a.textContent.trim().length>5){r.push({t:a.textContent.trim().slice(0,120),h:a.href})}});return JSON.stringify(r.slice(0,25));"
    result = b('/execute', {'code': code2})
    if result.get('result') and result['result'] != 'null':
        try: return json.loads(result['result'])
        except: pass
    return []

def groq_proposal(title, budget):
    key = env_get('GROQ_API_KEY')
    if not key: return f'??????? Python/AI ???????????. ??????? {title[:30]} ???????????. ??????? ??????.'
    try:
        import httpx
        r = httpx.post('https://api.groq.com/openai/v1/chat/completions',
            headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
            json={'model': 'llama-3.1-8b-instant', 'messages': [
                {'role': 'system', 'content': '?? Python/AI ???????????. ?????? ???????? ???????????????? ?????? (3 ???????????) ?? ?????. ??? ???????????. ?? ???????.'},
                {'role': 'user', 'content': f'?????: {title}\n??????: {budget}\n?????? ??????:'}
            ], 'max_tokens': 200}, timeout=15)
        if r.status_code == 200: return r.json()['choices'][0]['message']['content']
    except Exception as e: log.debug(f'Groq: {e}')
    return f'??????????????? ?? Python ? AI. ???????? {title[:40]} ? ????????? ????????. ????? ?????? ?????.'

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
    except Exception as e: log.debug(f'TG: {e}')

def redis_op(op, key, val=None):
    try:
        import redis as _r
        r = _r.from_url(REDIS, decode_responses=True)
        if op == 'get': v = r.get(key); return json.loads(v) if v else None
        if op == 'set': r.set(key, json.dumps(val, ensure_ascii=False), ex=86400*7)
        if op == 'incr': r.incrbyfloat(key, float(val))
    except: return None

HOT_KW = ['python','???','bot','ai','ml','???????','??????????','scraping','??????',
           'gpt','telegram','api','fastapi','django','flask','selenium','playwright',
           'excel','??????','data','??????','?????']

def scan():
    log.info("=== Kwork Scan Start ===")
    b('/stealth', {})
    
    all_found = []
    seen = set()
    
    for url, tag in [
        ('https://kwork.ru/projects?c=41',          'Python'),
        ('https://kwork.ru/projects?c=41&q=python', 'Python2'),
        ('https://kwork.ru/projects?c=67',          'AI/Data'),
        ('https://kwork.ru/projects?c=41&q=bot',    'Bot'),
    ]:
        log.info(f"[{tag}] {url}")
        b('/navigate', {'url': url})
        time.sleep(4)
        
        links = get_project_links()
        log.info(f"  Got {len(links)} links")
        
        for lnk in links:
            title = lnk.get('t','').strip()
            href  = lnk.get('h','')
            pid   = href.rstrip('/').split('/')[-1]
            if not title or len(title) < 10 or pid in seen or 'list' in href: continue
            seen.add(pid)
            hot = any(k in title.lower() for k in HOT_KW)
            all_found.append({'title':title,'url':href,'id':pid,'budget':'','hot':hot,'cat':tag})
        time.sleep(1)
    
    hot = [p for p in all_found if p['hot']]
    log.info(f"Total: {len(all_found)}, Hot: {len(hot)}")
    redis_op('set', 'kwork:scan:last', {'ts':time.time(),'total':len(all_found),'hot':len(hot),'projects':[p['title'] for p in all_found[:10]]})
    
    applied = redis_op('get','kwork:applied') or []
    sent = 0
    
    for proj in hot[:4]:
        if proj['id'] in applied: continue
        log.info(f"Hot: {proj['title'][:60]}")
        
        proposal = groq_proposal(proj['title'], proj['budget'])
        
        # Try to apply via browser
        b('/navigate', {'url': proj['url']})
        time.sleep(3)
        
        ok = False
        for txt in ['????????????','????????? ???????????']:
            btn = b('/find', {'text': txt})
            if 'error' not in btn and btn.get('x'):
                b('/click', {'x':int(btn['x']),'y':int(btn['y'])}); time.sleep(2)
                b('/fill', {'selector':'textarea','text':proposal}); time.sleep(1)
                send = b('/find', {'text': '?????????'})
                if 'error' not in send and send.get('x'):
                    b('/click', {'x':int(send['x']),'y':int(send['y'])}); time.sleep(2)
                    ok = True; sent += 1
                    applied.append(proj['id'])
                    redis_op('set','kwork:applied',applied[-100:])
                break
        
        tg_send(
            f"{'??' if ok else '??'} <b>Kwork</b>: {proj['title'][:80]}\n"
            f"<i>{proj['url'][:60]}</i>\n"
            f"{'? ?????? ?????????' if ok else '?? ????? ???????'}"
        )
        time.sleep(3)
    
    if sent:
        redis_op('incr','aaas:revenue:kwork:total', sent*0.05)
        redis_op('incr','aaas:revenue:total_usd', sent*0.05)
    
    log.info(f"Done: scanned={len(all_found)} hot={len(hot)} sent={sent}")
    return {'scanned':len(all_found),'hot':len(hot),'sent':sent}

if __name__ == '__main__':
    result = scan()
    print(json.dumps(result))
