#!/usr/bin/env python3
"""
daily_revenue_report.py — Ежедневный отчёт о доходах MaxAI
Запускается каждый день в 08:00.
Собирает данные со всех источников дохода и отправляет в Telegram.
"""
import json, logging, os, sys, time, hmac, hashlib, sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen, Request

sys.path.insert(0, '/root/my_personal_ai')
sys.path.insert(0, '/root/bybit-bot')

Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/daily_revenue.log'),
    ]
)
log = logging.getLogger('daily_revenue')

API_KEY    = 'O8NZsb1QOlQET3c3kH'
API_SECRET = 'Nt5ZdXPNrJvGQQg6DMeBkcDtdRpMhEybhHHQ'
TG_TOKEN   = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT    = '1985320458'
BYBIT_BASE = 'https://api.bybit.com'
STATE_FILE = Path('/root/my_personal_ai/data/daily_revenue_state.json')

def tg(text: str):
    try:
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4096], 'parse_mode': 'HTML'}).encode()
        req = Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                      data=data, headers={'Content-Type': 'application/json'})
        urlopen(req, timeout=10)
        log.info('TG sent')
    except Exception as e:
        log.error('TG error: %s', e)

def bybit_get(path: str, params: dict = None) -> dict:
    params = params or {}
    ts = int(time.time() * 1000)
    query = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
    sign_str = f'{ts}{API_KEY}5000{query}' if query else f'{ts}{API_KEY}5000'
    sig = hmac.new(API_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        'X-BAPI-API-KEY': API_KEY,
        'X-BAPI-TIMESTAMP': str(ts),
        'X-BAPI-SIGN': sig,
        'X-BAPI-RECV-WINDOW': '5000',
    }
    url = f'{BYBIT_BASE}{path}' + (f'?{query}' if query else '')
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error('Bybit GET %s: %s', path, e)
        return {}

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {
            'start_balance': 221.12,
            'start_date': '2026-05-24',
            'total_pnl': 0.0,
            'best_day': 0.0,
            'worst_day': 0.0,
            'trading_days': 0,
        }

def save_state(s: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))


def get_bybit_summary() -> dict:
    result = {'balance': 0, 'daily_pnl': 0, 'weekly_pnl': 0, 'positions': 0, 'trades_today': 0}

    # Balance
    r = bybit_get('/v5/account/wallet-balance', {'accountType': 'UNIFIED'})
    try:
        coins = r['result']['list'][0]['coin']
        for c in coins:
            if c['coin'] == 'USDT':
                result['balance'] = float(c.get('walletBalance', 0))
                break
    except Exception:
        pass

    # Bot status
    try:
        req = Request('http://127.0.0.1:8001/status')
        with urlopen(req, timeout=5) as r2:
            bot = json.loads(r2.read())
            result['daily_pnl'] = float(bot.get('daily_pnl', 0))
            result['trades_today'] = int(bot.get('trades_today', 0))
    except Exception:
        pass

    # Risk data
    try:
        req = Request('http://127.0.0.1:8001/risk')
        with urlopen(req, timeout=5) as r3:
            risk = json.loads(r3.read())
            result['weekly_pnl'] = float(risk.get('week_pnl', 0))
            result['weekly_remaining'] = float(risk.get('weekly_remaining_usdt', 0))
    except Exception:
        pass

    # Positions
    r4 = bybit_get('/v5/position/list', {'category': 'linear', 'settleCoin': 'USDT'})
    try:
        positions = r4.get('result', {}).get('list', [])
        result['positions'] = len([p for p in positions if float(p.get('size', 0)) > 0])
    except Exception:
        pass

    # Today's closed trades PnL from journal
    try:
        conn = sqlite3.connect('/root/bybit-bot/data/journal.db')
        today = datetime.utcnow().strftime('%Y-%m-%d')
        ts_start = time.mktime(datetime.strptime(today, '%Y-%m-%d').timetuple())
        cur = conn.execute(
            "SELECT COUNT(*), SUM(pnl) FROM orders WHERE ts > ? AND status='filled'",
            (ts_start,)
        )
        row = cur.fetchone()
        conn.close()
        result['trades_today_db'] = row[0] or 0
        result['pnl_today_db'] = float(row[1] or 0)
    except Exception:
        result['trades_today_db'] = 0
        result['pnl_today_db'] = 0

    return result


def get_kwork_summary() -> dict:
    try:
        state = json.loads(Path('/root/my_personal_ai/data/kwork_state.json').read_text())
        return {'applied': state.get('total_applied', 0), 'won': state.get('won', 0),
                'earned_rub': state.get('total_earned_rub', 0)}
    except Exception:
        return {'applied': 0, 'won': 0, 'earned_rub': 0}

def get_freelance_leads() -> int:
    try:
        count = 0
        lf = Path('/root/my_personal_ai/data/freelance_leads.jsonl')
        if lf.exists():
            today = datetime.utcnow().strftime('%Y-%m-%d')
            for line in lf.read_text().splitlines():
                try:
                    d = json.loads(line)
                    if today in str(d.get('ts', '')):
                        count += 1
                except Exception:
                    pass
        return count
    except Exception:
        return 0


def run():
    log.info('=== Daily Revenue Report ===')
    state = load_state()
    now = datetime.utcnow()

    bybit = get_bybit_summary()
    kwork = get_kwork_summary()
    freelance_today = get_freelance_leads()

    # Calculate overall PnL
    start_bal = state.get('start_balance', 221.12)
    current_bal = bybit['balance'] or start_bal
    total_change = current_bal - start_bal
    total_pct = (total_change / start_bal * 100) if start_bal > 0 else 0

    days_running = (now - datetime.strptime(state.get('start_date', '2026-05-24'), '%Y-%m-%d')).days + 1
    state['trading_days'] = state.get('trading_days', 0) + 1

    lines = [
        f'📊 <b>MaxAI Daily Report — {now.strftime("%d.%m.%Y")}</b>',
        f'',
        f'━━━━ 💰 BYBIT TRADING ━━━━',
        f'💳 Баланс: <b>${current_bal:.2f}</b>',
        f'📈 Сегодня: <b>{"+" if bybit["daily_pnl"] >= 0 else ""}{bybit["daily_pnl"]:.3f}$</b>',
        f'📆 За неделю: <b>{"+" if bybit["weekly_pnl"] >= 0 else ""}{bybit["weekly_pnl"]:.3f}$</b>',
        f'🔄 Сделок сегодня (БД): {bybit.get("trades_today_db", 0)} (PnL: ${bybit.get("pnl_today_db", 0):.3f})',
        f'📊 Открытых позиций: {bybit["positions"]}',
        f'⚠️ Недельный бюджет: ${bybit.get("weekly_remaining", 0):.2f} осталось',
        f'',
        f'━━━━ 💼 ФРИЛАНС ━━━━',
        f'🔍 Kwork откликов всего: {kwork["applied"]}',
        f'🏆 Выиграно проектов: {kwork["won"]}',
        f'💵 Заработано на Kwork: {kwork["earned_rub"]:,}₽',
        f'📧 HN лидов сегодня: {freelance_today}',
        f'',
        f'━━━━ 📈 ИТОГО ━━━━',
        f'🚀 Дней работы: {days_running}',
        f'💰 Изменение баланса: {"+" if total_change >= 0 else ""}{total_change:.3f}$ ({total_pct:+.2f}%)',
        f'🎯 Цель сегодня: ${current_bal * 0.005:.2f} (+0.5%)',
        f'',
        f'━━━━ 🤖 АГЕНТЫ ━━━━',
    ]

    # Check agent statuses
    agent_files = {
        'bybit_earn': '/root/my_personal_ai/data/bybit_earn_status.json',
        'revenue_exec': '/root/my_personal_ai/data/revenue_executor_state.json',
        'kwork': '/root/my_personal_ai/data/kwork_state.json',
    }
    for name, f in agent_files.items():
        try:
            d = json.loads(Path(f).read_text())
            last = d.get('last_run', 'никогда')
            lines.append(f'  • {name}: последний запуск {last[:16]}')
        except Exception:
            lines.append(f'  • {name}: нет данных')

    lines += [
        f'',
        f'⏰ Следующий отчёт: завтра в 08:00 UTC',
    ]

    tg('\n'.join(lines))

    # Update state
    state['last_balance'] = current_bal
    state['last_report'] = now.isoformat()
    if bybit['daily_pnl'] > state.get('best_day', 0):
        state['best_day'] = bybit['daily_pnl']
    save_state(state)

    log.info('Report sent. Balance: $%.2f, PnL today: $%.3f', current_bal, bybit['daily_pnl'])


if __name__ == '__main__':
    run()
