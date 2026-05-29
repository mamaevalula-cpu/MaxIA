#!/usr/bin/env python3
"""HuggingFace signup - multi-step form handling"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('hf_signup')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'
HF_PASS = 'FroggyBot2025!HF'
HF_USER = 'froggyai2025'

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
            log.info('  wait %d/%d', i+1, tries)
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

async def main():
    import nodriver as uc
    log.info('HuggingFace signup')
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
        page = await browser.get('https://huggingface.co/join')
        await asyncio.sleep(10)
        t = await txt(page)
        log.info('Join page: %s', t[:200])
        url = str(await js(page, "return window.location.href;"))
        log.info('URL: %s', url)

        # Log form structure
        inputs = await js(page,
            "return JSON.stringify(Array.from(document.querySelectorAll('input'))"
            ".map(function(i) { return {type:i.type, name:i.name, id:i.id, ph:i.placeholder.slice(0,20)}; }));"
        )
        log.info('Form inputs: %s', str(inputs)[:400])

        # Try login first (account may exist from previous attempt)
        login_page = await browser.get('https://huggingface.co/login')
        await asyncio.sleep(8)
        await fill(login_page, 'input[name="username"]', GMAIL)
        await asyncio.sleep(0.2)
        await fill(login_page, 'input[type="password"]', HF_PASS)
        await asyncio.sleep(0.2)
        r_login = await js(login_page,
            "var b = document.querySelector('input[type=\"submit\"],button[type=\"submit\"]');"
            "if (b) { b.click(); return 'clicked'; } return null;"
        )
        log.info('Login attempt: %s', r_login)
        await asyncio.sleep(8)
        t_login = await txt(login_page)
        url_login = str(await js(login_page, "return window.location.href;"))
        log.info('After login URL: %s', url_login)
        log.info('After login: %s', t_login[:200])

        if 'login' not in url_login and 'sign' not in url_login:
            log.info('LOGIN SUCCESS!')
            # Get API token
            tp = await browser.get('https://huggingface.co/settings/tokens')
            await asyncio.sleep(7)
            tc = await tp.get_content()
            tok = re.search(r'hf_[a-zA-Z0-9]{30,}', tc)
            if tok:
                set_key(ENV, 'HF_API_KEY', tok.group())
                log.info('*** HF TOKEN FOUND: %s ***', tok.group()[:25])
                return
            # Create token
            r_new = await js(tp,
                "var b = Array.from(document.querySelectorAll('button,a'))"
                ".find(function(b) { return /new|create|generate/i.test(b.textContent) && b.offsetParent; });"
                "if (b) { b.click(); return b.textContent.trim(); } return null;"
            )
            log.info('New token: %s', r_new)
            await asyncio.sleep(5)
            tc2 = await tp.get_content()
            tok2 = re.search(r'hf_[a-zA-Z0-9]{30,}', tc2)
            if tok2:
                set_key(ENV, 'HF_API_KEY', tok2.group())
                log.info('*** HF TOKEN CREATED: %s ***', tok2.group()[:25])
            return

        # Sign up flow - Step 1: Email
        page2 = await browser.get('https://huggingface.co/join')
        await asyncio.sleep(10)

        # HuggingFace join form might be multi-step
        # Step 1: Fill email
        em = await fill(page2, 'input[name="email"]', GMAIL)
        if not em:
            em = await fill(page2, 'input[type="email"]', GMAIL)
        log.info('Email filled: %s', em)

        # Click Next/Continue
        r1 = await js(page2,
            "var b = document.querySelector('input[type=\"submit\"],button[type=\"submit\"]');"
            "if (!b) b = Array.from(document.querySelectorAll('button'))"
            "  .find(function(b) { return /next|continue/i.test(b.textContent) && b.offsetParent; });"
            "if (b) { b.click(); return b.value || b.textContent.trim(); } return null;"
        )
        log.info('Step1 submit: %s', r1)
        await asyncio.sleep(5)

        t3 = await txt(page2)
        log.info('Step1 after: %s', t3[:200])
        url3 = str(await js(page2, "return window.location.href;"))
        log.info('Step1 URL: %s', url3)

        # Step 2: Username + Password (if prompted)
        inputs2 = await js(page2,
            "return JSON.stringify(Array.from(document.querySelectorAll('input'))"
            ".map(function(i) { return {type:i.type, name:i.name, id:i.id}; }));"
        )
        log.info('Step2 inputs: %s', str(inputs2)[:300])

        un = await fill(page2, 'input[name="username"]', HF_USER)
        pw = await fill(page2, 'input[type="password"]', HF_PASS)
        log.info('Username: %s Password: %s', un, pw)

        if un or pw:
            r2 = await js(page2,
                "var b = document.querySelector('input[type=\"submit\"],button[type=\"submit\"]');"
                "if (b) { b.click(); return b.value || b.textContent.trim(); } return null;"
            )
            log.info('Step2 submit: %s', r2)
            await asyncio.sleep(8)
            t4 = await txt(page2)
            log.info('Step2 after: %s', t4[:300])

        # Wait for verification email
        body = await wait_email('huggingface', 20, 10)
        if body:
            links = re.findall(r'https://[^\s<>"]+huggingface[^\s<>"]*', body, re.I)
            if links:
                vp = await browser.get(links[0])
                await asyncio.sleep(8)
                log.info('Verify: %s', (await txt(vp))[:150])
                url_v = str(await js(vp, "return window.location.href;"))
                log.info('Verify URL: %s', url_v[:80])

                if 'login' not in url_v:
                    # Get token
                    tp = await browser.get('https://huggingface.co/settings/tokens')
                    await asyncio.sleep(7)
                    # Create token
                    r_new = await js(tp,
                        "var b = Array.from(document.querySelectorAll('button,a'))"
                        ".find(function(b) { return /new|create/i.test(b.textContent) && b.offsetParent; });"
                        "if (b) { b.click(); return b.textContent.trim(); } return null;"
                    )
                    if r_new:
                        await asyncio.sleep(5)
                        # Fill token name
                        await fill(tp, 'input[name="tokenName"]', 'mytoken')
                        await fill(tp, 'input[type="text"]', 'mytoken')
                        await asyncio.sleep(0.5)
                        r_gen = await js(tp,
                            "var b = document.querySelector('input[type=\"submit\"],button[type=\"submit\"]');"
                            "if (!b) b = Array.from(document.querySelectorAll('button'))"
                            "  .find(function(b) { return /generat|creat/i.test(b.textContent); });"
                            "if (b) { b.click(); return b.textContent.trim(); } return null;"
                        )
                        log.info('Generate: %s', r_gen)
                        await asyncio.sleep(5)
                        tc3 = await tp.get_content()
                        tok3 = re.search(r'hf_[a-zA-Z0-9]{30,}', tc3)
                        if tok3:
                            set_key(ENV, 'HF_API_KEY', tok3.group())
                            log.info('*** HF TOKEN: %s ***', tok3.group()[:25])
        else:
            log.warning('No HuggingFace email received')

    finally:
        try: browser.stop()
        except: pass

    v = dotenv_values(ENV).get('HF_API_KEY', '')
    log.info('HF_API_KEY: %s', ('SET ' + v[:20]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
