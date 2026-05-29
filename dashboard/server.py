# -*- coding: utf-8 -*-
"""
dashboard/server.py — Web Dashboard server (port 8080).
Runs in background thread, accessible from outside via http://SERVER_IP:8080/
"""
from __future__ import annotations
import logging, threading
from pathlib import Path
from typing import Any

log = logging.getLogger("dashboard.server")

def start_dashboard(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Launch dashboard FastAPI app in background daemon thread."""
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.staticfiles import StaticFiles
        import uvicorn
    except ImportError as e:
        log.warning("Dashboard deps missing (%s) — run: pip install fastapi uvicorn", e)
        return

    app = FastAPI(title="APEX AI Dashboard", version="5.0", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    from dashboard.routes import register
    register(app)

    # Serve static files fallback (js/css/assets if any)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    t = threading.Thread(
        target=lambda: uvicorn.run(
            app, host=host, port=port,
            log_level="warning", access_log=False,
        ),
        daemon=True, name="dashboard-server"
    )
    t.start()
    log.info("APEX AI Dashboard → http://%s:%d/", host, port)
    print(f"  [Dashboard] http://{host}:{port}/  (accessible externally)")
