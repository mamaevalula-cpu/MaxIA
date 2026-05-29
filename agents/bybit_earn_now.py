#!/usr/bin/env python3
"""
bybit_earn_now.py — НЕМЕДЛЕННО кладём USDT в Bybit Earn
Цель: пассивный доход с первого дня ~7-12% APY
Запустить ПРЯМО СЕЙЧАС: /root/venv/bin/python3 /root/my_personal_ai/agents/bybit_earn_now.py
"""
import json, hmac, hashlib, time, logging
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger('earn')

API_KEY    = 'O8NZsb1QOlQET3c3kH'
API_SECRET = 'Nt5ZdXPNrJvGQQg6DMeBkcDtdRpMhEybhHHQ'
TG_TOKEN   = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT    = '1985320458'
BASE       = 'https://api.bybit.com'

STATE_FILE = Path('/root/my_personal_ai/data/bybit_earn_status.json')

def tg(text):
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4096], 'parse_mode': 'HTML'}).encode()
        urlopen(Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                        data=d, headers={'Content-Type':'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def sign_get(path, params=None):
    params = params or {}
    ts = int(time.time() * 1000)
    q = '&'.join(f'{k}={v}' for k,v in sorted(params.items()))
    msg = f'{ts}{API_KEY}5000{q}' if q else f'{ts}{API_KEY}5000'
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    headers = {
        'X-BAPI-API-KEY': API_KEY, 'X-BAPI-TIMESTAMP': str(ts),
        'X-BAPI-SIGN': sig, 'X-BAPI-RECV-WINDOW': '5000',
    }
    url = f'{BASE}{path}' + (f'?{q}' if q else '')
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error('GET %s: %s', path, e)
        return {}

def sign_post(path, body):
    ts = int(time.time() * 1000)
    body_str = json.dumps(body)
    msg = f'{ts}{API_KEY}5000{body_str}'
    sig = hmac.new(API_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    headers = {
        'X-BAPI-API-KEY': API_KEY, 'X-BAPI-TIMESTAMP': str(ts),
        'X-BAPI-SIGN': sig, 'X-BAPI-RECV-WINDOW': '5000',
        'Content-Type': 'application/json',
    }
    try:
        req = Request(f'{BASE}{path}', data=body_str.encode(), headers=headers)
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except HTTPError as e:
        body_err = e.read().decode()
        log.error('POST %s HTTP %d: %s', path, e.code, body_err[:300])
        return {'retCode': e.code, 'retMsg': body_err[:200]}
    except Exception as e:
        log.error('POST %s: %s', path, e)
        return {}

def get_usdt_balance():
    r = sign_get('/v5/account/wallet-balance', {'accountType': 'UNIFIED'})
    try:
        acct = r['result']['list'][0]
        # Use account-level totalAvailableBalance (correct for UNIFIED)
        total_avail = float(acct.get('totalAvailableBalance') or 0)
        for coin in acct['coin']:
            if coin['coin'] == 'USDT':
                wallet = float(coin.get('walletBalance') or 0)
                # availableToWithdraw is empty string for UNIFIED — use account level
                avail_raw = coin.get('availableToWithdraw', '')
                available = float(avail_raw) if avail_raw and avail_raw != '' else total_avail
                return {'total': wallet, 'available': available}
    except Exception as e:
        log.error('Balance parse: %s', e)
    return {'total': 0, 'available': 0}

def get_earn_products():
    """Get available Flexible Saving products for USDT."""
    # Try different endpoints
    products = []

    # Method 1: Savings products
    r = sign_get('/v5/earn/product', {'category': 'FlexibleSaving', 'coin': 'USDT'})
    if r.get('retCode') == 0:
        items = r.get('result', {}).get('list', [])
        for item in items:
            if 'USDT' in item.get('coin', '') and item.get('status') == 'Available':
                products.append({
                    'id': item.get('productId', ''),
                    'coin': item.get('coin', ''),
                    'apy': float(item.get('estimateApr', '0%').replace('%','') or 0),
                    'min': float(item.get('minStakeAmount', 1)),
                    'source': 'FlexibleSaving',
                })
        log.info('FlexibleSaving products: %d', len(products))
    else:
        log.info('FlexibleSaving: retCode=%s retMsg=%s', r.get('retCode'), r.get('retMsg','')[:100])

    # Method 2: Bybit Savings
    r2 = sign_get('/v5/earn/product', {'category': 'Savings', 'coin': 'USDT'})
    if r2.get('retCode') == 0:
        items2 = r2.get('result', {}).get('list', [])
        for item in items2:
            if 'USDT' in item.get('coin', '') and item.get('status') == 'Available':
                products.append({
                    'id': item.get('productId', ''),
                    'coin': item.get('coin', ''),
                    'apy': float(item.get('estimateApr', '0%').replace('%','') or 0),
                    'min': float(item.get('minStakeAmount', 1)),
                    'source': 'Savings',
                })
        log.info('Savings products: %d', len(items2))

    return products

def get_current_earn_balance():
    """Check current earn holdings."""
    r = sign_get('/v5/earn/position', {'category': 'FlexibleSaving'})
    if r.get('retCode') == 0:
        items = r.get('result', {}).get('list', [])
        total = sum(float(i.get('totalAmount', 0)) for i in items if 'USDT' in i.get('coinName', ''))
        return total, items
    return 0, []

def deposit_to_earn(product_id: str, amount: float, coin: str = 'USDT') -> bool:
    """Deposit to Bybit Earn product."""
    log.info('Depositing %.2f %s to product %s', amount, coin, product_id)
    # Check if API key has Earn permission first
    r3 = sign_get('/v5/user/query-api')
    earn_perms = r3.get('result', {}).get('permissions', {}).get('Earn', [])
    if not earn_perms:
        tg(
            '<b>Bybit Earn</b>: API ключ не имеет прав Earn!\n'
            'Нужно вручную:\n'
            '1. bybit.com → API Management\n'
            '2. Ключ → Edit → Включи Earn permission\n\n'
            f'Или вручную: Finance → Earn → USDT Flexible → ${to_deposit:.0f}'
        )
        return
    r = sign_post('/v5/earn/purchase', {
        'productId': product_id,
        'amount': str(round(amount, 2)),
        'coin': coin,
        'orderType': 'Purchase',
    })
    code = r.get('retCode', -1)
    msg = r.get('retMsg', '')
    log.info('Deposit result: retCode=%d msg=%s', code, msg)
    return code == 0

def run():
    log.info('=== Bybit Earn NOW ===')

    # 1. Get balance
    bal = get_usdt_balance()
    log.info('Balance: total=%.2f available=%.2f', bal['total'], bal['available'])

    if bal['total'] == 0:
        tg('❌ Bybit Earn: не могу получить баланс. Проверь API ключи.')
        return

    # 2. Check current earn positions
    earn_total, earn_items = get_current_earn_balance()
    log.info('Already in Earn: %.2f USDT (%d positions)', earn_total, len(earn_items))

    # 3. Decide how much to deposit
    # Keep 30 USDT free for trading, deposit the rest (max 150 USDT)
    min_free = 30.0
    max_earn = 150.0

    available = bal['available']
    can_deposit = max(0, available - min_free)
    to_deposit = min(can_deposit, max_earn - earn_total)

    log.info('Available: %.2f, already earning: %.2f, to_deposit: %.2f', available, earn_total, to_deposit)

    if to_deposit < 1.0:
        msg = (
            f'🏦 <b>Bybit Earn статус</b>\n'
            f'💳 Баланс: ${bal["total"]:.2f} (свободно: ${available:.2f})\n'
            f'📈 Уже в Earn: ${earn_total:.2f}\n'
        )
        if earn_total > 0:
            daily = earn_total * 0.07 / 365
            msg += f'💰 Пассивный доход: ~${daily:.3f}/день @ 7% APY\n'
            msg += f'📅 В месяц: ~${daily*30:.2f}'
        else:
            msg += '⚠️ Нечего депонировать (нужно свободных USDT > $31)'
        tg(msg)

        # Save state
        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            'balance': bal['total'],
            'available': available,
            'in_earn': earn_total,
            'last_run': datetime.utcnow().isoformat(),
        }, indent=2))
        return

    # 4. Get earn products
    products = get_earn_products()

    if not products:
        # Try known product IDs for USDT Flexible
        log.warning('No products found via API, trying known IDs')
        # Bybit Flexible USDT Saving product IDs (may vary by account type)
        known_ids = ['Bybit01', 'USDT001', 'FlexUsdt', 'USDT_Flexible']

        tg(
            f'⚠️ <b>Bybit Earn</b>: продукты через API недоступны\n'
            f'💡 Рекомендация: вручную зайти на bybit.com → Finance → Bybit Earn\n'
            f'   и положить ${to_deposit:.2f} USDT в Flexible Savings\n'
            f'   Это даст ~${to_deposit * 0.07 / 365:.3f}/день пассивного дохода\n\n'
            f'💳 Баланс: ${bal["total"]:.2f}, свободно: ${available:.2f}'
        )

        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            'balance': bal['total'],
            'available': available,
            'in_earn': earn_total,
            'products_found': 0,
            'last_run': datetime.utcnow().isoformat(),
            'action': 'no_products',
        }, indent=2))
        return

    # Sort by APY
    products.sort(key=lambda p: p['apy'], reverse=True)
    best = products[0]
    log.info('Best product: %s APY=%.2f%% min=%.2f', best['id'], best['apy'], best['min'])

    if to_deposit < best['min']:
        tg(f'⚠️ Bybit Earn: хочу депонировать ${to_deposit:.2f} но минимум ${best["min"]:.2f}')
        return

    # 5. Deposit!
    ok = deposit_to_earn(best['id'], to_deposit)

    if ok:
        daily = to_deposit * (best['apy']/100) / 365
        monthly = daily * 30
        annual = to_deposit * (best['apy']/100)

        tg(
            f'✅ <b>Bybit Earn — депозит выполнен!</b>\n\n'
            f'💰 Задеплоено: <b>${to_deposit:.2f} USDT</b>\n'
            f'📈 APY: <b>{best["apy"]:.1f}%</b>\n'
            f'💵 Доход в день: ~<b>${daily:.3f}</b>\n'
            f'📅 Доход в месяц: ~<b>${monthly:.2f}</b>\n'
            f'📆 Доход в год: ~<b>${annual:.2f}</b>\n\n'
            f'🏦 Всего в Earn: ${earn_total + to_deposit:.2f}'
        )

        STATE_FILE.parent.mkdir(exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            'balance': bal['total'],
            'available': available - to_deposit,
            'in_earn': earn_total + to_deposit,
            'last_deposit': to_deposit,
            'last_deposit_apy': best['apy'],
            'product_id': best['id'],
            'last_run': datetime.utcnow().isoformat(),
            'action': 'deposited',
        }, indent=2))
    else:
        tg(
            f'❌ <b>Bybit Earn: ошибка депозита</b>\n'
            f'Сумма: ${to_deposit:.2f}, продукт: {best["id"]}\n'
            f'Проверь права API ключа (нужны: Spot Trading, Assets)'
        )

if __name__ == '__main__':
    run()
