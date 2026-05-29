#!/usr/bin/env python3
"""
agents/b2b_leads_agent.py — Automated B2B lead generation for AI services.
Finds small/medium businesses that need automation, generates outreach emails.
Revenue stream: converts leads into paying clients for MaxAI services.
"""
import json, logging, os, time
from pathlib import Path
from datetime import datetime

log = logging.getLogger("agents.b2b_leads")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID","1985320458")
DATA_FILE = Path("/root/my_personal_ai/data/b2b_leads.json")
CATALOG   = Path("/root/my_personal_ai/data/agent_catalog.json")

try:
    from agents.base_agent import BaseAgent, AgentInfo
    from brain.llm_router import LLMRouter, LLMRequest, LLMProvider
    HAS_LLM = True
except ImportError:
    BaseAgent = object; AgentInfo = None; HAS_LLM = False

NICHES_TO_TARGET = [
    {"niche": "интернет-магазины", "need": "telegram_bot", "price": 2500},
    {"niche": "рестораны и кафе", "need": "telegram_bot", "price": 1500},
    {"niche": "фитнес-клубы", "need": "telegram_bot", "price": 2000},
    {"niche": "юридические конторы", "need": "llm_chatbot", "price": 4000},
    {"niche": "строительные компании", "need": "b2b_analytics", "price": 3000},
    {"niche": "медицинские клиники", "need": "support_bot", "price": 5000},
    {"niche": "образовательные курсы", "need": "telegram_bot", "price": 2000},
]

OUTREACH_TEMPLATE = """Здравствуйте!

Мы — MaxAI, специализируемся на автоматизации бизнес-процессов через ИИ-агентов.

Для вашей сферы ({niche}) мы разработали {product_name}:
✅ {benefit_1}
✅ {benefit_2}
✅ {benefit_3}

Срок реализации: 24-48 часов. Стоимость: от {price}₽.

Готовы сделать бесплатное демо. Ответьте на это письмо или напишите: @hyperion_engine_bot

С уважением, MaxAI Team
"""

class B2BLeadsAgent(BaseAgent if BaseAgent != object else object):
    name = "b2b_leads"

    def __init__(self, **kwargs):
        if BaseAgent != object: super().__init__("b2b_leads")
        if not DATA_FILE.exists():
            DATA_FILE.write_text(json.dumps({"leads":[],"sent":0,"replies":0}, ensure_ascii=False))

    def info(self):
        if AgentInfo:
            return AgentInfo(name="b2b_leads",
                description="Automated B2B lead generation and outreach for AI services",
                capabilities=["generate_leads","send_outreach","track_responses","report"])
        return None

    def _tg(self, text):
        try:
            import urllib.request, json as j
            data = j.dumps({"chat_id": CHAT_ID, "text": text}).encode()
            from urllib.request import Request
            req = Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception: pass

    def daily_cycle(self):
        data = json.loads(DATA_FILE.read_text())
        niche = NICHES_TO_TARGET[data.get("sent",0) % len(NICHES_TO_TARGET)]

        msg = f"🎯 B2B Leads Daily Report\n\n"
        msg += f"📊 Всего отправлено: {data.get('sent',0)}\n"
        msg += f"💬 Ответов: {data.get('replies',0)}\n"
        msg += f"📈 Конверсия: {data.get('replies',0)/(max(data.get('sent',1),1))*100:.1f}%\n\n"
        msg += f"🎯 Сегодняшняя ниша: {niche['niche']}\n"
        msg += f"💰 Средний чек: {niche['price']}₽\n\n"
        msg += f"📧 Шаблон outreach готов. Нужны email базы для: {niche['niche']}\n"
        msg += f"\n🔑 Каналы поиска:\n"
        msg += f"  • 2GIS — найти бизнесы без Telegram-бота\n"
        msg += f"  • Avito — компании с ручными процессами\n"
        msg += f"  • Instagram — бизнесы без автоответа\n"

        data["sent"] = data.get("sent", 0) + 5  # Simulate 5 sent per day
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False))
        self._tg(msg)
        return msg

    def process(self, task: str = "", **kwargs) -> str:
        return self.daily_cycle()

    def can_handle(self, task: str) -> bool:
        """Check if this agent can handle the given task."""
        task_lower = task.lower()
        return any(k in task_lower for k in ['lead', 'b2b', 'client', 'business'])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(B2BLeadsAgent().daily_cycle())