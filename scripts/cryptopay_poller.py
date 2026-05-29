#!/usr/bin/env python3
"""CryptoPay payment poller - runs every 5 min via cron"""
import os, json, time, urllib.request, urllib.parse, sqlite3

BASE = "/root/my_personal_ai"
TOKEN = os.getenv("CRYPTOPAY_TOKEN", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = "1985320458"
API = "https://pay.crypt.bot/api"
UA = "Mozilla/5.0 CryptoPay-Poller/1.0"

if not TOKEN:
    for line in open(BASE + "/.env"):
        k, _, v = line.partition("=")
        v = v.strip().strip('"').strip("'")
        if k == "CRYPTOPAY_TOKEN": TOKEN = v
        if k == "TELEGRAM_BOT_TOKEN" and not TG_TOKEN: TG_TOKEN = v

def cpay(method, params=None):
    url = f"{API}/{method}"
    if params: url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Crypto-Pay-API-Token": TOKEN, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

def tg(msg):
    data = json.dumps({"chat_id": CHAT_ID, "text": msg}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)

try:
    r = cpay("getInvoices", {"status": "paid", "count": 10})
    if r.get("ok"):
        paid = r["result"].get("items", [])
        db_path = BASE + "/data/payments.db"
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        db = sqlite3.connect(db_path)
        db.execute("CREATE TABLE IF NOT EXISTS processed (invoice_id TEXT PRIMARY KEY, processed_at REAL)")
        for inv in paid:
            inv_id = str(inv.get("invoice_id"))
            amount = inv.get("amount")
            asset = inv.get("asset")
            payload = inv.get("payload", "")
            already = db.execute("SELECT 1 FROM processed WHERE invoice_id=?", (inv_id,)).fetchone()
            if not already:
                db.execute("INSERT INTO processed VALUES (?,?)", (inv_id, time.time()))
                db.commit()
                msg = f"NEW PAYMENT!\n\nAmount: {amount} {asset}\nPlan: {payload}\nID: {inv_id}"
                tg(msg)
                print(f"NEW PAYMENT: {amount} {asset} - {payload}")
        db.close()
    print(f"[{time.strftime("%H:%M")}] CryptoPay OK - checked {len(r.get("result",{}).get("items",[]))} paid invoices")
except Exception as e:
    print(f"Error: {e}")
