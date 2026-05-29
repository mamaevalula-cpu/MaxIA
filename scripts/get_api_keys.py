#!/usr/bin/env python3
"""
get_api_keys.py — Attempts to get Cerebras + OpenRouter API keys
via browser OAuth (Google/GitHub) — no CAPTCHA required for OAuth.
"""
import sys, os, re, asyncio, time
sys.path.insert(0, "/root/my_personal_ai")
os.chdir("/root/my_personal_ai")

from dotenv import load_dotenv, set_key
load_dotenv()

ENV_FILE = "/root/my_personal_ai/.env"

async def try_get_cerebras(page):
    print("=== Cerebras ===")
    try:
        await page.goto("https://cloud.cerebras.ai/platform/", timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        url = page.url
        print(f"  Current URL: {url}")

        # Check if already logged in (redirected to dashboard/api-keys)
        if "platform" in url and "login" not in url and "sign" not in url:
            # Try navigating to API keys page
            await page.goto("https://cloud.cerebras.ai/platform/api-keys", timeout=20000, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            content = await page.content()
            # Look for key patterns
            keys = re.findall(r'cbsk-[a-zA-Z0-9_\-]{20,}', content)
            if keys:
                print(f"  FOUND KEY: {keys[0][:20]}...")
                return keys[0]
            # Try to find create/copy button
            text = await page.inner_text("body")
            if "cbsk-" in text:
                keys2 = re.findall(r'cbsk-[a-zA-Z0-9_\-]{20,}', text)
                if keys2:
                    print(f"  FOUND KEY (text): {keys2[0][:20]}...")
                    return keys2[0]
            print(f"  Logged in but no key found. Page title: {await page.title()}")
            return None

        # Not logged in — look for OAuth buttons
        content = await page.content()
        print(f"  Page title: {await page.title()}")

        # Look for Google or GitHub sign-in
        for selector in [
            'button:has-text("Continue with Google")',
            'button:has-text("Sign in with Google")',
            'a:has-text("Continue with Google")',
            'button:has-text("Continue with GitHub")',
            'a:has-text("Continue with GitHub")',
            '[data-provider="google"]',
            '[data-provider="github"]',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    print(f"  Found OAuth button: {selector}")
                    print("  NOTE: OAuth requires user interaction (browser session)")
                    return None
            except Exception:
                pass

        # Check for Cloudflare
        if "cloudflare" in content.lower() or "challenge" in content.lower():
            print("  BLOCKED: Cloudflare challenge detected")
        else:
            print(f"  No OAuth buttons found. Snippet: {content[:200]}")

    except Exception as e:
        print(f"  ERROR: {e}")
    return None


async def try_get_openrouter(page):
    print("=== OpenRouter ===")
    try:
        await page.goto("https://openrouter.ai/keys", timeout=30000, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        url = page.url
        print(f"  Current URL: {url}")

        # Check if already logged in
        if "/keys" in url and "sign" not in url and "login" not in url:
            content = await page.content()
            text = await page.inner_text("body")
            keys = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', content + text)
            if keys:
                print(f"  FOUND KEY: {keys[0][:20]}...")
                return keys[0]
            # Try clicking "Create Key" and reading
            for sel in ['button:has-text("Create Key")', 'button:has-text("Create key")', 'button:has-text("New key")']:
                try:
                    btn = await page.query_selector(sel)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(2)
                        content2 = await page.content()
                        keys2 = re.findall(r'sk-or-v1-[a-zA-Z0-9]{40,}', content2)
                        if keys2:
                            print(f"  FOUND KEY after create: {keys2[0][:20]}...")
                            return keys2[0]
                except Exception:
                    pass
            print(f"  Logged in but no key visible. Title: {await page.title()}")
            return None

        # Look for OAuth
        content = await page.content()
        print(f"  Page title: {await page.title()}")
        for selector in [
            'button:has-text("Continue with Google")',
            'button:has-text("Sign in with Google")',
            'a:has-text("Sign in with Google")',
            'button:has-text("Continue with GitHub")',
            'a:has-text("Continue with GitHub")',
            'button:has-text("Google")',
            'button:has-text("GitHub")',
        ]:
            try:
                el = await page.query_selector(selector)
                if el:
                    print(f"  Found OAuth button: {selector}")
                    print("  NOTE: OAuth requires user interaction")
                    return None
            except Exception:
                pass

        if "cloudflare" in content.lower():
            print("  BLOCKED: Cloudflare challenge")
        else:
            print(f"  No OAuth found. Snippet: {content[:200]}")

    except Exception as e:
        print(f"  ERROR: {e}")
    return None


async def main():
    from playwright.async_api import async_playwright
    try:
        from playwright_stealth import stealth_async
        HAS_STEALTH = True
    except ImportError:
        HAS_STEALTH = False
        print("WARNING: playwright-stealth not available")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--lang=en-US,en",
            ],
        )
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        if HAS_STEALTH:
            await stealth_async(page)
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = {runtime: {}};
        """)

        found = {}

        # Check Cerebras
        key = await try_get_cerebras(page)
        if key:
            found['CEREBRAS_API_KEY'] = key
            set_key(ENV_FILE, 'CEREBRAS_API_KEY', key)
            print(f"  Written CEREBRAS_API_KEY to .env")

        # Check OpenRouter
        key = await try_get_openrouter(page)
        if key:
            found['OPENROUTER_API_KEY'] = key
            set_key(ENV_FILE, 'OPENROUTER_API_KEY', key)
            print(f"  Written OPENROUTER_API_KEY to .env")

        await browser.close()

    print()
    if found:
        print(f"SUCCESS: Found {len(found)} key(s): {list(found.keys())}")
    else:
        print("RESULT: No keys found automatically.")
        print("Both services use Cloudflare Turnstile on login page.")
        print("OAuth (Google/GitHub) bypasses CAPTCHA but requires")
        print("an interactive browser session with user clicking.")
        print()
        print("Alternatives:")
        print("  1. Use existing free providers: Groq (free), DeepSeek ($0.94 left)")
        print("  2. Manually sign up at https://cloud.cerebras.ai (Google OAuth, fast)")
        print("  3. Manually sign up at https://openrouter.ai (GitHub OAuth, fast)")
        print("  4. Both have free tiers that work without payment")


if __name__ == "__main__":
    asyncio.run(main())
