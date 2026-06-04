#!/usr/bin/env python3
import urllib.request, json, time, re, imaplib, email as emaillib
import os, logging, base64
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [KH] %(message)s")
log = logging.getLogger("kh")
BROWSER  = "http://127.0.0.1:8096"
ENV_PATH = Path("/root/my_personal_ai/.env")
GMAIL_APP = "mgmfmgphxvxsvbdw"
EMAIL_A = "froggyinternet@gmail.com"
EMAIL_B = "jimmorrisoninlove@gmail.com"

def b(path, data=None, method=None):
    url = BROWSER + path
    m   = method or ("POST" if data is not None else "GET")
    body = json.dumps(data).encode() if data is not None else b""
    req  = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"}, method=m)
    try:
        with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())
    except Exception as e: return {"error": str(e)}

def nav(url):   log.info(f"NAV {url}"); r=b("/navigate",{"url":url}); time.sleep(3); return r
def screenshot(n):
    r=b("/screenshot",method="GET")
    if r.get("data"):
        d=Path("/root/my_personal_ai/data/screenshots"); d.mkdir(exist_ok=True)
        (d/f"{n}_{int(time.time())}.jpg").write_bytes(base64.b64decode(r["data"]))
        log.info(f"Screenshot: {n}")
def click(x,y): b("/click",{"x":x,"y":y}); time.sleep(1.0)
def enter():    b("/key",{"key":"Enter"}); time.sleep(1.5)
def fill(s,t):  return b("/fill",{"selector":s,"text":t})
def find(text=None,sel=None):
    d={"text":text} if text else {"selector":sel}; return b("/find",d)
def pi():       return b("/page/info",method="GET")
def js(c):      return b("/execute",{"code":c})
def cur():      return b("/health",method="GET").get("url","")

def save_env(k,v):
    c=ENV_PATH.read_text() if ENV_PATH.exists() else ""
    if f"{k}=" in c: c=re.sub(f"^{k}=.*",f"{k}={v}",c,flags=re.MULTILINE)
    else: c+=f"\n{k}={v}"
    ENV_PATH.write_text(c); log.info(f".env {k}={v[:25]}")

def gmail_wait(acc,kw,timeout=90):
    log.info(f"Gmail: [{kw}] timeout={timeout}s")
    t=time.time()
    while time.time()-t<timeout:
        try:
            m=imaplib.IMAP4_SSL("imap.gmail.com"); m.login(acc,GMAIL_APP); m.select("INBOX")
            _,ids=m.search(None,"UNSEEN")
            for mid in reversed((ids[0].split() or [])[-10:]):
                _,data=m.fetch(mid,"(RFC822)")
                msg=emaillib.message_from_bytes(data[0][1])
                body=""
                if msg.is_multipart():
                    for p in msg.walk():
                        if "text" in p.get_content_type(): body+=p.get_payload(decode=True).decode("utf-8","ignore")
                else: body=msg.get_payload(decode=True).decode("utf-8","ignore")
                full=str(msg.get("Subject",""))+" "+body
                if kw.lower() in full.lower():
                    urls=re.findall(r"https?://[^\s'\"<>]+",full)
                    for u in urls:
                        if any(w in u for w in ["verify","confirm","magic","login","token","activate"]):
                            m.close(); m.logout(); log.info(f"Got: {u[:80]}"); return u
            m.close(); m.logout()
        except Exception as e: log.debug(f"Gmail:{e}")
        time.sleep(12)
    return None

def harvest_fetchai():
    log.info("=== FETCH.AI AGENTVERSE ===")
    res={"platform":"fetch_ai","status":"start","key":None,"email":EMAIL_A}
    pw="MaxAI_Fetch_2026!"
    nav("https://agentverse.ai"); screenshot("fa1_home")
    nav("https://agentverse.ai/auth/signup"); screenshot("fa2_signup")
    log.info(f"URL:{cur()} Title:{pi().get('title','?')}")
    for s in ["input[type=email]","input[name=email]","input[placeholder*=email]","input:first-of-type"]:
        if fill(s,EMAIL_A).get("ok"): log.info(f"Email:{s}"); break
    for s in ["input[type=password]","input[name=password]"]:
        if fill(s,pw).get("ok"): log.info(f"Pass:{s}"); break
    screenshot("fa3_form")
    submitted=False
    for txt in ["Sign up","Create Account","Register","Continue","Submit"]:
        btn=find(text=txt)
        if "error" not in btn: click(int(btn["x"]),int(btn["y"])); time.sleep(2.5); submitted=True; break
    if not submitted: enter()
    screenshot("fa4_submit"); log.info(f"Post-submit:{cur()}")
    if any(w in cur() for w in ["verify","check","confirm"]):
        lnk=gmail_wait(EMAIL_A,"agentverse",90) or gmail_wait(EMAIL_A,"fetch",60)
        if lnk: nav(lnk); time.sleep(3); screenshot("fa5_verified"); log.info("Verified!")
        else: res.update({"status":"needs_email_verify"}); save_env("FETCH_EMAIL",EMAIL_A); save_env("FETCH_PASSWORD",pw); return res
    api_key=None
    for p in ["https://agentverse.ai/profile/api-keys","https://agentverse.ai/settings/developer","https://agentverse.ai/dashboard"]:
        nav(p); time.sleep(2)
        for txt in ["Create API Key","Generate Key","+ New Key","Add key"]:
            btn=find(text=txt)
            if "error" not in btn: click(int(btn["x"]),int(btn["y"])); time.sleep(2); screenshot("fa6_key"); break
        r2=js("const el=[...document.querySelectorAll('input,code,pre,span')].find(e=>{const t=(e.value||e.textContent||'').trim();return t.length>30&&/^[a-zA-Z0-9_\\-\\.]+$/.test(t)});return el?(el.value||el.textContent.trim()):null")
        val=r2.get("result")
        if val and val!="null" and len(val)>30: api_key=val; break
    if api_key:
        save_env("FETCH_API_KEY",api_key); save_env("FETCH_AGENT_ADDRESS","agent1q"+re.sub(r"[^a-z0-9]","",api_key.lower())[:20])
        res.update({"status":"success","key":api_key}); log.info(f"FETCH KEY:{api_key[:30]}")
    else:
        res["status"]="registered_no_key"; save_env("FETCH_EMAIL",EMAIL_A); save_env("FETCH_PASSWORD",pw)
        log.info(f"Registered. URL:{cur()}")
    screenshot("fa_done"); return res

def harvest_virtual():
    log.info("=== VIRTUAL PROTOCOL ===")
    res={"platform":"virtual_protocol","status":"start","key":None,"email":EMAIL_B}
    nav("https://app.virtuals.io"); screenshot("vp1_home")
    log.info(f"Title:{pi().get('title','?')}")
    for txt in ["Sign Up","Get Started","Launch App","Enter App","Log In"]:
        btn=find(text=txt)
        if "error" not in btn: click(int(btn["x"]),int(btn["y"])); time.sleep(2.5); screenshot("vp2_click"); break
    for s in ["input[type=email]","input[placeholder*=email]","input[name=email]"]:
        if fill(s,EMAIL_B).get("ok"): log.info("VP email filled"); enter(); time.sleep(2); screenshot("vp3_email"); break
    lnk=gmail_wait(EMAIL_B,"virtual",60)
    if lnk:
        nav(lnk); time.sleep(3); screenshot("vp4_magic"); log.info("Magic link OK")
        for ap in ["https://app.virtuals.io/developer","https://app.virtuals.io/settings"]:
            nav(ap); time.sleep(2)
            r2=js("const el=[...document.querySelectorAll('input,code,[class*=key],[class*=token]')].find(e=>{const t=(e.value||e.textContent||'').trim();return t.length>=20&&/^[a-zA-Z0-9_\\-]+$/.test(t)});return el?(el.value||el.textContent.trim()):null")
            val=r2.get("result")
            if val and val!="null": save_env("VIRTUAL_PROTOCOL_API_KEY",val); res.update({"status":"success","key":val}); log.info(f"VP KEY:{val[:25]}"); break
        if not res["key"]: res["status"]="logged_in_no_key"
    else:
        nav("https://docs.virtuals.io"); time.sleep(2); screenshot("vp5_docs")
        res.update({"status":"wallet_required","note":"Connect MetaMask in panel browser"})
        save_env("VIRTUAL_EMAIL",EMAIL_B); log.info("VP: wallet required")
    screenshot("vp_done"); return res

def finish(results):
    import redis as _r
    r=_r.from_url("redis://127.0.0.1:6379/0",decode_responses=True)
    missing=[x["platform"] for x in results if not x.get("key")]
    if missing:
        hitl={"req_id":f"hitl_keys_{int(time.time())}","type":"manual_api_key","dept":"aaas_fleet",
              "action":f"Вручную ввести API ключи: {', '.join(missing)}",
              "details":{"fetch_url":"https://agentverse.ai/profile/api-keys","virtual_url":"https://app.virtuals.io/developer",
                         "email_a":EMAIL_A,"email_b":EMAIL_B,"env_keys":["FETCH_API_KEY","VIRTUAL_PROTOCOL_API_KEY"],
                         "screenshots":"/root/my_personal_ai/data/screenshots/",
                         "how_to":"1.Открой Браузер в панели 2.Зайди на ссылки 3.Залогинься 4.Скопируй ключ 5.Сохрани в .env"},
              "state":"AWAITING_MANUAL_ACTION","ts":time.time()}
        k="swarm:hitl:queue"
        if r.type(k) not in("none","list"): r.delete(k)
        r.lpush(k,json.dumps(hitl,default=str)); log.info(f"HITL created: {missing}")
    try:
        env_c=ENV_PATH.read_text()
        tok=next((l.split("=",1)[1].strip() for l in env_c.splitlines() if l.startswith("TELEGRAM_BOT_TOKEN=")),"")
        cid=next((l.split("=",1)[1].strip() for l in env_c.splitlines() if l.startswith("TELEGRAM_OWNER_ID=")),"")
        if tok and cid:
            lines=["Harvester завершён\n"]
            for res in results:
                icon="OK" if res.get("key") else "WARN"
                lines.append(f"[{icon}] {res['platform']}: {res['status']}")
                if res.get("key"): lines.append(f"  KEY={res['key'][:30]}")
                if res.get("note"): lines.append(f"  NOTE={res['note'][:60]}")
            if missing: lines.append(f"\nНужно вручную: {', '.join(missing)}\nПанель -> Браузер")
            req=urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage",
                data=json.dumps({"chat_id":cid,"text":"\n".join(lines)}).encode(),
                headers={"Content-Type":"application/json"},method="POST")
            urllib.request.urlopen(req,timeout=6); log.info("TG sent")
    except Exception as e: log.debug(f"TG:{e}")
    Path("/root/my_personal_ai/data/key_harvest_results.json").write_text(json.dumps(results,indent=2,default=str))
    print("\n=== РЕЗУЛЬТАТ ===")
    for res in results: print(f"  {res['platform']}: {res['status']}"+(f" | KEY={res['key'][:25]}" if res.get("key") else ""))

if __name__=="__main__":
    log.info("MaxAI Key Harvester v3 — start")
    results=[harvest_fetchai(), harvest_virtual()]
    finish(results)
