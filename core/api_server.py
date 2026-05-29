# -*- coding: utf-8 -*-
"""
core/api_server.py — Internal REST API для межпроектного взаимодействия.
Запускается из main.py в фоновом потоке. Не блокирует daemon.
"""
from __future__ import annotations
import logging, threading
from typing import Any

log = logging.getLogger("core.api_server")

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False
    log.warning("fastapi/uvicorn not installed — internal API disabled. Run: pip install fastapi uvicorn")


def _build_app() -> "FastAPI":
    app = FastAPI(title="APEX AI Internal API", version="1.0.0", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "project": "ai-system", "version": "1.0.0"}

    @app.get("/agents/status")
    async def agents_status() -> dict[str, Any]:
        try:
            from brain.orchestrator import BrainOrchestrator
            return BrainOrchestrator.get().get_agent_statuses()
        except Exception as e:
            log.debug("agents_status error: %s", e)
            return {"error": str(e)}

    @app.post("/task")
    async def submit_task(payload: dict[str, Any]) -> dict[str, Any]:
        """
        Принять задачу от Trading Bot или внешних клиентов.
        Body: {"text": "...", "user_id": 0, "source": "trading-bot"}
        """
        try:
            from brain.orchestrator import BrainOrchestrator
            orch = BrainOrchestrator.get()
            text = payload.get("text", "")
            user_id = int(payload.get("user_id", 0))
            result = await orch.process(text, user_id)
            return {"ok": True, "result": result}
        except Exception as e:
            log.error("POST /task error: %s", e)
            return {"ok": False, "error": str(e)}

    @app.get("/llm/status")
    async def llm_status() -> dict[str, Any]:
        try:
            from brain.llm_router import LLMRouter
            return LLMRouter.get().status_report()
        except Exception as e:
            return {"error": str(e)}

    return app


def start_api_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    if not _HAS_FASTAPI:
        return
    app = _build_app()
    t = threading.Thread(
        target=lambda: uvicorn.run(
            app, host=host, port=port,
            log_level="warning", access_log=False
        ),
        daemon=True, name="api-server"
    )
    t.start()
    log.info("APEX AI internal API → http://%s:%d", host, port)
