#!/usr/bin/env python3
"""
panel_js_selfheal.py
Runs every 5min via cron. Detects and auto-fixes common panel JS issues:
1. Direct 127.0.0.1 calls in panel HTML (browser can't reach them)
2. Missing proxy routes in routes.py
3. Panel not responding
"""
import subprocess, urllib.request, json, time
from pathlib import Path

LOG       = Path("/root/my_personal_ai/logs/panel_selfheal.log")
PANEL_HTML= Path("/root/my_personal_ai/dashboard/static/index.html")
ROUTES    = Path("/root/my_personal_ai/dashboard/routes.py")
TOKEN     = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT      = "1985320458"

BAD_URLS  = ["127.0.0.1:4000","127.0.0.1:8088","127.0.0.1:11434","127.0.0.1:8001"]
FIX_MAP   = [
    ("http://127.0.0.1:4000/api/swarm/status", "/api/os/swarm"),
    ("http://127.0.0.1:8088/health",           "/api/os/grok"),
    ("http://127.0.0.1:11434/api/tags",        "/api/os/models"),
    ("http://127.0.0.1:8001/positions",        "/api/os/positions"),
    ("http://127.0.0.1:8088/v1/chat/completions", "/api/os/grok_chat"),
]

PROXY_CODE = chr(10).join([
    '',
    '    @app.get("/api/os/swarm")',
    '    async def os_proxy_swarm():',
    '        import urllib.request as _ur, json as _j',
    '        try:',
    '            with _ur.urlopen("http://127.0.0.1:4000/api/swarm/status", timeout=3) as _r: return _j.loads(_r.read())',
    '        except Exception as e: return {"error": str(e), "ceo": {"cycle":0,"alerts":[],"alert_count":0}}',
    '',
    '    @app.get("/api/os/grok")',
    '    async def os_proxy_grok():',
    '        import urllib.request as _ur, json as _j',
    '        try:',
    '            with _ur.urlopen("http://127.0.0.1:8088/health", timeout=3) as _r: return _j.loads(_r.read())',
    '        except Exception as e: return {"error": str(e), "status": "down", "ollama": False, "providers": {}}',
    '',
    '    @app.get("/api/os/positions")',
    '    async def os_proxy_positions():',
    '        import urllib.request as _ur, json as _j',
    '        try:',
    '            with _ur.urlopen("http://127.0.0.1:8001/positions", timeout=3) as _r: return _j.loads(_r.read())',
    '        except Exception as e: return {"error": str(e), "positions": []}',
    '',
    '    @app.get("/api/os/models")',
    '    async def os_proxy_models():',
    '        import urllib.request as _ur, json as _j',
    '        try:',
    '            with _ur.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as _r: return _j.loads(_r.read())',
    '        except Exception as e: return {"error": str(e), "models": []}',
    '',
    '    @app.post("/api/os/grok_chat")',
    '    async def os_proxy_grok_chat(request: Request):',
    '        import urllib.request as _ur, json as _j',
    '        body = await request.body()',
    '        try:',
    '            req = _ur.Request("http://127.0.0.1:8088/v1/chat/completions",data=body,headers={"Content-Type":"application/json"},method="POST")',
    '            with _ur.urlopen(req, timeout=60) as _r: return _j.loads(_r.read())',
    '        except Exception as e: return {"choices":[{"message":{"content":"Error: "+str(e)[:60]}}]}',
])


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(f"[{ts}] {msg}")


def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data, headers={"Content-Type":"application/json"}), timeout=8)
    except Exception:
        pass


def panel_up():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8090/api/status", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def fix_html_calls():
    if not PANEL_HTML.exists():
        return 0
    html = PANEL_HTML.read_text()
    changed = 0
    for old, new in FIX_MAP:
        if old in html:
            html = html.replace(old, new)
            changed += 1
            log(f"  Fixed: {old} -> {new}")
    if changed:
        PANEL_HTML.write_text(html)
    return changed


def ensure_proxy_routes():
    if not ROUTES.exists():
        return False
    text = ROUTES.read_text()
    if '/api/os/swarm' in text:
        return False
    marker = '    @app.get("/api/status")'
    if marker not in text:
        return False
    text = text.replace(marker, PROXY_CODE + chr(10) + marker, 1)
    ROUTES.write_text(text)
    log("Re-added missing /api/os/* proxy routes")
    return True


def run():
    fixes = []

    # 1. Panel up?
    if not panel_up():
        subprocess.run(["systemctl", "restart", "personal-ai"], timeout=25)
        time.sleep(5)
        if not panel_up():
            log("CRIT: panel not responding after restart")
            tg("Panel DOWN - check personal-ai service")
            return
        fixes.append("panel restarted")

    # 2. Proxy routes in routes.py?
    if ensure_proxy_routes():
        subprocess.run(["systemctl", "restart", "personal-ai"], timeout=25)
        time.sleep(4)
        fixes.append("proxy routes restored in routes.py")

    # 3. Direct 127.0.0.1 calls in HTML?
    if PANEL_HTML.exists():
        html = PANEL_HTML.read_text()
        bad = sum(1 for url in BAD_URLS if url in html)
        if bad > 0:
            log(f"Found {bad} direct internal calls - fixing...")
            n = fix_html_calls()
            if n:
                subprocess.run(["systemctl", "restart", "personal-ai"], timeout=25)
                time.sleep(4)
                fixes.append(f"fixed {n} direct 127.0.0.1 calls in HTML")

    if fixes:
        msg = "Panel JS auto-fix:" + chr(10) + chr(10).join(fixes)
        log(msg)
        tg(msg)
    else:
        log("Panel OK - no fixes needed")


if __name__ == "__main__":
    run()
