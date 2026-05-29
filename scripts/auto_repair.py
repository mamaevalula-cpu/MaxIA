#!/usr/bin/env python3
"""MaxAI Auto-Repair watchdog: runs every 30 mins via cron, auto-fixes services."""
import subprocess, shutil, os, sys, time
from datetime import datetime
from pathlib import Path

LOG = Path('/root/my_personal_ai/logs/auto_repair.log')
LOG.parent.mkdir(parents=True, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with open(LOG, 'a') as f:
        f.write(line + '\n')

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return -1, str(e)

log('=== MaxAI Auto-Repair START ===')
services = ['personal-ai', 'bybit-monitor', 'maxai-tgbot', 'corp-tgbot', 'nginx', 'redis-server', 'maxai-corporate', 'maxai-edge-router', 'maxai-guardian']
fixed = 0

for svc in services:
    rc, out = run(['systemctl', 'is-active', svc])
    if 'active' not in out:
        log(f'FIXING: {svc} is {out or "inactive"} → restarting...')
        run(['systemctl', 'restart', svc])
        time.sleep(2)
        rc2, out2 = run(['systemctl', 'is-active', svc])
        if 'active' in out2:
            log(f'FIXED: {svc} restarted OK')
            fixed += 1
        else:
            log(f'FAIL: {svc} still down after restart')
    else:
        pass  # all good, no log spam

# Disk check
disk = shutil.disk_usage('/')
free_gb = disk.free / 1024**3
if free_gb < 2:
    log(f'WARNING: disk only {free_gb:.1f}GB free — clearing old logs')
    for lf in sorted(Path('/root/my_personal_ai/logs').glob('*.log'),
                     key=lambda p: p.stat().st_mtime)[:-10]:
        if lf.stat().st_size > 10*1024*1024:
            lf.write_text('')
            log(f'Cleared: {lf.name}')
            fixed += 1


# HTTP health checks — restart if endpoint hangs (catches zombie processes)
_http_checks = [
    ('bybit-monitor',   'http://127.0.0.1:8001/status', 5),
    ('maxai-corporate', 'http://127.0.0.1:8091/api/corporate/health', 4),
]
import urllib.request as _ur
for _svc, _url, _tmo in _http_checks:
    try:
        _ur.urlopen(_url, timeout=_tmo).read()
    except Exception as _he:
        log(f'HTTP check FAIL {_url} ({_he}) — restarting {_svc}')
        run(['systemctl', 'restart', _svc])
        fixed += 1

# API health check
try:
    import urllib.request
    r = urllib.request.urlopen('http://127.0.0.1:8090/api/status', timeout=4)
    if r.getcode() != 200:
        raise Exception(f'status {r.getcode()}')
except Exception as e:
    log(f'API down: {e} — restarting personal-ai')
    run(['systemctl', 'restart', 'personal-ai'])
    fixed += 1

if fixed:
    log(f'Auto-repair complete: {fixed} issues fixed')
else:
    log(f'All systems OK — no repair needed')

log('=== MaxAI Auto-Repair END ===\n')
