#!/usr/bin/env python3
"""V2 signup: improved page interaction, JS-based cookie/form handling"""
import asyncio, sys, os, re, imaplib, email as elib, time, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('signup_v2')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'
PASS  = 'FroggyBot2025!TG'

def imap_latest(kw='', since_min=12):
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

async def wait_email(kw, tries=25, since=12):
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

async def js_eval(page, script):
    try:
        # Wrap in IIFE so top-level `return` statements work in evaluate()
        wrapped = "(function() { " + script + " })()"
        return await page.evaluate(wrapped)
    except Exception as e:
        log.debug('JS eval error: %s', e)
        return None

async def accept_cookies_js(page):
    """Accept cookies via JavaScript evaluation."""
    script = (
        "var btns = Array.from(document.querySelectorAll('button'));"
        "var ab = btns.find(function(b) { return /accept/i.test(b.textContent) && b.offsetParent; });"
        "if (ab) { ab.click(); return 'clicked:' + ab.textContent.trim().slice(0,20); }"
        "var dialogs = document.querySelectorAll('[class*=\"cookie\"],[id*=\"cookie\"],[class*=\"consent\"]');"
        "var found = false;"
        "dialogs.forEach(function(d) {"
        "  d.querySelectorAll('button').forEach(function(b) {"
        "    if (/accept|ok|agree/i.test(b.textContent)) { b.click(); found = true; }"
        "  });"
        "});"
        "return found ? 'dismissed' : 'none';"
    )
    result = await js_eval(page, script)
    if result and result != 'none':
        log.info('  Cookies accepted: %s', result)
        await asyncio.sleep(2)
        return True
    return False

async def js_fill_input(page, selector, value):
    """Fill input field using React-compatible JavaScript."""
    escaped_val = value.replace("'", "\\'").replace('"', '\\"')
    script = (
        "var el = document.querySelector('" + selector + "');"
        "if (!el) return false;"
        "var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');"
        "if (setter && setter.set) { setter.set.call(el, '" + escaped_val + "'); }"
        "else { el.value = '" + escaped_val + "'; }"
        "el.dispatchEvent(new Event('input', {bubbles: true}));"
        "el.dispatchEvent(new Event('change', {bubbles: true}));"
        "return true;"
    )
    return await js_eval(page, script)

async def js_click_submit(page, text_patterns):
    """Click submit button matching text patterns."""
    pattern = '|'.join(text_patterns)
    script = (
        "var btns = Array.from(document.querySelectorAll('button'));"
        "var re = new RegExp('" + pattern + "', 'i');"
        "var sb = btns.find(function(b) { return re.test(b.textContent) && b.offsetParent; });"
        "if (!sb) sb = document.querySelector('button[type=\"submit\"]');"
        "if (sb) { sb.click(); return sb.textContent.trim(); }"
        "return null;"
    )
    return await js_eval(page, script)

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
    for txt in ['Verify', 'Continue', 'Submit', 'Confirm']:
        btn = await page.find(txt, best_match=True)
        if btn:
            try:
                if await btn.get_position():
                    await btn.mouse_click()
                    await asyncio.sleep(4)
                    return True
            except:
                pass
    return False

def save_key(name, value):
    set_key(ENV, name, value)
    log.info('Saved %s: %s...', name, value[:20])
    try:
        import httpx
        env = dotenv_values(ENV)
        tok = env.get('TELEGRAM_BOT_TOKEN', '')
        chat = env.get('TELEGRAM_CHAT_ID', '')
        if tok and chat:
            httpx.post(
                f'https://api.telegram.org/bot{tok}/sendMessage',
                json={'chat_id': chat, 'text': f'New API key: {name}'},
                timeout=8
            )
    except:
        pass

# ── Together.ai ────────────────────────────────────────────────────────────────
async def together_v2(browser):
    log.info('=== Together.ai v2 ===')
    if dotenv_values(ENV).get('TOGETHER_API_KEY', ''):
        log.info('Already have key')
        return True
    try:
        # Signin page has a "Create account" link
        page = await browser.get('https://api.together.xyz/signin')
        await asyncio.sleep(12)
        t = await get_text(page)
        log.info('Signin page: %s', t[:200])

        # Find signup link via JS
        signup_url = await js_eval(page,
            "var links = Array.from(document.querySelectorAll('a'));"
            "var su = links.find(function(l) {"
            "  return /sign.?up|create.?account|register|join/i.test(l.textContent) || /sign-?up|register/i.test(l.href);"
            "});"
            "return su ? su.href : null;"
        )
        log.info('Signup URL found: %s', signup_url)

        if signup_url and 'together' in str(signup_url):
            page2 = await browser.get(signup_url)
        else:
            page2 = await browser.get('https://api.together.xyz/signup')
        await asyncio.sleep(12)

        inputs_info = await js_eval(page2,
            "return Array.from(document.querySelectorAll('input'))"
            ".map(function(i) { return {type: i.type, name: i.name, id: i.id}; });"
        )
        log.info('Page inputs: %s', inputs_info[:6])

        await js_fill_input(page2, 'input[type="email"]', GMAIL)
        await asyncio.sleep(0.5)
        await js_fill_input(page2, 'input[type="password"]', PASS)
        await asyncio.sleep(0.5)

        result = await js_click_submit(page2, ['sign.?up', 'create', 'continue', 'register', 'get.?started'])
        log.info('Submit clicked: %s', result)
        await asyncio.sleep(10)

        t3 = await get_text(page2)
        log.info('After submit: %s', t3[:200])

        if any(x in t3.lower() for x in ['verif', 'confirm', 'check your email', 'sent']):
            body = await wait_email('together', 20, 8)
            if body:
                codes = re.findall(r'\b[0-9]{6}\b', body)
                links = [l for l in re.findall(r'https://\S+', body) if 'together' in l.lower()]
                if links:
                    vp = await browser.get(links[0])
                    await asyncio.sleep(8)
                elif codes:
                    await enter_otp(page2, codes[0])
                    await asyncio.sleep(5)

        kp = await browser.get('https://api.together.xyz/settings/api-keys')
        await asyncio.sleep(7)
        kc = await kp.get_content()
        tok = re.search(r'[0-9a-f]{64}', kc)
        if tok:
            save_key('TOGETHER_API_KEY', tok.group())
            return True
    except Exception as e:
        log.error('Together v2: %s', e)
    return False

# ── Cerebras v2 ────────────────────────────────────────────────────────────────
async def cerebras_v2(browser):
    log.info('=== Cerebras v2 ===')
    if dotenv_values(ENV).get('CEREBRAS_API_KEY', ''):
        log.info('Already have key')
        return True
    try:
        page = await browser.get('https://cloud.cerebras.ai/')
        await asyncio.sleep(10)

        # Accept cookies via JS (multiple attempts)
        for attempt in range(5):
            result = await accept_cookies_js(page)
            if result:
                break
            await asyncio.sleep(2)

        await asyncio.sleep(5)  # Wait for cookie modal to fully disappear

        t = await get_text(page)
        log.info('After cookies: %s', t[:200])

        # Get list of all visible inputs
        inputs = await js_eval(page,
            "return Array.from(document.querySelectorAll('input'))"
            ".filter(function(i) { return i.offsetParent !== null; })"
            ".map(function(i) { return {type: i.type, name: i.name, placeholder: i.placeholder, id: i.id}; });"
        )
        log.info('Visible inputs: %s', inputs[:5])

        # Fill email (try multiple selectors)
        email_filled = False
        for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
            if await js_fill_input(page, sel, GMAIL):
                log.info('Email filled via: %s', sel)
                email_filled = True
                break

        if not email_filled:
            # Click "Sign up" / "Get started" first
            clicked = await js_eval(page,
                "var links = Array.from(document.querySelectorAll('a,button'));"
                "var su = links.find(function(l) {"
                "  return /sign.?up|get.?started|try.?free|register/i.test(l.textContent) && l.offsetParent;"
                "});"
                "if (su) { su.click(); return su.textContent.trim(); }"
                "return null;"
            )
            log.info('Clicked nav link: %s', clicked)
            await asyncio.sleep(5)
            # Try email again
            for sel in ['input[type="email"]', 'input[name="email"]']:
                if await js_fill_input(page, sel, GMAIL):
                    log.info('Email filled after nav click')
                    email_filled = True
                    break

        if email_filled:
            result = await js_click_submit(page, ['continue.with.email', 'continue', 'sign.?up', 'submit', 'send'])
            log.info('Submit: %s', result)
            await asyncio.sleep(12)

            body = await wait_email('cerebras', 20, 10)
            if not body:
                body = await wait_email('okta', 15, 10)
            if body:
                links = re.findall(r'https://[^\s<>"]+(?:cerebras|okta|cloud)[^\s<>"]*', body, re.I)
                codes = re.findall(r'\b[0-9]{6}\b', body)
                log.info('Links: %d Codes: %s', len(links), codes[:2])
                if links:
                    ml = await browser.get(links[0])
                    await asyncio.sleep(9)
                    log.info('Magic link: %s', (await get_text(ml))[:150])
                elif codes:
                    await enter_otp(page, codes[0])
                    await asyncio.sleep(6)

        kp = await browser.get('https://cloud.cerebras.ai/platform/api-keys')
        await asyncio.sleep(6)
        await accept_cookies_js(kp)
        await asyncio.sleep(2)
        kc = await kp.get_content()
        ks = re.findall(r'cbsk-[a-zA-Z0-9_-]{20,}', kc)
        if ks:
            save_key('CEREBRAS_API_KEY', ks[0])
            return True

        await js_eval(kp,
            "var btns = Array.from(document.querySelectorAll('button'));"
            "var cb = btns.find(function(b) { return /create|generate|new/i.test(b.textContent) && b.offsetParent; });"
            "if (cb) cb.click();"
        )
        await asyncio.sleep(5)
        kc2 = await kp.get_content()
        ks2 = re.findall(r'cbsk-[a-zA-Z0-9_-]{20,}', kc2)
        if ks2:
            save_key('CEREBRAS_API_KEY', ks2[0])
            return True

    except Exception as e:
        log.error('Cerebras v2: %s', e)
    return False

# ── HuggingFace v2 ─────────────────────────────────────────────────────────────
async def hf_v2(browser):
    log.info('=== HuggingFace v2 ===')
    if dotenv_values(ENV).get('HF_API_KEY', ''):
        log.info('Already have key')
        return True
    try:
        page = await browser.get('https://huggingface.co/join')
        await asyncio.sleep(9)
        t = await get_text(page)
        log.info('HF join: %s', t[:200])

        # Get form inputs
        inputs = await js_eval(page,
            "return Array.from(document.querySelectorAll('input'))"
            ".filter(function(i) { return i.offsetParent !== null; })"
            ".map(function(i) { return {type: i.type, name: i.name, id: i.id}; });"
        )
        log.info('HF inputs: %s', inputs[:6])

        await js_fill_input(page, 'input[name="username"],#username', 'froggyai2025')
        await js_fill_input(page, 'input[name="email"],input[type="email"]', GMAIL)
        await js_fill_input(page, 'input[name="password"],input[type="password"]', PASS)

        await asyncio.sleep(1)
        result = await js_click_submit(page, ['create account', 'register', 'sign up', 'join'])
        if not result:
            result = await js_eval(page,
                "var f = document.querySelector('form');"
                "if (f) { f.requestSubmit(); return 'form submit'; }"
                "return null;"
            )
        log.info('HF submit: %s', result)
        await asyncio.sleep(10)

        t2 = await get_text(page)
        log.info('After submit: %s', t2[:200])

        if any(x in t2.lower() for x in ['verif', 'confirm', 'email', 'sent']):
            body = await wait_email('huggingface', 20, 8)
            if body:
                links = re.findall(r'https://[^\s<>"]+huggingface[^\s<>"]*', body, re.I)
                if links:
                    vp = await browser.get(links[0])
                    await asyncio.sleep(8)
                    log.info('Verified: %s', (await get_text(vp))[:100])

        tp = await browser.get('https://huggingface.co/settings/tokens')
        await asyncio.sleep(7)
        tc = await tp.get_content()
        tok = re.search(r'hf_[a-zA-Z0-9]{30,}', tc)
        if tok:
            save_key('HF_API_KEY', tok.group())
            return True

        # Create new token
        await js_eval(tp,
            "var btns = Array.from(document.querySelectorAll('button'));"
            "var nb = btns.find(function(b) { return /new|create|generate|add/i.test(b.textContent) && b.offsetParent; });"
            "if (nb) nb.click();"
        )
        await asyncio.sleep(5)
        tc2 = await tp.get_content()
        tok2 = re.search(r'hf_[a-zA-Z0-9]{30,}', tc2)
        if tok2:
            save_key('HF_API_KEY', tok2.group())
            return True

    except Exception as e:
        log.error('HF v2: %s', e)
    return False

async def main():
    import nodriver as uc
    log.info('Signup v2 starting...')
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
        results['together']    = await together_v2(browser)
        results['cerebras']    = await cerebras_v2(browser)
        results['huggingface'] = await hf_v2(browser)
    finally:
        try:
            browser.stop()
        except:
            pass

    log.info('=== V2 RESULTS ===')
    env = dotenv_values(ENV)
    for name, ok in results.items():
        log.info('  %s: %s', name, 'OK' if ok else 'FAILED')

    summary = []
    for k in ['TOGETHER_API_KEY', 'CEREBRAS_API_KEY', 'HF_API_KEY']:
        v = env.get(k, '')
        summary.append(f"{'OK' if v else 'FAIL'}: {k.split('_')[0]}")
    log.info('Summary: %s', ' | '.join(summary))

if __name__ == '__main__':
    asyncio.run(main())
