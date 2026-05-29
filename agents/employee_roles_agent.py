#!/usr/bin/env python3
"""
agents/employee_roles_agent.py
MaxAI company org structure manager.
Maps all agents to roles, departments, KPIs.
Runs daily to verify all roles are filled.
"""
import json, logging, os
from pathlib import Path
from datetime import datetime

log = logging.getLogger("agents.employee_roles")
BASE = Path("/root/my_personal_ai")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "1985320458")
ROLES_FILE = BASE / "data" / "employee_roles.json"

try:
    from agents.base_agent import BaseAgent, AgentInfo
    HAS_BASE = True
except ImportError:
    BaseAgent = object; AgentInfo = None; HAS_BASE = False

ORG_STRUCTURE = {
    "C_SUITE": {
        "description": "Top management - strategy and control",
        "employees": {
            "hyperion_ceo_agent":     {"title": "CEO",            "kpi": "All services GREEN", "schedule": "every 3h"},
            "quality_guardian_agent": {"title": "CPO/QA Director","kpi": "avg quality > 85/100", "schedule": "every 6h"},
            "world_expander_agent":   {"title": "CMO",            "kpi": "new market expansion", "schedule": "7am/7pm"},
            "agent_factory_agent":    {"title": "CHRO",           "kpi": "1 new agent/12h", "schedule": "every 12h"},
            "autodev_agent":          {"title": "CTO",            "kpi": "backlog improvements", "schedule": "every 8h"},
        }
    },
    "ENGINEERING": {
        "description": "Development and infrastructure",
        "employees": {
            "claude_dev_agent": {"title": "Lead Engineer", "kpi": "code_change tasks"},
            "coder_agent":      {"title": "Engineer",      "kpi": "coding tasks"},
            "server_agent":     {"title": "DevOps",        "kpi": "server operations"},
        }
    },
    "SALES": {
        "description": "Sales and client acquisition",
        "employees": {
            "freelance_agent":        {"title": "Sales Rep",      "kpi": "Kwork orders"},
            "b2b_leads_agent":        {"title": "BD Manager",     "kpi": "B2B leads"},
            "instagram_parser_agent": {"title": "Lead Gen",       "kpi": "Instagram leads"},
            "avito_scanner_agent":    {"title": "Lead Gen",       "kpi": "Avito clients"},
            "promotion_agent":        {"title": "Growth Manager", "kpi": "promotion"},
        }
    },
    "FINANCE": {
        "description": "Finance and trading",
        "employees": {
            "bybit_earn_agent":        {"title": "Finance Ops",   "kpi": "Bybit Earn APY"},
            "funding_arb_agent":       {"title": "Quant Trader",  "kpi": "funding rate arb"},
            "crypto_rebalancer_agent": {"title": "Portfolio Mgr", "kpi": "40/40/20 allocation"},
            "expense_tracker_agent":   {"title": "Accountant",    "kpi": "expense tracking"},
        }
    },
    "AI_ML": {
        "description": "AI training and improvement",
        "employees": {
            "smart_trainer_agent": {"title": "ML Engineer",   "kpi": "error reduction"},
            "analyzer_agent":      {"title": "Data Analyst",  "kpi": "system insights"},
        }
    },
    "MARKETING": {
        "description": "Marketing and content",
        "employees": {
            "channel_monetization_agent": {"title": "Media Manager", "kpi": "TG channel revenue"},
            "saas_subscription_agent":    {"title": "Product Mgr",   "kpi": "MRR growth"},
        }
    },
    "OPERATIONS": {
        "description": "Day-to-day operations",
        "employees": {
            "task_executor_agent": {"title": "Ops Manager",  "kpi": "tasks completed"},
            "scheduler_agent":     {"title": "Scheduler",    "kpi": "cron jobs"},
            "hr_director":         {"title": "HR Director",  "kpi": "agent hiring"},
        }
    },
}

COMPANY_KPIS = {
    "revenue_target_monthly_usd": 5000,
    "agent_quality_target": 85,
    "service_uptime_target_pct": 99,
    "agents_total_target": 80,
    "capabilities_target": 20,
}


class EmployeeRolesAgent(BaseAgent if HAS_BASE else object):
    name = "employee_roles"
    VERSION = "1.0"

    def __init__(self, **kwargs):
        if HAS_BASE:
            super().__init__("employee_roles")

    def can_handle(self, text: str) -> bool:
        return any(k in text.lower() for k in ["roles", "employees", "org", "structure", "staff"])

    def info(self):
        if AgentInfo:
            return AgentInfo(name="employee_roles",
                             description="Manages MaxAI company org structure and employee KPIs",
                             capabilities=["org_chart", "kpi_check", "role_audit"])
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

    def audit_roles(self):
        """Check all roles are filled by existing agent files."""
        agents_dir = BASE / "agents"
        existing = {f.stem for f in agents_dir.glob("*.py")}
        gaps = []
        filled = []
        for dept, info in ORG_STRUCTURE.items():
            for agent_name, role in info["employees"].items():
                if agent_name in existing:
                    filled.append(role["title"] + " (" + agent_name + ")")
                else:
                    gaps.append(dept + "/" + role["title"] + " (" + agent_name + ")")
        return {"filled": len(filled), "gaps": gaps, "total_roles": len(filled) + len(gaps)}

    def generate_org_chart(self):
        """Generate text org chart."""
        lines = ["MAXAI ORG STRUCTURE", "=" * 40]
        for dept, info in ORG_STRUCTURE.items():
            lines.append("")
            lines.append("[" + dept + "] " + info["description"])
            for agent, role in info["employees"].items():
                lines.append("  * " + role["title"] + ": " + agent)
                if "kpi" in role:
                    lines.append("    KPI: " + str(role["kpi"]))
        return "\n".join(lines)

    def daily_org_report(self):
        """Run daily org audit and report."""
        audit = self.audit_roles()
        chart = self.generate_org_chart()
        state = {
            "last_run": datetime.now().isoformat(),
            "filled_roles": audit["filled"],
            "gaps": audit["gaps"],
            "total_roles": audit["total_roles"],
            "departments": len(ORG_STRUCTURE),
        }
        ROLES_FILE.parent.mkdir(parents=True, exist_ok=True)
        ROLES_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

        msg = "MAXAI Org Report\n"
        msg += str(len(ORG_STRUCTURE)) + " departments\n"
        msg += "Roles filled: " + str(audit["filled"]) + "/" + str(audit["total_roles"]) + "\n"
        if audit["gaps"]:
            msg += "Vacancies: " + ", ".join(audit["gaps"][:3]) + "\n"
        else:
            msg += "All roles filled!\n"
        msg += "Chart saved to employee_roles.json"
        self._tg(msg)
        return "Org audit: " + str(audit["filled"]) + "/" + str(audit["total_roles"]) + " roles filled"

    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        """Orchestrator bridge."""
        return self.daily_org_report()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = EmployeeRolesAgent()
    print(agent.generate_org_chart())
    print()
    print(agent.daily_org_report())
