#!/usr/bin/env python3
"""OpenRouter: signup with careful OTP detection + second email attempt"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('or_signup2')

ENV   = '/root/my_personal_ai/.env'
GMAIL  = 'froggyinternet@gmail.com'
GMAIL2 = 'jimmorrisoninlove@gmail.com'
GPASS  = 'umtp ewnj biih wfbp'
GPASS2 = 'Fukcyoubithc48'  # Email password, not app password
OR_PASS = 'FroggyBot2025!OR2'

def imap_get(email_addr, password, kw='', since_min=15):
    try:
        m = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        m.login(email_addr, password)
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
        log.warning('IMAP %s: %s', email_addr[:15], e)
    return None

async def wait_email(email_addr, password, kw, tries=20, since=15):
    for i in range(tries):
        await asyncio.sleep(6)
        b = imap_get(email_addr, password, kw, since)
        if b: return b
        if (i+1) % 5 == 0:
            log.info('  wait [%s] %d/%d', kw, i+1, tries)
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
    except: return None

async def fill(page, sel, val):
    v = val.replace("'", "\\'")
    return await js(page,
        "var el = document.querySelector('" + sel + "');"
        "if (!el) return false;"
        "var s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value');"
        "if (s&&s.set) s.set.call(el,'" + v + "'); else el.value='" + v + "';"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        "return el.value.length>0;"
    )

async def otp_enter(page, code):
    otp6 = await page.query_selector_all('input[maxlength="1"]')
    if len(otp6) >= 1:
        for d, el in zip(code[:len(otp6)], otp6[:6]):
            await el.mouse_click(); await el.send_keys(d)
            await asyncio.sleep(0.1)
        return True
    otp1 = await page.select('input[maxlength="6"]')
    if otp1:
        await otp1.mouse_click(); await otp1.send_keys(code)
        return True
    return False

async def try_get_key(browser):
    kp = await browser.get('https://openrouter.ai/workspaces/default/keys')
    await asyncio.sleep(6)
    kc = await kp.get_content()
    ks = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc)
    if ks:
        set_key(ENV, 'OPENROUTER_API_KEY', ks[0])
        log.info('*** KEY FOUND: %s ***', ks[0][:25])
        return True
    kt = await txt(kp)
    if 'sign in' not in kt[:100].lower():
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
                set_key(ENV, 'OPENROUTER_API_KEY', ks2[0])
                log.info('*** KEY CREATED: %s ***', ks2[0][:25])
                return True
    log.info('Keys page (not logged in): %s', kt[:100])
    return False

async def signup_flow(browser, email, password, app_pass):
    """Try signup for OpenRouter. Returns True if logged in."""
    page = await browser.get('https://openrouter.ai/sign-up')
    await asyncio.sleep(8)
    t = await txt(page)
    log.info('Signup page [%s]: %s', email[:15], t[:200])

    # Fill email
    await fill(page, 'input[name="emailAddress"]', email)
    await asyncio.sleep(0.3)

    # Fill password
    await fill(page, 'input[type="password"]', password)
    await asyncio.sleep(0.3)

    # Accept terms if checkbox present
    await js(page,
        "var cb = document.querySelector('input[type=\"checkbox\"]');"
        "if (cb && !cb.checked) cb.click();"
        "return !!cb;"
    )

    # Submit
    r1 = await js(page,
        "var b = Array.from(document.querySelectorAll('button'))"
        ".find(function(b) {"
        "  var t = b.textContent.trim().toLowerCase();"
        "  return (t === 'continue' || t === 'sign up' || t.includes('create')) && b.offsetParent;"
        "});"
        "if (b) { b.click(); return b.textContent.trim(); } return null;"
    )
    log.info('Submit: %s', r1)
    await asyncio.sleep(10)

    t2 = await txt(page)
    log.info('After submit: %s', t2[:300])

    # Log all visible elements for debugging
    all_els = await js(page,
        "return JSON.stringify(Array.from(document.querySelectorAll('input[maxlength],input[type]'))"
        ".map(function(e) { return e.type + ':' + (e.maxLength || '') + ':' + (e.name || '') + ':' + (e.placeholder || '').slice(0,20); }));"
    )
    log.info('Inputs on page: %s', str(all_els)[:400])

    # Wait for OTP or verify email
    otp6 = await page.query_selector_all('input[maxlength="1"]')
    otp1 = await page.select('input[maxlength="6"]')
    has_otp = len(otp6) >= 1 or bool(otp1)
    log.info('OTP fields: %d+1=%s', len(otp6), bool(otp1))

    if has_otp:
        # Check Gmail for OTP
        body = await wait_email(email, app_pass, 'clerk', 25, 10)
        if not body:
            body = await wait_email(email, app_pass, 'openrouter', 10, 10)
        if body:
            codes = re.findall(r'\b[0-9]{6}\b', body)
            log.info('OTP codes: %s', codes[:2])
            if codes:
                if await otp_enter(page, codes[0]):
                    await asyncio.sleep(6)
                    # Click Verify/Continue
                    await js(page,
                        "var b = Array.from(document.querySelectorAll('button'))"
                        ".find(function(b) { return b.offsetParent && b.type !== 'reset'; });"
                        "if (b) b.click();"
                    )
                    await asyncio.sleep(6)
                    return True
        else:
            log.warning('No OTP email')
    elif 'already' in t2.lower() or 'exist' in t2.lower():
        log.info('Account exists, checking sign-in...')
        # Try sign-in
        si = await browser.get('https://openrouter.ai/sign-in')
        await asyncio.sleep(8)
        await fill(si, 'input[name="identifier"]', email)
        await asyncio.sleep(0.5)
        await js(si,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return b.textContent.trim() === 'Continue'; });"
            "if (b) b.click();"
        )
        await asyncio.sleep(5)
        await fill(si, 'input[type="password"]', password)
        await asyncio.sleep(0.5)
        await js(si,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return b.textContent.trim() === 'Continue'; });"
            "if (b) b.click();"
        )
        await asyncio.sleep(8)
        return True  # Try getting keys anyway

    return False


async def main():
    import nodriver as uc
    log.info('OpenRouter signup v2 (dual email)')
    browser = await uc.start(
        headless=True,
        browser_executable_path='/usr/bin/google-chrome-stable',
        browser_args=[
            '--no-sandbox', '--disable-dev-shm-usage', '--window-size=1280,900',
            '--disable-blink-features=AutomationControlled',
            '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
    )
    try:
        # Try primary email first
        log.info('-- Attempt 1: primary email --')
        ok = await signup_flow(browser, GMAIL, OR_PASS, GPASS)
        if ok and await try_get_key(browser):
            return

        # Try second email (may not have app password but let's try)
        log.info('-- Attempt 2: second email --')
        ok2 = await signup_flow(browser, GMAIL2, OR_PASS, GPASS2)
        if ok2 and await try_get_key(browser):
            return

    finally:
        try: browser.stop()
        except: pass

    v = dotenv_values(ENV).get('OPENROUTER_API_KEY', '')
    log.info('OPENROUTER_API_KEY: %s', ('SET ' + v[:25]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
