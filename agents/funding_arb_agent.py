#!/usr/bin/env python3
"""
funding_arb_agent.py — Funding Rate Arbitrage Agent
Зарабатывает на funding rate: когда ставка > 0.03%/8h — открываем хедж.
Стратегия: Long spot + Short futures = нейтральная позиция + сбор funding.
Или просто SHORT когда funding очень высокий (лонги платят шортам).

Запуск: /root/venv/bin/python3 /root/my_personal_ai/agents/funding_arb_agent.py
"""
import json, hmac, hashlib, time, logging
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('funding_arb')

API_KEY    = 'O8NZsb1QOlQET3c3kH'
API_SECRET = 'Nt5ZdXPNrJvGQQg6DMeBkcDtdRpMhEybhHHQ'
TG_TOKEN   = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT    = '1985320458'
BASE       = 'https://api.bybit.com'
STATE_FILE = Path('/root/my_personal_ai/data/funding_arb_state.json')

# Only enter if funding is really high
ENTRY_THRESHOLD = 0.0003   # 0.03%/8h = 32.85% annual
PAIRS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'DOGEUSDT',
         'XRPUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT', 'ADAUSDT']

def tg(text):
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4096], 'parse_mode': 'HTML'}).encode()
        urlopen(Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                        data=d, headers={'Content-Type':'application/json'}), timeout=8)
    except Exception: pass

def api_get(path, params=None):
    params = params or {}
    ts = int(time.time() * 1000)
    q = '&'.join(f'{k}={v}' for k,v in sorted(params.items()))
    msg = f'{ts}{API_KEY}5000{q}' if q else f'{ts}{API_KEY}5000'
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    headers = {'X-BAPI-API-KEY': API_KEY, 'X-BAPI-TIMESTAMP': str(ts),
               'X-BAPI-SIGN': sig, 'X-BAPI-RECV-WINDOW': '5000'}
    url = f'{BASE}{path}' + (f'?{q}' if q else '')
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def get_funding_rates() -> list:
    """Get current funding rates for all pairs."""
    results = []
    for symbol in PAIRS:
        r = api_get('/v5/market/tickers', {'category': 'linear', 'symbol': symbol})
        try:
            item = r.get('result', {}).get('list', [{}])[0]
            rate = float(item.get('fundingRate', 0))
            next_time = item.get('nextFundingTime', '')
            price = float(item.get('lastPrice', 0))
            results.append({
                'symbol': symbol,
                'rate': rate,
                'rate_pct': rate * 100,
                'annual_pct': abs(rate) * 3 * 365 * 100,
                'next_funding_time': next_time,
                'price': price,
                'direction': 'SHORT_pays_LONG' if rate < 0 else 'LONG_pays_SHORT',
            })
        except Exception:
            pass
        time.sleep(0.1)
    return sorted(results, key=lambda x: abs(x['rate']), reverse=True)

def get_balance():
    r = api_get('/v5/account/wallet-balance', {'accountType': 'UNIFIED'})
    try:
        for c in r['result']['list'][0]['coin']:
            if c['coin'] == 'USDT':
                return float(c.get('walletBalance', 0))
    except Exception: pass
    return 0

def run():
    log.info('=== Funding Arb Agent ===')

    # Get all funding rates
    rates = get_funding_rates()

    if not rates:
        tg('❌ Funding Arb: не удалось получить данные')
        return

    # Report top opportunities
    lines = [
        '📊 <b>Funding Rate Monitor</b>',
        f'⏰ {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}',
        '',
        '<b>Топ возможности (годовых):</b>',
    ]

    opportunities = []
    for r in rates[:10]:
        icon = '🔥' if abs(r['rate']) >= ENTRY_THRESHOLD else '📊'
        arrow = '↓ SHORT wins' if r['rate'] > 0 else '↑ LONG wins'
        lines.append(
            f'{icon} <b>{r["symbol"]}</b>: {r["rate_pct"]:+.4f}%/8h '
            f'= {r["annual_pct"]:.1f}% годовых ({arrow})'
        )
        if abs(r['rate']) >= ENTRY_THRESHOLD:
            opportunities.append(r)

    if opportunities:
        lines.append('')
        lines.append(f'⚡ <b>Высокие ставки ({len(opportunities)}):</b>')
        for opp in opportunities:
            if opp['rate'] > 0:
                # Longs paying shorts — go SHORT
                lines.append(
                    f'  💰 {opp["symbol"]}: открой SHORT {opp["price"]:.2f}\n'
                    f'     Лонги платят: {opp["rate_pct"]:.4f}%/8h = '
                    f'${100 * opp["rate"]:.4f}/8h на $100'
                )
            else:
                # Shorts paying longs — go LONG
                lines.append(
                    f'  💰 {opp["symbol"]}: открой LONG {opp["price"]:.2f}\n'
                    f'     Шорты платят: {abs(opp["rate_pct"]):.4f}%/8h = '
                    f'${100 * abs(opp["rate"]):.4f}/8h на $100'
                )

        # Estimate potential
        bal = get_balance()
        if bal > 10:
            trade_size = min(bal * 0.1, 50)  # 10% or $50 max per arb
            best = opportunities[0]
            earn_per_8h = trade_size * abs(best['rate'])
            earn_day = earn_per_8h * 3
            lines.append('')
            lines.append(f'💡 Потенциал при ${trade_size:.0f} в лучшей позиции:')
            lines.append(f'   ${earn_per_8h:.4f}/8h = ${earn_day:.3f}/день')
    else:
        lines.append('')
        lines.append(f'📉 Нет ставок выше {ENTRY_THRESHOLD*100:.3f}%/8h прямо сейчас')
        lines.append('⏳ Ставки обычно растут перед крупными движениями')

    tg('\n'.join(lines))

    # Save state
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps({
        'last_run': datetime.utcnow().isoformat(),
        'top_rates': rates[:5],
        'opportunities': opportunities,
    }, indent=2, default=str))

    log.info('Done. Top rate: %s at %.4f%%/8h',
             rates[0]['symbol'] if rates else 'N/A',
             rates[0]['rate']*100 if rates else 0)

if __name__ == '__main__':
    run()

class FundingArbAgent:
    """Wrapper class for funding arbitrage — collects funding rates when > 0.05%/8h."""
    def __init__(self):
        self.name = "funding_arb"

    def run_once(self):
        """Execute one funding arb cycle."""
        run()

    def get_top_rates(self, n: int = 5) -> list:
        """Return top N symbols by funding rate."""
        rates = get_funding_rates()
        return rates[:n] if rates else []

    @property
    def balance(self) -> float:
        """Return current USDT balance."""
        return get_balance()
