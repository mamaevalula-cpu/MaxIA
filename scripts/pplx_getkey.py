#!/usr/bin/env python3
"""Get Perplexity API key - we know we can log in via magic link to console.perplexity.ai"""
import asyncio, sys, os, re, imaplib, email as elib, logging
from datetime import datetime, timedelta
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')
from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('pplx_key')

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

async def login_magic_link(page):
    """Full login flow via email magic link on console.perplexity.ai"""
    await page.get('https://console.perplexity.ai/')
    await asyncio.sleep(8)
    t = await txt(page)
    url = await js(page, "return window.location.href;")
    log.info('URL: %s', str(url)[:80])
    log.info('Page: %s', t[:150])

    # If already logged in (has API keys menu), skip
    if 'api keys' in t.lower() and 'sign in' not in t.lower():
        log.info('Already logged in!')
        return True

    # Click "Continue with email"
    r1 = await js(page,
        "var el = Array.from(document.querySelectorAll('button,a'))"
        ".find(function(e) { return e.textContent.trim().toLowerCase().includes('with email') && e.offsetParent; });"
        "if (el) { el.click(); return el.textContent.trim(); } return null;"
    )
    log.info('With email: %s', r1)
    if not r1:
        return False
    await asyncio.sleep(4)

    await fill(page, 'input[type="email"]', GMAIL)
    await asyncio.sleep(0.5)

    r2 = await js(page,
        "var form = document.querySelector('form');"
        "if (form) {"
        "  var sb = Array.from(form.querySelectorAll('button')).find(function(b) { return b.offsetParent; });"
        "  if (sb) { sb.click(); return sb.textContent.trim().slice(0,30); }"
        "}"
        "return null;"
    )
    log.info('Submit: %s', r2)
    await asyncio.sleep(10)

    t2 = await txt(page)
    log.info('After submit: %s', t2[:150])

    body = await wait_email('perplexity', 20, 12)
    if not body:
        log.error('No email')
        return False

    links = [l for l in re.findall(r'https://[^\s<>"]{30,}', body) if 'perplexity' in l.lower()]
    log.info('Magic links: %d', len(links))
    if not links:
        return False

    await page.get(links[0])
    await asyncio.sleep(10)

    url2 = await js(page, "return window.location.href;")
    log.info('After magic: %s', str(url2)[:80])
    return 'console.perplexity.ai' in str(url2) and '/auth/login' not in str(url2)


async def main():
    import nodriver as uc
    log.info('Perplexity API key getter')
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
        page = await browser.get('https://console.perplexity.ai/')
        await asyncio.sleep(5)

        logged_in = await login_magic_link(page)
        log.info('Logged in: %s', logged_in)

        if logged_in:
            # Get group ID from current URL
            url = str(await js(page, "return window.location.href;"))
            log.info('Dashboard URL: %s', url[:100])

            # Extract group ID
            m = re.search(r'/group/([a-f0-9-]+)', url)
            group_id = m.group(1) if m else None
            log.info('Group ID: %s', group_id)

            t = await txt(page)
            log.info('Dashboard: %s', t[:300])

            # Navigate to API keys page
            if group_id:
                api_keys_url = f'https://console.perplexity.ai/group/{group_id}/api-keys'
            else:
                api_keys_url = 'https://console.perplexity.ai/api-keys'

            await page.get(api_keys_url)
            await asyncio.sleep(8)

            url2 = await js(page, "return window.location.href;")
            t2 = await txt(page)
            log.info('API keys URL: %s', str(url2)[:100])
            log.info('API keys page: %s', t2[:400])

            kc = await page.get_content()

            # Check for existing key
            tok = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc)
            if tok:
                set_key(ENV, 'PERPLEXITY_API_KEY', tok.group())
                log.info('*** KEY FOUND: %s ***', tok.group()[:25])
                return

            # Try to create a new key
            log.info('No existing key, trying to create...')

            # Click "Generate" or "New API key"
            r3 = await js(page,
                "var b = Array.from(document.querySelectorAll('button,a'))"
                ".find(function(b) {"
                "  var t = b.textContent.trim().toLowerCase();"
                "  return (t.includes('generate') || t.includes('create') || t.includes('new') || t.includes('add')) && b.offsetParent;"
                "});"
                "if (b) { b.click(); return b.textContent.trim(); } return null;"
            )
            log.info('Create key: %s', r3)

            if r3:
                await asyncio.sleep(5)

                # Fill name if needed
                await fill(page, 'input[placeholder*="name" i]', 'my-api-key')
                await fill(page, 'input[placeholder*="key" i]', 'my-api-key')

                # Submit
                r4 = await js(page,
                    "var b = Array.from(document.querySelectorAll('button'))"
                    ".find(function(b) {"
                    "  var t = b.textContent.trim().toLowerCase();"
                    "  return (t.includes('create') || t.includes('generate') || t.includes('confirm') || t === 'save') && b.offsetParent;"
                    "});"
                    "if (b) { b.click(); return b.textContent.trim(); } return null;"
                )
                log.info('Confirm create: %s', r4)
                await asyncio.sleep(5)

                kc2 = await page.get_content()
                tok2 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc2)
                if tok2:
                    set_key(ENV, 'PERPLEXITY_API_KEY', tok2.group())
                    log.info('*** KEY CREATED: %s ***', tok2.group()[:25])
                else:
                    t_after = await txt(page)
                    log.info('After create: %s', t_after[:400])
            else:
                # Try clicking on "API keys" nav item
                r5 = await js(page,
                    "var b = Array.from(document.querySelectorAll('a,button,li'))"
                    ".find(function(b) {"
                    "  return /api.?key/i.test(b.textContent.trim()) && b.offsetParent;"
                    "});"
                    "if (b) { b.click(); return b.textContent.trim(); } return null;"
                )
                log.info('Click API keys nav: %s', r5)
                await asyncio.sleep(5)
                kc3 = await page.get_content()
                tok3 = re.search(r'pplx-[a-zA-Z0-9]{40,}', kc3)
                if tok3:
                    set_key(ENV, 'PERPLEXITY_API_KEY', tok3.group())
                    log.info('*** KEY FOUND AFTER NAV: %s ***', tok3.group()[:25])

    finally:
        try: browser.stop()
        except: pass

    v = dotenv_values(ENV).get('PERPLEXITY_API_KEY', '')
    log.info('PERPLEXITY_API_KEY: %s', ('SET ' + v[:25]) if v else 'EMPTY')

if __name__ == '__main__':
    asyncio.run(main())
