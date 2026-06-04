#!/usr/bin/env python3
"""Upwork Job Scanner v2 — uses Playwright to scrape job listings."""
import json, os, logging, time, re, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s [UPWORK] %(message)s',
    handlers=[logging.FileHandler('/root/my_personal_ai/logs/upwork_scanner.log'),
              logging.StreamHandler()])
log = logging.getLogger('upwork')

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT  = os.getenv('TELEGRAM_CHAT_ID', '1985320458')
STATE = Path('/root/my_personal_ai/data/upwork_seen.json')

SEARCH_QUERIES = ['python telegram bot', 'ai automation python', 'chatgpt integration', 'fastapi developer']
HOT_KEYWORDS   = ['python','telegram','bot','ai','chatgpt','fastapi','automation','openai','llm','agent']

def load_seen(): 
    try: return set(json.loads(STATE.read_text()))
    except: return set()

def save_seen(seen): 
    STATE.write_text(json.dumps(list(seen)[-200:]))

def tg(msg):
    if not TOKEN: return
    try:
        data = json.dumps({'chat_id': CHAT, 'text': msg, 'parse_mode': 'HTML', 'disable_web_page_preview': True}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage', data=data,
            headers={'Content-Type': 'application/json'}), timeout=5)
    except: pass

def score_job(title, desc):
    text = (title + ' ' + desc).lower()
    return sum(1 for kw in HOT_KEYWORDS if kw in text)

def main():
    seen = load_seen()
    new_jobs = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
            locale='en-US'
        )
        page = ctx.new_page()
        
        for query in SEARCH_QUERIES[:2]:
            url = f'https://www.upwork.com/nx/jobs/search/?q={query.replace(" ","+")}&sort=recency'
            log.info(f'Scanning: {url}')
            
            try:
                page.goto(url, timeout=25000, wait_until='networkidle')
                time.sleep(3)
                
                # Get job listings
                jobs_data = page.evaluate("""
                    () => {
                        const jobs = [];
                        document.querySelectorAll('[data-test=job-tile], .job-tile, article').forEach(el => {
                            const title = el.querySelector('h2, h3, [data-test=job-title]');
                            const link  = el.querySelector('a[href*="/jobs/"]');
                            const desc  = el.querySelector('[data-test=job-description-text], .description');
                            if (title && link) {
                                jobs.push({
                                    title: title.textContent.trim().slice(0, 100),
                                    url: 'https://www.upwork.com' + (link.href.includes('upwork.com') ? '' : link.pathname),
                                    desc: desc ? desc.textContent.trim().slice(0, 300) : ''
                                });
                            }
                        });
                        return jobs.slice(0, 10);
                    }
                """)
                
                log.info(f'Found {len(jobs_data)} jobs for "{query}"')
                
                for job in jobs_data:
                    job_id = job['url'][-50:]
                    if job_id not in seen and score_job(job['title'], job['desc']) >= 2:
                        new_jobs.append(job)
                        seen.add(job_id)
                        
            except Exception as e:
                log.warning(f'Error scanning {query}: {e}')
        
        browser.close()
    
    log.info(f'New hot jobs: {len(new_jobs)}')
    
    for job in new_jobs[:3]:
        score = score_job(job['title'], job['desc'])
        tg(f'💼 <b>Upwork Hot Job (score:{score})</b>\n\n<b>{job["title"]}</b>\n\n{job["desc"][:200]}...\n\n<a href="{job["url"]}">Открыть на Upwork</a>')
        log.info(f'Sent: {job["title"][:60]}')
    
    save_seen(seen)
    if not new_jobs:
        log.info('No new hot jobs today')

if __name__ == '__main__':
    main()
