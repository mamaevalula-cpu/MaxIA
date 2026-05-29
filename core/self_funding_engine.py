#!/usr/bin/env python3
"""Self-Funding Engine v2026.2 — CHIEF AI INTEGRATOR"""
import threading, time, json, logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from enum import Enum

log = logging.getLogger("self_funding_engine")
AUDIT_LOG_PATH = Path("/root/my_personal_ai/logs/sfe_audit.jsonl")
STATE_PATH     = Path("/root/my_personal_ai/data/sfe_state.json")

ALLOCATION_RULES = {
    "sale_closed":    {"compute": 0.03, "yield": 0.00, "principal": 0.97},
    "affiliate_conv": {"compute": 0.70, "yield": 0.30, "principal": 0.00},
    "microtx":        {"compute": 0.50, "yield": 0.50, "principal": 0.00},
    "defi_profit":    {"compute": 0.30, "yield": 0.20, "principal": 0.50},
}
MAX_TX_USD = 10_000
MAX_DAILY_USD = 50_000
DEFI_CAP_USD  = 3_000

@dataclass
class BudgetState:
    compute_wallet_usd:  float = 50.0
    yield_vault_usd:     float = 0.0
    principal_usd:       float = 0.0
    defi_deployed_usd:   float = 0.0
    daily_pnl_usd:       float = 0.0
    daily_drawdown_pct:  float = 0.0
    circuit_breaker:     bool  = False
    stream1_monthly:     float = 0.0
    stream2_monthly:     float = 0.0
    stream3_monthly:     float = 0.0
    defi_unlocked:       bool  = False
    token_to_revenue:    float = 0.0
    lead_close_velocity: float = 0.0
    token_roi:           float = 0.0
    last_optimization:   float = 0.0

class SelfFundingEngine:
    """Closed-loop self-funding with 3 revenue streams + budget guardrails."""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._state = BudgetState()
        self._audit_lock = threading.Lock()
        self._load_state()
        self._start_optimization_loop()
        log.info("SelfFundingEngine v2026.2 | Compute=$%.2f", self._state.compute_wallet_usd)

    def _load_state(self):
        if STATE_PATH.exists():
            try:
                d = json.loads(STATE_PATH.read_text())
                for k, v in d.items():
                    if hasattr(self._state, k):
                        setattr(self._state, k, v)
            except Exception as e:
                log.warning("SFE load failed: %s", e)

    def _save_state(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(asdict(self._state), indent=2))

    def _audit(self, event_type: str, amount: float, context: dict):
        entry = {"ts": time.time(), "event": event_type, "amount_usd": amount,
                 "state": asdict(self._state), "context": context}
        with self._audit_lock:
            AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG_PATH, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def process_revenue(self, event: str, gross_usd: float, context: dict = None) -> dict:
        context = context or {}
        rules = ALLOCATION_RULES.get(event, {"compute": 0.5, "yield": 0.5, "principal": 0.0})
        self._state.compute_wallet_usd += gross_usd * rules["compute"]
        self._state.yield_vault_usd    += gross_usd * rules["yield"]
        self._state.principal_usd      += gross_usd * rules["principal"]
        if event in ("sale_closed", "affiliate_conv"):
            self._state.stream1_monthly += gross_usd
        elif event == "microtx":
            self._state.stream2_monthly += gross_usd
        elif event == "defi_profit":
            self._state.stream3_monthly += gross_usd
        self._save_state()
        self._audit(event, gross_usd, {**context, "rules": rules})
        return {"compute": self._state.compute_wallet_usd, "yield": self._state.yield_vault_usd}

    def check_guardrails(self) -> dict:
        s = self._state
        alerts = []
        if s.compute_wallet_usd < 20:
            alerts.append({"level":"WARNING","msg":f"Compute wallet low: ${s.compute_wallet_usd:.2f}","action":"economy_models"})
        if s.compute_wallet_usd < 100 and s.daily_drawdown_pct > 5 and not s.circuit_breaker:
            s.circuit_breaker = True
            self._save_state()
            alerts.append({"level":"CRITICAL","msg":"CIRCUIT BREAKER: DeFi paused","action":"circuit_breaker"})
        if s.stream1_monthly + s.stream2_monthly >= 500 and not s.defi_unlocked:
            s.defi_unlocked = True
            self._save_state()
            alerts.append({"level":"INFO","msg":"DeFi Stream 3 UNLOCKED!","action":"defi_unlock"})
        return {"circuit_breaker": s.circuit_breaker, "defi_unlocked": s.defi_unlocked,
                "compute": s.compute_wallet_usd, "yield": s.yield_vault_usd,
                "stream1": s.stream1_monthly, "stream2": s.stream2_monthly,
                "stream3": s.stream3_monthly, "alerts": alerts}

    def can_act_autonomously(self) -> tuple:
        s = self._state
        if s.compute_wallet_usd < 20: return False, "Compute wallet < $20"
        if s.daily_drawdown_pct > 10: return False, "Daily drawdown > 10%"
        if s.circuit_breaker: return False, "Circuit breaker active"
        return True, "All guardrails OK"

    def can_use_defi(self) -> tuple:
        if not self._state.defi_unlocked: return False, "Need $500/mo for 30d first"
        if self._state.circuit_breaker: return False, "Circuit breaker active"
        if self._state.defi_deployed_usd >= DEFI_CAP_USD: return False, f"DeFi cap ${DEFI_CAP_USD}"
        return True, "DeFi allowed"

    def _optimization_cycle(self):
        while True:
            time.sleep(86400)
            try:
                s = self._state
                total_rev = s.stream1_monthly + s.stream2_monthly + s.stream3_monthly
                s.token_to_revenue = max(s.compute_wallet_usd * 0.1, 0.01) / max(total_rev, 0.01)
                s.last_optimization = time.time()
                self._save_state()
                self._audit("optimization_24h", 0, asdict(s))
                log.info("SFE 24h cycle: T2R=%.3f ROI=%.1f", s.token_to_revenue, s.token_roi)
            except Exception as e:
                log.error("SFE cycle error: %s", e)

    def _start_optimization_loop(self):
        threading.Thread(target=self._optimization_cycle, daemon=True).start()

    def get_status(self) -> dict:
        s = self._state
        g = self.check_guardrails()
        ok, reason = self.can_act_autonomously()
        return {
            "engine": "SelfFundingEngine v2026.2",
            "compute_wallet_usd": round(s.compute_wallet_usd, 2),
            "yield_vault_usd":    round(s.yield_vault_usd, 2),
            "principal_usd":      round(s.principal_usd, 2),
            "total_revenue_mtd":  round(s.stream1_monthly+s.stream2_monthly+s.stream3_monthly, 2),
            "stream1_affiliate":  round(s.stream1_monthly, 2),
            "stream2_microtx":    round(s.stream2_monthly, 2),
            "stream3_defi":       round(s.stream3_monthly, 2),
            "circuit_breaker":    s.circuit_breaker,
            "defi_unlocked":      s.defi_unlocked,
            "autonomous_ok":      ok,
            "autonomous_reason":  reason,
            "token_to_revenue":   round(s.token_to_revenue, 3),
            "token_roi":          round(s.token_roi, 2),
            "alerts":             g["alerts"],
        }
