# -*- coding: utf-8 -*-
"""
telegram_mini_app/planner_router.py — Intelligent message router & intent planner.

Определяет intent, выбирает action, проверяет риск и возвращает decision:
- execute: выполнить действие безопасно
- clarify: уточнить у пользователя
- deny: опасное действие, отклонить
- error: внутренняя ошибка
- widget: отправить интерактивное окно (TWA)
"""
from __future__ import annotations

import logging
import json
from typing import Literal, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

log = logging.getLogger("planner_router")


class ActionStatus(str, Enum):
    """Decision status."""
    EXECUTE = "execute"        # Safe to execute immediately
    CLARIFY = "clarify"        # Need user confirmation
    DENY = "deny"              # Dangerous, reject
    ERROR = "error"            # Internal error
    WIDGET = "widget"          # Send interactive widget


class IntentType(str, Enum):
    """Recognized intents."""
    # Safe, read-only
    VIEW_BALANCE = "view_balance"
    VIEW_POSITIONS = "view_positions"
    VIEW_ALERTS = "view_alerts"
    VIEW_STATUS = "view_status"
    VIEW_HISTORY = "view_history"
    
    # Moderate, needs clarification
    SET_ALERT = "set_alert"
    UPDATE_ALERT = "update_alert"
    DELETE_ALERT = "delete_alert"
    
    # Dangerous, needs strong confirmation
    CLOSE_POSITION = "close_position"
    CLOSE_ALL_POSITIONS = "close_all_positions"
    CANCEL_ORDER = "cancel_order"
    EMERGENCY_STOP = "emergency_stop"
    
    # Settings
    CHANGE_SETTINGS = "change_settings"
    CHANGE_RISK_LEVEL = "change_risk_level"
    
    # Unknown
    UNKNOWN = "unknown"


@dataclass
class RouterDecision:
    """Decision from planner-router."""
    status: ActionStatus
    intent: IntentType
    title: str
    message: str
    
    # Action details
    action: str                                    # Executable action ID
    data: dict[str, Any]                           # Context data
    
    # Confirmation
    requires_confirmation: bool
    confirmation_prompt: Optional[str] = None
    idempotency_key: Optional[str] = None
    
    # Widget (for TWA)
    widget_type: Optional[str] = None              # "balance", "position", "alert", etc.
    open_widget: bool = False
    
    # Fallback
    use_legacy_handler: bool = False               # Fall back to old bot logic
    legacy_handler_name: Optional[str] = None
    
    # Metadata
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "intent": self.intent.value,
            "title": self.title,
            "message": self.message,
            "action": self.action,
            "data": self.data,
            "requires_confirmation": self.requires_confirmation,
            "confirmation_prompt": self.confirmation_prompt,
            "idempotency_key": self.idempotency_key,
            "widget_type": self.widget_type,
            "open_widget": self.open_widget,
            "use_legacy_handler": self.use_legacy_handler,
            "legacy_handler_name": self.legacy_handler_name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── Intent Detection Rules ────────────────────────────────────────────────────

INTENT_KEYWORDS = {
    IntentType.VIEW_BALANCE: [
        "balance", "баланс", "how much", "сколько", "деньги", "usdt", "btc", "средства"
    ],
    IntentType.VIEW_POSITIONS: [
        "position", "позиция", "open", "opened", "открытые", "trade", "trades"
    ],
    IntentType.VIEW_ALERTS: [
        "alert", "алерт", "оповещение", "уведомление", "notification", "trigger"
    ],
    IntentType.VIEW_STATUS: [
        "status", "статус", "health", "how are", "working", "как дела", "включен"
    ],
    IntentType.CLOSE_POSITION: [
        "close", "закрыть", "close position", "liquidate", "exit", "выход", "stop"
    ],
    IntentType.CLOSE_ALL_POSITIONS: [
        "close all", "закрыть все", "liquidate all", "exit all", "выход всё"
    ],
    IntentType.EMERGENCY_STOP: [
        "stop", "stop bot", "emergency", "стоп", "аварийно", "halt", "freeze"
    ],
    IntentType.SET_ALERT: [
        "set alert", "alert when", "notify", "алерт", "когда", "условие"
    ],
    IntentType.CHANGE_SETTINGS: [
        "setting", "config", "change", "update", "настройка", "изменить", "параметр"
    ],
}


def detect_intent(text: str) -> IntentType:
    """Detect intent from user text."""
    text_lower = text.lower().strip()
    
    # Check keywords for each intent
    for intent, keywords in INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return intent
    
    return IntentType.UNKNOWN


def estimate_risk_level(intent: IntentType, user_data: dict) -> Literal["low", "medium", "high", "critical"]:
    """Estimate risk level for intent."""
    if intent in [IntentType.EMERGENCY_STOP, IntentType.CLOSE_ALL_POSITIONS]:
        return "critical"
    
    if intent in [IntentType.CLOSE_POSITION, IntentType.CANCEL_ORDER]:
        return "high"
    
    if intent in [IntentType.SET_ALERT, IntentType.UPDATE_ALERT, IntentType.CHANGE_SETTINGS]:
        return "medium"
    
    if intent in [IntentType.VIEW_BALANCE, IntentType.VIEW_POSITIONS, IntentType.VIEW_ALERTS]:
        return "low"
    
    return "medium"


def check_user_quota(user_id: int, action: str, db_path: Optional[str] = None) -> bool:
    """Check if user is within quota for this action."""
    # TODO: implement quota checking from revenue layer
    # For now, all users can execute (will be gated by entitlements)
    return True


# ─── Main Router ──────────────────────────────────────────────────────────────

class PlannerRouter:
    """Intelligent message router."""
    
    def __init__(self, user_id: int, bot_token: Optional[str] = None):
        self.user_id = user_id
        self.bot_token = bot_token
    
    def route(self, text: str, user_data: dict, context: Optional[dict] = None) -> RouterDecision:
        """
        Route user message and return decision.
        
        Args:
            text: User message
            user_data: User profile (tier, permissions, etc.)
            context: Trading context (current balance, positions, etc.)
        
        Returns:
            RouterDecision with action, confirmation requirements, etc.
        """
        intent = detect_intent(text)
        risk_level = estimate_risk_level(intent, user_data or {})
        context = context or {}
        
        log.info(f"[ROUTE] user={self.user_id} intent={intent} risk={risk_level} text={text[:50]}")
        
        # Route by intent type
        if intent == IntentType.VIEW_BALANCE:
            return self._route_view_balance(user_data, context)
        
        elif intent == IntentType.VIEW_POSITIONS:
            return self._route_view_positions(user_data, context)
        
        elif intent == IntentType.VIEW_ALERTS:
            return self._route_view_alerts(user_data, context)
        
        elif intent == IntentType.VIEW_STATUS:
            return self._route_view_status(user_data, context)
        
        elif intent == IntentType.CLOSE_POSITION:
            return self._route_close_position(text, user_data, context)
        
        elif intent == IntentType.CLOSE_ALL_POSITIONS:
            return self._route_close_all_positions(user_data, context)
        
        elif intent == IntentType.EMERGENCY_STOP:
            return self._route_emergency_stop(user_data, context)
        
        elif intent == IntentType.SET_ALERT:
            return self._route_set_alert(text, user_data, context)
        
        else:
            # Unknown intent: fall back to legacy LLM handler
            return RouterDecision(
                status=ActionStatus.WIDGET,
                intent=IntentType.UNKNOWN,
                title="Processing...",
                message="Routing to AI assistant...",
                action="llm_fallback",
                data={"original_text": text},
                requires_confirmation=False,
                use_legacy_handler=True,
                legacy_handler_name="telegram_agent_llm_handler",
                widget_type=None,
                open_widget=False,
            )
    
    def _route_view_balance(self, user_data: dict, context: dict) -> RouterDecision:
        """Route: show balance."""
        return RouterDecision(
            status=ActionStatus.WIDGET,
            intent=IntentType.VIEW_BALANCE,
            title="Balance",
            message="Loading your balance...",
            action="get_balance",
            data={"user_id": self.user_id},
            requires_confirmation=False,
            widget_type="balance",
            open_widget=True,
        )
    
    def _route_view_positions(self, user_data: dict, context: dict) -> RouterDecision:
        """Route: show positions."""
        return RouterDecision(
            status=ActionStatus.WIDGET,
            intent=IntentType.VIEW_POSITIONS,
            title="Open Positions",
            message="Loading your positions...",
            action="get_positions",
            data={"user_id": self.user_id},
            requires_confirmation=False,
            widget_type="positions",
            open_widget=True,
        )
    
    def _route_view_alerts(self, user_data: dict, context: dict) -> RouterDecision:
        """Route: show alerts."""
        return RouterDecision(
            status=ActionStatus.WIDGET,
            intent=IntentType.VIEW_ALERTS,
            title="Alerts",
            message="Loading your alerts...",
            action="get_alerts",
            data={"user_id": self.user_id},
            requires_confirmation=False,
            widget_type="alerts",
            open_widget=True,
        )
    
    def _route_view_status(self, user_data: dict, context: dict) -> RouterDecision:
        """Route: show system status."""
        return RouterDecision(
            status=ActionStatus.WIDGET,
            intent=IntentType.VIEW_STATUS,
            title="System Status",
            message="Checking system health...",
            action="get_status",
            data={"user_id": self.user_id},
            requires_confirmation=False,
            widget_type="status",
            open_widget=False,  # Show in chat, not TWA
        )
    
    def _route_close_position(self, text: str, user_data: dict, context: dict) -> RouterDecision:
        """Route: close specific position (needs confirmation)."""
        # Try to extract symbol from text (e.g., "close BTCUSD")
        parts = text.split()
        symbol = None
        for i, part in enumerate(parts):
            if "usd" in part.lower():
                symbol = part.upper()
                break
        
        return RouterDecision(
            status=ActionStatus.CLARIFY,
            intent=IntentType.CLOSE_POSITION,
            title="Close Position",
            message=f"Are you sure you want to close {symbol or 'this position'}?",
            action="close_position",
            data={"symbol": symbol, "user_id": self.user_id},
            requires_confirmation=True,
            confirmation_prompt=f"Confirm: close {symbol or 'position'}?",
            idempotency_key=f"close_{self.user_id}_{symbol or 'unknown'}_" + str(datetime.utcnow().timestamp()),
        )
    
    def _route_close_all_positions(self, user_data: dict, context: dict) -> RouterDecision:
        """Route: close all positions (critical, needs strong confirmation)."""
        return RouterDecision(
            status=ActionStatus.CLARIFY,
            intent=IntentType.CLOSE_ALL_POSITIONS,
            title="⚠️ Close ALL Positions",
            message="This will close ALL open positions. Are you absolutely sure?",
            action="close_all_positions",
            data={"user_id": self.user_id},
            requires_confirmation=True,
            confirmation_prompt="I understand the risks. Close ALL positions.",
            idempotency_key=f"close_all_{self.user_id}_" + str(datetime.utcnow().timestamp()),
        )
    
    def _route_emergency_stop(self, user_data: dict, context: dict) -> RouterDecision:
        """Route: emergency stop (always available, instant execution)."""
        return RouterDecision(
            status=ActionStatus.EXECUTE,  # Emergency stop is immediate
            intent=IntentType.EMERGENCY_STOP,
            title="🛑 Emergency Stop",
            message="Emergency stop activated. All trading halted.",
            action="emergency_stop",
            data={"user_id": self.user_id},
            requires_confirmation=False,  # NO confirmation for safety
            idempotency_key=f"estop_{self.user_id}_" + str(datetime.utcnow().timestamp()),
        )
    
    def _route_set_alert(self, text: str, user_data: dict, context: dict) -> RouterDecision:
        """Route: set price alert."""
        # Try to parse: "alert BTCUSD at 50000" or "notify when BTC > 50k"
        # For now, clarify parameters
        return RouterDecision(
            status=ActionStatus.CLARIFY,
            intent=IntentType.SET_ALERT,
            title="Create Alert",
            message="Please provide: symbol, price, and condition (>, <, =)",
            action="set_alert",
            data={"user_id": self.user_id, "raw_text": text},
            requires_confirmation=False,
            confirmation_prompt=None,
        )
