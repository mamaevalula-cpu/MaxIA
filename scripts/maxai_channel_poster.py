#!/usr/bin/env python3
"""
MaxAI Corporation — Professional Channel Poster v2.0
Уровень маркетинга: Enterprise 2026
Все ссылки проверены. Нет битых URL. Нет IP-адресов клиентам.
"""
import json, os, time, urllib.request, random
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv("/root/my_personal_ai/.env")

CORP_TOKEN  = os.getenv("CORP_BOT_TOKEN", "")
CHANNEL     = "@maxai_chanal"
STATE_FILE  = Path("/root/my_personal_ai/data/channel_posts.json")

# ── Verified URLs (never IP, always domain) ──────────────────────────
DOMAIN   = "https://maxai.fyi"
PORTAL   = "https://maxai.fyi"
HIRE     = "https://maxai.fyi/hire"
TG_BOT   = "@MaxAI_SaaS_Bot"
TG_CORP  = "@Corporation_MaxAI_bot"
CHANNEL_LINK = "https://t.me/maxai_chanal"
FIVERR   = "https://www.fiverr.com/maxai_co"

# ── Professional Images (from public CDN — reliable) ─────────────────
IMAGES = {
    "nexus":   "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1200&q=80",
    "trading": "https://images.unsplash.com/photo-1642790106117-e829e14a795f?w=1200&q=80",
    "code":    "https://images.unsplash.com/photo-1555066931-4365d14bab8c?w=1200&q=80",
    "ai":      "https://images.unsplash.com/photo-1677442135703-1787eea5ce01?w=1200&q=80",
    "money":   "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1200&q=80",
    "robot":   "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?w=1200&q=80",
}

def tg_send_text(text: str) -> bool:
    """Send text message to channel."""
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{CORP_TOKEN}/sendMessage",
        data=json.dumps({"chat_id": CHANNEL, "text": text,
                         "parse_mode": "HTML",
                         "disable_web_page_preview": False}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
            return d.get("ok", False)
    except: return False

def tg_send_photo(photo_url: str, caption: str) -> bool:
    """Send photo with caption to channel."""
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{CORP_TOKEN}/sendPhoto",
        data=json.dumps({"chat_id": CHANNEL, "photo": photo_url,
                         "caption": caption, "parse_mode": "HTML"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read())
            if d.get("ok"):
                return True
            # Photo URL failed — fallback to text
            return tg_send_text(caption)
    except:
        return tg_send_text(caption)

def get_prices() -> dict:
    """Get live crypto prices."""
    try:
        url = 'https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCUSDT%22%2C%22ETHUSDT%22%2C%22SOLUSDT%22%5D'
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read())
        return {d['symbol'].replace('USDT',''): {
            'price': float(d['lastPrice']),
            'change': float(d['priceChangePercent'])
        } for d in data}
    except: return {}

def fmt_price(p: dict) -> str:
    ch = p.get('change', 0)
    arrow = "▲" if ch >= 0 else "▼"
    sign  = "+" if ch >= 0 else ""
    return f"${p.get('price',0):,.0f} {arrow}{sign}{ch:.1f}%"

def load_state() -> dict:
    try: return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except: return {}

def save_state(s: dict): STATE_FILE.write_text(json.dumps(s, indent=2))

# ════════════════════════════════════════════════════════════════════
# PROFESSIONAL 2026-LEVEL POST TEMPLATES
# ════════════════════════════════════════════════════════════════════

def post_nexus_platform() -> bool:
    """MaxAI NEXUS — flagship platform post."""
    caption = (
        "🌐 <b>MaxAI NEXUS — Платформа автономных AI-агентов</b>\n\n"
        "Пока ваши конкуренты нанимают людей — вы используете AI-агентов, "
        "которые работают <b>24/7 без перерывов и ошибок.</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>10 специализированных агентов:</b>\n"
        "  💻 CodeMaster — Python/FastAPI/React\n"
        "  📊 TradeBot Pro — Bybit/Binance сигналы\n"
        "  🎯 LeadHunter — автопоиск клиентов\n"
        "  🔬 BrainSearch — research за 30 сек\n"
        "  📣 ViralBot — контент и SMM\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📦 <b>Тарифы:</b>\n"
        "  Starter — <b>от $19/мес</b> · 1 агент\n"
        "  Pro — <b>$49/мес</b> · 5 агентов\n"
        "  Business — <b>$99/мес</b> · 15 агентов\n\n"
        "🔑 Оплата крипто · Активация мгновенная\n\n"
        f"👉 Зарегистрироваться: {PORTAL}\n"
        f"💬 Вопросы: {TG_BOT}"
    )
    return tg_send_photo(IMAGES["nexus"], caption)

def post_trading_bot() -> bool:
    """Trading bot results post."""
    prices = get_prices()
    btc = prices.get("BTC", {})
    eth = prices.get("ETH", {})
    sol = prices.get("SOL", {})
    now = datetime.now().strftime("%d.%m %H:%M")

    caption = (
        f"📊 <b>Рынок сейчас — {now} МСК</b>\n\n"
        + (f"  ₿ BTC: {fmt_price(btc)}\n" if btc else "")
        + (f"  Ξ ETH: {fmt_price(eth)}\n" if eth else "")
        + (f"  ◎ SOL: {fmt_price(sol)}\n" if sol else "")
        + "\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 <b>MaxAI TradeBot Pro работает 24/7</b>\n\n"
        "Пока вы спите — бот анализирует рынок:\n"
        "  ✅ Мульти-ТФ анализ (1h + 15m)\n"
        "  ✅ ADX + RSI + Supertrend фильтры\n"
        "  ✅ Автоматические SL/TP\n"
        "  ✅ Trailing stop (прибыль не отдаём)\n"
        "  ✅ Circuit breaker защита\n\n"
        "Leverage 2x · Risk 0.8%/сделку · Max 2 позиции\n\n"
        f"🚀 Запустить торгового агента: {TG_BOT}\n"
        f"📋 Подробнее: {PORTAL}"
    )
    return tg_send_photo(IMAGES["trading"], caption)

def post_services() -> bool:
    """Services & pricing post."""
    caption = (
        "🛠 <b>MaxAI Corporation — Разработка под ключ</b>\n\n"
        "Мы не просто пишем код — мы строим системы, "
        "которые <b>зарабатывают деньги</b> без вашего участия.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Что делаем за 1-7 дней:</b>\n\n"
        "🤖 Telegram-бот с AI (GPT-4/Claude)\n"
        "   ↳ от <b>2 000 ₽</b> · Срок: 1 день\n\n"
        "📊 Торговый бот Bybit/Binance\n"
        "   ↳ от <b>10 000 ₽</b> · Срок: 3-5 дней\n\n"
        "🕷 Парсер/автоматизация бизнеса\n"
        "   ↳ от <b>1 500 ₽</b> · Срок: 1 день\n\n"
        "🔌 FastAPI бэкенд + интеграции API\n"
        "   ↳ от <b>5 000 ₽</b> · Срок: 2-3 дня\n\n"
        "🧠 AI-агент для бизнеса 24/7\n"
        "   ↳ от <b>19$/мес</b> · Подписка\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💳 Оплата USDT · ₽ · Предоплата 50%\n"
        "⚡ Гарантия результата\n\n"
        f"📩 Обсудить проект: {TG_BOT}\n"
        f"💼 Fiverr: {FIVERR}\n"
        f"🌐 Все услуги: {HIRE}"
    )
    return tg_send_photo(IMAGES["code"], caption)

def post_ai_agents() -> bool:
    """AI agent revolution post."""
    caption = (
        "🚀 <b>2026: Компании без сотрудников — это реальность</b>\n\n"
        "Amazon, Meta, Klarna сокращают тысячи человек, "
        "заменяя их AI-агентами. Это не будущее — это происходит сейчас.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "MaxAI Corporation предоставляет автономных агентов для:\n\n"
        "📋 <b>Лидогенерации</b>\n"
        "   Находим клиентов на Kwork/Upwork 24/7\n\n"
        "💬 <b>Клиентской поддержки</b>\n"
        "   Отвечаем на вопросы без задержек\n\n"
        "📈 <b>Торговых операций</b>\n"
        "   Торгуем на бирже пока вы занимаетесь бизнесом\n\n"
        "🔄 <b>Бизнес-автоматизации</b>\n"
        "   Парсинг, отчёты, интеграции — автоматически\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Стоимость одного агента:</b> от $19/мес\n"
        "<b>ROI:</b> первые результаты за 24 часа\n\n"
        f"🎯 Попробуйте бесплатно: {TG_BOT}\n"
        f"📊 Платформа агентов: {PORTAL}"
    )
    return tg_send_photo(IMAGES["ai"], caption)

def post_revenue() -> bool:
    """Revenue & results post."""
    caption = (
        "💰 <b>Как MaxAI Corporation зарабатывает деньги для клиентов</b>\n\n"
        "Реальные цифры — не маркетинговые обещания:\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📬 <b>Kwork/Upwork агент</b>\n"
        "   46+ откликов на проекты отправлено\n"
        "   Работает каждые 15 минут\n\n"
        "📊 <b>Торговый агент Bybit</b>\n"
        "   Leverage 2x · Risk 0.8%/сделку\n"
        "   Supertrend + ADX + RSI стратегия\n\n"
        "🤗 <b>HuggingFace Space</b>\n"
        "   Demo → Конвертация в клиентов\n"
        "   Доступен 24/7: maxocrporate.hf.space\n\n"
        "🌐 <b>NEXUS Platform</b>\n"
        "   Клиентский портал с 10 агентами\n"
        "   Тарифы: $19/$49/$99/$299\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Ваши агенты работают — вы получаете результат.\n\n"
        f"▶️ Начать: {TG_BOT}\n"
        f"📋 Тарифы: {HIRE}"
    )
    return tg_send_photo(IMAGES["money"], caption)

def post_market_update() -> bool:
    """Market update with crypto prices."""
    prices = get_prices()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    btc = prices.get("BTC",{})
    eth = prices.get("ETH",{})
    sol = prices.get("SOL",{})

    def trend_icon(ch):
        if ch > 2: return "🟢🔥"
        if ch > 0: return "🟢"
        if ch > -2: return "🔴"
        return "🔴💥"

    caption = (
        f"📡 <b>Крипто-обзор MaxAI — {now}</b>\n\n"
        "<b>Топ активы прямо сейчас:</b>\n\n"
    )
    if btc: caption += f"  {trend_icon(btc.get('change',0))} <b>Bitcoin:</b> {fmt_price(btc)}\n"
    if eth: caption += f"  {trend_icon(eth.get('change',0))} <b>Ethereum:</b> {fmt_price(eth)}\n"
    if sol: caption += f"  {trend_icon(sol.get('change',0))} <b>Solana:</b> {fmt_price(sol)}\n"

    caption += (
        "\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🤖 <b>MaxAI TradeBot</b> анализирует рынок 24/7\n\n"
        "Ключевые фильтры перед входом:\n"
        "  · Supertrend + EMA50/200 (1h)\n"
        "  · ADX > 25 (только в тренде)\n"
        "  · Volume > 0.9x avg (ликвидность)\n"
        "  · 2h cooldown после каждой сделки\n\n"
        "Защита капитала важнее прибыли.\n\n"
        f"📈 Торговый агент: {TG_BOT}\n"
        f"🌐 Платформа: {PORTAL}"
    )
    return tg_send_photo(IMAGES["trading"], caption)

# ── Post rotation ────────────────────────────────────────────────────
POSTS = [
    ("nexus",   post_nexus_platform,  "NEXUS Platform"),
    ("services", post_services,       "Services & Prices"),
    ("trading",  post_trading_bot,    "Trading Bot"),
    ("ai_rev",   post_ai_agents,      "AI Revolution"),
    ("market",   post_market_update,  "Market Update"),
    ("revenue",  post_revenue,        "Revenue System"),
]

def main():
    state = load_state()
    last_topic = state.get("last_topic", "revenue")
    last_ts    = state.get("last_ts", 0)

    # Find next topic
    topics = [p[0] for p in POSTS]
    try:    idx = topics.index(last_topic)
    except: idx = -1
    next_idx   = (idx + 1) % len(POSTS)
    topic_id, post_fn, topic_name = POSTS[next_idx]

    print(f"Posting: {topic_name}")
    ok = post_fn()

    if ok:
        state["last_topic"] = topic_id
        state["last_ts"]    = time.time()
        save_state(state)
        print(f"✅ Posted: {topic_name}")
    else:
        print(f"❌ Failed: {topic_name}")

if __name__ == "__main__":
    main()
