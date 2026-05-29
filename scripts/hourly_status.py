#!/usr/bin/env python3
"""Sends brief hourly status to Telegram - lightweight"""
import json, time, urllib.request as ur, os
from dotenv import load_dotenv
load_dotenv('/root/my_personal_ai/.env')

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = '1985320458'

def send(text):
    if not TOKEN: return
    data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
    try:
        req = ur.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST")
        with ur.urlopen(req, timeout=8): pass
    except Exception: pass

def main():
    hour = int(time.strftime('%H'))
    if hour < 8 or hour > 23: return
    
    try:
        with ur.urlopen('http://localhost:8090/api/status', timeout=3) as r:
            t = json.loads(r.read())
        trading = t.get('trading', t)
        pnl = float(trading.get('daily_pnl_usdt', trading.get('daily_pnl', 0)))
        bal = float(trading.get('balance_usdt', t.get('balance_usdt', 0)))
        trades = int(t.get('paper_trades_today', t.get('positions_count', 0)))
        emoji = '📈' if pnl > 0 else '📉'
        send(f"{emoji} <b>Час {time.strftime('%H:00')}</b> | Баланс: <b>${bal:,.2f}</b> | PnL: {'+' if pnl>=0 else ''}${pnl:.2f} | Сделок: {trades}")
    except Exception:
        pass

if __name__ == '__main__':
    main()

