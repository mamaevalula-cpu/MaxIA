#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MaxAI Telegram Manager v1
Listens to personal Telegram (@mamaevmaksi) via MTProto.
Analyzes incoming messages, stores in Redis for panel review.
Owner approves/rejects responses from the panel (HITL mode).

SAFETY: Never auto-sends replies without owner approval.
"""
import asyncio, json, logging, os, re, sys, time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [TG-MGR] %(message)s')
log = logging.getLogger('tg_manager')

BASE = Path('/root/my_personal_ai')
ENV_FILE = BASE / '.env'
REDIS_URL = 'redis://127.0.0.1:6379/0'
SESSION_FILE = '/root/maxai-ecosystem/.maxai-mtproto.session'


def load_env():
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip().strip('"').strip("'")
    return {**env, **os.environ}


ENV = load_env()
API_ID   = int(ENV.get('TELEGRAM_API_ID', '0'))
API_HASH = ENV.get('TELEGRAM_API_HASH', '')
OWNER_ID = int(ENV.get('TELEGRAM_OWNER_ID', ENV.get('TELEGRAM_CHAT_ID', '0')))
GROQ_KEY = ENV.get('GROQ_API_KEY', '')

# Whitelisted known contacts - messages from these are not flagged as "clients"
WHITELIST = set()  # Will be populated from Redis


async def get_redis():
    try:
        import redis.asyncio as aioredis
        return await aioredis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error(f'Redis connect failed: {e}')
        return None


async def analyze_message(text: str, sender_name: str) -> dict:
    """Classify message type and generate draft response."""
    try:
        import httpx
        prompt = (
            f"Classify this message from '{sender_name}' and draft a brief response.\n"
            f"Message: {text[:500]}\n\n"
            f"Respond in JSON: {{\"type\": \"service_inquiry|payment|support|spam|other\", "
            f"\"draft\": \"draft response in Russian\", "
            f"\"priority\": \"high|medium|low\", "
            f"\"auto_reply_safe\": false}}"
        )
        if GROQ_KEY:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.post(
                    'https://api.groq.com/openai/v1/chat/completions',
                    headers={'Authorization': f'Bearer {GROQ_KEY}'},
                    json={
                        'model': 'llama-3.1-8b-instant',
                        'messages': [{'role': 'user', 'content': prompt}],
                        'max_tokens': 300,
                    }
                )
                if r.status_code == 200:
                    content = r.json()['choices'][0]['message']['content']
                    # Try to parse JSON from response
                    m = re.search(r'\{.*\}', content, re.DOTALL)
                    if m:
                        return json.loads(m.group())
    except Exception as e:
        log.debug(f'AI analysis failed: {e}')

    return {
        'type': 'unknown',
        'draft': 'Спасибо за сообщение! Мы ответим вам в ближайшее время.',
        'priority': 'medium',
        'auto_reply_safe': False,
    }


async def store_inbox_message(sender_id: int, sender_name: str, text: str, analysis: dict):
    """Store message in Redis for panel review."""
    r = await get_redis()
    if not r:
        return

    msg = {
        'id': f'tg_{int(time.time())}_{sender_id}',
        'sender_id': sender_id,
        'sender_name': sender_name,
        'text': text[:500],
        'analysis': analysis,
        'ts': time.time(),
        'time': datetime.now().isoformat(),
        'status': 'pending',  # pending / approved / rejected
        'draft_reply': analysis.get('draft', ''),
    }

    await r.lpush('maxai:personal_tg:inbox', json.dumps(msg))
    await r.ltrim('maxai:personal_tg:inbox', 0, 199)
    await r.set('maxai:personal_tg:last_message_ts', time.time())

    log.info(f'Stored message from {sender_name} (type={analysis.get("type")}, priority={analysis.get("priority")})')


async def run_manager():
    """Main loop: listen to personal Telegram via MTProto."""
    log.info('MaxAI Telegram Manager starting...')

    if not API_ID or not API_HASH:
        log.error('TELEGRAM_API_ID or TELEGRAM_API_HASH not set!')
        return

    if not Path(SESSION_FILE).exists():
        log.error(f'MTProto session not found at {SESSION_FILE}')
        return

    try:
        from telethon import TelegramClient, events
        from telethon.sessions import StringSession
    except ImportError:
        log.error('telethon not installed. Run: /root/venv/bin/pip install telethon')
        return

    session_str = Path(SESSION_FILE).read_text(encoding='utf-8').strip()

    r = await get_redis()
    if r:
        # Load whitelist from Redis
        wl = await r.smembers('maxai:personal_tg:whitelist')
        WHITELIST.update(int(x) for x in wl if x.isdigit())
        log.info(f'Whitelist loaded: {len(WHITELIST)} contacts')
        await r.set('maxai:tg_manager:status', 'starting')

    client = TelegramClient(StringSession(session_str), API_ID, API_HASH)

    @client.on(events.NewMessage(incoming=True))
    async def on_message(event):
        try:
            sender = await event.get_sender()
            if not sender:
                return

            sender_id   = sender.id
            sender_name = getattr(sender, 'username', None) or getattr(sender, 'first_name', 'Unknown')
            text        = event.message.text or ''

            if not text:
                return

            # Skip if sender is in whitelist (known trusted contact)
            if sender_id in WHITELIST:
                log.debug(f'Whitelist skip: {sender_name}')
                return

            log.info(f'New message from {sender_name} ({sender_id}): {text[:80]}')

            # Analyze with AI
            analysis = await analyze_message(text, str(sender_name))

            # Store for panel review (NEVER auto-reply without approval)
            await store_inbox_message(sender_id, str(sender_name), text, analysis)

            # Update Redis status
            r2 = await get_redis()
            if r2:
                await r2.set('maxai:tg_manager:last_activity', time.time())
                await r2.incr('maxai:tg_manager:messages_processed')

        except Exception as e:
            log.error(f'Message handler error: {e}')

    try:
        await client.connect()
    except Exception as e:
        log.error(f'MTProto connect failed: {e}')
        if r:
            await r.set('maxai:tg_manager:status', 'session_invalid')
            await r.set('maxai:tg_manager:error', str(e))
        return

    if not await client.is_user_authorized():
        log.warning('MTProto session not authorized. Session needs re-authentication.')
        log.warning('Run: node /root/maxai-ecosystem/scripts/tg_qr_auth.js to re-auth')
        if r:
            await r.set('maxai:tg_manager:status', 'needs_auth')
            await r.set('maxai:tg_manager:error', 'Session not authorized - needs QR re-auth')
        await client.disconnect()
        return

    try:
        me = await client.get_me()
        log.info(f'MTProto connected as: @{me.username} (ID: {me.id})')

        if r:
            await r.set('maxai:tg_manager:status', 'running')
            await r.set('maxai:tg_manager:account', json.dumps({
                'username': me.username,
                'id': me.id,
                'started_at': time.time(),
            }))

        log.info('Listening for incoming messages (HITL mode - no auto-reply)...')
        await client.run_until_disconnected()

    finally:
        await client.disconnect()
        if r:
            await r.set('maxai:tg_manager:status', 'stopped')


if __name__ == '__main__':
    try:
        asyncio.run(run_manager())
    except KeyboardInterrupt:
        log.info('Telegram Manager stopped by user')
    except Exception as e:
        log.critical(f'Fatal error: {e}', exc_info=True)
        sys.exit(1)
