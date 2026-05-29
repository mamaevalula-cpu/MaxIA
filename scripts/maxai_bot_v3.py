#!/usr/bin/env python3
# MaxAI Telegram Bot v3
from __future__ import annotations
import asyncio, hashlib, hmac, json, logging, os, signal, sys, time
import urllib.request, urllib.error
from pathlib import Path
try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
    from telegram.constants import ChatAction
except ImportError:
    sys.exit('install python-telegram-bot>=22')

BASE=Path('/root/my_personal_ai')
LOG_FILE=BASE/'logs'/'bot_v3.log'
PID_FILE=Path('/tmp/maxai_bot_v3.pid')
ENV_FILE=BASE/'.env'

def _load_env():
    env={}
    try:
        for line in ENV_FILE.read_text().splitlines():
            line=line.strip()
            if '=' in line and not line.startswith('#'):
                k,_,v=line.partition('=')
                env[k.strip()]=v.strip().strip(chr(34)).strip(chr(39))
    except Exception: pass
    return {**env,**os.environ}

ENV=_load_env()
BOT_TOKEN=ENV.get('TELEGRAM_BOT_TOKEN','')
OWNER_ID=int(ENV.get('TELEGRAM_CHAT_ID','1985320458'))
GROQ_KEY=ENV.get('GROQ_API_KEY','')
ANTHROPIC_KEY=ENV.get('ANTHROPIC_API_KEY','')
OR_KEY=ENV.get('OPENROUTER_API_KEY','')
DS_KEY=ENV.get('DEEPSEEK_API_KEY','')
HF_KEY=ENV.get('HUGGINGFACE_TOKEN','')
BYBIT_KEY=ENV.get('BYBIT_API_KEY','')
BYBIT_SECRET=ENV.get('BYBIT_API_SECRET','')
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.StreamHandler(sys.stdout),logging.FileHandler(str(LOG_FILE),encoding='utf-8')])
log=logging.getLogger('bot_v3')

def _acquire_lock():
    if PID_FILE.exists():
        try:
            old=int(PID_FILE.read_text().strip());os.kill(old,0)
            log.warning('Killing old PID %d',old);os.kill(old,signal.SIGTERM);time.sleep(3)
            try: os.kill(old,signal.SIGKILL)
            except ProcessLookupError: pass
        except (ProcessLookupError,ValueError,OSError): pass
    PID_FILE.write_text(str(os.getpid()))

def _release_lock():
    try: PID_FILE.unlink(missing_ok=True)
    except Exception: pass

def _http_sync(url,body=None,hdrs=None,timeout=8):
    req=urllib.request.Request(url,data=body,headers=hdrs or {},method='POST' if body else 'GET')
    with urllib.request.urlopen(req,timeout=timeout) as r: return json.loads(r.read())

async def ahttp(url,data=None,headers=None,timeout=8):
    body=json.dumps(data).encode() if data else None
    hdrs={'Content-Type':'application/json',**(headers or {})}
    return await asyncio.to_thread(_http_sync,url,body,hdrs,timeout)

SYSTEM_PROMPT=(
    'Ты MaxAI — персональный AI-ассистент Максима. '
    'Отвечай кратко, по-деловому, на русском языке. '
    'Помогаешь с криптотрейдингом, бизнесом и автоматизацией. '
    'Если не знаешь — так и скажи, не придумывай.'
)

async def _ask_groq(text,history=None):
    if not GROQ_KEY: raise RuntimeError('no groq key')
    msgs=[{'role':'system','content':SYSTEM_PROMPT}]
    if history: msgs.extend(history[-6:])
    msgs.append({'role':'user','content':text})
    d=await ahttp('https://api.groq.com/openai/v1/chat/completions',
        data={'model':'llama-3.3-70b-versatile','messages':msgs,'max_tokens':1024,'temperature':0.7},
        headers={'Authorization':f'Bearer {GROQ_KEY}'},timeout=30)
    return d['choices'][0]['message']['content'].strip()

async def _ask_anthropic(text,history=None):
    if not ANTHROPIC_KEY: raise RuntimeError('no anthropic key')
    msgs=[]
    if history: msgs.extend(history[-6:])
    msgs.append({'role':'user','content':text})
    d=await ahttp('https://api.anthropic.com/v1/messages',
        data={'model':'claude-haiku-4-5','max_tokens':1024,'system':SYSTEM_PROMPT,'messages':msgs},
        headers={'x-api-key':ANTHROPIC_KEY,'anthropic-version':'2023-06-01'},timeout=30)
    return d['content'][0]['text'].strip()

async def _ask_openrouter(text,history=None):
    if not OR_KEY: raise RuntimeError('no or key')
    msgs=[{'role':'system','content':SYSTEM_PROMPT}]
    if history: msgs.extend(history[-6:])
    msgs.append({'role':'user','content':text})
    d=await ahttp('https://openrouter.ai/api/v1/chat/completions',
        data={'model':'meta-llama/llama-3.3-70b-instruct:free','messages':msgs,'max_tokens':1024},
        headers={'Authorization':'Bearer '+OR_KEY,'HTTP-Referer':'https://maxai.bot'},timeout=30)
    return d['choices'][0]['message']['content'].strip()

async def _ask_deepseek(text,history=None):
    if not DS_KEY: raise RuntimeError('no ds key')
    msgs=[{'role':'system','content':SYSTEM_PROMPT}]
    if history: msgs.extend(history[-6:])
    msgs.append({'role':'user','content':text})
    d=await ahttp('https://api.deepseek.com/v1/chat/completions',
        data={'model':'deepseek-chat','messages':msgs,'max_tokens':1024},
        headers={'Authorization':'Bearer '+DS_KEY},timeout=30)
    return d['choices'][0]['message']['content'].strip()

async def _ask_huggingface(text,history=None):
    if not HF_KEY: raise RuntimeError('no hf key')
    msgs=[{'role':'system','content':SYSTEM_PROMPT}]
    if history: msgs.extend(history[-6:])
    msgs.append({'role':'user','content':text})
    d=await ahttp('https://router.huggingface.co/v1/chat/completions',
        data={'model':'meta-llama/Llama-3.3-70B-Instruct','messages':msgs,'max_tokens':1024,'temperature':0.7},
        headers={'Authorization':'Bearer '+HF_KEY},timeout=35)
    return d['choices'][0]['message']['content'].strip()

async def ask_ai(text,user_id=None,history=None):
    if GROQ_KEY:
        for _att in range(2):
            try: return await _ask_groq(text,history)
            except Exception as e1:
                log.warning('Groq att%d: %s',_att+1,e1)
                if _att==0: await asyncio.sleep(1)
    if OR_KEY:
        try: return await _ask_openrouter(text,history)
        except Exception as e2: log.warning('OR(%s)',e2)
    if DS_KEY:
        try: return await _ask_deepseek(text,history)
        except Exception as e3: log.warning('DS(%s)',e3)
    if HF_KEY:
        try: return await _ask_huggingface(text,history)
        except Exception as e4: log.warning('HF(%s)',e4)
    try:
        d=await ahttp('http://127.0.0.1:8090/api/chat',
            data={'message':text,'user_id':str(user_id or OWNER_ID),'session_id':'tg_'+str(user_id or 0)},
            timeout=20)
        r=d.get('response') or d.get('reply') or d.get('message','')
        if r: return r.strip()
    except Exception as e4: log.warning('Panel(%s)',e4)
    return '⚠️ AI временно недоступен. Попробуй снова через минуту.'

async def get_bybit_balance():
    if not BYBIT_KEY: return 'Bybit API not configured'
    try:
        ts=str(int(time.time()*1000));params='accountType=UNIFIED'
        sig=hmac.new(BYBIT_SECRET.encode(),(ts+BYBIT_KEY+'5000'+params).encode(),hashlib.sha256).hexdigest()
        d=await ahttp(f'https://api.bybit.com/v5/account/wallet-balance?{params}',
            headers={'X-BAPI-API-KEY':BYBIT_KEY,'X-BAPI-TIMESTAMP':ts,'X-BAPI-SIGN':sig,'X-BAPI-RECV-WINDOW':'5000'},timeout=10)
        item=d['result']['list'][0];eq=float(item.get('totalEquity',0));wb=float(item.get('totalWalletBalance',0));upnl=eq-wb
        sign='+' if upnl>=0 else ''
        return f'<b>Bybit Balance</b>\nEquity: <b>{DOLS}{eq:.2f} USDT</b>\nWallet: {DOLS}{wb:.2f} USDT\nuPnL: {sign}{upnl:.2f} USDT'
    except Exception as e: return f'Balance error: {e}'

async def get_trading_status():
    try:
        d=await asyncio.wait_for(ahttp('http://127.0.0.1:8001/status',timeout=3),timeout=4)
        mode='LIVE' if not d.get('paper_mode',True) else 'Paper'
        bal=d.get('balance_usdt','?');pnl=d.get('daily_pnl',0);pos=d.get('active_positions',0)
        sign='+' if float(pnl or 0)>=0 else ''
        return f'Trading bot: <b>{mode}</b>\nBalance: {DOLS}{bal}\nPnL today: {sign}{pnl} USDT\nPositions: {pos}'
    except Exception: return 'Trading bot: status unavailable'

_history={}
def _push(uid,role,content):
    h=_history.setdefault(uid,[]);h.append({'role':role,'content':content})
    if len(h)>20: _history[uid]=h[-20:]
def _hist(uid): return _history.get(uid,[])

async def cmd_start(update,ctx):
    name=update.effective_user.first_name or 'друг'
    await update.message.reply_html(
        f'Привет, {name}!\n\n<b>MaxAI — персональный AI-ассистент</b>\n\n'
        '/status — статус системы\n/balance — баланс Bybit\n'
        '/trading — торговый бот\n/clear — сбросить чат\n/help — помощь\n\n'
        'Пиши любое сообщение — AI ответит!')

async def cmd_help(update,ctx):
    await update.message.reply_html(
        '<b>Команды:</b>\n/start /status /balance /trading /clear\n\n'
        'Панель: http://77.90.2.171\n\nЛюбой текст → AI ответит')

async def cmd_status(update,ctx):
    await update.message.chat.send_action(ChatAction.TYPING)
    trading=await get_trading_status()
    gr='OK' if GROQ_KEY else 'NO'
    an='OK' if ANTHROPIC_KEY else 'NO'
    await update.message.reply_html(
        f'<b>Система MaxAI</b>\n\nTelegram: Online\nGroq: {gr} | Anthropic: {an}\n\n{trading}\n\nПанель: http://77.90.2.171')

async def cmd_balance(update,ctx):
    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_html(await get_bybit_balance())

async def cmd_trading(update,ctx):
    await update.message.chat.send_action(ChatAction.TYPING)
    await update.message.reply_html(await get_trading_status())

async def cmd_clear(update,ctx):
    _history.pop(update.effective_user.id,None)
    await update.message.reply_text('История чата очищена ✓')

async def cmd_subscribe(update,ctx):
    await update.message.reply_html(
        f'<b>Подписки Crypto Signals</b>\n\n'
        f'<b>{DOLS}9/мес Basic</b>\nhttps://t.me/CryptoBot?start=IVFJXrKVDgBs\n\n'
        f'<b>{DOLS}29/мес Pro</b>\nhttps://t.me/CryptoBot?start=IVVAA3ZMFcHv\n\n'
        f'<b>{DOLS}49/мес AI</b>\nhttps://t.me/CryptoBot?start=IVGAU7NMlgxg\n\n'
        'После оплаты доступ активируется автоматически.',
        disable_web_page_preview=True)

async def handle_text(update,ctx):
    log.info('MSG_RECEIVED: update=%s', update.update_id if hasattr(update,'update_id') else '?')
    if not update.message or not update.message.text: return
    uid=update.effective_user.id;text=update.message.text.strip()
    log.info('MSG_TEXT uid=%d: %s', uid, text[:80])
    if not text: return
    direct=text[:6].lower()=='maxai '
    query=text[6:].strip() if direct else text
    if not query: query=text
    log.info('AI%s uid=%d: %s','(direct)' if direct else '',uid,query[:100])
    await update.message.chat.send_action(ChatAction.TYPING)
    reply=await ask_ai(query,user_id=uid,history=([] if direct else _hist(uid)))
    if not direct: _push(uid,'user',query);_push(uid,'assistant',reply) if not direct else None
    await update.message.reply_text(reply)
    log.info('Reply uid=%d (%d chars)',uid,len(reply))

async def error_handler(update,ctx):
    log.error('PTB error: %s',ctx.error,exc_info=ctx.error)

async def handle_unknown_cmd(update,ctx):
    if not update.message: return
    uid  = update.effective_user.id
    text = (update.message.text or '').strip()
    direct=text[:6].lower()=='maxai '
    query=text[6:].strip() if direct else text.lstrip('/').strip() or text
    log.info('Cmd uid=%d: %s',uid,query[:80])
    await update.message.chat.send_action(ChatAction.TYPING)
    reply=await ask_ai(query,user_id=uid,history=([] if direct else _hist(uid)))
    if not direct: _push(uid,'user',query);_push(uid,'assistant',reply) if not direct else None
    await update.message.reply_text(reply)

async def cmd_addkey(update, ctx):
    """Save API key: /addkey NAME=value"""
    if update.effective_user.id != OWNER_ID:
        return
    text = (update.message.text or '').strip()
    parts = text.split(None, 1)
    if len(parts) < 2 or '=' not in parts[1]:
        await update.message.reply_text('Формат: /addkey OPENROUTER_API_KEY=sk-or-...')
        return
    key_val = parts[1].strip()
    name, _, value = key_val.partition('=')
    name = name.strip().upper()
    value = value.strip()
    if not name or not value:
        await update.message.reply_text('Неверный формат')
        return
    try:
        env_path = ENV_FILE
        src_env = env_path.read_text()
        import re as _re
        if f'{name}=' in src_env:
            src_env = _re.sub(rf'^{name}=.*$', f'{name}={value}', src_env, flags=_re.MULTILINE)
        else:
            src_env += chr(10) + name + chr(61) + value
        env_path.write_text(src_env)
        log.info('Key saved: %s', name)
        await update.message.reply_text(f'✅ {name} сохранён. Перезапускаю бота...')
        import subprocess as _sp
        _sp.Popen(['systemctl', 'restart', 'maxai-tgbot'])
    except Exception as e:
        await update.message.reply_text(f'❌ Ошибка: {e}')


def main():
    if not BOT_TOKEN: log.critical('TELEGRAM_BOT_TOKEN missing');sys.exit(1)
    _acquire_lock()
    import atexit;atexit.register(_release_lock)
    log.info('MaxAI Bot v3 PTB %s',__import__('telegram').__version__)
    log.info('GROQ=%s ANTHROPIC=%s BYBIT=%s',bool(GROQ_KEY),bool(ANTHROPIC_KEY),bool(BYBIT_KEY))
    app=(Application.builder().token(BOT_TOKEN).connect_timeout(10).read_timeout(30).write_timeout(10).build())
    app.add_handler(CommandHandler('start',cmd_start))
    app.add_handler(CommandHandler('help',cmd_help))
    app.add_handler(CommandHandler('status',cmd_status))
    app.add_handler(CommandHandler('balance',cmd_balance))
    app.add_handler(CommandHandler('trading',cmd_trading))
    app.add_handler(CommandHandler('clear',cmd_clear))
    app.add_handler(CommandHandler('addkey',cmd_addkey))
    app.add_handler(CommandHandler('subscribe',cmd_subscribe))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text))
    # Unknown commands -> treat as AI query
    app.add_handler(MessageHandler(filters.COMMAND,handle_unknown_cmd))
    app.add_error_handler(error_handler)
    log.info('Polling started drop_pending_updates=True')
    app.run_polling(drop_pending_updates=True,allowed_updates=['message'])
    _release_lock()

if __name__=='__main__':
    main()
