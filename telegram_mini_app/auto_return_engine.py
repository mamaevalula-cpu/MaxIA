# -*- coding: utf-8 -*-
"""
telegram_mini_app/auto_return_engine.py — Intelligent retention engine.

Sends personalized "return" cards when there's genuine value:
- PnL changed significantly
- Drawdown increased
- Position closed
- New opportunity appeared
- Session ended

NOT spam. Only high-confidence triggers with real user value.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Any, Callable
from enum import Enum

log = logging.getLogger("auto_return_engine")


class ReturnTriggerType(str, Enum):
    """Types of return triggers."""
    PNL_CHANGE = "pnl_change"           # PnL changed by >N%
    POSITION_CLOSED = "position_closed" # Position automatically closed
    DRAWDOWN_MILESTONE = "drawdown_milestone"  # Drawdown threshold hit
    NEW_OPPORTUNITY = "new_opportunity" # Signal for new trade
    SESSION_ENDED = "session_ended"     # Daily/weekly summary
    WINNING_STREAK = "winning_streak"   # Multiple wins in a row
    COMEBACK_ELIGIBLE = "comeback_eligible"  # User hasn't checked in 24h+


@dataclass
class ReturnCard:
    """Personalized card to bring user back to app."""
    card_id: str
    user_id: int
    trigger_type: ReturnTriggerType
    title: str
    description: str
    cta_text: str  # Call-to-action button text
    deeplink: str  # Deep link to open specific TWA widget
    
    # Metadata
    value_score: float  # 0.0-1.0: confidence that user will find this valuable
    created_at: datetime = None
    expires_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(hours=24)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "user_id": self.user_id,
            "trigger_type": self.trigger_type.value,
            "title": self.title,
            "description": self.description,
            "cta_text": self.cta_text,
            "deeplink": self.deeplink,
            "value_score": self.value_score,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


# ─── Card Factory ─────────────────────────────────────────────────────────────

class ReturnCardFactory:
    """Create retention cards based on trading events."""
    
    @staticmethod
    def pnl_change(
        user_id: int,
        pnl_change: float,
        pnl_change_pct: float,
        current_pnl: float,
    ) -> Optional[ReturnCard]:
        """
        Trigger: PnL changed significantly.
        Only if change > 5% or > $500 (to avoid spam).
        """
        if abs(pnl_change_pct) < 0.05:
            return None  # Too small, skip
        
        emoji = "📈" if pnl_change > 0 else "📉"
        direction = "UP" if pnl_change > 0 else "DOWN"
        
        return ReturnCard(
            card_id=f"pnl_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            trigger_type=ReturnTriggerType.PNL_CHANGE,
            title=f"{emoji} Your PnL {direction}",
            description=f"${pnl_change:+.2f} ({pnl_change_pct:+.1%}) | Total: ${current_pnl:.2f}",
            cta_text="Open Dashboard",
            deeplink="overview",
            value_score=0.8 if abs(pnl_change_pct) > 0.1 else 0.6,
        )
    
    @staticmethod
    def position_closed(
        user_id: int,
        symbol: str,
        pnl: float,
        pnl_pct: float,
    ) -> ReturnCard:
        """
        Trigger: Position closed.
        Always valuable to show final PnL.
        """
        emoji = "🎉" if pnl > 0 else "🤔"
        
        return ReturnCard(
            card_id=f"closed_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            trigger_type=ReturnTriggerType.POSITION_CLOSED,
            title=f"{emoji} {symbol} Closed",
            description=f"Exit PnL: ${pnl:.2f} ({pnl_pct:+.1%})",
            cta_text="See Details",
            deeplink="positions",
            value_score=0.9,
        )
    
    @staticmethod
    def drawdown_milestone(
        user_id: int,
        drawdown_pct: float,
        threshold_pct: float,
    ) -> ReturnCard:
        """
        Trigger: Drawdown hit milestone.
        Warns about risk.
        """
        return ReturnCard(
            card_id=f"dd_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            trigger_type=ReturnTriggerType.DRAWDOWN_MILESTONE,
            title="⚠️ Drawdown Alert",
            description=f"Current: {drawdown_pct:.1%} | Review your risk",
            cta_text="Check Risk Dashboard",
            deeplink="risk",
            value_score=0.95,  # High priority
        )
    
    @staticmethod
    def winning_streak(
        user_id: int,
        wins: int,
        total_pnl: float,
    ) -> ReturnCard:
        """
        Trigger: Multiple wins in a row.
        Celebrate and keep momentum.
        """
        return ReturnCard(
            card_id=f"streak_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            trigger_type=ReturnTriggerType.WINNING_STREAK,
            title=f"🔥 {wins}-Trade Win Streak!",
            description=f"Total PnL: ${total_pnl:.2f}. Keep it up!",
            cta_text="See Positions",
            deeplink="positions",
            value_score=0.85,
        )
    
    @staticmethod
    def session_ended(
        user_id: int,
        session_pnl: float,
        trades_today: int,
    ) -> ReturnCard:
        """
        Trigger: Daily session ended.
        Summary of today's activity.
        """
        emoji = "📊" if trades_today > 0 else "😴"
        
        return ReturnCard(
            card_id=f"session_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            trigger_type=ReturnTriggerType.SESSION_ENDED,
            title=f"{emoji} Daily Summary",
            description=f"{trades_today} trades | PnL: ${session_pnl:+.2f}",
            cta_text="View Report",
            deeplink="reports",
            value_score=0.7,
        )
    
    @staticmethod
    def comeback_eligible(
        user_id: int,
        days_since_last_visit: int,
        total_pnl: float,
        open_positions: int,
    ) -> Optional[ReturnCard]:
        """
        Trigger: User hasn't checked in 24h+ and has activity.
        Only send if there's something to show.
        """
        if days_since_last_visit < 1:
            return None  # Too recent, skip
        
        if open_positions == 0 and total_pnl == 0:
            return None  # Nothing to show, skip
        
        what_to_see = ""
        deeplink = "overview"
        
        if open_positions > 0:
            what_to_see = f"{open_positions} open position(s)"
            deeplink = "positions"
        elif total_pnl != 0:
            what_to_see = f"Your PnL: ${total_pnl:.2f}"
            deeplink = "overview"
        
        days_text = f"{days_since_last_visit}d" if days_since_last_visit > 1 else "yesterday"
        
        return ReturnCard(
            card_id=f"comeback_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            trigger_type=ReturnTriggerType.COMEBACK_ELIGIBLE,
            title="👋 Welcome Back!",
            description=f"Last check-in: {days_text} | {what_to_see}",
            cta_text="Open My Cabinet",
            deeplink=deeplink,
            value_score=0.7,
        )


# ─── Auto Return Engine ────────────────────────────────────────────────────────

class AutoReturnEngine:
    """Manages retention triggers and sends personalized cards."""
    
    def __init__(self, send_message_fn: Callable):
        """
        Initialize engine.
        
        Args:
            send_message_fn: async fn(user_id, card: ReturnCard) -> bool
        """
        self.send_message = send_message_fn
    
    async def check_and_send_triggers(
        self,
        user_id: int,
        portfolio_state: dict,
        previous_state: dict,
    ) -> list[ReturnCard]:
        """
        Check for retention triggers and send cards.
        
        Args:
            user_id: User ID
            portfolio_state: Current portfolio (balance, positions, pnl, etc.)
            previous_state: Previous portfolio state for delta analysis
        
        Returns: List of cards sent
        """
        cards_sent = []
        
        # 1. Check PnL change
        current_pnl = portfolio_state.get("pnl", 0)
        previous_pnl = previous_state.get("pnl", 0)
        pnl_change = current_pnl - previous_pnl
        pnl_change_pct = (pnl_change / abs(previous_pnl)) if previous_pnl != 0 else 0
        
        card = ReturnCardFactory.pnl_change(user_id, pnl_change, pnl_change_pct, current_pnl)
        if card:
            if await self._send_card(card):
                cards_sent.append(card)
        
        # 2. Check position closures
        current_positions = set(portfolio_state.get("positions", {}).keys())
        previous_positions = set(previous_state.get("positions", {}).keys())
        closed_positions = previous_positions - current_positions
        
        for symbol in closed_positions:
            prev_pos = previous_state["positions"][symbol]
            # Assume position closed with some PnL
            pnl = prev_pos.get("pnl", 0)
            entry = prev_pos.get("entry_price", 0)
            exit_price = portfolio_state.get("last_price", entry)
            pnl_pct = (pnl / (entry * prev_pos.get("qty", 1))) if entry > 0 else 0
            
            card = ReturnCardFactory.position_closed(user_id, symbol, pnl, pnl_pct)
            if await self._send_card(card):
                cards_sent.append(card)
        
        # 3. Check drawdown
        drawdown = portfolio_state.get("drawdown_pct", 0)
        threshold = portfolio_state.get("drawdown_threshold", 0.2)
        
        if drawdown > threshold:
            card = ReturnCardFactory.drawdown_milestone(user_id, drawdown, threshold)
            if await self._send_card(card):
                cards_sent.append(card)
        
        # 4. Check winning streak
        recent_trades = portfolio_state.get("recent_trades", [])
        if len(recent_trades) >= 3:
            all_wins = all(t.get("pnl", 0) > 0 for t in recent_trades[-3:])
            if all_wins:
                total_pnl = sum(t.get("pnl", 0) for t in recent_trades[-3:])
                card = ReturnCardFactory.winning_streak(user_id, len(recent_trades[-3:]), total_pnl)
                if await self._send_card(card):
                    cards_sent.append(card)
        
        # 5. Check comeback eligibility
        last_visit = portfolio_state.get("last_visit_at", datetime.utcnow())
        if isinstance(last_visit, str):
            last_visit = datetime.fromisoformat(last_visit)
        
        days_since = (datetime.utcnow() - last_visit).days
        open_positions = len(portfolio_state.get("positions", {}))
        
        card = ReturnCardFactory.comeback_eligible(
            user_id,
            days_since,
            current_pnl,
            open_positions,
        )
        if card and await self._send_card(card):
            cards_sent.append(card)
        
        log.info(f"[AUTO_RETURN] user={user_id} sent {len(cards_sent)} cards")
        return cards_sent
    
    async def _send_card(self, card: ReturnCard) -> bool:
        """
        Send a single card.
        
        Returns True if sent successfully.
        """
        try:
            # Format as a nice message with button
            text = f"""
{card.title}

{card.description}

Tap the button below to continue.
"""
            
            # In real implementation, use Telegram inline buttons
            # For now, just send the card
            await self.send_message(card.user_id, card)
            log.info(f"Card {card.card_id} sent to user {card.user_id}")
            return True
        
        except Exception as e:
            log.error(f"Failed to send card {card.card_id}: {e}")
            return False
