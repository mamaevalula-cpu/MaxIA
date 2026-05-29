# -*- coding: utf-8 -*-
"""
telegram_mini_app/alert_handler.py — Real-time alert system for critical trading events.

Features:
- Telegram notifications with inline buttons
- Quick actions (close position, ignore, emergency stop)
- Emergency stop always available
- Optional TWA deep link
"""
from __future__ import annotations

import logging
import json
from typing import Optional, Callable, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

log = logging.getLogger("alert_handler")


class AlertSeverity(str, Enum):
    """Alert severity level."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertType(str, Enum):
    """Types of trading alerts."""
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    LIQUIDATION_RISK = "liquidation_risk"
    DRAWDOWN_WARNING = "drawdown_warning"
    PNL_MILESTONE = "pnl_milestone"
    MARGIN_LOW = "margin_low"
    PRICE_ALERT = "price_alert"
    ORDER_FILLED = "order_filled"
    SYSTEM_ERROR = "system_error"
    MANUAL_STOP = "manual_stop"


@dataclass
class TradingAlert:
    """Critical trading event alert."""
    alert_id: str
    user_id: int
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    
    # Action context
    action_data: dict[str, Any]  # {"symbol": "BTCUSD", "margin_ratio": 0.45, ...}
    
    # Quick actions available
    available_actions: list[str]  # ["close_position", "ignore", "emergency_stop"]
    
    # Deep link to TWA
    twa_deeplink: Optional[str] = None
    twa_widget_type: Optional[str] = None  # "position", "risk", "chart", etc.
    
    # Metadata
    created_at: datetime = None
    expires_at: Optional[datetime] = None  # TTL for alert relevance
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "user_id": self.user_id,
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "action_data": self.action_data,
            "available_actions": self.available_actions,
            "twa_deeplink": self.twa_deeplink,
            "twa_widget_type": self.twa_widget_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


# ─── Alert Factory ────────────────────────────────────────────────────────────

class AlertFactory:
    """Create pre-formatted trading alerts."""
    
    @staticmethod
    def liquidation_risk(
        user_id: int,
        symbol: str,
        margin_ratio: float,
        current_price: float,
        liquidation_price: float,
    ) -> TradingAlert:
        """Alert: position approaching liquidation."""
        from datetime import timedelta
        import uuid
        
        return TradingAlert(
            alert_id=f"liq_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            alert_type=AlertType.LIQUIDATION_RISK,
            severity=AlertSeverity.CRITICAL if margin_ratio < 0.3 else AlertSeverity.WARNING,
            title="⚠️ Liquidation Risk",
            message=f"{symbol} margin: {margin_ratio:.1%}\nLiquidation at ${liquidation_price}",
            action_data={
                "symbol": symbol,
                "margin_ratio": margin_ratio,
                "current_price": current_price,
                "liquidation_price": liquidation_price,
            },
            available_actions=["close_position", "ignore", "emergency_stop"],
            twa_deeplink=f"position/{symbol}",
            twa_widget_type="position",
            expires_at=datetime.utcnow() + timedelta(minutes=30),
        )
    
    @staticmethod
    def drawdown_warning(
        user_id: int,
        drawdown_pct: float,
        max_drawdown_allowed: float,
    ) -> TradingAlert:
        """Alert: portfolio drawdown exceeded threshold."""
        from datetime import timedelta
        import uuid
        
        return TradingAlert(
            alert_id=f"dd_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            alert_type=AlertType.DRAWDOWN_WARNING,
            severity=AlertSeverity.WARNING,
            title="📉 Drawdown Warning",
            message=f"Current: {drawdown_pct:.1%} | Limit: {max_drawdown_allowed:.1%}",
            action_data={
                "drawdown_pct": drawdown_pct,
                "max_drawdown_allowed": max_drawdown_allowed,
            },
            available_actions=["close_all_positions", "ignore", "emergency_stop"],
            twa_deeplink="risk",
            twa_widget_type="risk",
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )
    
    @staticmethod
    def position_opened(
        user_id: int,
        symbol: str,
        entry_price: float,
        quantity: float,
        leverage: int,
    ) -> TradingAlert:
        """Alert: position opened."""
        from datetime import timedelta
        import uuid
        
        return TradingAlert(
            alert_id=f"open_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            alert_type=AlertType.POSITION_OPENED,
            severity=AlertSeverity.INFO,
            title="📈 Position Opened",
            message=f"{symbol} @ ${entry_price} | {quantity} qty | {leverage}x",
            action_data={
                "symbol": symbol,
                "entry_price": entry_price,
                "quantity": quantity,
                "leverage": leverage,
            },
            available_actions=["ignore"],
            twa_deeplink=f"position/{symbol}",
            twa_widget_type="position",
        )
    
    @staticmethod
    def position_closed(
        user_id: int,
        symbol: str,
        exit_price: float,
        pnl: float,
        pnl_pct: float,
    ) -> TradingAlert:
        """Alert: position closed."""
        from datetime import timedelta
        import uuid
        
        emoji = "🎉" if pnl > 0 else "💔"
        return TradingAlert(
            alert_id=f"close_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            alert_type=AlertType.POSITION_CLOSED,
            severity=AlertSeverity.INFO,
            title=f"{emoji} Position Closed",
            message=f"{symbol} @ ${exit_price} | PnL: ${pnl:.2f} ({pnl_pct:+.1%})",
            action_data={
                "symbol": symbol,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            },
            available_actions=["ignore"],
            twa_deeplink="overview",
            twa_widget_type="balance",
        )
    
    @staticmethod
    def system_error(
        user_id: int,
        error_message: str,
    ) -> TradingAlert:
        """Alert: system error occurred."""
        from datetime import timedelta
        import uuid
        
        return TradingAlert(
            alert_id=f"err_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            alert_type=AlertType.SYSTEM_ERROR,
            severity=AlertSeverity.EMERGENCY,
            title="🚨 System Error",
            message=error_message,
            action_data={"error": error_message},
            available_actions=["emergency_stop", "ignore"],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        )


# ─── Alert Handler ────────────────────────────────────────────────────────────

class AlertHandler:
    """Handle trading alerts and send via Telegram."""
    
    def __init__(self, send_message_fn: Callable, send_alert_fn: Optional[Callable] = None):
        """
        Initialize alert handler.
        
        Args:
            send_message_fn: async fn(user_id, text, reply_markup)
            send_alert_fn: async fn(alert: TradingAlert) - optional TWA integration
        """
        self.send_message = send_message_fn
        self.send_alert = send_alert_fn
    
    async def dispatch_alert(self, alert: TradingAlert) -> bool:
        """
        Send alert to user via Telegram.
        
        Returns True if successfully sent, False otherwise.
        """
        try:
            # Check if alert has expired
            if alert.expires_at and datetime.utcnow() > alert.expires_at:
                log.warning(f"Alert {alert.alert_id} expired, skipping")
                return False
            
            # Format Telegram message with emoji
            emoji_map = {
                AlertSeverity.INFO: "ℹ️",
                AlertSeverity.WARNING: "⚠️",
                AlertSeverity.CRITICAL: "🚨",
                AlertSeverity.EMERGENCY: "🛑",
            }
            
            emoji = emoji_map.get(alert.severity, "")
            text = f"{emoji} {alert.title}\n\n{alert.message}"
            
            # Build inline buttons
            buttons = []
            
            if "close_position" in alert.available_actions:
                buttons.append({
                    "text": "Close Position",
                    "callback_data": f"close_pos_{alert.alert_id}",
                })
            
            if "close_all_positions" in alert.available_actions:
                buttons.append({
                    "text": "Close All",
                    "callback_data": f"close_all_{alert.alert_id}",
                })
            
            if "emergency_stop" in alert.available_actions:
                buttons.append({
                    "text": "🛑 Emergency Stop",
                    "callback_data": f"estop_{alert.alert_id}",
                })
            
            if alert.twa_deeplink:
                buttons.append({
                    "text": "📱 Open App",
                    "url": f"https://t.me/YOUR_BOT_NAME/app?startapp={alert.twa_deeplink}",
                })
            
            if "ignore" in alert.available_actions:
                buttons.append({
                    "text": "Dismiss",
                    "callback_data": f"dismiss_{alert.alert_id}",
                })
            
            # Format inline keyboard
            reply_markup = None
            if buttons:
                reply_markup = {
                    "inline_keyboard": [
                        [buttons[i]] if i % 2 == 0 else [buttons[i-1], buttons[i]]
                        for i in range(len(buttons))
                    ]
                }
            
            # Send via Telegram
            await self.send_message(alert.user_id, text, reply_markup)
            log.info(f"Alert {alert.alert_id} sent to user {alert.user_id}")
            
            # Optional: also dispatch to TWA backend
            if self.send_alert:
                await self.send_alert(alert)
            
            return True
        
        except Exception as e:
            log.error(f"Failed to send alert {alert.alert_id}: {e}", exc_info=True)
            return False
    
    async def handle_alert_action(
        self,
        alert_id: str,
        action: str,
        user_id: int,
        execute_fn: Callable,
    ) -> bool:
        """
        Handle user action on alert (close position, emergency stop, etc.).
        
        Args:
            alert_id: ID of the alert
            action: "close_position", "close_all_positions", "emergency_stop", etc.
            user_id: User ID
            execute_fn: async fn(action, alert_id, user_id) -> bool
        
        Returns True if action executed successfully.
        """
        try:
            result = await execute_fn(action, alert_id, user_id)
            if result:
                log.info(f"Alert action {action} completed for user {user_id}")
            return result
        except Exception as e:
            log.error(f"Failed to execute alert action {action}: {e}", exc_info=True)
            return False
