#!/usr/bin/env python3
# groq_auto_key.py - Get Groq API key via browser automation
import re, time, json, subprocess
from pathlib import Path

ENV_FILE = Path("/root/my_personal_ai/.env")

def load_env():
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k,_,v = line.partition("="); env[k.strip()] = v.strip()
    return env

def save_key(name, value):
    src = ENV_FILE.read_text()
    if (name+"=") in src:
        import re as _r
        src = _r.sub(rf"^{name}=.*$", name+"="+value, src, flags=_r.MULTILINE)
    else:
        src = src.rstrip()+chr(10)+name+"="+value+chr(10)
    ENV_FILE.write_text(src)
    print(f"SAVED: {name}={value[:12]}***")

def get_groq_key():
    env = load_env()
    gmail = env.get("GOOGLE_EMAIL_AUTH","froggyinternet@gmail.com")
    gmail_pass = env.get("EMAIL_FROGGY_PASS","Froggy!2345")
    app_pass = (env.get("GOOGLE_APP_PASS") or "").replace(" ","")

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-gpu"])
        ctx = b.new_context(user_agent="Mozilla/5.0 Chrome/120", viewport={"width":1280,"height":800})
        page = ctx.new_page()
        try:
            page.goto("https://console.groq.com/keys", timeout=30000, wait_until="domcontentloaded")
            time.sleep(5)
            url = page.url
            print("URL:", url[:70])

            # Already logged in
            if "keys" in url and "login" not in url.lower() and "sign" not in url.lower():
                keys = re.findall(r"gsk_[A-Za-z0-9]{40,}", page.content())
                if keys: ctx.close(); b.close(); return keys[0]
                # Try create new key
                try:
                    page.get_by_text("Create API Key", exact=False).first.click()
                    time.sleep(2)
                    try: page.locator("input").first.fill("MaxAI-"+str(int(time.time())%10000))
                    except: pass
                    for txt in ["Submit","Create","Generate","Save"]:
                        try: page.get_by_text(txt,exact=False).first.click(); time.sleep(2); break
                        except: pass
                    keys2 = re.findall(r"gsk_[A-Za-z0-9]{40,}", page.content())
                    if keys2: ctx.close(); b.close(); return keys2[0]
                except Exception as e: print("create:", e)

            # Find Google sign-in button
            for sel in ["button:has-text('Continue with Google')","button:has-text('Sign in with Google')"]:
                try: page.locator(sel).first.wait_for(timeout=3000,state="visible"); page.locator(sel).first.click(); time.sleep(4); break
                except: pass

            for step in range(5):
                cur = page.url
                if "accounts.google.com" in cur:
                    try:
                        ei = page.locator("input[type='email']").first
                        ei.wait_for(timeout=4000,state="visible"); ei.fill(gmail); page.keyboard.press("Enter"); time.sleep(3)
                    except: pass
                    try:
                        pi = page.locator("input[type='password']").first
                        pi.wait_for(timeout=4000,state="visible"); pi.fill(gmail_pass); page.keyboard.press("Enter"); time.sleep(4)
                    except: pass
                if "groq.com" in page.url: break
                time.sleep(3)

            if "groq.com" in page.url:
                page.goto("https://console.groq.com/keys", timeout=15000); time.sleep(4)
                keys = re.findall(r"gsk_[A-Za-z0-9]{40,}", page.content())
                if keys: ctx.close(); b.close(); return keys[0]
            print("Final URL:", page.url[:80])
        except Exception as e: print("Error:", e)
        ctx.close(); b.close()
    return None

if __name__ == "__main__":
    print("Getting Groq key via browser...")
    key = get_groq_key()
    if key:
        save_key("GROQ_API_KEY", key)
        print("SUCCESS:", key[:16]+"***")
        env = load_env()
        try:
            import urllib.request, json as _j
            d = _j.dumps({"chat_id":env.get("TELEGRAM_CHAT_ID",""),"text":"Groq key obtained: "+key[:12]+"***"}).encode()
            urllib.request.urlopen(urllib.request.Request("https://api.telegram.org/bot"+env.get("CORP_BOT_TOKEN","")+"/sendMessage",data=d,headers={"Content-Type":"application/json"}),timeout=8)
        except: pass
    else:
        print("FAILED. Get manually: https://console.groq.com/keys")
        print("Then send to bot: GROQ_API_KEY=gsk_...")
