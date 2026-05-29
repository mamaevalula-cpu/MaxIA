# -*- coding: utf-8 -*-
"""
integrations/trading_bridge.py — HTTP-клиент к Trading Bot (:8001).
Fire-and-forget для событий. Sync-запросы для статуса.
"""
from __future__ import annotations
import logging
from typing import Any, Optional

log = logging.getLogger("integrations.trading_bridge")
_TRADING_URL = "http://127.0.0.1:8001"


async def get_trading_status() -> Optional[dict[str, Any]]:
    """Статус торгового бота. None если недоступен."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{_TRADING_URL}/status")
            return r.json() if r.status_code == 200 else None
    except Exception as e:
        log.debug("Trading bot unreachable: %s", e)
        return None


async def notify_trade_event(event: dict[str, Any]) -> None:
    """Отправить событие от AI System → Trading Bot (fire-and-forget)."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(f"{_TRADING_URL}/signal", json=event)
    except Exception as e:
        log.debug("Trade event notify failed: %s", e)


async def request_ai_analysis(symbol: str, context: dict[str, Any]) -> str:
    """Trading Bot запрашивает AI-анализ через этот bridge."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post("http://127.0.0.1:8000/task", json={
                "text": f"Торговый анализ {symbol}: {context}",
                "user_id": 0,
                "source": "trading-bot"
            })
            return r.json().get("result", "")
    except Exception as e:
        log.warning("AI analysis request failed: %s", e)
        return ""
