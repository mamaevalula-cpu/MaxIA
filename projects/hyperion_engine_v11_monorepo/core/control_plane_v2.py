"""
Hyperion v12 — Control Plane (Economic Router)
FastAPI on port 8006. Replaces NestJS (Node.js not installed).
Receives tasks → computes EV → routes to execution queue.
"""
from __future__ import annotations
import asyncio, json, logging, os, time, uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
import asyncpg, aio_pika
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
try:
    import sys as _sys, os as _os
    _root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _root not in _sys.path:
        _sys.path.insert(0, _root)
    from core.hyperion_v121_api import router as v121_router
    print(f"[v12.1] API router loaded: {len(v121_router.routes)} routes")
except Exception as _e:
    print(f"[v12.1] WARNING: router not loaded: {_e}")
    v121_router = None
from pydantic import BaseModel

log = logging.getLogger("hyperion.control_plane")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

PG_DSN   = os.environ.get("HYPERION_PG_DSN",   "postgresql://postgres@localhost/hyperion_v12")
AMQP_URL = os.environ.get("HYPERION_AMQP_URL",  "amqp://guest:guest@localhost/")

_pg:      Optional[asyncpg.Pool]          = None
_amqp:    Optional[aio_pika.Connection]   = None
_channel: Optional[aio_pika.Channel]      = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pg, _amqp, _channel
    _pg      = await asyncpg.create_pool(PG_DSN, min_size=2, max_size=10)
    _amqp    = await aio_pika.connect_robust(AMQP_URL)
    _channel = await _amqp.channel()
    await _channel.set_qos(prefetch_count=10)
    log.info("Control Plane v12 started")
    yield
    await _pg.close()
    await _amqp.close()


app = FastAPI(title="Hyperion v12 Control Plane", lifespan=lifespan)

# Mount v12.1 Control Surface
if v121_router:
    app.include_router(v121_router)
# Mount v12.2 Monolith Extension
try:
    import sys as _sys2, os as _os2
    _root2 = _os2.path.dirname(_os2.path.dirname(_os2.path.abspath(__file__)))
    if _root2 not in _sys2.path:
        _sys2.path.insert(0, _root2)
    from core.hyperion_v122_ext import router as v122_router
    app.include_router(v122_router)
    print(f"[v12.2] Monolith ext loaded: {len(v122_router.routes)} routes")
except Exception as _e2:
    import traceback as _tb2
    print(f"[v12.2] WARNING: ext not loaded: {_e2}")
    print(_tb2.format_exc()[:300])
    v122_router = None


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/api/v1/ui")


class TaskSubmit(BaseModel):
    department_id:      str            = "maxai-dev"
    market_id:          str            = "RU"
    business_context:   Dict[str, Any] = {}
    input_data:         Dict[str, Any] = {}
    expected_revenue:   float          = 10.0
    estimated_cost:     float          = 0.5
    success_probability: float         = 0.8
    urgency_score:      int            = 1


@app.get("/health")
async def health():
    return {"status": "ok", "service": "hyperion-control-plane-v12"}


@app.post("/tasks/submit")
async def submit_task(body: TaskSubmit):
    task_id = str(uuid.uuid4())
    await _pg.execute(
        "INSERT INTO tasks(task_id,department_id,market_id,business_context,input_data,created_at,updated_at)"
        " VALUES($1,$2,$3,$4,$5,NOW(),NOW())",
        task_id, body.department_id, body.market_id,
        json.dumps(body.business_context), json.dumps(body.input_data)
    )
    ev = (body.expected_revenue * body.success_probability) - body.estimated_cost
    await _pg.execute(
        "INSERT INTO task_valuations(task_id,expected_revenue,estimated_cost,success_probability,urgency_score)"
        " VALUES($1,$2,$3,$4,$5)",
        task_id, body.expected_revenue, body.estimated_cost,
        body.success_probability, body.urgency_score
    )
    if ev > 0:
        await _pg.execute("UPDATE tasks SET current_state='VALUATED',updated_at=NOW() WHERE task_id=$1", task_id)
        exchange = await _channel.get_exchange("hyperion.v12.core")
        msg = json.dumps({
            "task_id": task_id,
            "department_id": body.department_id,
            "market_id": body.market_id,
            "input_data": body.input_data,
            "expected_value": ev
        }).encode()
        await exchange.publish(
            aio_pika.Message(body=msg, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key="task.capability.run"
        )
        await _pg.execute("UPDATE tasks SET current_state='ROUTED',updated_at=NOW() WHERE task_id=$1", task_id)
        state = "ROUTED"
    else:
        await _pg.execute("UPDATE tasks SET current_state='FAILED',updated_at=NOW() WHERE task_id=$1", task_id)
        state = "FAILED"
    return {"task_id": task_id, "expected_value": round(ev, 4), "routed": state == "ROUTED", "state": state}


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    row = await _pg.fetchrow("SELECT * FROM tasks WHERE task_id=$1", task_id)
    if not row:
        raise HTTPException(404, "Task not found")
    return dict(row)


@app.get("/dashboard")
async def dashboard():
    states   = await _pg.fetch("SELECT current_state, count(*) as n FROM tasks GROUP BY current_state")
    revenue  = await _pg.fetchrow("SELECT SUM(expected_revenue) as total_rev, COUNT(*) as total FROM task_valuations")
    caps     = await _pg.fetchrow("SELECT COUNT(*) as n FROM capabilities")
    patterns = await _pg.fetchrow("SELECT COUNT(*) as n FROM pattern_memory")
    return {
        "tasks_by_state":         {r["current_state"]: r["n"] for r in states},
        "total_tasks":            revenue["total"] or 0,
        "total_expected_revenue": float(revenue["total_rev"] or 0),
        "capabilities":           caps["n"] or 0,
        "patterns_learned":       patterns["n"] or 0,
        "pg_ok":                  True,
        "amqp_ok":                not _amqp.is_closed if _amqp else False,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8006, log_level="info")
