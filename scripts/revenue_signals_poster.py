#!/usr/bin/env python3
"""
MaxAI Trading Signals Poster v1.0
Publishes real trading signals from the bot to Telegram channel.
Revenue: subscribers pay for premium signals (via Stars / crypto).
"""
import json, os, time, logging, urllib.request
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('signals_poster')

TRADING_URL = 'http://127.0.0.1:8001'
BOT_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID     = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')
# Public channel for free signals (use your channel @username or ID)
CHANNEL_ID  = os.environ.get('SIGNALS_CHANNEL_ID', CHAT_ID)

STATE_FILE  = Path('/root/my_personal_ai/data/signals_poster_state.json')

def tg(chat_id, text, parse_mode='HTML'):
    try:
        data = json.dumps({'chat_id': chat_id, 'text': text,
                           'parse_mode': parse_mode, 'disable_web_page_preview': True}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except Exception as e:
        log.warning(f'TG send error: {e}')
        return {}

def get_trading_status():
    try:
        with urllib.request.urlopen(f'{TRADING_URL}/status', timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def get_positions():
    try:
        with urllib.request.urlopen(f'{TRADING_URL}/positions', timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {}

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: pass
    return {'last_signal': {}, 'signals_posted': 0, 'total_pnl': 0.0}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2))

def post_daily_report(st, pos_data):
    """Post daily summary to channel."""
    bal = st.get('balance_usdt', 0)
    pnl = st.get('daily_pnl', 0)
    positions = pos_data.get('positions', [])
    mode = '🔴 LIVE' if not st.get('paper_mode', True) else '🟡 PAPER'
    strategies = st.get('active_strategies', [])

    pnl_icon = '📈' if pnl >= 0 else '📉'
    pnl_str = f'+${pnl:.4f}' if pnl >= 0 else f'-${abs(pnl):.4f}'

    pos_lines = []
    for p in positions:
        side_icon = '🟢 LONG' if p.get('side') == 'Buy' else '🔴 SHORT'
        pnl_p = p.get('pnl', 0)
        pnl_p_str = f'+${pnl_p:.2f}' if pnl_p >= 0 else f'-${abs(pnl_p):.2f}'
        pos_lines.append(
            f"  • {p.get('symbol','?')} {side_icon} {p.get('size','?')} @ ${p.get('entry_price',0):.2f} "
            f"PnL: {pnl_p_str}"
        )

    text = (
        f"🤖 <b>MaxAI Trading — Дневной отчёт</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: <b>${bal:.2f} USDT</b> {mode}\n"
        f"{pnl_icon} Daily PnL: <b>{pnl_str} USDT</b>\n"
        f"📊 Стратегии: {', '.join(strategies) or '—'}\n"
        f"📂 Позиций: {len(positions)}\n"
    )
    if pos_lines:
        text += "━━━━━━━━━━━━━━━━━━━━\n"
        text += "📍 <b>Открытые позиции:</b>\n"
        text += '\n'.join(pos_lines) + '\n'

    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')} UTC+3\n"
        f"🔗 Подписаться на сигналы: @MaxAI_Signals\n"
        f"💼 Заказать бота: @hyperion_engine_bot"
    )
    return tg(CHANNEL_ID, text)

def post_signal(signal, st):
    """Post a new trading signal to channel."""
    symbol  = signal.get('symbol', '?')
    action  = signal.get('action', '?')
    strategy= signal.get('strategy', '?')
    strength= signal.get('strength', 0)
    reason  = signal.get('reason', '')
    price   = signal.get('price', 0)

    action_icon = '🟢 LONG' if action in ('BUY', 'LONG', 'buy', 'long') else '🔴 SHORT'
    strength_bars = '█' * min(int(strength * 10), 10)
    strength_pct = int(strength * 100)

    text = (
        f"📡 <b>MaxAI Signal</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🪙 <b>{symbol}</b> {action_icon}\n"
        f"📈 Стратегия: <b>{strategy}</b>\n"
        f"💪 Сила сигнала: {strength_bars} {strength_pct}%\n"
        f"💡 Причина: {reason[:120]}\n"
    )
    if price:
        text += f"💲 Цена входа: ~${price:.4f}\n"

    text += (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>Не является финансовым советом. Торгуйте осознанно.</i>\n"
        f"🔗 Premium сигналы: @MaxAI_Signals | бот: @hyperion_engine_bot"
    )
    return tg(CHANNEL_ID, text)

def run():
    state = load_state()
    st = get_trading_status()
    pos_data = get_positions()

    if 'error' in st:
        log.warning(f'Trading API error: {st["error"]}')
        return

    now = datetime.now()

    # Post daily report at 09:00
    last_report_day = state.get('last_report_day', '')
    today_str = now.strftime('%Y-%m-%d')
    if last_report_day != today_str and now.hour >= 9:
        log.info('Posting daily report')
        result = post_daily_report(st, pos_data)
        if result.get('ok'):
            state['last_report_day'] = today_str
            state['signals_posted'] = state.get('signals_posted', 0) + 1
            log.info('Daily report posted OK')

    # Check for new signal
    last_sig = st.get('last_signal', {})
    last_sig_ts = last_sig.get('ts', 0)
    prev_sig_ts = state.get('last_signal', {}).get('ts', 0)

    if last_sig and last_sig_ts and last_sig_ts > prev_sig_ts:
        log.info(f'New signal detected: {last_sig.get("symbol")} {last_sig.get("action")}')
        # Only post signals with strength > 0.6
        if last_sig.get('strength', 0) > 0.6:
            result = post_signal(last_sig, st)
            if result.get('ok'):
                state['last_signal'] = last_sig
                state['signals_posted'] = state.get('signals_posted', 0) + 1
                log.info(f'Signal posted OK — total posted: {state["signals_posted"]}')
        else:
            state['last_signal'] = last_sig
            log.info(f'Signal too weak ({last_sig.get("strength", 0):.2f}), skipping')

    save_state(state)
    log.info(f'Done. Signals posted total: {state.get("signals_posted", 0)}')

if __name__ == '__main__':
    run()
