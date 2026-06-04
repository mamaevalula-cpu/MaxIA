#!/usr/bin/env python3
# update_state.py — writes /tmp/maxai_state.json every minute
# Updated 2026-05-31: added grok_stack status
import json, urllib.request, time, subprocess
from pathlib import Path

d = {}

# Trading bot
try:
    with urllib.request.urlopen("http://127.0.0.1:8001/status", timeout=2) as r:
        t = json.loads(r.read())
        d = {"bal": round(float(t.get("balance_usdt",0)),2),
             "pnl": round(float(t.get("daily_pnl",0)),2),
             "pos": t.get("open_positions",0),
             "bot": "LIVE" if t.get("online") else "STOP",
             "ts": time.time()}
except: pass

# Grok Stack health
grok = {}
for svc in ["ollama","grok-router","grok-webui"]:
    try:
        out = subprocess.run(["systemctl","is-active",svc+".service"],
            capture_output=True,text=True,timeout=2).stdout.strip()
        grok[svc] = out == "active"
    except: grok[svc] = False

# Grok router HTTP check
try:
    with urllib.request.urlopen("http://127.0.0.1:8088/health", timeout=2) as r:
        gh = json.loads(r.read())
        grok["router_ok"] = gh.get("status") == "ok"
        grok["ollama_ok"] = gh.get("ollama", False)
        grok["providers"] = gh.get("providers", {})
except: grok["router_ok"] = False

d["grok"] = grok
Path("/tmp/maxai_state.json").write_text(json.dumps(d))
