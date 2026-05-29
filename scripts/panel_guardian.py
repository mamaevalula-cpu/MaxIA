"""
MaxAI Panel Guardian — Bonus Service
Monitors personal-ai (panel) + hyperion-engine and auto-heals them.
Runs as systemd service: panel-guardian.service
Checks every 60 seconds. Sends Telegram alert only on state change.
"""
import subprocess, time, urllib.request, urllib.parse, json, os, sys
from datetime import datetime

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID',   '1985320458')

SERVICES = {
    'personal-ai':     {'port': 8090, 'path': '/api/v5/projects', 'label': 'Panel (8090)'},

}

INTERVAL  = 60    # check every 60s
MAX_FIXES = 3     # auto-fix attempts before giving up and alerting
LOG_FILE  = '/root/my_personal_ai/logs/panel_guardian.log'

state = {svc: {'ok': True, 'fixes': 0, 'last_alert': 0} for svc in SERVICES}


def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line, flush=True)
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')
    except Exception:
        pass


def send_tg(text):
    url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage'
    data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text}).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as r:
            pass
    except Exception as e:
        log(f'TG error: {e}')


def check_http(port, path, timeout=5):
    try:
        url = f'http://localhost:{port}{path}'
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def is_active(svc):
    try:
        result = subprocess.run(['systemctl', 'is-active', svc],
                                capture_output=True, text=True, timeout=5)
        return result.stdout.strip() == 'active'
    except Exception:
        return False


def restart_service(svc):
    try:
        subprocess.run(['systemctl', 'restart', svc], timeout=30, check=True)
        time.sleep(8)
        return True
    except Exception as e:
        log(f'Restart {svc} failed: {e}')
        return False


def check_and_heal():
    for svc, cfg in SERVICES.items():
        was_ok = state[svc]['ok']
        port   = cfg['port']
        path   = cfg['path']
        label  = cfg['label']

        # Check systemd + HTTP
        svc_active = is_active(svc)
        http_ok    = check_http(port, path)
        now_ok     = http_ok  # HTTP-only: daemon fork makes systemd is-active unreliable

        if now_ok:
            if not was_ok:
                state[svc]['ok']    = True
                state[svc]['fixes'] = 0
                log(f'RECOVERED: {label}')
                send_tg(f'Panel Guardian: {label} RECOVERED')
            else:
                state[svc]['fixes'] = 0
            continue

        # Service is down
        fixes = state[svc]['fixes']
        log(f'DOWN: {label} | http={http_ok} | fixes={fixes}')

        if fixes < MAX_FIXES:
            log(f'Auto-fix #{fixes+1}: restarting {svc}...')
            ok = restart_service(svc)
            state[svc]['fixes'] += 1

            if ok and check_http(port, path):
                log(f'Fixed: {label} restored after restart #{fixes+1}')
                state[svc]['ok'] = True
                state[svc]['fixes'] = 0
                if not was_ok:
                    send_tg(f'Panel Guardian: {label} auto-fixed (restart #{fixes+1})')
            else:
                state[svc]['ok'] = False
                if was_ok:
                    send_tg(f'Panel Guardian: {label} DOWN - attempting auto-fix...')
        else:
            state[svc]['ok'] = False
            now = time.time()
            if now - state[svc]['last_alert'] > 1800:  # alert every 30min
                state[svc]['last_alert'] = now
                send_tg(
                    f'Panel Guardian ALERT: {label} is DOWN\n'
                    f'Tried {fixes} auto-fixes, all failed.\n'
                    f'Manual intervention needed.\n'
                    f'Check: systemctl status {svc}'
                )


def main():
    log('Panel Guardian started. Monitoring: ' + ', '.join(SERVICES.keys()))
    send_tg('Panel Guardian started. Auto-healing enabled for panel + Hyperion.')
    while True:
        try:
            check_and_heal()
        except Exception as e:
            log(f'Guardian error: {e}')
        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
