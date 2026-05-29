"""
MaxAI Gateway Extension — adds /maxai/* endpoints to Hyperion gateway
Exposes agent pool stats, hiring plans, revenue, and public marketplace
"""
from __future__ import annotations
import json, time
from pathlib import Path
from typing import Any, Dict, List

# ── These endpoints are ADDED to the existing gateway.py app ─────────────────
# Import and call extend_app(app) from gateway.py startup


def extend_app(app):
    """Register MaxAI endpoints on existing FastAPI app."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from maxai.core import get_pool, get_revenue, HRDirector

    @app.get("/maxai/status")
    async def maxai_status() -> Dict:
        """Full MaxAI system status."""
        pool = get_pool()
        rev  = get_revenue()
        hr   = HRDirector(pool)
        return {
            "brand":    "MaxAI — World's Largest AI Agent Marketplace",
            "version":  "1.0.0",
            "agents":   pool.stats(),
            "revenue":  rev.today_stats(),
            "plan":     hr.hiring_plan(),
            "hyperion_port": 8005,
            "ts":       time.time(),
        }

    @app.get("/maxai/agents")
    async def maxai_agents(skill: str = "", tier: str = "") -> Dict:
        """List MaxAI agents, optionally filtered."""
        pool   = get_pool()
        agents = list(pool._agents.values())
        if skill:
            agents = [a for a in agents if skill in a.skills]
        if tier:
            agents = [a for a in agents if a.tier == tier.upper()]
        return {
            "count":  len(agents),
            "agents": [
                {"id": a.agent_id, "name": a.name, "tier": a.tier,
                 "skills": a.skills, "status": a.status,
                 "tasks": a.tasks_done, "revenue_rub": a.revenue_rub}
                for a in agents if a.status != "retired"
            ]
        }

    @app.get("/maxai/revenue")
    async def maxai_revenue() -> Dict:
        rev = get_revenue()
        return rev.today_stats()

    @app.post("/maxai/hire")
    async def maxai_hire(body: Dict) -> Dict:
        """Hire a new agent via API."""
        pool = get_pool()
        name   = body.get("name", f"agent_{int(time.time())}")
        skills = body.get("skills", ["python"])
        tier   = body.get("tier", "WORKER")
        desc   = body.get("description", "")
        agent  = pool.hire(name, skills, tier, desc)
        return {"hired": True, "agent_id": agent.agent_id, "name": agent.name}

    @app.post("/maxai/revenue/record")
    async def maxai_record_revenue(body: Dict) -> Dict:
        """Record a revenue transaction."""
        rev = get_revenue()
        rev.record(
            amount_rub = float(body.get("amount_rub", 0)),
            channel    = body.get("channel", "direct"),
            task_id    = body.get("task_id", ""),
            agent      = body.get("agent", ""),
        )
        return {"ok": True, "total_usd": rev.data["total_usd"]}

    @app.get("/maxai/leaderboard")
    async def maxai_leaderboard() -> Dict:
        pool = get_pool()
        return {
            "top_earners":  pool.top_earners(10),
            "agent_stats":  pool.stats(),
            "brand":        "MaxAI",
        }

    @app.get("/maxai/hiring-plan")
    async def maxai_hiring_plan() -> Dict:
        pool = get_pool()
        hr   = HRDirector(pool)
        return hr.hiring_plan()

    @app.get("/maxai/v12/dashboard")
    async def maxai_v12_dashboard():
        """Hyperion v12: PostgreSQL tasks + RabbitMQ queue depths."""
        import urllib.request as _ur, json as _json
        try:
            with _ur.urlopen("http://localhost:8006/dashboard", timeout=3) as _r:
                data = _json.loads(_r.read())
            data["control_plane"] = "http://localhost:8006"
            data["data_plane"] = "active"
            return data
        except Exception as _e:
            return {"error": str(_e), "control_plane_port": 8006}



    return app


# ── Hyperion v12 Dashboard ────────────────────────────────────────────────────

