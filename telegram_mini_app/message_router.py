# -*- coding: utf-8 -*-
"""
telegram_mini_app/message_router.py — Intelligent message routing for text/voice.

Routes user messages (text or transcribed voice) to appropriate handlers:
- Trading intent → risk_checker → execute or deny
- Information request → existing bot logic (fallback)
- Alert management → alert_system
- Premium purchase → revenue.py

Design:
1. Parse intent from user message
2. Validate user authorization (invite-only)
3. Check risk & preconditions
4. Execute or return clarification
5. Fallback to old bot if uncertain

All responses follow unified TWAResponse schema.
"""
from __future__ import annotations

import logging
import json
import re
from typing import Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

log = logging.getLogger("message_router")

# ─── Intent Types ─────────────────────────────────────────────────────────────

class IntentType(str, Enum):
    """Message intent classification."""
    TRADE_LONG = "trade_long"           # "buy 1 BTC"
    TRADE_SHORT = "trade_short"         # "short 5 ETH"
    CLOSE_POSITION = "close_position"   # "close my BTC"
    SET_ALERT = "set_alert"             # "alert me at 40k"
    CANCEL_ALERT = "cancel_alert"       # "remove alert"
    GET_STATUS = "get_status"           # "what's my balance"
    GET_PNL = "get_pnl"                # "show PnL"
    GET_POSITIONS = "get_positions"     # "open positions"
    EMERGENCY_STOP = "emergency_stop"   # "stop everything"
    ASK_AI = "ask_ai"                   # "what's bitcoin"
    UNCLEAR = "unclear"                 # couldn't determine


# ─── Intent Parser ────────────────────────────────────────────────────────────

class IntentParser:
    """Parse user message into intent + parameters."""
    
    def __init__(self):
        self.trade_patterns = {
            "trade_long": [
                r"(?:buy|long|go long|bullish).*?(\d+\.?\d*)\s*(\w+)",
                r"(\d+\.?\d*)\s*(\w+).*?(?:buy|long)",
            ],
            "trade_short": [
                r"(?:short|sell short|bearish).*?(\d+\.?\d*)\s*(\w+)",
                r"(\d+\.?\d*)\s*(\w+).*?(?:short|sell short)",
            ],
            "close_position": [
                r"(?:close|exit|liquidate).*?(?:my\s+)?(\w+)",
                r"(?:close|exit|liquidate)\s+(?:all|everything)",
            ],
            "set_alert": [
                r"(?:alert|notify|remind).*?(?:at|if|when).*?(\d+\.?\d*)",
                r"alert.*?(\w+).*?(\d+\.?\d*)",
            ],
            "emergency_stop": [
                r"(?:emergency|stop|halt|kill|panic)",
                r"(?:close all|exit all|liquidate all)",
            ],
        }
    
    def parse(self, message: str) -> tuple[IntentType, dict[str, Any]]:
        """
        Parse message into intent + parameters.
        
        Returns:
            (intent, params) where params includes extracted values
        """
        msg_lower = message.lower().strip()
        
        # Check emergency stop first (always highest priority)
        if self._match_patterns(msg_lower, self.trade_patterns["emergency_stop"]):
            return IntentType.EMERGENCY_STOP, {"message": message}
        
        # Check trade patterns
        for intent_str, patterns in self.trade_patterns.items():
            if intent_str == "emergency_stop":
                continue
            
            match = self._find_match(msg_lower, patterns)
            if match:
                intent = IntentType(intent_str)
                params = self._extract_params(intent, match, message)
                return intent, params
        
        # Check status/info requests
        if any(w in msg_lower for w in ["balance", "portfolio", "positions", "risk"]):
            return IntentType.GET_STATUS, {"query": message}
        
        if any(w in msg_lower for w in ["pnl", "profit", "loss", "earnings"]):
            return IntentType.GET_PNL, {"query": message}
        
        if any(w in msg_lower for w in ["open", "positions", "holdings"]):
            return IntentType.GET_POSITIONS, {"query": message}
        
        # Default: ask AI or fallback to old bot
        return IntentType.UNCLEAR, {"message": message}
    
    def _match_patterns(self, text: str, patterns: list[str]) -> bool:
        """Check if any pattern matches."""
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)
    
    def _find_match(self, text: str, patterns: list[str]):
        """Find first matching pattern and return match object."""
        for p in patterns:
            m = re.search(p, text, re.IGNORECASE)
            if m:
                return m
        return None
    
    def _extract_params(self, intent: IntentType, match, original_msg: str) -> dict[str, Any]:
        """Extract parameters from regex match."""
        params = {"message": original_msg, "confidence": 0.8}
        
        if intent in (IntentType.TRADE_LONG, IntentType.TRADE_SHORT):
            groups = match.groups()
            if len(groups) >= 2:
                try:
                    params["size"] = float(groups[0])
                    params["symbol"] = groups[1].upper()
                    params["confidence"] = 0.9
                except (ValueError, IndexError):
                    pass
        
        elif intent == IntentType.CLOSE_POSITION:
            try:
                symbol = match.group(1).upper() if match.lastindex >= 1 else None
                if symbol:
                    params["symbol"] = symbol
                    params["confidence"] = 0.95
                else:
                    params["close_all"] = True
                    params["confidence"] = 0.9
            except (IndexError, AttributeError):
                params["close_all"] = True
        
        elif intent == IntentType.SET_ALERT:
            groups = match.groups()
            if len(groups) >= 1:
                try:
                    params["price"] = float(groups[0])
                    if len(groups) > 1:
                        params["symbol"] = groups[1].upper()
                    params["confidence"] = 0.85
                except ValueError:
                    pass
        
        return params


# ─── Message Router ───────────────────────────────────────────────────────────

@dataclass
class RoutedMessage:
    """Result of message routing."""
    intent: IntentType
    params: dict[str, Any]
    confidence: float
    user_id: int
    is_authorized: bool
    requires_confirmation: bool = False
    requires_premium: bool = False
    error: Optional[str] = None


class MessageRouter:
    """Route messages to appropriate handlers."""
    
    def __init__(self, get_user_auth: Callable[[int], bool], 
                 get_user_premium: Optional[Callable[[int], bool]] = None):
        """
        Args:
            get_user_auth: Callable(user_id) -> is_authorized
            get_user_premium: Callable(user_id) -> is_premium
        """
        self.parser = IntentParser()
        self.get_user_auth = get_user_auth
        self.get_user_premium = get_user_premium or (lambda uid: False)
    
    async def route(self, user_id: int, message: str, 
                    is_voice: bool = False) -> RoutedMessage:
        """
        Route message to handler.
        
        Args:
            user_id: Telegram user ID
            message: Text message or transcribed voice
            is_voice: True if from voice message
        
        Returns:
            RoutedMessage with intent, params, and requirements
        """
        # Check authorization (invite-only system)
        is_auth = self.get_user_auth(user_id)
        if not is_auth:
            return RoutedMessage(
                intent=IntentType.UNCLEAR,
                params={"message": message},
                confidence=0.0,
                user_id=user_id,
                is_authorized=False,
                error="User not authorized (invite-only)"
            )
        
        # Parse intent
        intent, params = self.parser.parse(message)
        params["is_voice"] = is_voice
        
        # Determine if requires confirmation
        requires_confirmation = intent in (
            IntentType.TRADE_LONG, IntentType.TRADE_SHORT,
            IntentType.CLOSE_POSITION, IntentType.EMERGENCY_STOP
        )
        
        # Determine if requires premium
        requires_premium = False  # TODO: Add premium feature gating
        
        # Get confidence from params
        confidence = params.pop("confidence", 0.7)
        
        # If low confidence on trading, escalate to clarification
        if confidence < 0.7 and intent in (
            IntentType.TRADE_LONG, IntentType.TRADE_SHORT, 
            IntentType.CLOSE_POSITION
        ):
            intent = IntentType.UNCLEAR
        
        return RoutedMessage(
            intent=intent,
            params=params,
            confidence=confidence,
            user_id=user_id,
            is_authorized=True,
            requires_confirmation=requires_confirmation,
            requires_premium=requires_premium,
        )


# ─── Response Builder ──────────────────────────────────────────────────────────

class ResponseBuilder:
    """Build TWA responses from routed messages."""
    
    @staticmethod
    def execute_response(intent: IntentType, data: dict, 
                        idempotency_key: str = "") -> dict:
        """Response for ready-to-execute actions."""
        return {
            "status": "execute",
            "title": ResponseBuilder._intent_title(intent),
            "message": ResponseBuilder._intent_message(intent, data),
            "widgetType": "confirm" if data.get("requires_confirmation") else "none",
            "data": data,
            "action": "execute",
            "requiresConfirmation": data.get("requires_confirmation", False),
            "idempotencyKey": idempotency_key,
            "entitlementRequired": data.get("requires_premium", False),
        }
    
    @staticmethod
    def clarify_response(intent: IntentType, data: dict) -> dict:
        """Response when need more info."""
        return {
            "status": "clarify",
            "title": f"Need Details - {ResponseBuilder._intent_title(intent)}",
            "message": ResponseBuilder._clarify_message(intent, data),
            "widgetType": "none",
            "data": data,
            "action": "clarify",
            "requiresConfirmation": False,
        }
    
    @staticmethod
    def deny_response(reason: str, premium_required: bool = False) -> dict:
        """Response when action not allowed."""
        return {
            "status": "deny",
            "title": "Action Not Allowed",
            "message": reason,
            "widgetType": "premium" if premium_required else "none",
            "data": {"reason": reason},
            "action": "cancel",
            "requiresConfirmation": False,
            "entitlementRequired": premium_required,
        }
    
    @staticmethod
    def error_response(error: str) -> dict:
        """Response for system errors."""
        return {
            "status": "error",
            "title": "System Error",
            "message": error,
            "widgetType": "none",
            "data": {"error": error},
            "action": "retry",
        }
    
    @staticmethod
    def widget_response(widget_type: str, data: dict, title: str = "") -> dict:
        """Response with interactive widget."""
        return {
            "status": "widget",
            "title": title or widget_type.capitalize(),
            "message": f"Showing {widget_type}...",
            "widgetType": widget_type,
            "data": data,
            "action": "none",
        }
    
    @staticmethod
    def _intent_title(intent: IntentType) -> str:
        """Get human title for intent."""
        titles = {
            IntentType.TRADE_LONG: "Open Long Position",
            IntentType.TRADE_SHORT: "Open Short Position",
            IntentType.CLOSE_POSITION: "Close Position",
            IntentType.SET_ALERT: "Set Price Alert",
            IntentType.CANCEL_ALERT: "Cancel Alert",
            IntentType.EMERGENCY_STOP: "Emergency Stop",
            IntentType.GET_STATUS: "Portfolio Status",
            IntentType.GET_PNL: "Today's P&L",
            IntentType.GET_POSITIONS: "Open Positions",
            IntentType.ASK_AI: "Ask AI",
        }
        return titles.get(intent, "Unknown Action")
    
    @staticmethod
    def _intent_message(intent: IntentType, data: dict) -> str:
        """Get human message for intent."""
        if intent == IntentType.TRADE_LONG:
            return f"Buy {data.get('size', '?')} {data.get('symbol', '?')} at market"
        elif intent == IntentType.TRADE_SHORT:
            return f"Short {data.get('size', '?')} {data.get('symbol', '?')} at market"
        elif intent == IntentType.CLOSE_POSITION:
            symbol = data.get('symbol')
            if symbol:
                return f"Close your {symbol} position (P&L: {data.get('pnl', 'calculating...')})"
            return "Close all positions"
        elif intent == IntentType.EMERGENCY_STOP:
            return "Trigger emergency stop - close all positions and disable trading"
        return "Executing..."
    
    @staticmethod
    def _clarify_message(intent: IntentType, data: dict) -> str:
        """Get clarification message."""
        if intent in (IntentType.TRADE_LONG, IntentType.TRADE_SHORT):
            return f"Got it! But I need the size and symbol. Message like: 'buy 5 ETH' or 'short 0.5 BTC'"
        return f"Could you clarify? {data.get('message', '')}"


# ─── Exports ──────────────────────────────────────────────────────────────────

__all__ = [
    "IntentType",
    "IntentParser",
    "MessageRouter",
    "ResponseBuilder",
    "RoutedMessage",
]
