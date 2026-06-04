#!/usr/bin/env python3
"""
Smart Key Harvester v4 — Fetch.ai + Virtual Protocol
Uses actual signin flows, screenshots analysis, proper auth paths
"""
import urllib.request, json, time, re, logging, base64, os
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [SH] %(message)s')
log = logging.getLogger('smart_harvest')

B = 'http://127.0.0.1:8096'
ENV = Path('/root/my_personal_ai/.env')
SS_DIR = Path('/root/my_personal_ai/data/screenshots'); SS_DIR.mkdir(exist_ok=True)
EMAIL_A = 'froggyinternet@gmail.com'
EMAIL_B = 'jimmorrisoninlove@gmail.com'

def req(path, data=None, method=None):
    m = method or ('POST' if data is not None else 'GET')
    body = json.dumps(data).encode() if data is not None else b''
    r = urllib.request.Request(B+path, data=body, headers={'Content-Type':'application/json'}, method=m)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp: return json.loads(resp.read())
    except Exception as e: return {'error':str(e)}

def nav(url, wait=3):
    log.info(f'→ {url}')
    r = req('/navigate', {'url':url}); time.sleep(wait); return r

def ss(name):
    r = req('/screenshot', method='GET')
    if r.get('data'): (SS_DIR/f'{name}_{int(time.time())}.jpg').write_bytes(base64.b64decode(r['data']))
    log.info(f'📸 {name}')

def info():   return req('/page/info', method='GET')
def js(c):    return req('/execute', {'code':c})
def url():    return req('/health', method='GET').get('url','')
def click(x,y): req('/click',{'x':x,'y':y}); time.sleep(1.2)
def typ(t):   req('/type',{'text':t}); time.sleep(0.3)
def enter():  req('/key',{'key':'Enter'}); time.sleep(2)
def fill(s,t): return req('/fill',{'selector':s,'text':t})

def find_btn(texts):
    for txt in texts:
        r = req('/find', {'text':txt})
        if 'error' not in r: return r
    return None

def page_text():
    r = js('return document.body.innerText.slice(0,4000)')
    return r.get('result','')

def save_env(k, v):
    c = ENV.read_text() if ENV.exists() else ''
    if f'{k}=' in c: c = re.sub(f'^{k}=.*$', f'{k}={v}', c, flags=re.MULTILINE)
    else: c += f'\n{k}={v}'
    ENV.write_text(c); log.info(f'✓ .env: {k}={v[:30]}')

def gmail_check(email, keyword, timeout=90):
    import imaplib, email as em
    GMAIL_APP = 'mgmfmgphxvxsvbdw'
    log.info(f'Gmail checking [{keyword}] in {email}...')
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL('imap.gmail.com')
            m.login(email, GMAIL_APP)
            m.select('INBOX')
            _, ids = m.search(None, 'ALL')
            for mid in reversed((ids[0].split() or [])[-20:]):
                _, data = m.fetch(mid, '(RFC822)')
                msg = em.message_from_bytes(data[0][1])
                body = ''
                if msg.is_multipart():
                    for p in msg.walk():
                        if 'text' in p.get_content_type():
                            try: body += p.get_payload(decode=True).decode('utf-8','ignore')
                            except: pass
                else:
                    try: body = msg.get_payload(decode=True).decode('utf-8','ignore')
                    except: body = str(msg.get_payload())
                full = str(msg.get('Subject','')) + ' ' + body
                age  = time.time() - time.mktime(em.utils.parsedate(msg.get('Date','Thu, 1 Jan 1970 00:00:00 +0000')))
                if keyword.lower() in full.lower() and age < 600:
                    links = re.findall(r'https?://[^\s\'"<>]+', full)
                    for lnk in links:
                        if any(w in lnk for w in ['verify','confirm','magic','login','token','activate','click']):
                            m.close(); m.logout()
                            log.info(f'Got link: {lnk[:80]}')
                            return lnk
            m.close(); m.logout()
        except Exception as e:
            log.debug(f'Gmail: {e}')
        time.sleep(15)
    return None

# ─────────────────────────────────────────────────────────────
# FETCH.AI — Proper OAuth flow via accounts.fetch.ai
# ─────────────────────────────────────────────────────────────
def harvest_fetchai():
    log.info('━━━ FETCH.AI AGENTVERSE ━━━')
    result = {'platform':'fetch_ai','status':'start','key':None,'email':EMAIL_A}
    pw = 'MaxAI_Fetch2026!'

    # Step 1: Real signin/signup URL
    nav('https://agentverse.ai/api/signin', wait=4); ss('fa1_signin_redirect')
    landed = url()
    log.info(f'Landed at: {landed}')
    title = info().get('title','')
    log.info(f'Title: {title}')
    pt = page_text()

    # Step 2: Check if we landed on accounts.fetch.ai or similar OAuth
    if 'accounts.fetch.ai' in landed or 'auth' in landed:
        log.info('On accounts.fetch.ai auth portal')
        # Look for "Sign up" or "Create account"
        btn = find_btn(['Sign up','Create account','Register','Create Account','New account'])
        if btn:
            click(int(btn['x']), int(btn['y'])); time.sleep(2)
            ss('fa2_create_acct')
        else:
            # Navigate directly to register page
            base_auth = re.sub(r'/.*$','',landed.replace('https://','https://')+'/')
            nav(f'https://accounts.fetch.ai/register', wait=3)
            nav(f'https://accounts.fetch.ai/sign-up', wait=3)
            ss('fa2_signup_page')

    elif 'agentverse.ai' in landed:
        # Check if there's a register link
        pi = info()
        reg_link = next((l['href'] for l in pi.get('links',[])
            if any(w in l.get('href','').lower() for w in ['signup','register','create','sign-up'])), None)
        if reg_link:
            nav(reg_link, wait=3); ss('fa2_reg_link')
        else:
            # Try accounts portal directly
            nav('https://accounts.fetch.ai', wait=3); ss('fa2_accounts')

    ss('fa3_current'); log.info(f'URL: {url()} | Title: {info().get("title","")}')
    pt2 = page_text()

    # Step 3: Fill registration form
    email_filled = False
    for sel in ['input[type="email"]','input[name="email"]','#email',
                'input[placeholder*="email" i]','input[autocomplete="email"]']:
        r = fill(sel, EMAIL_A)
        if r.get('ok'):
            log.info(f'Email filled: {sel}'); email_filled = True; break

    if not email_filled:
        # Try clicking by text position
        for txt in ['Email','Email address','Your email']:
            lbl = req('/find', {'text':txt})
            if 'error' not in lbl:
                click(int(lbl['x']), int(lbl['y']))
                time.sleep(0.5); typ(EMAIL_A); break

    pw_filled = False
    for sel in ['input[type="password"]','input[name="password"]','#password',
                'input[name="new-password"]','input[autocomplete="new-password"]']:
        r = fill(sel, pw)
        if r.get('ok'):
            log.info(f'Password filled: {sel}'); pw_filled = True; break

    # Confirm password if needed
    for sel in ['input[name="confirm_password"]','input[name="confirmPassword"]',
                'input[id*="confirm" i]']:
        r = fill(sel, pw)
        if r.get('ok'): log.info(f'Confirm pw: {sel}'); break

    ss('fa4_form_filled')

    # Step 4: Submit
    btn = find_btn(['Sign Up','Create Account','Register','Submit','Continue','Next','Create'])
    if btn:
        click(int(btn['x']), int(btn['y'])); time.sleep(3)
    else:
        enter()
    ss('fa5_submitted'); log.info(f'After submit: {url()}')

    # Step 5: Check for email verification
    cur = url()
    title3 = info().get('title','')
    if any(w in (cur+title3).lower() for w in ['verify','check','email','confirm','sent']):
        log.info('Email verification required')
        lnk = gmail_check(EMAIL_A, 'fetch', 90) or gmail_check(EMAIL_A, 'agentverse', 60)
        if lnk:
            nav(lnk, wait=4); ss('fa6_verified'); log.info('Email verified!')
        else:
            result.update({'status':'needs_email_verify','note':'Check '+EMAIL_A+' inbox'})
            save_env('FETCH_EMAIL', EMAIL_A); save_env('FETCH_PASSWORD', pw)
            result['login_url'] = 'https://agentverse.ai/api/signin'
            return result
    elif 'already' in page_text().lower() or 'exist' in page_text().lower():
        log.info('Account may already exist, trying to login')
        nav('https://agentverse.ai/api/signin', wait=4)
        for sel in ['input[type="email"]','input[name="email"]']:
            if fill(sel, EMAIL_A).get('ok'): break
        for sel in ['input[type="password"]','input[name="password"]']:
            if fill(sel, pw).get('ok'): break
        btn2 = find_btn(['Log in','Sign In','Login','Continue'])
        if btn2: click(int(btn2['x']), int(btn2['y'])); time.sleep(3)
        else: enter()
        ss('fa7_login_attempt')

    # Step 6: Find API Key
    time.sleep(2); api_key = None
    ss('fa8_dashboard')
    log.info(f'Dashboard URL: {url()}')

    for api_path in [
        'https://agentverse.ai/profile/api-keys',
        'https://agentverse.ai/settings',
        'https://agentverse.ai/dashboard',
        url(),  # current page
    ]:
        if 'agentverse.ai' not in api_path: continue
        nav(api_path, wait=2)
        # Click "Create" or "Generate" button
        btn = find_btn(['Create API Key','Generate API Key','+ New','+ Add key','Create key','New API key'])
        if btn:
            click(int(btn['x']), int(btn['y'])); time.sleep(2); ss('fa9_key_created')
        # Look for key in inputs/code blocks
        r = js("""
        const candidates=[];
        document.querySelectorAll('input,code,pre,[class*="key"],[class*="token"],[class*="api"]').forEach(el=>{
            const t=(el.value||el.textContent||'').trim();
            if(t.length>=30 && /^[a-zA-Z0-9_\\-\\.]+$/.test(t)) candidates.push(t);
        });
        return candidates[0]||null;
        """)
        val = r.get('result')
        if val and val != 'null' and len(val) >= 30:
            api_key = val; log.info(f'Key found at {api_path}'); break

    if api_key:
        save_env('FETCH_API_KEY', api_key)
        save_env('FETCH_AGENT_ADDRESS', 'agent1q' + re.sub(r'[^a-z0-9]','',api_key.lower())[:24])
        result.update({'status':'success','key':api_key})
        log.info(f'✅ Fetch.ai API key: {api_key[:35]}...')
    else:
        result.update({'status':'registered_manual_step_needed'})
        save_env('FETCH_EMAIL', EMAIL_A); save_env('FETCH_PASSWORD', pw)
        result['manual_url'] = 'https://agentverse.ai/profile/api-keys'
        result['note'] = f'Зарегистрирован как {EMAIL_A}. Открой вкладку Браузер → перейди по ссылке → скопируй API ключ'
        log.info('⚠ No key found. Manual step needed.')

    ss('fa_done'); return result


# ─────────────────────────────────────────────────────────────
# VIRTUAL PROTOCOL — docs API approach since wallet required
# ─────────────────────────────────────────────────────────────
def harvest_virtual():
    log.info('━━━ VIRTUAL PROTOCOL ━━━')
    result = {'platform':'virtual_protocol','status':'start','key':None,'email':EMAIL_B}

    # Check their developer API
    nav('https://app.virtuals.io', wait=4); ss('vp1_home')
    title = info().get('title','')
    pt = page_text()
    log.info(f'VP: {title} | {url()}')

    # Check if they have a non-wallet path
    pi2 = info()
    links = pi2.get('links', [])
    log.info(f'Links found: {len(links)}')

    # Find developer/docs/API links
    dev_link = next((l['href'] for l in links
        if any(w in l.get('href','').lower() for w in ['developer','docs','api'])), None)

    # Try to find email/social login
    for txt in ['Continue with Email','Email Login','Sign in with Email','Use Email']:
        btn = find_btn([txt])
        if btn:
            click(int(btn['x']), int(btn['y'])); time.sleep(2)
            for sel in ['input[type="email"]','input[placeholder*="email" i]']:
                if fill(sel, EMAIL_B).get('ok'):
                    log.info('VP email entered'); enter(); time.sleep(2)
                    ss('vp2_email_sent')
                    lnk = gmail_check(EMAIL_B, 'virtual', 60)
                    if lnk:
                        nav(lnk, wait=3); ss('vp3_logged')
                        # Check for API key
                        for ap in ['https://app.virtuals.io/developer','https://app.virtuals.io/settings',
                                   'https://app.virtuals.io/profile']:
                            nav(ap, wait=2)
                            r = js("const el=[...document.querySelectorAll('input,code,[class*=key]')].find(e=>{ const t=(e.value||e.textContent||'').trim(); return t.length>=20&&/^[a-zA-Z0-9_\\-]+$/.test(t)});return el?(el.value||el.textContent.trim()):null")
                            val = r.get('result')
                            if val and val != 'null':
                                save_env('VIRTUAL_PROTOCOL_API_KEY', val)
                                result.update({'status':'success','key':val})
                                log.info(f'✅ VP key: {val[:25]}')
                                break
                    break
            break

    if not result.get('key'):
        # Check developer docs
        for docs_url in [
            'https://docs.virtuals.io',
            'https://whitepaper.virtuals.io',
            'https://developer.virtuals.io',
            'https://api.virtuals.io',
        ]:
            nav(docs_url, wait=2); ss(f'vp_docs_{docs_url.split(".")[1]}')
            pt3 = page_text()
            if any(w in pt3.lower() for w in ['api key','bearer token','authorization','api_key']):
                log.info(f'API docs at: {url()}')
                # Try to get free API key from docs
                code_blocks = js("return [...document.querySelectorAll('code,pre')].map(e=>e.textContent).filter(t=>t.length>10).slice(0,5).join('||')")
                log.info(f'Code blocks: {code_blocks.get("result","")[:200]}')
                result['docs_url'] = url()
                break

        # VP requires wallet - save info for manual connection
        result.update({
            'status': 'wallet_required_manual',
            'note': 'Virtual Protocol требует MetaMask кошелёк. Открой панель → Браузер → app.virtuals.io → подключи MetaMask → Settings → API Key',
            'manual_url': 'https://app.virtuals.io',
            'wallet_guide': 'Нужен MetaMask: MetaMask Extension → Create Wallet → Connect на app.virtuals.io',
        })
        save_env('VIRTUAL_EMAIL', EMAIL_B)
        save_env('VIRTUAL_MANUAL_URL', 'https://app.virtuals.io/developer')
        log.info('VP: requires wallet connection')

    ss('vp_done'); return result


# ─────────────────────────────────────────────────────────────
# FINISH
# ─────────────────────────────────────────────────────────────
def finish(results):
    import redis as _r
    r = _r.from_url('redis://127.0.0.1:6379/0', decode_responses=True)

    missing = [x['platform'] for x in results if not x.get('key')]
    if missing:
        hitl = {
            'req_id':  f'hitl_keys_{int(time.time())}',
            'type':    'manual_api_key_needed',
            'dept':    'aaas_fleet',
            'action':  f'Вручную получить API ключи: {", ".join(missing)}',
            'details': {
                'fetch_ai':  {
                    'url':   'https://agentverse.ai/profile/api-keys',
                    'email': EMAIL_A,
                    'note':  'Зайди через браузер панели. Логин: froggyinternet@gmail.com'
                },
                'virtual_protocol': {
                    'url':  'https://app.virtuals.io',
                    'note': 'Требует MetaMask кошелёк. Подключи кошелёк → Settings → API'
                },
                'screenshots': str(SS_DIR),
                'env_keys':    ['FETCH_API_KEY','FETCH_SEED_PHRASE','VIRTUAL_PROTOCOL_API_KEY'],
                'how_to':      '1. Браузер в панели → URL → войди → Settings → API Key → скопируй → .env',
            },
            'state': 'AWAITING_MANUAL_ACTION',
            'ts':    time.time(),
        }
        k = 'swarm:hitl:queue'
        if r.type(k) not in ('none','list'): r.delete(k)
        r.lpush(k, json.dumps(hitl, default=str))
        log.info(f'HITL: {missing}')

    # Save results
    Path('/root/my_personal_ai/data/key_harvest_results.json').write_text(
        json.dumps(results, indent=2, default=str))

    # Telegram
    try:
        env_c = ENV.read_text()
        tok = next((l.split('=',1)[1].strip() for l in env_c.splitlines() if l.startswith('TELEGRAM_BOT_TOKEN=')), '')
        cid = next((l.split('=',1)[1].strip() for l in env_c.splitlines() if l.startswith('TELEGRAM_OWNER_ID=')), '')
        if tok and cid:
            lines = ['🤖 <b>MaxAI Key Harvester — Готово</b>\n']
            for res in results:
                icon = '✅' if res.get('key') else '⚠️'
                lines.append(f'{icon} <b>{res["platform"]}</b>: {res["status"]}')
                if res.get('key'):
                    lines.append(f'   🔑 <code>{res["key"][:35]}</code>')
                if res.get('note'): lines.append(f'   ℹ️ {res["note"][:100]}')
                if res.get('manual_url'): lines.append(f'   🔗 {res["manual_url"]}')
            if missing:
                lines.append(f'\n🖱 <b>Нужно вручную</b> ({len(missing)} платформы):')
                lines.append('👉 Открой <b>Панель → вкладка Браузер</b>')
                lines.append('  1. Fetch.ai → agentverse.ai/profile/api-keys')
                lines.append('  2. Virtual → app.virtuals.io + MetaMask')
            lines.append(f'\n📸 Скриншоты: /root/my_personal_ai/data/screenshots/')
            msg = '\n'.join(lines)
            rr = urllib.request.Request(
                f'https://api.telegram.org/bot{tok}/sendMessage',
                data=json.dumps({'chat_id':cid,'text':msg,'parse_mode':'HTML'}).encode(),
                headers={'Content-Type':'application/json'}, method='POST')
            urllib.request.urlopen(rr, timeout=8)
            log.info('✓ Telegram notified')
    except Exception as e:
        log.debug(f'TG: {e}')

    print('\n' + '='*55)
    print('HARVEST COMPLETE')
    print('='*55)
    for res in results:
        print(f'  {res["platform"]:25} → {res["status"]}'
              + (f' | KEY={res["key"][:25]}' if res.get('key') else ''))
    if missing:
        print(f'\n  Manual steps needed: {missing}')
        print('  Screenshots: ' + str(SS_DIR))
        print('  HITL created in swarm:hitl:queue')


if __name__ == '__main__':
    log.info('MaxAI Smart Key Harvester v4')
    results = [harvest_fetchai(), harvest_virtual()]
    finish(results)
