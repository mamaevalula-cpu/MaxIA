#!/usr/bin/env python3
"""V4b: Timing fixes for OpenRouter + Perplexity email submit precision"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('signup_v4b')

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
    log.info('  Waiting email: [%s]', kw)
    for i in range(tries):
        await asyncio.sleep(6)
        b = imap_check(kw, since)
        if b: return b
        if (i+1) % 5 == 0:
            log.info('  Still waiting [%s] %d/%d', kw, i+1, tries)
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

async def wait_for_element(page, selector, timeout=15):
    """Poll until element appears or timeout."""
    for _ in range(timeout):
        el = await js(page, "return !!document.querySelector('" + selector + "');")
        if el:
            return True
        await asyncio.sleep(1)
    return False

async def otp_enter(page, code):
    otp6 = await page.query_selector_all('input[maxlength="1"]')
    otp1 = await page.select('input[maxlength="6"]')
    if len(otp6) >= 6:
        for d, el in zip(code[:6], otp6[:6]):
            await el.mouse_click(); await el.send_keys(d)
            await asyncio.sleep(0.1)
        log.info('  OTP 6-field entered')
    elif otp1:
        await otp1.mouse_click(); await otp1.send_keys(code)
        log.info('  OTP 1-field entered')
    else:
        return False
    await asyncio.sleep(1)
    for t in ['Verify', 'Continue', 'Submit', 'Confirm']:
        b = await page.find(t, best_match=True)
        if b:
            try:
                if await b.get_position():
                    await b.mouse_click()
                    await asyncio.sleep(5)
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
                json={'chat_id': cid, 'text': f'[SIGNUP] Key obtained: {name}'},
                timeout=5
            )
    except: pass


# ── OpenRouter: careful step-by-step Clerk flow ─────────────────────────────
async def openrouter(browser):
    log.info('=== OpenRouter ===')
    if dotenv_values(ENV).get('OPENROUTER_API_KEY', ''):
        log.info('Already have key')
        return True
    OR_PASS = 'FroggyBot2025!OR'

    async def try_get_key(page, kp_url):
        kp = await browser.get(kp_url)
        await asyncio.sleep(6)
        kc = await kp.get_content()
        ks = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc)
        if ks:
            save('OPENROUTER_API_KEY', ks[0])
            return True
        # Try create
        r = await js(kp,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return /create|generate|new/i.test(b.textContent) && b.offsetParent; });"
            "if (b) { b.click(); return b.textContent.trim(); } return null;"
        )
        if r:
            await asyncio.sleep(5)
            kc2 = await kp.get_content()
            ks2 = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc2)
            if ks2:
                save('OPENROUTER_API_KEY', ks2[0])
                return True
        return False

    try:
        page = await browser.get('https://openrouter.ai/sign-in')
        await asyncio.sleep(8)

        # Step 1: Enter email
        ei = 'input[name="identifier"]'
        if not await fill(page, ei, GMAIL):
            ei = 'input[type="email"]'
            await fill(page, ei, GMAIL)
        log.info('Email entered')
        await asyncio.sleep(0.5)

        # Click Continue (step 1)
        r1 = await js(page,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) {"
            "  var t = b.textContent.trim().toLowerCase();"
            "  return t === 'continue' && b.offsetParent;"
            "});"
            "if (!b) b = document.querySelector('form button[type=\"submit\"]');"
            "if (b) { b.click(); return b.textContent.trim(); } return null;"
        )
        log.info('Step1 click: %s', r1)

        # Wait for page to update (password field or OTP or "Check email")
        await asyncio.sleep(4)

        # Check what appeared
        t1 = await txt(page)
        log.info('After step1: %s', t1[:250])

        pw_appeared = await wait_for_element(page, 'input[type="password"]', 8)
        otp_appeared = len(await page.query_selector_all('input[maxlength="1"]')) >= 1

        if pw_appeared:
            # Password step
            log.info('Password field appeared')
            await fill(page, 'input[type="password"]', OR_PASS)
            await asyncio.sleep(0.5)
            r2 = await js(page,
                "var b = Array.from(document.querySelectorAll('button'))"
                ".find(function(b) {"
                "  var t = b.textContent.trim().toLowerCase();"
                "  return t === 'continue' && b.offsetParent;"
                "});"
                "if (!b) b = document.querySelector('form button[type=\"submit\"]');"
                "if (b) { b.click(); return b.textContent.trim(); } return null;"
            )
            log.info('Step2 click: %s', r2)
            await asyncio.sleep(8)

            t2 = await txt(page)
            log.info('After pw: %s', t2[:200])

            # Check for OTP after password
            otp_f = await page.query_selector_all('input[maxlength="1"]')
            if len(otp_f) >= 1:
                otp_appeared = True

        if otp_appeared:
            log.info('OTP form found')
            body = await wait_email('clerk', 20, 8)
            if not body:
                body = await wait_email('openrouter', 10, 8)
            if body:
                codes = re.findall(r'\b[0-9]{6}\b', body)
                links = re.findall(r'https://[^\s<>"]+(?:verify|confirm|activate)[^\s<>"]*', body, re.I)
                log.info('Codes: %s, Links: %d', codes[:2], len(links))
                if codes:
                    await otp_enter(page, codes[0])
                elif links:
                    lp = await browser.get(links[0])
                    await asyncio.sleep(6)
            else:
                log.warning('No OTP email received')

        # Check if logged in
        result = await try_get_key(page, 'https://openrouter.ai/workspaces/default/keys')
        if result:
            return True

        # If not logged in, try sign UP instead
        log.info('Sign-in failed, trying sign-up...')
        sp = await browser.get('https://openrouter.ai/sign-up')
        await asyncio.sleep(8)
        st = await txt(sp)
        log.info('Sign-up page: %s', st[:200])

        await fill(sp, 'input[name="emailAddress"]', GMAIL)
        await asyncio.sleep(0.3)
        await fill(sp, 'input[type="password"]', OR_PASS)
        await asyncio.sleep(0.3)

        # Check Terms checkbox
        await js(sp,
            "var cb = document.querySelector('input[type=\"checkbox\"]');"
            "if (cb && !cb.checked) cb.click();"
            "return !!cb;"
        )

        r3 = await js(sp,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) {"
            "  var t = b.textContent.trim().toLowerCase();"
            "  return (t === 'continue' || t.includes('sign up') || t.includes('create')) && b.offsetParent;"
            "});"
            "if (b) { b.click(); return b.textContent.trim(); } return null;"
        )
        log.info('Sign-up submit: %s', r3)
        await asyncio.sleep(10)

        st2 = await txt(sp)
        log.info('After sign-up: %s', st2[:250])

        # Look for OTP or email verification
        otp_su = await sp.query_selector_all('input[maxlength="1"]')
        if len(otp_su) >= 1:
            log.info('OTP on sign-up')
            body2 = await wait_email('clerk', 20, 8)
            if not body2:
                body2 = await wait_email('openrouter', 10, 8)
            if body2:
                codes2 = re.findall(r'\b[0-9]{6}\b', body2)
                if codes2:
                    await otp_enter(sp, codes2[0])

        return await try_get_key(sp, 'https://openrouter.ai/workspaces/default/keys')

    except Exception as e:
        log.error('OpenRouter: %s', e)
    return False


# ── Perplexity: email-specific submit after "Continue with email" ─────────────
async def perplexity(browser):
    log.info('=== Perplexity ===')
    if dotenv_values(ENV).get('PERPLEXITY_API_KEY', ''):
        log.info('Already have key')
        return True
    try:
        page = await browser.get('https://www.perplexity.ai/settings/api')
        await asyncio.sleep(8)
        t = await txt(page)
        log.info('API page: %s', t[:200])

        # Click "Continue with email" specifically (not Google/Apple)
        r1 = await js(page,
            "var els = Array.from(document.querySelectorAll('button,a'));"
            "var el = els.find(function(e) {"
            "  var t = e.textContent.trim().toLowerCase();"
            "  return t.includes('with email') && e.offsetParent;"
            "});"
            "if (el) { el.click(); return el.textContent.trim(); }"
            "return null;"
        )
        log.info('Continue with email: %s', r1)
        if not r1:
            log.warning('No "with email" button found')
            return False
        await asyncio.sleep(4)

        t2 = await txt(page)
        log.info('After email btn: %s', t2[:200])

        # Fill email
        filled = await fill(page, 'input[type="email"]', GMAIL)
        if not filled:
            filled = await fill(page, 'input[name="email"]', GMAIL)
        if not filled:
            log.warning('Email input not found after Continue with email click')
            return False
        log.info('Email filled')
        await asyncio.sleep(0.5)

        # Click the submit button that is NOT "Continue with Google/Apple/SSO"
        # The magic link submit should be labeled something like "Continue" but is the FIRST/ONLY button in the email form
        r2 = await js(page,
            "var form = document.querySelector('form');"
            "if (form) {"
            "  var submitBtns = Array.from(form.querySelectorAll('button'));"
            "  var sb = submitBtns.find(function(b) { return b.offsetParent; });"
            "  if (sb) { sb.click(); return 'form-submit:' + sb.textContent.trim().slice(0,30); }"
            "}"
            "var btns = Array.from(document.querySelectorAll('button'));"
            "var sb2 = btns.find(function(b) {"
            "  var t = b.textContent.trim().toLowerCase();"
            "  return (t.includes('continue') || t.includes('send') || t.includes('submit') || t === 'next')"
            "  && !t.includes('google') && !t.includes('apple') && !t.includes('sso') && b.offsetParent;"
            "});"
            "if (sb2) { sb2.click(); return 'btn:' + sb2.textContent.trim().slice(0,30); }"
            "return null;"
        )
        log.info('Email submit: %s', r2)
        await asyncio.sleep(10)

        t3 = await txt(page)
        log.info('After submit: %s', t3[:200])

        # Wait for magic link
        body = await wait_email('perplexity', 20, 10)
        if not body:
            # Try with no keyword (catch any email)
            body = await wait_email('magic', 10, 10)

        if body:
            links = re.findall(r'https://[^\s<>"]+(?:perplexity|verify|magic|auth)[^\s<>"]*', body, re.I)
            codes = re.findall(r'\b[0-9]{6}\b', body)
            log.info('Links: %d codes: %s', len(links), codes[:2])
            if links:
                vp = await browser.get(links[0])
                await asyncio.sleep(10)
                log.info('Magic link page: %s', (await txt(vp))[:150])
            elif codes:
                await otp_enter(page, codes[0])
                await asyncio.sleep(6)
        else:
            log.warning('No email received for Perplexity')

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
        # Create key
        r3 = await js(kp,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return /create|generate|new|add/i.test(b.textContent) && b.offsetParent; });"
            "if (b) { b.click(); return b.textContent.trim(); } return null;"
        )
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


async def main():
    import nodriver as uc
    log.info('Signup v4b starting...')
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
    finally:
        try: browser.stop()
        except: pass

    log.info('=== V4b RESULTS ===')
    for name, ok in results.items():
        log.info('  %s: %s', name, 'OK' if ok else 'FAILED')

    env = dotenv_values(ENV)
    for k in ['OPENROUTER_API_KEY', 'PERPLEXITY_API_KEY']:
        v = env.get(k, '')
        log.info('%s: %s', k, ('SET ' + v[:25]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
