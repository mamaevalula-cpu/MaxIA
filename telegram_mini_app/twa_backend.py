# -*- coding: utf-8 -*-
"""
telegram_mini_app/twa_backend.py — FastAPI backend для Telegram Mini App.

Secure bridge между TWA frontend (React) и основной системой.
Все операции проходят валидацию initData, risk-check, и audit logging.

Запуск:
    uvicorn telegram_mini_app.twa_backend:app --host 127.0.0.1 --port 8002 --workers 2
"""
from __future__ import annotations

import logging
import json
import hmac
import hashlib
import os
from typing import Optional, Callable
from datetime import datetime, timedelta
from functools import wraps
import uuid

from fastapi import FastAPI, HTTPException, Request, Depends, Header
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .twa_types import (
    TelegramInitData, TelegramUser, TWARequest, TWAResponse,
    PortfolioSnapshot, AlertSnapshot, PositionSnapshot,
    PremiumState, PremiumFeature, StarTransaction
)

log = logging.getLogger("twa_backend")

# ─── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Telegram Mini App Backend",
    description="Secure bridge for Telegram Web App",
    version="1.0.0"
)

# CORS: Allow only trusted origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://web.telegram.org"],  # Telegram WebApp only
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["Content-Type", "Authorization", "X-Init-Data", "X-Idempotency-Key"],
)

# ─── Configuration ────────────────────────────────────────────────────────────

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
MAX_REQUEST_AGE_SECONDS = 300  # Requests older than 5 min are rejected
IDEMPOTENCY_TTL = 3600  # 1 hour

# In-memory caches (use Redis in production)
_verified_sessions: dict[int, datetime] = {}  # user_id -> expiration
_idempotency_cache: dict[str, TWAResponse] = {}  # idempotency_key -> response

# ─── Pydantic Request Models ──────────────────────────────────────────────────

class InitDataRequest(BaseModel):
    """Frontend sends raw initData to validate."""
    init_data: str


class TWAActionRequest(BaseModel):
    """Generic action request from TWA."""
    action: str
    data: dict
    idempotency_key: Optional[str] = None


# ─── Init Data Validation ──────────────────────────────────────────────────────

def parse_and_validate_init_data(init_data_str: str) -> TelegramInitData:
    """
    Parse & validate Telegram WebApp initData.
    
    Raises HTTPException if invalid.
    """
    try:
        # Parse query string format: key=value&key=value&...
        params = dict(p.split("=", 1) for p in init_data_str.split("&"))
        
        # Extract user JSON
        user_data = json.loads(params.get("user", "{}"))
        user = TelegramUser(
            id=user_data["id"],
            is_bot=user_data.get("is_bot", False),
            first_name=user_data.get("first_name", ""),
            username=user_data.get("username"),
            language_code=user_data.get("language_code"),
            is_premium=user_data.get("is_premium"),
        )
        
        # Extract auth data
        auth_date = int(params.get("auth_date", 0))
        hash_value = params.get("hash", "")
        
        init_data = TelegramInitData(
            auth_date=auth_date,
            hash=hash_value,
            user=user,
            start_param=params.get("start_param"),
            chat_instance=params.get("chat_instance"),
        )
        
        # Validate signature
        if not init_data.is_valid_signature(BOT_TOKEN):
            raise HTTPException(status_code=401, detail="Invalid signature")
        
        # Validate age (prevent replay attacks)
        age = (datetime.utcnow().timestamp() - auth_date)
        if age > MAX_REQUEST_AGE_SECONDS:
            raise HTTPException(status_code=401, detail="Init data too old")
        
        return init_data
        
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        log.warning(f"Invalid init data: {e}")
        raise HTTPException(status_code=400, detail="Invalid init data format")


async def get_current_user(x_init_data: str = Header(None)) -> TelegramUser:
    """Dependency: extract & validate user from X-Init-Data header."""
    if not x_init_data:
        raise HTTPException(status_code=401, detail="Missing X-Init-Data header")
    
    init_data = parse_and_validate_init_data(x_init_data)
    return init_data.user


# ─── Idempotency & Request Deduplication ──────────────────────────────────────

def require_idempotency(f: Callable) -> Callable:
    """Decorator: ensure idempotent requests."""
    @wraps(f)
    async def wrapper(*args, idempotency_key: Optional[str] = None, **kwargs):
        if idempotency_key:
            if idempotency_key in _idempotency_cache:
                return _idempotency_cache[idempotency_key]
        
        result = await f(*args, **kwargs)
        
        if idempotency_key:
            _idempotency_cache[idempotency_key] = result
            # TODO: Add cleanup task for expired keys
        
        return result
    
    return wrapper


# ─── Health & Status ──────────────────────────────────────────────────────────

@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "service": "telegram-mini-app-backend"
    }


@app.post("/auth/validate")
async def validate_init_data(req: InitDataRequest) -> dict:
    """
    Validate & cache session from init data.
    Called by frontend after user opens Mini App.
    """
    init_data = parse_and_validate_init_data(req.init_data)
    user_id = init_data.user.id
    
    # Cache session
    _verified_sessions[user_id] = datetime.utcnow() + timedelta(hours=1)
    
    log.info(f"Session validated: user_id={user_id}")
    
    return {
        "success": True,
        "user": init_data.user.to_dict(),
        "session_valid_until": _verified_sessions[user_id].isoformat(),
    }


# ─── Portfolio API ────────────────────────────────────────────────────────────

async def get_portfolio_snapshot(user_id: int) -> PortfolioSnapshot:
    """
    Fetch current portfolio state from trading core.
    
    TODO: Implement actual fetch from trading_agent / integrations.
    """
    # Placeholder: return dummy data
    return PortfolioSnapshot(
        balance=10000.0,
        equity=10500.0,
        margin_used=500.0,
        margin_available=9500.0,
        total_pnl=500.0,
        total_pnl_percent=5.0,
        positions=[
            PositionSnapshot(
                id="pos_1",
                symbol="BTC/USDT",
                size=0.5,
                entry_price=40000,
                current_price=41000,
                pnl=500,
                pnl_percent=2.5,
                risk_level="low",
                stop_loss=39000,
                take_profit=42000,
            )
        ],
        alerts=[
            AlertSnapshot(
                id="alert_1",
                severity="warning",
                title="High volatility detected",
                message="BTC/USDT volatility exceeded 3% in 5 min",
                action_required=False,
            )
        ],
        risk_score=25.0,
        updated_at=datetime.utcnow(),
    )


@app.get("/portfolio")
async def get_portfolio(user: TelegramUser = Depends(get_current_user)) -> dict:
    """Get full portfolio snapshot for dashboard."""
    portfolio = await get_portfolio_snapshot(user.id)
    return portfolio.to_dict()


# ─── Trading Actions with Risk Check ──────────────────────────────────────────

async def check_action_risk(
    user_id: int,
    action: str,
    data: dict
) -> tuple[bool, Optional[str]]:
    """
    Check if action is safe to execute.
    Returns (is_safe, reason_if_not_safe)
    
    TODO: Integrate with real risk checker.
    """
    # Placeholder checks
    if action == "close_position" and data.get("size", 0) > 0.5:
        return False, "Position too large, requires confirmation"
    
    return True, None


@app.post("/action/execute")
@require_idempotency
async def execute_action(
    req: TWAActionRequest,
    user: TelegramUser = Depends(get_current_user),
    x_idempotency_key: str = Header(None),
) -> dict:
    """
    Execute a TWA action (trade, close position, etc).
    
    Actions:
    - close_position: { position_id: str }
    - set_alert: { symbol: str, level: float, type: "price" | "pnl" }
    - emergency_stop: {}
    """
    action = req.action
    data = req.data
    
    log.info(f"Action requested: {action} by user {user.id}")
    
    # Risk check
    is_safe, reason = await check_action_risk(user.id, action, data)
    
    if not is_safe:
        return {
            "success": False,
            "requires_confirmation": True,
            "confirmation_prompt": reason,
            "error": None,
        }
    
    # Execute action
    try:
        if action == "close_position":
            position_id = data.get("position_id")
            # TODO: Call trading agent
            result = {"closed_position_id": position_id}
        
        elif action == "set_alert":
            # TODO: Call alert service
            result = {"alert_id": str(uuid.uuid4())}
        
        elif action == "emergency_stop":
            # TODO: Stop all trading
            result = {"status": "stopped"}
        
        else:
            raise ValueError(f"Unknown action: {action}")
        
        return {
            "success": True,
            "data": result,
        }
    
    except Exception as e:
        log.exception(f"Action execution failed: {action}")
        return {
            "success": False,
            "error": str(e),
        }


# ─── Premium & Stars ──────────────────────────────────────────────────────────

async def get_premium_state(user_id: int) -> PremiumState:
    """
    Fetch user's premium status & entitlements.
    
    TODO: Implement actual fetch from revenue service.
    """
    return PremiumState(
        user_id=user_id,
        is_premium=False,
        stars_balance=0,
        features=[],
        subscriptions=[],
    )


@app.get("/premium/status")
async def get_premium_status(user: TelegramUser = Depends(get_current_user)) -> dict:
    """Get user's premium status & available features."""
    state = await get_premium_state(user.id)
    return state.to_dict()


@app.post("/premium/purchase")
async def purchase_premium(
    req: dict,
    user: TelegramUser = Depends(get_current_user),
) -> dict:
    """
    Initiate Star purchase.
    Frontend shows Telegram payment dialog, backend verifies completion.
    """
    product_id = req.get("product_id")
    
    # TODO: Integrate with Telegram payment API
    
    return {
        "success": True,
        "transaction_id": str(uuid.uuid4()),
        "message": "Purchase initiated. Confirm in Telegram.",
    }


# ─── Audit & Logging ──────────────────────────────────────────────────────────

@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """Log all TWA API calls for security audit."""
    if request.url.path.startswith("/api/"):
        user_id = None
        try:
            init_data = request.headers.get("X-Init-Data")
            if init_data:
                parsed = parse_and_validate_init_data(init_data)
                user_id = parsed.user.id
        except:
            pass
        
        start = datetime.utcnow()
        response = await call_next(request)
        duration = (datetime.utcnow() - start).total_seconds()
        
        log.info(f"[AUDIT] {request.method} {request.url.path} user={user_id} status={response.status_code} duration={duration:.3f}s")
    else:
        response = await call_next(request)
    
    return response


# ─── Error Handling ──────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Standard error response."""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": exc.detail,
        },
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8002,
        workers=1,
    )
