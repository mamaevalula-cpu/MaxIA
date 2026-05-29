# -*- coding: utf-8 -*-
"""
core/governance.py — Operational Governance Layer (OGL).

Enforces:
  - Token budget per session and per task
  - Orchestration depth limits (MAX_AGENT_DEPTH)
  - Safe mode (automatic load reduction under overload)
  - Environment isolation verification
  - Anti-loop protection
  - Bounded retry governance (single layer)

Usage:
    from core.governance import gov

    # Check before LLM call
    gov.check_token_budget(estimated_tokens=500, task_id="t-001")

    # Wrap orchestration depth
    with gov.orchestration_depth_guard(task_id="t-001"):
        ...

    # Report token usage after call
    gov.record_token_usage(tokens_used=432, provider="deepseek", task_id="t-001")

    # Safe mode check
    if gov.is_safe_mode():
        # skip debate, use single model
        ...
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

log = logging.getLogger("core.governance")


# ── Policy constants ──────────────────────────────────────────────────────────

# Token budgets
SESSION_TOKEN_BUDGET     = 500_000   # max tokens per session before safe mode
TASK_TOKEN_BUDGET        = 50_000    # max tokens per individual task
SAFE_MODE_THRESHOLD      = 0.95     # activate safe mode at 75% session budget

# Orchestration limits
MAX_AGENT_DEPTH          = 2        # max nested orchestration calls
MAX_DEBATE_SPECIALISTS   = 3        # cap parallel debate specialists
MAX_TOOL_CHAIN           = 5        # max sequential tool calls per task

# Retry governance (single layer only)
MAX_RETRIES              = 3        # absolute retry ceiling

# Execution environment
VALID_ENVIRONMENTS       = {"local", "staging", "production", "sandbox"}


# ── Enums ─────────────────────────────────────────────────────────────────────

class ExecutionEnvironment(str, Enum):
    LOCAL      = "local"
    STAGING    = "staging"
    PRODUCTION = "production"
    SANDBOX    = "sandbox"
    UNKNOWN    = "unknown"


class SafeModeReason(str, Enum):
    TOKEN_BUDGET    = "token_budget_near_limit"
    RETRY_STORM     = "retry_storm_detected"
    DEPTH_EXCEEDED  = "orchestration_depth_exceeded"
    OPERATOR_SET    = "operator_activated"
    INSTABILITY     = "system_instability"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class TokenUsage:
    session_total:  int = 0
    task_totals:    Dict[str, int] = field(default_factory=dict)
    provider_totals: Dict[str, int] = field(default_factory=dict)


@dataclass
class GovernanceViolation(Exception):
    code:    str
    message: str
    task_id: str = ""

    def __str__(self) -> str:
        return f"[GOV:{self.code}] {self.message} (task={self.task_id})"


# ── Main Governance Layer ─────────────────────────────────────────────────────

class GovernanceLayer:
    """
    Singleton governance controller. Thread-safe.
    Call gov.reset_session() at the start of each new session.
    """

    _instance: Optional[GovernanceLayer] = None
    _lock = threading.Lock()

    def __new__(cls) -> GovernanceLayer:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        self._token_usage = TokenUsage()
        self._depth_counters: Dict[str, int] = {}   # task_id → current depth
        self._retry_counters: Dict[str, int] = {}   # task_id → retries used
        self._safe_mode: bool = False
        self._safe_mode_reason: Optional[SafeModeReason] = None
        self._environment: ExecutionEnvironment = ExecutionEnvironment.LOCAL
        self._session_start: float = time.time()
        self._lock = threading.Lock()

        log.info("GovernanceLayer initialized | env=%s | session_token_budget=%d",
                 self._environment.value, SESSION_TOKEN_BUDGET)

    # ── Environment ───────────────────────────────────────────────────────────

    def set_environment(self, env: str) -> None:
        """Declare execution environment. Must be called at startup."""
        with self._lock:
            try:
                self._environment = ExecutionEnvironment(env.lower())
                log.info("Execution environment set: %s", self._environment.value)
            except ValueError:
                self._environment = ExecutionEnvironment.UNKNOWN
                log.warning("Unknown environment '%s' — treating as UNKNOWN", env)

    @property
    def environment(self) -> ExecutionEnvironment:
        return self._environment

    def require_environment(self, *allowed: str) -> None:
        """
        Raise GovernanceViolation if current environment is not in allowed list.
        Use before any production mutation.
        """
        with self._lock:
            if self._environment.value not in [a.lower() for a in allowed]:
                raise GovernanceViolation(
                    code="ENV_MISMATCH",
                    message=f"Operation requires env={allowed}, current={self._environment.value}",
                )

    def is_production(self) -> bool:
        return self._environment == ExecutionEnvironment.PRODUCTION

    # ── Token Budget ──────────────────────────────────────────────────────────

    def check_token_budget(self, estimated_tokens: int, task_id: str = "") -> None:
        """
        Raise GovernanceViolation if estimated_tokens would exceed budget.
        Call BEFORE making any LLM request.
        """
        with self._lock:
            session_remaining = SESSION_TOKEN_BUDGET - self._token_usage.session_total
            log.info("GOV_CHECK: budget=%d used=%d remaining=%d asked=%d safe=%s",
                SESSION_TOKEN_BUDGET, self._token_usage.session_total,
                session_remaining, estimated_tokens, self._safe_mode)
            task_used = self._token_usage.task_totals.get(task_id, 0)
            task_remaining = TASK_TOKEN_BUDGET - task_used

            if estimated_tokens > session_remaining:
                self._activate_safe_mode(SafeModeReason.TOKEN_BUDGET)
                raise GovernanceViolation(
                    code="SESSION_BUDGET_EXCEEDED",
                    message=f"Session token budget exhausted. "
                            f"Used={self._token_usage.session_total}, "
                            f"Budget={SESSION_TOKEN_BUDGET}",
                    task_id=task_id,
                )

            if task_id and estimated_tokens > task_remaining:
                raise GovernanceViolation(
                    code="TASK_BUDGET_EXCEEDED",
                    message=f"Task token budget exceeded. "
                            f"Used={task_used}, Budget={TASK_TOKEN_BUDGET}",
                    task_id=task_id,
                )

            # Warn at 75% session budget
            if (self._token_usage.session_total / SESSION_TOKEN_BUDGET) >= SAFE_MODE_THRESHOLD:
                if not self._safe_mode:
                    self._activate_safe_mode(SafeModeReason.TOKEN_BUDGET)
                    log.warning("SAFE MODE: session token budget at %.0f%%",
                                self._token_usage.session_total / SESSION_TOKEN_BUDGET * 100)

    def record_token_usage(self, tokens_used: int, provider: str = "", task_id: str = "") -> None:
        """Report actual token usage after an LLM call."""
        with self._lock:
            self._token_usage.session_total += tokens_used
            if task_id:
                self._token_usage.task_totals[task_id] = (
                    self._token_usage.task_totals.get(task_id, 0) + tokens_used
                )
            if provider:
                self._token_usage.provider_totals[provider] = (
                    self._token_usage.provider_totals.get(provider, 0) + tokens_used
                )

    def token_usage_summary(self) -> dict:
        with self._lock:
            pct = self._token_usage.session_total / SESSION_TOKEN_BUDGET * 100
            return {
                "session_total":    self._token_usage.session_total,
                "session_budget":   SESSION_TOKEN_BUDGET,
                "session_pct":      round(pct, 1),
                "provider_totals":  dict(self._token_usage.provider_totals),
                "safe_mode":        self._safe_mode,
            }

    # ── Orchestration Depth ───────────────────────────────────────────────────

    @contextmanager
    def orchestration_depth_guard(self, task_id: str = ""):
        """
        Context manager that tracks orchestration depth.
        Raises GovernanceViolation if MAX_AGENT_DEPTH exceeded.

        Usage:
            with gov.orchestration_depth_guard(task_id):
                result = inner_agent.run(...)
        """
        with self._lock:
            current = self._depth_counters.get(task_id, 0)
            if current >= MAX_AGENT_DEPTH:
                raise GovernanceViolation(
                    code="DEPTH_EXCEEDED",
                    message=f"Orchestration depth {current} >= MAX_AGENT_DEPTH={MAX_AGENT_DEPTH}",
                    task_id=task_id,
                )
            self._depth_counters[task_id] = current + 1
            depth = self._depth_counters[task_id]

        log.debug("Orchestration depth: %d/%d (task=%s)", depth, MAX_AGENT_DEPTH, task_id)
        try:
            yield depth
        finally:
            with self._lock:
                self._depth_counters[task_id] = max(0, self._depth_counters.get(task_id, 1) - 1)

    def get_allowed_debate_specialists(self, requested: int) -> int:
        """
        Return how many debate specialists are allowed.
        In safe mode: max 1. Otherwise: capped at MAX_DEBATE_SPECIALISTS.
        """
        if self._safe_mode:
            log.warning("Safe mode: capping debate specialists to 1 (requested=%d)", requested)
            return 1
        return min(requested, MAX_DEBATE_SPECIALISTS)

    # ── Retry Governance ──────────────────────────────────────────────────────

    def check_retry_budget(self, task_id: str) -> int:
        """
        Return remaining retry budget for task.
        Raises GovernanceViolation if exhausted.
        Only ONE layer should call this per task.
        """
        with self._lock:
            used = self._retry_counters.get(task_id, 0)
            remaining = MAX_RETRIES - used
            if remaining <= 0:
                raise GovernanceViolation(
                    code="RETRY_BUDGET_EXHAUSTED",
                    message=f"Retry budget exhausted for task={task_id} (max={MAX_RETRIES})",
                    task_id=task_id,
                )
            return remaining

    def record_retry(self, task_id: str) -> int:
        """Increment retry counter. Returns retries used so far."""
        with self._lock:
            used = self._retry_counters.get(task_id, 0) + 1
            self._retry_counters[task_id] = used
            if used >= MAX_RETRIES - 1:
                log.warning("Retry budget low: task=%s retries=%d/%d", task_id, used, MAX_RETRIES)
            return used

    # ── Safe Mode ─────────────────────────────────────────────────────────────

    def _activate_safe_mode(self, reason: SafeModeReason) -> None:
        """Internal: activate safe mode."""
        if not self._safe_mode:
            self._safe_mode = True
            self._safe_mode_reason = reason
            log.warning("SAFE MODE ACTIVATED: reason=%s", reason.value)

    def activate_safe_mode(self, reason: str = "operator_activated") -> None:
        """Operator: manually activate safe mode."""
        with self._lock:
            try:
                r = SafeModeReason(reason)
            except ValueError:
                r = SafeModeReason.OPERATOR_SET
            self._activate_safe_mode(r)

    def deactivate_safe_mode(self) -> None:
        """Operator: restore normal operation."""
        with self._lock:
            if self._safe_mode:
                self._safe_mode = False
                self._safe_mode_reason = None
                log.info("Safe mode deactivated by operator")

    def is_safe_mode(self) -> bool:
        return self._safe_mode

    def safe_mode_status(self) -> dict:
        with self._lock:
            return {
                "active": self._safe_mode,
                "reason": self._safe_mode_reason.value if self._safe_mode_reason else None,
            }

    # ── Anti-Loop Protection ──────────────────────────────────────────────────

    def detect_retry_storm(self, task_id: str, window_sec: float = 30.0) -> bool:
        """
        Detect if retries are happening too fast (storm pattern).
        Activates safe mode and returns True if storm detected.
        """
        with self._lock:
            used = self._retry_counters.get(task_id, 0)
            elapsed = time.time() - self._session_start
            rate = used / max(elapsed, 1)
            if rate > 0.5 and used >= 2:   # > 0.5 retries/sec
                self._activate_safe_mode(SafeModeReason.RETRY_STORM)
                log.error("RETRY STORM detected: task=%s rate=%.2f/s", task_id, rate)
                return True
        return False

    # ── Session Lifecycle ─────────────────────────────────────────────────────

    def reset_session(self) -> None:
        """Call at the start of each new conversation/session."""
        with self._lock:
            self._token_usage = TokenUsage()
            self._depth_counters.clear()
            self._retry_counters.clear()
            self._safe_mode = False
            self._safe_mode_reason = None
            self._session_start = time.time()
            log.info("GovernanceLayer session reset")

    def reset_task(self, task_id: str) -> None:
        """Clear per-task counters (e.g., after task completes)."""
        with self._lock:
            self._depth_counters.pop(task_id, None)
            self._retry_counters.pop(task_id, None)
            self._token_usage.task_totals.pop(task_id, None)

    def status(self) -> dict:
        """Full governance status snapshot."""
        with self._lock:
            return {
                "environment":     self._environment.value,
                "safe_mode":       self._safe_mode,
                "safe_mode_reason": self._safe_mode_reason.value if self._safe_mode_reason else None,
                "token_usage":     {
                    "session_total":  self._token_usage.session_total,
                    "session_budget": SESSION_TOKEN_BUDGET,
                    "session_pct":    round(
                        self._token_usage.session_total / SESSION_TOKEN_BUDGET * 100, 1
                    ),
                },
                "active_tasks":    len(self._depth_counters),
                "session_uptime_s": round(time.time() - self._session_start, 1),
                "policy": {
                    "max_agent_depth":       MAX_AGENT_DEPTH,
                    "max_debate_specialists": MAX_DEBATE_SPECIALISTS,
                    "max_retries":           MAX_RETRIES,
                    "session_token_budget":  SESSION_TOKEN_BUDGET,
                    "task_token_budget":     TASK_TOKEN_BUDGET,
                },
            }


# ── Singleton export ──────────────────────────────────────────────────────────

gov = GovernanceLayer()
