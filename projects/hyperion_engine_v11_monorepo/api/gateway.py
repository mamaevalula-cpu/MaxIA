"""
api/gateway.py  —  FastAPI API Gateway for Корпорация MaxAI v11.

Exposes REST endpoints for:
  - Agent registration / discovery
  - Task submission and status tracking
  - Health check
"""
from __future__ import annotations

import logging
from pathlib import Path
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from core.agent_registry import AgentRegistry, AgentStatus
from core.orchestrator import Orchestrator, TaskRequest

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Корпорация MaxAI v11 — Agent Marketplace",
    version="11.0.0",
    description="Self-improving agent marketplace: register agents, submit tasks, track results.",
)

# These will be injected at startup
_registry: Optional[AgentRegistry] = None
_orchestrator: Optional[Orchestrator] = None


def init_app(registry: AgentRegistry, orchestrator: Orchestrator) -> None:
    global _registry, _orchestrator
    _registry = registry
    _orchestrator = orchestrator




# ── Auto-startup: init registry and orchestrator ─────────────────────

@app.on_event("startup")
async def startup_event() -> None:
    """Auto-initialise registry and orchestrator when uvicorn starts."""
    import os
    global _registry, _orchestrator
    try:
        # Load .env so env vars are available
        from dotenv import load_dotenv
        load_dotenv("/root/my_personal_ai/.env", override=False)
    except ImportError:
        pass

    try:
        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "agent_registry.db")
        _registry = AgentRegistry(db_path=Path(db_path))
        _registry.init()
        _orchestrator = Orchestrator(registry=_registry)
        logger.info("Hyperion startup: registry=%s, orchestrator=%s", _registry, _orchestrator)
        # Pre-register the default agents
        for agent_cfg in [
            {"name": "telegram_bot_builder", "capabilities": ["telegram", "python", "bot"], "description": "Builds production Telegram bots"},
            {"name": "trading_bot_builder",  "capabilities": ["trading", "bybit", "python"], "description": "Grid, DCA, Momentum trading bots"},
            {"name": "python_script_writer", "capabilities": ["python", "scraping", "automation"], "description": "Python scripts, parsers, API integrations"},
        ]:
            try:
                _registry.register(
                    name=agent_cfg["name"],
                    capabilities=agent_cfg["capabilities"],
                    description=agent_cfg["description"],
                )
            except Exception:
                pass  # Already registered
        logger.info("Hyperion: %d agents registered at startup", len(_registry.list_active()))
        # Load MaxAI endpoints (/maxai/status, /agents, /revenue, etc.)
        try:
            import sys as _sys, os as _os
            _sys.path.insert(0, str(Path(__file__).parent.parent))
            from maxai.gateway_ext import extend_app
            extend_app(app)
            logger.info("MaxAI endpoints registered: /maxai/*")
        except Exception as _ex:
            logger.warning("MaxAI ext failed (non-critical): %s", _ex)
        # Load Hyperion /api/v1/ and /api/v2/ endpoints
        try:
            from maxai.hyperion_endpoints import extend_hyperion_api
            extend_hyperion_api(app)
            logger.info("Hyperion API endpoints registered: /api/v1/* /api/v2/*")
        except Exception as _ex2:
            logger.warning("Hyperion API ext failed: %s", _ex2)

    except Exception as exc:
        logger.error("Hyperion startup failed: %s", exc, exc_info=True)



# ── Models ───────────────────────────────────────────────────────────

class AgentRegisterRequest(BaseModel):
    name: str = Field(..., description="Unique agent name")
    description: str = Field("", description="What this agent does")
    capabilities: List[str] = Field(..., description="List of task capabilities")
    version: str = Field("1.0.0")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentResponse(BaseModel):
    agent_id: str
    name: str
    status: str
    capabilities: List[str]
    tasks_completed: int
    tasks_failed: int


class TaskSubmitRequest(BaseModel):
    capability: str = Field(..., description="Required agent capability")
    payload: Dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(5, ge=1, le=10, description="1=high, 10=low")
    timeout_seconds: float = Field(60.0, gt=0)
    max_retries: int = Field(3, ge=0, le=10)


class TaskResponse(BaseModel):
    task_id: str
    status: str
    submitted_at: float


# ── Endpoints ────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "ts": time.time(),
        "service": "hyperion-engine-v11",
    }


@app.post("/agents/register", response_model=AgentResponse,
          status_code=status.HTTP_201_CREATED)
async def register_agent(req: AgentRegisterRequest) -> AgentResponse:
    if _registry is None:
        raise HTTPException(503, "Registry not initialised")
    agent_id = _registry.register(
        name=req.name,
        description=req.description,
        capabilities=req.capabilities,
        version=req.version,
        metadata=req.metadata,
    )
    rec = _registry.get(agent_id)
    return AgentResponse(
        agent_id=rec.agent_id,
        name=rec.name,
        status=rec.status.value,
        capabilities=rec.capabilities,
        tasks_completed=rec.tasks_completed,
        tasks_failed=rec.tasks_failed,
    )


@app.get("/agents", response_model=List[AgentResponse])
async def list_agents() -> List[AgentResponse]:
    if _registry is None:
        raise HTTPException(503, "Registry not initialised")
    agents = _registry.list_active()
    return [
        AgentResponse(
            agent_id=a.agent_id,
            name=a.name,
            status=a.status.value,
            capabilities=a.capabilities,
            tasks_completed=a.tasks_completed,
            tasks_failed=a.tasks_failed,
        )
        for a in agents
    ]


@app.post("/tasks/submit", response_model=TaskResponse,
          status_code=status.HTTP_202_ACCEPTED)
async def submit_task(req: TaskSubmitRequest) -> TaskResponse:
    if _orchestrator is None:
        raise HTTPException(503, "Orchestrator not initialised")
    task = TaskRequest(
        capability=req.capability,
        payload=req.payload,
        priority=req.priority,
        timeout_seconds=req.timeout_seconds,
        max_retries=req.max_retries,
    )
    task_id = await _orchestrator.submit(task)
    return TaskResponse(
        task_id=task_id,
        status="pending",
        submitted_at=task.submitted_at,
    )




# ── MaxAI Landing Page ────────────────────────────────────────────────────────
from fastapi.responses import HTMLResponse

@app.get("/", response_class=HTMLResponse)
async def landing_page():
    """MaxAI public landing page."""
    try:
        from pathlib import Path as _Path
        html_path = _Path(__file__).parent.parent / "maxai" / "landing.html"
        if html_path.exists():
            return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return HTMLResponse(content="""
    <html><head><title>MaxAI</title></head>
    <body style='background:#060610;color:#00D4FF;font-family:monospace;padding:40px;'>
    <h1>MaxAI Agent Marketplace</h1>
    <p>API running on port 8005</p>
    <a href='/marketplace' style='color:#7B2FFF'>View Marketplace</a>
    </body></html>
    """)


# ── Payment endpoint (CryptoPay integration) ─────────────────────────

class PaymentRequest(BaseModel):
    agent_name: str = Field(..., description="Agent to hire")
    task_description: str = Field(..., description="What you need done")
    budget_rub: float = Field(1000.0, description="Budget in RUB")
    contact_telegram: str = Field("", description="Your Telegram @username")


class PaymentResponse(BaseModel):
    invoice_id: str
    pay_url: str
    amount_rub: float
    agent_name: str
    status: str


@app.post("/pay", response_model=PaymentResponse, status_code=201)
async def create_payment(req: PaymentRequest) -> PaymentResponse:
    """Create CryptoPay invoice to hire an agent."""
    import os, urllib.request, json as _json

    token = os.getenv("CRYPTOPAY_TOKEN", os.getenv("CRYPTO_PAY_TOKEN", ""))
    if not token:
        raise HTTPException(503, "Payment system not configured")

    # Convert RUB → USDT (approx 1 USDT = 90 RUB)
    amount_usdt = round(req.budget_rub / 90.0, 2)

    desc = (
        f"HYPERION ENGINE v11.0\n"
        f"Agent: {req.agent_name}\n"
        f"Task: {req.task_description[:100]}\n"
        f"Contact: {req.contact_telegram}"
    )

    try:
        payload = _json.dumps({
            "asset": "USDT",
            "amount": str(amount_usdt),
            "description": desc,
            "paid_btn_name": "callback",
            "paid_btn_url": "https://t.me/your_bot_username",
        }).encode()

        req_obj = urllib.request.Request(
            os.getenv("CRYPTOPAY_API_URL", "https://pay.crypt.bot/api/createInvoice"),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Crypto-Pay-API-Token": token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req_obj, timeout=10) as resp:
            data = _json.loads(resp.read())

        if data.get("ok"):
            inv = data["result"]
            return PaymentResponse(
                invoice_id=str(inv["invoice_id"]),
                pay_url=inv["pay_url"],
                amount_rub=req.budget_rub,
                agent_name=req.agent_name,
                status="pending",
            )
        raise HTTPException(502, f"CryptoPay error (check CRYPTOPAY_TOKEN and CRYPTOPAY_API_URL): {data}")

    except Exception as exc:
        logger.error("Payment creation failed: %s", exc)
        raise HTTPException(502, f"Payment failed: {exc}")


@app.get("/marketplace")
async def marketplace_info() -> Dict[str, Any]:
    """Public info about available agents and pricing."""
    return {
        "platform": "HYPERION ENGINE v11.0",
        "tagline": "AI Agent Marketplace — hire agents, automate tasks",
        "agents": [
            {
                "name": "telegram_bot_builder",
                "title": "Telegram Bot Builder",
                "description": "Creates production-ready Telegram bots with AI, commands, keyboards, DB",
                "price_rub": 1000,
                "delivery_hours": 24,
                "examples": ["Support bot", "Order bot", "AI assistant bot"],
            },
            {
                "name": "trading_bot_builder",
                "title": "Trading Bot (Bybit/Binance)",
                "description": "Grid, DCA, Momentum strategies. Tested on live accounts.",
                "price_rub": 1500,
                "delivery_hours": 48,
            },
            {
                "name": "python_script_writer",
                "title": "Python Script / Parser",
                "description": "Web scraping, API integration, automation, data processing",
                "price_rub": 800,
                "delivery_hours": 24,
            },
        ],
        "contact_telegram": "@hyperion_engine_bot",
        "pay_endpoint": "/pay",
        "task_endpoint": "/tasks/submit",
    }
