#!/usr/bin/env python3
"""
agents/saas_subscription_agent.py — Manages AI SaaS subscriptions.
Tracks clients, sends renewal reminders, reports MRR.
Revenue stream: recurring monthly revenue from rented agent slots.
"""
import json, logging, os, time
from pathlib import Path
from datetime import datetime, timedelta

log = logging.getLogger("agents.saas")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID","1985320458")
DATA_FILE = Path("/root/my_personal_ai/data/saas_subscriptions.json")

try:
    from agents.base_agent import BaseAgent, AgentInfo
except ImportError:
    BaseAgent = object; AgentInfo = None

DEFAULT_DATA = {
    "subscriptions": [],
    "mrr_rub": 0,
    "total_clients": 0,
    "revenue_total": 0
}

class SaasSubscriptionAgent(BaseAgent if BaseAgent != object else object):
    name = "saas_subscription"

    def __init__(self, **kwargs):
        if BaseAgent != object: super().__init__("saas_subscription")
        if not DATA_FILE.exists():
            DATA_FILE.write_text(json.dumps(DEFAULT_DATA, ensure_ascii=False))

    def info(self):
        if AgentInfo:
            return AgentInfo(name="saas_subscription",
                description="Manages AI SaaS subscriptions and MRR tracking",
                capabilities=["track_subscriptions","send_renewals","report_mrr","add_client"])
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

    def daily_report(self):
        data = json.loads(DATA_FILE.read_text())
        subs = data.get("subscriptions", [])
        active = [s for s in subs if s.get("status") == "active"]
        mrr = sum(s.get("price_rub", 0) for s in active)
        expiring = [s for s in active if
                    datetime.fromisoformat(s.get("expires","2030-01-01")) <= datetime.now() + timedelta(days=3)]

        msg = f"📊 MaxAI SaaS Dashboard\n\n"
        msg += f"👥 Активных подписок: {len(active)}\n"
        msg += f"💰 MRR: {mrr:,}₽/месяц\n"
        msg += f"📈 Прогноз годовой: {mrr*12:,}₽\n"
        if expiring:
            msg += f"\n⚠️ Истекают через 3 дня: {len(expiring)}\n"
            for s in expiring:
                msg += f"  • {s.get('name','?')}: {s.get('price_rub',0)}₽\n"
        if not active:
            msg += "\n🎯 Цель: первые 5 клиентов = 15,000₽/мес\n"
            msg += "📣 Каналы: kwork.ru, Telegram, direct outreach"

        data["mrr_rub"] = mrr
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False))
        self._tg(msg)
        return msg

    def add_client(self, name, plan, price_rub, months=1):
        data = json.loads(DATA_FILE.read_text())
        sub = {
            "id": f"sub_{int(time.time())}",
            "name": name, "plan": plan, "price_rub": price_rub,
            "status": "active",
            "created": datetime.now().isoformat(),
            "expires": (datetime.now() + timedelta(days=30*months)).isoformat()
        }
        data["subscriptions"].append(sub)
        data["total_clients"] += 1
        data["revenue_total"] += price_rub * months
        DATA_FILE.write_text(json.dumps(data, ensure_ascii=False))
        self._tg(f"✅ Новый клиент: {name}\n💰 {price_rub}₽/мес | {plan}")
        return sub

    def process(self, task: str = "", **kwargs) -> str:
        return self.daily_report()

    def can_handle(self, task: str) -> bool:
        """Check if this agent can handle the given task."""
        task_lower = task.lower()
        return any(k in task_lower for k in ['saas', 'subscription', 'license', 'api key'])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    a = SaasSubscriptionAgent()
    print(a.daily_report())