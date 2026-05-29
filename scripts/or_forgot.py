#!/usr/bin/env python3
"""OpenRouter: step-by-step forgot password with proper timing"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('or_forgot')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'
NEW_PASS = 'FroggyBot2025!OR2'

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

async def wait_el(page, sel, t=15):
    for _ in range(t):
        r = await js(page, "return !!document.querySelector('" + sel + "');")
        if r: return True
        await asyncio.sleep(1)
    return False

async def get_keys(browser):
    kp = await browser.get('https://openrouter.ai/workspaces/default/keys')
    await asyncio.sleep(6)
    kc = await kp.get_content()
    ks = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc)
    if ks:
        set_key(ENV, 'OPENROUTER_API_KEY', ks[0])
        log.info('*** KEY: %s ***', ks[0][:25])
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
            set_key(ENV, 'OPENROUTER_API_KEY', ks2[0])
            log.info('*** KEY CREATED: %s ***', ks2[0][:25])
            return True
    kt = await txt(kp)
    log.info('Keys page: %s', kt[:150])
    return False


async def main():
    import nodriver as uc
    log.info('OpenRouter forgot password')
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

        # Step 1: Enter email + Continue
        await fill(page, 'input[name="identifier"]', GMAIL)
        await asyncio.sleep(0.5)

        r1 = await js(page,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return b.textContent.trim() === 'Continue' && b.offsetParent; });"
            "if (b) { b.click(); return 'ok'; } return null;"
        )
        log.info('Continue: %s', r1)

        # Wait specifically for password field to appear
        pw_appeared = await wait_el(page, 'input[type="password"]', 10)
        log.info('Password appeared: %s', pw_appeared)

        if pw_appeared:
            t2 = await txt(page)
            log.info('Password step: %s', t2[:300])

            # Log ALL links visible
            all_links = await js(page,
                "return JSON.stringify(Array.from(document.querySelectorAll('a,button'))"
                ".filter(function(e) { return e.offsetParent; })"
                ".map(function(e) { return e.tagName + ':' + e.textContent.trim().slice(0,30); }));"
            )
            log.info('All visible els: %s', str(all_links)[:600])

            # Click "Forgot password?" - try both a and button
            r_forgot = await js(page,
                "var all = Array.from(document.querySelectorAll('a,button,span,[role=\"link\"]'));"
                "var el = all.find(function(e) { return /forgot|reset.*pass/i.test(e.textContent) && e.offsetParent; });"
                "if (el) { el.click(); return el.tagName + ':' + el.textContent.trim(); } return null;"
            )
            log.info('Forgot click: %s', r_forgot)

            if not r_forgot:
                # Try clicking "Sign in with a passkey" or looking for email code option
                r_otp = await js(page,
                    "var all = Array.from(document.querySelectorAll('a,button,span'));"
                    "var el = all.find(function(e) {"
                    "  return /email.?code|one.?time|passkey|alternative/i.test(e.textContent) && e.offsetParent;"
                    "});"
                    "if (el) { el.click(); return el.textContent.trim(); } return null;"
                )
                log.info('Alt auth: %s', r_otp)

            await asyncio.sleep(5)
            t3 = await txt(page)
            log.info('After forgot: %s', t3[:200])

            # Wait for reset email
            body = await wait_email('clerk', 20, 10)
            if not body:
                body = await wait_email('openrouter', 10, 10)

            if body:
                codes = re.findall(r'\b[0-9]{6,8}\b', body)
                links = re.findall(r'https://[^\s<>"]{30,}', body)
                pplx_links = [l for l in links if 'openrouter' in l.lower() or 'clerk' in l.lower()]
                log.info('Codes: %s Links: %d', codes[:2], len(pplx_links))

                if pplx_links:
                    rp = await browser.get(pplx_links[0])
                    await asyncio.sleep(8)
                    t_r = await txt(rp)
                    log.info('Reset page: %s', t_r[:300])

                    # Set new password
                    await fill(rp, 'input[name="password"]', NEW_PASS)
                    await fill(rp, 'input[name="newPassword"]', NEW_PASS)
                    await fill(rp, 'input[name="confirmPassword"]', NEW_PASS)
                    await asyncio.sleep(0.5)

                    r_save = await js(rp,
                        "var b = Array.from(document.querySelectorAll('button'))"
                        ".find(function(b) { return b.offsetParent && b.type !== 'reset'; });"
                        "if (b) { b.click(); return b.textContent.trim(); } return null;"
                    )
                    log.info('Save: %s', r_save)
                    await asyncio.sleep(8)
                    t_after = await txt(rp)
                    log.info('After save: %s', t_after[:200])

                elif codes:
                    # OTP reset code
                    otp6 = await page.query_selector_all('input[maxlength="1"]')
                    if len(otp6) >= 6:
                        for d, el in zip(codes[0][:6], otp6[:6]):
                            await el.mouse_click(); await el.send_keys(d)
                            await asyncio.sleep(0.1)
                        await asyncio.sleep(1)
                        r_next = await js(page,
                            "var b = Array.from(document.querySelectorAll('button'))"
                            ".find(function(b) { return b.offsetParent; });"
                            "if (b) { b.click(); return b.textContent.trim(); } return null;"
                        )
                        log.info('After OTP: %s', r_next)
                        await asyncio.sleep(5)
                        # Set new password
                        await fill(page, 'input[name="password"]', NEW_PASS)
                        await asyncio.sleep(0.5)
                        r_pw = await js(page,
                            "var b = Array.from(document.querySelectorAll('button')).find(function(b){return b.offsetParent;});"
                            "if (b) { b.click(); return b.textContent.trim(); } return null;"
                        )
                        log.info('Set pw: %s', r_pw)
                        await asyncio.sleep(8)

                if await get_keys(browser):
                    return

        # If forgot pw flow failed, try OTP email sign-in
        log.info('Trying Clerk email code sign-in...')
        si = await browser.get('https://openrouter.ai/sign-in')
        await asyncio.sleep(8)
        await fill(si, 'input[name="identifier"]', GMAIL)
        await asyncio.sleep(0.5)
        await js(si,
            "var b = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) { return b.textContent.trim() === 'Continue'; });"
            "if (b) b.click();"
        )
        await wait_el(si, 'input[type="password"]', 10)
        t_pw = await txt(si)
        log.info('PW step: %s', t_pw[:200])

        # Look for email code option
        r_ec = await js(si,
            "var all = Array.from(document.querySelectorAll('a,button,p,span'));"
            "log = all.map(function(e) { return e.textContent.trim().slice(0,40); });"
            "return JSON.stringify(log.filter(function(t) { return t.length > 3; }).slice(0,20));"
        )
        log.info('Page elements: %s', str(r_ec)[:600])

    finally:
        try: browser.stop()
        except: pass

    v = dotenv_values(ENV).get('OPENROUTER_API_KEY', '')
    log.info('OPENROUTER_API_KEY: %s', ('SET ' + v[:25]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
