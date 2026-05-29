#!/usr/bin/env python3
"""OpenRouter: password reset flow (account exists with unknown password)"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('or_reset')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'
NEW_PASS = 'FroggyBot2025!OR'

def imap_get(kw='', since_min=15):
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
    for i in range(tries):
        await asyncio.sleep(6)
        b = imap_get(kw, since)
        if b: return b
        if (i+1) % 5 == 0:
            log.info('  waiting [%s] %d/%d', kw, i+1, tries)
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
    if len(otp6) >= 6:
        for d, el in zip(code[:6], otp6[:6]):
            await el.mouse_click(); await el.send_keys(d)
            await asyncio.sleep(0.1)
        log.info('OTP 6-field entered')
        return True
    otp1 = await page.select('input[maxlength="6"]')
    if otp1:
        await otp1.mouse_click(); await otp1.send_keys(code)
        log.info('OTP 1-field entered')
        return True
    return False

async def get_keys(browser):
    kp = await browser.get('https://openrouter.ai/workspaces/default/keys')
    await asyncio.sleep(6)
    kc = await kp.get_content()
    kt = await txt(kp)
    ks = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc)
    if ks:
        set_key(ENV, 'OPENROUTER_API_KEY', ks[0])
        log.info('*** KEY FOUND: %s ***', ks[0][:25])
        return True
    log.info('Keys page: %s', kt[:150])
    # Create key
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
    return False


async def main():
    import nodriver as uc
    log.info('OpenRouter password reset flow')
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
        page = await browser.get('https://openrouter.ai/sign-in')
        await asyncio.sleep(8)
        t = await txt(page)
        log.info('Sign-in page: %s', t[:200])

        # Fill email
        await fill(page, 'input[name="identifier"]', GMAIL)
        await asyncio.sleep(0.5)

        # Click Continue
        r1 = await js(page,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return b.textContent.trim() === 'Continue' && b.offsetParent; });"
            "if (b) { b.click(); return 'clicked'; } return null;"
        )
        log.info('Continue: %s', r1)
        await asyncio.sleep(5)

        t2 = await txt(page)
        log.info('After email: %s', t2[:250])

        # Look for "Forgot password" link
        r_forgot = await js(page,
            "var el = Array.from(document.querySelectorAll('a,button'))"
            ".find(function(e) { return /forgot|reset/i.test(e.textContent) && e.offsetParent; });"
            "if (el) { el.click(); return el.textContent.trim(); } return null;"
        )
        log.info('Forgot pw: %s', r_forgot)
        await asyncio.sleep(5)

        t3 = await txt(page)
        log.info('Forgot page: %s', t3[:200])

        # Fill email on reset form
        await fill(page, 'input[name="identifier"]', GMAIL)
        await fill(page, 'input[type="email"]', GMAIL)
        await asyncio.sleep(0.5)

        r3 = await js(page,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) {"
            "  var t = b.textContent.trim().toLowerCase();"
            "  return (t.includes('send') || t.includes('reset') || t.includes('continue')) && b.offsetParent;"
            "});"
            "if (!b) b = document.querySelector('button[type=\"submit\"]');"
            "if (b) { b.click(); return b.textContent.trim(); } return null;"
        )
        log.info('Reset submit: %s', r3)
        await asyncio.sleep(10)

        t4 = await txt(page)
        log.info('After reset: %s', t4[:200])

        # Wait for password reset email
        body = await wait_email('clerk', 20, 10)
        if not body:
            body = await wait_email('openrouter', 15, 10)
        if not body:
            log.error('No reset email')

            # Try OTP login instead (some Clerk configs allow OTP instead of password)
            log.info('Trying OTP sign-in...')
            si = await browser.get('https://openrouter.ai/sign-in')
            await asyncio.sleep(8)
            await fill(si, 'input[name="identifier"]', GMAIL)
            await asyncio.sleep(0.5)
            r_cnt = await js(si,
                "var b = Array.from(document.querySelectorAll('button'))"
                ".find(function(b) { return b.textContent.trim() === 'Continue' && b.offsetParent; });"
                "if (b) { b.click(); return 'ok'; } return null;"
            )
            await asyncio.sleep(5)
            # Look for "Use email code" option
            r_otp = await js(si,
                "var el = Array.from(document.querySelectorAll('a,button'))"
                ".find(function(e) { return /email.?code|one.?time|magic/i.test(e.textContent) && e.offsetParent; });"
                "if (el) { el.click(); return el.textContent.trim(); } return null;"
            )
            log.info('OTP option: %s', r_otp)
            if r_otp:
                await asyncio.sleep(5)
                body2 = await wait_email('clerk', 20, 10)
                if body2:
                    codes = re.findall(r'\b[0-9]{6}\b', body2)
                    if codes:
                        otp6 = await si.query_selector_all('input[maxlength="1"]')
                        if len(otp6) >= 1:
                            await otp_enter(si, codes[0])
                            await asyncio.sleep(6)
                            return await get_keys(browser)
            return False

        if body:
            # Follow reset link
            links = re.findall(r'https://[^\s<>"]+(?:reset|password)[^\s<>"]*', body, re.I)
            codes = re.findall(r'\b[0-9]{6}\b', body)
            log.info('Reset links: %d codes: %s', len(links), codes[:2])

            if links:
                rp = await browser.get(links[0])
                await asyncio.sleep(8)
                t_reset = await txt(rp)
                log.info('Reset page: %s', t_reset[:200])

                # Set new password
                await fill(rp, 'input[name="password"]', NEW_PASS)
                await fill(rp, 'input[name="confirmPassword"]', NEW_PASS)

                r_save = await js(rp,
                    "var b = Array.from(document.querySelectorAll('button'))"
                    ".find(function(b) {"
                    "  var t = b.textContent.trim().toLowerCase();"
                    "  return (t.includes('reset') || t.includes('save') || t.includes('continue')) && b.offsetParent;"
                    "});"
                    "if (b) { b.click(); return b.textContent.trim(); } return null;"
                )
                log.info('Save pw: %s', r_save)
                await asyncio.sleep(8)
                t_after = await txt(rp)
                log.info('After reset: %s', t_after[:200])

            elif codes:
                # OTP-based reset
                otp6 = await page.query_selector_all('input[maxlength="1"]')
                if otp6:
                    await otp_enter(page, codes[0])
                    await asyncio.sleep(5)
                    await fill(page, 'input[name="password"]', NEW_PASS)
                    await fill(page, 'input[name="confirmPassword"]', NEW_PASS)
                    r_s = await js(page,
                        "var b = Array.from(document.querySelectorAll('button[type=\"submit\"]')).find(function(b){return b.offsetParent;});"
                        "if (b) { b.click(); return b.textContent.trim(); } return null;"
                    )
                    log.info('Save after OTP: %s', r_s)
                    await asyncio.sleep(8)

            return await get_keys(browser)

    finally:
        try: browser.stop()
        except: pass

    v = dotenv_values(ENV).get('OPENROUTER_API_KEY', '')
    log.info('OPENROUTER_API_KEY: %s', ('SET ' + v[:25]) if v else 'EMPTY')
    return bool(v)

if __name__ == '__main__':
    asyncio.run(main())
