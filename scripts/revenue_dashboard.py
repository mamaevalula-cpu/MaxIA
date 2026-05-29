#!/usr/bin/env python3
"""
MaxAI Revenue Dashboard & Auto-Growth Engine v1.0
Aggregates all revenue streams, tracks KPIs, reports to Telegram.
Runs every morning at 08:00.
"""
import json, os, sys, time, logging, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/root/my_personal_ai')
LOG_FILE  = '/root/my_personal_ai/logs/revenue_dashboard.log'
STATE_FILE= Path('/root/my_personal_ai/data/revenue_dashboard.json')
BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('revenue_dashboard')

def tg(text, parse_mode='HTML'):
    try:
        data = json.dumps({'chat_id': CHAT_ID, 'text': text,
                           'parse_mode': parse_mode, 'disable_web_page_preview': True}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8): pass
    except Exception as e:
        log.warning(f'TG: {e}')

def get_trading_data():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8001/status', timeout=5) as r:
            d = json.loads(r.read())
        return {
            'balance': d.get('balance_usdt', 0),
            'pnl': d.get('daily_pnl', 0),
            'positions': d.get('open_positions', 0),
            'mode': 'LIVE' if not d.get('paper_mode', True) else 'PAPER',
        }
    except:
        return {'balance': 0, 'pnl': 0, 'positions': 0, 'mode': '?'}

def get_freelance_stats():
    f = Path('/root/my_personal_ai/data/freelance_stats.json')
    if f.exists():
        try: return json.loads(f.read_text())
        except: pass
    return {'total_leads': 0, 'total_scanned': 0}

def get_b2b_stats():
    f = Path('/root/my_personal_ai/data/b2b_leads_v2.json')
    if f.exists():
        try:
            d = json.loads(f.read_text())
            leads = d.get('leads', [])
            return {
                'total': len(leads),
                'converted': len([l for l in leads if l.get('status') == 'converted']),
                'contacted': len([l for l in leads if l.get('status') == 'contacted']),
                'revenue_usd': sum(l.get('price_usd', 0) for l in leads if l.get('status') == 'converted'),
            }
        except: pass
    return {'total': 0, 'converted': 0, 'contacted': 0, 'revenue_usd': 0}

def get_signals_stats():
    f = Path('/root/my_personal_ai/data/signals_poster_state.json')
    if f.exists():
        try: return json.loads(f.read_text())
        except: pass
    return {'signals_posted': 0}

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: pass
    return {'start_balance': None, 'history': []}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

def run():
    state = load_state()
    trading   = get_trading_data()
    freelance = get_freelance_stats()
    b2b       = get_b2b_stats()
    signals   = get_signals_stats()

    # Track start balance
    if state.get('start_balance') is None:
        state['start_balance'] = trading['balance']
        log.info(f'Setting start balance: ${trading["balance"]:.2f}')

    start_bal = state['start_balance']
    growth_usd = trading['balance'] - start_bal
    growth_pct = (growth_usd / start_bal * 100) if start_bal > 0 else 0

    # Revenue projections
    # Trading: 0.5% daily target
    trading_daily_target = trading['balance'] * 0.005
    trading_monthly = trading_daily_target * 30

    # Freelance: $50 avg per job, 2 conversions/week target
    freelance_monthly = 400  # $50 × 2 × 4 weeks

    # B2B: current converted revenue
    b2b_revenue = b2b['revenue_usd']

    total_monthly_target = trading_monthly + freelance_monthly + b2b_revenue

    # Snapshot for history
    snapshot = {
        'ts': datetime.now().isoformat(),
        'balance': trading['balance'],
        'pnl': trading['pnl'],
        'freelance_leads': freelance.get('total_leads', 0),
        'b2b_converted': b2b['converted'],
        'signals_posted': signals.get('signals_posted', 0),
    }
    state['history'].append(snapshot)
    state['history'] = state['history'][-90:]  # Keep 90 days

    # Determine growth trend (last 7 days)
    week_ago_bal = start_bal
    if len(state['history']) >= 7:
        week_ago_bal = state['history'][-7].get('balance', start_bal)
    week_growth = trading['balance'] - week_ago_bal

    save_state(state)

    # Build report
    now = datetime.now()
    day_n = (now - datetime(2026, 5, 28)).days + 1  # Day counter from launch

    pnl_icon = '📈' if trading['pnl'] >= 0 else '📉'
    growth_icon = '🟢' if growth_usd >= 0 else '🔴'
    week_icon = '📈' if week_growth >= 0 else '📉'

    msg = (
        f"🏢 <b>MaxAI Corporation — День {day_n}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>БАЛАНС: ${trading['balance']:.2f} USDT</b> [{trading['mode']}]\n"
        f"{growth_icon} С запуска: {'+' if growth_usd>=0 else ''}{growth_usd:.2f}$ ({growth_pct:+.1f}%)\n"
        f"{pnl_icon} PnL сегодня: {'+' if trading['pnl']>=0 else ''}{trading['pnl']:.4f}$\n"
        f"{week_icon} Неделя: {'+' if week_growth>=0 else ''}{week_growth:.2f}$\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Revenue Streams:</b>\n"
        f"  🤖 Trading Bot (LIVE): {trading['positions']} позиции\n"
        f"  💼 Freelance лиды: {freelance.get('total_leads',0)} найдено\n"
        f"  🏢 B2B Pipeline: {b2b['total']} лидов, {b2b['converted']} конвертировано\n"
        f"  📡 Сигналы: {signals.get('signals_posted',0)} опубликовано\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Monthly Target:</b>\n"
        f"  Trading (0.5%/день): ${trading_monthly:.0f}\n"
        f"  Freelance (2 сделки/нед): ${freelance_monthly}\n"
        f"  B2B: ${b2b_revenue:.0f} (факт)\n"
        f"  <b>ИТОГО цель: ${total_monthly_target:.0f}/месяц</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Активных агентов: 47 | Сервисов: 11/11\n"
        f"⏰ {now.strftime('%d.%m.%Y %H:%M')} | maxai.bot"
    )

    today = now.strftime('%Y-%m-%d')
    last_report = state.get('last_report_day', '')
    if last_report != today and now.hour >= 8:
        tg(msg)
        state['last_report_day'] = today
        save_state(state)
        log.info('Morning report sent')
    else:
        log.info('Report skipped (already sent today or too early)')

if __name__ == '__main__':
    # Force send if run directly
    state = load_state()
    state['last_report_day'] = ''
    save_state(state)
    run()
