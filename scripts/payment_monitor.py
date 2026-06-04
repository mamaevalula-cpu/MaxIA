#!/usr/bin/env python3
"""
MaxAI Real Payment Monitor
Checks TRC20 (USDT), ETH, and BTC wallets for incoming transactions.
Runs every 10 minutes via cron, alerts owner on Telegram.
"""
import urllib.request, urllib.parse, json, time, logging
from pathlib import Path
from datetime import datetime

LOG = Path('/root/my_personal_ai/logs/payment_monitor.log')
LOG.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [PAY_MONITOR] %(message)s',
    handlers=[logging.FileHandler(str(LOG)), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

ENV = Path('/root/my_personal_ai/.env')
REDIS_URL = 'redis://127.0.0.1:6379/0'

# Owner wallets
WALLETS = {
    'TRC20_USDT': 'TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2',
    'ETH_ERC20':  '0x7b72d6072f973a79d13abb11769927890832cc12',
    'BTC':        '158AEebXosZfxHY1ZVQNfTT6BHcuHqGFr4',
}

def env_get(k):
    if not ENV.exists(): return ''
    for l in ENV.read_text().splitlines():
        if '=' in l and l.startswith(k + '='): return l.split('=', 1)[1].strip()
    return ''

def http_get(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'MaxAI/1.0'})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        log.debug(f'HTTP GET {url[:60]}: {e}')
        return None

def redis_conn():
    try:
        import redis as _r
        return _r.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error(f'Redis connect: {e}')
        return None

def tg_send(msg):
    tok = env_get('TELEGRAM_BOT_TOKEN')
    cid = '1985320458'
    if not tok: return
    try:
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{tok}/sendMessage',
            data=json.dumps({'chat_id': cid, 'text': msg, 'parse_mode': 'HTML',
                             'disable_web_page_preview': True}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        urllib.request.urlopen(req, timeout=10)
        log.info('TG alert sent')
    except Exception as e:
        log.error(f'TG send: {e}')

def check_trc20(address):
    """Check TRC20 USDT transactions via TronGrid (free, no API key)."""
    url = f'https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit=20&only_confirmed=true'
    data = http_get(url)
    if not data or 'data' not in data:
        return []

    txs = []
    for tx in data.get('data', []):
        token = tx.get('token_info', {})
        symbol = token.get('symbol', '')
        if 'USDT' not in symbol and 'USDC' not in symbol:
            continue
        decimals = int(token.get('decimals', 6))
        to_addr = tx.get('to', '')
        if to_addr.lower() != address.lower():
            continue  # only incoming
        amount_raw = int(tx.get('value', 0))
        amount_usd = amount_raw / (10 ** decimals)
        tx_id = tx.get('transaction_id', '')
        ts = int(tx.get('block_timestamp', 0)) // 1000
        txs.append({
            'chain': 'TRC20',
            'symbol': symbol,
            'amount': amount_usd,
            'txid': tx_id,
            'ts': ts,
            'from': tx.get('from', ''),
        })
    return txs

def check_eth(address):
    """Check ETH/ERC20 transactions via Etherscan (free tier, no key needed for basic)."""
    url = (f'https://api.etherscan.io/api?module=account&action=tokentx'
           f'&address={address}&page=1&offset=20&sort=desc'
           f'&contractaddress=0xdAC17F958D2ee523a2206206994597C13D831ec7')  # USDT ERC20
    data = http_get(url)
    txs = []
    if data and data.get('status') == '1':
        for tx in data.get('result', []):
            if tx.get('to', '').lower() != address.lower():
                continue
            amount = int(tx.get('value', 0)) / 1e6
            txs.append({
                'chain': 'ERC20',
                'symbol': tx.get('tokenSymbol', 'USDT'),
                'amount': amount,
                'txid': tx.get('hash', ''),
                'ts': int(tx.get('timeStamp', 0)),
                'from': tx.get('from', ''),
            })

    # Also check native ETH
    url2 = (f'https://api.etherscan.io/api?module=account&action=txlist'
            f'&address={address}&page=1&offset=10&sort=desc')
    data2 = http_get(url2)
    if data2 and data2.get('status') == '1':
        for tx in data2.get('result', []):
            if tx.get('to', '').lower() != address.lower():
                continue
            value_eth = int(tx.get('value', 0)) / 1e18
            if value_eth < 0.001:
                continue
            txs.append({
                'chain': 'ETH',
                'symbol': 'ETH',
                'amount': value_eth,
                'txid': tx.get('hash', ''),
                'ts': int(tx.get('timeStamp', 0)),
                'from': tx.get('from', ''),
            })
    return txs

def check_btc(address):
    """Check BTC via Blockstream API (free)."""
    url = f'https://blockstream.info/api/address/{address}/txs'
    data = http_get(url)
    txs = []
    if not data or not isinstance(data, list):
        return txs
    for tx in data[:10]:
        tx_id = tx.get('txid', '')
        ts = tx.get('status', {}).get('block_time', 0)
        for vout in tx.get('vout', []):
            if vout.get('scriptpubkey_address', '') == address:
                amount_btc = vout.get('value', 0) / 1e8
                txs.append({
                    'chain': 'BTC',
                    'symbol': 'BTC',
                    'amount': amount_btc,
                    'txid': tx_id,
                    'ts': ts,
                    'from': 'unknown',
                })
    return txs

def get_seen_txids(r):
    raw = r.get('maxai:payments:seen_txids')
    if raw:
        try: return set(json.loads(raw))
        except: pass
    return set()

def save_seen_txids(r, seen):
    # Keep last 500 txids to avoid infinite growth
    seen_list = list(seen)[-500:]
    r.set('maxai:payments:seen_txids', json.dumps(seen_list), ex=86400 * 30)

def record_payment(r, tx, estimated_usd=None):
    """Record a real payment in Redis."""
    ts = tx.get('ts', time.time())
    record = {
        'chain': tx['chain'],
        'symbol': tx['symbol'],
        'amount': tx['amount'],
        'estimated_usd': estimated_usd or tx['amount'],
        'txid': tx['txid'],
        'from': tx['from'],
        'ts': ts,
        'date': datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M') if ts else 'unknown',
        'recorded_at': time.time(),
    }
    r.lpush('maxai:real:payments', json.dumps(record))
    r.ltrim('maxai:real:payments', 0, 199)

    # Update real revenue counter
    if estimated_usd and estimated_usd > 0:
        r.incrbyfloat('aaas:revenue:real_total_usd', estimated_usd)
        # Also track by date
        today = datetime.now().strftime('%Y-%m-%d')
        r.incrbyfloat(f'maxai:real:revenue:daily:{today}', estimated_usd)
        r.expire(f'maxai:real:revenue:daily:{today}', 86400 * 7)

    log.info(f'Recorded real payment: {tx["symbol"]} {tx["amount"]} txid={tx["txid"][:16]}')
    return record

def estimate_usd(tx):
    """Rough USD estimate for non-stablecoin assets."""
    sym = tx['symbol'].upper()
    amount = tx['amount']
    if 'USDT' in sym or 'USDC' in sym or 'DAI' in sym:
        return amount
    if sym == 'ETH':
        return amount * 3500  # rough estimate
    if sym == 'BTC':
        return amount * 65000  # rough estimate
    return amount  # fallback

def run():
    log.info('=== Payment Monitor Run ===')
    r = redis_conn()
    if not r:
        log.error('Cannot connect to Redis')
        return

    seen = get_seen_txids(r)
    # First run: seen is empty. We initialize it with current txids WITHOUT alerting,
    # so only truly NEW future transactions trigger alerts.
    is_first_run = len(seen) == 0

    if is_first_run:
        log.info('First run — seeding seen txids from existing transactions (no alerts)')

    new_payments = []

    # Check TRC20
    log.info(f'Checking TRC20: {WALLETS["TRC20_USDT"][:20]}...')
    trc20_txs = check_trc20(WALLETS['TRC20_USDT'])
    log.info(f'  Found {len(trc20_txs)} TRC20 transactions')
    for tx in trc20_txs:
        if tx['txid'] not in seen:
            seen.add(tx['txid'])
            if not is_first_run:
                usd = estimate_usd(tx)
                record_payment(r, tx, usd)
                new_payments.append(tx)
                log.info(f'  NEW TRC20: {tx["symbol"]} {tx["amount"]:.4f} (${usd:.2f})')
            else:
                log.info(f'  Seeding TRC20: {tx["txid"][:16]}...')

    # Check ETH
    log.info(f'Checking ETH: {WALLETS["ETH_ERC20"][:20]}...')
    eth_txs = check_eth(WALLETS['ETH_ERC20'])
    log.info(f'  Found {len(eth_txs)} ETH transactions')
    for tx in eth_txs:
        if tx['txid'] not in seen:
            seen.add(tx['txid'])
            if not is_first_run:
                usd = estimate_usd(tx)
                record_payment(r, tx, usd)
                new_payments.append(tx)
                log.info(f'  NEW ETH: {tx["symbol"]} {tx["amount"]:.6f} (${usd:.2f})')
            else:
                log.info(f'  Seeding ETH: {tx["txid"][:16]}...')

    # Check BTC
    log.info(f'Checking BTC: {WALLETS["BTC"][:20]}...')
    btc_txs = check_btc(WALLETS['BTC'])
    log.info(f'  Found {len(btc_txs)} BTC transactions')
    for tx in btc_txs:
        if tx['txid'] not in seen:
            seen.add(tx['txid'])
            if not is_first_run:
                usd = estimate_usd(tx)
                record_payment(r, tx, usd)
                new_payments.append(tx)
                log.info(f'  NEW BTC: {tx["symbol"]} {tx["amount"]:.8f} (${usd:.2f})')
            else:
                log.info(f'  Seeding BTC: {tx["txid"][:16]}...')

    save_seen_txids(r, seen)

    # Update last check timestamp
    r.set('maxai:payment_monitor:last_run', json.dumps({
        'ts': time.time(),
        'time': datetime.now().isoformat(),
        'new_payments': len(new_payments),
        'total_checked': len(trc20_txs) + len(eth_txs) + len(btc_txs),
    }))

    # Alert owner for new payments
    for tx in new_payments:
        usd = estimate_usd(tx)
        msg = (
            f'💰 <b>НОВЫЙ ПЛАТЁЖ!</b>\n\n'
            f'Цепочка: <b>{tx["chain"]}</b>\n'
            f'Сумма: <b>{tx["amount"]:.6f} {tx["symbol"]}</b> (~${usd:.2f})\n'
            f'От: <code>{tx["from"][:30]}...</code>\n'
            f'TxID: <code>{tx["txid"][:20]}...</code>\n'
            f'Время: {datetime.fromtimestamp(tx["ts"]).strftime("%Y-%m-%d %H:%M") if tx["ts"] else "?"}\n\n'
            f'Реальный доход подтверждён!'
        )
        tg_send(msg)

    if not new_payments:
        log.info('No new payments found')
    else:
        log.info(f'Found {len(new_payments)} new payments!')

    # Get real revenue total
    real_total = float(r.get('aaas:revenue:real_total_usd') or 0)
    log.info(f'Real revenue total: ${real_total:.4f}')

    return {
        'new_payments': len(new_payments),
        'real_total_usd': real_total,
        'trc20_checked': len(trc20_txs),
        'eth_checked': len(eth_txs),
        'btc_checked': len(btc_txs),
    }

if __name__ == '__main__':
    result = run()
    print(json.dumps(result, default=str))
