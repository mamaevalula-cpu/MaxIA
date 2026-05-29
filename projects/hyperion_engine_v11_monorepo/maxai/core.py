"""
MaxAI Core — Agent Pool + HR Director + Revenue Tracker
Goal: 10,000+ agents, $1000/day within 30 days
Brand: MaxAI — The World's Largest AI Agent Marketplace
"""
from __future__ import annotations
import json, logging, time, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("maxai.core")

BASE_DIR = Path("/root/my_personal_ai/projects/hyperion_engine_v11_monorepo/maxai")
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class AgentSpec:
    agent_id:    str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name:        str = ""
    tier:        str = "WORKER"       # BOARD | C_SUITE | MANAGER | WORKER
    skills:      List[str] = field(default_factory=list)
    status:      str = "idle"         # idle | busy | training | retired
    tasks_done:  int = 0
    revenue_rub: float = 0.0
    quality_avg: float = 1.0          # 0..1 quality score
    created_at:  float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    manager_id:  Optional[str] = None
    description: str = ""


class AgentPool:
    """Manages 10,000+ agents. Hire, assign, monitor, retire."""

    FOUNDING_TEAM = [
        # C-Suite (5)
        {"name": "ceo_maxwell",    "tier": "C_SUITE", "skills": ["strategy", "vision", "fundraising", "decisions"]},
        {"name": "cto_helix",      "tier": "C_SUITE", "skills": ["architecture", "security", "scaling", "devops"]},
        {"name": "cmo_aurora",     "tier": "C_SUITE", "skills": ["marketing", "seo", "social_media", "ads", "brand"]},
        {"name": "cfo_nexus",      "tier": "C_SUITE", "skills": ["finance", "pricing", "revenue", "billing"]},
        {"name": "hr_titan",       "tier": "C_SUITE", "skills": ["hiring", "training", "performance", "culture"]},
        # Managers (6)
        {"name": "dev_lead_volt",  "tier": "MANAGER", "skills": ["python", "code_review", "telegram_bots", "api"]},
        {"name": "qa_guardian",    "tier": "MANAGER", "skills": ["testing", "quality_control", "review", "validation"]},
        {"name": "sales_hawk",     "tier": "MANAGER", "skills": ["sales", "outreach", "negotiation", "crm"]},
        {"name": "support_nova",   "tier": "MANAGER", "skills": ["support", "communication", "client_care"]},
        {"name": "growth_spark",   "tier": "MANAGER", "skills": ["growth", "viral", "referral", "partnerships"]},
        {"name": "ops_titan",      "tier": "MANAGER", "skills": ["operations", "monitoring", "reporting", "sla"]},
        # Worker Agents (Development)
        {"name": "bot_smith_01",   "tier": "WORKER", "skills": ["telegram_bot", "python", "aiogram", "keyboards"]},
        {"name": "bot_smith_02",   "tier": "WORKER", "skills": ["telegram_bot", "python", "pyrogram", "payments"]},
        {"name": "bot_smith_03",   "tier": "WORKER", "skills": ["telegram_bot", "python", "admin", "moderation"]},
        {"name": "trader_bot_01",  "tier": "WORKER", "skills": ["trading_bot", "bybit", "python", "grid", "dca"]},
        {"name": "trader_bot_02",  "tier": "WORKER", "skills": ["trading_bot", "binance", "python", "momentum"]},
        {"name": "parser_01",      "tier": "WORKER", "skills": ["scraping", "selenium", "requests", "bs4"]},
        {"name": "parser_02",      "tier": "WORKER", "skills": ["scraping", "playwright", "api_scraping"]},
        {"name": "api_builder_01", "tier": "WORKER", "skills": ["fastapi", "rest_api", "docker", "postgresql"]},
        {"name": "api_builder_02", "tier": "WORKER", "skills": ["flask", "django", "rest_api", "auth"]},
        {"name": "chatbot_01",     "tier": "WORKER", "skills": ["chatgpt_integration", "openai", "rag", "bot"]},
        {"name": "chatbot_02",     "tier": "WORKER", "skills": ["llm_integration", "langchain", "embeddings"]},
        # Worker Agents (Marketing & Growth)
        {"name": "content_01",     "tier": "WORKER", "skills": ["copywriting", "seo", "content", "blog"]},
        {"name": "seo_01",         "tier": "WORKER", "skills": ["seo", "keyword_research", "backlinks", "audit"]},
        {"name": "social_01",      "tier": "WORKER", "skills": ["instagram", "telegram", "vk", "smm", "posts"]},
        {"name": "ads_01",         "tier": "WORKER", "skills": ["yandex_direct", "vk_ads", "targeting", "creatives"]},
        # Worker Agents (Sales & Outreach)
        {"name": "outreach_01",    "tier": "WORKER", "skills": ["email_outreach", "cold_email", "b2b_sales"]},
        {"name": "freelance_01",   "tier": "WORKER", "skills": ["kwork", "fiverr", "upwork", "proposals"]},
        {"name": "freelance_02",   "tier": "WORKER", "skills": ["kwork", "fl_ru", "habr_freelance", "bids"]},
    ]

    def __init__(self, db_path: Path = DATA_DIR / "agent_pool.json"):
        self.db_path = db_path
        self._agents: Dict[str, AgentSpec] = {}
        self._load()

    def _load(self):
        if self.db_path.exists():
            try:
                data = json.loads(self.db_path.read_text())
                for d in data:
                    valid = {k: v for k, v in d.items() if k in AgentSpec.__dataclass_fields__}
                    a = AgentSpec(**valid)
                    self._agents[a.agent_id] = a
                return
            except Exception as e:
                log.warning("Pool load failed: %s", e)
        self._seed_founding_team()

    def _save(self):
        data = [vars(a).copy() for a in self._agents.values()]
        self.db_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def _seed_founding_team(self):
        for d in self.FOUNDING_TEAM:
            a = AgentSpec(**d)
            self._agents[a.agent_id] = a
        self._save()
        log.info("MaxAI: seeded %d founding agents", len(self.FOUNDING_TEAM))

    # ── Public API ────────────────────────────────────────────────────

    def hire(self, name: str, skills: List[str], tier: str = "WORKER", description: str = "") -> AgentSpec:
        a = AgentSpec(name=name, tier=tier, skills=skills, description=description)
        self._agents[a.agent_id] = a
        self._save()
        log.info("MaxAI hired: %s (%s)", name, skills)
        return a

    def hire_batch(self, specs: List[Dict]) -> List[AgentSpec]:
        hired = []
        for s in specs:
            a = AgentSpec(**s)
            self._agents[a.agent_id] = a
            hired.append(a)
        self._save()
        return hired

    def find_available(self, skills_req: List[str]) -> Optional[AgentSpec]:
        candidates = [
            a for a in self._agents.values()
            if a.status == "idle" and any(s in a.skills for s in skills_req)
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda a: a.quality_avg * (1 + a.tasks_done * 0.01))

    def assign_task(self, agent_id: str) -> bool:
        if agent_id in self._agents and self._agents[agent_id].status == "idle":
            self._agents[agent_id].status = "busy"
            self._agents[agent_id].last_active = time.time()
            self._save()
            return True
        return False

    def complete_task(self, agent_id: str, revenue_rub: float = 0.0, quality: float = 1.0):
        if agent_id in self._agents:
            a = self._agents[agent_id]
            a.status = "idle"
            a.tasks_done += 1
            a.revenue_rub = round(a.revenue_rub + revenue_rub, 2)
            a.last_active = time.time()
            # Update quality avg (exponential moving average)
            a.quality_avg = round(a.quality_avg * 0.9 + quality * 0.1, 3)
            self._save()

    def fire(self, agent_id: str):
        if agent_id in self._agents:
            self._agents[agent_id].status = "retired"
            self._save()

    def stats(self) -> Dict:
        agents = list(self._agents.values())
        active = [a for a in agents if a.status != "retired"]
        return {
            "total_agents":      len(active),
            "idle":              sum(1 for a in active if a.status == "idle"),
            "busy":              sum(1 for a in active if a.status == "busy"),
            "revenue_total_rub": round(sum(a.revenue_rub for a in active), 2),
            "tasks_completed":   sum(a.tasks_done for a in active),
            "avg_quality":       round(sum(a.quality_avg for a in active) / max(len(active), 1), 3),
            "by_tier": {
                "C_SUITE": sum(1 for a in active if a.tier == "C_SUITE"),
                "MANAGER": sum(1 for a in active if a.tier == "MANAGER"),
                "WORKER":  sum(1 for a in active if a.tier == "WORKER"),
            },
        }

    def top_earners(self, n: int = 10) -> List[Dict]:
        active = [a for a in self._agents.values() if a.status != "retired"]
        ranked = sorted(active, key=lambda a: a.revenue_rub, reverse=True)
        return [
            {"rank": i+1, "name": a.name, "revenue_rub": a.revenue_rub,
             "tasks": a.tasks_done, "quality": a.quality_avg}
            for i, a in enumerate(ranked[:n])
        ]

    def list_by_skill(self, skill: str) -> List[AgentSpec]:
        return [a for a in self._agents.values() if skill in a.skills and a.status != "retired"]

    def scale_to(self, target: int, skill_rotation: List[str]) -> int:
        """Auto-hire to reach target agent count."""
        current = len([a for a in self._agents.values() if a.status != "retired"])
        hired = 0
        for i in range(max(0, target - current)):
            skill = skill_rotation[i % len(skill_rotation)]
            name  = f"{skill[:12].replace('_','')}_w{current+i+1:05d}"
            self.hire(name, [skill, "python"])
            hired += 1
        return hired


class HRDirector:
    """C-Suite HR Agent. Hires, trains, evaluates, fires. Scales to 10k agents."""

    TARGET_AGENT_COUNT = 10000
    MIN_QUALITY_THRESHOLD = 0.3
    MIN_TASKS_TO_EVALUATE = 5

    PRIORITY_SKILLS = [
        "telegram_bot",     # Most popular on Kwork/Fiverr, fast delivery
        "python_script",    # High volume, steady demand
        "trading_bot",      # High value per task ($15-50)
        "web_scraping",     # Steady demand, repeat clients
        "api_integration",  # Medium-high value
        "chatbot",          # Growing demand
        "content_writing",  # Volume play
        "seo_optimization", # Recurring monthly clients
        "web_automation",   # High value
        "data_analysis",    # Enterprise clients
        "fastapi_service",  # API development
        "discord_bot",      # Good demand
    ]

    def __init__(self, pool: AgentPool):
        self.pool = pool

    def hiring_plan(self) -> Dict:
        stats = self.pool.stats()
        target_daily_usd = 1000.0
        avg_task_rub = 1200.0
        tasks_per_day = (target_daily_usd * 90) / avg_task_rub
        agents_for_target = int(tasks_per_day / 2)  # 2 tasks/agent/day

        phases = {
            "week_1":  {"agents": 50,   "focus": "Kwork gig publication + first orders"},
            "week_2":  {"agents": 200,  "focus": "Active bidding on all platforms"},
            "week_3":  {"agents": 500,  "focus": "SaaS API launch + enterprise outreach"},
            "month_2": {"agents": 2000, "focus": "Scale winning channels 10x"},
            "month_3": {"agents": 5000, "focus": "Global expansion (Fiverr, Upwork)"},
            "month_6": {"agents": 10000,"focus": "Fully autonomous 10k agent marketplace"},
        }

        return {
            "current_agents":    stats["total_agents"],
            "target_agents":     self.TARGET_AGENT_COUNT,
            "gap":               max(0, self.TARGET_AGENT_COUNT - stats["total_agents"]),
            "agents_for_1k_usd": agents_for_target,
            "tasks_per_day_needed": round(tasks_per_day),
            "avg_task_value_rub": avg_task_rub,
            "target_daily_usd":  target_daily_usd,
            "priority_skills":   self.PRIORITY_SKILLS[:6],
            "phases":            phases,
            "timeline": "30 days to $1000/day, 6 months to 10k agents",
        }

    def daily_hr_cycle(self) -> Dict:
        """Run every morning: evaluate, fire bad agents, hire needed workers."""
        fired = 0
        hired = []
        stats = self.pool.stats()

        # Fire underperformers
        for a in list(self.pool._agents.values()):
            if a.tasks_done >= self.MIN_TASKS_TO_EVALUATE and a.quality_avg < self.MIN_QUALITY_THRESHOLD:
                self.pool.fire(a.agent_id)
                fired += 1

        # Hire to fill gaps
        current = stats["total_agents"]
        next_target = min(self.TARGET_AGENT_COUNT, current + 50)  # grow 50/day
        n_hired = self.pool.scale_to(next_target, self.PRIORITY_SKILLS)

        return {"fired": fired, "hired": n_hired, "total": len(self.pool._agents)}


class RevenueTracker:
    """Tracks all money across all channels. Reports vs $1000/day target."""

    def __init__(self, db_path: Path = DATA_DIR / "revenue.json"):
        self.db_path = db_path
        self._load()

    def _load(self):
        if self.db_path.exists():
            self.data = json.loads(self.db_path.read_text())
        else:
            self.data = {
                "brand": "MaxAI",
                "started_at": time.strftime("%Y-%m-%d"),
                "target_daily_usd": 1000.0,
                "total_rub": 0.0,
                "total_usd": 0.0,
                "by_channel": {
                    "kwork": 0.0, "fiverr": 0.0, "upwork": 0.0,
                    "direct": 0.0, "api_saas": 0.0, "telegram": 0.0,
                },
                "daily": {},
                "transactions": [],
            }
            self._save()

    def _save(self):
        self.db_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))

    def record(self, amount_rub: float, channel: str, task_id: str = "", agent: str = ""):
        usd = round(amount_rub / 90.0, 2)
        today = time.strftime("%Y-%m-%d")
        self.data["total_rub"] = round(self.data["total_rub"] + amount_rub, 2)
        self.data["total_usd"] = round(self.data["total_usd"] + usd, 2)
        ch = self.data["by_channel"]
        ch[channel] = round(ch.get(channel, 0.0) + amount_rub, 2)
        if today not in self.data["daily"]:
            self.data["daily"][today] = {"rub": 0.0, "usd": 0.0, "count": 0}
        d = self.data["daily"][today]
        d["rub"] = round(d["rub"] + amount_rub, 2)
        d["usd"] = round(d["usd"] + usd, 2)
        d["count"] += 1
        self.data["transactions"].append({
            "ts": time.time(), "date": today,
            "rub": amount_rub, "usd": usd,
            "channel": channel, "task_id": task_id, "agent": agent,
        })
        self._save()
        log.info("Revenue +%.0f RUB ($%.2f) via %s | total $%.2f", amount_rub, usd, channel, self.data["total_usd"])

    def today_stats(self) -> Dict:
        today = time.strftime("%Y-%m-%d")
        day = self.data["daily"].get(today, {"rub": 0.0, "usd": 0.0, "count": 0})
        target = self.data["target_daily_usd"]
        pct = round(day["usd"] / target * 100, 1) if target else 0.0
        return {
            "date":          today,
            "today_rub":     day["rub"],
            "today_usd":     day["usd"],
            "transactions":  day["count"],
            "target_usd":    target,
            "progress_pct":  pct,
            "total_rub":     self.data["total_rub"],
            "total_usd":     self.data["total_usd"],
            "by_channel":    self.data["by_channel"],
        }

    def daily_report(self) -> str:
        t = self.today_stats()
        lines = [
            "MaxAI Revenue Report",
            "Date: " + t["date"],
            "Today: " + str(t["today_rub"]) + " RUB / $" + str(t["today_usd"]),
            "Target: $" + str(t["target_usd"]) + " | Progress: " + str(t["progress_pct"]) + "%",
            "Total: " + str(t["total_rub"]) + " RUB / $" + str(t["total_usd"]),
            "Channels: " + str(t["by_channel"]),
        ]
        return "\n".join(lines)


# ── Singletons ────────────────────────────────────────────────────────────────

_pool: Optional[AgentPool] = None
_revenue: Optional[RevenueTracker] = None


def get_pool() -> AgentPool:
    global _pool
    if _pool is None:
        _pool = AgentPool()
    return _pool


def get_revenue() -> RevenueTracker:
    global _revenue
    if _revenue is None:
        _revenue = RevenueTracker()
    return _revenue


if __name__ == "__main__":
    pool = get_pool()
    hr   = HRDirector(pool)
    rev  = get_revenue()

    print("=== MaxAI Agent Pool ===")
    print(json.dumps(pool.stats(), ensure_ascii=False, indent=2))
    print()
    print("=== 30-Day Plan to $1000/day ===")
    print(json.dumps(hr.hiring_plan(), ensure_ascii=False, indent=2))
    print()
    print("=== Revenue ===")
    print(rev.daily_report())
    print()
    print("=== Top Earners ===")
    for e in pool.top_earners(5):
        print(" ", e)
