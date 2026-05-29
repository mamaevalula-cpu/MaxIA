#!/usr/bin/env python3
"""
create_bots.py — Create MaxAI bots on registered platforms
Platforms: Coze (logged_in), Relevance AI (registered), Langflow (registered)
"""
import asyncio, json, logging, os, time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('create_bots')

TG_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT  = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

EMAIL1   = 'froggyinternet@gmail.com'
EMAIL2   = 'jimmorrisoninlove@gmail.com'
PASSWORD = 'Internetinternet!2'
PASSWORD2 = 'Fukcyoubithc48'

MAXAI_API = 'http://77.90.2.171:8090'
CONTACT   = '@maxai_corp'

COZE_PROMPT = """You are MaxAI — an AI automation assistant from MaxAI Corporation.

Your role: Help users understand what can be automated in their business.

When a user describes a task:
1. Identify what can be automated
2. Suggest specific solution (Telegram bot / parser / AI workflow)
3. Give measurable result: "This will save X hours per week"
4. End with: "Order full implementation: @maxai_corp | From 3000 RUB / $33"

Rules:
- Be specific and measurable
- Russian if user writes in Russian
- Under 300 words
- Always end with @maxai_corp CTA"""

STATUS_FILE = Path('/root/my_personal_ai/data/platform_status.json')

def tg(text):
    import urllib.request as ur
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4000]}).encode()
        ur.urlopen(ur.Request(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=d, headers={'Content-Type': 'application/json'}
        ), timeout=8)
    except Exception as e:
        log.warning('TG error: %s', e)

def load_status():
    try:
        return json.loads(STATUS_FILE.read_text())
    except:
        return {}

def save_status(s):
    STATUS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))


async def create_coze_bot(page):
    """Create MaxAI bot on Coze"""
    log.info('[Coze] Starting bot creation...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        # Login first
        await page.goto('https://www.coze.com/signin', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        page_text = (await page.inner_text('body')).lower()
        if 'dashboard' in page_text or 'workspace' in page_text or 'create bot' in page_text.lower():
            log.info('[Coze] Already logged in')
        else:
            # Try to login
            for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="email" i]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL2)
                    break
            for sel in ['input[type="password"]', 'input[name="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD2)
                    break
            for sel in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Log in")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    break
            await asyncio.sleep(5)

        # Navigate to bot creation
        await page.goto('https://www.coze.com/space/bots/create', wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(3)

        # Try alternative URL
        current = page.url
        if 'create' not in current and 'bot' not in current:
            await page.goto('https://www.coze.com/', wait_until='domcontentloaded', timeout=20000)
            await asyncio.sleep(3)
            # Look for "Create Bot" button
            for sel in ['button:has-text("Create Bot")', 'button:has-text("New Bot")',
                        'a:has-text("Create")', '[data-testid*="create"]']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    break

        # Fill bot name
        for sel in ['input[placeholder*="bot name" i]', 'input[name="name"]',
                    'input[placeholder*="name" i]', 'input[aria-label*="name" i]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.clear()
                await el.fill('MaxAI Assistant')
                log.info('[Coze] Filled bot name')
                break

        # Fill description
        for sel in ['textarea[placeholder*="description" i]', 'textarea[name="description"]',
                    'input[placeholder*="description" i]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill('Business automation assistant. Telegram bots, parsers, AI workflows. Order: @maxai_corp')
                log.info('[Coze] Filled description')
                break

        # Click Create/Confirm
        for sel in ['button:has-text("Create")', 'button:has-text("Confirm")',
                    'button[type="submit"]', 'button:has-text("Next")']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                log.info('[Coze] Clicked create')
                break

        new_url = page.url
        if 'bot' in new_url and ('edit' in new_url or 'settings' in new_url or len(new_url) > 30):
            # Now fill the system prompt
            for sel in ['textarea[placeholder*="prompt" i]', 'textarea[placeholder*="instruction" i]',
                        '#system-prompt', '[data-testid*="prompt"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(COZE_PROMPT)
                    log.info('[Coze] Filled system prompt')
                    break

            # Save / Publish
            for sel in ['button:has-text("Publish")', 'button:has-text("Save")',
                        'button:has-text("Deploy")', 'button[type="submit"]']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(3)
                    log.info('[Coze] Published/saved')
                    break

            result['status'] = 'bot_created'
            result['bot_url'] = new_url
            log.info('[Coze] Bot created! URL: %s', new_url)
        else:
            result['status'] = 'creation_failed'
            result['page_url'] = new_url
            log.warning('[Coze] Could not create bot. URL: %s', new_url)

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[Coze] Error: %s', e)

    return result


async def create_relevance_agent(page):
    """Create MaxAI agent on Relevance AI"""
    log.info('[RelevanceAI] Starting agent creation...')
    result = {'status': 'unknown', 'ts': time.time()}
    try:
        # Login
        await page.goto('https://app.relevanceai.com/login', wait_until='domcontentloaded', timeout=30000)
        await asyncio.sleep(3)

        page_text = (await page.inner_text('body')).lower()
        if 'dashboard' not in page_text and 'workspace' not in page_text:
            for sel in ['input[type="email"]', 'input[name="email"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(EMAIL1)
                    break
            for sel in ['input[type="password"]']:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.fill(PASSWORD)
                    break
            for sel in ['button[type="submit"]', 'button:has-text("Sign in")', 'button:has-text("Log in")']:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    break
            await asyncio.sleep(5)

        # Navigate to create agent
        await page.goto('https://app.relevanceai.com/agents/new', wait_until='domcontentloaded', timeout=20000)
        await asyncio.sleep(3)

        # Fill agent name
        for sel in ['input[placeholder*="agent name" i]', 'input[name="name"]',
                    'input[placeholder*="name" i]', 'input[aria-label*="name" i]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill('MaxAI Lead Qualifier')
                log.info('[RelevanceAI] Filled agent name')
                break

        # Fill description/goal
        for sel in ['textarea[placeholder*="description" i]', 'textarea[name="description"]',
                    'textarea[placeholder*="goal" i]']:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.fill(
                    'Qualifies incoming leads: receives name, company, request -> '
                    'scores intent -> routes to CRM or Telegram. '
                    'Revenue outcome: 3x faster lead response. Order: @maxai_corp'
                )
                log.info('[RelevanceAI] Filled description')
                break

        # Submit
        for sel in ['button[type="submit"]', 'button:has-text("Create")',
                    'button:has-text("Save")', 'button:has-text("Next")']:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(4)
                break

        new_url = page.url
        if 'agent' in new_url and len(new_url) > 40:
            result['status'] = 'agent_created'
            result['agent_url'] = new_url
            log.info('[RelevanceAI] Agent created! URL: %s', new_url)
        else:
            result['status'] = 'creation_failed'
            result['page_url'] = new_url
            log.warning('[RelevanceAI] Could not create agent')

    except Exception as e:
        result['status'] = 'error'
        result['error'] = str(e)[:200]
        log.error('[RelevanceAI] Error: %s', e)

    return result


async def run():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async as sa
        USE_STEALTH = True
    except:
        USE_STEALTH = False

    status = load_status()

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage',
                  '--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        )
        page = await ctx.new_page()
        if USE_STEALTH:
            await sa(page)

        # 1. Create Coze bot
        coze_result = await create_coze_bot(page)
        status['coze_bot'] = coze_result
        save_status(status)
        log.info('Coze result: %s', coze_result['status'])

        await asyncio.sleep(5)

        # 2. Create Relevance AI agent
        rel_result = await create_relevance_agent(page)
        status['relevance_ai_agent'] = rel_result
        save_status(status)
        log.info('RelevanceAI result: %s', rel_result['status'])

        await browser.close()

    msg = (
        f'MaxAI Bot Creation — Done\n\n'
        f'Coze bot: {coze_result["status"]}\n'
        f'RelevanceAI agent: {rel_result["status"]}\n'
    )
    if coze_result.get('bot_url'):
        msg += f'Coze URL: {coze_result["bot_url"]}\n'
    if rel_result.get('agent_url'):
        msg += f'RelevanceAI URL: {rel_result["agent_url"]}\n'

    tg(msg)
    print(msg)


if __name__ == '__main__':
    asyncio.run(run())
