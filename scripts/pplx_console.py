#!/usr/bin/env python3
"""Perplexity console.perplexity.ai - correct domain for API keys"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('pplx_console')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'

def imap_get(kw='', since_min=12):
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

async def wait_email(kw, tries=20, since=12):
    for i in range(tries):
        await asyncio.sleep(5)
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


async def main():
    import nodriver as uc
    log.info('Perplexity console.perplexity.ai fix')
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
        # Go directly to console (the API keys domain)
        page = await browser.get('https://console.perplexity.ai/')
        await asyncio.sleep(8)
        t = await txt(page)
        url = await js(page, "return window.location.href;")
        log.info('Console URL: %s', str(url)[:100])
        log.info('Console page: %s', t[:200])

        # Should show login page - click "Continue with email"
        r1 = await js(page,
            "var el = Array.from(document.querySelectorAll('button,a'))"
            ".find(function(e) { return e.textContent.trim().toLowerCase().includes('with email') && e.offsetParent; });"
            "if (el) { el.click(); return el.textContent.trim(); } return null;"
        )
        log.info('Continue with email: %s', r1)
        await asyncio.sleep(4)

        # Fill email
        filled = await fill(page, 'input[type="email"]', GMAIL)
        if not filled:
            filled = await fill(page, 'input[name="email"]', GMAIL)
        log.info('Email filled: %s', filled)
        await asyncio.sleep(0.5)

        # Submit (not Google/Apple)
        r2 = await js(page,
            "var form = document.querySelector('form');"
            "if (form) {"
            "  var sb = Array.from(form.querySelectorAll('button')).find(function(b) { return b.offsetParent; });"
            "  if (sb) { sb.click(); return 'form:'+sb.textContent.trim().slice(0,30); }"
            "}"
            "var sb2 = Array.from(document.querySelectorAll('button'))"
            ".find(function(b) {"
            "  var t = b.textContent.trim().toLowerCase();"
            "  return (t.includes('continue') || t.includes('send') || t === 'next')"
            "  && !t.includes('google') && !t.includes('apple') && !t.includes('sso') && b.offsetParent;"
            "});"
            "if (sb2) { sb2.click(); return 'btn:'+sb2.textContent.trim().slice(0,30); }"
            "return null;"
        )
        log.info('Submit: %s', r2)
        await asyncio.sleep(10)

        t2 = await txt(page)
        log.info('After submit: %s', t2[:200])

        # Wait for magic link from console.perplexity.ai
        body = await wait_email('perplexity', 20, 12)
        if not body:
            log.error('No email received')
            return

        # Extract the magic link
        # Look for console.perplexity.ai or perplexity links
        links = re.findall(r'https://[^\s<>"]{30,}', body)
        pplx_links = [l for l in links if 'perplexity' in l.lower()]
        log.info('All perplexity links: %s', pplx_links[:3])

        if not pplx_links:
            log.error('No perplexity links in email')
            return

        magic_url = pplx_links[0]
        log.info('Following: %s', magic_url[:100])

        # Navigate to magic link (same page)
        await page.get(magic_url)
        await asyncio.sleep(12)

        url2 = await js(page, "return window.location.href;")
        t3 = await txt(page)
        log.info('After magic URL: %s', str(url2)[:100])
        log.info('After magic txt: %s', t3[:300])

        # Check for API keys on current page
        kc = await page.get_content()

        # First check if we're on an API console page
        if 'pplx-' in kc:
            tok = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc)
            if tok:
                set_key(ENV, 'PERPLEXITY_API_KEY', tok.group())
                log.info('*** KEY FOUND ON MAGIC PAGE: %s ***', tok.group()[:25])
                return

        # Navigate to console home
        await page.get('https://console.perplexity.ai/')
        await asyncio.sleep(8)
        url3 = await js(page, "return window.location.href;")
        t4 = await txt(page)
        log.info('Console home URL: %s', str(url3)[:100])
        log.info('Console home txt: %s', t4[:300])

        kc2 = await page.get_content()
        if 'pplx-' in kc2:
            tok2 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc2)
            if tok2:
                set_key(ENV, 'PERPLEXITY_API_KEY', tok2.group())
                log.info('*** KEY FOUND: %s ***', tok2.group()[:25])
                return

        # Try creating key
        r3 = await js(page,
            "var b = Array.from(document.querySelectorAll('button,a'))"
            ".find(function(b) { return /generate|create|new|add/i.test(b.textContent) && b.offsetParent; });"
            "if (b) { b.click(); return b.textContent.trim(); } return null;"
        )
        log.info('Create key: %s', r3)
        if r3:
            await asyncio.sleep(5)
            kc3 = await page.get_content()
            tok3 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc3)
            if tok3:
                set_key(ENV, 'PERPLEXITY_API_KEY', tok3.group())
                log.info('*** KEY CREATED: %s ***', tok3.group()[:25])

    finally:
        try: browser.stop()
        except: pass

    v = dotenv_values(ENV).get('PERPLEXITY_API_KEY', '')
    log.info('PERPLEXITY_API_KEY: %s', ('SET ' + v[:25]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
