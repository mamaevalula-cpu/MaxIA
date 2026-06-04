#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MaxAI Kwork Order Checker
Runs every hour via cron. Reports pending proposals, checks for accepted orders.
When Kwork API becomes available, integrates proper status checks.
"""
import json, time, logging
from pathlib import Path
from datetime import datetime

LOG = Path('/root/my_personal_ai/logs/kwork_orders.log')
LOG.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [KWORK_ORDERS] %(message)s',
    handlers=[logging.FileHandler(str(LOG)), logging.StreamHandler()]
)
log = logging.getLogger(__name__)

ENV = Path('/root/my_personal_ai/.env')
REDIS_URL = 'redis://127.0.0.1:6379/0'
OWNER_ID = '1985320458'


def env_get(k):
    if not ENV.exists(): return ''
    for l in ENV.read_text().splitlines():
        if '=' in l and l.startswith(k + '='): return l.split('=', 1)[1].strip()
    return ''


def redis_conn():
    try:
        import redis as _r
        return _r.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error(f'Redis connect: {e}')
        return None


def tg_send(msg):
    import urllib.request
    tok = env_get('TELEGRAM_BOT_TOKEN')
    if not tok:
        log.warning('No TELEGRAM_BOT_TOKEN')
        return
    try:
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{tok}/sendMessage',
            data=json.dumps({'chat_id': OWNER_ID, 'text': msg, 'parse_mode': 'HTML',
                             'disable_web_page_preview': True}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST'
        )
        urllib.request.urlopen(req, timeout=10)
        log.info('TG alert sent')
    except Exception as e:
        log.error(f'TG send failed: {e}')


def check_pending_proposals(r):
    """Count proposals that have been sent but not yet accepted (< 48h old)."""
    now_ts = time.time()
    ttl_48h = 48 * 3600

    # From timestamped applied dict
    applied_raw = r.get('kwork:applied_ts')
    pending_count = 0
    pending_details = []

    if applied_raw:
        try:
            applied_dict = json.loads(applied_raw)
            for proj_id, ts in applied_dict.items():
                age_hours = (now_ts - float(ts)) / 3600
                if age_hours < 48:
                    pending_count += 1
                    pending_details.append({
                        'proj_id': proj_id,
                        'sent_ago_hours': round(age_hours, 1),
                    })
        except Exception as e:
            log.warning(f'Error parsing applied_ts: {e}')

    return pending_count, pending_details


def get_total_proposals(r):
    """Get total proposals counter."""
    return int(r.get('kwork:proposals:total') or 0)


def get_last_scan(r):
    """Get last scan result."""
    raw = r.get('kwork:scan:last')
    if raw:
        try:
            return json.loads(raw)
        except:
            pass
    return {}


def run():
    log.info('=== Kwork Order Checker Run ===')
    r = redis_conn()
    if not r:
        log.error('Cannot connect to Redis')
        return {'error': 'redis_unavailable'}

    pending_count, pending_details = check_pending_proposals(r)
    total_proposals = get_total_proposals(r)
    last_scan = get_last_scan(r)
    last_scan_time = last_scan.get('ts', 0)
    last_scan_ago_min = (time.time() - last_scan_time) / 60 if last_scan_time else 999

    result = {
        'pending_proposals': pending_count,
        'total_proposals': total_proposals,
        'last_scan_ago_min': round(last_scan_ago_min, 1),
        'last_scan_hot': last_scan.get('hot', 0),
        'last_scan_total': last_scan.get('total', 0),
        'checked_at': datetime.now().isoformat(),
    }

    log.info(f'Pending proposals (< 48h): {pending_count}')
    log.info(f'Total proposals sent ever: {total_proposals}')
    log.info(f'Last scan: {last_scan_ago_min:.1f} min ago, hot={last_scan.get("hot", 0)}')

    # Update Redis with checker result
    r.set('kwork:order_checker:last', json.dumps(result))

    # Send hourly summary to owner if there are pending proposals
    if pending_count > 0 or total_proposals == 0:
        msg = (
            f'\U0001f4cb <b>Kwork Order Report</b>\n\n'
            f'⏳ Ожидают ответа: <b>{pending_count}</b> откликов\n'
            f'\U0001f4e4 Всего отправлено: <b>{total_proposals}</b>\n'
            f'\U0001f52d Последнее сканирование: {last_scan_ago_min:.0f} мин назад\n'
            f'\U0001f525 Горячих проектов: {last_scan.get("hot", 0)}\n\n'
        )
        if total_proposals == 0:
            msg += (
                '⚠️ <b>Ни одного отклика не отправлено!</b>\n'
                'Возможные причины:\n'
                '• Все проекты уже в списке применённых\n'
                '• Браузер не авторизован на Kwork\n'
                '• Ошибка отправки формы\n\n'
                'Действие: проверь /root/my_personal_ai/logs/kwork_scan.log'
            )
        else:
            msg += '\U0001f4a1 Когда заказчик примет отклик — оплата придёт на кошелёк.'

        # Only send if last run had pending > 0 to avoid spam
        # Send max once per 4 hours
        last_alert_ts = float(r.get('kwork:order_checker:last_alert_ts') or 0)
        if (time.time() - last_alert_ts) > 4 * 3600:
            tg_send(msg)
            r.set('kwork:order_checker:last_alert_ts', time.time())

    # TODO: When Kwork API becomes available, implement proper order status check:
    # GET https://api.kwork.ru/orders?status=accepted
    # This would detect accepted proposals and trigger payment flow

    return result


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, ensure_ascii=False, indent=2))
