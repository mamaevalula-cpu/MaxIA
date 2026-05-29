#!/usr/bin/env python3
"""
agents/autodev_agent.py — AutoDev: Autonomous Developer
Continuously improves Корпорация MaxAI. Picks next task from backlog,
checks codebase health, reports progress. Works with claude_dev_agent
for actual code implementation.
"""
import json, logging, os, time, subprocess
from pathlib import Path
from datetime import datetime

log = logging.getLogger("agents.autodev")
BASE = Path("/root/my_personal_ai")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "1985320458")
DEV_LOG   = BASE / "data" / "autodev_improvements.json"

try:
    from agents.base_agent import BaseAgent, AgentInfo
    HAS_BASE = True
except ImportError:
    BaseAgent = object
    AgentInfo = None
    HAS_BASE = False


IMPROVEMENT_BACKLOG = [
    {"id": "fix_01", "priority": 1, "title": "Add Redis caching to LLM router",
     "desc": "Cache frequent LLM responses — reduce API costs 40%"},
    {"id": "fix_02", "priority": 1, "title": "Add Hyperion v12 websocket live dashboard",
     "desc": "Real-time task updates without page refresh via WebSocket"},
    {"id": "fix_03", "priority": 1, "title": "Auto-register new agents in main.py",
     "desc": "Scan agents/ folder on startup, auto-import any new agent file"},
    {"id": "fix_04", "priority": 2, "title": "Add crypto payment USDT gateway",
     "desc": "Accept USDT payments directly — instant settlement, no banks"},
    {"id": "fix_05", "priority": 2, "title": "Add dynamic pricing engine to Hyperion",
     "desc": "Adjust capability prices based on demand, competition, time"},
    {"id": "fix_06", "priority": 2, "title": "Build client portal web UI",
     "desc": "Clients can check order status, download deliverables themselves"},
    {"id": "fix_07", "priority": 3, "title": "Add multi-worker parallel task execution",
     "desc": "Run 4+ tasks simultaneously instead of sequential"},
    {"id": "fix_08", "priority": 3, "title": "Add Hyperion v12 capability auto-tester",
     "desc": "Automatically test each capability monthly, report quality score"},
    {"id": "fix_09", "priority": 1, "title": "Add anti-hallucination guardrails",
     "desc": "Validate LLM outputs before sending to clients — no hallucinated code"},
    {"id": "fix_10", "priority": 2, "title": "Build agent performance leaderboard",
     "desc": "Track which agents generate most revenue, rank them daily"},
]


class AutoDevAgent(BaseAgent if HAS_BASE else object):
    name = "autodev"

    def __init__(self, **kwargs):
        if HAS_BASE:
            super().__init__("autodev")

    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in ["разработ", "develop", "feature", "улучш", "improve", "autodev"])

    def info(self):
        if AgentInfo:
            return AgentInfo(
                name="autodev",
                description="Autonomous developer — adds features and improvements to Корпорация MaxAI",
                capabilities=["feature_planning", "codebase_health", "backlog_management", "dev_reporting"]
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

    def get_codebase_health(self):
        health = {}
        checks = [
            ("personal_ai_api", "curl -s http://localhost:8000/health"),
            ("hyperion_v12", "curl -s http://localhost:8006/health"),
            ("bybit_bot", "curl -s http://localhost:8001/status"),
            ("database", "psql postgresql://postgres:hyperion_v12_pass@127.0.0.1/hyperion_v12 -t -c 'SELECT 1'"),
        ]
        for name, cmd in checks:
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=8)
                health[name] = "ok" if r.returncode == 0 else "fail"
            except Exception:
                health[name] = "timeout"
        return health

    def get_done_ids(self):
        if DEV_LOG.exists():
            try:
                history = json.loads(DEV_LOG.read_text())
                return {h.get("id") for h in history if h.get("status") == "done"}
            except Exception:
                pass
        return set()

    def daily_dev_cycle(self):
        health = self.get_codebase_health()
        done_ids = self.get_done_ids()
        history = json.loads(DEV_LOG.read_text()) if DEV_LOG.exists() else []

        # Find next task
        next_task = None
        for item in sorted(IMPROVEMENT_BACKLOG, key=lambda x: x["priority"]):
            if item["id"] not in done_ids:
                next_task = item
                break

        done_count = len(done_ids)
        health_ok = sum(1 for v in health.values() if v == "ok")
        health_total = len(health)

        msg = "🔨 AutoDev Report\n\n"
        msg += f"🏥 Codebase: {health_ok}/{health_total} components healthy\n"
        for comp, status in health.items():
            e = "✅" if status == "ok" else "❌"
            msg += f"  {e} {comp}: {status}\n"

        msg += f"\n📈 Progress: {done_count}/{len(IMPROVEMENT_BACKLOG)} improvements done\n\n"

        if next_task:
            msg += f"🎯 Next [{next_task['priority']}★]: {next_task['title']}\n"
            msg += f"  {next_task['desc']}\n\n"
            msg += "💡 Will be implemented via claude_dev_agent in next cycle"
            # Log as planned
            history.append({
                "id": next_task["id"],
                "title": next_task["title"],
                "status": "planned",
                "ts": time.time()
            })
        else:
            msg += "✅ All backlog items completed! Growth mode: adding new features."

        DEV_LOG.write_text(json.dumps(history[-100:], ensure_ascii=False))
        self._tg(msg)
        return msg

    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        return self.daily_dev_cycle()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(AutoDevAgent().daily_dev_cycle())
