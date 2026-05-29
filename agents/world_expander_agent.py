#!/usr/bin/env python3
"""
agents/world_expander_agent.py — WorldExpander: Global Market Expansion
Drives MaxAI expansion to new countries and markets.
Tracks expansion KPIs, generates localized content, monitors competitors.
Path: RU → KZ,BY → EN global → APAC → EU → 1000 clients worldwide.
"""
import json, logging, os, time
from pathlib import Path
from datetime import datetime

log = logging.getLogger("agents.world_expander")
BASE = Path("/root/my_personal_ai")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "1985320458")
EXPANSION_FILE = BASE / "data" / "world_expansion.json"

try:
    from agents.base_agent import BaseAgent, AgentInfo
    HAS_BASE = True
except ImportError:
    BaseAgent = object
    AgentInfo = None
    HAS_BASE = False


EXPANSION_ROADMAP = {
    "phase_1": {"name": "CIS (active)", "markets": ["RU", "KZ", "BY", "UA"], "target_usd": 5000},
    "phase_2": {"name": "English global", "markets": ["US", "UK", "AU", "CA"], "timeline": "Q2 2026", "target_usd": 20000},
    "phase_3": {"name": "APAC", "markets": ["IN", "SG", "MY", "PH"], "timeline": "Q3 2026", "target_usd": 50000},
    "phase_4": {"name": "EU + MENA", "markets": ["DE", "FR", "AE", "SA"], "timeline": "Q4 2026", "target_usd": 100000},
}

DAILY_GROWTH_ACTIONS = {
    0: "Submit 5 Upwork proposals for AI bot development (EN market)",
    1: "Research KZ market: top 20 businesses needing Telegram bots in Almaty",
    2: "Publish EN case study: 'How we built a trading bot in 48h'",
    3: "Find 5 dev agencies for white-label MaxAI partnership",
    4: "Analyze top 10 Fiverr AI Automation sellers — find gaps to exploit",
    5: "Post LinkedIn article: 'AI agents that work 24/7 for your business'",
    6: "Weekly review: measure expansion KPIs, adjust strategy",
}

PATH_TO_1000_CLIENTS = {
    "RU_market": {"target": 300, "avg_check_rub": 2000, "monthly_rev": 600000},
    "EN_market": {"target": 500, "avg_check_usd": 50, "monthly_rev": 25000},
    "KZ_market": {"target": 100, "avg_check_kzt": 50000, "monthly_rev": 5000000},
    "APAC_market": {"target": 100, "avg_check_usd": 30, "monthly_rev": 3000},
}


class WorldExpanderAgent(BaseAgent if HAS_BASE else object):
    name = "world_expander"

    def __init__(self, **kwargs):
        if HAS_BASE:
            super().__init__("world_expander")

    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in [
            "расшир", "expand", "global", "international", "рынок", "market",
            "страна", "country", "1000 client"
        ])

    def info(self):
        if AgentInfo:
            return AgentInfo(
                name="world_expander",
                description="Global market expansion — grows MaxAI across countries to 1000+ clients",
                capabilities=["market_analysis", "expansion_planning", "competitor_tracking", "localization"]
            )
        return None

    def _tg(self, text):
        try:
            import urllib.request as ur
            data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode()
            req = ur.Request(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data=data, headers={"Content-Type": "application/json"}
            )
            ur.urlopen(req, timeout=8)
        except Exception:
            pass

    def expansion_report(self):
        state = {}
        if EXPANSION_FILE.exists():
            try:
                state = json.loads(EXPANSION_FILE.read_text())
            except Exception:
                pass

        today_action = DAILY_GROWTH_ACTIONS.get(datetime.now().weekday(), "Review all expansion metrics")
        state["actions_taken"] = state.get("actions_taken", 0) + 1
        state["last_report"] = datetime.now().isoformat()
        EXPANSION_FILE.write_text(json.dumps(state, ensure_ascii=False))

        msg = "🌍 World Expansion Report\n\n"
        msg += f"📍 Phase 1 (Active): {', '.join(EXPANSION_ROADMAP['phase_1']['markets'])}\n"
        msg += f"  Revenue target: ${EXPANSION_ROADMAP['phase_1']['target_usd']:,}\n\n"

        msg += f"📍 Phase 2 ({EXPANSION_ROADMAP['phase_2']['timeline']}): {', '.join(EXPANSION_ROADMAP['phase_2']['markets'])}\n"
        msg += f"  Revenue target: ${EXPANSION_ROADMAP['phase_2']['target_usd']:,}\n\n"

        msg += f"📅 Today's Action:\n{today_action}\n\n"

        msg += "🎯 Path to 1000 Clients:\n"
        for market, data in PATH_TO_1000_CLIENTS.items():
            msg += f"  • {market}: {data['target']} clients\n"

        total_clients = sum(d["target"] for d in PATH_TO_1000_CLIENTS.values())
        msg += f"\n📊 Total target: {total_clients} clients\n"
        msg += f"⚡ Actions taken this week: {state.get('actions_taken', 0)}"

        self._tg(msg)
        return msg

    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        return self.expansion_report()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(WorldExpanderAgent().expansion_report())
