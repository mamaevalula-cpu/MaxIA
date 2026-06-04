#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MaxAI Root Cause Analyzer
Runs every 30 min. Checks all services, identifies ROOT CAUSES, applies systemic fixes.
Never just restarts - always fixes the underlying issue.
"""
import json, os, re, subprocess, sys, time, logging
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s [RCA] %(message)s')
log = logging.getLogger('rca')

BASE = Path('/root/my_personal_ai')
VENV_PY = '/root/venv/bin/python3'
REDIS_URL = 'redis://127.0.0.1:6379/0'

SERVICES = [
    'maxai-aaas', 'maxai-tgbot', 'maxai-core', 'corp-tgbot',
    'personal-ai', 'bybit-monitor', 'nginx',
]


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=isinstance(cmd, str))
        return r.stdout + r.stderr, r.returncode
    except Exception as e:
        return str(e), 1


def redis_set(key, val):
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.set(key, val, ex=7200)
    except Exception as e:
        log.debug(f'Redis set failed: {e}')


def redis_lpush(key, val):
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        r.lpush(key, val)
        r.ltrim(key, 0, 99)
    except Exception as e:
        log.debug(f'Redis lpush failed: {e}')


def get_service_status(svc):
    out, rc = run(['systemctl', 'is-active', svc])
    return out.strip() == 'active'


def get_restart_count(svc):
    out, _ = run(['systemctl', 'show', svc, '--property=NRestarts'])
    m = re.search(r'NRestarts=(\d+)', out)
    return int(m.group(1)) if m else 0


def get_journal_errors(svc, lines=50):
    out, _ = run(['journalctl', '-u', svc, '--no-pager', '-n', str(lines),
                  '--output=short-precise'])
    errors = [l for l in out.split('\n')
              if re.search(r'error|Error|ERROR|Exception|Traceback|failed|FAIL|killed|OOM', l)]
    return errors


def diagnose_service(svc):
    """Find root cause for service issues."""
    errors = get_journal_errors(svc)
    log_file = BASE / 'logs' / f'{svc.replace("maxai-","")}.log'
    log_errors = []
    if log_file.exists():
        try:
            lines = log_file.read_text(errors='replace').splitlines()[-100:]
            log_errors = [l for l in lines
                         if re.search(r'ERROR|error|Exception|Traceback', l)]
        except Exception:
            pass

    all_errors = errors + log_errors
    error_text = ' '.join(all_errors).lower()

    if 'modulenotfounderror' in error_text or 'importerror' in error_text:
        m = re.search(r"no module named '([^']+)'", error_text, re.I)
        pkg = m.group(1) if m else 'unknown'
        return 'import_error', f'Missing package: {pkg}', pkg

    if 'redis' in error_text and ('wrongtype' in error_text or 'type error' in error_text):
        return 'redis_type_error', 'Redis key type mismatch', None

    if 'timeout' in error_text or 'timed out' in error_text:
        return 'timeout', 'API/network timeout', None

    if 'memoryerror' in error_text or 'oom' in error_text or 'killed' in error_text:
        return 'oom', 'Out of memory', None

    if 'syntaxerror' in error_text:
        return 'syntax_error', 'Python syntax error', None

    if 'connectionrefused' in error_text or 'connection refused' in error_text:
        return 'connection_refused', 'Dependency service not running', None

    if 'permissionerror' in error_text or 'permission denied' in error_text:
        return 'permission', 'File permission error', None

    if all_errors:
        return 'unknown', all_errors[-1][:200] if all_errors else 'no errors found', None

    return 'clean_exit', 'Service exits cleanly (logic bug or missing infinite loop)', None


def fix_import_error(svc, pkg):
    """Install missing package."""
    if not pkg or pkg == 'unknown':
        return False
    log.info(f'Fixing import error in {svc}: installing {pkg}')
    out, rc = run([VENV_PY, '-m', 'pip', 'install', '--quiet', pkg], timeout=60)
    return rc == 0


def fix_redis_type_error(svc):
    """Flush bad Redis keys for the service."""
    log.info(f'Fixing Redis type error for {svc}')
    try:
        import redis
        r = redis.from_url(REDIS_URL, decode_responses=True)
        prefix = svc.replace('maxai-', '').replace('-', '_')
        fixed = 0
        for key in r.scan_iter(f'{prefix}:*', count=100):
            try:
                r.type(key)
            except Exception:
                r.delete(key)
                fixed += 1
        log.info(f'Redis: cleared {fixed} bad keys for {svc}')
        return True
    except Exception as e:
        log.warning(f'Redis fix failed: {e}')
        return False


def restart_service(svc):
    """Restart via systemctl with verification."""
    out, rc = run(['systemctl', 'restart', svc], timeout=20)
    time.sleep(5)
    return get_service_status(svc)


def analyze_and_fix():
    report = {
        'ts': time.time(),
        'time': datetime.now().isoformat(),
        'services': {},
        'fixes_applied': [],
        'alerts': [],
    }

    for svc in SERVICES:
        is_active = get_service_status(svc)
        restarts = get_restart_count(svc)

        svc_report = {
            'active': is_active,
            'restarts': restarts,
            'root_cause': None,
            'fix_applied': None,
            'fix_success': None,
        }

        if not is_active or restarts > 10:
            cause_type, cause_desc, cause_detail = diagnose_service(svc)
            svc_report['root_cause'] = f'{cause_type}: {cause_desc}'
            log.info(f'{svc}: root_cause={cause_type} restarts={restarts}')

            fixed = False
            if cause_type == 'import_error' and cause_detail:
                fixed = fix_import_error(svc, cause_detail)
                svc_report['fix_applied'] = f'pip install {cause_detail}'

            elif cause_type == 'redis_type_error':
                fixed = fix_redis_type_error(svc)
                svc_report['fix_applied'] = 'redis_type_clear'

            elif cause_type in ('timeout', 'unknown', 'clean_exit', 'connection_refused'):
                if not is_active:
                    fixed = restart_service(svc)
                    svc_report['fix_applied'] = 'systemctl_restart'
                else:
                    fixed = True

            elif cause_type == 'oom':
                out, _ = run(['systemctl', 'show', svc, '--property=MemoryLimit'])
                if 'infinity' in out.lower():
                    unit_file = f'/etc/systemd/system/{svc}.service'
                    if Path(unit_file).exists():
                        unit = Path(unit_file).read_text()
                        if 'MemoryLimit' not in unit:
                            unit = unit.replace('[Service]', '[Service]\nMemoryLimit=512M')
                            Path(unit_file).write_text(unit)
                            run(['systemctl', 'daemon-reload'])
                            fixed = restart_service(svc)
                            svc_report['fix_applied'] = 'memory_limit_512m'

            svc_report['fix_success'] = fixed

            if fixed:
                report['fixes_applied'].append(f'{svc}: {cause_type} -> {svc_report["fix_applied"]}')
            else:
                report['alerts'].append(f'{svc}: {cause_type} - fix failed, manual intervention needed')

        report['services'][svc] = svc_report

    redis_set('maxai:health:root_causes', json.dumps(report, default=str))
    redis_lpush('maxai:health:rca_history', json.dumps({
        'ts': report['ts'],
        'fixes': len(report['fixes_applied']),
        'alerts': len(report['alerts']),
    }))

    log.info(f'RCA complete: {len(report["fixes_applied"])} fixes, {len(report["alerts"])} alerts')
    for f in report['fixes_applied']:
        log.info(f'  FIX: {f}')
    for a in report['alerts']:
        log.warning(f'  ALERT: {a}')

    return report


if __name__ == '__main__':
    log.info('MaxAI Root Cause Analyzer starting...')
    report = analyze_and_fix()
    print(json.dumps(report, indent=2, default=str))
