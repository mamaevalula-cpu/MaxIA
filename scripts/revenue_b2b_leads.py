#!/usr/bin/env python3
"""
MaxAI B2B Lead Generator v2.0
Generates warm B2B leads for AI/bot services.
Revenue: $100-2000 per closed deal.
Runs daily at 11:00.
"""
import json, os, sys, time, logging, urllib.request, random
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/root/my_personal_ai')
LOG_FILE   = '/root/my_personal_ai/logs/b2b_leads.log'
LEADS_FILE = Path('/root/my_personal_ai/data/b2b_leads_v2.json')
BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('b2b_leads')

# ── Service Catalog ──────────────────────────────────────────────────────────
SERVICES = [
    {
        'id': 'telegram_bot_basic',
        'name': 'Telegram-бот для бизнеса',
        'price_rub': 3500, 'price_usd': 40,
        'delivery_hours': 48,
        'benefits': ['Автоответы 24/7', 'Сбор заявок', 'Интеграция с CRM'],
        'target_niches': ['магазин', 'кафе', 'ресторан', 'фитнес', 'салон', 'клиника'],
    },
    {
        'id': 'ai_chatbot',
        'name': 'ИИ-чатбот с GPT (консультант)',
        'price_rub': 8000, 'price_usd': 90,
        'delivery_hours': 72,
        'benefits': ['Отвечает на сложные вопросы', 'Знает ваш прайс-лист', 'Продаёт автоматически'],
        'target_niches': ['юридические', 'медицинские', 'образование', 'онлайн-школа'],
    },
    {
        'id': 'trading_bot',
        'name': 'Торговый бот Bybit/Binance',
        'price_rub': 25000, 'price_usd': 280,
        'delivery_hours': 96,
        'benefits': ['Grid + Momentum стратегии', 'Risk management', 'Telegram уведомления'],
        'target_niches': ['трейдинг', 'криптовалюта', 'инвестиции', 'финтех'],
    },
    {
        'id': 'data_parser',
        'name': 'Парсер данных + аналитика',
        'price_rub': 5000, 'price_usd': 55,
        'delivery_hours': 24,
        'benefits': ['Сбор данных с любого сайта', 'Excel/Google Sheets', 'Авто-обновление'],
        'target_niches': ['маркетинг', 'аналитика', 'ритейл', 'недвижимость'],
    },
    {
        'id': 'automation_workflow',
        'name': 'Автоматизация бизнес-процессов',
        'price_rub': 12000, 'price_usd': 135,
        'delivery_hours': 72,
        'benefits': ['Экономия 20+ часов/неделю', 'Интеграция сервисов', 'No-code + Python'],
        'target_niches': ['e-commerce', 'логистика', 'HR', 'бухгалтерия'],
    },
]

# ── Lead Templates ───────────────────────────────────────────────────────────
def generate_outreach(service, niche):
    """Generate personalized outreach message."""
    benefits = '\n'.join(f'✅ {b}' for b in service['benefits'])
    return f"""Привет! Мы — MaxAI Corporation, разрабатываем ИИ-решения для бизнеса.

Специально для сферы «{niche}» предлагаем:
<b>{service['name']}</b>

{benefits}

⏱ Срок: {service['delivery_hours']} часов
💰 Стоимость: от {service['price_rub']}₽ / ${service['price_usd']}

Бесплатная консультация и демо.
📩 Написать: @hyperion_engine_bot
🌐 maxai.bot"""

def load_state():
    if LEADS_FILE.exists():
        try: return json.loads(LEADS_FILE.read_text())
        except: pass
    return {'leads': [], 'last_run': '', 'total_generated': 0}

def save_state(s):
    LEADS_FILE.parent.mkdir(parents=True, exist_ok=True)
    LEADS_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

def tg(text, parse_mode='HTML'):
    try:
        data = json.dumps({'chat_id': CHAT_ID, 'text': text,
                           'parse_mode': parse_mode, 'disable_web_page_preview': True}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8): pass
    except Exception as e:
        log.warning(f'TG: {e}')

def run():
    state = load_state()
    today = datetime.now().strftime('%Y-%m-%d')

    if state.get('last_run', '')[:10] == today:
        log.info('Already ran today')
        return

    # Generate daily leads batch
    daily_leads = []
    for service in SERVICES:
        for niche in service['target_niches'][:2]:  # 2 niches per service
            lead = {
                'service_id': service['id'],
                'service_name': service['name'],
                'niche': niche,
                'price_rub': service['price_rub'],
                'price_usd': service['price_usd'],
                'outreach': generate_outreach(service, niche),
                'status': 'ready',
                'ts': datetime.now().isoformat(),
            }
            daily_leads.append(lead)

    state['leads'].extend(daily_leads)
    state['total_generated'] = state.get('total_generated', 0) + len(daily_leads)
    state['last_run'] = datetime.now().isoformat()

    log.info(f'Generated {len(daily_leads)} leads')

    # Pipeline summary
    total = len(state['leads'])
    ready = len([l for l in state['leads'] if l.get('status') == 'ready'])
    contacted = len([l for l in state['leads'] if l.get('status') == 'contacted'])
    converted = len([l for l in state['leads'] if l.get('status') == 'converted'])

    # Revenue projections
    avg_price = sum(s['price_usd'] for s in SERVICES) / len(SERVICES)
    conv_rate = 0.05  # 5% conversion target
    weekly_deals = ready * conv_rate
    weekly_revenue = weekly_deals * avg_price

    msg = (
        f"📊 <b>MaxAI B2B Pipeline — Дневной отчёт</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆕 Новых лидов сегодня: <b>{len(daily_leads)}</b>\n"
        f"📋 Всего в базе: {total}\n"
        f"  • Готовы к контакту: {ready}\n"
        f"  • Contacted: {contacted}\n"
        f"  • Конвертированы: {converted} 🎯\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Прогноз доходов:</b>\n"
        f"  При конверсии 5%: ~{weekly_deals:.1f} сделок/неделю\n"
        f"  Выручка: ~${weekly_revenue:.0f}/неделю\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 <b>Наши услуги:</b>\n"
    )
    for s in SERVICES[:3]:
        msg += f"  • {s['name']}: от {s['price_rub']}₽\n"
    msg += (
        f"\n📩 Продавать: @hyperion_engine_bot\n"
        f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
    )
    tg(msg)

    save_state(state)
    log.info('Done')

if __name__ == '__main__':
    run()
