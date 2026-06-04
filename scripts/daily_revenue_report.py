#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Daily revenue report sender - runs at 9:00 AM via cron
import urllib.request, json, os

BASE = '/root/my_personal_ai'

def load_env():
    env = {}
    try:
        for line in open(BASE + '/.env').read().splitlines():
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return {**env, **os.environ}

ENV = load_env()
BOT_TOKEN = ENV.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID = ENV.get('TELEGRAM_CHAT_ID', '1985320458')

def api_get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None

def send_msg(text):
    if not BOT_TOKEN:
        print('No BOT_TOKEN')
        return None
    data = json.dumps({'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode()
    req = urllib.request.Request(
        'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage',
        data=data,
        headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print('Send error:', e)
        return None

rev = api_get('http://127.0.0.1:4000/api/aaas/revenue')
fleet = api_get('http://127.0.0.1:4000/api/aaas/fleet')
trading = api_get('http://127.0.0.1:8090/api/trading/balance')

lines = ['<b>📊 MaxAI Daily Revenue Report</b>', '']
if rev:
    total = rev.get('total_usd', 0)
    today = rev.get('today_usd', 0)
    monthly = rev.get('estimated_monthly_usd', 0)
    goal_pct = rev.get('goal_pct', 0)
    lines.append('💰 Total earned: <b>$' + '{:.3f}'.format(total) + '</b>')
    lines.append('📅 Today: <b>$' + '{:.3f}'.format(today) + '</b>')
    lines.append('📈 Est. monthly: <b>$' + '{:.2f}'.format(monthly) + '</b>')
    lines.append('🎯 Goal ($100): <b>' + '{:.1f}'.format(goal_pct) + '%</b>')
    by_plat = rev.get('by_platform', {})
    active_plats = {k: v for k, v in by_plat.items() if v > 0}
    if active_plats:
        lines.append('')
        lines.append('<b>By platform:</b>')
        for k, v in active_plats.items():
            lines.append('  ' + k + ': $' + '{:.3f}'.format(v))
if fleet:
    lines.append('')
    lines.append('🤖 Active agents: <b>' + str(fleet.get('active_agents', 0)) + '</b>')
    lines.append('⚡ Total spawned: <b>' + str(fleet.get('total_spawned', 0)) + '</b>')
if trading:
    bal = trading.get('balance_usdt', 0)
    pnl = trading.get('daily_pnl', 0)
    sign = '+' if pnl >= 0 else ''
    lines.append('')
    lines.append('📈 Bybit balance: <b>$' + '{:.2f}'.format(bal) + '</b>')
    lines.append('📊 Daily PnL: <b>' + sign + '{:.4f}'.format(pnl) + ' USDT</b>')

lines.append('')
lines.append('Panel: https://maxai.fyi')

msg = '\n'.join(lines)
result = send_msg(msg)
if result:
    print('Report sent: ' + str(result.get('ok')))
else:
    print('Failed to send report')
