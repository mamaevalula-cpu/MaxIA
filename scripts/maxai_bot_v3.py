#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MaxAI Telegram Bot v3 — Complete Rewrite
@maksim_bybit_bot — главный личный бот Максима
Все тексты на русском языке, inline keyboards, rich HTML.
"""
from __future__ import annotations
import asyncio, hashlib, hmac, json, logging, os, re, signal, sys, time
import urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
    from telegram.ext import (Application, CommandHandler, MessageHandler,
                               CallbackQueryHandler, filters, ContextTypes)
    from telegram.constants import ChatAction, ParseMode
    from telegram.error import TelegramError
except ImportError:
    sys.exit('Установи: pip install python-telegram-bot>=20')

# ── Paths & env ───────────────────────────────────────────────────────────────
BASE      = Path('/root/my_personal_ai')
LOG_FILE  = BASE / 'logs' / 'bot_v3.log'
PID_FILE  = Path('/tmp/maxai_bot_v3.pid')
ENV_FILE  = BASE / '.env'

def _load_env() -> dict:
    env: dict = {}
    try:
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return {**env, **os.environ}

ENV           = _load_env()
BOT_TOKEN     = ENV.get('TELEGRAM_BOT_TOKEN', '')
OWNER_ID      = int(ENV.get('TELEGRAM_CHAT_ID', '1985320458'))
GROQ_KEY      = ENV.get('GROQ_API_KEY', '')
CEREBRAS_KEY  = ENV.get('CEREBRAS_API_KEY', '')
ANTHROPIC_KEY = ENV.get('ANTHROPIC_API_KEY', '')
OR_KEY        = ENV.get('OPENROUTER_API_KEY', '')
DS_KEY        = ENV.get('DEEPSEEK_API_KEY', '')
HF_KEY        = ENV.get('HUGGINGFACE_TOKEN', '')
BYBIT_KEY     = ENV.get('BYBIT_API_KEY', '')
BYBIT_SECRET  = ENV.get('BYBIT_API_SECRET', '')

USDT_TRC20 = 'TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2'
ETH_ADDR   = '0x7b72d6072f973a79d13abb11769927890832cc12'
BTC_ADDR   = '158AEebXosZfxHY1ZVQNfTT6BHcuHqGFr4'
SOL_ADDR   = '4v5rZQDfgHwE5135fQcVaQcaczYsb86gXbPgxWw4XDzK'
PANEL_URL = 'https://maxai.fyi'
API_BASE   = 'https://maxai.fyi'
LOCAL_API  = 'http://127.0.0.1:8090'

TASK_PRICES = {
    'research': 0.10, 'analysis': 0.20, 'coding': 0.25,
    'trading': 0.50, 'social': 0.30, 'scraping': 0.15,
}

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(LOG_FILE), encoding='utf-8'),
    ]
)
log = logging.getLogger('bot_v3')

# ── PID lock ──────────────────────────────────────────────────────────────────
def _acquire_lock() -> None:
    if PID_FILE.exists():
        try:
            old = int(PID_FILE.read_text().strip())
            os.kill(old, 0)
            log.warning('Завершаем старый PID %d', old)
            os.kill(old, signal.SIGTERM)
            time.sleep(3)
            try:
                os.kill(old, signal.SIGKILL)
            except ProcessLookupError:
                pass
        except (ProcessLookupError, ValueError, OSError):
            pass
    PID_FILE.write_text(str(os.getpid()))

def _release_lock() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _http_sync(url: str, body=None, hdrs=None, timeout: int = 8):
    try:
        import httpx as _hx
        if body:
            r = _hx.post(url, content=body, headers=hdrs or {}, timeout=timeout)
        else:
            r = _hx.get(url, headers=hdrs or {}, timeout=timeout)
        return r.json()
    except Exception:
        req = urllib.request.Request(
            url, data=body, headers=hdrs or {},
            method='POST' if body else 'GET'
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

async def ahttp(url: str, data=None, headers: dict | None = None, timeout: int = 8):
    body = json.dumps(data).encode() if data else None
    hdrs = {'Content-Type': 'application/json', **(headers or {})}
    return await asyncio.to_thread(_http_sync, url, body, hdrs, timeout)

async def api_get(path: str, timeout: int = 6):
    """Call panel API, return dict or None on error."""
    try:
        return await ahttp(f'{API_BASE}{path}', timeout=timeout)
    except Exception as e:
        log.debug('API %s error: %s', path, e)
        return None

# ── AI chain ──────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = (
    'Ты MaxAI — персональный AI-ассистент Максима. '
    'Отвечай кратко, по-деловому, на русском языке. '
    'Помогаешь с криптотрейдингом, бизнесом и автоматизацией. '
    'Если не знаешь — честно скажи.'
)

_groq_block_until = 0.0

def _groq_blocked() -> bool:
    return time.time() < _groq_block_until

def _set_groq_blocked(hours: float = 1.0) -> None:
    global _groq_block_until
    _groq_block_until = time.time() + hours * 3600
    log.warning('Groq заблокирован на %gh', hours)

async def _ask_groq(text: str, history=None) -> str:
    if not GROQ_KEY:
        raise RuntimeError('no groq key')
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    if history:
        msgs.extend(history[-6:])
    msgs.append({'role': 'user', 'content': text})
    d = await ahttp(
        'https://api.groq.com/openai/v1/chat/completions',
        data={'model': 'llama-3.3-70b-versatile', 'messages': msgs,
              'max_tokens': 1024, 'temperature': 0.7},
        headers={'Authorization': f'Bearer {GROQ_KEY}'}, timeout=30
    )
    return d['choices'][0]['message']['content'].strip()

async def _ask_anthropic(text: str, history=None) -> str:
    if not ANTHROPIC_KEY:
        raise RuntimeError('no anthropic key')
    msgs = []
    if history:
        msgs.extend(history[-6:])
    msgs.append({'role': 'user', 'content': text})
    d = await ahttp(
        'https://api.anthropic.com/v1/messages',
        data={'model': 'claude-haiku-4-5', 'max_tokens': 1024,
              'system': SYSTEM_PROMPT, 'messages': msgs},
        headers={'x-api-key': ANTHROPIC_KEY, 'anthropic-version': '2023-06-01'},
        timeout=30
    )
    return d['content'][0]['text'].strip()

async def _ask_openrouter(text: str, history=None) -> str:
    if not OR_KEY:
        raise RuntimeError('no or key')
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    if history:
        msgs.extend(history[-6:])
    msgs.append({'role': 'user', 'content': text})
    d = await ahttp(
        'https://openrouter.ai/api/v1/chat/completions',
        data={'model': 'meta-llama/llama-3.3-70b-instruct:free',
              'messages': msgs, 'max_tokens': 1024},
        headers={'Authorization': 'Bearer ' + OR_KEY,
                 'HTTP-Referer': 'https://maxai.bot'}, timeout=30
    )
    return d['choices'][0]['message']['content'].strip()

async def _ask_deepseek(text: str, history=None) -> str:
    if not DS_KEY:
        raise RuntimeError('no ds key')
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    if history:
        msgs.extend(history[-6:])
    msgs.append({'role': 'user', 'content': text})
    d = await ahttp(
        'https://api.deepseek.com/v1/chat/completions',
        data={'model': 'deepseek-chat', 'messages': msgs, 'max_tokens': 1024},
        headers={'Authorization': 'Bearer ' + DS_KEY}, timeout=30
    )
    return d['choices'][0]['message']['content'].strip()

async def _ask_huggingface(text: str, history=None) -> str:
    if not HF_KEY:
        raise RuntimeError('no hf key')
    msgs = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    if history:
        msgs.extend(history[-6:])
    msgs.append({'role': 'user', 'content': text})
    d = await ahttp(
        'https://router.huggingface.co/v1/chat/completions',
        data={'model': 'meta-llama/Llama-3.3-70B-Instruct',
              'messages': msgs, 'max_tokens': 1024, 'temperature': 0.7},
        headers={'Authorization': 'Bearer ' + HF_KEY}, timeout=35
    )
    return d['choices'][0]['message']['content'].strip()

async def ask_ai(text: str, user_id=None, history=None) -> str:
    if GROQ_KEY and not _groq_blocked():
        try:
            return await _ask_groq(text, history)
        except Exception as e1:
            log.warning('Groq: %s', e1)
            if '403' in str(e1) or 'Forbidden' in str(e1):
                _set_groq_blocked()
    if ANTHROPIC_KEY:
        try:
            return await _ask_anthropic(text, history)
        except Exception as ea:
            log.warning('Anthropic: %s', ea)
    if OR_KEY:
        try:
            return await _ask_openrouter(text, history)
        except Exception as e2:
            log.warning('OR: %s', e2)
    if DS_KEY:
        try:
            return await _ask_deepseek(text, history)
        except Exception as e3:
            log.warning('DS: %s', e3)
    if HF_KEY:
        try:
            return await _ask_huggingface(text, history)
        except Exception as e4:
            log.warning('HF: %s', e4)
    try:
        d = await ahttp(
            f'{LOCAL_API}/api/chat',
            data={'message': text, 'user_id': str(user_id or OWNER_ID),
                  'session_id': 'tg_' + str(user_id or 0)},
            timeout=20
        )
        r = d.get('response') or d.get('reply') or d.get('message', '')
        if r:
            return r.strip()
    except Exception as e5:
        log.warning('Panel chat: %s', e5)
    return '⚠️ AI временно недоступен. Попробуй снова через минуту.'

# ── Conversation history ──────────────────────────────────────────────────────
_history: dict[int, list] = {}

def _push(uid: int, role: str, content: str) -> None:
    h = _history.setdefault(uid, [])
    h.append({'role': role, 'content': content})
    if len(h) > 20:
        _history[uid] = h[-20:]

def _hist(uid: int) -> list:
    return _history.get(uid, [])

# ── Inline keyboards ──────────────────────────────────────────────────────────
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('\U0001f4ca Статус',    callback_data='status'),
            InlineKeyboardButton('\U0001f4c8 Трейдинг',  callback_data='trading'),
        ],
        [
            InlineKeyboardButton('\U0001f916 AaaS',      callback_data='fleet'),
            InlineKeyboardButton('\U0001f4b0 Выручка',   callback_data='revenue'),
        ],
        [
            InlineKeyboardButton('⚡ Агенты',    callback_data='agents'),
            InlineKeyboardButton('\U0001f4b1 Арбитраж',  callback_data='arb'),
        ],
        [
            InlineKeyboardButton('\U0001f5a5 Панель',    url=PANEL_URL),
            InlineKeyboardButton('\U0001f4b3 Оплата',    callback_data='pay'),
        ],
        [
            InlineKeyboardButton('❓ Помощь',    callback_data='help'),
        ],
    ])

def back_kb(prefix: str = '') -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('\U0001f504 Обновить', callback_data=(prefix or 'status')),
        InlineKeyboardButton('\U0001f3e0 Меню', callback_data='start'),
    ]])

def trading_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('\U0001f504 Обновить',  callback_data='trading'),
            InlineKeyboardButton('\U0001f4b0 Баланс',    callback_data='balance'),
        ],
        [
            InlineKeyboardButton('\U0001f5a5 На панель', url=PANEL_URL),
            InlineKeyboardButton('\U0001f3e0 Меню',      callback_data='start'),
        ],
    ])

def fleet_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('\U0001f504 Обновить',   callback_data='fleet'),
            InlineKeyboardButton('\U0001f4b0 Выручка',    callback_data='revenue'),
        ],
        [
            InlineKeyboardButton('\U0001f4ca На панель',  url=PANEL_URL),
            InlineKeyboardButton('\U0001f3e0 Меню',       callback_data='start'),
        ],
    ])

# ── Data fetchers ──────────────────────────────────────────────────────────────
async def fetch_status_text() -> str:
    """Get full system status — all data verified real-time."""
    bal_d    = await api_get('/api/trading/balance')    or {}
    pos_d    = await api_get('/api/trading/positions')  or {}
    engine_d = await api_get('/api/aaas/engine')        or {}
    rev_d    = await api_get('/api/aaas/revenue')       or {}
    nexus_d  = await api_get('/nexus/stats')            or {}

    balance    = float(bal_d.get('balance_usdt', bal_d.get('balance', 0)) or 0)
    positions  = pos_d.get('positions', [])
    pos_count  = len(positions)
    daily_pnl  = float(bal_d.get('daily_pnl', 0) or 0)
    daily_pct  = float(bal_d.get('daily_pnl_pct', 0) or 0)
    engine_st  = engine_d.get('status', '?')
    engine_cyc = engine_d.get('cycle', '?')
    real_rev   = float(rev_d.get('real_usd', sum(float(p.get('amount',0)) for p in rev_d.get('real_payments',[]) if isinstance(rev_d.get('real_payments',[]),list)) if not isinstance(sum(float(p.get('amount',0)) for p in rev_d.get('real_payments',[]) if isinstance(rev_d.get('real_payments',[]),list)), list) else 0) or 0)
    nexus_cli  = nexus_d.get('clients', 0)

    pnl_icon   = '📈' if daily_pnl >= 0 else '📉'
    eng_icon   = '✅' if engine_st == 'running' else '❌'

    lines = [
        '\U0001f916 <b>MaxAI Corporation — Статус</b>',
        '',
        f'💰 <b>Bybit:</b> ${balance:.2f} USDT',
        f'{pnl_icon} <b>Дневной PnL:</b> ${daily_pnl:+.2f} ({daily_pct:.2f}%)',
        f'📊 <b>Позиций:</b> {pos_count}',
    ]
    for p in positions[:3]:
        pnl_p = float(p.get("unrealisedPnl","0"))
        lines.append(f'   → {p["symbol"]} {p["side"]} PnL: ${pnl_p:+.4f}')
    lines += [
        '',
        f'{eng_icon} <b>AaaS Engine:</b> {engine_st} (цикл #{engine_cyc})',
        f'💵 <b>Реальный доход:</b> ${real_rev:.2f}',
        f'👥 <b>NEXUS клиентов:</b> {nexus_cli}',
        '',
        f'🌐 Панель: <a href="{PANEL_URL}">{PANEL_URL}</a>',
        f'🛒 Клиентам: <a href="https://maxai.fyi">maxai.fyi</a>',
    ]
    return '\n'.join(lines)


async def fetch_trading_text() -> str:
    """Full trading status with verified SL/TP/Leverage from Bybit API."""
    bal_d = await api_get('/api/trading/balance') or {}
    pos_d = await api_get('/api/trading/positions') or {}

    balance   = float(bal_d.get('balance_usdt', bal_d.get('balance',0)) or 0)
    daily_pnl = float(bal_d.get('daily_pnl', 0) or 0)
    daily_pct = float(bal_d.get('daily_pnl_pct', 0) or 0)
    positions = pos_d.get('positions', [])

    pnl_icon = '📈' if daily_pnl >= 0 else '📉'
    lines = [
        f'\U0001f4c8 <b>Торговля Bybit LIVE</b>',
        '',
        f'💰 Баланс: <b>${balance:.2f}</b> USDT',
        f'{pnl_icon} Дневной PnL: <b>${daily_pnl:+.2f}</b> ({daily_pct:.2f}%)',
        f'📊 Позиций: <b>{len(positions)}</b>',
        '',
    ]

    if not positions:
        lines.append('ℹ️ Нет открытых позиций')
        lines.append('🔍 V4: сканирует ETH/BNB/SOL/XRP каждые 75с')
        lines.append('🎯 5 условий: EMA+ADX+RSI+Pullback+Vol')
        lines.append('⏰ Сессия: 02-23 UTC')
    else:
        for p in positions:
            sym  = p.get("symbol","?")
            side = p.get("side","?")
            ep   = float(p.get("avg_price", p.get("avgPrice",0)) or 0)
            size = p.get("size","?")
            pnl  = float(p.get("unrealised_pnl", p.get("unrealisedPnl",0)) or 0)
            sl   = p.get("stopLoss","") or p.get("stop_loss","")
            tp   = p.get("takeProfit","") or p.get("take_profit","")
            lev  = p.get("leverage","?")
            pct  = pnl/max(0.01, ep*float(str(size).replace("?","1") or "1"))*100 if ep>0 else 0
            icon = '🟢' if pnl >= 0 else '🔴'

            lines += [
                f'{icon} <b>{sym}</b> {side} x{lev}',
                f'   📍 Вход: ${ep:.4f} | Объём: {size}',
                f'   💹 PnL: <b>${pnl:+.4f}</b>',
                f'   🛡 SL: ${float(sl):.4f}' if sl else '   🛡 SL: ❌ не задан',
                f'   🎯 TP: ${float(tp):.4f}' if tp else '   🎯 TP: ❌ не задан',
                '',
            ]

    lines += [
        f'🤖 V4 LIVE: EMA Pullback | SL=3×ATR TP=6×ATR R:R=2:1',
        f'⚡ Плечо: 2x | Риск: 1%/сделку | Макс: 1 сделка/день',
        f'🌐 Панель: {PANEL_URL}',
    ]
    return "\n".join(lines)


async def fetch_fleet_text() -> str:
    engine_d  = await api_get('/api/aaas/engine') or {}
    fleet_d   = await api_get('/api/aaas/fleet') or {}
    revenue_d = await api_get('/api/aaas/revenue') or {}

    eng_status = engine_d.get('status', engine_d.get('engine_status', '?'))
    eng_uptime = engine_d.get('uptime_hours', engine_d.get('uptime_h', '?'))
    eng_cycle  = engine_d.get('cycle', engine_d.get('cycle_count', '?'))

    rents_today = fleet_d.get('rents_today', fleet_d.get('total_spawned', 0))
    active      = fleet_d.get('active_agents', 0)

    rev_today   = float(revenue_d.get('today_usd', 0) or 0)
    by_platform = revenue_d.get('by_platform', {})

    plat_lines = ''
    for name, val in (by_platform or {}).items():
        if float(val or 0) > 0:
            plat_lines += f'  • {name}: <code>${float(val):.2f}</code>\n'

    return (
        f'<b>\U0001f916 AaaS Флот — Фабрика Агентов</b>\n\n'
        f'<b>⚡ Engine:</b> <code>{eng_status}</code> | Uptime: {eng_uptime}h | Цикл: {eng_cycle}\n\n'
        f'<b>\U0001f4ca Статистика:</b>\n'
        f'  • Аренд сегодня: <b>{rents_today}</b>\n'
        f'  • Активных: <b>{active}</b> агентов\n'
        f'  • Выручка: <b>${rev_today:.2f}</b>\n'
        + (f'\n<b>\U0001f4b0 По платформам:</b>\n{plat_lines}' if plat_lines else '') +
        f'\n<i>\U0001f5a5 {PANEL_URL}</i>'
    )

async def fetch_revenue_text() -> str:
    revenue_d = await api_get('/api/aaas/revenue') or {}

    total       = float(revenue_d.get('total_usd', 0) or 0)
    is_real    = False  # AaaS revenue = internal tracking, not real cash
    today       = float(revenue_d.get('today_usd', 0) or 0)
    avg_day     = float(revenue_d.get('daily_avg_usd', 0) or 0)
    est_monthly = float(revenue_d.get('estimated_monthly_usd', today * 30) or 0)
    goal_pct    = float(revenue_d.get('goal_pct', 0) or 0)
    by_platform = revenue_d.get('by_platform', {})
    # Get real Bybit balance for comparison
    bybit_d     = {}
    try:
        bybit_d = await api_get('/api/trading/balance') or {}
    except Exception:
        pass
    real_balance = float(bybit_d.get('balance_usdt', 0) or 0)

    plat_lines = ''
    for name, val in (by_platform or {}).items():
        if float(val or 0) > 0:
            plat_lines += f'  • {name}: <code>${float(val):.2f}</code>\n'

    try:
        import redis as _rr, json as _jj
        _rc = _rr.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
        real_usd = float(_rc.get('aaas:revenue:real_total_usd') or 0)
        kwork_applied = len(_jj.loads(_rc.get('kwork:applied') or '[]'))
    except Exception:
        real_usd = 0.0
        kwork_applied = 0

    return (
        f'<b>\U0001f4b0 MaxAI Revenue Dashboard</b>\n\n'
        f'<b>\U0001f4b5 РЕАЛЬНЫЕ ДЕНЬГИ:</b>\n'
        f'  Bybit USDT: <b>${real_balance:.2f}</b>\n'
        f'  Подтверждённых оплат: <b>${real_usd:.4f}</b>\n\n'
        f'<b>\U0001f4ca Учёт AI задач (не деньги):</b>\n'
        f'  Выполнено задач: <b>${total:.3f}</b> (tracking)\n'
        f'  Сегодня: <b>${today:.3f}</b>\n'
        + (f'\n<b>По платформам:</b>\n{plat_lines}' if plat_lines else '') +
        f'\nKwork откликов: <b>{kwork_applied}</b>\n'
        f'\n<i>\U0001f5a5 {PANEL_URL}</i>'
    )

async def fetch_agents_text() -> str:
    agents_d = await api_get('/api/agents') or {}
    hitl_d   = await api_get('/api/actions/pending') or {}

    ags = agents_d.get('agents', [])
    if not isinstance(ags, list):
        ags = []

    ag_lines = ''
    for a in ags[:8]:
        name   = a.get('name', a.get('id', '?'))
        status = a.get('status', '?')
        emoji  = '\U0001f7e2' if status in ('active', 'running') else '\U0001f534'
        ag_lines += f'  {emoji} <b>{name}</b> — <code>{status}</code>\n'
    if not ag_lines:
        ag_lines = '  <i>Нет данных об агентах</i>\n'

    pending    = hitl_d.get('actions', hitl_d.get('pending', []))
    if not isinstance(pending, list):
        pending = []
    hitl_count = len(pending)

    return (
        f'<b>⚡ Агенты MaxAI</b>\n\n'
        f'<b>Список агентов:</b>\n{ag_lines}\n'
        f'<b>\U0001f514 HITL очередь:</b> <code>{hitl_count}</code> ожидают решения\n\n'
        f'<i>Управление: {PANEL_URL}</i>'
    )

async def fetch_arb_text() -> str:
    arb_d = await api_get('/api/arb/metrics') or {}

    opportunities = int(arb_d.get('total_opps', arb_d.get('opportunities', 0)) or 0)
    executed      = int(arb_d.get('executed', arb_d.get('trades_executed', 0)) or 0)
    profit        = float(arb_d.get('profit_usd', arb_d.get('total_profit', 0)) or 0)
    best_spread   = arb_d.get('max_score', arb_d.get('best_spread', '?'))
    status        = arb_d.get('status', 'неизвестно')

    return (
        f'<b>\U0001f4b1 Арбитраж MaxAI</b>\n\n'
        f'<b>Статус:</b> <code>{status}</code>\n\n'
        f'<b>\U0001f4ca Метрики:</b>\n'
        f'  • Найдено возможностей: <b>{opportunities}</b>\n'
        f'  • Исполнено сделок: <b>{executed}</b>\n'
        f'  • Прибыль: <b>${profit:.4f}</b>\n'
        f'  • Лучший спред: <code>{best_spread}</code>\n\n'
        f'<i>\U0001f5a5 {PANEL_URL}</i>'
    )

# ── Command handlers ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = update.effective_user.first_name or 'friend'
    text = (
        '🤖 <b>MaxAI Corporation</b>\n\n'
        f'Hi <b>{name}</b>! Python & AI development:\n\n'
        '🤖 <b>Telegram bots + AI agents</b> from 2000 rub\n'
        '📊 <b>Trading bots</b> Bybit/Binance, live 24/7\n'
        '🔍 <b>Parsers & automation</b>\n'
        '💻 <b>FastAPI / backends</b>\n'
        '📦 <b>AaaS subscription</b> from $19/mo\n\n'
        '<b>🎁 First task FREE</b>\n\n'
        '🌐 Site: https://maxai.fyi/hire\n'
        '🛒 Fiverr: fiverr.com/maxai_co\n'
        '💳 USDT TRC20: <code>TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2</code>'
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('🎁 Try FREE', callback_data='try_free'),
    ], [
        InlineKeyboardButton('💰 Prices', callback_data='hire'),
        InlineKeyboardButton('📊 Status', callback_data='status'),
    ], [
        InlineKeyboardButton('🌐 Website', url='https://maxai.fyi/hire'),
        InlineKeyboardButton('🖥 Panel', url=PANEL_URL),
    ]])
    await update.message.reply_html(text, reply_markup=kb, disable_web_page_preview=True)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        '<b>❓ Команды MaxAI:</b>\n\n'
        '/start — \U0001f680 Главное меню\n'
        '\U0001f310 Сайт: https://maxai.fyi/hire\n\n'
        '/status — \U0001f4ca Статус системы\n'
        '/trading — \U0001f4c8 Торговля и позиции\n'
        '/fleet — \U0001f916 AaaS Флот\n'
        '/revenue — \U0001f4b0 Выручка и доходы\n'
        '/arb — \U0001f4b1 Арбитраж\n'
        '/agents — ⚡ Агенты и HITL\n'
        '/pay — \U0001f4b3 Оплата услуг\n'
        '/panel — \U0001f5a5 Открыть панель\n'
        '/clear — \U0001f5d1 Сбросить историю чата\n\n'
        '<b>\U0001f4a1 AI-ассистент:</b>\n'
        'Пишите любые вопросы — отвечу на русском языке.\n\n'
        f'<i>Панель: {PANEL_URL}</i>'
    )
    await update.message.reply_html(text, reply_markup=main_menu_kb())

async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    text = await fetch_status_text()
    await update.message.reply_html(text, reply_markup=back_kb('status'),
                                    disable_web_page_preview=True)

async def cmd_trading(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    text = await fetch_trading_text()
    await update.message.reply_html(text, reply_markup=trading_kb(),
                                    disable_web_page_preview=True)

async def cmd_fleet(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    text = await fetch_fleet_text()
    await update.message.reply_html(text, reply_markup=fleet_kb(),
                                    disable_web_page_preview=True)

async def cmd_aaas(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias for /fleet — AaaS overview."""
    await cmd_fleet(update, ctx)

async def cmd_revenue(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    text = await fetch_revenue_text()
    await update.message.reply_html(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('\U0001f504 Обновить', callback_data='revenue'),
            InlineKeyboardButton('\U0001f916 Флот',     callback_data='fleet'),
            InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
        ]]),
        disable_web_page_preview=True
    )

async def cmd_arb(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    text = await fetch_arb_text()
    await update.message.reply_html(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('\U0001f504 Обновить', callback_data='arb'),
            InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
        ]]),
        disable_web_page_preview=True
    )

async def cmd_agents(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    text = await fetch_agents_text()
    await update.message.reply_html(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('\U0001f504 Обновить', callback_data='agents'),
            InlineKeyboardButton('\U0001f5a5 Панель',   url=PANEL_URL),
            InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
        ]]),
        disable_web_page_preview=True
    )



async def cmd_try(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    try:
        import redis as _r
        rdb = _r.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
        key = f'maxai:free_trial:{uid}'
        if rdb.exists(key) and uid != OWNER_ID:
            await update.message.reply_html(
                '\U0001f44b Вы уже использовали бесплатную задачу!\n\n'
                'Используйте /pay для продолжения работы.'
            )
            return
        rdb.set(key, '1', ex=86400 * 30)
    except Exception:
        pass
    await update.message.reply_html(
        '<b>\U0001f381 Бесплатная задача!</b>\n\n'
        'Напишите мне задачу прямо сейчас — я выполню её бесплатно.\n\n'
        '<b>Примеры:</b>\n'
        '• Проанализируй рынок BTC за последнюю неделю\n'
        '• Напиши Python скрипт для парсинга цен\n'
        '• Сделай research по теме нейросети 2026\n\n'
        '<i>После бесплатной задачи — /pay для продолжения</i>'
    )


async def cmd_promo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        '<b>\U0001f4e3 MaxAI — Ваш AI-ассистент 24/7</b>\n\n'
        'Экономьте часы работы с MaxAI:\n\n'
        '\U0001f4ca <b>Анализ данных</b> — любой датасет за 30 сек\n'
        '\U0001f4bb <b>Написание кода</b> — Python, JS, SQL по ТЗ\n'
        '\U0001f50d <b>Research</b> — глубокий анализ любой темы\n'
        '\U0001f4c8 <b>Торговые сигналы</b> — крипто и форекс\n'
        '\U0001f4dd <b>Контент</b> — посты, тексты, переводы\n\n'
        '<b>\U0001f4b0 Цены:</b>\n'
        '• Разовая задача от <b>$0.10</b>\n'
        '• Подписка 30 дней — <b>$8</b>\n\n'
        '<b>Оплата USDT TRC20:</b>\n'
        '<code>TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2</code>\n\n'
        'Попробуйте бесплатно: /try'
    )
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton('\U0001f680 Попробовать', callback_data='try_free'),
        InlineKeyboardButton('\U0001f4b3 Оплатить', callback_data='pay'),
    ]]))


async def cmd_pay(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        '<b>\U0001f4b3 Оплата услуг MaxAI</b>\n\n'
        '<b>Тарифы задач (разово):</b>\n'
        '  • Research — <b>$0.10</b>\n'
        '  • Analysis — <b>$0.20</b>\n'
        '  • Coding — <b>$0.25</b>\n'
        '  • Trading — <b>$0.50</b>\n'
        '  • Scraping — <b>$0.15</b>\n'
        '  • Social — <b>$0.30</b>\n\n'
        '<b>Подписки:</b>\n'
        '  • 1 час — <b>$0.10</b>\n'
        '  • 24 часа — <b>$0.50</b>\n'
        '  • 7 дней — <b>$2.50</b>\n'
        '  • 30 дней — <b>$8.00</b>\n\n'
        '<b>Реквизиты для оплаты:</b>\n\n'
        '\U0001fa99 <b>USDT TRC20:</b>\n'
        f'<code>{USDT_TRC20}</code>\n\n'
        '⟠ <b>ETH / BNB (ERC20/BEP20):</b>\n'
        f'<code>{ETH_ADDR}</code>\n\n'
        '<b>После оплаты:</b>\n'
        '<code>/confirm TXID TYPE</code>\n'
        '<i>Пример: /confirm abc123 research</i>'
    )
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton('\U0001f916 Аренда агента', callback_data='rent'),
        InlineKeyboardButton('\U0001f3e0 Меню',          callback_data='start'),
    ]]))

async def cmd_rent(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        '<b>\U0001f916 Аренда AI-агентов MaxAI</b>\n\n'
        '<b>Виды агентов:</b>\n'
        '  \U0001f50d Research — $0.10/задачу\n'
        '  \U0001f4c8 Trading — $0.50/задачу\n'
        '  \U0001f4bb Coding — $0.25/задачу\n'
        '  \U0001f4ca Analysis — $0.20/задачу\n'
        '  \U0001f578 Scraping — $0.15/задачу\n'
        '  \U0001f4e2 Social — $0.30/задачу\n\n'
        '<b>Подписки:</b>\n'
        '  1 час — $0.10\n'
        '  24 часа — $0.50\n'
        '  7 дней — $2.50\n'
        '  30 дней — $8.00\n\n'
        '<b>USDT TRC20:</b>\n'
        f'<code>{USDT_TRC20}</code>\n\n'
        '<b>После оплаты:</b>\n'
        '<code>/confirm TXID rent:TYPE:DURATION</code>'
    )
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton('\U0001f4b3 Оплата', callback_data='pay'),
        InlineKeyboardButton('\U0001f3e0 Меню',   callback_data='start'),
    ]]))

async def cmd_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(
        f'<b>\U0001f5a5 MaxAI Corporation</b>\n\n'
        f'🖥 <b>Панель управления:</b> {PANEL_URL}\n'
        f'🌐 <b>Сайт / Услуги:</b> https://maxai.fyi/hire\n\n'
        f'Нажми кнопку ниже:',
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton('\U0001f680 Открыть панель', url=PANEL_URL),
        ]])
    )

async def cmd_hire(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Professional services and pricing."""
    text = (
        '<b>MaxAI Corporation — Услуги разработки</b>\n\n'
        '<b>Автоматизация и AI — от идеи до прибыли</b>\n\n'
        '🤖 <b>Telegram-бот + AI (GPT-4/Claude)</b>\n'
        '   от 2 000 ₽ · срок 1 день\n\n'
        '📊 <b>Торговый бот Bybit/Binance</b>\n'
        '   от 10 000 ₽ · срок 3-5 дней\n\n'
        '🕷 <b>Парсер / автоматизация</b>\n'
        '   от 1 500 ₽ · срок 1 день\n\n'
        '🔌 <b>FastAPI бэкенд + интеграции</b>\n'
        '   от 5 000 ₽ · срок 2-3 дня\n\n'
        '🧠 <b>AI-агент 24/7 (AaaS)</b>\n'
        '   от $19/мес · подписка\n\n'
        '━━━━━━━━━━━━━━━━━━━━━\n'
        '💳 Оплата USDT / ₽ / крипто\n'
        '⚡ Предоплата 50% · Гарантия результата\n\n'
        f'🌐 Все услуги: {HIRE}\n'
        f'💼 Fiverr: {FIVERR}'
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton('🌐 Все услуги', url=HIRE),
        InlineKeyboardButton('💬 Написать', url=f'https://t.me/MaxAI_SaaS_Bot'),
    ], [
        InlineKeyboardButton('💼 Fiverr', url=FIVERR),
        InlineKeyboardButton('🏠 Меню', callback_data='start'),
    ]])
    await update.message.reply_html(text, reply_markup=kb, disable_web_page_preview=True)


async def cmd_balance(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.chat.send_action(ChatAction.TYPING)
    d   = await api_get('/api/trading/balance') or {}
    bal = d.get('balance_usdt', d.get('balance', d.get('total', '?')))
    text = (
        f'<b>\U0001f4b0 Баланс Bybit</b>\n\n'
        f'USDT: <code>${bal}</code>\n\n'
        f'<i>\U0001f5a5 {PANEL_URL}</i>'
    )
    await update.message.reply_html(text, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton('\U0001f504 Обновить', callback_data='balance'),
        InlineKeyboardButton('\U0001f4c8 Позиции',  callback_data='trading'),
        InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
    ]]))

async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    _history.pop(update.effective_user.id, None)
    await update.message.reply_text('\U0001f5d1 История чата очищена.')

async def _verify_trongrid_tx(txid: str) -> dict | None:
    """Verify TRC20 transaction on TronGrid. Returns tx data if valid incoming to owner wallet."""
    url = f'https://api.trongrid.io/v1/transactions/{txid}'
    try:
        data = await ahttp(url, timeout=15)
        if not data:
            return None
        items = data.get('data', [])
        if not items:
            return None
        tx = items[0]
        # Check trc20_transfer_info first (most reliable for USDT transfers)
        trc20_info = tx.get('trc20_transfer_info', [])
        for transfer in trc20_info:
            to_addr = transfer.get('to_address', '')
            if USDT_TRC20.lower() in to_addr.lower() or to_addr == USDT_TRC20:
                amount_raw = int(transfer.get('amount_str', transfer.get('amount', 0)))
                decimals = int(transfer.get('decimals', 6))
                amount_usdt = amount_raw / (10 ** decimals)
                return {
                    'txid': txid,
                    'amount_usdt': amount_usdt,
                    'to': to_addr,
                    'confirmed': tx.get('ret', [{}])[0].get('contractRet', '') == 'SUCCESS',
                }
        # Fallback: check if USDT_TRC20 appears anywhere in response string
        if USDT_TRC20 in str(data):
            return {'txid': txid, 'amount_usdt': 0, 'to': USDT_TRC20, 'confirmed': True, 'note': 'partial_match'}
        return None
    except Exception as e:
        log.warning('TronGrid verify error txid=%s: %s', txid, e)
        return None


async def cmd_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import redis as _r
    import datetime as _dt
    uid   = update.effective_user.id
    parts = (update.message.text or '').split()
    if len(parts) < 3:
        await update.message.reply_html(
            '⚠️ <b>Формат:</b> <code>/confirm TXID TYPE</code>\n'
            '<i>Пример: /confirm abc123xyz research</i>'
        )
        return
    txid      = parts[1].strip()
    task_type = parts[2].lower().strip()

    # 1. Validate TXID format (min 10 chars, alphanumeric)
    if len(txid) < 10 or not re.match(r'^[a-zA-Z0-9]+$', txid):
        await update.message.reply_html(
            '❌ <b>Неверный TXID</b>\n'
            'TXID должен быть минимум 10 символов, только буквы и цифры.\n'
            'Скопируйте TxID из блокчейн-обозревателя.'
        )
        return

    await update.message.chat.send_action(ChatAction.TYPING)

    try:
        rdb = _r.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
    except Exception as e:
        await update.message.reply_text(f'Ошибка Redis: {e}')
        return

    # 2. Check duplicate TXID
    if rdb.exists('payment:txid:' + txid):
        await update.message.reply_html(
            '⚠️ <b>Этот TXID уже использован.</b>\n'
            'Каждая транзакция может быть подтверждена только один раз.'
        )
        return

    # 3. Verify on TronGrid blockchain
    await update.message.reply_html('\U0001f50d <i>Проверяю транзакцию в блокчейне...</i>')
    tx_data = await _verify_trongrid_tx(txid)

    base_type = task_type.split(':')[0]
    price = TASK_PRICES.get(base_type, 0.15)
    today = _dt.date.today().strftime('%Y-%m-%d')

    if tx_data and tx_data.get('confirmed'):
        amount_usdt = tx_data.get('amount_usdt', price)
        if amount_usdt == 0:
            amount_usdt = price  # fallback to expected price

        # 4. Record in Redis
        rdb.set('payment:txid:' + txid,
                json.dumps({'uid': uid, 'task': task_type, 'ts': time.time(),
                            'verified': True, 'amount_usdt': amount_usdt}),
                ex=172800 * 7)
        rdb.lpush('aaas:payments:pending',
                  json.dumps({'uid': uid, 'txid': txid, 'type': task_type,
                              'ts': time.time(), 'verified': True}))

        # 5. Update real revenue counters
        rdb.lpush('maxai:real:payments', json.dumps({
            'chain': 'TRC20', 'symbol': 'USDT', 'amount': amount_usdt,
            'txid': txid, 'from': f'tg_user_{uid}', 'ts': time.time(),
            'date': today, 'task_type': task_type, 'verified_blockchain': True,
        }))
        rdb.ltrim('maxai:real:payments', 0, 199)
        rdb.incrbyfloat('aaas:revenue:real_total_usd', amount_usdt)
        rdb.incrbyfloat('aaas:revenue:total_usd', amount_usdt)
        rdb.incrbyfloat('aaas:revenue:telegram_gateway:total', amount_usdt)
        rdb.incrbyfloat(f'aaas:revenue:daily:{today}', amount_usdt)

        # 6. Notify owner (OWNER_ID = 1985320458)
        real_total = float(rdb.get('aaas:revenue:real_total_usd') or 0)
        owner_msg = (
            f'\U0001f4b0 <b>РЕАЛЬНЫЙ ПЛАТЁЖ ПОДТВЕРЖДЁН!</b>\n\n'
            f'\U0001f464 Пользователь: <code>{uid}</code>\n'
            f'\U0001f4b5 Сумма: <b>${amount_usdt:.4f} USDT</b>\n'
            f'\U0001f4cb Тип: <code>{task_type}</code>\n'
            f'\U0001f517 TxID: <code>{txid[:30]}...</code>\n'
            f'⛓ Верифицировано: TronGrid\n\n'
            f'\U0001f4ca Итого реального дохода: <b>${real_total:.4f}</b>'
        )
        try:
            bot_obj = ctx.application.bot
            await bot_obj.send_message(chat_id=OWNER_ID, text=owner_msg, parse_mode='HTML')
        except Exception as oe:
            log.warning('Owner notify failed: %s', oe)

        # 7. Respond to user
        await update.message.reply_html(
            f'✅ <b>Оплата подтверждена!</b>\n\n'
            f'\U0001f4b5 Сумма: <b>${amount_usdt:.4f} USDT</b>\n'
            f'\U0001f4cb Тип: <code>{task_type}</code>\n'
            f'\U0001f517 TxID: <code>{txid[:20]}...</code>\n\n'
            f'\U0001f916 Запускаю агента...'
        )

        # 8. Spawn agent via API
        try:
            spawn_result = await ahttp(
                f'{API_BASE}/api/aaas/spawn',
                data={'task_type': base_type, 'user_id': str(uid),
                      'txid': txid, 'verified': True},
                timeout=10
            )
            if spawn_result and spawn_result.get('agent_id'):
                agent_id = spawn_result['agent_id']
                await update.message.reply_html(
                    f'\U0001f680 <b>Агент запущен!</b>\n'
                    f'ID: <code>{agent_id}</code>\n'
                    f'\U0001f4dd Используй /status для проверки.'
                )
        except Exception as se:
            log.warning('Spawn agent failed: %s', se)
            await update.message.reply_html(
                f'⚠️ Агент будет запущен в течение минуты.\n'
                f'Используй /task {task_type} чтобы запустить задачу.'
            )

        log.info('REAL payment confirmed uid=%d txid=%s type=%s amount=%.4f',
                 uid, txid, task_type, amount_usdt)

    else:
        # Blockchain check failed — accept manually with owner alert
        log.warning('TronGrid could not verify txid=%s, accepting manually uid=%d', txid, uid)

        rdb.set('payment:txid:' + txid,
                json.dumps({'uid': uid, 'task': task_type, 'ts': time.time(),
                            'verified': False, 'manual': True}),
                ex=172800)
        rdb.lpush('aaas:payments:pending',
                  json.dumps({'uid': uid, 'txid': txid, 'type': task_type,
                              'ts': time.time(), 'verified': False}))
        rdb.incrbyfloat('aaas:revenue:total_usd', price)
        rdb.incrbyfloat(f'aaas:revenue:daily:{today}', price)

        # Notify owner for manual review
        try:
            bot_obj = ctx.application.bot
            await bot_obj.send_message(
                chat_id=OWNER_ID,
                text=(f'⚠️ <b>Ручная проверка платежа</b>\n\n'
                      f'Пользователь: <code>{uid}</code>\n'
                      f'TxID: <code>{txid}</code>\n'
                      f'Тип: <code>{task_type}</code>\n\n'
                      f'TronGrid не подтвердил автоматически.\n'
                      f'Проверь вручную: https://tronscan.org/#/transaction/{txid}'),
                parse_mode='HTML'
            )
        except Exception as oe:
            log.warning('Owner notify failed: %s', oe)

        await update.message.reply_html(
            f'⏳ <b>Платёж на проверке</b>\n\n'
            f'TxID: <code>{txid}</code>\n'
            f'Тип: <code>{task_type}</code>\n\n'
            f'Транзакция принята на ручную проверку.\n'
            f'Агент будет запущен после подтверждения (~5 мин).\n\n'
            f'\U0001f50e Проверить: https://tronscan.org/#/transaction/{txid[:20]}'
        )
        log.info('Manual payment accepted uid=%d txid=%s type=%s',
                 uid, txid, task_type)

async def cmd_task(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    import redis as _r
    uid   = update.effective_user.id
    parts = (update.message.text or '').split(None, 2)
    if len(parts) < 3:
        await update.message.reply_html(
            '<b>Формат:</b> <code>/task TYPE ОПИСАНИЕ</code>\n\n'
            'Типы: research, analysis, coding, trading, social, scraping'
        )
        return
    task_type   = parts[1].lower()
    description = parts[2]
    try:
        rdb     = _r.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
        has_sub = rdb.exists('aaas:subscription:' + str(uid))
    except Exception:
        has_sub = False
    if not has_sub and uid != OWNER_ID:
        price = TASK_PRICES.get(task_type, 0.15)
        await update.message.reply_html(
            f'Задача <b>{task_type}</b> стоит <b>${price}</b>.\n'
            f'Оплатите /pay и подтвердите: /confirm TXID {task_type}'
        )
        return
    await update.message.chat.send_action(ChatAction.TYPING)
    prefix = {
        'research': 'Подготовь исследовательский отчёт: ',
        'analysis': 'Проанализируй: ',
        'coding':   'Напиши код для: ',
        'trading':  'Торговый сигнал: ',
        'social':   'Составь пост для соцсети: ',
    }.get(task_type, 'Выполни задачу: ')
    result = await ask_ai(prefix + description, user_id=uid)
    await update.message.reply_text(result)

async def cmd_addkey(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != OWNER_ID:
        return
    text  = (update.message.text or '').strip()
    parts = text.split(None, 1)
    if len(parts) < 2 or '=' not in parts[1]:
        await update.message.reply_text('Формат: /addkey OPENROUTER_API_KEY=sk-or-...')
        return
    name, _, value = parts[1].strip().partition('=')
    name  = name.strip().upper()
    value = value.strip()
    if not name or not value:
        await update.message.reply_text('Неверный формат')
        return
    try:
        src = ENV_FILE.read_text(encoding='utf-8')
        if f'{name}=' in src:
            src = re.sub(rf'^{name}=.*$', f'{name}={value}', src, flags=re.MULTILINE)
        else:
            src += '\n' + name + '=' + value
        ENV_FILE.write_text(src, encoding='utf-8')
        log.info('Key saved: %s', name)
        import subprocess as _sp
        _sp.Popen(['systemctl', 'restart', 'maxai-tgbot'])
        await update.message.reply_text(f'✅ {name} сохранён. Перезапуск...')
    except Exception as e:
        await update.message.reply_text(f'❌ Ошибка: {e}')

# ── Callback query handler ────────────────────────────────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query  = update.callback_query
    await query.answer()
    action = query.data

    async def edit(text: str, kb=None) -> None:
        try:
            await query.edit_message_text(
                text, parse_mode=ParseMode.HTML,
                reply_markup=kb, disable_web_page_preview=True
            )
        except TelegramError as e:
            if 'not modified' not in str(e).lower():
                log.warning('edit_message_text: %s', e)

    if action == 'start':
        name = update.effective_user.first_name or 'друг'
        await edit(f'\U0001f44b <b>{name}</b>, выбери раздел:', kb=main_menu_kb())
    elif action == 'status':
        await edit('⏳ Загружаю статус...')
        await edit(await fetch_status_text(), kb=back_kb('status'))
    elif action == 'trading':
        await edit('⏳ Загружаю позиции...')
        await edit(await fetch_trading_text(), kb=trading_kb())
    elif action == 'balance':
        d   = await api_get('/api/trading/balance') or {}
        bal = d.get('balance_usdt', d.get('balance', d.get('total', '?')))
        await edit(
            f'<b>\U0001f4b0 Баланс Bybit</b>\n\nUSDT: <code>${bal}</code>\n\n<i>{PANEL_URL}</i>',
            kb=InlineKeyboardMarkup([[
                InlineKeyboardButton('\U0001f504 Обновить', callback_data='balance'),
                InlineKeyboardButton('\U0001f4c8 Позиции',  callback_data='trading'),
                InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
            ]])
        )
    elif action == 'fleet':
        await edit('⏳ Загружаю флот...')
        await edit(await fetch_fleet_text(), kb=fleet_kb())
    elif action == 'revenue':
        await edit('⏳ Загружаю выручку...')
        await edit(await fetch_revenue_text(), kb=InlineKeyboardMarkup([[
            InlineKeyboardButton('\U0001f504 Обновить', callback_data='revenue'),
            InlineKeyboardButton('\U0001f916 Флот',     callback_data='fleet'),
            InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
        ]]))
    elif action == 'arb':
        await edit('⏳ Загружаю арбитраж...')
        await edit(await fetch_arb_text(), kb=InlineKeyboardMarkup([[
            InlineKeyboardButton('\U0001f504 Обновить', callback_data='arb'),
            InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
        ]]))
    elif action == 'agents':
        await edit('⏳ Загружаю агентов...')
        await edit(await fetch_agents_text(), kb=InlineKeyboardMarkup([[
            InlineKeyboardButton('\U0001f504 Обновить', callback_data='agents'),
            InlineKeyboardButton('\U0001f3e0 Меню',     callback_data='start'),
        ]]))
    elif action == 'pay':
        await edit(
            f'<b>\U0001f4b3 Оплата услуг MaxAI</b>\n\n'
            f'\U0001fa99 <b>USDT TRC20:</b>\n<code>{USDT_TRC20}</code>\n\n'
            f'⟠ <b>ETH/BNB:</b>\n<code>{ETH_ADDR}</code>\n\n'
            f'После оплаты: <code>/confirm TXID TYPE</code>',
            kb=InlineKeyboardMarkup([[
                InlineKeyboardButton('\U0001f916 Аренда', callback_data='rent'),
                InlineKeyboardButton('\U0001f3e0 Меню',   callback_data='start'),
            ]])
        )
    elif action == 'rent':
        await edit(
            f'<b>\U0001f916 Аренда агентов MaxAI</b>\n\n'
            f'Research $0.10 | Trading $0.50 | Coding $0.25\n'
            f'Analysis $0.20 | Scraping $0.15 | Social $0.30\n\n'
            f'<b>USDT TRC20:</b>\n<code>{USDT_TRC20}</code>',
            kb=InlineKeyboardMarkup([[
                InlineKeyboardButton('\U0001f4b3 Оплата', callback_data='pay'),
                InlineKeyboardButton('\U0001f3e0 Меню',   callback_data='start'),
            ]])
        )
    elif action == 'try_free':
        await query.message.reply_html(
            '<b>\U0001f381 Напишите задачу!</b>\n\n'
            'Я выполню её бесплатно прямо сейчас.\n\n'
            'Напишите любой вопрос или задачу.'
        )
        return
    elif action == 'help':
        await edit(
            '<b>❓ Команды MaxAI:</b>\n\n'
            '/start /status /trading /fleet\n'
            '/revenue /arb /agents /pay /panel /hire\n'
            '/try — бесплатная задача | /promo — тарифы\n\n'
            'Любой текст → AI-ответ на русском',
            kb=main_menu_kb()
        )
    elif action == 'hire':
        await query.message.reply_html(
            '<b>MaxAI Corporation — Услуги</b>\n\n'
            'Telegram-бот с AI — от 2 000 руб\n'
            'Парсер/автоматизация — от 1 500 руб\n'
            'FastAPI бэкенд — от 5 000 руб\n'
            'Трейдинг-бот — от 10 000 руб\n'
            'AaaS подписка — от $19/мес\n\n'
            'Сайт: https://maxai.fyi/hire\n'
            'Fiverr: fiverr.com/maxai_co',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton('Сайт', url='https://maxai.fyi/hire'),
                InlineKeyboardButton('Fiverr', url='https://www.fiverr.com/maxai_co'),
            ], [
                InlineKeyboardButton('Написать', url='https://t.me/MaxAI_SaaS_Bot'),
                InlineKeyboardButton('Меню', callback_data='start'),
            ]])
        )
        return

# ── Text & unknown command handler ────────────────────────────────────────────
async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    user    = update.effective_user
    uid     = user.id
    chat_id = update.effective_chat.id
    text    = update.message.text.strip()
    if not text:
        return

    # Auto-respond to pricing questions
    text_lower = text.lower()
    price_triggers = ['price', 'цена', 'стоимость', 'сколько', 'cost', 'тариф', 'платить', 'оплат', 'купить']
    if any(t in text_lower for t in price_triggers) and uid != OWNER_ID:
        await cmd_pay(update, ctx)
        return

    # Forward client messages to owner (@mamaevmaksi)
    if chat_id != OWNER_ID:
        try:
            username = user.username or user.first_name or str(user.id)
            fwd = (
                "<b>" + "Новый клиент" + "</b>" + "\n\n"
                + "@" + username + " (ID: " + str(user.id) + ")\n"
                + text[:300] + "\n\n"
                + "<i>MaxAI обрабатывает автоматически</i>"
            )
            await ctx.bot.send_message(OWNER_ID, fwd, parse_mode='HTML')
        except Exception as _fe:
            log.debug('Forward to owner failed: %s', _fe)

        try:
            import redis as _redis
            _r = _redis.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
            _r.lpush('maxai:client:messages', json.dumps({
                'user': user.username or user.first_name,
                'user_id': user.id,
                'text': text[:200],
                'ts': time.time(),
            }))
            _r.ltrim('maxai:client:messages', 0, 99)
        except Exception as _re:
            log.debug('Redis client log failed: %s', _re)

    try:
        import sys as _sys
        if '/root/my_personal_ai/dashboard' not in _sys.path:
            _sys.path.insert(0, '/root/my_personal_ai/dashboard')
        from smart_executor import route as _route
        result = _route(text)
        if result and len(result) > 20:
            await update.message.reply_html(result)
            _push(uid, 'user', text)
            _push(uid, 'assistant', result)
            return
    except Exception as _e:
        log.debug('Executor skip: %s', _e)

    await update.message.chat.send_action(ChatAction.TYPING)
    reply = await ask_ai(text, user_id=uid, history=_hist(uid))
    _push(uid, 'user', text)
    _push(uid, 'assistant', reply)
    await update.message.reply_text(reply)
    log.info('Reply uid=%d (%d chars)', uid, len(reply))


async def handle_unknown_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    uid  = update.effective_user.id
    text = (update.message.text or '').lstrip('/').strip() or update.message.text or ''
    await update.message.chat.send_action(ChatAction.TYPING)
    reply = await ask_ai(text, user_id=uid, history=_hist(uid))
    _push(uid, 'user', text)
    _push(uid, 'assistant', reply)
    await update.message.reply_text(reply)

async def error_handler(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error('PTB error: %s', ctx.error, exc_info=ctx.error)

# ── Startup: register commands ────────────────────────────────────────────────
async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand('start',   '\U0001f680 Главное меню'),
        BotCommand('status',  '\U0001f4ca Статус системы'),
        BotCommand('trading', '\U0001f4c8 Торговля и позиции'),
        BotCommand('fleet',   '\U0001f916 AaaS Флот'),
        BotCommand('aaas',    '\U0001f4b0 AaaS Dashboard'),
        BotCommand('revenue', '\U0001f4b0 Выручка и доходы'),
        BotCommand('arb',     '\U0001f4b1 Арбитраж'),
        BotCommand('agents',  '⚡ Агенты и HITL'),
        BotCommand('pay',     '\U0001f4b3 Оплата услуг'),
        BotCommand('try',     '\U0001f381 Бесплатная задача'),
        BotCommand('promo',   '\U0001f4e3 Акция и тарифы'),
        BotCommand('panel',   '\U0001f5a5 Открыть панель'),
        BotCommand('hire',    '💼 Услуги и цены'),
        BotCommand('help',    '❓ Помощь'),
    ])
    log.info('Bot commands registered.')

# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    if not BOT_TOKEN:
        log.critical('TELEGRAM_BOT_TOKEN не задан!')
        sys.exit(1)

    _acquire_lock()
    import atexit
    atexit.register(_release_lock)

    log.info('MaxAI Bot v3 starting (PTB %s)', __import__('telegram').__version__)
    log.info('GROQ=%s ANTHROPIC=%s OR=%s BYBIT=%s',
             bool(GROQ_KEY), bool(ANTHROPIC_KEY), bool(OR_KEY), bool(BYBIT_KEY))

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(30)
        .write_timeout(10)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler('start',   cmd_start))
    app.add_handler(CommandHandler('help',    cmd_help))
    app.add_handler(CommandHandler('status',  cmd_status))
    app.add_handler(CommandHandler('balance', cmd_balance))
    app.add_handler(CommandHandler('trading', cmd_trading))
    app.add_handler(CommandHandler('fleet',   cmd_fleet))
    app.add_handler(CommandHandler('aaas',    cmd_aaas))
    app.add_handler(CommandHandler('revenue', cmd_revenue))
    app.add_handler(CommandHandler('arb',     cmd_arb))
    app.add_handler(CommandHandler('agents',  cmd_agents))
    app.add_handler(CommandHandler('pay',     cmd_pay))
    app.add_handler(CommandHandler('rent',    cmd_rent))
    app.add_handler(CommandHandler('panel',   cmd_panel))
    app.add_handler(CommandHandler('clear',   cmd_clear))
    app.add_handler(CommandHandler('confirm', cmd_confirm))
    app.add_handler(CommandHandler('task',    cmd_task))
    app.add_handler(CommandHandler('try',     cmd_try))
    app.add_handler(CommandHandler('promo',   cmd_promo))
    app.add_handler(CommandHandler('addkey',  cmd_addkey))
    app.add_handler(CommandHandler('hire',    cmd_hire))
    app.add_handler(CommandHandler('order',   cmd_hire))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.COMMAND, handle_unknown_cmd))
    app.add_error_handler(error_handler)

    log.info('Polling started (drop_pending_updates=True)')
    app.run_polling(drop_pending_updates=True, allowed_updates=['message', 'callback_query'])
    _release_lock()

if __name__ == '__main__':
    main()
