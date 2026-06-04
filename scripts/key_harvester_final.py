#!/usr/bin/env python3
"""MaxAI Key Harvester Final — JS-based form interaction for React SPAs."""
import urllib.request, json, time, re, logging, base64, imaplib, email as em
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [KH] %(message)s')
log = logging.getLogger('kh')
B = 'http://127.0.0.1:8096'
ENV = Path('/root/my_personal_ai/.env')
SS = Path('/root/my_personal_ai/data/screenshots'); SS.mkdir(exist_ok=True)
EMAIL_A = 'froggyinternet@gmail.com'
EMAIL_B = 'jimmorrisoninlove@gmail.com'
GMAIL_APP = 'mgmfmgphxvxsvbdw'

def r(path, data=None, method=None):
    m = method or ('POST' if data is not None else 'GET')
    body = json.dumps(data).encode() if data is not None else b''
    req = urllib.request.Request(B+path, data=body, headers={'Content-Type':'application/json'}, method=m)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {'error': str(e)}

def nav(url, wait=5):
    log.info(f'=> {url}')
    r('/navigate', {'url': url}); time.sleep(wait)

def ss(name):
    x = r('/screenshot', method='GET')
    if x.get('data'):
        (SS/f'{name}_{int(time.time())}.jpg').write_bytes(base64.b64decode(x['data']))
    log.info(f'ss: {name}')

def js(code): return r('/execute', {'code': code})
def url():    return r('/health', method='GET').get('url', '')
def click(x, y): r('/click', {'x':x,'y':y}); time.sleep(1.5)

def wait_for_inputs(timeout=15):
    t = time.time()
    while time.time()-t < timeout:
        n = js('return document.querySelectorAll("input").length')
        if int(n.get('result',0) or 0) > 0:
            return True
        time.sleep(1)
    return False

def js_fill(selector, value):
    code = f"""
    const el = document.querySelector('{selector}');
    if(!el) return false;
    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nativeInputValueSetter.call(el, '{value}');
    el.dispatchEvent(new Event('input', {{bubbles:true}}));
    el.dispatchEvent(new Event('change', {{bubbles:true}}));
    return true;
    """
    result = js(code)
    return result.get('result') == 'true'

def gmail_wait(email, keyword, timeout=90):
    log.info(f'Gmail: [{keyword}] for {email}...')
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL('imap.gmail.com')
            m.login(email, GMAIL_APP); m.select('INBOX')
            _, ids = m.search(None, 'ALL')
            for mid in reversed((ids[0].split() or [])[-20:]):
                _, data = m.fetch(mid, '(RFC822)')
                msg = em.message_from_bytes(data[0][1])
                body = ''
                for part in (msg.walk() if msg.is_multipart() else [msg]):
                    if 'text' in part.get_content_type():
                        try: body += part.get_payload(decode=True).decode('utf-8', 'ignore')
                        except: pass
                full = str(msg.get('Subject','')) + ' ' + body
                age_h = str(msg.get('Date',''))
                if keyword.lower() in full.lower():
                    links = re.findall(r'https?://[^\s\'"<>]+', full)
                    for lnk in links:
                        if any(w in lnk for w in ['verify','confirm','magic','activate','login']):
                            m.close(); m.logout()
                            log.info(f'Got: {lnk[:80]}'); return lnk
            m.close(); m.logout()
        except Exception as e:
            log.debug(f'Gmail: {e}')
        time.sleep(15)
    return None

def save_env(k, v):
    c = ENV.read_text() if ENV.exists() else ''
    if f'{k}=' in c: c = re.sub(f'^{k}=.*$', f'{k}={v}', c, flags=re.MULTILINE)
    else: c += f'\n{k}={v}'
    ENV.write_text(c); log.info(f'.env: {k}={v[:30]}')

def harvest_fetchai():
    log.info('=== FETCH.AI ===')
    res = {'platform':'fetch_ai','status':'start','key':None}
    pw = 'MaxAI2026Fetch!'

    # Step 1: Login page (which has sign-up link)
    nav('https://accounts.fetch.ai/login/?redirect_uri=https%3A%2F%2Fagentverse.ai%2Fapi%2Fauth%3Fav-redirect-url%3D%2F&client_id=agentverse&response_type=code', wait=6)
    ss('fa1_login')
    log.info(f'URL: {url()}')

    # Step 2: Wait for React and find sign-up link via JS
    has_inputs = wait_for_inputs(10)
    log.info(f'Inputs on login page: {has_inputs}')

    # Find and click Create/Register/Sign Up link
    signup_href = js("""
    const links = [...document.querySelectorAll('a,button')];
    const found = links.find(el => /sign.?up|creat|register/i.test(el.textContent+el.href));
    if(found && found.href) return found.href;
    if(found) { found.click(); return 'clicked'; }
    return null;
    """)
    log.info(f'Signup link: {signup_href.get("result")}')

    sig_url = signup_href.get('result')
    if sig_url and sig_url.startswith('http'):
        nav(sig_url, wait=6)
    elif sig_url == 'clicked':
        time.sleep(4)
    else:
        nav('https://accounts.fetch.ai/signup', wait=5)
        if 'accounts.fetch.ai' not in url():
            nav('https://accounts.fetch.ai/register', wait=5)

    ss('fa2_signup'); log.info(f'Signup URL: {url()}')

    # Step 3: Wait for form and fill via React-compatible JS
    has_inputs = wait_for_inputs(12)
    log.info(f'Inputs on signup page: {has_inputs}')
    ss('fa3_form')

    # Inspect inputs
    inputs_info = js("return JSON.stringify([...document.querySelectorAll('input')].map(e=>({type:e.type,name:e.name,id:e.id,placeholder:e.placeholder})).slice(0,8))")
    log.info(f'Inputs: {inputs_info.get("result","[]")[:200]}')

    # Fill via JS (React-compatible)
    email_ok = False
    for sel in ['input[type="email"]','input[name="email"]','input[id="email"]','#username','input:first-of-type']:
        if js_fill(sel, EMAIL_A):
            log.info(f'Email filled via JS: {sel}'); email_ok = True; break

    if not email_ok:
        # Try Playwright fill as backup
        r('/fill', {'selector':'input[type="email"]','text':EMAIL_A})
        r('/fill', {'selector':'input:first-of-type','text':EMAIL_A})

    for sel in ['input[type="password"]','input[name="password"]','input[id="password"]']:
        if js_fill(sel, pw):
            log.info(f'Pass filled via JS: {sel}'); break
    for sel in ['input[name="confirmPassword"]','input[name="confirm_password"]','input:last-of-type']:
        if js_fill(sel, pw): log.info(f'Confirm filled: {sel}'); break

    ss('fa4_filled')

    # Step 4: Submit via JS click or button finding
    submitted = js("""
    const btn = [...document.querySelectorAll('button,input[type=submit]')]
        .find(b => /sign.?up|creat|register|submit|continue/i.test(b.textContent+b.type+b.value));
    if(btn){ btn.click(); return 'clicked_'+btn.textContent.trim().slice(0,20); }
    return null;
    """)
    log.info(f'Submit: {submitted.get("result")}')
    if not submitted.get('result'):
        r('/key', {'key':'Enter'})
    time.sleep(4); ss('fa5_submitted'); log.info(f'Post: {url()}')

    # Step 5: Email verification check
    cur = url()
    pt = js('return document.body.innerText.slice(0,500)').get('result','')
    if any(w in (cur+pt).lower() for w in ['verify','check email','confirm','sent']):
        log.info('Verification email expected')
        lnk = gmail_wait(EMAIL_A, 'fetch', 90) or gmail_wait(EMAIL_A, 'agentverse', 60)
        if lnk:
            nav(lnk, wait=5); ss('fa6_verified'); log.info('Verified!')
        else:
            res.update({'status':'needs_verify','note':'Check '+EMAIL_A}); save_env('FETCH_EMAIL',EMAIL_A); save_env('FETCH_PASSWORD',pw); return res

    # Step 6: Get API key
    time.sleep(3)
    api_key = None
    # Try to navigate to Agentverse with session
    nav('https://agentverse.ai/', wait=5); ss('fa7_agentverse')
    log.info(f'Agentverse: {url()}')

    for path in ['https://agentverse.ai/profile/api-keys','https://agentverse.ai/settings']:
        nav(path, wait=3); ss('fa8_apikeys')
        # Try create
        js("""
        const btn=[...document.querySelectorAll('button')].find(b=>/creat|generat|new.?key|add.?key/i.test(b.textContent));
        if(btn) btn.click();
        """); time.sleep(2)
        # Extract key
        key_val = js("""
        const els=[...document.querySelectorAll('input,code,pre,[class*=key],[class*=token]')];
        const found=els.find(e=>{const t=(e.value||e.textContent||'').trim(); return t.length>=30&&/^[a-zA-Z0-9_\\-\\.]+$/.test(t)});
        return found?(found.value||found.textContent.trim()):null
        """)
        val = key_val.get('result')
        if val and val!='null' and len(str(val))>25:
            api_key=val; log.info(f'Key at {path}'); break

    if api_key:
        save_env('FETCH_API_KEY',api_key); save_env('FETCH_AGENT_ADDRESS','agent1q'+re.sub(r'[^a-z0-9]','',api_key.lower())[:20])
        res.update({'status':'success','key':api_key}); log.info(f'FETCH KEY: {api_key[:30]}')
    else:
        res.update({'status':'registered_need_manual','manual_url':'https://agentverse.ai/profile/api-keys'})
        save_env('FETCH_EMAIL',EMAIL_A); save_env('FETCH_PASSWORD',pw)
        res['note']='Аккаунт создан. Войди в Браузере -> agentverse.ai/profile/api-keys -> создай и скопируй ключ'
        log.info('Registered. Manual step needed for API key.')

    ss('fa_done'); return res

def harvest_virtual():
    log.info('=== VIRTUAL PROTOCOL ===')
    res = {'platform':'virtual_protocol','status':'start','key':None}

    nav('https://app.virtuals.io', wait=5); ss('vp1_home')
    log.info(f'VP: {url()}')

    wait_for_inputs(8)
    inputs_count = js('return document.querySelectorAll("input").length').get('result',0)
    log.info(f'VP inputs: {inputs_count}')

    # Try email login
    email_btn = js("const b=[...document.querySelectorAll('button,a')].find(e=>/email/i.test(e.textContent));if(b){b.click();return 'found'}return null")
    if email_btn.get('result') == 'found':
        time.sleep(2); wait_for_inputs(8)
        for sel in ['input[type="email"]','input[placeholder*="email" i]']:
            if js_fill(sel, EMAIL_B):
                log.info('VP email filled')
                js("const b=[...document.querySelectorAll('button')].find(b=>/continu|next|login|sign/i.test(b.textContent));if(b)b.click()")
                time.sleep(3); ss('vp2_email')
                lnk = gmail_wait(EMAIL_B,'virtual',60)
                if lnk:
                    nav(lnk,wait=5); ss('vp3_magic')
                    for ap in ['https://app.virtuals.io/developer','https://app.virtuals.io/settings']:
                        nav(ap,wait=3)
                        val = js("const e=[...document.querySelectorAll('input,code,[class*=key]')].find(e=>{const t=(e.value||e.textContent||'').trim();return t.length>=20&&/^[a-zA-Z0-9_-]+$/.test(t)});return e?(e.value||e.textContent.trim()):null").get('result')
                        if val and val!='null':
                            save_env('VIRTUAL_PROTOCOL_API_KEY',val)
                            res.update({'status':'success','key':val}); log.info(f'VP KEY: {val[:25]}'); break
                break

    if not res.get('key'):
        res.update({'status':'wallet_required','note':'Virtual Protocol требует MetaMask. Открой Браузер -> app.virtuals.io -> Connect Wallet -> Settings -> API','manual_url':'https://app.virtuals.io'})
        save_env('VIRTUAL_EMAIL',EMAIL_B)
        log.info('VP: wallet required for API key')

    ss('vp_done'); return res

def finish(results):
    import redis as _r
    rd = _r.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
    missing=[x['platform'] for x in results if not x.get('key')]
    if missing:
        hitl={'req_id':f'hitl_keys_{int(time.time())}','type':'manual_api_key','dept':'aaas_fleet',
              'action':f'Ввести вручную API ключи: {", ".join(missing)}',
              'details':{'fetch_url':'https://agentverse.ai/profile/api-keys','virtual_url':'https://app.virtuals.io',
                         'email_fetch':EMAIL_A,'email_virtual':EMAIL_B,
                         'instructions':['1. Открой панель -> Браузер','2. Fetch.ai: agentverse.ai -> Profile -> API Keys -> Create','3. Virtual: app.virtuals.io -> Connect MetaMask -> Settings -> API','4. Скопируй ключ и сохрани в /root/my_personal_ai/.env'],
                         'env_keys':['FETCH_API_KEY','VIRTUAL_PROTOCOL_API_KEY','FETCH_SEED_PHRASE']},
              'state':'AWAITING_MANUAL_ACTION','ts':time.time()}
        k='swarm:hitl:queue'
        if rd.type(k) not in('none','list'): rd.delete(k)
        rd.lpush(k,json.dumps(hitl,default=str)); log.info(f'HITL: {missing}')
    try:
        env_c=ENV.read_text()
        tok=next((l.split('=',1)[1].strip() for l in env_c.splitlines() if l.startswith('TELEGRAM_BOT_TOKEN=')),'')
        cid=next((l.split('=',1)[1].strip() for l in env_c.splitlines() if l.startswith('TELEGRAM_OWNER_ID=')),'')
        if tok and cid:
            lines=['Harvester Done\n']
            for res in results:
                lines.append(f'{"OK" if res.get("key") else "WARN"} {res["platform"]}: {res["status"]}')
                if res.get('key'): lines.append(f'  KEY={res["key"][:30]}')
                if res.get('note'): lines.append(f'  {res["note"][:80]}')
                if res.get('manual_url'): lines.append(f'  URL={res["manual_url"]}')
            if missing:
                lines.append(f'\nManual needed: {", ".join(missing)}')
                lines.append('Panel -> Browser tab -> login -> copy API key')
            req=urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage',
                data=json.dumps({'chat_id':cid,'text':chr(10).join(lines)}).encode(),
                headers={'Content-Type':'application/json'},method='POST')
            urllib.request.urlopen(req,timeout=6); log.info('TG sent')
    except Exception as e: log.debug(f'TG:{e}')
    Path('/root/my_personal_ai/data/key_harvest_results.json').write_text(json.dumps(results,indent=2,default=str))
    print('\n=== DONE ===')
    for res in results: print(f'  {res["platform"]}: {res["status"]}'+(f' KEY={res["key"][:25]}' if res.get('key') else ''))

if __name__=='__main__':
    results=[harvest_fetchai(), harvest_virtual()]
    finish(results)
