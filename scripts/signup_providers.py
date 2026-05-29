#!/usr/bin/env python3
"""
Autonomous API provider signup script.
Tries Together.ai, OpenRouter, Cerebras, HuggingFace.
Uses nodriver (Chrome headless) + IMAP email verification.
Saves keys to .env automatically.
Run: /root/venv/bin/python3 /root/my_personal_ai/scripts/signup_providers.py
"""
import asyncio, sys, os, re, imaplib, email as elib, time, logging
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')

from dotenv import load_dotenv, set_key, dotenv_values
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('signup')

ENV       = '/root/my_personal_ai/.env'
GMAIL     = 'froggyinternet@gmail.com'
GPASS     = 'umtp ewnj biih wfbp'
PASS_TG   = 'FroggyBot2025!TG'
PASS_OR   = 'FroggyBot2025!OR'
PASS_CB   = 'FroggyBot2025!CB'
PASS_HF   = 'FroggyBot2025!HF'

# ── IMAP helpers ──────────────────────────────────────────────────────────────

def imap_latest(kw='', since_min=8):
    """Fetch latest email matching keyword from Gmail."""
    try:
        m = imaplib.IMAP4_SSL('imap.gmail.com', 993)
        m.login(GMAIL, GPASS)
        m.select('INBOX')
        since = (datetime.now() - timedelta(minutes=since_min)).strftime('%d-%b-%Y')
        _, d = m.search(None, 'SINCE ' + since)
        ids = d[0].split()[-20:] if d[0] else []
        for mid in reversed(ids):
            _, d2 = m.fetch(mid, '(RFC822)')
            msg = elib.message_from_bytes(d2[0][1])
            frm = str(msg.get('From', '')).lower()
            subj = str(msg.get('Subject', '')).lower()
            if not kw or kw.lower() in frm or kw.lower() in subj:
                body = ''
                if msg.is_multipart():
                    for p in msg.walk():
                        if p.get_content_type() in ('text/plain', 'text/html'):
                            try: body += p.get_payload(decode=True).decode('utf-8', errors='replace')
                            except: pass
                else:
                    try: body = msg.get_payload(decode=True).decode('utf-8', errors='replace')
                    except: pass
                m.logout()
                return body
        m.logout()
    except Exception as e:
        log.warning('IMAP error: %s', e)
    return None

async def wait_email(kw, tries=25, since_min=5):
    """Wait for email matching keyword."""
    log.info('Waiting email: %s', kw)
    for i in range(tries):
        await asyncio.sleep(6)
        body = imap_latest(kw, since_min)
        if body:
            return body
        if (i + 1) % 5 == 0:
            log.info('  still waiting... (%d/%d)', i + 1, tries)
    return None

# ── Page helpers ───────────────────────────────────────────────────────────────

async def page_text(page):
    c = await page.get_content()
    c = re.sub(r'<style[^>]*>.*?</style>', '', c, flags=re.DOTALL)
    c = re.sub(r'<script[^>]*>.*?</script>', '', c, flags=re.DOTALL)
    c = re.sub(r'<[^>]+>', ' ', c)
    return re.sub(r'\s+', ' ', c).strip()

async def fill_input(page, selector, value, delay=0.3):
    """Try multiple input selectors."""
    selectors = [selector] if isinstance(selector, str) else selector
    for sel in selectors:
        try:
            el = await page.select(sel)
            if el:
                await el.mouse_click()
                await asyncio.sleep(delay)
                # Clear existing text
                await el.send_keys('\x03')  # Ctrl+A
                await asyncio.sleep(0.1)
                await el.send_keys(value)
                return True
        except:
            pass
    return False

async def click_button(page, texts, timeout=5):
    """Click first button matching any text."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for text in texts:
            try:
                btn = await page.find(text, best_match=True)
                if btn:
                    pos = await btn.get_position()
                    if pos:
                        await btn.mouse_click()
                        await asyncio.sleep(2)
                        return True
            except:
                pass
        await asyncio.sleep(0.5)
    return False

async def enter_otp(page, code):
    """Enter 6-digit OTP into form."""
    log.info('  Entering OTP: %s', code)
    # Try individual character inputs
    otp6 = await page.query_selector_all('input[maxlength="1"]')
    otp1 = await page.select('input[maxlength="6"]')
    if len(otp6) >= 6:
        for digit, el in zip(code[:6], otp6[:6]):
            await el.mouse_click()
            await el.send_keys(digit)
            await asyncio.sleep(0.12)
        await asyncio.sleep(1)
        await click_button(page, ['Verify', 'Continue', 'Submit', 'Confirm'])
        return True
    elif otp1:
        await otp1.mouse_click()
        await otp1.send_keys(code)
        await asyncio.sleep(1)
        await click_button(page, ['Verify', 'Continue', 'Submit'])
        return True
    return False

def notify_telegram(msg):
    """Send notification via Telegram."""
    try:
        import httpx
        env = dotenv_values(ENV)
        tok = env.get('TELEGRAM_BOT_TOKEN', '')
        chat = env.get('TELEGRAM_CHAT_ID', '')
        if tok and chat:
            httpx.post(f'https://api.telegram.org/bot{tok}/sendMessage',
                json={'chat_id': chat, 'text': msg}, timeout=8)
    except:
        pass

# ── Together.ai signup ─────────────────────────────────────────────────────────

async def signup_together(browser):
    log.info('=== Together.ai signup ===')
    env = dotenv_values(ENV)
    if env.get('TOGETHER_API_KEY', '').strip():
        log.info('TOGETHER already has key, skipping')
        return True

    try:
        page = await browser.get('https://api.together.xyz/signup')
        await asyncio.sleep(7)

        # Accept cookies
        await click_button(page, ['Accept all', 'Accept All', 'Accept'])
        await asyncio.sleep(2)

        t = await page_text(page)
        log.info('Page: %s', t[:200])

        # Fill email
        filled = await fill_input(page, ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]'], GMAIL)
        if not filled:
            log.warning('No email input found')
            return False

        # Fill password
        await fill_input(page, ['input[type="password"]', 'input[name="password"]'], PASS_TG)

        # Submit
        await asyncio.sleep(1)
        await click_button(page, ['Sign up', 'Create account', 'Get started', 'Continue', 'Register'])
        await asyncio.sleep(8)

        t2 = await page_text(page)
        log.info('After submit: %s', t2[:300])

        # Check for verification needed
        if any(x in t2.lower() for x in ['verif', 'confirm', 'check your email', 'sent', 'code']):
            log.info('Waiting for verification email...')
            body = await wait_email('together', 25, 5)
            if not body:
                body = await wait_email('noreply', 10, 5)
            if body:
                codes = re.findall(r'\b[0-9]{6}\b', body)
                links = [l for l in re.findall(r'https://\S+', body) if 'together' in l.lower() or 'verif' in l.lower()]
                log.info('Codes: %s Links: %s', codes[:2], links[:1])
                if links:
                    vp = await browser.get(links[0])
                    await asyncio.sleep(8)
                    log.info('Verify page: %s', (await page_text(vp))[:150])
                elif codes:
                    await enter_otp(page, codes[0])
                    await asyncio.sleep(5)

        # Check if already logged in
        if 'already' in t2.lower() or 'exists' in t2.lower():
            log.info('Account may already exist, trying login...')
            page2 = await browser.get('https://api.together.xyz/signin')
            await asyncio.sleep(5)
            await fill_input(page2, ['input[type="email"]', 'input[name="email"]'], GMAIL)
            await fill_input(page2, ['input[type="password"]', 'input[name="password"]'], PASS_TG)
            await click_button(page2, ['Sign in', 'Log in', 'Continue'])
            await asyncio.sleep(8)

        # Try to get API key
        kp = await browser.get('https://api.together.xyz/settings/api-keys')
        await asyncio.sleep(7)
        kc = await kp.get_content()
        kt = await page_text(kp)
        log.info('Keys page: %s', kt[:200])

        # Look for key in page content
        tok = re.search(r'[0-9a-f]{64}', kc)
        if tok:
            set_key(ENV, 'TOGETHER_API_KEY', tok.group())
            log.info('TOGETHER_API_KEY saved: %s...', tok.group()[:20])
            notify_telegram(f'Together.ai key obtained!')
            return True
        else:
            # Try to create a new key via button
            created = await click_button(kp, ['Create', 'Generate', 'New key', 'Add key'])
            if created:
                await asyncio.sleep(4)
                kc2 = await kp.get_content()
                tok2 = re.search(r'[0-9a-f]{64}', kc2)
                if tok2:
                    set_key(ENV, 'TOGETHER_API_KEY', tok2.group())
                    log.info('TOGETHER_API_KEY created: %s...', tok2.group()[:20])
                    notify_telegram(f'Together.ai key created!')
                    return True
        log.warning('Together: no key found on keys page')
    except Exception as e:
        log.error('Together signup error: %s', e)
    return False

# ── OpenRouter signup ──────────────────────────────────────────────────────────

async def signup_openrouter(browser):
    log.info('=== OpenRouter signup ===')
    env = dotenv_values(ENV)
    if env.get('OPENROUTER_API_KEY', '').strip():
        log.info('OPENROUTER already has key, skipping')
        return True

    try:
        page = await browser.get('https://openrouter.ai/sign-up')
        await asyncio.sleep(7)
        t = await page_text(page)
        log.info('SignUp page: %s', t[:200])

        # Fill form
        await fill_input(page, ['input[name="emailAddress"]', 'input[type="email"]', 'input[name="email"]'], GMAIL)
        await fill_input(page, ['input[type="password"]', 'input[name="password"]'], PASS_OR)

        # Check checkbox if present
        try:
            cb = await page.select('input[type="checkbox"]')
            if cb:
                await cb.mouse_click()
                await asyncio.sleep(0.2)
        except:
            pass

        await asyncio.sleep(2)
        await click_button(page, ['Continue', 'Sign up', 'Create account'])
        await asyncio.sleep(9)

        t2 = await page_text(page)
        log.info('After submit: %s', t2[:300])

        # Check for OTP fields
        otp6 = await page.query_selector_all('input[maxlength="1"]')
        otp1 = await page.select('input[maxlength="6"]')
        if len(otp6) >= 1 or otp1:
            log.info('OTP form detected, checking email...')
            body = await wait_email('clerk', 25, 5)
            if not body:
                body = await wait_email('openrouter', 10, 5)
            if not body:
                body = await wait_email('noreply', 10, 5)
            if body:
                codes = re.findall(r'\b[0-9]{6}\b', body)
                log.info('OTP codes found: %s', codes[:2])
                if codes:
                    await enter_otp(page, codes[0])
                    await asyncio.sleep(6)
                    t3 = await page_text(page)
                    log.info('After OTP: %s', t3[:200])

        # Also try sign-in if account exists
        if 'already' in t2.lower() or 'sign in' in t2.lower() or 'exists' in t2.lower():
            log.info('Account may exist, trying sign-in...')
            si = await browser.get('https://openrouter.ai/sign-in')
            await asyncio.sleep(5)
            await fill_input(si, ['input[name="identifier"]', 'input[type="email"]', 'input[name="emailAddress"]'], GMAIL)
            await click_button(si, ['Continue'])
            await asyncio.sleep(4)
            t_si = await page_text(si)
            # OTP for sign-in
            otp_si = await si.query_selector_all('input[maxlength="1"]')
            if len(otp_si) >= 1:
                body2 = await wait_email('clerk', 20, 5)
                if body2:
                    c2 = re.findall(r'\b[0-9]{6}\b', body2)
                    if c2:
                        await enter_otp(si, c2[0])
                        await asyncio.sleep(6)

        # Get API key
        kp = await browser.get('https://openrouter.ai/settings/keys')
        await asyncio.sleep(6)
        kc = await kp.get_content()
        kt = await page_text(kp)
        log.info('Keys page: %s', kt[:200])

        # Look for existing key
        ks = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc)
        if ks:
            set_key(ENV, 'OPENROUTER_API_KEY', ks[0])
            log.info('OPENROUTER_API_KEY saved: %s...', ks[0][:25])
            notify_telegram(f'OpenRouter key obtained!')
            return True

        # Create new key
        created = await click_button(kp, ['Create key', 'Create', 'Generate', 'Add key', 'New API key'])
        if created:
            await asyncio.sleep(5)
            kc2 = await kp.get_content()
            ks2 = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc2)
            if ks2:
                set_key(ENV, 'OPENROUTER_API_KEY', ks2[0])
                log.info('OPENROUTER_API_KEY created: %s...', ks2[0][:25])
                notify_telegram(f'OpenRouter key created!')
                return True

        # Try via profile page
        alt = await browser.get('https://openrouter.ai/workspaces/default/keys')
        await asyncio.sleep(5)
        kc3 = await alt.get_content()
        ks3 = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', kc3)
        if ks3:
            set_key(ENV, 'OPENROUTER_API_KEY', ks3[0])
            log.info('OPENROUTER_API_KEY found: %s...', ks3[0][:25])
            notify_telegram(f'OpenRouter key found!')
            return True

        log.warning('OpenRouter: no key found')
    except Exception as e:
        log.error('OpenRouter signup error: %s', e)
    return False

# ── Cerebras signup ─────────────────────────────────────────────────────────────

async def signup_cerebras(browser):
    log.info('=== Cerebras signup ===')
    env = dotenv_values(ENV)
    if env.get('CEREBRAS_API_KEY', '').strip():
        log.info('CEREBRAS already has key, skipping')
        return True

    try:
        page = await browser.get('https://cloud.cerebras.ai/')
        await asyncio.sleep(9)

        # Accept cookies
        for _ in range(3):
            try:
                await click_button(page, ['Accept All', 'Accept', 'Got it', 'OK'])
                await asyncio.sleep(1)
            except:
                break

        t = await page_text(page)
        log.info('Page: %s', t[:200])

        # Find email input (might be in a modal or on page)
        ce = await page.select('input[type="email"]')
        if not ce:
            ce = await page.select('input[name="email"]')
        if not ce:
            # Try clicking "Sign up" or "Get started" first
            await click_button(page, ['Sign up', 'Get started', 'Try for free', 'Login', 'Sign in'])
            await asyncio.sleep(4)
            ce = await page.select('input[type="email"]')

        if ce:
            await ce.mouse_click()
            await asyncio.sleep(0.3)
            await ce.send_keys(GMAIL)
            log.info('Email entered')

            # Submit
            await click_button(page, ['CONTINUE WITH EMAIL', 'Continue with Email', 'Continue', 'Send magic link', 'Sign up', 'Submit'])
            await asyncio.sleep(10)
            t2 = await page_text(page)
            log.info('After submit: %s', t2[:200])

            # Wait for magic link/OTP
            body = await wait_email('cerebras', 20, 5)
            if not body:
                body = await wait_email('magic', 10, 5)
            if not body:
                body = await wait_email('okta', 10, 5)
            if body:
                clinks = re.findall(r'https://[^\s<>"]+(?:cerebras|okta|cloud)[^\s<>"]*', body, re.I)
                ccodes = re.findall(r'\b[0-9]{6}\b', body)
                log.info('Links: %d Codes: %s', len(clinks), ccodes[:2])
                if clinks:
                    ml = await browser.get(clinks[0])
                    await asyncio.sleep(9)
                    log.info('Magic link page: %s', (await page_text(ml))[:200])
                elif ccodes:
                    await enter_otp(page, ccodes[0])
                    await asyncio.sleep(6)
        else:
            log.warning('No email input found on Cerebras page')
            # Try direct API key page if already logged in
            kp = await browser.get('https://cloud.cerebras.ai/platform/api-keys')
            await asyncio.sleep(6)
            kc = await kp.get_content()
            ks = re.findall(r'cbsk-[a-zA-Z0-9_-]{20,}', kc)
            if ks:
                set_key(ENV, 'CEREBRAS_API_KEY', ks[0])
                log.info('CEREBRAS_API_KEY found (already logged): %s...', ks[0][:20])
                return True
            return False

        # Check API keys page
        await asyncio.sleep(3)
        kp = await browser.get('https://cloud.cerebras.ai/platform/api-keys')
        await asyncio.sleep(6)
        kc = await kp.get_content()
        kt = await page_text(kp)
        log.info('Keys page: %s', kt[:200])

        ks = re.findall(r'cbsk-[a-zA-Z0-9_-]{20,}', kc)
        if ks:
            set_key(ENV, 'CEREBRAS_API_KEY', ks[0])
            log.info('CEREBRAS_API_KEY saved: %s...', ks[0][:20])
            notify_telegram(f'Cerebras key obtained!')
            return True

        # Create new key
        await click_button(kp, ['Create API Key', 'Create', 'Generate', 'New key', 'Add'])
        await asyncio.sleep(5)
        kc2 = await kp.get_content()
        ks2 = re.findall(r'cbsk-[a-zA-Z0-9_-]{20,}', kc2)
        if ks2:
            set_key(ENV, 'CEREBRAS_API_KEY', ks2[0])
            log.info('CEREBRAS_API_KEY created: %s...', ks2[0][:20])
            notify_telegram(f'Cerebras key created!')
            return True

        log.warning('Cerebras: no key found')
    except Exception as e:
        log.error('Cerebras signup error: %s', e)
    return False

# ── HuggingFace signup ─────────────────────────────────────────────────────────

async def signup_huggingface(browser):
    log.info('=== HuggingFace signup ===')
    env = dotenv_values(ENV)
    if env.get('HF_API_KEY', '').strip():
        log.info('HF already has key, skipping')
        return True

    try:
        # HuggingFace registration is simpler
        page = await browser.get('https://huggingface.co/join')
        await asyncio.sleep(7)
        t = await page_text(page)
        log.info('HF page: %s', t[:200])

        # Fill username
        await fill_input(page, ['input[name="username"]', 'input[id="username"]'], 'froggybot2025ai')
        # Fill email
        await fill_input(page, ['input[name="email"]', 'input[type="email"]'], GMAIL)
        # Fill password
        await fill_input(page, ['input[name="password"]', 'input[type="password"]'], PASS_HF)

        await asyncio.sleep(1)
        await click_button(page, ['Create account', 'Register', 'Sign up', 'Join'])
        await asyncio.sleep(9)
        t2 = await page_text(page)
        log.info('After submit: %s', t2[:200])

        # Email verification
        if any(x in t2.lower() for x in ['verif', 'confirm', 'check your email']):
            body = await wait_email('huggingface', 20, 5)
            if body:
                links = re.findall(r'https://[^\s<>"]+huggingface[^\s<>"]*', body, re.I)
                if links:
                    vp = await browser.get(links[0])
                    await asyncio.sleep(8)
                    log.info('HF verify: %s', (await page_text(vp))[:200])

        # Get API token
        tp = await browser.get('https://huggingface.co/settings/tokens')
        await asyncio.sleep(6)
        tc = await tp.get_content()
        tt = await page_text(tp)
        log.info('Tokens page: %s', tt[:200])

        # Look for existing token
        tok = re.search(r'hf_[a-zA-Z0-9]{30,}', tc)
        if tok:
            set_key(ENV, 'HF_API_KEY', tok.group())
            log.info('HF_API_KEY found: %s...', tok.group()[:20])
            return True

        # Create new token
        await click_button(tp, ['New token', 'Create', 'Generate new token', 'Add token'])
        await asyncio.sleep(4)
        tc2 = await tp.get_content()
        tok2 = re.search(r'hf_[a-zA-Z0-9]{30,}', tc2)
        if tok2:
            set_key(ENV, 'HF_API_KEY', tok2.group())
            log.info('HF_API_KEY created: %s...', tok2.group()[:20])
            notify_telegram(f'HuggingFace token created!')
            return True

        log.warning('HuggingFace: no token found')
    except Exception as e:
        log.error('HuggingFace signup error: %s', e)
    return False

# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    import nodriver as uc

    log.info('Starting signup automation...')
    log.info('Target: Together.ai | OpenRouter | Cerebras | HuggingFace')

    browser = await uc.start(
        headless=True,
        browser_executable_path='/usr/bin/google-chrome-stable',
        browser_args=[
            '--no-sandbox', '--disable-dev-shm-usage',
            '--window-size=1280,900',
            '--disable-blink-features=AutomationControlled',
            '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36',
        ]
    )
    log.info('Browser started')

    results = {}

    try:
        results['together']    = await signup_together(browser)
        results['openrouter']  = await signup_openrouter(browser)
        results['cerebras']    = await signup_cerebras(browser)
        results['huggingface'] = await signup_huggingface(browser)
    finally:
        try: browser.stop()
        except: pass

    log.info('=== RESULTS ===')
    for svc, ok in results.items():
        log.info('  %s: %s', svc, 'OK' if ok else 'FAILED')

    # Final env check
    env = dotenv_values(ENV)
    keys = ['TOGETHER_API_KEY','OPENROUTER_API_KEY','CEREBRAS_API_KEY','HF_API_KEY']
    summary = []
    for k in keys:
        v = env.get(k, '')
        summary.append(f"{'✅' if v else '❌'} {k.split('_')[0]}")

    msg = 'Signup results:\n' + '\n'.join(summary)
    log.info(msg)
    notify_telegram(msg)
    return results

if __name__ == '__main__':
    asyncio.run(main())
