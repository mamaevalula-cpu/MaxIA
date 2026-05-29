# -*- coding: utf-8 -*-
"""
telegram_mini_app/twa_types.py — Shared types для TWA backend & frontend.
"""
from __future__ import annotations
from typing import Optional, Any, Literal
from dataclasses import dataclass, asdict
from datetime import datetime
import json

# ─── Telegram WebApp InitData Validation ──────────────────────────────────────

@dataclass
class TelegramUser:
    """Telegram user из initData."""
    id: int
    is_bot: bool
    first_name: str
    username: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: Optional[bool] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TelegramInitData:
    """Parsed initData от Telegram WebApp."""
    auth_date: int
    hash: str
    user: TelegramUser
    start_param: Optional[str] = None
    chat_instance: Optional[str] = None
    
    def is_valid_signature(self, bot_token: str) -> bool:
        """Verify signature against Telegram bot token."""
        import hmac
        import hashlib
        
        # Build data-check-string: key=value\nkey=value\n...
        check_string = "\n".join([
            f"auth_date={self.auth_date}",
            f"user={json.dumps(asdict(self.user), sort_keys=True)}" if self.user else "",
            *(f"{k}={v}" for k, v in [
                ("chat_instance", self.chat_instance),
                ("start_param", self.start_param),
            ] if v)
        ]).strip()
        
        # Compute HMAC-SHA256(bot_token, check_string)
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        
        return computed_hash == self.hash

# ─── TWA API Request/Response Types ────────────────────────────────────────────

@dataclass
class TWARequest:
    """Generic TWA request from frontend."""
    action: str  # "get_balance", "close_position", "set_alert", etc.
    data: dict[str, Any]
    idempotency_key: Optional[str] = None  # For safety


@dataclass
class TWAResponse:
    """Generic TWA response."""
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    requires_confirmation: bool = False
    confirmation_prompt: Optional[str] = None
    
    def to_json(self) -> str:
        return json.dumps({
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_prompt": self.confirmation_prompt,
        })


# ─── Trading State for TWA Display ────────────────────────────────────────────

@dataclass
class PositionSnapshot:
    """Trading position snapshot for TWA."""
    id: str
    symbol: str
    size: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_percent: float
    risk_level: Literal["low", "medium", "high", "critical"]  # dynamically computed
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioSnapshot:
    """Full portfolio state for TWA dashboard."""
    balance: float
    equity: float
    margin_used: float
    margin_available: float
    total_pnl: float
    total_pnl_percent: float
    positions: list[PositionSnapshot]
    alerts: list[AlertSnapshot]
    risk_score: float  # 0-100, 0=safe, 100=critical
    updated_at: datetime
    
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["positions"] = [p.to_dict() for p in self.positions]
        d["alerts"] = [a.to_dict() for a in self.alerts]
        d["updated_at"] = self.updated_at.isoformat()
        return d


@dataclass
class AlertSnapshot:
    """Alert for TWA display."""
    id: str
    severity: Literal["info", "warning", "critical"]
    title: str
    message: str
    action_required: bool
    suggested_action: Optional[str] = None  # "close_position", "emergency_stop", etc.
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


# ─── Premium & Revenue Types ────────────────────────────────────────────────────

@dataclass
class PremiumFeature:
    """Premium feature entitlement."""
    id: str
    name: str
    description: str
    cost_stars: int
    is_subscription: bool
    granted_until: Optional[datetime] = None  # For subscriptions
    
    def is_active(self) -> bool:
        if not self.is_subscription:
            return True
        return self.granted_until is not None and datetime.utcnow() < self.granted_until
    
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.granted_until:
            d["granted_until"] = self.granted_until.isoformat()
        return d


@dataclass
class PremiumState:
    """User's premium status."""
    user_id: int
    is_premium: bool
    stars_balance: int
    features: list[PremiumFeature]
    subscriptions: list[str]  # ["alerts_pro", "analytics_pro", ...]
    
    def has_feature(self, feature_id: str) -> bool:
        return any(f.id == feature_id and f.is_active() for f in self.features)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "is_premium": self.is_premium,
            "stars_balance": self.stars_balance,
            "features": [f.to_dict() for f in self.features],
            "subscriptions": self.subscriptions,
        }


@dataclass
class StarTransaction:
    """Record of Telegram Star transaction."""
    user_id: int
    product_id: str
    amount: int
    direction: Literal["in", "out"]  # in=purchase, out=refund
    status: Literal["pending", "completed", "failed"]
    transaction_id: str
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d
