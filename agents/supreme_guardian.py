#!/usr/bin/env python3
"""
supreme_guardian.py — MaxAI Верховный Страж 24/7
Мониторит ВСЕ сервисы, перезапускает при падении, авто-чинит ошибки.
Запускается как systemd-сервис maxai-guardian.service
"""
import json, logging, os, subprocess, sys, time, hmac, hashlib, threading
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request

# ─── Config ────────────────────────────────────────────────────────────────
TG_TOKEN  = '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM'
TG_CHAT   = '1985320458'
CHECK_INTERVAL = 120   # seconds between full checks
ALERT_COOLDOWN = 600   # don't repeat same alert within 10min

LOG_DIR = Path('/root/my_personal_ai/logs')
LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = Path('/root/my_personal_ai/data/guardian_state.json')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(LOG_DIR / 'guardian.log')),
    ]
)
log = logging.getLogger('guardian')

# ─── Services to monitor ────────────────────────────────────────────────────
SERVICES = {
    'bybit-monitor': {
        'name': 'Bybit Trading Bot',
        'critical': True,
        'restart_cmd': 'systemctl restart bybit-monitor',
        'fix_hints': ['bybit_monitor.py', 'IndentationError', 'SyntaxError'],
    },
    'personal-ai': {
        'name': 'Personal AI (port 8090)',
        'critical': True,
        'restart_cmd': 'systemctl restart personal-ai',
        'fix_hints': ['main.py', 'ImportError', 'ModuleNotFound'],
    },
    'hyperion-control-plane-v2': {
        'name': 'MaxAI Control Plane (port 8006)',
        'critical': True,
        'restart_cmd': 'systemctl restart hyperion-control-plane-v2',
        'fix_hints': [],
    },
    'nginx': {
        'name': 'Nginx (port 80)',
        'critical': True,
        'restart_cmd': 'systemctl restart nginx',
        'fix_hints': [],
    },
    'postgresql': {
        'name': 'PostgreSQL Database',
        'critical': False,
        'restart_cmd': 'systemctl restart postgresql',
        'fix_hints': [],
    },
}

# ─── HTTP endpoints to check ────────────────────────────────────────────────
HTTP_CHECKS = [
    {'url': 'http://127.0.0.1:8090/health', 'name': 'personal-ai health', 'service': 'personal-ai'},
    {'url': 'http://127.0.0.1:8006/health', 'name': 'hyperion status', 'service': 'hyperion-control-plane-v2'},
    {'url': 'http://127.0.0.1:8001/status', 'name': 'bybit-bot status', 'service': 'bybit-monitor'},
]

# ─── Telegram ──────────────────────────────────────────────────────────────
def tg(text: str, silent: bool = False):
    try:
        payload = {
            'chat_id': TG_CHAT,
            'text': text[:4096],
            'parse_mode': 'HTML',
            'disable_notification': silent,
        }
        data = json.dumps(payload).encode()
        req = Request(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'}
        )
        urlopen(req, timeout=10)
    except Exception as e:
        log.warning('TG error: %s', e)

# ─── State management ───────────────────────────────────────────────────────
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {'alerts': {}, 'restarts': {}, 'total_restarts': 0, 'uptime_start': datetime.utcnow().isoformat()}

def save_state(s: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))

# ─── Service checks ─────────────────────────────────────────────────────────
def check_service(name: str) -> str:
    """Returns: active | failed | inactive | unknown"""
    try:
        r = subprocess.run(
            ['systemctl', 'is-active', name],
            capture_output=True, text=True, timeout=5
        )
        return r.stdout.strip()
    except Exception:
        return 'unknown'

def restart_service(name: str, info: dict) -> bool:
    """Restart service and return True if successful."""
    log.warning('Restarting %s...', name)
    try:
        r = subprocess.run(
            info['restart_cmd'].split(), capture_output=True, text=True, timeout=30
        )
        time.sleep(5)
        new_status = check_service(name)
        ok = new_status == 'active'
        log.info('Restart %s: %s → %s', name, 'OK' if ok else 'FAILED', new_status)
        return ok
    except Exception as e:
        log.error('Restart failed for %s: %s', name, e)
        return False

def check_http(url: str) -> bool:
    try:
        req = Request(url)
        with urlopen(req, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False

# ─── Auto-fix logic ─────────────────────────────────────────────────────────
def get_service_error(name: str) -> str:
    """Get last error from journalctl."""
    try:
        r = subprocess.run(
            ['journalctl', '-u', name, '-n', '20', '--no-pager', '-q'],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout[-500:] if r.stdout else ''
    except Exception:
        return ''

def try_autofix(name: str, info: dict) -> bool:
    """Attempt to auto-fix known error patterns."""
    error_log = get_service_error(name)

    if 'bybit-monitor' in name:
        # Check for syntax error
        r = subprocess.run(
            ['/root/venv/bin/python3', '-m', 'py_compile', '/root/bybit-bot/bybit_monitor.py'],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode != 0:
            log.error('bybit_monitor.py syntax error: %s', r.stderr[:200])
            # Emergency: restore from backup
            backup = Path('/root/bybit-bot/bybit_monitor.py.bak')
            if backup.exists():
                import shutil
                shutil.copy(backup, '/root/bybit-bot/bybit_monitor.py')
                log.info('Restored bybit_monitor.py from backup')
                return True
            return False

    if 'IndentationError' in error_log or 'SyntaxError' in error_log:
        log.warning('Syntax error detected in %s', name)

    if 'ModuleNotFoundError' in error_log or 'ImportError' in error_log:
        log.warning('Import error in %s — trying pip install', name)
        module_match = None
        for line in error_log.split('\n'):
            if 'No module named' in line:
                try:
                    module_match = line.split("'")[1].split('.')[0]
                except Exception:
                    pass
        if module_match:
            subprocess.run(
                ['/root/venv/bin/pip', 'install', module_match, '-q'],
                timeout=60
            )

    return False

# ─── Disk and resource checks ───────────────────────────────────────────────
def check_resources() -> dict:
    result = {}
    try:
        # Disk usage
        r = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
        for line in r.stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5:
                result['disk_use_pct'] = int(parts[4].replace('%', ''))
                result['disk_free'] = parts[3]
    except Exception:
        pass

    try:
        # Memory
        r = subprocess.run(['free', '-m'], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if line.startswith('Mem:'):
                parts = line.split()
                total = int(parts[1])
                used = int(parts[2])
                result['mem_used_pct'] = round(used / total * 100)
                result['mem_free_mb'] = int(parts[3]) if len(parts) > 3 else 0
    except Exception:
        pass

    try:
        # Load
        with open('/proc/loadavg') as f:
            la = f.read().split()
            result['load_1m'] = float(la[0])
    except Exception:
        pass

    return result

# ─── Log rotation ───────────────────────────────────────────────────────────
def rotate_large_logs():
    """Truncate log files > 50MB."""
    for logfile in LOG_DIR.glob('*.log'):
        try:
            size_mb = logfile.stat().st_size / 1024 / 1024
            if size_mb > 50:
                # Keep last 10000 lines
                r = subprocess.run(['tail', '-n', '10000', str(logfile)], capture_output=True)
                logfile.write_bytes(r.stdout)
                log.info('Rotated %s (was %.1fMB)', logfile.name, size_mb)
        except Exception as e:
            log.warning('Log rotation error %s: %s', logfile.name, e)

# ─── Cron sanity check ──────────────────────────────────────────────────────
REQUIRED_CRONS = [
    'revenue_executor',
    'kwork_agent',
    'daily_revenue_report',
    'bybit_earn',
]

def check_crons():
    """Ensure critical cron jobs exist."""
    try:
        r = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
        current = r.stdout
        missing = [c for c in REQUIRED_CRONS if c not in current]
        if missing:
            log.warning('Missing cron jobs: %s', missing)
            return missing
    except Exception:
        pass
    return []

# ─── Main guardian loop ─────────────────────────────────────────────────────
def guardian_loop():
    state = load_state()
    log.info('Supreme Guardian started. Monitoring %d services.', len(SERVICES))

    tg(
        '🛡️ <b>MaxAI Supreme Guardian запущен</b>\n'
        f'⏰ {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}\n'
        f'🔍 Мониторинг: {", ".join(SERVICES.keys())}\n'
        f'⏱️ Интервал проверки: {CHECK_INTERVAL}s',
        silent=True
    )

    consecutive_failures = {}
    last_resource_alert = 0
    last_rotate = 0
    cycle = 0

    while True:
        try:
            cycle += 1
            now = time.time()
            problems = []
            recoveries = []

            # ── Check all services ──────────────────────────────────────────
            for svc_name, svc_info in SERVICES.items():
                status = check_service(svc_name)

                if status == 'active':
                    # Service is OK
                    was_failing = consecutive_failures.get(svc_name, 0) > 0
                    if was_failing:
                        recoveries.append(f'✅ {svc_info["name"]} восстановлен')
                        log.info('RECOVERED: %s', svc_name)
                    consecutive_failures[svc_name] = 0

                else:
                    # Service is down
                    consecutive_failures[svc_name] = consecutive_failures.get(svc_name, 0) + 1
                    fails = consecutive_failures[svc_name]
                    log.warning('Service %s is %s (fail count: %d)', svc_name, status, fails)

                    # Try autofix first
                    if fails == 1:
                        try_autofix(svc_name, svc_info)

                    # Restart
                    ok = restart_service(svc_name, svc_info)

                    state['restarts'][svc_name] = state['restarts'].get(svc_name, 0) + 1
                    state['total_restarts'] = state.get('total_restarts', 0) + 1

                    # Alert logic
                    alert_key = f'alert_{svc_name}'
                    last_alert = state['alerts'].get(alert_key, 0)

                    if now - last_alert > ALERT_COOLDOWN:
                        if ok:
                            problems.append(f'⚠️ <b>{svc_info["name"]}</b> упал → перезапущен ✅')
                        else:
                            emoji = '🚨' if svc_info['critical'] else '⚠️'
                            problems.append(f'{emoji} <b>{svc_info["name"]}</b> упал и не восстановился!')
                        state['alerts'][alert_key] = now

            # ── HTTP health checks (every 5 cycles) ─────────────────────────
            if cycle % 5 == 0:
                for check in HTTP_CHECKS:
                    ok = check_http(check['url'])
                    if not ok:
                        log.warning('HTTP check failed: %s', check['name'])
                        # Try restarting the associated service
                        svc = check.get('service')
                        if svc and svc in SERVICES:
                            s = check_service(svc)
                            if s != 'active':
                                restart_service(svc, SERVICES[svc])

            # ── Resource checks (every 10 cycles) ───────────────────────────
            if cycle % 10 == 0:
                res = check_resources()

                disk_pct = res.get('disk_use_pct', 0)
                mem_pct = res.get('mem_used_pct', 0)
                load = res.get('load_1m', 0)

                alerts_needed = []
                if disk_pct > 90:
                    alerts_needed.append(f'💾 Диск заполнен на {disk_pct}%! Осталось {res.get("disk_free", "?")}')
                if mem_pct > 95:
                    alerts_needed.append(f'🧠 ОЗУ {mem_pct}% использовано! Свободно {res.get("mem_free_mb", "?")}MB')
                if load > 8:
                    alerts_needed.append(f'🔥 Высокая нагрузка CPU: {load}')

                if alerts_needed and now - last_resource_alert > 1800:
                    problems.extend(alerts_needed)
                    last_resource_alert = now

            # ── Log rotation (every 100 cycles) ─────────────────────────────
            if cycle % 100 == 0:
                rotate_large_logs()

            # ── Send alerts ──────────────────────────────────────────────────
            if problems or recoveries:
                lines = ['🛡️ <b>MaxAI Guardian Alert</b>', f'⏰ {datetime.utcnow().strftime("%H:%M UTC")}', '']
                lines.extend(recoveries)
                lines.extend(problems)
                tg('\n'.join(lines))

            # ── Heartbeat (every 60 cycles = every 2 hours) ─────────────────
            if cycle % 60 == 0:
                svcs_ok = sum(1 for s in SERVICES if check_service(s) == 'active')
                tg(
                    f'💚 <b>Guardian Heartbeat</b>\n'
                    f'✅ Сервисов активно: {svcs_ok}/{len(SERVICES)}\n'
                    f'🔄 Перезапусков всего: {state.get("total_restarts", 0)}\n'
                    f'⏰ {datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")}',
                    silent=True
                )

            save_state(state)

        except Exception as e:
            log.error('Guardian loop error: %s', e)

        time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
    guardian_loop()
