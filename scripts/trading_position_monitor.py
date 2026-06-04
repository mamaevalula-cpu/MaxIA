#!/usr/bin/env python3
# trading_position_monitor.py - monitors positions for TP/SL hits
import json, time, urllib.request, os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv('/root/my_personal_ai/.env')

TOKEN = os.getenv('CORP_BOT_TOKEN', '')
CHAT = os.getenv('TELEGRAM_CHAT_ID', '')
BOT_URL = 'http://127.0.0.1:8001'
STATE_FILE = Path('/root/my_personal_ai/data/positions_monitor.json')

def tg(msg):
    try:
        data = json.dumps({'chat_id': CHAT, 'text': msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            'https://api.telegram.org/bot'+TOKEN+'/sendMessage',
            data=data, headers={'Content-Type':'application/json'}), timeout=8)
    except Exception: pass

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: pass
    return {'positions': {}, 'last_check': 0}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2))

state = load_state()

# Get current positions
try:
    with urllib.request.urlopen(BOT_URL+'/positions', timeout=4) as r:
        data = json.loads(r.read())
    current_positions = {p['symbol']: p for p in data.get('positions', [])}
except Exception as e:
    print('Error:', e)
    import sys; sys.exit(0)

prev_positions = state.get('positions', {})

# Detect closed positions (were open, now gone)
closed = set(prev_positions.keys()) - set(current_positions.keys())
for sym in closed:
    prev = prev_positions[sym]
    pnl = float(prev.get('pnl', 0))
    sign = '+' if pnl >= 0 else ''
    emoji = 'WIN' if pnl >= 0 else 'LOSS'
    msg = chr(10).join([
        f'{emoji} Position CLOSED: {sym}',
        f'Side: {prev.get("side","?")} | Size: {prev.get("size","?")}',
        f'Entry: {prev.get("entry_price","?")} | Last PnL: {sign}{pnl:.4f} USD',
        f'',
        f'Total balance update coming...',
    ])
    tg(msg)
    print(f'CLOSED: {sym} pnl={pnl}')

# Detect new positions
new_syms = set(current_positions.keys()) - set(prev_positions.keys())
for sym in new_syms:
    pos = current_positions[sym]
    msg = chr(10).join([
        f'NEW Position: {sym}',
        f'Side: {pos.get("side","?")} | Size: {pos.get("size","?")}',
        f'Entry: {pos.get("entry_price","?")} | TP: {pos.get("take_profit","?")} | SL: {pos.get("stop_loss","?")}',
    ])
    tg(msg)
    print(f'NEW: {sym}')

# Alert on near-TP positions
for sym, pos in current_positions.items():
    try:
        pnl = float(pos.get('pnl', 0))
        entry = float(pos.get('entry_price', 0))
        mark = float(pos.get('mark_price', 0))
        tp = float(pos.get('take_profit', 0))
        if tp > 0 and entry > 0 and mark > 0:
            # For sell: mark approaching TP from above
            side = pos.get('side', '')
            if side == 'Sell':
                dist_pct = (mark - tp) / mark * 100
                if 0 < dist_pct < 2:  # Within 2% of TP
                    msg = f'NEAR TP: {sym} Sell | Mark={mark} TP={tp} | {dist_pct:.1f}% away | PnL={pnl:.3f}'
                    tg(msg)
                    print(msg)
            elif side == 'Buy':
                dist_pct = (tp - mark) / mark * 100
                if 0 < dist_pct < 2:  # Within 2% of TP
                    msg = f'NEAR TP: {sym} Buy | Mark={mark} TP={tp} | {dist_pct:.1f}% away | PnL={pnl:.3f}'
                    tg(msg)
                    print(msg)
    except Exception: pass

state['positions'] = current_positions
state['last_check'] = time.time()
save_state(state)
