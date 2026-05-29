#!/usr/bin/env python3
"""
MaxAI Auto-Proposal Sender v1.0
Project 1: Revenue from Day 1

Reads hot freelance leads, sends ready proposals via Telegram to the team,
AND posts to direct Telegram messages (simulating outreach).
Revenue: $20-500 per completed project.

Runs every 2 hours. Only processes 'ready' leads not yet sent.
"""
import json, os, logging, time, hashlib
import urllib.request
from datetime import datetime
from pathlib import Path

LOG_FILE   = '/root/my_personal_ai/logs/auto_proposal.log'
LEADS_FILE = Path('/root/my_personal_ai/data/freelance_leads.jsonl')
SENT_FILE  = Path('/root/my_personal_ai/data/proposals_sent.json')
BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('auto_proposal')

def tg(text, parse_mode='HTML'):
    try:
        data = json.dumps({'chat_id': CHAT_ID, 'text': text,
                           'parse_mode': parse_mode, 'disable_web_page_preview': True}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8): pass
    except Exception as e:
        log.warning(f'TG: {e}')

def load_sent():
    if SENT_FILE.exists():
        try: return set(json.loads(SENT_FILE.read_text()))
        except: pass
    return set()

def save_sent(sent):
    SENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    SENT_FILE.write_text(json.dumps(list(sent)[-500:]))

def load_leads():
    if not LEADS_FILE.exists():
        return []
    leads = []
    try:
        with open(LEADS_FILE) as f:
            for line in f:
                try:
                    leads.append(json.loads(line.strip()))
                except: pass
    except: pass
    return leads

def run():
    sent = load_sent()
    leads = load_leads()

    if not leads:
        log.info('No leads found')
        return

    # Only process new HIGH-QUALITY leads (score >= 20)
    new_leads = []
    for lead in leads:
        if lead.get("score", 0) < 20:
            continue
        lid = hashlib.md5((lead.get('url','') + lead.get('title','')).encode()).hexdigest()
        if lid not in sent:
            new_leads.append((lid, lead))

    if not new_leads:
        log.info('No new leads to process')
        return

    # Send top 3 per run (rate limit)
    batch = new_leads[:3]
    log.info(f'Processing {len(batch)} new leads (total queue: {len(new_leads)})')

    for lid, lead in batch:
        title = lead.get('title', '?')[:70]
        source = lead.get('source', '?')
        score = lead.get('score', 0)
        url = lead.get('url', '')
        proposal = lead.get('proposal', '')
        matches = lead.get('matches', [])

        # Format as ready-to-send proposal card
        msg = (
            f"📤 <b>Готовый пропозал — отправить вручную</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 <b>{title}</b>\n"
            f"🏷 Источник: {source} | Скор: {score}\n"
            f"🔑 Ключевые слова: {', '.join(matches[:4])}\n"
            f"🔗 <a href=\"{url}\">Открыть вакансию</a>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✍️ <b>Пропозал:</b>\n"
            f"<i>{proposal[:600] if proposal else 'Шаблон не сгенерирован'}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👉 Скопируй и отправь напрямую"
        )
        tg(msg)
        sent.add(lid)
        log.info(f'Proposal sent for: {title}')
        time.sleep(2)

    save_sent(sent)

    # Summary if many pending
    if len(new_leads) > 3:
        remaining = len(new_leads) - 3
        tg(
            f"📊 <b>Очередь предложений MaxAI</b>\n"
            f"✅ Отправлено сейчас: 3\n"
            f"⏳ В очереди ещё: {remaining}\n"
            f"🔄 Следующий запуск: через 2 часа\n"
            f"💰 Потенциал: ${len(new_leads) * 50:.0f} (при 5% конверсии)"
        )

if __name__ == '__main__':
    run()
