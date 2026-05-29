#!/usr/bin/env python3
"""weekly_email.py - Weekly performance report via Resend."""
import sys, os, json, time, urllib.request, sqlite3, subprocess
from datetime import datetime, timedelta

sys.path.insert(0, '/root/my_personal_ai')
sys.path.insert(0, '/root/venv/lib/python3.12/site-packages')
from dotenv import load_dotenv
load_dotenv('/root/my_personal_ai/.env')

RESEND_KEY = os.getenv('RESEND_API_KEY', '')
FROM_EMAIL = os.getenv('OUTREACH_FROM_EMAIL', 'audit@maxai.fyi')
TO_EMAIL   = os.getenv('OWNER_EMAIL', 'froggyinternet@gmail.com')

def send_resend(subject, html_body):
    payload = json.dumps({"from": FROM_EMAIL, "to": [TO_EMAIL],
                          "subject": subject, "html": html_body})
    cmd = ['curl','-s','-X','POST','https://api.resend.com/emails',
           '-H', f'Authorization: Bearer {RESEND_KEY}',
           '-H', 'Content-Type: application/json', '-d', payload]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    try: return json.loads(r.stdout)
    except: return {'error': r.stdout or r.stderr}

def stats():
    s = {}
    try:
        with urllib.request.urlopen("http://localhost:8090/api/status", timeout=3) as r:
            d = json.loads(r.read())
        s['mode'] = 'Paper' if d.get('paper_mode') else 'Live'
        s['bal']  = d.get('paper_balance', 10000) if d.get('paper_mode') else d.get('balance_usdt', 0)
        s['pnl']  = d.get('daily_pnl', 0)
    except: s['mode'] = 'Offline'; s['bal'] = 0; s['pnl'] = 0
    try:
        conn = sqlite3.connect('/root/my_personal_ai/data/memory.db')
        s['kb'] = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        wk = conn.execute("SELECT COUNT(*) FROM knowledge WHERE ts > ?", (time.time()-604800,)).fetchone()[0]
        s['kb_wk'] = wk; conn.close()
    except: s['kb'] = 0; s['kb_wk'] = 0
    try:
        wa = (datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d')
        leads = [json.loads(l) for l in open('/root/my_personal_ai/data/freelance_leads.jsonl')
                 if json.loads(l).get('date','') >= wa]
        s['leads'] = len(leads)
        s['top']   = sorted(leads, key=lambda x: x.get('score',0), reverse=True)[:5]
    except: s['leads'] = 0; s['top'] = []
    return s

def main():
    if not RESEND_KEY:
        print("No RESEND_API_KEY"); return
    s = stats()
    week = datetime.now().strftime('%d.%m.%Y')
    leads_li = ''.join(f"<li>[{j.get('score',0)}] {j.get('title','')[:60]}</li>" for j in s.get('top',[]))
    html = f"""<html><body style="font-family:Arial;max-width:600px;margin:0 auto">
<div style="background:linear-gradient(135deg,#667eea,#764ba2);padding:24px;border-radius:12px 12px 0 0">
<h1 style="color:white;margin:0">MaxAI Weekly Report</h1>
<p style="color:rgba(255,255,255,.8);margin:8px 0 0">Неделя до {week}</p></div>
<div style="background:#f8f9fa;padding:20px;border-radius:0 0 12px 12px;border:1px solid #e9ecef">
<h2>Торговля</h2><p>Режим: <b>{s['mode']}</b> | Баланс: <b>${s['bal']:.2f}</b> | P&L: <b>${s['pnl']:+.2f}</b></p>
<h2>База знаний</h2><p>Записей: <b>{s['kb']}</b> | +{s['kb_wk']} за неделю</p>
<h2>Фриланс лиды ({s['leads']} за неделю)</h2><ul>{leads_li}</ul>
<p><a href="http://77.90.2.171:8080">Открыть дашборд</a></p>
</div></body></html>"""
    r = send_resend(f"MaxAI Weekly | {week}", html)
    if r.get('id'): print(f"Sent: {r['id']}")
    else: print(f"Failed: {r}")

if __name__ == '__main__':
    main()
