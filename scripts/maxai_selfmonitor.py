#!/usr/bin/env python3
"""MaxAI Self-Monitor v4 - smarter checks"""
import urllib.request,json,subprocess,time,re
from pathlib import Path
TOKEN="8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT="1985320458"
LOG=Path("/root/my_personal_ai/logs/maxai_selfmonitor.log")
BACKUP=None  # DISABLED: panel restoration would overwrite current version
HTML="/root/my_personal_ai/dashboard/static/index.html"

def tg(m):
    try:
        d=json.dumps({"chat_id":CHAT,"text":m}).encode()
        urllib.request.urlopen(urllib.request.Request("https://api.telegram.org/bot"+TOKEN+"/sendMessage",d,{"Content-Type":"application/json"}),timeout=5)
    except:pass

def log(m):
    open(str(LOG),"a").write("["+time.strftime("%Y-%m-%d %H:%M:%S")+"] "+str(m)+chr(10))

def chk(u,t=4):
    try:
        with urllib.request.urlopen(u,timeout=t) as r:return json.loads(r.read()),r.status
    except:return {},0

def svc(n):
    try:return subprocess.run(["systemctl","is-active",n+".service"],text=True,timeout=3,capture_output=True).stdout.strip()
    except:return "?"

def restart(n):
    try:subprocess.run(["systemctl","restart",n+".service"],timeout=20)
    except:pass

fixes=[]

# 1. Service must be active
if svc("personal-ai")!="active":
    subprocess.run(["systemctl","reset-failed","personal-ai.service"],timeout=5)
    restart("personal-ai");time.sleep(10)
    fixes.append("Restarted personal-ai")

# 2. HTTP must respond
_,code=chk("http://localhost:8090/api/status",5)
if code!=200:
    Path(HTML).write_bytes(Path(BACKUP).read_bytes())
    restart("personal-ai");time.sleep(10)
    fixes.append("HTML restored - HTTP down")

# 3. CRITICAL: window.__ST__ must be in HTML (JS works)
# Only restore if completely missing - NOT just because balance=0
try:
    with urllib.request.urlopen("http://localhost:8090/",timeout=8) as r:html=r.read().decode("utf-8")
    if "window.__ST__" not in html or "loadDash" not in html:
        Path(HTML).write_bytes(Path(BACKUP).read_bytes())
        restart("personal-ai");time.sleep(10)
        fixes.append("HTML restored - JS broken")
        tg("MaxAI ALERT: Panel JS was broken - restored from backup")
except Exception as e:
    log("check err: "+str(e))

# 4. Other services
for s in ["bybit-monitor","corp-tgbot","nginx","maxai-tgbot","ollama","grok-router","grok-webui"]:
    if svc(s)!="active":
        restart(s);fixes.append("Restarted "+s)

if fixes:
    tg("MaxAI AutoFix:"+chr(10)+"".join("- "+f+chr(10) for f in fixes))
    log("FIXED:"+str(fixes))
else:
    log("OK")
