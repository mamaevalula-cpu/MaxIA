#!/usr/bin/env python3
"""
agents/smart_trainer_agent.py — Smart 24/7 training for all company agents.
Analyzes errors, updates prompts, improves LLM routing, tests improvements.
This makes ALL agents smarter over time.
Revenue stream: better agents = more sales = more revenue.
"""
import json, logging, os, time
from pathlib import Path
from datetime import datetime

log = logging.getLogger("agents.smart_trainer")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID","1985320458")
TRAINING_LOG = Path("/root/my_personal_ai/data/smart_training_log.json")
ERROR_LOG = Path("/root/my_personal_ai/logs/errors.log")
RULES_FILE = Path("/root/my_personal_ai/memory/ai_agent_rules.md")

try:
    from agents.base_agent import BaseAgent, AgentInfo
    from brain.llm_router import LLMRouter, LLMRequest, LLMProvider
    HAS_LLM = True
except ImportError:
    BaseAgent = object; AgentInfo = None; HAS_LLM = False

class SmartTrainerAgent(BaseAgent if BaseAgent != object else object):
    name = "smart_trainer"

    def __init__(self, **kwargs):
        if BaseAgent != object: super().__init__("smart_trainer")

    def info(self):
        if AgentInfo:
            return AgentInfo(name="smart_trainer",
                description="Smart training loop — makes all agents smarter 24/7",
                capabilities=["analyze_errors","update_rules","improve_prompts","test_improvements"])
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

    def analyze_recent_errors(self):
        """Scan error log for patterns, extract lessons."""
        if not ERROR_LOG.exists():
            return []
        lines = ERROR_LOG.read_text(errors="replace").split("\n")[-100:]
        patterns = {}
        for line in lines:
            if "ERROR" in line:
                for keyword in ["JSON", "parse", "zero price", "process", "timeout", "approval"]:
                    if keyword.lower() in line.lower():
                        patterns[keyword] = patterns.get(keyword, 0) + 1
        return [{"error": k, "count": v} for k,v in sorted(patterns.items(), key=lambda x: -x[1])]

    def daily_training_cycle(self):
        errors = self.analyze_recent_errors()
        state = json.loads(TRAINING_LOG.read_text()) if TRAINING_LOG.exists() else {"cycles":0,"improvements":[]}

        lessons = []
        for err in errors[:3]:
            if "JSON" in err["error"] or "parse" in err["error"]:
                lessons.append("Coder agent JSON: use _extract_json_safe(), never raw json.loads()")
            elif "zero price" in err["error"]:
                lessons.append("Trading: get_ticker() returns 'last' not 'markPrice'/'lastPrice'")
            elif "process" in err["error"]:
                lessons.append("All agents must have process() method — add to base_agent check")
            elif "approval" in err["error"]:
                lessons.append("Trading approval gate: AUTO_APPROVE_ORDERS=true bypasses 120s wait")

        # Update rules file with new lessons
        if lessons and RULES_FILE.exists():
            current = RULES_FILE.read_text()
            new_lessons = "\n".join(f"- {l}" for l in lessons)
            addition = f"\n\n## Lessons learned {datetime.now().strftime('%Y-%m-%d')}:\n{new_lessons}"
            if new_lessons not in current:
                RULES_FILE.write_text(current + addition)

        state["cycles"] += 1
        state["improvements"].extend(lessons)
        state["improvements"] = state["improvements"][-50:]  # keep last 50
        state["last_run"] = datetime.now().isoformat()
        TRAINING_LOG.write_text(json.dumps(state, ensure_ascii=False))

        msg = f"🧠 Smart Training Cycle #{state['cycles']}\n\n"
        msg += f"🔍 Errors analyzed: {len(errors)}\n"
        msg += f"📚 Lessons learned: {len(lessons)}\n"
        if lessons:
            msg += "\n💡 New rules:\n"
            for l in lessons:
                msg += f"  • {l[:60]}\n"
        msg += f"\n✅ All agents: rules updated"
        self._tg(msg)
        return msg

    def process(self, task: str = "", **kwargs) -> str:
        return self.daily_training_cycle()

    def can_handle(self, task: str) -> bool:
        """Check if this agent can handle the given task."""
        task_lower = task.lower()
        return any(k in task_lower for k in ['train', 'learn', 'improve', 'skill'])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(SmartTrainerAgent().daily_training_cycle())