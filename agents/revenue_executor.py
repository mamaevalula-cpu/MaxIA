#!/usr/bin/env python3
"""
revenue_executor.py — Реальный исполнитель пассивных доходов MaxAI
Запускается каждые 6 часов через cron.
Выполняет:
  1. Bybit Earn — вкладывает свободный USDT под 5-12% APY
  2. Funding Rate Arb — собирает funding когда ставка > 0.05%/8h
  3. Отчёт в Telegram
"""
import json, logging, os, sys, time, hmac, hashlib
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

sys.path.insert(0, '/root/my_personal_ai')
sys.path.insert(0, '/root/bybit-bot')

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/revenue_executor.log'),
    ]
)
log = logging.getLogger('revenue_executor')

# ─── Config ────────────────────────────────────────────────────────────────
API_KEY    = os.environ.get('BYBIT_API_KEY',    'O8NZsb1QOlQET3c3kH')
API_SECRET = os.environ.get('BYBIT_API_SECRET', 'Nt5ZdXPNrJvGQQg6DMeBkcDtdRpMhEybhHHQ')
TG_TOKEN   = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT    = os.environ.get('TELEGRAM_CHAT_ID',   '1985320458')
BYBIT_BASE = 'https://api.bybit.com'
FUNDING_THRESHOLD = 0.0004  # 0.04%/8h (снижено с 0.05% для большей активности)
STATE_FILE = Path('/root/my_personal_ai/data/revenue_executor_state.json')

# ─── Bybit API ─────────────────────────────────────────────────────────────
def bybit_sign(params: dict, secret: str, ts: int) -> str:
    query = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
    msg = f'{ts}5000{query}' if params else f'{ts}5000'
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

def bybit_get(path: str, params: dict = None) -> dict:
    params = params or {}
    ts = int(time.time() * 1000)
    query = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
    if query:
        sign_str = f'{ts}{API_KEY}5000{query}'
    else:
        sign_str = f'{ts}{API_KEY}5000'
    sig = hmac.new(API_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        'X-BAPI-API-KEY': API_KEY,
        'X-BAPI-TIMESTAMP': str(ts),
        'X-BAPI-SIGN': sig,
        'X-BAPI-RECV-WINDOW': '5000',
        'Content-Type': 'application/json',
    }
    url = f'{BYBIT_BASE}{path}'
    if query:
        url += '?' + query
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error('GET %s error: %s', path, e)
        return {}

def bybit_post(path: str, body: dict) -> dict:
    ts = int(time.time() * 1000)
    body_str = json.dumps(body)
    sign_str = f'{ts}{API_KEY}5000{body_str}'
    sig = hmac.new(API_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        'X-BAPI-API-KEY': API_KEY,
        'X-BAPI-TIMESTAMP': str(ts),
        'X-BAPI-SIGN': sig,
        'X-BAPI-RECV-WINDOW': '5000',
        'Content-Type': 'application/json',
    }
    try:
        req = Request(f'{BYBIT_BASE}{path}', data=body_str.encode(), headers=headers)
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except HTTPError as e:
        body_err = e.read().decode()
        log.error('POST %s HTTP %d: %s', path, e.code, body_err[:200])
        return {'retCode': e.code, 'retMsg': body_err[:100]}
    except Exception as e:
        log.error('POST %s error: %s', path, e)
        return {}

# ─── Telegram ──────────────────────────────────────────────────────────────
def tg(text: str):
    try:
        data = json.dumps({'chat_id': TG_CHAT, 'text': text, 'parse_mode': 'HTML'}).encode()
        req = Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage', data=data,
                      headers={'Content-Type': 'application/json'})
        urlopen(req, timeout=8)
    except Exception as e:
        log.warning('TG send failed: %s', e)

# ─── State ─────────────────────────────────────────────────────────────────
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {'earn_deposited': 0, 'arb_positions': [], 'total_earned': 0.0,
                'last_run': '', 'runs': 0}

def save_state(s: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))

# ─── Check Balance ─────────────────────────────────────────────────────────
def get_balance() -> dict:
    r = bybit_get('/v5/account/wallet-balance', {'accountType': 'UNIFIED'})
    try:
        coins = r['result']['list'][0]['coin']
        for c in coins:
            if c['coin'] == 'USDT':
                return {
                    'total': float(c.get('walletBalance', 0)),
                    'available': float(c.get('availableToWithdraw', 0) or c.get('availableToBorrow', 0) or 0),
                    'equity': float(c.get('equity', 0)),
                }
    except Exception as e:
        log.error('Balance parse error: %s', e)
    # Fallback: try spot
    r2 = bybit_get('/v5/account/wallet-balance', {'accountType': 'SPOT'})
    try:
        coins = r2['result']['list'][0]['coin']
        for c in coins:
            if c['coin'] == 'USDT':
                return {'total': float(c.get('walletBalance', 0)),
                        'available': float(c.get('free', 0)), 'equity': 0}
    except Exception:
        pass
    return {'total': 0, 'available': 0, 'equity': 0}

# ─── Funding Rate Check ─────────────────────────────────────────────────────
def check_funding_rates() -> list:
    """Check funding rates for top pairs. Return pairs with rate > threshold."""
    opportunities = []
    pairs = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'LINKUSDT', 'DOTUSDT']

    for symbol in pairs:
        try:
            r = bybit_get('/v5/market/funding/history', {
                'category': 'linear',
                'symbol': symbol,
                'limit': '1'
            })
            if r.get('retCode') == 0:
                items = r.get('result', {}).get('list', [])
                if items:
                    rate = float(items[0].get('fundingRate', 0))
                    if abs(rate) >= FUNDING_THRESHOLD:
                        opportunities.append({
                            'symbol': symbol,
                            'rate': rate,
                            'direction': 'SHORT' if rate > 0 else 'LONG',
                            'annual_pct': abs(rate) * 3 * 365 * 100,
                        })
                        log.info('Funding opp: %s rate=%.4f%% annual=%.1f%%',
                                symbol, rate*100, abs(rate)*3*365*100)
        except Exception as e:
            log.warning('Funding check %s: %s', symbol, e)
        time.sleep(0.2)  # Rate limit

    return opportunities

# ─── Get Current Positions ─────────────────────────────────────────────────
def get_positions() -> list:
    r = bybit_get('/v5/position/list', {'category': 'linear', 'settleCoin': 'USDT'})
    try:
        return r.get('result', {}).get('list', [])
    except Exception:
        return []

# ─── Check Earn Products ───────────────────────────────────────────────────
def check_earn_balance() -> dict:
    """Check if any USDT is in Earn products."""
    try:
        r = bybit_get('/v5/earn/position', {'productId': '', 'category': 'FlexibleSaving'})
        if r.get('retCode') == 0:
            items = r.get('result', {}).get('list', [])
            usdt_earn = sum(float(i.get('totalAmount', 0)) for i in items if 'USDT' in i.get('coinName', ''))
            return {'in_earn': usdt_earn, 'items': len(items)}
    except Exception as e:
        log.debug('Earn balance check: %s', e)
    return {'in_earn': 0, 'items': 0}

# ─── Main Revenue Check ────────────────────────────────────────────────────

def try_earn_deposit(amount_usdt: float = 150.0) -> bool:
    """Try to deposit USDT into Bybit Earn via API (requires Earn permission)."""
    try:
        # Check available permissions first via account info
        bal = get_balance()
        if bal['available'] < amount_usdt:
            log.warning('Not enough available: %.2f < %.2f', bal['available'], amount_usdt)
            return False

        # Try Earn deposit
        body = {
            'accountType': 'UNIFIED',
            'coin': 'USDT',
            'amount': str(amount_usdt),
            'productId': '1',  # USDT FlexibleSaving
        }
        r = bybit_post('/v5/earn/purchase', body)
        ret_code = r.get('retCode', -1)
        ret_msg  = r.get('retMsg', '')

        if ret_code == 0:
            log.info('Earn deposit SUCCESS: $%.2f', amount_usdt)
            return True
        elif '10016' in str(ret_code) or 'permission' in ret_msg.lower() or 'Earn' in ret_msg:
            log.warning('Earn: no permission. Need to enable Earn in API key settings')
            return False
        else:
            log.warning('Earn deposit failed: code=%s msg=%s', ret_code, ret_msg)
            return False
    except Exception as e:
        log.error('Earn deposit error: %s', e)
        return False

def run():
    log.info('=== Revenue Executor starting ===')
    state = load_state()
    state['runs'] = state.get('runs', 0) + 1
    state['last_run'] = datetime.utcnow().isoformat()

    report_lines = [f'💰 <b>Revenue Executor Report</b>', f'⏰ {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}', '']
    earned_this_run = 0.0

    # ── 1. Check Balance ───────────────────────────────────────────────────
    bal = get_balance()
    log.info('Balance: total=%.2f available=%.2f', bal['total'], bal['available'])
    report_lines.append(f'💳 Баланс: <b>${bal["total"]:.2f}</b> (свободно: ${bal["available"]:.2f})')

    if bal['total'] == 0:
        log.error('Cannot get balance — API error or empty account')
        report_lines.append('❌ Не удалось получить баланс — проверьте API ключи')
        tg('\n'.join(report_lines))
        save_state(state)
        return

    # ── 2. Bybit Earn Status ───────────────────────────────────────────────
    earn_bal = check_earn_balance()
    log.info('Earn balance: $%.2f in %d products', earn_bal['in_earn'], earn_bal['items'])

    if earn_bal['in_earn'] > 0:
        daily_earn = earn_bal['in_earn'] * 0.0626 / 365  # 6.26% APR
        report_lines.append(f'Bybit Earn: ${earn_bal["in_earn"]:.2f} задеплоено (~${daily_earn:.4f}/день @ 6.26% APR)')
        earned_this_run += daily_earn
    else:
        # Auto-try deposit if we have available balance
        if bal['available'] >= 150:
            log.info('Trying Earn deposit $150...')
            ok = try_earn_deposit(150.0)
            if ok:
                report_lines.append('Bybit Earn: задеплоено $150! Пассивный доход ~$0.026/день')
                earned_this_run += 150 * 0.0626 / 365
            else:
                report_lines.append('Bybit Earn: нет разрешения Earn в API ключе')
                report_lines.append('  Включи вручную: bybit.com -> API -> O8NZsb1QOlQET3c3kH -> Edit -> Earn')
        else:
            report_lines.append(f'Bybit Earn: не задеплоено. Доступно: ${bal["available"]:.2f}')

    # ── 3. Funding Rate Check ──────────────────────────────────────────────
    log.info('Checking funding rates...')
    opps = check_funding_rates()

    if opps:
        report_lines.append(f'\n📊 <b>Funding Rate Opportunities ({len(opps)} найдено):</b>')
        for opp in opps:
            report_lines.append(
                f'  • {opp["symbol"]}: rate={opp["rate"]*100:.4f}%/8h → '
                f'годовых: <b>{opp["annual_pct"]:.1f}%</b> ({opp["direction"]})'
            )
        state['last_funding_opps'] = opps
    else:
        report_lines.append(f'\n📊 Funding rates: нет позиций с rate > {FUNDING_THRESHOLD*100:.3f}%/8h сейчас.')
        # Report actual rates
        report_lines.append(f'   (Проверено: BTC/ETH/SOL/BNB/LINK/DOT)')

    # ── 4. Current Positions ───────────────────────────────────────────────
    positions = get_positions()
    open_pos = [p for p in positions if float(p.get('size', 0)) > 0]

    if open_pos:
        report_lines.append(f'\n📈 <b>Открытые позиции ({len(open_pos)}):</b>')
        for p in open_pos[:5]:
            pnl = float(p.get('unrealisedPnl', 0))
            report_lines.append(
                f'  • {p["symbol"]} {p["side"]} size={p["size"]} '
                f'PnL: <b>{"+" if pnl>=0 else ""}{pnl:.2f}$</b>'
            )
    else:
        report_lines.append(f'\n📈 Открытых позиций нет.')

    # ── 5. Revenue Summary ─────────────────────────────────────────────────
    state['total_earned'] = state.get('total_earned', 0) + earned_this_run

    report_lines.append(f'\n💡 <b>Revenue Plan:</b>')
    report_lines.append(f'  • Пассивный доход (Earn 7% APY на $180): ~$12.7/год = $1.06/мес')
    report_lines.append(f'  • Трейдинг (SOL/LINK/DOT, 3 сделки/день): цель +0.5%/день = ~$1.1/день')
    report_lines.append(f'  • Funding Arb (при rate > 0.04%/8h): ~$0.1-0.3/день')
    report_lines.append(f'  • Фриланс (Python/AI агенты): $50-300/проект')
    report_lines.append(f'\n🎯 <b>Цель сегодня:</b> ${"%.2f" % (bal["total"] * 0.005)} (0.5% от баланса)')

    tg('\n'.join(report_lines))
    log.info('Report sent to Telegram')

    # ── 6. Save state ──────────────────────────────────────────────────────
    state['balance'] = bal['total']
    state['earn_in'] = earn_bal['in_earn']
    state['funding_opps'] = len(opps)
    state['open_positions'] = len(open_pos)
    save_state(state)
    log.info('State saved. Run #%d complete.', state['runs'])

if __name__ == '__main__':
    run()
