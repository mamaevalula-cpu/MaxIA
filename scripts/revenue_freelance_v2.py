#!/usr/bin/env python3
"""
MaxAI Freelance Auto-Bidder v2.0
Scans RSS feeds for AI/Python/Bot jobs, scores them,
generates proposals via LLM, notifies via Telegram.
Revenue: $20-500 per completed task.
"""
import json, os, sys, time, logging, re, hashlib
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '/root/my_personal_ai')
LOG_FILE   = '/root/my_personal_ai/logs/freelance_scanner.log'
LEADS_FILE = Path('/root/my_personal_ai/data/freelance_leads.jsonl')
SEEN_FILE  = Path('/root/my_personal_ai/data/freelance_seen.json')
STATS_FILE = Path('/root/my_personal_ai/data/freelance_stats.json')

BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s'
)
log = logging.getLogger('freelance_v2')

# ── Job feeds ───────────────────────────────────────────────────────────────
FEEDS = [
    ("RemoteOK AI",        "https://remoteok.com/remote-ai-jobs.rss"),
    ("RemoteOK Dev",       "https://remoteok.com/remote-dev-jobs.rss"),
    ("WeWorkRemotely",     "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("HN Hiring",          "https://hnrss.org/whoishiring"),
    ("NodeDesk Remote",    "https://nodesk.co/remote-work/rss.xml"),
]

# Keywords for scoring (higher = better match)
KEYWORDS_SCORE = {
    # Very high value
    'trading bot': 30, 'algo trading': 25, 'quant': 25, 'crypto bot': 25,
    'telegram bot': 20, 'llm': 20, 'gpt': 18, 'claude': 18, 'openai': 18,
    # High value
    'ai agent': 20, 'autonomous': 18, 'langchain': 15, 'fastapi': 15,
    'python automation': 15, 'web scraping': 12, 'data pipeline': 12,
    # Good value
    'python': 8, 'bot': 8, 'api integration': 10, 'chatbot': 10,
    'machine learning': 10, 'automation': 8, 'django': 6, 'flask': 6,
    # High budget indicators
    'senior': 8, '$100': 15, '$150': 18, '$200': 22, '$500': 30,
    'full-time': 5, 'contract': 3,
}

SKIP_KEYWORDS = ['java', 'ruby', 'php', 'wordpress', 'shopify', 'drupal',
                 'graphic design', 'video editing', 'content writer',
                 'social media manager', 'recruiter']

def tg(text):
    """Send Telegram message."""
    try:
        data = json.dumps({
            'chat_id': CHAT_ID, 'text': text,
            'parse_mode': 'HTML', 'disable_web_page_preview': True
        }).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8): pass
    except Exception as e:
        log.warning(f'TG error: {e}')

def load_seen():
    if SEEN_FILE.exists():
        try: return set(json.loads(SEEN_FILE.read_text()))
        except: pass
    return set()

def save_seen(seen):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(list(seen)[-2000:]))

def score_job(title, desc):
    text = (title + ' ' + desc).lower()
    for kw in SKIP_KEYWORDS:
        if kw.lower() in text:
            return 0, []
    score = 0
    matches = []
    for kw, pts in KEYWORDS_SCORE.items():
        if kw.lower() in text:
            score += pts
            matches.append(kw)
    return score, matches

def fetch_feed(name, url, timeout=15):
    jobs = []
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent': 'MaxAI/1.0 (+https://maxai.bot)',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read()
        root = ET.fromstring(content)
        channel = root.find('channel') or root
        items = channel.findall('item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
        for item in items[:30]:
            def get(tag, default=''):
                el = item.find(tag)
                if el is not None and el.text:
                    return re.sub(r'<[^>]+>', '', el.text).strip()
                return default
            title = get('title') or get('{http://www.w3.org/2005/Atom}title')
            link  = get('link')  or get('{http://www.w3.org/2005/Atom}id')
            desc  = get('description') or get('{http://www.w3.org/2005/Atom}summary', '')
            jobs.append({'source': name, 'title': title, 'url': link, 'desc': desc[:500]})
        log.info(f'{name}: fetched {len(jobs)} items')
    except Exception as e:
        log.warning(f'{name} feed error: {e}')
    return jobs

def generate_proposal(job):
    """Generate a short proposal text using LLM or template."""
    title = job.get('title', '')
    desc  = job.get('desc', '')

    # Try LLM first
    try:
        import urllib.request as ur, json as j2
        prompt = f"""Write a SHORT (4-5 sentences) freelance proposal for this job:

Title: {title}
Description: {desc[:300]}

Proposal should:
- Start with specific experience (trading bots, AI agents, FastAPI)
- Mention MaxAI Corporation and our stack (Python, LLM, Telegram bots)
- Mention 24-48h delivery
- End with: "Reply to discuss details."
Language: match the job language (English or Russian).
"""
        payload = j2.dumps({'text': prompt, 'source': 'freelance_proposal'}).encode()
        req = ur.Request('http://127.0.0.1:8090/api/chat',
                        data=payload, headers={'Content-Type': 'application/json'})
        with ur.urlopen(req, timeout=20) as r:
            d = j2.loads(r.read())
        proposal = d.get('response') or d.get('reply') or ''
        if len(proposal) > 50:
            return proposal
    except Exception as e:
        log.debug(f'LLM proposal failed: {e}')

    # Fallback template
    templates_ru = [
        f"Добрый день! Мы — MaxAI Corporation, специализируемся на Python/AI/Telegram-ботах. "
        f"По вашему заданию «{title[:60]}» у нас есть готовые решения и аналогичный опыт. "
        f"Готовы выполнить за 24-48 часов. Stack: Python, FastAPI, LLM, asyncio. "
        f"Напишите, обсудим детали.",
    ]
    templates_en = [
        f"Hi! MaxAI Corporation here, specializing in Python/AI/Trading bots. "
        f"We have direct experience with '{title[:60]}' type projects. "
        f"Delivery: 24-48 hours. Stack: Python, FastAPI, LLMs, asyncio. "
        f"Reply to discuss details.",
    ]
    lang = 'ru' if any(c in (title + desc) for c in 'аоиеёыьэюяАОИЕЁЫЬЭЮЯ') else 'en'
    return templates_ru[0] if lang == 'ru' else templates_en[0]

def run():
    LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    all_jobs = []

    for name, url in FEEDS:
        jobs = fetch_feed(name, url)
        all_jobs.extend(jobs)
        time.sleep(1)

    # Score and filter
    hot_jobs = []
    for job in all_jobs:
        jid = hashlib.md5((job['url'] + job['title']).encode()).hexdigest()
        if jid in seen:
            continue
        seen.add(jid)
        score, matches = score_job(job['title'], job['desc'])
        if score >= 20:
            job['score'] = score
            job['matches'] = matches
            hot_jobs.append(job)

    # Sort by score
    hot_jobs.sort(key=lambda x: x['score'], reverse=True)
    hot_jobs = hot_jobs[:10]  # Top 10

    log.info(f'Found {len(hot_jobs)} hot jobs (score>=20) from {len(all_jobs)} total')

    if hot_jobs:
        # Save leads
        with open(LEADS_FILE, 'a') as f:
            for job in hot_jobs:
                job['ts'] = datetime.now().isoformat()
                job['proposal'] = generate_proposal(job)
                f.write(json.dumps(job, ensure_ascii=False) + '\n')

        # Send to Telegram
        msg = f"💼 <b>Новые фриланс-заказы MaxAI</b>\n"
        msg += f"Найдено: {len(hot_jobs)} горячих лидов\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        for j in hot_jobs[:5]:
            msg += f"🔥 <b>{j['title'][:60]}</b>\n"
            msg += f"   Скор: {j['score']} | {j['source']}\n"
            msg += f"   🔑 {', '.join(j['matches'][:4])}\n"
            if j.get('url'):
                msg += f"   🔗 {j['url'][:60]}\n"
            msg += "\n"
        msg += f"💡 Proposals готовы. Всего лидов сохранено."
        tg(msg)
        log.info(f'Notified: {len(hot_jobs)} hot jobs')
    else:
        log.info('No hot jobs found this run')

    save_seen(seen)

    # Update stats
    stats = {}
    if STATS_FILE.exists():
        try: stats = json.loads(STATS_FILE.read_text())
        except: pass
    stats['last_run'] = datetime.now().isoformat()
    stats['total_leads'] = stats.get('total_leads', 0) + len(hot_jobs)
    stats['total_scanned'] = stats.get('total_scanned', 0) + len(all_jobs)
    STATS_FILE.write_text(json.dumps(stats, indent=2))

if __name__ == '__main__':
    run()
