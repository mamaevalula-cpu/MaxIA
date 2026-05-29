#!/usr/bin/env python3
"""
agents/channel_monetization_agent.py — Telegram channel growth and monetization.
Posts daily value content + weekly promo. Tracks subscribers/revenue.
Revenue stream: direct Telegram channel subscriptions + ad placement fees.
"""
import json, logging, os, time, random
from pathlib import Path
from datetime import datetime

log = logging.getLogger("agents.channel")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID","1985320458")
CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", CHAT_ID)
DATA_FILE = Path("/root/my_personal_ai/data/channel_monetization.json")

try:
    from agents.base_agent import BaseAgent, AgentInfo
except ImportError:
    BaseAgent = object
    AgentInfo = None

DAILY_POSTS = [
    "🤖 MaxAI Tip #{n}\n\n{tip}\n\n📩 Заказать бота: @hyperion_engine_bot\n💰 Цены от 1000₽",
]

TIPS = [
    "Telegram-бот увеличивает конверсию клиентов на 30-40%. Автоответы 24/7 — больше продаж.",
    "Торговый бот на Bybit зарабатывает даже пока вы спите. Grid-стратегия: +0.5% в день.",
    "Парсер данных — экономит 20+ часов в неделю на ручном сборе информации.",
    "ИИ-чатбот на базе GPT снижает нагрузку на поддержку на 70%.",
    "FastAPI + PostgreSQL — профессиональный backend за 72 часа. Деплой на VPS включён.",
    "SEO-контент от ИИ: 5 статей в день, каждая оптимизирована под ваши ключевые слова.",
    "Автоматизация email-рассылки: +22% open rate с персонализацией через ИИ.",
]

class ChannelMonetizationAgent(BaseAgent if BaseAgent != object else object):
    name = "channel_monetization"

    def __init__(self, **kwargs):
        if BaseAgent != object:
            super().__init__("channel_monetization")

    def info(self):
        if AgentInfo:
            return AgentInfo(name="channel_monetization",
                description="Manages Telegram channel content and monetization",
                capabilities=["post_content","track_subscribers","ad_placement"])
        return None

    def _tg(self, text, chat_id=None):
        try:
            import urllib.request, json as j
            cid = chat_id or CHANNEL_ID
            data = j.dumps({"chat_id": cid, "text": text, "parse_mode": "HTML"}).encode()
            from urllib.request import Request
            req = Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            log.error("TG error: %s", e)

    def post_daily(self):
        state = json.loads(DATA_FILE.read_text()) if DATA_FILE.exists() else {"post_count":0,"revenue":0}
        n = state.get("post_count", 0) + 1
        tip = TIPS[n % len(TIPS)]
        text = DAILY_POSTS[0].format(n=n, tip=tip)
        self._tg(text)
        state["post_count"] = n
        state["last_post"] = datetime.now().isoformat()
        DATA_FILE.write_text(json.dumps(state, ensure_ascii=False))
        return f"Posted daily content #{n}"

    def post_promo(self):
        promo = (
            "🚀 <b>MaxAI — ИИ-агенты для вашего бизнеса</b>\n\n"
            "✅ Telegram боты от <b>1000₽</b> (24 часа)\n"
            "✅ Торговые боты от <b>1500₽</b>\n"
            "✅ Парсеры и скраперы от <b>800₽</b>\n"
            "✅ ИИ-ассистенты от <b>2500₽</b>\n"
            "✅ FastAPI backend от <b>2000₽</b>\n\n"
            "🎁 <b>Аренда агентов</b>: от 3000₽/месяц\n\n"
            "📩 Написать: @hyperion_engine_bot"
        )
        self._tg(promo)
        return "Promo posted"

    def process(self, task: str = "", **kwargs) -> str:
        if "promo" in task.lower():
            return self.post_promo()
        return self.post_daily()


    def can_handle(self, task: str) -> bool:
        task_lower = task.lower()
        return any(k in task_lower for k in ['channel', 'monetize', 'telegram', 'youtube', 'subscriber'])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    a = ChannelMonetizationAgent()
    print(a.process())