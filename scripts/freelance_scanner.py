#!/usr/bin/env python3
"""
Freelance job scanner v2 — AI/automation jobs from RSS.
Runs daily at 09:00, stores best matches in knowledge base.
"""
import sys, os, json, time, sqlite3, logging, re
from datetime import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError
import xml.etree.ElementTree as ET

sys.path.insert(0, '/root/my_personal_ai')
LOG = '/root/my_personal_ai/logs/freelance_scanner.log'
# Load env vars for Telegram tokens
try:
    from dotenv import load_dotenv
    load_dotenv('/root/my_personal_ai/.env')
except ImportError:
    pass

DB  = '/root/my_personal_ai/data/memory.db'
LEADS_FILE = '/root/my_personal_ai/data/freelance_leads.jsonl'

logging.basicConfig(filename=LOG, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

KEYWORDS = [
    'AI', 'automation', 'python', 'trading bot', 'chatbot', 'LLM',
    'machine learning', 'FastAPI', 'Telegram bot', 'bot', 'scraping',
    'data pipeline', 'n8n', 'zapier', 'rpa', 'workflow', 'openai',
    'langchain', 'gpt', 'claude', 'autonomous', 'agent',
]

HIGH_VALUE = ['trading', 'fintech', 'quant', 'algo', 'crypto',
              'enterprise', 'saas', 'b2b', 'startup']

HOT_THRESHOLD = 4   # score >= this triggers Telegram alert

FEEDS = [
    ("RemoteOK AI", "https://remoteok.com/remote-ai-jobs.rss"),
    ("We Work Remotely Dev", "https://weworkremotely.com/categories/remote-programming-jobs.rss"),
    ("We Work Remotely DevOps", "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"),
    ("HN Who's Hiring", "https://hnrss.org/whoishiring"),
    ("GitHub Jobs Mirror", "https://remoteok.com/remote-dev-jobs.rss"),
]

def fetch_feed(name, url, timeout=12):
    try:
        req = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; MaxAI-Scanner/2.0; +https://maxai.fyi)',
            'Accept': 'application/rss+xml, application/xml, text/xml',
        })
        with urlopen(req, timeout=timeout) as r:
            data = r.read()
        return ET.fromstring(data)
    except URLError as e:
        log.warning("Feed %s failed: %s", name, e)
    except ET.ParseError as e:
        log.warning("Feed %s parse error: %s", name, e)
    except Exception as e:
        log.warning("Feed %s error: %s", name, e)
    return None

def score_job(title, desc):
    text = (title + ' ' + desc).lower()
    score = sum(1 for kw in KEYWORDS if kw.lower() in text)
    bonus = sum(2 for hv in HIGH_VALUE if hv in text)
    return score + bonus

def clean_html(text):
    return re.sub(r'<[^>]+>', ' ', text or '').strip()[:300]

def save_lead(job):
    with open(LEADS_FILE, 'a') as f:
        f.write(json.dumps(job, ensure_ascii=False) + '\n')

def save_to_knowledge(jobs):
    if not jobs:
        return 0
    try:
        conn = sqlite3.connect(DB)
        added = 0
        for job in jobs:
            title = (job.get('title') or 'Untitled')[:255]
            content = (
                "[FREELANCE] %s | Source: %s | Score: %s | URL: %s | %s"
                % (job.get('title',''), job.get('source',''), job.get('score',0),
                   job.get('url',''), job.get('desc','')[:150])
            )
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO knowledge (category, title, content, source, ts) VALUES (?,?,?,?,?)",
                    ('freelance_leads', title, content, job.get('source',''), time.time())
                )
                added += 1
            except Exception as e:
                log.warning("DB insert failed: %s", e)
        conn.commit()
        conn.close()
        return added
    except Exception as e:
        log.error("Knowledge save failed: %s", e)
        return 0


def _tg_notify_hot(jobs):
    try:
        import urllib.request as _ur, json as _j, os as _os
        tok = _os.getenv('TELEGRAM_BOT_TOKEN','') or _os.getenv('BOT_TOKEN','')
        cid = _os.getenv('TELEGRAM_CHAT_ID','') or _os.getenv('OWNER_CHAT_ID','')
        if not tok or not cid:
            log.warning('TG notify skip: no BOT_TOKEN/CHAT_ID env')
            return
        nl = chr(10)
        header = chr(128293) + ' *Hot freelance leads* (score>=%d):' % HOT_THRESHOLD
        rows = []
        for j in jobs[:5]:
            rows.append('[%d] %s' % (j['score'], j['title'][:80]))
            if j.get('url'):
                rows.append(j['url'][:120])
        text = header + nl + nl.join(rows)
        body = _j.dumps({'chat_id': cid, 'text': text, 'parse_mode': 'Markdown'}).encode()
        req = _ur.Request(
            'https://api.telegram.org/bot%s/sendMessage' % tok,
            data=body, headers={'Content-Type': 'application/json'}, method='POST'
        )
        with _ur.urlopen(req, timeout=8) as r:
            d = _j.loads(r.read())
        if d.get('ok'):
            log.info('TG: hot jobs alert sent (%d jobs)', len(jobs))
        else:
            log.warning('TG: send failed: %s', d.get('description'))
    except Exception as e:
        log.warning('TG notify error: %s', e)

def main():
    log.info("=== Freelance scanner v2 starting ===")
    all_jobs = []
    seen_urls = set()

    for name, url in FEEDS:
        tree = fetch_feed(name, url)
        if tree is None:
            continue
        channel = tree.find('channel')
        items = channel.findall('item') if channel else tree.findall('.//item')
        count = 0
        for item in items[:25]:
            title = clean_html(item.findtext('title') or '')
            desc  = clean_html(item.findtext('description') or item.findtext('summary') or '')
            link  = (item.findtext('link') or '').strip()
            pub   = (item.findtext('pubDate') or '').strip()
            if not title or link in seen_urls:
                continue
            seen_urls.add(link)
            score = score_job(title, desc)
            if score >= 2:
                job = {
                    'title': title, 'source': name, 'url': link,
                    'score': score, 'desc': desc[:200], 'pub': pub,
                    'ts': time.time(), 'date': datetime.now().isoformat(),
                }
                all_jobs.append(job)
                save_lead(job)
                log.info("Match [%d]: %s", score, title[:60])
                count += 1
        log.info("Feed %s: %d matches", name, count)

    all_jobs.sort(key=lambda x: x['score'], reverse=True)
    added = save_to_knowledge(all_jobs[:15])

    summary = (
        "Freelance scan: %d matches, %d saved | %s"
        % (len(all_jobs), added, datetime.now().strftime('%Y-%m-%d %H:%M'))
    )
    hot_jobs = [j for j in all_jobs if j['score'] >= HOT_THRESHOLD]
    log.info('Found %d hot jobs (score>=%d) from %d total', len(hot_jobs), HOT_THRESHOLD, len(all_jobs))
    if hot_jobs:
        _tg_notify_hot(hot_jobs)
    else:
        log.info('No hot jobs this run')
    log.info("Done: %d matches, %d saved", len(all_jobs), added)
    print(summary)

    if all_jobs:
        print("\nTop matches:")
        for j in all_jobs[:5]:
            print("  [%d] %s (%s)" % (j['score'], j['title'][:70], j['source']))

    # Post summary to dashboard
    try:
        import urllib.request
        summary_data = json.dumps({
            "content": summary,
            "category": "freelance_daily_report",
            "source": "freelance_scanner_v2",
        }).encode()
        req = urllib.request.Request(
            "http://localhost:8090/api/knowledge/add",
            data=summary_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

if __name__ == '__main__':
    main()
