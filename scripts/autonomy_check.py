#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autonomy_check.py — MaxAI System Autonomy Watchdog
Runs every 5 minutes via cron. Checks all critical systems,
auto-fixes issues, sends Telegram alerts.
"""
import json, os, subprocess, time, urllib.request
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BASE        = Path('/root/my_personal_ai')
ENV_FILE    = BASE / '.env'
LOG_FILE    = BASE / 'logs' / 'autonomy_check.log'

def _load_env() -> dict:
    env: dict = {}
    try:
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception:
        pass
    return {**env, **os.environ}

ENV       = _load_env()
BOT_TOKEN = ENV.get('TELEGRAM_BOT_TOKEN', '')
CHAT_ID   = ENV.get('TELEGRAM_CHAT_ID', '1985320458')

REQUIRED_SERVICES = [
    'maxai-tgbot',
    'corp-tgbot',
    'personal-ai',
    'bybit-monitor',
    'nginx',
]

API_CHECKS = [
    ('http://127.0.0.1:8090/api/v1/status',       'Panel /api/v1/status'),
    ('http://127.0.0.1:8090/api/trading/balance',  'Trading balance'),
    ('http://127.0.0.1:8090/api/aaas/engine',      'AaaS engine'),
    ('http://127.0.0.1:8090/api/aaas/revenue',     'AaaS revenue'),
    ('http://127.0.0.1:8090/api/services',         'Services'),
]

KWORK_SCAN_LOG   = BASE / 'logs' / 'kwork_scan.log'
BOT_LOG_CORP     = BASE / 'logs' / 'corp_tgbot.log'
BOT_RESTART_LOCK = Path('/tmp/autonomy_restart.lock')

# ── Helpers ───────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

def tg_alert(msg: str) -> None:
    if not BOT_TOKEN:
        return
    try:
        data = json.dumps({'chat_id': CHAT_ID, 'text': msg[:4000],
                           'parse_mode': 'HTML'}).encode()
        req  = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log(f'TG alert failed: {e}')

def svc_active(name: str) -> bool:
    try:
        r = subprocess.run(
            ['systemctl', 'is-active', name + '.service'],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip() == 'active'
    except Exception:
        return False

def svc_restart(name: str) -> bool:
    try:
        subprocess.run(['systemctl', 'restart', name + '.service'],
                       timeout=30, check=True)
        time.sleep(5)
        return svc_active(name)
    except Exception as e:
        log(f'restart {name} failed: {e}')
        return False

def api_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            return r.status < 400
    except Exception:
        return False

def check_kwork_recent(minutes: int = 20) -> bool:
    """Return True if kwork scan ran within last N minutes."""
    try:
        if not KWORK_SCAN_LOG.exists():
            return False
        mtime = KWORK_SCAN_LOG.stat().st_mtime
        return (time.time() - mtime) < (minutes * 60)
    except Exception:
        return False

def check_corp_bot_409() -> bool:
    """Return True (problem exists) if 409 seen in last 5 min of corp log."""
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'corp-tgbot.service', '--since', '5 minutes ago',
             '--no-pager', '-q'],
            capture_output=True, text=True, timeout=10
        )
        return '409' in result.stdout
    except Exception:
        return False

def check_aaas_revenue() -> bool:
    """Return True if AaaS engine has been active (cycle > 0)."""
    try:
        with urllib.request.urlopen('http://127.0.0.1:4000/api/aaas/engine', timeout=5) as r:
            d = json.loads(r.read())
            cycle = int(d.get('cycle', d.get('cycle_count', 0)) or 0)
            return cycle > 0
    except Exception:
        return False

# ── Main checks ───────────────────────────────────────────────────────────────
def main() -> None:
    log('=== Autonomy check START ===')
    issues  = []
    fixes   = []
    alerts  = []

    # 1. Required services
    for svc in REQUIRED_SERVICES:
        if not svc_active(svc):
            issues.append(f'Service DOWN: {svc}')
            log(f'FAIL service {svc} — restarting...')
            ok = svc_restart(svc)
            if ok:
                fixes.append(f'Restarted {svc}')
                log(f'OK restarted {svc}')
            else:
                alerts.append(f'\U0001f6a8 Service {svc} failed to restart!')
                log(f'ERROR could not restart {svc}')

    # 2. API checks
    for url, label in API_CHECKS:
        if not api_ok(url):
            issues.append(f'API down: {label}')
            log(f'FAIL api {label}')
            # Try restarting personal-ai once
            if 'personal-ai' not in fixes:
                ok = svc_restart('personal-ai')
                if ok:
                    fixes.append('Restarted personal-ai (API recovery)')
                    log('OK restarted personal-ai for API recovery')
                else:
                    alerts.append(f'\U0001f6a8 API {label} unreachable, personal-ai restart failed!')

    # 3. Kwork scanner
    if not check_kwork_recent(20):
        issues.append('Kwork scan not run in 20 min')
        log('WARN kwork scan stale — triggering manually')
        try:
            subprocess.Popen(
                ['/root/venv/bin/python3',
                 str(BASE / 'scripts' / 'kwork_scan_v2.py')],
                start_new_session=True
            )
            fixes.append('Triggered kwork_scan_v2.py manually')
        except Exception as e:
            alerts.append(f'\U0001f6a8 Kwork scan trigger failed: {e}')

    # 4. Corp bot 409 check
    if check_corp_bot_409():
        issues.append('Corp bot 409 CONFLICT in last 5 min')
        log('WARN corp bot 409 detected — restarting')
        ok = svc_restart('corp-tgbot')
        if ok:
            fixes.append('Restarted corp-tgbot (409 recovery)')
        else:
            alerts.append('\U0001f6a8 corp-tgbot restart failed after 409!')

    # 5. AaaS revenue engine — managed by systemd, use systemctl only
    if not check_aaas_revenue():
        issues.append('AaaS engine not responding via API')
        log('WARN AaaS engine API not responding — using systemctl restart')
        try:
            ok = svc_restart('maxai-aaas')
            if ok:
                fixes.append('Restarted maxai-aaas via systemctl')
                log('OK maxai-aaas restarted via systemctl')
            else:
                alerts.append('⚨ maxai-aaas systemctl restart failed!')
        except Exception as e:
            log(f'aaas restart err: {e}')

    # 6. Report
    if issues:
        summary = (
            f'<b>\U0001f916 MaxAI Autonomy Check</b>\n\n'
            f'<b>Проблемы ({len(issues)}):</b>\n'
            + ''.join(f'  • {i}\n' for i in issues) +
            (f'\n<b>Исправлено:</b>\n' + ''.join(f'  ✅ {f}\n' for f in fixes) if fixes else '') +
            (f'\n<b>Требует внимания:</b>\n' + ''.join(f'  {a}\n' for a in alerts) if alerts else '') +
            f'\n<i>{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</i>'
        )
        log(f'Issues: {issues}')
        log(f'Fixes:  {fixes}')
        tg_alert(summary)
    else:
        log('All checks OK')

    log('=== Autonomy check END ===')

if __name__ == '__main__':
    main()
