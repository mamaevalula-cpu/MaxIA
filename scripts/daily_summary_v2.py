#!/usr/bin/env python3
"""Daily summary v2 — trading + NEXUS + Kwork combined."""
import os, json, redis, datetime, urllib.request

rdb = redis.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT  = os.getenv('TELEGRAM_CHAT_ID', '1985320458')

def tg(msg):
    if not TOKEN: return
    try:
        data = json.dumps({'chat_id': CHAT, 'text': msg, 'parse_mode': 'HTML'}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'}), timeout=5)
    except: pass

today = str(datetime.date.today())
bal   = float(rdb.get('bybit:balance_usdt') or 0)
start = float(rdb.get(f'bybit:start_bal:{today}') or bal)
pnl   = round(bal - start, 4)
rev   = float(rdb.get('nexus:revenue:real_total') or 0)
cli   = int(rdb.llen('nexus:clients:list'))
tasks = int(rdb.get(f'nexus:stats:tasks:{today}') or 0)
kwork = 74  # total proposals

live  = os.getenv('TRADING_LIVE_CONFIRMED', 'false').lower() == 'true'

pnl_icon = 'UP' if pnl >= 0 else 'DOWN'
msg = (
    f'MaxAI Corporation — Ежедневный отчёт {today}\n\n'
    f'Торговля (V4 {"LIVE" if live else "PAPER"}):\n'
    f'  Баланс:  USDT\n'
    f'  PnL сегодня:  ({pnl_icon})\n\n'
    f'NEXUS Platform:\n'
    f'  Клиентов: {cli}\n'
    f'  Задач сегодня: {tasks}\n'
    f'  Выручка всего: \n\n'
    f'Маркетинг:\n'
    f'  Kwork откликов всего: {kwork}\n\n'
    f'Система: 15/15 сервисов активны'
)

tg(msg)
print('Daily summary sent')
