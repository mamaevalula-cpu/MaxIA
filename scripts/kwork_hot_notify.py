#!/usr/bin/env python3
"""Send Kwork hot projects to Telegram for manual apply."""
import json, os, re, urllib.request, urllib.parse
from pathlib import Path

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
CHAT  = os.getenv('TELEGRAM_CHAT_ID', '1985320458')
SEEN  = Path('/root/my_personal_ai/data/kwork_notified.json')

def load_seen():
    try: return set(json.loads(SEEN.read_text()))
    except: return set()

def save_seen(s): SEEN.write_text(json.dumps(list(s)[-500:]))

def tg(msg):
    if not TOKEN: return
    try:
        data = json.dumps({'chat_id': CHAT, 'text': msg, 'parse_mode': 'HTML', 'disable_web_page_preview': True}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'}), timeout=5)
    except: pass

def get_hot_projects():
    # Read from kwork scan log
    log = Path('/root/my_personal_ai/logs/kwork_scan.log')
    if not log.exists(): return []
    
    # Parse last scan results
    content = log.read_text()
    lines = content.split('\n')
    
    # Find hot projects from recent scans
    projects = []
    for i, line in enumerate(lines[-300:]):
        if 'HOT' in line or ('кворк' in line.lower() and len(line) > 30):
            projects.append(line.strip())
        # Also look for project titles
        if 'title' in line.lower() or 'проект' in line.lower():
            if len(line) > 20:
                projects.append(line.strip())
    
    return list(set(projects))[:10]

# Main: send top 3 to TG
seen = load_seen()
projects = get_hot_projects()

new_p = [p for p in projects if p not in seen][:3]
if new_p:
    msg = '🔥 Kwork: горячие проекты для отклика!\n\n' + '\n\n'.join(f'• {p[:150]}' for p in new_p)
    msg += '\n\n💡 Открой kwork.ru/projects и откликнись вручную'
    tg(msg)
    seen.update(new_p)
    save_seen(seen)
    print(f'Sent {len(new_p)} hot projects')
else:
    print('No new hot projects to send')
