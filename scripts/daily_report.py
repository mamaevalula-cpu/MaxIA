#!/usr/bin/env python3
"""
daily_report.py — Daily system summary via Telegram.
Runs at 08:00 every day via cron.
"""
import sys, os, json, time, urllib.request, urllib.parse, sqlite3, logging
from datetime import datetime

sys.path.insert(0, '/root/my_personal_ai')
sys.path.insert(0, '/root/venv/lib/python3.12/site-packages')

LOG = '/root/my_personal_ai/logs/daily_report.log'
logging.basicConfig(filename=LOG, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

def get_env():
    from dotenv import load_dotenv
    load_dotenv('/root/my_personal_ai/.env')
    return {
        'bot_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
        'chat_id': os.getenv('TELEGRAM_CHAT_ID', ''),
    }

def send_telegram(token, chat_id, text):
    """Send Telegram message."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return None

def get_trading_status():
    """Get current trading status."""
    try:
        with urllib.request.urlopen("http://localhost:8090/api/status", timeout=3) as r:
            d = json.loads(r.read())
        mode = "📄 Paper" if d.get('paper_mode') else "⚡ LIVE"
        bal = d.get('trading', d).get('balance_usdt', d.get('balance_usdt', 0))
        pnl = d.get('daily_pnl', 0)
        trades = d.get('paper_trades_today', 0) if d.get('paper_mode') else d.get('trades_today', 0)
        return f"{mode} | Баланс: ${bal:.2f} | P&L: ${pnl:+.2f} | Сделок: {trades}"
    except Exception:
        return "❌ Торговый бот недоступен"

def get_knowledge_stats():
    """Get knowledge base stats."""
    try:
        db = '/root/my_personal_ai/data/memory.db'
        conn = sqlite3.connect(db)
        count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        today = conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE ts > ?",
            (time.time() - 86400,)
        ).fetchone()[0]
        conn.close()
        return f"{count} записей (+{today} сегодня)"
    except Exception:
        return "н/д"

def get_system_health():
    """Check system health."""
    try:
        with urllib.request.urlopen("http://localhost:8090/api/status", timeout=3) as r:
            d = json.loads(r.read())
        agents = d.get('agents_count', 0)
        return f"✅ OK | {agents} агентов активны"
    except Exception:
        return "❌ Dashboard недоступен"

def get_freelance_stats():
    """Get latest freelance leads count."""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        count = 0
        with open('/root/my_personal_ai/data/freelance_leads.jsonl') as f:
            for line in f:
                j = json.loads(line)
                if today in j.get('date', ''):
                    count += 1
        return f"{count} новых вакансий сегодня"
    except Exception:
        return "н/д"

def get_sales_stats():
    """Get sales pipeline stats."""
    try:
        with urllib.request.urlopen("http://localhost:8090/api/status", timeout=3) as r:
            d = json.loads(r.read())
        stats = d.get('stats', {})
        total = stats.get('total_leads', 0)
        return f"{total} лидов в воронке"
    except Exception:
        return "н/д"

def main():
    env = get_env()
    if not env['bot_token'] or not env['chat_id']:
        log.warning("Telegram not configured")
        print("Telegram not configured")
        return

    now = datetime.now()
    date_str = now.strftime('%d.%m.%Y')
    
    trading = get_trading_status()
    health = get_system_health()
    kb = get_knowledge_stats()
    freelance = get_freelance_stats()
    sales = get_sales_stats()

    msg = (
        f"<b>🤖 MaxAI Daily Report | {date_str}</b>\n\n"
        f"<b>🏥 Система:</b> {health}\n"
        f"<b>💹 Торговля:</b> {trading}\n"
        f"<b>📚 База знаний:</b> {kb}\n"
        f"<b>💼 Фриланс:</b> {freelance}\n"
        f"<b>💰 Продажи:</b> {sales}\n\n"
        f"<i>🔗 Дашборд: http://77.90.2.171:8080</i>"
    )

    result = send_telegram(env['bot_token'], env['chat_id'], msg)
    if result and result.get('ok'):
        log.info("Daily report sent successfully")
        print("✅ Daily report sent to Telegram")
    else:
        log.error("Failed to send: %s", result)
        print("❌ Failed to send report")

if __name__ == '__main__':
    main()
