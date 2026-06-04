#!/usr/bin/env python3
"""
MaxAI Real Revenue Monitor
Every 30 min: checks ALL real revenue sources, sends summary to owner.
"""
import urllib.request, json, time, logging
from pathlib import Path
from datetime import datetime, date

LOG = Path('/root/my_personal_ai/logs/revenue_monitor.log')
LOG.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [REV_MON] %(message)s',
    handlers=[logging.FileHandler(str(LOG)), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

ENV = Path('/root/my_personal_ai/.env')
REDIS_URL = 'redis://127.0.0.1:6379/0'
PANEL_API = 'http://127.0.0.1:3000'
OWNER_TG  = '1985320458'

def env_get(k):
    if not ENV.exists(): return ''
    for l in ENV.read_text().splitlines():
        if '=' in l and l.startswith(k + '='): return l.split('=', 1)[1].strip()
    return ''

def redis_conn():
    try:
        import redis as _r
        return _r.from_url(REDIS_URL, decode_responses=True)
    except: return None

def http_get(url, timeout=8):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except: return None

def tg_send(msg):
    tok = env_get('TELEGRAM_BOT_TOKEN')
    if not tok: return
    try:
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{tok}/sendMessage',
            data=json.dumps({'chat_id': OWNER_TG, 'text': msg, 'parse_mode': 'HTML',
                             'disable_web_page_preview': True}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.error(f'TG: {e}')

def get_bybit_balance(r):
    try:
        trading_data = http_get(f'{PANEL_API}/api/trading/balance')
        if trading_data:
            return float(trading_data.get('balance_usdt', 0) or 0)
    except: pass
    try:
        val = r.get('trading:balance:usdt') if r else None
        return float(val) if val else 0.0
    except: return 0.0

def get_real_payments(r):
    if not r: return [], 0.0
    try:
        raw = r.lrange('maxai:real:payments', 0, 19)
        payments = [json.loads(x) for x in raw if x]
        total = float(r.get('aaas:revenue:real_total_usd') or 0)
        return payments, total
    except: return [], 0.0

def get_kwork_stats(r):
    if not r: return {'scanned': 0, 'sent': 0, 'applied': 0}
    try:
        last = r.get('kwork:scan:last')
        applied = r.get('kwork:applied')
        scan_data = json.loads(last) if last else {}
        applied_list = json.loads(applied) if applied else []
        return {
            'scanned': scan_data.get('total', 0),
            'hot': scan_data.get('hot', 0),
            'applied_total': len(applied_list),
        }
    except: return {'scanned': 0, 'hot': 0, 'applied_total': 0}

def get_telegram_clients(r):
    if not r: return 0
    try:
        return r.llen('maxai:client:messages')
    except: return 0

def get_kwork_today_sent(r):
    """Count proposals sent today from kwork scan logs."""
    if not r: return 0
    try:
        log_file = Path('/root/my_personal_ai/logs/kwork_scan.log')
        if not log_file.exists(): return 0
        today_str = date.today().strftime('%Y-%m-%d')
        count = 0
        for line in log_file.read_text(errors='ignore').splitlines():
            if today_str in line and 'SUCCESS applied' in line:
                count += 1
        return count
    except: return 0

def run():
    log.info('=== Revenue Monitor Run ===')
    r = redis_conn()

    bybit_balance = get_bybit_balance(r)
    real_payments, real_total = get_real_payments(r)
    kwork = get_kwork_stats(r)
    tg_clients = get_telegram_clients(r)
    kwork_today = get_kwork_today_sent(r)

    # AI tasks executed today
    ai_tasks_today = 0
    if r:
        today_str = date.today().strftime('%Y-%m-%d')
        try:
            ai_tasks_today = int(r.get(f'aaas:tasks:daily:{today_str}') or 0)
        except: pass

    # Recent payments list
    payments_str = ''
    if real_payments:
        for p in real_payments[:3]:
            usd = p.get('estimated_usd', 0)
            sym = p.get('symbol', '?')
            amt = p.get('amount', 0)
            dt  = p.get('date', '?')
            payments_str += f'  • {dt}: {amt:.4f} {sym} (~${usd:.2f})\n'
    else:
        payments_str = '  Нет подтверждённых платежей\n'

    msg = (
        f'📊 <b>MaxAI Revenue Report</b>\n'
        f'{datetime.now().strftime("%Y-%m-%d %H:%M")}\n\n'
        f'<b>💰 РЕАЛЬНЫЕ АКТИВЫ:</b>\n'
        f'Bybit USDT: <b>${bybit_balance:.2f}</b>\n'
        f'Подтверждённых оплат: <b>${real_total:.4f}</b>\n\n'
        f'<b>📈 Активность за период:</b>\n'
        f'Kwork откликов сегодня: <b>{kwork_today}</b>\n'
        f'Kwork всего откликов: <b>{kwork.get("applied_total", 0)}</b>\n'
        f'Kwork найдено проектов: <b>{kwork.get("scanned", 0)}</b> (горячих: {kwork.get("hot", 0)})\n'
        f'Telegram клиентов: <b>{tg_clients}</b>\n'
        f'AI задач выполнено: <b>{ai_tasks_today}</b>\n\n'
        f'<b>💳 Последние платежи:</b>\n'
        f'{payments_str}\n'
        f'<b>Ваши кошельки:</b>\n'
        f'TRC20: <code>TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2</code>\n'
        f'ETH: <code>0x7b72d6072f973a79d13abb11769927890832cc12</code>'
    )

    tg_send(msg)
    log.info(f'Report sent. Bybit=${bybit_balance:.2f} Real=${real_total:.4f}')

    return {
        'bybit_usd': bybit_balance,
        'real_total_usd': real_total,
        'kwork_today': kwork_today,
        'tg_clients': tg_clients,
    }

if __name__ == '__main__':
    result = run()
    print(json.dumps(result, default=str))
