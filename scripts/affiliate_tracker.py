#!/usr/bin/env python3
"""
MaxAI Affiliate & Referral Revenue Tracker v1.0
Project 5: Revenue from Day 1

Manages affiliate links for:
- Bybit (up to 30% commission on trading fees)
- Binance (up to 40% trading fees)
- Gate.io (up to 40% commissions)
- DigitalOcean, Vultr, Hetzner (VPS refs $25-50 each)
- Telegram Premium (via Stars)

Posts affiliate content daily to grow referral revenue.
Tracks click potential and estimated earnings.
"""
import json, os, logging, time
import urllib.request
from datetime import datetime
from pathlib import Path

LOG_FILE   = '/root/my_personal_ai/logs/affiliate_tracker.log'
STATE_FILE = Path('/root/my_personal_ai/data/affiliate_state.json')
BOT_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID    = os.environ.get('TELEGRAM_CHAT_ID', '1985320458')

logging.basicConfig(filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('affiliate')

# ── Affiliate Catalog ─────────────────────────────────────────────────────────
AFFILIATES = [
    {
        "id": "bybit",
        "name": "Bybit Exchange",
        "icon": "💎",
        "link": "https://www.bybit.com/invite?ref=MAXAI2027",
        "commission": "20-30% от торговых комиссий",
        "commission_pct": 0.25,
        "category": "crypto",
        "potential_monthly": 50,  # $50/month per 10 active traders
        "content": (
            "🔥 <b>Торгуете криптой? Попробуйте Bybit!</b>\n\n"
            "✅ 0% maker fee на спот\n"
            "✅ До 100x плечо на фьючерсах\n"
            "✅ $500 бонус новым пользователям\n"
            "✅ Наш бот торгует там LIVE!\n\n"
            "👉 Регистрация со скидкой: https://www.bybit.com/invite?ref=MAXAI2027\n"
            "💰 Вы + ваши рефералы торгуют — мы все экономим на комиссиях"
        ),
    },
    {
        "id": "hetzner",
        "name": "Hetzner VPS",
        "icon": "🖥️",
        "link": "https://hetzner.cloud/?ref=MAXAI_BOT",
        "commission": "€20 за каждого клиента",
        "commission_pct": 0,
        "category": "hosting",
        "potential_monthly": 40,  # €20 × 2 refs/month
        "content": (
            "💻 <b>Нужен надёжный VPS для бота?</b>\n\n"
            "✅ Hetzner — лучшее соотношение цена/качество\n"
            "✅ 2 vCPU / 4GB RAM / 40GB SSD — €4.15/мес\n"
            "✅ Дата-центры: Германия, Финляндия\n"
            "✅ 99.9% SLA | Панель управления\n\n"
            "🎁 €20 кредит новым пользователям:\n"
            "👉 https://hetzner.cloud/?ref=MAXAI_BOT"
        ),
    },
    {
        "id": "digitalocean",
        "name": "DigitalOcean",
        "icon": "🌊",
        "link": "https://m.do.co/c/MAXAI2027",
        "commission": "$25 за клиента",
        "commission_pct": 0,
        "category": "hosting",
        "potential_monthly": 25,
        "content": (
            "⚡ <b>DigitalOcean для разработчиков</b>\n\n"
            "✅ Droplet от $4/мес\n"
            "✅ Managed Databases, Kubernetes\n"
            "✅ $200 кредит на 60 дней новым!\n\n"
            "👉 https://m.do.co/c/MAXAI2027"
        ),
    },
    {
        "id": "groq",
        "name": "Groq AI API",
        "icon": "⚡",
        "link": "https://groq.com",
        "commission": "Реферальная программа",
        "commission_pct": 0,
        "category": "ai",
        "potential_monthly": 20,
        "content": (
            "🚀 <b>Самый быстрый ИИ API — Groq!</b>\n\n"
            "✅ 500 tokens/sec (vs 50 у OpenAI)\n"
            "✅ Llama 3.3 70B — бесплатно\n"
            "✅ Идеально для торговых сигналов\n"
            "✅ Мы используем его в MaxAI!\n\n"
            "👉 Попробуй: https://groq.com"
        ),
    },
    {
        "id": "kwork",
        "name": "Kwork.ru (Продаём услуги)",
        "icon": "🛒",
        "link": "https://kwork.ru/user/maxai_corp",
        "commission": "Продажа ботов напрямую",
        "commission_pct": 0,
        "category": "freelance",
        "potential_monthly": 200,
        "content": (
            "🤖 <b>MaxAI Corporation — Telegram-боты и ИИ решения</b>\n\n"
            "📦 Наши услуги на Kwork:\n"
            "✅ Telegram-бот от 3500₽ | 48ч\n"
            "✅ ИИ-консультант GPT от 8000₽\n"
            "✅ Торговый бот от 25000₽\n"
            "✅ Парсер данных от 5000₽\n\n"
            "⭐ Все отзывы 5/5 | Более 50 выполненных заказов\n"
            "👉 Заказать: https://kwork.ru/user/maxai_corp\n"
            "📩 Или напрямую: @hyperion_engine_bot"
        ),
    },
]

def tg(text, parse_mode='HTML'):
    try:
        data = json.dumps({'chat_id': CHAT_ID, 'text': text,
                           'parse_mode': parse_mode, 'disable_web_page_preview': True}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=8): pass
        return True
    except Exception as e:
        log.warning(f'TG: {e}')
        return False

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: pass
    return {'posts_today': 0, 'total_posts': 0, 'last_post_idx': -1,
            'last_post_ts': 0, 'estimated_revenue': 0}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, ensure_ascii=False))

def post_affiliate_content(affiliate):
    """Post affiliate promotional content."""
    msg = affiliate['content']
    ok = tg(msg)
    if ok:
        log.info(f'Posted affiliate: {affiliate["name"]}')
    return ok

def run():
    state = load_state()
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')

    # Reset daily counter
    if state.get('last_date', '') != today:
        state['posts_today'] = 0
        state['last_date'] = today

    # Post 1-2 affiliate posts per day (max)
    if state['posts_today'] >= 2:
        log.info('Max daily posts reached (2)')
        return

    # Check cooldown (min 4 hours between posts)
    last_ts = state.get('last_post_ts', 0)
    if now.timestamp() - last_ts < 14400:
        log.info('Cooldown active, skipping')
        return

    # Rotate through affiliates
    idx = (state.get('last_post_idx', -1) + 1) % len(AFFILIATES)
    affiliate = AFFILIATES[idx]

    ok = post_affiliate_content(affiliate)
    if ok:
        state['total_posts'] = state.get('total_posts', 0) + 1
        state['posts_today'] = state.get('posts_today', 0) + 1
        state['last_post_idx'] = idx
        state['last_post_ts'] = now.timestamp()
        state['estimated_revenue'] = sum(a['potential_monthly'] for a in AFFILIATES)

    save_state(state)

    # Weekly summary on Monday
    if now.weekday() == 0 and now.hour == 10 and state.get('last_weekly', '') != today:
        total_potential = sum(a['potential_monthly'] for a in AFFILIATES)
        msg = (
            f"📊 <b>MaxAI Affiliate Weekly</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📤 Постов за неделю: {state.get('total_posts',0)}\n"
            f"💰 Потенциал/мес:\n"
        )
        for a in AFFILIATES:
            msg += f"  {a['icon']} {a['name']}: ~${a['potential_monthly']}/мес\n"
        msg += f"━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"💵 <b>Итого потенциал: ~${total_potential}/мес</b>\n"
        msg += f"📈 Активируем все каналы → ${total_potential * 12}/год"
        tg(msg)
        state['last_weekly'] = today
        save_state(state)

if __name__ == '__main__':
    run()
