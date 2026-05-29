#!/usr/bin/env python3
"""V4: Targeted fixes based on V3 findings
- OpenRouter: correct password FroggyBot2025!OR + OTP
- Perplexity: click 'Continue with email' before filling email
- Together.ai: /signup URL + dismiss cookies first
"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('signup_v4')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'

def imap_check(kw='', since_min=15):
    try:
        m = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        m.login(GMAIL, GPASS)
        m.select('INBOX')
        since = (datetime.now()-timedelta(minutes=since_min)).strftime('%d-%b-%Y')
        _, d = m.search(None, 'SINCE ' + since)
        ids = d[0].split()[-30:] if d[0] else []
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
                            try: body += p.get_payload(decode=True).decode('utf-8', errors='replace')
                            except: pass
                else:
                    try: body = msg.get_payload(decode=True).decode('utf-8', errors='replace')
                    except: pass
                m.logout()
                return body
        m.logout()
    except Exception as e:
        log.warning('IMAP: %s', e)
    return None

async def wait_email(kw, tries=20, since=15):
    log.info('  Waiting email: %s', kw)
    for i in range(tries):
        await asyncio.sleep(6)
        b = imap_check(kw, since)
        if b: return b
        if (i+1) % 5 == 0:
            log.info('  Still waiting %s %d/%d', kw, i+1, tries)
    return None

async def txt(page):
    c = await page.get_content()
    c = re.sub(r'<style[^>]*>.*?</style>', '', c, flags=re.DOTALL)
    c = re.sub(r'<script[^>]*>.*?</script>', '', c, flags=re.DOTALL)
    c = re.sub(r'<[^>]+>', ' ', c)
    return re.sub(r'\s+', ' ', c).strip()

async def js(page, code):
    try:
        return await page.evaluate("(function() { " + code + " })()")
    except Exception as e:
        log.debug('JS err: %s', e)
        return None

async def fill(page, selector, value):
    v = value.replace("'", "\\'")
    return await js(page,
        "var el = document.querySelector('" + selector + "');"
        "if (!el) return false;"
        "var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');"
        "if (setter && setter.set) setter.set.call(el, '" + v + "');"
        "else el.value = '" + v + "';"
        "el.dispatchEvent(new Event('input', {bubbles:true}));"
        "el.dispatchEvent(new Event('change', {bubbles:true}));"
        "return el.value.length > 0;"
    )

async def click_text(page, patterns):
    pat = '|'.join(patterns)
    return await js(page,
        "var re = new RegExp('" + pat + "', 'i');"
        "var els = Array.from(document.querySelectorAll('button,a,[role=\"button\"]'));"
        "var el = els.find(function(e) { return re.test(e.textContent.trim()) && e.offsetParent; });"
        "if (!el) el = document.querySelector('button[type=\"submit\"]');"
        "if (el) { el.click(); return el.textContent.trim().slice(0,40); }"
        "return null;"
    )

async def dismiss_cookies(page):
    result = await js(page,
        "var btns = Array.from(document.querySelectorAll('button'));"
        "var b = btns.find(function(b) {"
        "  var t = b.textContent.trim().toLowerCase();"
        "  return (t.includes('accept') || t==='ok' || t.includes('agree')) && b.offsetParent;"
        "});"
        "if (b) { b.click(); return b.textContent.trim(); }"
        "return null;"
    )
    if result:
        log.info('  Cookies: %s', result)
        await asyncio.sleep(2)
    return result

async def otp_enter(page, code):
    otp6 = await page.query_selector_all('input[maxlength="1"]')
    otp1 = await page.select('input[maxlength="6"]')
    if len(otp6) >= 6:
        for d, el in zip(code[:6], otp6[:6]):
            await el.mouse_click()
            await el.send_keys(d)
            await asyncio.sleep(0.1)
        log.info('  OTP entered in 6-field form')
    elif otp1:
        await otp1.mouse_click()
        await otp1.send_keys(code)
        log.info('  OTP entered in 1-field form')
    else:
        log.warning('  No OTP fields found!')
        return False
    await asyncio.sleep(1)
    for t in ['Verify', 'Continue', 'Submit', 'Confirm']:
        b = await page.find(t, best_match=True)
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
    log.info('*** SAVED %s = %s... ***', name, value[:25])
    try:
        import httpx
        env = dotenv_values(ENV)
        tok = env.get('TELEGRAM_BOT_TOKEN', '')
        cid = env.get('TELEGRAM_CHAT_ID', '')
        if tok and cid:
            httpx.post(
                f'https://api.telegram.org/bot{tok}/sendMessage',
                json={'chat_id': cid, 'text': f'[SIGNUP] New key: {name} obtained!'},
                timeout=5
            )
    except: pass


# ── OpenRouter: sign-in with correct credentials ─────────────────────────────
async def openrouter(browser):
    log.info('=== OpenRouter ===')
    if dotenv_values(ENV).get('OPENROUTER_API_KEY', ''):
        log.info('Already have key')
        return True
    OR_PASS = 'FroggyBot2025!OR'
    try:
        page = await browser.get('https://openrouter.ai/sign-in')
        await asyncio.sleep(8)

        # Step 1: Fill email identifier
        await fill(page, 'input[name="identifier"]', GMAIL)
        await asyncio.sleep(0.5)
        r1 = await click_text(page, ['continue', 'next', 'sign.?in'])
        log.info('Step1 click: %s', r1)
        await asyncio.sleep(5)

        t1 = await txt(page)
        log.info('After email: %s', t1[:200])

        # Step 2: Password if visible
        pw_filled = await fill(page, 'input[type="password"]', OR_PASS)
        if pw_filled:
            log.info('Password filled')
            r2 = await click_text(page, ['continue', 'sign.?in', 'submit'])
            log.info('Step2 click: %s', r2)
            await asyncio.sleep(6)

        t2 = await txt(page)
        log.info('After pw: %s', t2[:200])

        # Step 3: Check for OTP fields
        otp6 = await page.query_selector_all('input[maxlength="1"]')
        otp1 = await page.select('input[maxlength="6"]')
        log.info('OTP fields: %d single: %s', len(otp6), bool(otp1))

        if len(otp6) >= 1 or otp1:
            body = await wait_email('clerk', 20, 8)
            if not body:
                body = await wait_email('openrouter', 10, 8)
            if body:
                codes = re.findall(r'\b[0-9]{6}\b', body)
                links = re.findall(r'https://[^\s<>"]+(?:verify|confirm|activate)[^\s<>"]*', body, re.I)
                log.info('Codes: %s Links: %d', codes[:2], len(links))
                if codes:
                    if await otp_enter(page, codes[0]):
                        log.info('OTP entered')
                        await asyncio.sleep(6)
                elif links:
                    lp = await browser.get(links[0])
                    await asyncio.sleep(6)

        # Check keys page
        kp = await browser.get('https://openrouter.ai/workspaces/default/keys')
        await asyncio.sleep(6)
        kc = await kp.get_content()
        kt = await txt(kp)
        log.info('Keys page: %s', kt[:150])

        if 'sign in' not in kt[:100].lower() and 'sign-in' not in kc[:500].lower():
            ks = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc)
            if ks:
                save('OPENROUTER_API_KEY', ks[0])
                return True
            # Try creating a key
            r3 = await click_text(kp, ['create', 'generate', 'new key', 'add key'])
            log.info('Create key: %s', r3)
            if r3:
                await asyncio.sleep(5)
                kc2 = await kp.get_content()
                ks2 = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc2)
                if ks2:
                    save('OPENROUTER_API_KEY', ks2[0])
                    return True
        else:
            log.info('Not logged in to OpenRouter')
    except Exception as e:
        log.error('OpenRouter: %s', e)
    return False


# ── Perplexity: click "Continue with email" first ────────────────────────────
async def perplexity(browser):
    log.info('=== Perplexity ===')
    if dotenv_values(ENV).get('PERPLEXITY_API_KEY', ''):
        log.info('Already have key')
        return True
    try:
        # Go directly to API settings - will redirect to sign-in
        page = await browser.get('https://www.perplexity.ai/settings/api')
        await asyncio.sleep(8)
        t = await txt(page)
        log.info('API page: %s', t[:250])

        # Click "Continue with email" (NOT Google/Apple)
        r1 = await js(page,
            "var els = Array.from(document.querySelectorAll('button,a'));"
            "var el = els.find(function(e) {"
            "  var t = e.textContent.trim().toLowerCase();"
            "  return t.includes('email') && e.offsetParent;"
            "});"
            "if (el) { el.click(); return el.textContent.trim(); }"
            "return null;"
        )
        log.info('Continue with email: %s', r1)
        await asyncio.sleep(4)

        t2 = await txt(page)
        log.info('After email btn: %s', t2[:200])

        # Fill email
        filled = False
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
            v = await fill(page, sel, GMAIL)
            if v:
                log.info('Email filled: %s', sel)
                filled = True
                break

        if filled:
            r2 = await click_text(page, ['send.*link', 'continue', 'submit', 'next', 'send'])
            log.info('Submit: %s', r2)
            await asyncio.sleep(10)

            t3 = await txt(page)
            log.info('After submit: %s', t3[:200])

            # Wait for magic link email
            body = await wait_email('perplexity', 20, 10)
            if not body:
                body = await wait_email('', 10, 10)

            if body:
                links = re.findall(r'https://[^\s<>"]+(?:perplexity|verify|magic)[^\s<>"]*', body, re.I)
                codes = re.findall(r'\b[0-9]{6}\b', body)
                log.info('Links: %d, codes: %s', len(links), codes[:2])
                if links:
                    vp = await browser.get(links[0])
                    await asyncio.sleep(10)
                    log.info('Magic link: %s', (await txt(vp))[:150])
                elif codes:
                    await otp_enter(page, codes[0])
                    await asyncio.sleep(6)

        # Check API keys
        kp = await browser.get('https://www.perplexity.ai/settings/api')
        await asyncio.sleep(7)
        kc = await kp.get_content()
        tok = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc)
        if tok:
            save('PERPLEXITY_API_KEY', tok.group())
            return True
        kt = await txt(kp)
        log.info('Keys result: %s', kt[:200])
        # Try create
        r3 = await click_text(kp, ['create', 'generate', 'new', 'add'])
        if r3:
            await asyncio.sleep(5)
            kc2 = await kp.get_content()
            tok2 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc2)
            if tok2:
                save('PERPLEXITY_API_KEY', tok2.group())
                return True
    except Exception as e:
        log.error('Perplexity: %s', e)
    return False


# ── Together.ai: /signup with cookie dismiss ─────────────────────────────────
async def together(browser):
    log.info('=== Together.ai ===')
    TG_PASS = 'FroggyBot2025!TG'
    try:
        page = await browser.get('https://api.together.xyz/signup')
        await asyncio.sleep(12)

        # Dismiss cookies
        for _ in range(3):
            r = await dismiss_cookies(page)
            if r: break
            await asyncio.sleep(2)
        await asyncio.sleep(3)

        t = await txt(page)
        log.info('Signup: %s', t[:200])

        # List all inputs
        inputs_raw = await js(page,
            "return JSON.stringify(Array.from(document.querySelectorAll('input'))"
            ".map(function(i) { return i.type + ':' + (i.name || i.id || i.placeholder).slice(0,20); }));"
        )
        log.info('Inputs: %s', str(inputs_raw)[:200])

        # Look for "Continue with email" first (Auth0 style)
        r1 = await js(page,
            "var els = Array.from(document.querySelectorAll('button,a,[type=\"button\"]'));"
            "var el = els.find(function(e) {"
            "  var t = e.textContent.trim().toLowerCase();"
            "  return t.includes('email') && e.offsetParent;"
            "});"
            "if (el) { el.click(); return el.textContent.trim(); }"
            "return null;"
        )
        log.info('Continue w/email: %s', r1)
        if r1:
            await asyncio.sleep(4)

        # Fill email
        em = False
        for sel in ['input[type="email"]', 'input[name="email"]', '#email', 'input[placeholder*="email" i]']:
            v = await fill(page, sel, GMAIL)
            if v:
                log.info('Email filled: %s', sel)
                em = True
                break

        # Fill password
        if em:
            for sel in ['input[type="password"]', 'input[name="password"]', '#password']:
                v = await fill(page, sel, TG_PASS)
                if v:
                    log.info('Password filled')
                    break

        r2 = await click_text(page, ['sign.?up', 'create.*account', 'continue', 'register', 'next'])
        log.info('Submit: %s', r2)
        await asyncio.sleep(10)

        t2 = await txt(page)
        log.info('After submit: %s', t2[:200])

        # Email verification
        if any(x in t2.lower() for x in ['verif', 'check your email', 'sent', 'confirm']):
            body = await wait_email('together', 15, 8)
            if not body:
                body = await wait_email('', 10, 8)
            if body:
                links = [l for l in re.findall(r'https://\S+', body) if 'together' in l.lower() or 'verif' in l.lower()]
                codes = re.findall(r'\b[0-9]{6}\b', body)
                if links:
                    vp = await browser.get(links[0])
                    await asyncio.sleep(8)
                elif codes:
                    await otp_enter(page, codes[0])
                    await asyncio.sleep(6)

        # Try API keys page
        kp = await browser.get('https://api.together.xyz/settings/api-keys')
        await asyncio.sleep(8)
        kc = await kp.get_content()
        tok = re.search(r'[0-9a-f]{64}', kc)
        if tok:
            save('TOGETHER_API_KEY', tok.group())
            return True
        kt = await txt(kp)
        log.info('Keys page: %s', kt[:150])
    except Exception as e:
        log.error('Together: %s', e)
    return False


async def main():
    import nodriver as uc
    log.info('Signup v4 starting...')
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
        results['openrouter'] = await openrouter(browser)
        results['perplexity'] = await perplexity(browser)
        results['together']   = await together(browser)
    finally:
        try: browser.stop()
        except: pass

    log.info('=== V4 RESULTS ===')
    for name, ok in results.items():
        log.info('  %s: %s', name, 'OK' if ok else 'FAILED')

    env = dotenv_values(ENV)
    for k in ['OPENROUTER_API_KEY', 'PERPLEXITY_API_KEY', 'TOGETHER_API_KEY']:
        v = env.get(k, '')
        log.info('%s: %s', k, ('SET ' + v[:25]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
