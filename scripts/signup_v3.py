#!/usr/bin/env python3
"""V3: Together.ai sign-in (existing account), Perplexity signup, OpenRouter sign-in attempt"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('signup_v3')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'
PASS  = 'FroggyBot2025!TG'

def imap_latest(kw='', since_min=15):
    try:
        m = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        m.login(GMAIL, GPASS)
        m.select('INBOX')
        since = (datetime.now()-timedelta(minutes=since_min)).strftime('%d-%b-%Y')
        _, d = m.search(None, 'SINCE ' + since)
        ids = d[0].split()[-25:] if d[0] else []
        for mid in reversed(ids):
            _, d2 = m.fetch(mid, '(RFC822)')
            msg = elib.message_from_bytes(d2[0][1])
            frm = str(msg.get('From','')).lower()
            subj = str(msg.get('Subject','')).lower()
            if not kw or kw.lower() in frm or kw.lower() in subj:
                body = ''
                if msg.is_multipart():
                    for p in msg.walk():
                        if p.get_content_type() in ('text/plain','text/html'):
                            try: body += p.get_payload(decode=True).decode('utf-8',errors='replace')
                            except: pass
                else:
                    try: body = msg.get_payload(decode=True).decode('utf-8',errors='replace')
                    except: pass
                m.logout()
                return body
        m.logout()
    except Exception as e:
        log.warning('IMAP: %s', e)
    return None

async def wait_email(kw, tries=20, since=12):
    for i in range(tries):
        await asyncio.sleep(6)
        b = imap_latest(kw, since)
        if b: return b
        if (i+1)%5==0: log.info('  waiting %s %d/%d', kw, i+1, tries)
    return None

async def get_text(page):
    c = await page.get_content()
    c = re.sub(r'<style[^>]*>.*?</style>', '', c, flags=re.DOTALL)
    c = re.sub(r'<script[^>]*>.*?</script>', '', c, flags=re.DOTALL)
    c = re.sub(r'<[^>]+>', ' ', c)
    return re.sub(r'\s+', ' ', c).strip()

async def js(page, script):
    try:
        return await page.evaluate("(function() { " + script + " })()")
    except Exception as e:
        log.debug('JS: %s', e)
        return None

async def fill(page, selector, value):
    escaped = value.replace("'", "\\'")
    return await js(page,
        "var el = document.querySelector('" + selector + "');"
        "if (!el) return false;"
        "var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');"
        "if (setter && setter.set) { setter.set.call(el, '" + escaped + "'); }"
        "else { el.value = '" + escaped + "'; }"
        "el.dispatchEvent(new Event('input', {bubbles: true}));"
        "el.dispatchEvent(new Event('change', {bubbles: true}));"
        "return true;"
    )

async def click_btn(page, patterns):
    pat = '|'.join(patterns)
    return await js(page,
        "var re = new RegExp('" + pat + "', 'i');"
        "var btns = Array.from(document.querySelectorAll('button,a[role=\"button\"],input[type=\"submit\"]'));"
        "var b = btns.find(function(b) { return re.test(b.textContent) && b.offsetParent; });"
        "if (!b) b = document.querySelector('button[type=\"submit\"]');"
        "if (b) { b.click(); return b.textContent.trim().slice(0,30); }"
        "return null;"
    )

async def enter_otp(page, code):
    otp6 = await page.query_selector_all('input[maxlength="1"]')
    otp1 = await page.select('input[maxlength="6"]')
    if len(otp6) >= 6:
        for d, el in zip(code[:6], otp6[:6]):
            await el.mouse_click()
            await el.send_keys(d)
            await asyncio.sleep(0.1)
    elif otp1:
        await otp1.mouse_click()
        await otp1.send_keys(code)
    await asyncio.sleep(1)
    for txt in ['Verify', 'Continue', 'Submit']:
        b = await page.find(txt, best_match=True)
        if b:
            try:
                if await b.get_position():
                    await b.mouse_click()
                    await asyncio.sleep(4)
                    return True
            except: pass
    return False

def save(name, value):
    set_key(ENV, name, value)
    log.info('SAVED %s = %s...', name, value[:20])
    try:
        import httpx
        env = dotenv_values(ENV)
        tok = env.get('TELEGRAM_BOT_TOKEN','')
        cid = env.get('TELEGRAM_CHAT_ID','')
        if tok and cid:
            httpx.post(
                f'https://api.telegram.org/bot{tok}/sendMessage',
                json={'chat_id': cid, 'text': f'New key obtained: {name}'},
                timeout=5
            )
    except: pass


# ── Together.ai: SIGN IN (account exists, need key) ─────────────────────────
async def together_signin(browser):
    log.info('=== Together.ai SIGN IN ===')
    # Try via Auth0 token endpoint first
    try:
        import httpx
        # Try to get a token via Auth0 using resource owner password grant
        # (not all providers support this, but worth trying)
        resp = httpx.post(
            'https://auth.together.xyz/oauth/token',
            json={
                'grant_type': 'password',
                'username': GMAIL,
                'password': PASS,
                'audience': 'https://api.together.xyz',
                'scope': 'openid profile email',
                'client_id': 'together-ai',
            },
            timeout=10
        )
        log.info('Auth0 password grant: %d %s', resp.status_code, resp.text[:200])
        if resp.status_code == 200:
            data = resp.json()
            token = data.get('access_token','')
            if token:
                log.info('Got Auth0 token: %s...', token[:20])
    except Exception as e:
        log.debug('Auth0 direct: %s', e)

    # Browser signin
    try:
        page = await browser.get('https://api.together.xyz/signin')
        await asyncio.sleep(10)
        t = await get_text(page)
        log.info('Signin page: %s', t[:200])

        # List all inputs
        inputs = await js(page,
            "return JSON.stringify(Array.from(document.querySelectorAll('input'))"
            ".map(function(i) { return {type: i.type, name: i.name, id: i.id, ph: i.placeholder}; }));"
        )
        log.info('Inputs: %s', str(inputs)[:400])

        # Try email fill
        for sel in ['input[type="email"]', 'input[name="email"]', '#email', 'input[placeholder*="email" i]']:
            if await fill(page, sel, GMAIL):
                log.info('Email filled: %s', sel)
                break

        # Try password fill
        for sel in ['input[type="password"]', 'input[name="password"]', '#password']:
            if await fill(page, sel, PASS):
                log.info('Password filled: %s', sel)
                break

        result = await click_btn(page, ['sign.?in', 'log.?in', 'continue', 'enter'])
        log.info('Sign in click: %s', result)
        await asyncio.sleep(10)

        t2 = await get_text(page)
        log.info('After signin: %s', t2[:200])

        # Check for OTP
        otp_f = await page.query_selector_all('input[maxlength="1"]')
        if len(otp_f) >= 1:
            body = await wait_email('', 15, 5)
            if body:
                codes = re.findall(r'\b[0-9]{6}\b', body)
                if codes:
                    await enter_otp(page, codes[0])
                    await asyncio.sleep(5)

        # Try API keys page
        kp = await browser.get('https://api.together.xyz/settings/api-keys')
        await asyncio.sleep(8)
        kc = await kp.get_content()
        tok = re.search(r'[0-9a-f]{64}', kc)
        if tok:
            save('TOGETHER_API_KEY', tok.group())
            return True
        kt = await get_text(kp)
        log.info('Keys page: %s', kt[:200])
    except Exception as e:
        log.error('Together signin: %s', e)
    return False


# ── Perplexity: New signup ───────────────────────────────────────────────────
async def perplexity_signup(browser):
    log.info('=== Perplexity signup ===')
    if dotenv_values(ENV).get('PERPLEXITY_API_KEY',''):
        log.info('Already have key')
        return True
    try:
        # Perplexity uses email magic link or OAuth
        page = await browser.get('https://www.perplexity.ai/')
        await asyncio.sleep(10)
        t = await get_text(page)
        log.info('Perplexity home: %s', t[:200])

        # Accept cookies
        await js(page,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return /accept/i.test(b.textContent) && b.offsetParent; });"
            "if (b) b.click();"
            "return 'done';"
        )
        await asyncio.sleep(2)

        # Find sign up button
        signup_clicked = await js(page,
            "var btns = Array.from(document.querySelectorAll('button,a'));"
            "var b = btns.find(function(b) { return /sign.?up|create|get.?started|try.?free/i.test(b.textContent) && b.offsetParent; });"
            "if (b) { b.click(); return b.textContent.trim().slice(0,30); }"
            "return null;"
        )
        log.info('Signup click: %s', signup_clicked)
        await asyncio.sleep(5)

        t2 = await get_text(page)
        log.info('After signup click: %s', t2[:200])

        # Fill email
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
            if await fill(page, sel, GMAIL):
                log.info('Email filled: %s', sel)
                break

        result = await click_btn(page, ['continue', 'sign.?up', 'send', 'submit', 'next'])
        log.info('Submit: %s', result)
        await asyncio.sleep(10)

        t3 = await get_text(page)
        log.info('After submit: %s', t3[:200])

        # Wait for magic link or OTP
        body = await wait_email('perplexity', 20, 8)
        if not body:
            body = await wait_email('', 10, 5)

        if body:
            links = re.findall(r'https://[^\s<>"]+(?:perplexity|verify|confirm|magic)[^\s<>"]*', body, re.I)
            codes = re.findall(r'\b[0-9]{6}\b', body)
            log.info('Links: %d Codes: %s', len(links), codes[:2])
            if links:
                vp = await browser.get(links[0])
                await asyncio.sleep(8)
                log.info('Verify: %s', (await get_text(vp))[:150])
            elif codes:
                await enter_otp(page, codes[0])
                await asyncio.sleep(6)

        # Check API keys
        kp = await browser.get('https://www.perplexity.ai/settings/api')
        await asyncio.sleep(7)
        kc = await kp.get_content()
        tok = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc)
        if tok:
            save('PERPLEXITY_API_KEY', tok.group())
            return True
        kt = await get_text(kp)
        log.info('API page: %s', kt[:300])

        # Try to create key
        await js(kp,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return /create|generate|new|add/i.test(b.textContent) && b.offsetParent; });"
            "if (b) b.click();"
            "return 'clicked';"
        )
        await asyncio.sleep(5)
        kc2 = await kp.get_content()
        tok2 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc2)
        if tok2:
            save('PERPLEXITY_API_KEY', tok2.group())
            return True
    except Exception as e:
        log.error('Perplexity: %s', e)
    return False


# ── OpenRouter: Try sign-in (account may already exist) ─────────────────────
async def openrouter_signin(browser):
    log.info('=== OpenRouter sign-in attempt ===')
    if dotenv_values(ENV).get('OPENROUTER_API_KEY',''):
        log.info('Already have key')
        return True
    try:
        # Try sign in with existing credentials
        page = await browser.get('https://openrouter.ai/sign-in')
        await asyncio.sleep(8)
        t = await get_text(page)
        log.info('Sign-in page: %s', t[:200])

        for sel in ['input[name="identifier"]', 'input[type="email"]', 'input[name="email"]']:
            if await fill(page, sel, GMAIL):
                log.info('Email filled: %s', sel)
                break

        result = await click_btn(page, ['continue', 'sign.?in', 'next'])
        log.info('Continue: %s', result)
        await asyncio.sleep(6)

        t2 = await get_text(page)
        log.info('After continue: %s', t2[:200])

        # Password step
        for sel in ['input[type="password"]', 'input[name="password"]']:
            if await fill(page, sel, PASS):
                result2 = await click_btn(page, ['continue', 'sign.?in', 'submit'])
                log.info('Password submit: %s', result2)
                await asyncio.sleep(6)
                break

        # OTP step
        otp_f = await page.query_selector_all('input[maxlength="1"]')
        otp1 = await page.select('input[maxlength="6"]')
        if len(otp_f) >= 1 or otp1:
            log.info('OTP form found, waiting email...')
            body = await wait_email('clerk', 15, 5)
            if not body: body = await wait_email('openrouter', 8, 5)
            if body:
                codes = re.findall(r'\b[0-9]{6}\b', body)
                if codes:
                    await enter_otp(page, codes[0])
                    await asyncio.sleep(6)

        # Check keys page
        kp = await browser.get('https://openrouter.ai/workspaces/default/keys')
        await asyncio.sleep(6)
        kc = await kp.get_content()
        kt = await get_text(kp)
        log.info('Keys page: %s', kt[:150])

        if 'sign-in' not in kc[:500].lower() and 'sign in' not in kt[:100].lower():
            ks = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc)
            if ks:
                save('OPENROUTER_API_KEY', ks[0])
                return True
            # Create key
            await js(kp,
                "var b = Array.from(document.querySelectorAll('button'))"
                ".find(function(b) { return /create|generate|new/i.test(b.textContent) && b.offsetParent; });"
                "if (b) b.click();"
                "return 'clicked';"
            )
            await asyncio.sleep(5)
            kc2 = await kp.get_content()
            ks2 = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc2)
            if ks2:
                save('OPENROUTER_API_KEY', ks2[0])
                return True
    except Exception as e:
        log.error('OpenRouter: %s', e)
    return False


async def main():
    import nodriver as uc
    log.info('Signup v3 starting...')
    browser = await uc.start(
        headless=True,
        browser_executable_path='/usr/bin/google-chrome-stable',
        browser_args=[
            '--no-sandbox', '--disable-dev-shm-usage',
            '--window-size=1280,900',
            '--disable-blink-features=AutomationControlled',
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
    )
    results = {}
    try:
        results['together']    = await together_signin(browser)
        results['perplexity']  = await perplexity_signup(browser)
        results['openrouter']  = await openrouter_signin(browser)
    finally:
        try: browser.stop()
        except: pass

    log.info('=== V3 RESULTS ===')
    for name, ok in results.items():
        log.info('  %s: %s', name, 'OK' if ok else 'FAILED')

    env = dotenv_values(ENV)
    for k in ['TOGETHER_API_KEY', 'PERPLEXITY_API_KEY', 'OPENROUTER_API_KEY']:
        v = env.get(k,'')
        log.info('%s: %s', k, ('SET ' + v[:20]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
