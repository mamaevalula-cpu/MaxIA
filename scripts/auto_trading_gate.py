#!/usr/bin/env python3
"""
auto_trading_gate.py — Autonomous paper→live trading gate.
Runs every 6 hours. Checks criteria, notifies via Telegram.
If user approves, enables live trading automatically.
"""
import sys, os, json, time, urllib.request, logging
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/root/my_personal_ai')
sys.path.insert(0, '/root/venv/lib/python3.12/site-packages')
from dotenv import load_dotenv
load_dotenv('/root/my_personal_ai/.env')
load_dotenv('/root/bybit-bot/.env', override=True)

LOG = '/root/my_personal_ai/logs/auto_trading_gate.log'
CHECKPOINT = '/root/my_personal_ai/data/paper_trading_checkpoint.json'
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = os.getenv('TELEGRAM_CHAT_ID', '')

logging.basicConfig(filename=LOG, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

CRITERIA = {
    'min_hours':    48,
    'min_win_rate': 0.55,
    'max_drawdown': 5.0,
    'min_trades':   15,
}

def tg_send(text, reply_markup=None):
    payload = {'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
        data=data, headers={'Content-Type': 'application/json'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error('Telegram error: %s', e)
        return {}

def get_paper_status():
    try:
        with urllib.request.urlopen('http://localhost:8090/api/status', timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error('Monitor offline: %s', e)
        return {}

def enable_live_trading():
    """Enable live trading: update .env files and restart bybit-monitor."""
    import subprocess
    # Update both .env files
    for env_file in ['/root/bybit-bot/.env', '/root/my_personal_ai/.env']:
        try:
            with open(env_file) as f:
                content = f.read()
            content = content.replace(
                'TRADING_LIVE_CONFIRMED=false',
                'TRADING_LIVE_CONFIRMED=true'
            )
            with open(env_file, 'w') as f:
                f.write(content)
            log.info('Updated %s', env_file)
        except Exception as e:
            log.error('Failed to update %s: %s', env_file, e)
    # Restart monitor
    subprocess.run(['systemctl', 'restart', 'bybit-monitor'], timeout=15)
    log.info('bybit-monitor restarted in LIVE mode')

def check_and_notify():
    chk = {}
    try:
        with open(CHECKPOINT) as f:
            chk = json.load(f)
    except Exception:
        log.warning('No checkpoint found')
        return

    # Skip if already live
    live_conf = os.getenv('TRADING_LIVE_CONFIRMED', 'false').lower() == 'true'
    if live_conf:
        log.info('Already in live mode, skipping')
        return

    s = get_paper_status()
    if not s:
        return

    hours = (time.time() - chk.get('start_ts', time.time())) / 3600
    win_rate  = float(s.get('win_rate', 0))
    pnl       = float(s.get('daily_pnl', 0))
    trades    = int(s.get('paper_trades_today', 0))
    balance   = float(s.get('paper_balance', 10000))
    drawdown  = max(0.0, (10000 - balance) / 10000 * 100)

    log.info('Check: %.1fh run, wr=%.0f%%, dd=%.1f%%, trades=%d, pnl=%.2f',
             hours, win_rate*100, drawdown, trades, pnl)

    passes = (
        hours >= CRITERIA['min_hours'] and
        win_rate >= CRITERIA['min_win_rate'] and
        drawdown <= CRITERIA['max_drawdown'] and
        trades >= CRITERIA['min_trades']
    )

    # Every 6h send status update
    emoji = '✅' if passes else '⏳'
    msg = (
        f'<b>{emoji} Paper Trading Update</b>\n\n'
        f'⏱ Время: <b>{hours:.1f}h</b> / 48h\n'
        f'📈 Win rate: <b>{win_rate*100:.0f}%</b> (мин. 55%)\n'
        f'💰 PnL: <b>${pnl:+.2f}</b>\n'
        f'📊 Сделок: <b>{trades}</b> (мин. 15)\n'
        f'📉 Drawdown: <b>{drawdown:.1f}%</b> (макс. 5%)\n'
        f'💵 Реальный баланс Bybit: <b>$50.17</b>\n\n'
    )

    if passes:
        msg += (
            '🟢 <b>ВСЕ КРИТЕРИИ ВЫПОЛНЕНЫ!</b>\n'
            'Включить live торговлю с $50?\n'
            '⚠️ Риск: 2% на сделку = $1 макс.'
        )
        markup = json.dumps({'inline_keyboard': [[
            {'text': '✅ ДА — включить live', 'callback_data': 'enable_live_trading'},
            {'text': '❌ НЕТ — ещё подождать', 'callback_data': 'keep_paper'}
        ]]})
        tg_send(msg, markup)
        log.info('READY: sent approval request to Telegram')
    else:
        remaining = max(0, CRITERIA['min_hours'] - hours)
        msg += f'⏳ Ещё ждём: {remaining:.0f}h до готовности'
        tg_send(msg)
        log.info('Not ready yet: %.1fh remaining', remaining)

if __name__ == '__main__':
    check_and_notify()
