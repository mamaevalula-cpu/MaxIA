#!/usr/bin/env python3
"""
MaxAI 24/7 Operations Watchdog
Checks all services, restarts if down, runs revenue tasks.
Runs every 2 min via cron.
"""
import subprocess, json, time, os, urllib.request, logging
from pathlib import Path
from datetime import datetime

LOG = Path('/root/my_personal_ai/logs/watchdog_aaas.log')
LOG.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WD] %(message)s',
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()]
)
log = logging.getLogger()

SERVICES = [
    'maxai-aaas', 'maxai-tgbot', 'maxai-core',
    'maxai-browser', 'personal-ai', 'nginx', 'redis-server',
    'maxai-guardian', 'maxai-corporate'
]
ENDPOINTS = {
    'panel':    ('http://77.90.2.171:3000/', 200),
    'core':     ('http://127.0.0.1:4000/api/aaas/fleet', 200),
    'browser':  ('http://127.0.0.1:8096/health', 200),
    'api':      ('http://127.0.0.1:8090/api/v1/status', 200),
}

def is_active(svc):
    r = subprocess.run(['systemctl','is-active',svc], capture_output=True, text=True)
    return r.stdout.strip() == 'active'

def restart(svc):
    r = subprocess.run(['systemctl','restart',svc], capture_output=True, text=True)
    log.info(f'Restarted {svc}: {r.returncode}')
    return r.returncode == 0

def http_check(url, expected=200, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == expected
    except:
        return False

def notify(msg):
    env = Path('/root/my_personal_ai/.env')
    if not env.exists(): return
    e = dict(l.split('=',1) for l in env.read_text().splitlines() if '=' in l and not l.startswith('#'))
    tok = e.get('TELEGRAM_BOT_TOKEN','')
    cid = e.get('TELEGRAM_OWNER_ID','').strip()
    if not tok or not cid: return
    try:
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{tok}/sendMessage',
            data=json.dumps({'chat_id':cid,'text':msg}).encode(),
            headers={'Content-Type':'application/json'}, method='POST')
        urllib.request.urlopen(req, timeout=5)
    except: pass

# Track downtime
DOWN_TRACK = Path('/tmp/aaas_downtime.json')
if DOWN_TRACK.exists():
    downs = json.loads(DOWN_TRACK.read_text())
else:
    downs = {}

fixed = []
issues = []

# Check services
for svc in SERVICES:
    if not is_active(svc):
        down_since = downs.get(svc, time.time())
        downs[svc] = down_since
        down_mins = (time.time() - down_since) / 60
        log.warning(f'Service DOWN: {svc} (for {down_mins:.0f}m)')
        issues.append(f'{svc} down {down_mins:.0f}m')
        if restart(svc):
            fixed.append(f'restarted {svc}')
            del downs[svc]
            # Alert after 5 min down
            if down_mins > 5:
                notify(f'?? {svc} was down {down_mins:.0f}min ? restarted')
    elif svc in downs:
        del downs[svc]  # recovered

# Check HTTP endpoints
for name, (url, code) in ENDPOINTS.items():
    if not http_check(url, code):
        log.warning(f'HTTP FAIL: {name} ({url})')
        issues.append(f'{name} HTTP fail')
        if name == 'panel':
            subprocess.run(['systemctl','reload','nginx'], capture_output=True)
        elif name == 'core':
            restart('maxai-core')
        elif name == 'api':
            restart('personal-ai')

# Save downtime state
DOWN_TRACK.write_text(json.dumps(downs))

if fixed:
    log.info(f'Fixed: {fixed}')
if not issues:
    log.info('All OK')
