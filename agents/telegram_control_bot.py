#!/usr/bin/env python3
"""
telegram_control_bot.py — MaxAI Corporation Telegram Control Center
Полный контроль системы через Telegram 24/7.
"""
import json, logging, os, subprocess, sys, time, hmac, hashlib
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

TG_TOKEN = __import__('os').environ.get('TELEGRAM_BOT_TOKEN', '')  # F1.1 fix
TG_CHAT  = __import__('os').environ.get('TELEGRAM_CHAT_ID', '')  # F1.1 fix

BYBIT_API_KEY    = __import__('os').environ.get('BYBIT_API_KEY', '')  # F1.1 fix
BYBIT_API_SECRET = __import__('os').environ.get('BYBIT_API_SECRET', '')  # F1.1 fix
BYBIT_BASE       = 'https://api.bybit.com'

LOG_DIR   = Path('/root/my_personal_ai/logs')
LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = Path('/root/my_personal_ai/data/tgbot_state.json')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_DIR / 'tgbot.log')),
    ]
)
log = logging.getLogger('tgbot')

SERVICES = ['bybit-monitor', 'personal-ai', 'hyperion-control-plane-v2',
            'nginx', 'maxai-guardian', 'maxai-tgbot', 'postgresql']

# ─── Telegram API ──────────────────────────────────────────────────────────
def tg_send(chat_id: str, text: str):
    import re as _re
    clean = text[:4096]
    for parse_mode in ['HTML', None]:
        try:
            payload = {'chat_id': chat_id, 'text': clean}
            if parse_mode:
                payload['parse_mode'] = parse_mode
            data = json.dumps(payload).encode()
            req = Request(
                f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                data=data, headers={'Content-Type': 'application/json'}
            )
            with urlopen(req, timeout=10) as r:
                return json.loads(r.read())
        except Exception as e:
            if parse_mode:
                # Strip HTML tags and retry as plain text
                clean = _re.sub(r'<[^>]+>', '', text[:4096])
                clean = clean.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
                log.warning('tg_send HTML failed (%s), retrying plain', e)
            else:
                log.error('tg_send failed: %s', e)
    return None

def tg_get_updates(offset: int = 0) -> list:
    try:
        url = (f'https://api.telegram.org/bot{TG_TOKEN}/getUpdates'
               f'?offset={offset}&timeout=30&allowed_updates=["message"]')
        with urlopen(Request(url), timeout=35) as r:
            return json.loads(r.read()).get('result', [])
    except Exception as e:
        log.warning('getUpdates error: %s', e)
        return []

# ─── Bybit API ─────────────────────────────────────────────────────────────
def bybit_get(path: str, params: dict = None) -> dict:
    params = params or {}
    ts = int(time.time() * 1000)
    q = '&'.join(f'{k}={v}' for k, v in sorted(params.items()))
    sign = f'{ts}{BYBIT_API_KEY}5000{q}' if q else f'{ts}{BYBIT_API_KEY}5000'
    sig = hmac.new(BYBIT_API_SECRET.encode(), sign.encode(), hashlib.sha256).hexdigest()
    headers = {'X-BAPI-API-KEY': BYBIT_API_KEY, 'X-BAPI-TIMESTAMP': str(ts),
               'X-BAPI-SIGN': sig, 'X-BAPI-RECV-WINDOW': '5000'}
    url = f'{BYBIT_BASE}{path}' + (f'?{q}' if q else '')
    try:
        with urlopen(Request(url, headers=headers), timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        return {'error': str(e)}

def api_local(path: str) -> dict:
    try:
        with urlopen(Request(f'http://127.0.0.1{path}'), timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}

# ─── Commands ─────────────────────────────────────────────────────────────
def cmd_status() -> str:
    lines = [f'<b>MaxAI Corporation — Статус</b>', f'<i>{datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")}</i>', '']

    # Services
    ok_count = 0
    svc_lines = []
    for svc in SERVICES:
        try:
            r = subprocess.run(['systemctl', 'is-active', svc], capture_output=True, text=True, timeout=3)
            active = r.stdout.strip() == 'active'
            if active:
                ok_count += 1
            svc_lines.append(f'{"✅" if active else "❌"} {svc}')
        except Exception:
            svc_lines.append(f'❓ {svc}')

    lines.append(f'<b>Сервисы {ok_count}/{len(SERVICES)}:</b>')
    lines.extend(svc_lines)

    # Bot status
    bot = api_local('/api/v1/status') or api_local(':8001/status')
    try:
        bot = json.loads(urlopen(Request('http://127.0.0.1:8001/status'), timeout=3).read())
        lines.append(f'\n<b>Bybit ({bot.get("mode","?").upper()}):</b>')
        lines.append(f'  💳 ${bot.get("balance_usdt",0):.2f} | PnL: ${bot.get("daily_pnl",0):.4f}')
        lines.append(f'  Сделок: {bot.get("trades_today",0)} | Позиций: {bot.get("open_positions",0)}')
    except Exception:
        lines.append('\n❌ Bybit API недоступен')

    return '\n'.join(lines)


def cmd_balance() -> str:
    lines = ['<b>Bybit Balance</b>', '']
    # Real API
    r = bybit_get('/v5/account/wallet-balance', {'accountType': 'UNIFIED'})
    try:
        for c in r['result']['list'][0]['coin']:
            if c['coin'] == 'USDT':
                lines.append(f'💳 Баланс: <b>${float(c.get("walletBalance",0)):.2f} USDT</b>')
                lines.append(f'📊 Equity: <b>${float(c.get("equity",0)):.2f}</b>')
                break
    except Exception:
        lines.append('❌ Не удалось получить баланс')

    # Bot stats
    try:
        bot = json.loads(urlopen(Request('http://127.0.0.1:8001/status'), timeout=4).read())
        lines.append(f'📈 PnL сегодня: <b>${float(bot.get("daily_pnl",0)):.4f}</b>')
        lines.append(f'🔄 Сделок: {bot.get("trades_today",0)} | Режим: {bot.get("mode","?").upper()}')
    except Exception:
        lines.append('⚠️ Bot API недоступен')

    # Risk
    try:
        risk = json.loads(urlopen(Request('http://127.0.0.1:8001/risk'), timeout=3).read())
        lines.append(f'⚠️ Нед. остаток: <b>${float(risk.get("weekly_remaining_usdt",0)):.2f}</b>')
        lines.append(f'📅 Week PnL: ${float(risk.get("week_pnl",0)):.3f}')
    except Exception:
        pass

    return '\n'.join(lines)


def cmd_trading() -> str:
    """Detailed trading status."""
    lines = ['<b>Торговля — детальный статус</b>', '']
    try:
        bot = json.loads(urlopen(Request('http://127.0.0.1:8001/status'), timeout=5).read())
        risk = json.loads(urlopen(Request('http://127.0.0.1:8001/risk'), timeout=3).read())

        mode = bot.get('mode', '?').upper()
        bal = bot.get('balance_usdt', 0)
        pnl = bot.get('daily_pnl', 0)
        trades = bot.get('trades_today', 0)
        pairs = ', '.join(bot.get('active_pairs', []))
        active = bot.get('trading_active', False)
        strats = ', '.join([s['name'] for s in bot.get('strategies_info', []) if s.get('enabled')])

        week_rem = risk.get('weekly_remaining_usdt', 0)
        week_pnl = risk.get('week_pnl', 0)
        daily_lim = risk.get('daily_trades', 0)
        max_daily = risk.get('max_daily_trades', 3)
        emerg = risk.get('emergency_stop', False)

        lines += [
            f'Режим: <b>{mode}</b> | Торговля: {"ВКЛ" if active else "ВЫКЛ"}',
            f'',
            f'<b>Финансы:</b>',
            f'  Баланс: ${bal:.2f}',
            f'  PnL сегодня: ${pnl:.4f}',
            f'  PnL за неделю: ${week_pnl:.3f}',
            f'  Недельный лимит: ${week_rem:.2f} осталось',
            f'',
            f'<b>Торговля:</b>',
            f'  Пары: {pairs}',
            f'  Стратегии: {strats}',
            f'  Сделок сегодня: {daily_lim}/{max_daily}',
            f'  Emergency stop: {"ДА!" if emerg else "нет"}',
        ]

        last_sig = bot.get('last_signal', {})
        if last_sig:
            lines.append(f'\n<b>Последний сигнал:</b>')
            lines.append(f'  {last_sig.get("symbol","?")} {last_sig.get("action","?")} '
                        f'({last_sig.get("strategy","?")} strength={last_sig.get("strength",0):.2f})')
    except Exception as e:
        lines.append(f'❌ Ошибка: {e}')

    return '\n'.join(lines)


def cmd_analysis() -> str:
    """Market analysis - funding rates and opportunities."""
    lines = ['<b>Рыночный анализ</b>', f'<i>{datetime.utcnow().strftime("%H:%M UTC")}</i>', '']

    pairs = ['SOLUSDT', 'LINKUSDT', 'DOTUSDT', 'BTCUSDT', 'ETHUSDT']
    opportunities = []

    for symbol in pairs:
        try:
            r = bybit_get('/v5/market/tickers', {'category': 'linear', 'symbol': symbol})
            item = r.get('result', {}).get('list', [{}])[0]
            rate = float(item.get('fundingRate', 0))
            price = float(item.get('lastPrice', 0))
            change24h = float(item.get('price24hPcnt', 0)) * 100
            volume = float(item.get('volume24h', 0))

            annual = abs(rate) * 3 * 365 * 100
            direction = "LONG wins" if rate < 0 else "SHORT wins"

            change_icon = "📈" if change24h > 0 else "📉"
            lines.append(f'{change_icon} <b>{symbol}</b>: ${price:.2f} ({change24h:+.1f}%) | '
                        f'Funding: {rate*100:.4f}%/8h ({annual:.0f}%/yr {direction})')

            if abs(rate) >= 0.0003:
                opportunities.append(f'⚡ {symbol}: {rate*100:.4f}%/8h HIGH')
            time.sleep(0.1)
        except Exception:
            pass

    if opportunities:
        lines.append('')
        lines.append('<b>Торговые возможности:</b>')
        lines.extend(opportunities)
    else:
        lines.append('\nФандинг нейтральный, нет высоких ставок сейчас.')

    return '\n'.join(lines)


def cmd_restart(service: str) -> str:
    if service not in SERVICES:
        return f'❌ Сервис <b>{service}</b> неизвестен\nДоступны: ' + ', '.join(SERVICES)
    try:
        subprocess.run(['systemctl', 'restart', service], capture_output=True, text=True, timeout=30)
        time.sleep(3)
        r = subprocess.run(['systemctl', 'is-active', service], capture_output=True, text=True, timeout=3)
        ok = r.stdout.strip() == 'active'
        return f'{"✅" if ok else "❌"} <b>{service}</b>: {r.stdout.strip()}'
    except Exception as e:
        return f'❌ Ошибка: {e}'


def cmd_logs(service: str) -> str:
    # Check log file first
    log_file = LOG_DIR / f'{service}.log'
    if log_file.exists():
        r = subprocess.run(['tail', '-n', '25', str(log_file)], capture_output=True, text=True)
        text = r.stdout[-2500:] if r.stdout else 'пусто'
        return f'<b>Лог {service}:</b>\n<code>{text}</code>'

    # Fall back to journalctl
    if service in SERVICES:
        r = subprocess.run(
            ['journalctl', '-u', service, '-n', '25', '--no-pager', '-q'],
            capture_output=True, text=True, timeout=10
        )
        text = r.stdout[-2500:] if r.stdout else 'нет логов'
        return f'<b>Логи {service}:</b>\n<code>{text}</code>'

    return f'❌ Лог {service} не найден'


def cmd_agents() -> str:
    lines = ['<b>Агенты MaxAI</b>', '']
    try:
        agents = sorted([f for f in Path('/root/my_personal_ai/agents').glob('*.py')
                        if not f.name.startswith('_')],
                       key=lambda x: x.stat().st_mtime, reverse=True)
        for af in agents[:20]:
            r = subprocess.run(['pgrep', '-f', af.name], capture_output=True, text=True)
            icon = '🟢' if r.stdout.strip() else '⚫'
            lines.append(f'{icon} {af.name}')
    except Exception as e:
        lines.append(f'❌ {e}')
    return '\n'.join(lines)


def cmd_report() -> str:
    lines = ['<b>MaxAI Revenue Report</b>', f'<i>{datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")}</i>', '']

    # Balance
    try:
        r = bybit_get('/v5/account/wallet-balance', {'accountType': 'UNIFIED'})
        for c in r['result']['list'][0]['coin']:
            if c['coin'] == 'USDT':
                lines.append(f'💳 Баланс: <b>${float(c.get("walletBalance",0)):.2f}</b>')
                break
    except Exception:
        lines.append('💳 Баланс: N/A')

    # Bot stats
    try:
        bot = json.loads(urlopen(Request('http://127.0.0.1:8001/status'), timeout=3).read())
        lines.append(f'📈 PnL сегодня: ${bot.get("daily_pnl",0):.4f}')
        lines.append(f'Сделок: {bot.get("trades_today",0)}')
    except Exception:
        pass

    # Kwork
    try:
        ks = json.loads(Path('/root/my_personal_ai/data/kwork_state.json').read_text())
        lines.append(f'\n💼 Kwork: {ks.get("total_applied",0)} откликов, выиграно {ks.get("won",0)}')
    except Exception:
        lines.append('\n💼 Kwork: нет данных')

    # Services
    ok = sum(1 for s in SERVICES
             if subprocess.run(['systemctl','is-active',s], capture_output=True, text=True, timeout=3).stdout.strip() == 'active')
    lines.append(f'\n🖥️ Сервисов активно: {ok}/{len(SERVICES)}')

    return '\n'.join(lines)


def cmd_crons() -> str:
    r = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    jobs = [l for l in r.stdout.splitlines() if l.strip() and not l.startswith('#')]
    lines = [f'<b>Cron задачи ({len(jobs)}):</b>', '']
    for j in jobs[-25:]:
        parts = j.split()
        schedule = ' '.join(parts[:5]) if len(parts) >= 5 else j
        script = parts[-1].split('/')[-1] if len(parts) > 5 else ''
        lines.append(f'<code>{schedule[:18]}</code> {script}')
    return '\n'.join(lines)


def cmd_kwork() -> str:
    lines = ['<b>Kwork Agent</b>', '']
    try:
        ks = json.loads(Path('/root/my_personal_ai/data/kwork_state.json').read_text())
        lines += [
            f'Откликов всего: <b>{ks.get("total_applied",0)}</b>',
            f'Выиграно проектов: <b>{ks.get("won",0)}</b>',
            f'Заработано: <b>{ks.get("total_earned_rub",0):,} руб</b>',
        ]
    except Exception:
        lines.append('Нет данных. Агент ещё не запускался.')

    lines.append('\nЗапустить сейчас: нажми /run_kwork')
    return '\n'.join(lines)


def cmd_run_kwork() -> str:
    try:
        proc = subprocess.Popen(
            ['/root/venv/bin/python3', '/root/my_personal_ai/agents/kwork_agent.py'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return f'✅ Kwork агент запущен (PID {proc.pid}). Результат придёт в Telegram.'
    except Exception as e:
        return f'❌ Ошибка запуска: {e}'


def cmd_links() -> str:
    lines = [
        "<b>MaxAI — Все ресурсы</b>",
        "",
        "<b>Боты:</b>",
        "• @Corporation_MaxAI_bot — корп бот",
        "• @maksim_bybit_bot — управление системой",
        "",
        "<b>Панель управления:</b>",
        "• http://77.90.2.171/ — главная",
        "• http://77.90.2.171/api/v1/manifest",
        "",
        "<b>API для клиентов:</b>",
        "POST http://77.90.2.171/api/v1/webhook — заявки",
        "POST http://77.90.2.171/api/v1/ai — AI",
        "GET  http://77.90.2.171/api/v1/packs — пакеты",
        "",
        "<b>Статус системы:</b>",
        "http://77.90.2.171/health",
        "http://77.90.2.171/api/status",
    ]
    return chr(10).join(lines)


def cmd_help() -> str:
    return (
        '<b>MaxAI Corporation Control Bot</b>\n\n'
        '<b>Статус и данные:</b>\n'
        '/status — состояние всех сервисов\n'
        '/balance — баланс и PnL\n'
        '/trading — детали торговли\n'
        '/analysis — рыночный анализ\n'
        '/report — отчёт по доходам\n'
        '/kwork — статистика Kwork\n'
        '/agents — список агентов\n'
        '/crons — расписание cron\n'
        '\n<b>Управление:</b>\n'
        '/restart &lt;сервис&gt; — перезапуск\n'
        '/logs &lt;файл&gt; — логи (bot/guardian/bybit/corp)\n'
        '/run_kwork — запустить Kwork агент\n'
        '\n<b>Сервисы:</b>\n'
        + ', '.join(SERVICES) + '\n\n'
        'Или просто напиши вопрос — отвечу!'
    )




# ─── Intelligent Natural-Language Task Executor ─────────────────────────────
_AI_ACTIONS = {
    # Service restart patterns
    r'перезапуст[иь].*(?:байт|bybit|bybit-monitor)': lambda _: cmd_restart('bybit-monitor'),
    r'перезапуст[иь].*(?:панель|panel|personal-ai)': lambda _: cmd_restart('personal-ai'),
    r'перезапуст[иь].*(?:бот|bot|maxai-tgbot)':      lambda _: cmd_restart('maxai-tgbot'),
    # Trading / financial ? route to REAL DATA, no hallucination
        # Status/info
    r'(?:покажи|статус|состояние|как|что).{0,20}(?:торгу|трейд|позиц|сделк)': lambda _: cmd_trading(),
    r'(?:покажи|статус|состояние|баланс|сколько)': lambda _: cmd_balance(),
    r'(?:отчёт|отчет|доход|выручка|заработ)': lambda _: cmd_report(),
    r'(?:агенты|работают|запущен)': lambda _: cmd_agents(),
    r'(?:аналитика|анализ|рынок|прогноз)': lambda _: cmd_analysis(),
    # Kwork
    r'(?:kwork|kворк|кворк).*(?:запуст|зайди|войди|логин)': lambda _: cmd_run_kwork(),
    r'(?:обнов|замен|новые).*(?:логин|пароль|kwork|кворк)': lambda arg: _update_kwork_creds(arg),
    # Error fixes
    r'(?:исправь|почини|fix).*(?:ошибк|error|модел|model|llm|ии)': lambda _: _fix_llm_errors(),
    r'(?:проверь|check).*(?:ключ|key|api)': lambda _: _check_all_keys(),
    # Task creation
    r'создай.*(?:задач|task)': lambda arg: _create_task(arg),
    r'выполн[иь]': lambda arg: _execute_task(arg),
}

def _update_kwork_creds(text: str) -> str:
    """Parse and update Kwork credentials from text."""
    import re as _re
    email_m = _re.search(r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', text)
    pass_m  = _re.search(r'(?i)(?:пароль|password|pass)[:\s]+([\S]+)', text)
    if not email_m:
        return '❌ Email не найден в тексте'
    email = email_m.group(1)
    password = pass_m.group(1) if pass_m else None
    # Update .env
    env_path = Path('/root/my_personal_ai/.env')
    env = env_path.read_text()
    import re as _re2
    env = _re2.sub(r'KWORK_EMAIL=.*', f'KWORK_EMAIL={email}', env)
    if password:
        env = _re2.sub(r'KWORK_PASSWORD=.*', f'KWORK_PASSWORD={password}', env)
    env_path.write_text(env)
    log.info('Kwork creds updated: email=%s', email)
    return f'✅ Kwork обновлён:\nEmail: {email}\nПароль: {"****" if password else "без изменений"}\n\nЗапускаю агент...'

def _fix_llm_errors() -> str:
    """Check and report LLM provider status."""
    try:
        import urllib.request as _ur, json as _json
        r = _ur.urlopen('http://127.0.0.1:8090/api/llm/status', timeout=5)
        data = _json.loads(r.read())
        providers = data.get('providers', [])
        lines = ['<b>Статус LLM провайдеров:</b>']
        for p in providers:
            icon = '✅' if p.get('available') else '❌'
            lines.append(f'{icon} {p["name"]}: {p["model"]} (key={"да" if p.get("key_configured") else "нет"})')
        configured = data.get('configured', 0)
        lines.append(f'\nАктивных: {configured}/{len(providers)}')
        if configured == 0:
            lines.append('\n⚠️ Нет активных провайдеров! Нужны API ключи.')
        return '\n'.join(lines)
    except Exception as e:
        return f'❌ Ошибка получения статуса LLM: {e}'

def _check_all_keys() -> str:
    """Quick check of all API keys."""
    out = []
    keys_to_check = {
        'ANTHROPIC_API_KEY': 'Claude',
        'GROQ_API_KEY': 'Groq',
        'BYBIT_API_KEY': 'Bybit',
        'KWORK_EMAIL': 'Kwork',
    }
    for env_key, name in keys_to_check.items():
        val = os.environ.get(env_key, '')
        if val:
            masked = val[:4] + '...' + val[-4:] if len(val) > 8 else '***'
            out.append(f'✅ {name}: {masked}')
        else:
            out.append(f'❌ {name}: не задан')
    return '<b>API ключи:</b>\n' + '\n'.join(out)

def _create_task(text: str) -> str:
    """Register a task in the task queue."""
    try:
        import urllib.request as _ur, json as _json
        payload = _json.dumps({'type': 'ai_task', 'params': {'text': text, 'source': 'telegram'}, 'priority': 5}).encode()
        req = _ur.Request('http://127.0.0.1:8090/api/tasks/queue',
                         data=payload, headers={'Content-Type': 'application/json'})
        r = _ur.urlopen(req, timeout=5)
        d = _json.loads(r.read())
        return f'✅ Задача создана: {d.get("id","?")}'
    except Exception as e:
        return f'❌ Ошибка создания задачи: {e}'

def _execute_task(text: str) -> str:
    """Execute a task immediately via panel."""
    try:
        import urllib.request as _ur, json as _json
        payload = _json.dumps({'message': text, 'source': 'telegram_execute',
                               'system_prompt': 'You are MaxAI. Execute the given task and report results in Russian.'}).encode()
        req = _ur.Request('http://127.0.0.1:8090/api/chat',
                         data=payload, headers={'Content-Type': 'application/json'})
        r = _ur.urlopen(req, timeout=25)
        d = _json.loads(r.read())
        result = d.get('reply') or d.get('result') or d.get('response') or d.get('text') or str(d)
        return f'✅ Выполнено:\n{result[:1500]}'
    except Exception as e:
        return f'❌ Ошибка выполнения: {e}'

def _route_intelligent(text: str) -> str:
    """Route natural language text to the correct action."""
    import re as _re
    text_lower = text.lower()
    for pattern, action_fn in _AI_ACTIONS.items():
        if _re.search(pattern, text_lower):
            try:
                result = action_fn(text)
                if result:
                    return result
            except Exception as ex:
                log.warning('Intelligent action failed: %s', ex)
    return None  # No match — fall through to AI

# ─── Dispatcher ─────────────────────────────────────────────────────────────
def dispatch(text: str, chat_id: str):
    if str(chat_id) != TG_CHAT:
        tg_send(chat_id, '❌ Доступ запрещён.')
        return

    parts = text.strip().split(None, 1)
    cmd = parts[0].lstrip('/').split('@')[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ''

    log.info('Command: %s %s from %s', cmd, arg, chat_id)

    dispatch_table = {
        'status':   cmd_status,
        'balance':  cmd_balance,
        'trading':  cmd_trading,
        'analysis': cmd_analysis,
        'report':   cmd_report,
        'agents':   cmd_agents,
        'crons':    cmd_crons,
        'kwork':    cmd_kwork,
        'run_kwork': cmd_run_kwork,
        'help':     cmd_help,
        'start':    cmd_help,
        'links':    cmd_links,
    }

    if cmd == 'restart':
        reply = cmd_restart(arg) if arg else '❌ Укажи: /restart bybit-monitor'
    elif cmd == 'logs':
        reply = cmd_logs(arg) if arg else '❌ Укажи: /logs guardian'
    elif cmd == 'kwork' and arg and ('@' in arg or 'логин' in arg.lower() or 'пароль' in arg.lower()):
        # Credential update with full text
        reply = _update_kwork_creds(text)
        if 'Запускаю' in reply:
            tg_send(chat_id, reply)
            reply = cmd_run_kwork()
    elif cmd in dispatch_table:
        reply = dispatch_table[cmd]()
    else:
        # 1. Intelligent action router ? maps natural language to real system commands
        reply = _route_intelligent(text)

        if not reply:
            # 2. Anti-hallucination AI (max 3 sentences, never fabricate data)
            try:
                import urllib.request as _ur, json as _json
                _sys = (
                    'Ты MaxAI — ИИ-ассистент корпорации. Правила: '
                    '1) Отвечай на вопросы чётко, кратко, по-русски. '
                    '2) Для команд используй список /help. '
                    '3) Максимум 3 абзаца, никакой воды. '
                    '4) Данные только реальные из /trading /balance.'
                )
                # Smart truncation: keep first meaningful line for long messages
                _txt_clean = text.strip()
                if len(_txt_clean) > 600:
                    # Extract first meaningful sentence (user's real intent)
                    _first_line = _txt_clean.split('\n')[0].strip()
                    if len(_first_line) > 20:
                        _txt_for_ai = _first_line[:500]
                    else:
                        _txt_for_ai = _txt_clean[:500]
                    _txt_for_ai += ' [длинное сообщение сокращено до ключевой команды]'
                else:
                    _txt_for_ai = _txt_clean
                _pay = _json.dumps({'message': _txt_for_ai, 'source': 'telegram',
                                    'system_prompt': _sys}).encode()
                _req = _ur.Request('http://127.0.0.1:8090/api/chat',
                                   data=_pay,
                                   headers={'Content-Type': 'application/json'})
                with _ur.urlopen(_req, timeout=20) as _r:
                    _d = _json.loads(_r.read())
                reply = (_d.get('reply') or _d.get('response') or '').strip()
                if len(reply) > 800:
                    reply = reply[:780] + '\u2026\n<i>(/help ??? ???? ??????)</i>'
                if not reply:
                    raise ValueError('empty')
            except Exception as _e:
                log.warning('AI fallback: %s', _e)
                reply = '\u2753 ?? ?????. ????????? /help ??? ?????? ??????.'

    tg_send(chat_id, reply)



# ─── Main ───────────────────────────────────────────────────────────────────
def main():
    log.info('Telegram Control Bot started')
    STATE_FILE.parent.mkdir(exist_ok=True)

    try:
        offset = json.loads(STATE_FILE.read_text()).get('offset', 0)
    except Exception:
        offset = 0

    tg_send(TG_CHAT,
        f'MaxAI Corporation готова! {datetime.utcnow().strftime("%d.%m.%Y %H:%M UTC")}\n'
        'Введи /help для команд или /status для проверки системы'
    )

    while True:
        try:
            updates = tg_get_updates(offset)
            for update in updates:
                offset = update['update_id'] + 1
                msg = update.get('message', {})
                if not msg:
                    continue
                chat_id = str(msg.get('chat', {}).get('id', ''))
                text = msg.get('text', '')
                if text:
                    dispatch(text, chat_id)

            STATE_FILE.write_text(json.dumps({'offset': offset}))
        except Exception as e:
            log.error('Main loop: %s', e)
            time.sleep(5)


if __name__ == '__main__':
    main()
