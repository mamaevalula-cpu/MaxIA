#!/usr/bin/env python3
"""
MaxAI Upwork & International Freelance Parser v1.0
Project 4: Revenue from Day 1

Scans English-language freelance platforms (Upwork RSS, Contra, etc.)
for Python/AI/Bot jobs with $50+ budget.
Sends ready proposals in English.
Revenue: $100-2000 per project (international rates).

Runs daily at 10:00 and 18:00.
"""
import json, os, re, hashlib, time, logging
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

LOG_FILE   = '/root/my_personal_ai/logs/upwork_parser.log'
LEADS_FILE = Path('/root/my_personal_ai/data/intl_leads.jsonl')
SEEN_FILE  = Path('/root/my_personal_ai/data/intl_seen.json')
STATS_FILE = Path('/root/my_personal_ai/data/intl_stats.json')
BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('upwork_parser')

# ── High-value international feeds ───────────────────────────────────────────
FEEDS = [
    ("Upwork AI/ML",    "https://www.upwork.com/ab/feed/jobs/rss?q=artificial+intelligence+python&sort=recency&paging=0%3B10"),
    ("Upwork Trading",  "https://www.upwork.com/ab/feed/jobs/rss?q=trading+bot+python&sort=recency&paging=0%3B10"),
    ("Upwork Telegram", "https://www.upwork.com/ab/feed/jobs/rss?q=telegram+bot+python&sort=recency&paging=0%3B10"),
    ("RemoteOK Python", "https://remoteok.com/remote-python-jobs.rss"),
    ("RemoteOK AI",     "https://remoteok.com/remote-ai-jobs.rss"),
    ("Contra",          "https://contra.com/opportunities.rss"),
    ("Toptal Blog",     "https://www.toptal.com/developers/blog.rss"),
    ("PeoplePerHour",   "https://www.peopleperhour.com/sitemap-hourlies.xml"),
]

# Score keywords — English focus, higher $ budgets
KEYWORDS_SCORE = {
    # Very high value
    'trading bot': 35, 'algo trading': 30, 'quant': 28, 'crypto bot': 28,
    'telegram bot': 22, 'llm': 25, 'gpt-4': 22, 'claude api': 25, 'openai api': 22,
    'ai agent': 25, 'langchain': 20, 'autogen': 22, 'crewai': 22,
    # Budget indicators
    '$200': 25, '$300': 28, '$500': 32, '$1000': 40, '$2000': 45,
    'hourly': 15, 'long term': 12, 'ongoing': 12, 'monthly retainer': 20,
    # Skills
    'fastapi': 18, 'python automation': 15, 'web scraping': 12,
    'machine learning': 15, 'pytorch': 18, 'transformers': 20,
    'data pipeline': 12, 'vector database': 20, 'rag': 22, 'fine-tuning': 22,
    'python': 8, 'bot': 8, 'api integration': 12,
    'senior': 10, 'expert': 12, 'specialist': 10,
}

SKIP_KEYWORDS = ['java', 'ruby', 'php', 'wordpress', 'shopify', 'drupal',
                 'graphic design', 'video editing', 'content writer',
                 'social media manager', 'recruiter', 'hr manager']

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

def load_seen():
    if SEEN_FILE.exists():
        try: return set(json.loads(SEEN_FILE.read_text()))
        except: pass
    return set()

def save_seen(seen):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(list(seen)[-3000:]))

def score_job(title, desc):
    text = (title + ' ' + desc).lower()
    for kw in SKIP_KEYWORDS:
        if kw.lower() in text:
            return 0, []
    score, matches = 0, []
    for kw, pts in KEYWORDS_SCORE.items():
        if kw.lower() in text:
            score += pts
            matches.append(kw)
    return score, matches

def fetch_feed(name, url, timeout=15):
    jobs = []
    headers = {
        'User-Agent': 'Mozilla/5.0 MaxAI-Bot/1.0 (+https://maxai.bot)',
        'Accept': 'application/rss+xml, application/xml, text/xml, */*',
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content = r.read()
        root = ET.fromstring(content)
        # Handle both RSS and Atom
        channel = root.find('channel') or root
        items = channel.findall('item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
        for item in items[:20]:
            def get(tag, default=''):
                el = item.find(tag)
                if el is None:
                    el = item.find('{http://www.w3.org/2005/Atom}' + tag)
                if el is not None and el.text:
                    return re.sub(r'<[^>]+>', '', el.text).strip()
                return default
            title = get('title')
            link  = get('link') or get('id')
            desc  = get('description') or get('summary', '')
            if title:
                jobs.append({'source': name, 'title': title, 'url': link, 'desc': desc[:500]})
        log.info(f'{name}: {len(jobs)} jobs')
    except Exception as e:
        log.warning(f'{name}: {e}')
    return jobs

def generate_proposal_en(job):
    title = job.get('title', '')[:80]
    desc = job.get('desc', '')[:200]
    matches = job.get('matches', [])

    # Identify the job type for targeted proposal
    is_trading = any(k in (title + desc).lower() for k in ['trading', 'quant', 'algo', 'crypto'])
    is_bot = any(k in (title + desc).lower() for k in ['bot', 'telegram', 'discord', 'automation'])
    is_ai = any(k in (title + desc).lower() for k in ['ai', 'llm', 'gpt', 'agent', 'ml'])

    if is_trading:
        expertise = "quantitative trading systems (Grid, Momentum, Mean Reversion)"
        example = "Bybit/Binance trading bots with live P&L tracking"
    elif is_bot:
        expertise = "Telegram/Discord bots and automation systems"
        example = "bots serving 1000+ users with webhook integration"
    elif is_ai:
        expertise = "LLM applications, AI agents, and RAG systems"
        example = "multi-agent systems with Claude/GPT integration"
    else:
        expertise = "Python automation and API integrations"
        example = "production systems handling high-volume data"

    return (
        f"Hi! I'm from MaxAI Corporation — we specialize in {expertise}.\n\n"
        f"For your project '{title[:50]}', we've built similar {example}. "
        f"Our stack: Python 3.11+, FastAPI, asyncio, {', '.join(matches[:3]) if matches else 'LLM APIs'}.\n\n"
        f"Delivery: 24-72 hours with full documentation. "
        f"We offer a free 30-min consultation before starting.\n\n"
        f"Portfolio & reviews: https://maxai.bot\n"
        f"Reply to discuss scope and timeline."
    )

def run():
    LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    all_jobs = []

    for name, url in FEEDS:
        jobs = fetch_feed(name, url)
        all_jobs.extend(jobs)
        time.sleep(1.5)

    # Score and filter
    hot_jobs = []
    for job in all_jobs:
        jid = hashlib.md5((job.get('url','') + job.get('title','')).encode()).hexdigest()
        if jid in seen:
            continue
        seen.add(jid)
        score, matches = score_job(job['title'], job['desc'])
        if score >= 25:
            job['score'] = score
            job['matches'] = matches
            hot_jobs.append(job)

    hot_jobs.sort(key=lambda x: x['score'], reverse=True)
    hot_jobs = hot_jobs[:8]

    log.info(f'Found {len(hot_jobs)} hot international jobs (score>=25) from {len(all_jobs)} total')

    if hot_jobs:
        with open(LEADS_FILE, 'a') as f:
            for job in hot_jobs:
                job['ts'] = datetime.now().isoformat()
                job['proposal'] = generate_proposal_en(job)
                f.write(json.dumps(job, ensure_ascii=False) + '\n')

        msg = f"🌍 <b>MaxAI International Freelance</b>\n"
        msg += f"Found: {len(hot_jobs)} hot leads | {len(all_jobs)} scanned\n"
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        for j in hot_jobs[:4]:
            msg += f"💰 <b>{j['title'][:65]}</b>\n"
            msg += f"   Score: {j['score']} | {j['source']}\n"
            msg += f"   Keys: {', '.join(j['matches'][:3])}\n"
            if j.get('url'):
                msg += f"   🔗 {j['url'][:60]}\n"
            msg += "\n"
        msg += f"✍️ Proposals готовы. 💰 Потенциал: ${len(hot_jobs)*150:.0f}"
        tg(msg)

    save_seen(seen)

    # Update stats
    stats = {}
    if STATS_FILE.exists():
        try: stats = json.loads(STATS_FILE.read_text())
        except: pass
    stats['last_run'] = datetime.now().isoformat()
    stats['total_intl_leads'] = stats.get('total_intl_leads', 0) + len(hot_jobs)
    stats['total_scanned'] = stats.get('total_scanned', 0) + len(all_jobs)
    stats['feeds'] = len(FEEDS)
    STATS_FILE.write_text(json.dumps(stats, indent=2))

    log.info(f'Done. Intl leads: {len(hot_jobs)}, total ever: {stats["total_intl_leads"]}')

if __name__ == '__main__':
    run()
