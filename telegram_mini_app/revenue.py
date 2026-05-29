# -*- coding: utf-8 -*-
"""
telegram_mini_app/revenue.py — Revenue layer, premium entitlements, auto-return engine.

Features:
- Free/Basic/Pro tiers
- Stars-based digital goods
- Premium feature gating
- Auto-return triggers (PnL change, drawdown, closed position, etc.)
- Retention digest + alert subscriptions
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional, Callable
from enum import Enum

log = logging.getLogger("revenue")

# ─── Premium Tiers ────────────────────────────────────────────────────────────

class PremiumTier(str, Enum):
    FREE = "free"
    BASIC = "basic"  # ~10 USD/mo
    PRO = "pro"      # ~30 USD/mo


# ─── Feature Catalog ──────────────────────────────────────────────────────────

PREMIUM_FEATURES = {
    # Free tier
    "positions_view": {"tier": PremiumTier.FREE, "stars": 0, "desc": "View open positions"},
    "alerts_3": {"tier": PremiumTier.FREE, "stars": 0, "desc": "Up to 3 price alerts"},
    
    # Basic tier (~100 stars ≈ $2)
    "alerts_20": {"tier": PremiumTier.BASIC, "stars": 50, "desc": "Up to 20 alerts"},
    "daily_digest": {"tier": PremiumTier.BASIC, "stars": 50, "desc": "Daily PnL digest"},
    "risk_dashboard": {"tier": PremiumTier.BASIC, "stars": 40, "desc": "Risk dashboard"},
    
    # Pro tier (~300 stars ≈ $6)
    "alerts_unlimited": {"tier": PremiumTier.PRO, "stars": 150, "desc": "Unlimited alerts"},
    "advanced_analytics": {"tier": PremiumTier.PRO, "stars": 100, "desc": "Advanced analytics"},
    "telegram_reports": {"tier": PremiumTier.PRO, "stars": 100, "desc": "Weekly PDF reports"},
    "api_access": {"tier": PremiumTier.PRO, "stars": 200, "desc": "REST API access"},
    
    # Pay-as-you-go
    "custom_report": {"tier": None, "stars": 25, "desc": "Custom PDF report (one-time)"},
    "alert_pack_10": {"tier": None, "stars": 15, "desc": "10 additional alerts (one-time)"},
}

SUBSCRIPTION_PRODUCTS = {
    "basic_month": {"tier": PremiumTier.BASIC, "stars": 100, "duration_days": 30},
    "pro_month": {"tier": PremiumTier.PRO, "stars": 250, "duration_days": 30},
    "pro_quarter": {"tier": PremiumTier.PRO, "stars": 650, "duration_days": 90},  # 3% discount
    "pro_year": {"tier": PremiumTier.PRO, "stars": 2400, "duration_days": 365},    # 20% discount
}

# ─── Auto-Return Triggers ─────────────────────────────────────────────────────

@dataclass
class ReturnTrigger:
    """Retention trigger that prompts user to re-engage."""
    trigger_type: str  # "pnl_change", "position_closed", "new_opportunity", "session_ended"
    user_id: int
    data: dict  # {"pnl_change": 150.50, "symbol": "BTCUSD", ...}
    created_at: datetime = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()


# ─── Revenue Manager ──────────────────────────────────────────────────────────

class RevenueManager:
    """
    Manages premium features, subscriptions, stars, and retention.
    
    DB schema:
    - premium_tiers (user_id, tier, expires_at)
    - star_transactions (user_id, product_id, amount, direction, status)
    - feature_grants (user_id, feature_id, granted_until)
    - return_triggers (user_id, trigger_type, data, created_at)
    """
    
    def __init__(self, db_path: str = "/root/my_personal_ai/data/premium.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize premium database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS premium_tiers (
                    user_id INTEGER PRIMARY KEY,
                    tier TEXT DEFAULT 'free',
                    expires_at TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS star_transactions (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    product_id TEXT,
                    amount INTEGER,
                    direction TEXT,  -- 'in' or 'out'
                    status TEXT DEFAULT 'pending',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES premium_tiers(user_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feature_grants (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    feature_id TEXT,
                    granted_until TEXT,
                    granted_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES premium_tiers(user_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS return_triggers (
                    id TEXT PRIMARY KEY,
                    user_id INTEGER,
                    trigger_type TEXT,
                    data TEXT,  -- JSON
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES premium_tiers(user_id)
                )
            """)
            
            conn.commit()
    
    def get_user_tier(self, user_id: int) -> PremiumTier:
        """Get current tier. Checks expiration."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT tier, expires_at FROM premium_tiers WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            
            if not row:
                return PremiumTier.FREE
            
            tier_str, expires_at = row
            if expires_at and datetime.fromisoformat(expires_at) < datetime.utcnow():
                # Subscription expired
                self._downgrade_to_free(user_id)
                return PremiumTier.FREE
            
            return PremiumTier(tier_str)
    
    def has_feature(self, user_id: int, feature_id: str) -> bool:
        """Check if user has access to feature."""
        tier = self.get_user_tier(user_id)
        
        # Check tier access
        feature_info = PREMIUM_FEATURES.get(feature_id)
        if not feature_info:
            return False
        
        feature_tier = feature_info.get("tier")
        if feature_tier and feature_tier.value <= tier.value:
            return True
        
        # Check explicit grant (one-time purchase)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT granted_until FROM feature_grants WHERE user_id = ? AND feature_id = ?",
                (user_id, feature_id)
            ).fetchone()
            
            if row and row[0]:
                granted_until = datetime.fromisoformat(row[0])
                if granted_until > datetime.utcnow():
                    return True
        
        return False
    
    def upgrade_to_tier(self, user_id: int, tier: PremiumTier, duration_days: int = 30):
        """Upgrade user to paid tier."""
        expires_at = datetime.utcnow() + timedelta(days=duration_days)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO premium_tiers (user_id, tier, expires_at) VALUES (?, ?, ?)",
                (user_id, tier.value, expires_at.isoformat())
            )
            conn.commit()
        
        log.info(f"User {user_id} upgraded to {tier.value} (expires {expires_at})")
    
    def grant_feature(self, user_id: int, feature_id: str, duration_days: int = 30):
        """Grant one-time feature to user."""
        import uuid
        granted_until = datetime.utcnow() + timedelta(days=duration_days)
        grant_id = str(uuid.uuid4())
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO feature_grants (id, user_id, feature_id, granted_until) VALUES (?, ?, ?, ?)",
                (grant_id, user_id, feature_id, granted_until.isoformat())
            )
            conn.commit()
        
        log.info(f"Granted {feature_id} to user {user_id} until {granted_until}")
    
    def record_star_transaction(
        self,
        user_id: int,
        product_id: str,
        amount: int,
        direction: str = "out",
        status: str = "completed"
    ) -> str:
        """Record a star purchase/consumption."""
        import uuid
        txn_id = str(uuid.uuid4())
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO star_transactions (id, user_id, product_id, amount, direction, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (txn_id, user_id, product_id, amount, direction, status)
            )
            conn.commit()
        
        log.info(f"Recorded star transaction {txn_id}: {user_id} {direction} {amount} stars")
        return txn_id
    
    def create_return_trigger(self, trigger: ReturnTrigger):
        """Create trigger for retention (will be sent as digest)."""
        import uuid
        import json
        trigger_id = str(uuid.uuid4())
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO return_triggers (id, user_id, trigger_type, data)
                   VALUES (?, ?, ?, ?)""",
                (trigger_id, trigger.user_id, trigger.trigger_type, json.dumps(trigger.data))
            )
            conn.commit()
        
        log.info(f"Created return trigger {trigger_id} for user {trigger.user_id}: {trigger.trigger_type}")
    
    def _downgrade_to_free(self, user_id: int):
        """Downgrade expired premium subscription."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE premium_tiers SET tier = ?, expires_at = NULL WHERE user_id = ?",
                (PremiumTier.FREE.value, user_id)
            )
            conn.commit()
        
        log.warning(f"User {user_id} subscription expired, downgraded to free")


# ─── Singleton ────────────────────────────────────────────────────────────────

_revenue_manager: Optional[RevenueManager] = None

def get_revenue_manager() -> RevenueManager:
    global _revenue_manager
    if _revenue_manager is None:
        _revenue_manager = RevenueManager()
    return _revenue_manager
