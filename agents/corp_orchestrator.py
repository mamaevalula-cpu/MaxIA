#!/usr/bin/env python3
"""
corp_orchestrator.py — MaxAI Corporation Orchestrator
Мозг корпорации. Координирует всех агентов, отслеживает доходы,
распределяет задачи, оптимизирует стратегии.

Структура корпорации:
  CEO → corp_orchestrator.py (этот файл)
  CFO → revenue_executor.py + daily_revenue_report.py
  CTO → supreme_guardian.py (мониторинг и починка)
  CMO → kwork_agent.py + freelance agents
  Trader → bybit_monitor.py + funding_arb_agent.py
  Passive Income → bybit_earn_now.py

Запуск: 1 раз в день через cron в 07:00
"""
import json, logging, os, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen, Request

sys.path.insert(0, '/root/my_personal_ai')
Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/orchestrator.log'),
    ]
)
log = logging.getLogger('corp')

TG_TOKEN  = __import__('os').environ.get('TELEGRAM_BOT_TOKEN','')  # F1.1 fix
TG_CHAT   = __import__('os').environ.get('TELEGRAM_CHAT_ID','')  # F1.1 fix
DATA_DIR  = Path('/root/my_personal_ai/data')
DATA_DIR.mkdir(exist_ok=True)

VENV_PY = '/root/venv/bin/python3'

def tg(text: str):
    try:
        d = json.dumps({'chat_id': TG_CHAT, 'text': text[:4096], 'parse_mode': 'HTML'}).encode()
        urlopen(Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                        data=d, headers={'Content-Type':'application/json'}), timeout=8)
    except Exception as e:
        log.warning('TG: %s', e)

def run_agent(script: str, timeout: int = 120) -> tuple:
    """Run an agent script and return (success, output)."""
    try:
        r = subprocess.run(
            [VENV_PY, script],
            capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, (r.stdout + r.stderr)[-500:]
    except subprocess.TimeoutExpired:
        return False, f'Timeout after {timeout}s'
    except Exception as e:
        return False, str(e)

def check_service_active(name: str) -> bool:
    try:
        r = subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == 'active'
    except Exception:
        return False

def ensure_services_running():
    """Make sure all critical services are running."""
    critical = ['bybit-monitor', 'personal-ai', 'hyperion-control-plane-v2', 'nginx', 'maxai-guardian', 'maxai-tgbot']
    fixed = []
    for svc in critical:
        if not check_service_active(svc):
            log.warning('Service %s not active, restarting...', svc)
            subprocess.run(['systemctl', 'restart', svc], timeout=30)
            time.sleep(3)
            if check_service_active(svc):
                fixed.append(f'✅ {svc} перезапущен')
            else:
                fixed.append(f'❌ {svc} не запускается')
    return fixed

def get_bybit_balance() -> float:
    """Get Bybit USDT balance."""
    try:
        import hmac, hashlib
        KEY = __import__('os').environ.get('BYBIT_API_KEY','')  # F1.1
        SEC = __import__('os').environ.get('BYBIT_API_SECRET','')  # F1.1
        ts = int(time.time() * 1000)
        msg = f'{ts}{KEY}5000accountType=UNIFIED'
        sig = hmac.new(SEC.encode(), msg.encode(), hashlib.sha256).hexdigest()
        headers = {'X-BAPI-API-KEY': KEY, 'X-BAPI-TIMESTAMP': str(ts),
                   'X-BAPI-SIGN': sig, 'X-BAPI-RECV-WINDOW': '5000'}
        req = Request('https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED', headers=headers)
        r = json.loads(urlopen(req, timeout=10).read())
        for c in r['result']['list'][0]['coin']:
            if c['coin'] == 'USDT':
                return float(c.get('walletBalance', 0))
    except Exception as e:
        log.error('Balance: %s', e)
    return 0

def load_revenue_state() -> dict:
    state_file = DATA_DIR / 'corp_revenue.json'
    try:
        return json.loads(state_file.read_text())
    except Exception:
        return {
            'start_date': '2026-05-24',
            'start_balance': 221.12,
            'total_earned': 0.0,
            'best_day': 0.0,
            'days': [],
        }

def save_revenue_state(state: dict):
    (DATA_DIR / 'corp_revenue.json').write_text(json.dumps(state, indent=2, default=str))

def daily_morning_briefing():
    """7:00 UTC — Morning briefing and task distribution."""
    log.info('=== Corporation Morning Briefing ===')
    now = datetime.utcnow()
    state = load_revenue_state()

    # Ensure services
    fixes = ensure_services_running()

    # Get balance
    balance = get_bybit_balance()
    start_bal = state.get('start_balance', 221.12)
    change = balance - start_bal
    change_pct = (change / start_bal * 100) if start_bal > 0 else 0

    # Get kwork stats
    kwork_applied = 0
    kwork_won = 0
    try:
        ks = json.loads((DATA_DIR / 'kwork_state.json').read_text())
        kwork_applied = ks.get('total_applied', 0)
        kwork_won = ks.get('won', 0)
    except Exception:
        pass

    # Get earn stats
    earn_in = 0
    try:
        es = json.loads((DATA_DIR / 'bybit_earn_status.json').read_text())
        earn_in = es.get('in_earn', 0)
    except Exception:
        pass

    # Days running
    try:
        start = datetime.strptime(state.get('start_date', '2026-05-24'), '%Y-%m-%d')
        days = (now - start).days + 1
    except Exception:
        days = 1

    # Build morning report
    lines = [
        f'🌅 <b>MaxAI Утренний Брифинг — {now.strftime("%d.%m.%Y")}</b>',
        f'',
        f'━━━━ 📊 ФИНАНСЫ ━━━━',
        f'💳 Баланс: <b>${balance:.2f}</b>',
        f'📈 С начала: <b>{"+" if change >= 0 else ""}{change:.2f}$ ({change_pct:+.2f}%)</b>',
        f'🏦 В Earn: <b>${earn_in:.2f}</b> (~${earn_in*0.07/365:.3f}/день)',
        f'',
        f'━━━━ 🤖 АГЕНТЫ СЕГОДНЯ ━━━━',
        f'📋 Kwork откликов: {kwork_applied} (выиграно: {kwork_won})',
        f'⏱️ День #{days} работы',
    ]

    if fixes:
        lines.append('')
        lines.append('🔧 <b>Автоисправления:</b>')
        lines.extend(fixes)

    # Today's plan
    daily_target = balance * 0.005
    lines += [
        f'',
        f'━━━━ 🎯 ПЛАН НА СЕГОДНЯ ━━━━',
        f'1️⃣ Торговля: цель +${daily_target:.2f} (0.5%)',
        f'2️⃣ Kwork: отправить 5+ откликов',
        f'3️⃣ Earn: пассивно ~${earn_in*0.07/365:.3f}',
        f'4️⃣ Funding: мониторинг ставок',
        f'',
        f'⏰ Следующий отчёт: завтра 07:00 UTC',
    ]

    tg('\n'.join(lines))
    log.info('Morning briefing sent. Balance: $%.2f', balance)

    # Run today's agents
    agents_to_run = [
        ('/root/my_personal_ai/agents/bybit_earn_now.py', 'Bybit Earn check'),
        ('/root/my_personal_ai/agents/funding_arb_agent.py', 'Funding Rate check'),
    ]
    for script, name in agents_to_run:
        if Path(script).exists():
            ok, out = run_agent(script, timeout=60)
            log.info('%s: %s', name, 'OK' if ok else f'FAIL: {out[:100]}')
        else:
            log.warning('%s not found: %s', name, script)

    # Save state
    state['last_briefing'] = now.isoformat()
    state['last_balance'] = balance
    save_revenue_state(state)


def weekly_strategy_review():
    """Monday 09:00 UTC — Weekly strategy review and optimization."""
    log.info('=== Weekly Strategy Review ===')
    now = datetime.utcnow()
    balance = get_bybit_balance()
    state = load_revenue_state()

    start_bal = state.get('start_balance', 221.12)
    week_change = balance - state.get('last_week_balance', start_bal)
    week_pct = (week_change / state.get('last_week_balance', start_bal) * 100)

    lines = [
        f'📅 <b>MaxAI Еженедельный обзор</b>',
        f'',
        f'💰 Баланс: ${balance:.2f}',
        f'📊 За неделю: {"+" if week_change >= 0 else ""}{week_change:.2f}$ ({week_pct:+.2f}%)',
        f'',
        f'🔮 <b>Стратегия следующей недели:</b>',
    ]

    # Adaptive strategy based on performance
    if week_pct > 2:
        lines.append('🚀 Производительность ОТЛИЧНАЯ — увеличиваем агрессивность')
        lines.append('  → Торговля: 3% риск → 4%')
        lines.append('  → Kwork: 10 откликов/день')
    elif week_pct > 0:
        lines.append('✅ Производительность ХОРОШАЯ — держим курс')
        lines.append('  → Торговля: 3% риск (текущий)')
        lines.append('  → Kwork: 5-7 откликов/день')
    else:
        lines.append('⚠️ Производительность НИЗКАЯ — консервативный режим')
        lines.append('  → Торговля: снизить риск до 2%')
        lines.append('  → Больше Earn, меньше трейдинг')

    tg('\n'.join(lines))
    state['last_week_balance'] = balance
    save_revenue_state(state)


def run():
    """Main entry point — run based on time of day."""
    now = datetime.utcnow()
    hour = now.hour
    weekday = now.weekday()  # 0=Monday

    log.info('Corp Orchestrator running at %s UTC (hour=%d, weekday=%d)', now.strftime('%H:%M'), hour, weekday)

    if weekday == 0 and hour == 9:
        weekly_strategy_review()
    else:
        daily_morning_briefing()


if __name__ == '__main__':
    run()
