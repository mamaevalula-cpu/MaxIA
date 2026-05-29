"""
MaxAI Daily Telegram Marketing Post
Generates a fresh professional ad image and posts to Telegram channel.
Runs daily at 10:00 UTC via project_runner.
"""
import sys, os, json, urllib.request, urllib.parse, random
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '/root/my_personal_ai/projects/hyperion_engine_v11_monorepo')

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
CHAT_ID   = os.environ.get('TELEGRAM_CHAT_ID',   '1985320458')

# Rotate through ad templates daily
DAILY_TEMPLATES = [
    ('telegram_bot_ad',   'Telegram Bot Builder'),
    ('trading_bot_ad',    'Trading Bot'),
    ('hero_banner',       'MaxAI Marketplace'),
    ('agent_marketplace', 'AI Agent Ecosystem'),
    ('social_post',       'MaxAI Brand'),
    ('python_script_ad',  'Python Automation'),
    ('revenue_dashboard', 'Revenue Growth'),
    ('agent_avatar',      'AI Agent'),
    ('team_ai_agents',    'MaxAI Team'),
]

AD_CAPTIONS = {
    'telegram_bot_ad': (
        "🤖 Нужен Telegram бот?\n\n"
        "✅ Разработка за 24 часа\n"
        "✅ Любая сложность: интернет-магазин, запись, оплата, CRM\n"
        "✅ Поддержка 24/7\n\n"
        "💰 От 1000₽\n"
        "📩 Заказать: @hyperion_engine_bot\n"
        "🌐 maxai.space"
    ),
    'trading_bot_ad': (
        "📈 Торговый бот для Bybit/Binance\n\n"
        "✅ Автоматическая торговля 24/7\n"
        "✅ Grid, Momentum, Mean Reversion стратегии\n"
        "✅ Риск-менеджмент и стоп-лоссы\n\n"
        "💰 От 1500₽\n"
        "📩 Заказать: @hyperion_engine_bot\n"
        "🌐 maxai.space"
    ),
    'hero_banner': (
        "🌐 MaxAI — Маркетплейс ИИ-агентов\n\n"
        "🚀 29+ специализированных AI агентов\n"
        "⚡ Выполнение задач за 24 часа\n"
        "💎 Разработка, трейдинг, автоматизация\n\n"
        "💰 Минимальный заказ от 800₽\n"
        "📩 @hyperion_engine_bot\n"
        "🌐 maxai.space"
    ),
    'agent_marketplace': (
        "🏪 AI Agent Marketplace — MaxAI\n\n"
        "Армия из 10,000 ИИ-агентов работает для вас:\n"
        "• Разработчики Telegram ботов\n"
        "• Трейдеры и торговые боты\n"
        "• Парсеры и скрипты Python\n"
        "• API интеграции\n\n"
        "📩 Заказать: @hyperion_engine_bot"
    ),
    'social_post': (
        "⚡ MaxAI — будущее уже здесь\n\n"
        "Первый в мире маркетплейс ИИ-агентов.\n"
        "Автоматизируй бизнес, зарабатывай больше.\n\n"
        "🤖 Telegram боты\n"
        "📈 Trading боты\n"
        "🐍 Python скрипты\n\n"
        "📩 @hyperion_engine_bot | 🌐 maxai.space"
    ),
    'python_script_ad': (
        "🐍 Python скрипт или парсер?\n\n"
        "✅ Парсинг сайтов и данных\n"
        "✅ Автоматизация бизнес-процессов\n"
        "✅ API интеграции и боты\n"
        "✅ Любая сложность\n\n"
        "💰 От 800₽ / Срок: 24 часа\n"
        "📩 @hyperion_engine_bot"
    ),
    'revenue_dashboard': (
        "💹 Автоматизируй доход с MaxAI\n\n"
        "Наши агенты уже зарабатывают для клиентов:\n"
        "📊 Trading боты — пассивный доход\n"
        "🤖 Telegram боты — автопродажи\n"
        "⚙️ Python автоматизация — экономия времени\n\n"
        "🎯 Цель: $1000/день\n"
        "📩 @hyperion_engine_bot"
    ),
    'agent_avatar': (
        "🤖 Познакомьтесь с нашими ИИ-агентами\n\n"
        "Каждый агент — специалист в своей области:\n"
        "👨‍💻 Bot-Smith — Telegram разработчик\n"
        "📈 Trader-Bot — Автоматический трейдер\n"
        "🐍 Parser — Парсер данных\n\n"
        "Доступны 24/7 | Доставка за 24ч\n"
        "📩 @hyperion_engine_bot"
    ),
    'team_ai_agents': (
        "👥 Команда MaxAI — 29 специалистов\n\n"
        "🔵 Разработчики | 🟡 Трейдеры | 🟣 Маркетологи\n"
        "🟢 Поддержка | ⚪ Аналитики\n\n"
        "Профессиональная команда ИИ-агентов\n"
        "готова выполнить любой заказ за 24 часа.\n\n"
        "💰 От 800₽ | 📩 @hyperion_engine_bot"
    ),
}


def send_photo_tg(image_path: str, caption: str) -> bool:
    url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendPhoto'
    with open(image_path, 'rb') as fh:
        img = fh.read()
    b = 'MaxAIPost1'
    crlf = b'\r\n'
    body = b''
    body += b'--' + b.encode() + crlf
    body += b'Content-Disposition: form-data; name="chat_id"' + crlf + crlf
    body += CHAT_ID.encode() + crlf
    body += b'--' + b.encode() + crlf
    body += b'Content-Disposition: form-data; name="caption"' + crlf + crlf
    body += caption.encode('utf-8') + crlf
    body += b'--' + b.encode() + crlf
    fname = os.path.basename(image_path).encode()
    body += b'Content-Disposition: form-data; name="photo"; filename="' + fname + b'"' + crlf
    body += b'Content-Type: image/png' + crlf + crlf
    body += img
    body += crlf + b'--' + b.encode() + b'--' + crlf
    req = urllib.request.Request(
        url, data=body,
        headers={'Content-Type': 'multipart/form-data; boundary=' + b}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read()).get('ok', False)
    except Exception as e:
        print(f'Telegram error: {e}')
        return False


def send_text_tg(text: str) -> bool:
    url = 'https://api.telegram.org/bot' + BOT_TOKEN + '/sendMessage'
    data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text}).encode('utf-8')
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
            return json.loads(r.read()).get('ok', False)
    except Exception as e:
        print(f'Telegram msg error: {e}')
        return False


def run_daily_post():
    from maxai.image_system import MaxAIImageSystem

    # Pick today's template (rotate by day of year)
    day_idx = datetime.now().timetuple().tm_yday % len(DAILY_TEMPLATES)
    tmpl_name, tmpl_label = DAILY_TEMPLATES[day_idx]

    print(f'Daily post: {tmpl_name} ({tmpl_label})')

    # Generate fresh image
    img_sys = MaxAIImageSystem()
    path = img_sys.generate(tmpl_name)

    if not path or not path.exists():
        # Fallback: use cached image if exists
        images_dir = Path('/root/my_personal_ai/projects/hyperion_engine_v11_monorepo/maxai/data/images')
        cached = list(images_dir.glob(f'maxai_{tmpl_name}_*.png'))
        if cached:
            path = sorted(cached)[-1]  # latest
            print(f'Using cached: {path.name}')
        else:
            print('No image available, sending text post only')
            caption = AD_CAPTIONS.get(tmpl_name, '')
            if caption:
                send_text_tg(caption)
            return False

    caption = AD_CAPTIONS.get(tmpl_name, f'MaxAI - {tmpl_label}\n\n@hyperion_engine_bot')
    ok = send_photo_tg(str(path), caption)
    print(f'Post sent: {"OK" if ok else "FAILED"}')

    # Log to file
    log_entry = {
        'date': datetime.now().isoformat(),
        'template': tmpl_name,
        'image': str(path),
        'sent': ok
    }
    log_path = Path('/root/my_personal_ai/data/maxai_posts.json')
    posts = []
    if log_path.exists():
        try:
            with open(log_path) as f:
                posts = json.load(f)
        except Exception:
            posts = []
    posts.append(log_entry)
    posts = posts[-90:]  # keep last 90 days
    with open(log_path, 'w') as f:
        json.dump(posts, f, indent=2)

    return ok


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    success = run_daily_post()
    sys.exit(0 if success else 1)
