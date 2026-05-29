#!/usr/bin/env python3
"""Create Perplexity API key - logged in, click Start button"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('pplx_ckey')

ENV   = '/root/my_personal_ai/.env'
GMAIL = 'froggyinternet@gmail.com'
GPASS = 'umtp ewnj biih wfbp'
GROUP = '4a5fe369-ef7a-43e5-908e-903b97dac22e'

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
        await asyncio.sleep(5)
        b = imap_get(kw, since)
        if b: return b
        if (i+1) % 5 == 0:
            log.info('  waiting %d/%d', i+1, tries)
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

async def login_if_needed(page):
    """Login via magic link if not already logged in"""
    t = await txt(page)
    url = str(await js(page, "return window.location.href;"))
    if '/auth/login' not in url and 'sign in' not in t[:100].lower():
        log.info('Already logged in at %s', url[:60])
        return True

    # Click Continue with email
    r1 = await js(page,
        "var el = Array.from(document.querySelectorAll('button,a'))"
        ".find(function(e) { return e.textContent.trim().toLowerCase().includes('with email') && e.offsetParent; });"
        "if (el) { el.click(); return el.textContent.trim(); } return null;"
    )
    log.info('Email btn: %s', r1)
    await asyncio.sleep(4)

    await fill(page, 'input[type="email"]', GMAIL)
    await asyncio.sleep(0.5)

    # Submit via form
    r2 = await js(page,
        "var form = document.querySelector('form');"
        "if (form) {"
        "  var sb = Array.from(form.querySelectorAll('button')).find(function(b) { return b.offsetParent && b.type !== 'reset'; });"
        "  if (sb) { sb.click(); return sb.textContent.trim().slice(0,30); }"
        "  form.requestSubmit();"
        "  return 'requestSubmit';"
        "}"
        "return null;"
    )
    log.info('Form submit: %s', r2)
    await asyncio.sleep(10)

    body = await wait_email('perplexity', 20, 15)
    if not body:
        log.error('No email')
        return False

    links = [l for l in re.findall(r'https://[^\s<>"]{30,}', body)
             if 'console.perplexity' in l.lower() or ('perplexity' in l.lower() and 'callback' in l.lower())]
    if not links:
        links = [l for l in re.findall(r'https://[^\s<>"]{30,}', body) if 'perplexity' in l.lower()]
    log.info('Magic links: %d', len(links))
    if not links:
        return False

    await page.get(links[0])
    await asyncio.sleep(10)
    url2 = str(await js(page, "return window.location.href;"))
    log.info('After magic: %s', url2[:80])
    return '/auth/login' not in url2


async def main():
    import nodriver as uc
    log.info('Perplexity create key')
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
        page = await browser.get(f'https://console.perplexity.ai/group/{GROUP}/api-keys')
        await asyncio.sleep(8)

        logged_in = await login_if_needed(page)
        log.info('Login: %s', logged_in)

        if not logged_in:
            log.error('Could not log in')
            return

        # Navigate to API keys page
        api_keys_url = f'https://console.perplexity.ai/group/{GROUP}/api-keys'
        await page.get(api_keys_url)
        await asyncio.sleep(8)

        url = str(await js(page, "return window.location.href;"))
        t = await txt(page)
        log.info('API keys URL: %s', url[:100])
        log.info('API keys page: %s', t[:500])

        kc = await page.get_content()

        # Check for existing key first
        tok = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc)
        if tok:
            set_key(ENV, 'PERPLEXITY_API_KEY', tok.group())
            log.info('*** EXISTING KEY: %s ***', tok.group()[:25])
            return

        # Log all buttons on page
        btns = await js(page,
            "return JSON.stringify(Array.from(document.querySelectorAll('button,a[role]'))"
            ".filter(function(b) { return b.offsetParent; })"
            ".map(function(b) { return b.textContent.trim().slice(0,30); }));"
        )
        log.info('Buttons: %s', str(btns)[:400])

        # Click "Start" button (visible in previous log as the API key create button)
        r1 = await js(page,
            "var btns = Array.from(document.querySelectorAll('button,a'));"
            "var b = btns.find(function(b) {"
            "  var t = b.textContent.trim();"
            "  return (t === 'Start' || t === 'Generate' || t === 'Create' || t.includes('Generate a key') || t.includes('New key')) && b.offsetParent;"
            "});"
            "if (b) { b.click(); return b.textContent.trim(); } return null;"
        )
        log.info('Start/Create click: %s', r1)

        if not r1:
            # Try any button with create/generate in text
            r1 = await js(page,
                "var btns = Array.from(document.querySelectorAll('button,a'));"
                "var b = btns.find(function(b) {"
                "  var t = b.textContent.trim().toLowerCase();"
                "  return (t.includes('generat') || t.includes('creat') || t.includes('new') || t.includes('add')) && b.offsetParent;"
                "});"
                "if (b) { b.click(); return b.textContent.trim(); } return null;"
            )
            log.info('Alt create: %s', r1)

        if r1:
            await asyncio.sleep(5)
            t2 = await txt(page)
            log.info('After create: %s', t2[:400])
            kc2 = await page.get_content()
            tok2 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc2)
            if tok2:
                set_key(ENV, 'PERPLEXITY_API_KEY', tok2.group())
                log.info('*** KEY CREATED: %s ***', tok2.group()[:25])
                return

            # Maybe a dialog appeared - look for key in dialog
            # Fill key name if prompted
            name_filled = await fill(page, 'input[type="text"]', 'bot-key')
            if not name_filled:
                name_filled = await fill(page, 'input[placeholder*="name" i]', 'bot-key')

            r3 = await js(page,
                "var b = Array.from(document.querySelectorAll('button'))"
                ".find(function(b) {"
                "  var t = b.textContent.trim().toLowerCase();"
                "  return (t === 'create' || t === 'generate' || t === 'save' || t === 'confirm') && b.offsetParent;"
                "});"
                "if (b) { b.click(); return b.textContent.trim(); } return null;"
            )
            log.info('Dialog confirm: %s', r3)
            await asyncio.sleep(5)

            kc3 = await page.get_content()
            tok3 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc3)
            if tok3:
                set_key(ENV, 'PERPLEXITY_API_KEY', tok3.group())
                log.info('*** KEY AFTER DIALOG: %s ***', tok3.group()[:25])
                return

            t3 = await txt(page)
            log.info('Page after dialog: %s', t3[:400])

    finally:
        try: browser.stop()
        except: pass

    v = dotenv_values(ENV).get('PERPLEXITY_API_KEY', '')
    log.info('PERPLEXITY_API_KEY: %s', ('SET ' + v[:25]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
