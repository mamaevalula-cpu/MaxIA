# -*- coding: utf-8 -*-
"""
telegram_mini_app/risk_checker.py — Safety checks before execution.

Validates trading operations against:
- Account balance
- Position limits
- Risk ratios (drawdown, leverage)
- Circuit breakers
- Rate limits

All checks are server-side, no client-side trust.
"""
from __future__ import annotations

import logging
from typing import Optional, Callable, Any
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta

log = logging.getLogger("risk_checker")

# ─── Risk Limits ──────────────────────────────────────────────────────────────

@dataclass
class RiskLimits:
    """User-specific risk configuration."""
    max_position_size_usd: Decimal = Decimal("10000")
    max_leverage: Decimal = Decimal("5")
    max_daily_loss_usd: Decimal = Decimal("5000")
    max_drawdown_percent: Decimal = Decimal("20")
    max_open_positions: int = 10
    min_balance_cushion_usd: Decimal = Decimal("1000")
    rate_limit_trades_per_hour: int = 20


@dataclass
class PortfolioSnapshot:
    """Current portfolio state."""
    balance: Decimal
    unrealized_pnl: Decimal
    total_pnl_today: Decimal
    max_drawdown_today: Decimal
    num_open_positions: int
    total_position_value: Decimal
    weighted_leverage: Decimal
    positions: dict[str, dict[str, Any]]  # symbol -> {size, entry, current, unrealized_pnl}


@dataclass
class RiskCheckResult:
    """Result of risk check."""
    allowed: bool
    message: str
    warnings: list[str] = None
    actions_available: list[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.actions_available is None:
            self.actions_available = []


# ─── Risk Checker ─────────────────────────────────────────────────────────────

class RiskChecker:
    """Validate trading operations."""
    
    def __init__(self, get_portfolio: Callable[[int], PortfolioSnapshot],
                 get_limits: Callable[[int], RiskLimits] = None):
        """
        Args:
            get_portfolio: Callable(user_id) -> PortfolioSnapshot
            get_limits: Callable(user_id) -> RiskLimits (optional)
        """
        self.get_portfolio = get_portfolio
        self.get_limits = get_limits or (lambda uid: RiskLimits())
    
    async def check_open_position(
        self,
        user_id: int,
        symbol: str,
        side: str,  # "long" or "short"
        size: Decimal,
        entry_price: Optional[Decimal] = None,
    ) -> RiskCheckResult:
        """
        Check if it's safe to open a new position.
        
        Args:
            user_id: User ID
            symbol: Trading symbol (BTCUSD, ETHUSD, etc.)
            side: "long" or "short"
            size: Position size
            entry_price: Optional entry price (for limit orders)
        
        Returns:
            RiskCheckResult
        """
        portfolio = self.get_portfolio(user_id)
        limits = self.get_limits(user_id)
        warnings = []
        
        # Check 1: Position already exists?
        if symbol in portfolio.positions:
            existing = portfolio.positions[symbol]
            return RiskCheckResult(
                allowed=False,
                message=f"You already have {symbol} open ({existing['size']} @ {existing['entry']})",
                warnings=["Close existing position first or add to it"],
                actions_available=["close_position", "modify_position"]
            )
        
        # Check 2: Sufficient balance?
        position_value = size * (entry_price or Decimal("0"))  # Rough estimate
        if position_value > portfolio.balance:
            return RiskCheckResult(
                allowed=False,
                message=f"Insufficient balance. Position value: ${position_value:,.2f}, Available: ${portfolio.balance:,.2f}",
                actions_available=["deposit", "reduce_size"]
            )
        
        # Check 3: Would position exceed daily loss limit?
        estimated_max_loss = position_value * Decimal("0.1")  # Rough 10% loss estimate
        remaining_daily_budget = limits.max_daily_loss_usd + portfolio.total_pnl_today
        if remaining_daily_budget < estimated_max_loss:
            return RiskCheckResult(
                allowed=False,
                message=f"Daily loss limit reached. Remaining budget: ${remaining_daily_budget:,.2f}",
                warnings=["Wait for next trading day or increase daily loss limit"],
            )
        
        # Check 4: Would position exceed max drawdown?
        estimated_drawdown = portfolio.max_drawdown_today + (position_value / portfolio.balance * Decimal("10"))
        if estimated_drawdown > limits.max_drawdown_percent:
            return RiskCheckResult(
                allowed=False,
                message=f"Position would exceed max drawdown limit ({limits.max_drawdown_percent}%)",
                warnings=["Reduce position size or close existing positions"],
            )
        
        # Check 5: Too many open positions?
        if portfolio.num_open_positions >= limits.max_open_positions:
            return RiskCheckResult(
                allowed=False,
                message=f"Max open positions reached ({limits.max_open_positions})",
                actions_available=["close_position"]
            )
        
        # Check 6: Size too large?
        if position_value > limits.max_position_size_usd:
            return RiskCheckResult(
                allowed=False,
                message=f"Position exceeds max size (${limits.max_position_size_usd:,.2f})",
                warnings=[f"Reduce size to ${limits.max_position_size_usd:,.2f} or less"],
            )
        
        # Checks passed but warn about risks
        if portfolio.total_pnl_today < -Decimal("1000"):
            warnings.append(f"⚠️ You're down ${abs(portfolio.total_pnl_today):,.2f} today")
        
        if portfolio.max_drawdown_today > Decimal("10"):
            warnings.append(f"⚠️ Current drawdown: {portfolio.max_drawdown_today:.1f}%")
        
        if portfolio.balance < limits.min_balance_cushion_usd:
            warnings.append(f"⚠️ Balance low: ${portfolio.balance:,.2f}")
        
        return RiskCheckResult(
            allowed=True,
            message=f"✅ Safe to open {side} {size} {symbol}",
            warnings=warnings,
        )
    
    async def check_close_position(
        self,
        user_id: int,
        symbol: Optional[str] = None,
    ) -> RiskCheckResult:
        """
        Check if position(s) can be closed.
        
        Args:
            user_id: User ID
            symbol: Specific symbol, or None for all positions
        
        Returns:
            RiskCheckResult
        """
        portfolio = self.get_portfolio(user_id)
        
        if symbol:
            if symbol not in portfolio.positions:
                return RiskCheckResult(
                    allowed=False,
                    message=f"No open {symbol} position to close",
                )
            
            pos = portfolio.positions[symbol]
            return RiskCheckResult(
                allowed=True,
                message=f"✅ Close {symbol} @ {pos['current']} (P&L: ${pos['unrealized_pnl']:,.2f})",
                warnings=[],
            )
        else:
            if portfolio.num_open_positions == 0:
                return RiskCheckResult(
                    allowed=False,
                    message="No open positions to close",
                )
            
            return RiskCheckResult(
                allowed=True,
                message=f"✅ Close all {portfolio.num_open_positions} positions",
                warnings=[f"Closing all positions will reset portfolio"],
            )
    
    async def check_emergency_stop(self, user_id: int) -> RiskCheckResult:
        """
        Check emergency stop (always allowed).
        
        Returns:
            RiskCheckResult
        """
        portfolio = self.get_portfolio(user_id)
        
        if portfolio.num_open_positions == 0:
            return RiskCheckResult(
                allowed=True,
                message="✅ No open positions to stop (already safe)",
            )
        
        return RiskCheckResult(
            allowed=True,
            message=f"✅ Emergency stop: close all {portfolio.num_open_positions} positions and disable trading",
            warnings=["This cannot be undone in this request"],
        )
    
    async def check_rate_limit(
        self,
        user_id: int,
        action: str,
        window_hours: int = 1,
    ) -> RiskCheckResult:
        """
        Check rate limit for an action.
        
        Args:
            user_id: User ID
            action: Action type (e.g. "open_position", "close_position")
            window_hours: Time window to check
        
        Returns:
            RiskCheckResult
        """
        # TODO: Implement rate limit checking with database
        # For now, always allow
        return RiskCheckResult(
            allowed=True,
            message="Rate limit OK",
        )


# ─── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitBreaker:
    """Prevent cascading losses."""
    
    # Global circuit breaker thresholds
    MAX_SYSTEM_DRAWDOWN_PERCENT = Decimal("30")
    MAX_USERS_IN_LOSS_PERCENT = Decimal("50")
    MAX_CONCURRENT_OPERATIONS = 1000
    
    def __init__(self, get_system_stats: Callable[[], dict]):
        """
        Args:
            get_system_stats: Callable() -> {"drawdown": X, "users_in_loss": Y, "concurrent_ops": Z}
        """
        self.get_system_stats = get_system_stats
    
    async def check_system_health(self) -> bool:
        """Check if system is healthy enough for trading."""
        try:
            stats = self.get_system_stats()
            
            # Check drawdown
            if stats.get("drawdown", 0) > self.MAX_SYSTEM_DRAWDOWN_PERCENT:
                log.warning(f"Circuit breaker: system drawdown too high ({stats['drawdown']}%)")
                return False
            
            # Check concurrent operations
            if stats.get("concurrent_ops", 0) > self.MAX_CONCURRENT_OPERATIONS:
                log.warning(f"Circuit breaker: too many concurrent operations")
                return False
            
            return True
        except Exception as e:
            log.error(f"Circuit breaker check failed: {e}")
            return False  # Fail closed (safer)


# ─── Idempotency ──────────────────────────────────────────────────────────────

class IdempotencyStore:
    """Track executed operations by idempotency key."""
    
    def __init__(self):
        self.store: dict[str, dict[str, Any]] = {}
    
    def has(self, key: str) -> bool:
        """Check if operation was already executed."""
        if key not in self.store:
            return False
        
        # Check expiration (1 hour)
        created = self.store[key].get("created_at")
        if created:
            age = datetime.utcnow() - created
            if age > timedelta(hours=1):
                del self.store[key]
                return False
        
        return True
    
    def get(self, key: str) -> Optional[dict]:
        """Get cached result."""
        if self.has(key):
            return self.store[key].get("result")
        return None
    
    def store_result(self, key: str, result: dict) -> None:
        """Cache operation result."""
        self.store[key] = {
            "result": result,
            "created_at": datetime.utcnow(),
        }
        log.debug(f"Cached result for idempotency key: {key}")


# ─── Exports ──────────────────────────────────────────────────────────────────

__all__ = [
    "RiskLimits",
    "PortfolioSnapshot",
    "RiskCheckResult",
    "RiskChecker",
    "CircuitBreaker",
    "IdempotencyStore",
]
