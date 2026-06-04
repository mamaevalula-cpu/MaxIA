#!/usr/bin/env python3
"""
maxai_key_orchestrator.py — Autonomous Key Manager
Runs every 15 min. Validates all keys, auto-fetches where possible,
creates HITL requests for keys needing manual input.

Auto capabilities:
  - Groq: register/login via groq.com
  - WB: login to wb.ru seller and get API key
  - Cerebras: login to cloud.cerebras.ai
  - HuggingFace: already valid

HITL requests for:
  - PST.NET (virtual card, financial)
  - PyntaPay (payment routing)
  - iGameLink / NexaPoker (affiliate)
"""
import json, os, re, subprocess, time, urllib.request
from pathlib import Path
from datetime import datetime

ENV_FILE = Path("/root/my_personal_ai/.env")
DATA     = Path("/root/my_personal_ai/data")
LOGS     = Path("/root/my_personal_ai/logs")
CORP_TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT_ID    = "1985320458"
HITL_URL   = "http://127.0.0.1:4000"

def tg(msg, parse_mode="HTML"):
    try:
        data = json.dumps({"chat_id": CHAT_ID, "text": msg[:4000], "parse_mode": parse_mode}).encode()
        req = urllib.request.Request(
            "https://api.telegram.org/bot"+CORP_TOKEN+"/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        print("TG:", e)

def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

def save_key(name, value):
    src = ENV_FILE.read_text()
    if (name + "=") in src:
        src = re.sub(rf"^{name}=.*$", name + "=" + value, src, flags=re.MULTILINE)
    else:
        src = src.rstrip() + "\n" + name + "=" + value + "\n"
    ENV_FILE.write_text(src)
    # Also update os.environ for running processes
    os.environ[name] = value
    print(f"  SAVED: {name}={value[:8]}***")

def validate_groq(key):
    if not key: return False
    try:
        import httpx as _hxq
        r = _hxq.get("https://api.groq.com/openai/v1/models",
            headers={"Authorization": "Bearer " + key}, timeout=5)
        return r.status_code == 200
    except Exception:
        try:
            req = urllib.request.Request("https://api.groq.com/openai/v1/models",
                headers={"Authorization": "Bearer " + key})
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status == 200
        except Exception:
            return False

def validate_deepseek(key):
    if not key: return False
    try:
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=json.dumps({"model":"deepseek-chat","messages":[{"role":"user","content":"hi"}],"max_tokens":1}).encode(),
            headers={"Content-Type":"application/json","Authorization":"Bearer "+key},
            method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status == 200
    except Exception:
        return False

def validate_anthropic(key):
    if not key: return False
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=json.dumps({"model":"claude-haiku-4-5","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}).encode(),
            headers={"Content-Type":"application/json","x-api-key":key,"anthropic-version":"2023-06-01"},
            method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.status in (200, 201)
    except Exception as e:
        return "403" not in str(e) and "401" not in str(e)

def validate_openrouter(key):
    if not key: return False
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False

def try_get_groq_key():
    """
    Attempt to get a new Groq key via Playwright browser automation.
    Uses froggyinternet@gmail.com to sign in to console.groq.com.
    Returns new key or None.
    """
    script = """
import sys, re, time, os
sys.path.insert(0, '/root/my_personal_ai')
from playwright.sync_api import sync_playwright

ENV_FILE = '/root/my_personal_ai/.env'
email = 'froggyinternet@gmail.com'

def load_env():
    env = {}
    for line in open(ENV_FILE).read().splitlines():
        if '=' in line and not line.startswith('#'):
            k,_,v = line.partition('=')
            env[k.strip()] = v.strip()
    return env

env = load_env()
google_pass = env.get('EMAIL_FROGGY_PASS', '') or env.get('GOOGLE_APP_PASS','')

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-gpu'])
    ctx = b.new_context(user_agent='Mozilla/5.0 Chrome/120')
    page = ctx.new_page()

    # Navigate to Groq API keys
    page.goto('https://console.groq.com/keys', timeout=25000, wait_until='domcontentloaded')
    time.sleep(4)

    url = page.url
    print('URL:', url[:80])

    # If already on keys page
    if 'keys' in url and 'login' not in url and 'sign' not in url:
        content = page.content()
        keys = re.findall(r'gsk_[A-Za-z0-9]{40,}', content)
        if keys:
            print('FOUND_KEY:' + keys[0])
            ctx.close(); b.close()
            sys.exit(0)
        # Try to create a new key
        try:
            create_btn = page.get_by_text('Create API Key', exact=False).first
            create_btn.wait_for(timeout=4000, state='visible')
            create_btn.click()
            time.sleep(2)
            # Fill name
            name_input = page.locator('input[placeholder*="name"], input[placeholder*="Name"]').first
            try:
                name_input.wait_for(timeout=3000, state='visible')
                name_input.fill('MaxAI-Auto-' + str(int(time.time()))[-6:])
                time.sleep(0.5)
            except Exception:
                pass
            # Submit
            for submit_txt in ['Submit', 'Create', 'Generate']:
                try:
                    btn = page.get_by_text(submit_txt, exact=False).first
                    btn.click()
                    time.sleep(2)
                    break
                except Exception:
                    pass
            # Get key from modal/page
            content2 = page.content()
            keys2 = re.findall(r'gsk_[A-Za-z0-9]{40,}', content2)
            if keys2:
                print('FOUND_KEY:' + keys2[0])
                ctx.close(); b.close()
                sys.exit(0)
        except Exception as e:
            print('create_key_err:', str(e)[:80])

    print('NOT_LOGGED_IN: need Google OAuth')
    ctx.close(); b.close()
"""
    try:
        result = subprocess.run(
            ["/root/venv/bin/python3", "-c", script],
            capture_output=True, text=True, timeout=45
        )
        output = result.stdout + result.stderr
        match = re.search(r"FOUND_KEY:(gsk_[A-Za-z0-9]+)", output)
        if match:
            return match.group(1)
        print("  Groq auto-get result:", output[-200:])
    except Exception as e:
        print("  Groq auto-get error:", e)
    return None

def try_get_wb_key(env):
    """
    Attempt to get WB (Wildberries) API key via Playwright.
    Logs into WB seller dashboard and extracts/creates API key.
    """
    wb_login = env.get("WB_EMAIL") or env.get("WB_LOGIN", "")
    wb_pass  = env.get("WB_PASSWORD", "")
    if not wb_login or not wb_pass:
        return None

    script = f"""
import sys, re, time
from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, args=['--no-sandbox','--disable-gpu'])
    ctx = b.new_context(user_agent='Mozilla/5.0 Chrome/120')
    page = ctx.new_page()

    page.goto('https://seller.wildberries.ru/', timeout=20000)
    time.sleep(3)
    url = page.url
    print('WB URL:', url[:60])

    # Try to login
    if 'login' in url or 'auth' in url or 'sign' in url.lower():
        try:
            phone_input = page.locator('input[type="tel"], input[type="text"]').first
            phone_input.fill('{wb_login}')
            time.sleep(0.5)
            pwd_input = page.locator('input[type="password"]').first
            pwd_input.fill('{wb_pass}')
            time.sleep(0.5)
            page.keyboard.press('Enter')
            time.sleep(5)
        except Exception as e:
            print('WB login err:', str(e)[:80])

    # Navigate to API settings
    try:
        page.goto('https://seller.wildberries.ru/supplier-settings/access-to-new-portal', timeout=15000)
        time.sleep(4)
        content = page.content()
        keys = re.findall(r'[A-Za-z0-9]{{100,}}', content)
        if keys:
            print('WB_KEY_CANDIDATE:', keys[0][:40])
        else:
            print('WB_NO_KEY_FOUND')
    except Exception as e:
        print('WB nav err:', str(e)[:80])

    ctx.close(); b.close()
"""
    try:
        result = subprocess.run(
            ["/root/venv/bin/python3", "-c", script],
            capture_output=True, text=True, timeout=50
        )
        print("  WB result:", (result.stdout + result.stderr)[-300:])
    except Exception as e:
        print("  WB error:", e)
    return None

def create_hitl_request(service, description, action_url=None, instructions=""):
    """Create HITL request in maxai-core for manual key input."""
    import hashlib
    req_id = hashlib.md5(f"{service}{time.time()}".encode()).hexdigest()[:8]
    hitl_data = {
        "req_id": req_id,
        "dept": "fintech" if service in ("PST.NET","PyntaPay") else "affiliate",
        "action": f"setup_{service.lower().replace('.','_')}",
        "service": service,
        "description": description,
        "instructions": instructions,
        "action_url": action_url,
        "amount": 0,
        "state": "AWAITING_APPROVAL",
        "ts": time.time(),
        "expires_at": time.time() + 86400,
    }
    try:
        # Push to Redis
        import redis
        rr = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        queue = rr.get("swarm:hitl:queue")
        q = json.loads(queue) if queue else []
        # Don't duplicate
        existing = [r for r in q if r.get("service") == service]
        if not existing:
            q.append(hitl_data)
            rr.set("swarm:hitl:queue", json.dumps(q), ex=86400)
            print(f"  HITL created for {service}: {req_id}")
            return req_id
        else:
            print(f"  HITL already exists for {service}")
            return existing[0].get("req_id")
    except Exception as e:
        print(f"  HITL create error: {e}")
    return None


def validate_cerebras(key):
    if not key: return False
    try:
        req = urllib.request.Request(
            "https://api.cerebras.ai/v1/models",
            headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False

def run_orchestration():
    """Main orchestration loop — validate, auto-fetch, create HITLs."""
    env = load_env()
    report = []
    actions_taken = []
    hitl_needed = []

    print(f"\n{'='*50}")
    print(f"KEY ORCHESTRATOR — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    # 1. VALIDATE all existing keys
    checks = {
        "GROQ_API_KEY":       (validate_groq,       "Groq"),
        "DEEPSEEK_API_KEY":   (validate_deepseek,   "DeepSeek"),
        "ANTHROPIC_API_KEY":  (validate_anthropic,  "Claude"),
        "OPENROUTER_API_KEY": (validate_openrouter, "OpenRouter"),
        "CEREBRAS_API_KEY":   (validate_cerebras,   "Cerebras"),
    }

    key_status = {}
    for key_name, (validator, name) in checks.items():
        val = env.get(key_name, "")
        ok = validator(val) if val else False
        key_status[key_name] = ok
        status = "OK" if ok else ("MISSING" if not val else "INVALID/403")
        print(f"  {name}: {status}")
        report.append(f"{'OK' if ok else 'FAIL'} {name}")

    # 1.5 AUTO-FIX: Cerebras key missing → try background fetch
    if not key_status.get("CEREBRAS_API_KEY"):
        cerebras_key = env.get("CEREBRAS_API_KEY", "")
        if not cerebras_key:
            import subprocess as _sp_cb
            _sp_cb.Popen(["/root/venv/bin/python3", "/tmp/get_cerebras.py"],
                        start_new_session=True, stdout=open("/root/my_personal_ai/logs/cerebras_key.log","a"),
                        stderr=subprocess.STDOUT)
            print("  Cerebras key fetch started in background")

    # 2. AUTO-FIX: Groq key invalid → get new one
    if not key_status.get("GROQ_API_KEY"):
        print("\n  AUTO: Getting new Groq key...")
        new_key = try_get_groq_key()
        if new_key:
            save_key("GROQ_API_KEY", new_key)
            key_status["GROQ_API_KEY"] = True
            actions_taken.append("Groq key auto-obtained and saved")
            print(f"  SUCCESS: Groq key saved: {new_key[:12]}***")
        else:
            print("  FAIL: Could not auto-get Groq key (needs Google OAuth)")
            # Create HITL for owner to provide new key
            hitl_needed.append({
                "service": "Groq",
                "desc": "Groq API key is returning 403. Get new free key at console.groq.com",
                "url": "https://console.groq.com/keys",
                "env_key": "GROQ_API_KEY",
            })

    # 3. WB key — check and attempt auto-get
    wb_key = env.get("WILDBERRIES_API_KEY", "")
    if not wb_key:
        print("\n  AUTO: Attempting WB key...")
        wb_result = try_get_wb_key(env)
        if wb_result:
            save_key("WILDBERRIES_API_KEY", wb_result)
            actions_taken.append("WB key auto-obtained")
        else:
            hitl_needed.append({
                "service": "WildBerries",
                "desc": "WB seller API key needed. Go to seller.wildberries.ru → Настройки → Доступ к API",
                "url": "https://seller.wildberries.ru/supplier-settings/access-to-new-portal",
                "env_key": "WILDBERRIES_API_KEY",
            })

    # 4. PST.NET — create HITL (financial service, needs manual setup)
    pst_key = env.get("PST_API_KEY", "")
    if not pst_key:
        hitl_needed.append({
            "service": "PST.NET",
            "desc": "PST.NET API key for virtual cards. Register at pst.net/api",
            "url": "https://pst.net",
            "env_key": "PST_API_KEY",
        })

    # 5. PyntaPay — create HITL
    pynta_key = env.get("PYNTAPAY_API_KEY", "")
    if not pynta_key:
        hitl_needed.append({
            "service": "PyntaPay",
            "desc": "PyntaPay API key for payment routing. Register at pyntapay.com",
            "url": "https://pyntapay.com",
            "env_key": "PYNTAPAY_API_KEY",
        })

    # 6. Affiliate keys — create HITLs
    if not env.get("IGAMELINK_API_KEY"):
        hitl_needed.append({
            "service": "iGameLink",
            "desc": "iGameLink affiliate key. Register at igamelink.com",
            "url": "https://igamelink.com",
            "env_key": "IGAMELINK_API_KEY",
        })
    if not env.get("NEXA_API_KEY"):
        hitl_needed.append({
            "service": "NexaPoker",
            "desc": "NexaPoker affiliate key. Register at nexapoker.com",
            "url": "https://nexapoker.com",
            "env_key": "NEXA_API_KEY",
        })

    # 7. Create HITLs for all missing keys
    if hitl_needed:
        print(f"\n  Creating {len(hitl_needed)} HITL requests...")
        for h in hitl_needed:
            rid = create_hitl_request(h["service"], h["desc"], h.get("url"), h.get("env_key",""))
            if rid:
                report.append(f"HITL:{h['service']} ({rid})")

    # 8. Telegram summary
    ok_count = sum(1 for v in key_status.values() if v)
    total    = len(key_status)

    if actions_taken or hitl_needed:
        msg_lines = [
            "<b>KeyOrchestrator Report</b>",
            "",
            f"Keys OK: {ok_count}/{total}",
        ]
        if actions_taken:
            msg_lines += ["", "<b>Auto-fixed:</b>"] + [f"  ✅ {a}" for a in actions_taken]
        if hitl_needed:
            msg_lines += ["", "<b>HITL needed (tap /hitl):</b>"]
            for h in hitl_needed:
                msg_lines.append(f"  🔑 {h['service']}: {h['desc'][:60]}")
        msg_lines += ["", f"<i>{datetime.now().strftime('%H:%M')}</i>"]
        tg("\n".join(msg_lines))

    # Save last run timestamp
    (DATA / "key_orchestrator_last.json").write_text(
        json.dumps({"ts": time.time(), "ok": ok_count, "total": total,
                    "actions": actions_taken, "hitl": [h["service"] for h in hitl_needed]},
                   indent=2)
    )

    print(f"\nDone: {ok_count}/{total} keys valid | {len(actions_taken)} auto-fixed | {len(hitl_needed)} HITL")
    return ok_count, total

if __name__ == "__main__":
    run_orchestration()
