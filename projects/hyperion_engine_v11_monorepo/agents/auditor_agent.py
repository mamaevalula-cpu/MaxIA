"""
agents/auditor_agent.py  —  Auditor Agent for Корпорация MaxAI v11.

Subscribes to task.failed and task.completed events, analyses patterns,
and generates improvement suggestions stored in HyperionDB.

Self-improvement loop: periodically reads suggestions and logs them for
human review or automated application.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List

from libs.messaging import bus, Message
from storage.db import HyperionDB

logger = logging.getLogger(__name__)


@dataclass
class FailurePattern:
    agent_name: str
    error_type: str
    count: int = 0
    last_seen: float = field(default_factory=time.time)
    examples: List[str] = field(default_factory=list)


class AuditorAgent:
    """
    Monitors task outcomes and generates improvement suggestions.

    - Tracks failure patterns by agent and error type
    - Generates suggestions when failure rate exceeds threshold
    - Logs all insights to HyperionDB.agent_improvement
    """

    FAILURE_THRESHOLD = 3        # generate suggestion after N failures of same type
    ANALYSIS_INTERVAL_S = 60.0   # run pattern analysis every 60s
    MAX_EXAMPLES = 5             # keep last N error examples per pattern

    def __init__(self, db: HyperionDB) -> None:
        self._db = db
        self._patterns: Dict[str, FailurePattern] = {}  # key: "agent:error_type"
        self._running = False
        self._total_completed = 0
        self._total_failed = 0

        bus.subscribe("task.failed", self._on_task_failed)
        bus.subscribe("task.completed", self._on_task_completed)
        bus.subscribe("task.timeout", self._on_task_failed)

    async def _on_task_completed(self, msg: Message) -> None:
        self._total_completed += 1
        agent = msg.payload.get("agent_name", "unknown")
        self._db.log_audit("task_completed", msg.payload.get("task_id", ""), {
            "agent": agent,
            "duration_s": msg.payload.get("duration_s", 0),
        })

    async def _on_task_failed(self, msg: Message) -> None:
        self._total_failed += 1
        agent = msg.payload.get("agent_name", "unknown")
        error = msg.payload.get("error", "unknown_error")
        task_id = msg.payload.get("task_id", "")

        # Categorise error
        error_type = self._categorise_error(error)
        pattern_key = f"{agent}:{error_type}"

        if pattern_key not in self._patterns:
            self._patterns[pattern_key] = FailurePattern(
                agent_name=agent, error_type=error_type
            )

        p = self._patterns[pattern_key]
        p.count += 1
        p.last_seen = time.time()
        if len(p.examples) < self.MAX_EXAMPLES:
            p.examples.append(error[:200])

        self._db.log_audit("task_failed", task_id, {
            "agent": agent,
            "error_type": error_type,
            "error": error[:200],
        })

        # Generate suggestion if threshold reached
        if p.count >= self.FAILURE_THRESHOLD and p.count % self.FAILURE_THRESHOLD == 0:
            suggestion = self._generate_suggestion(p)
            self._db.add_improvement(agent, suggestion)
            logger.warning(
                "AuditorAgent improvement suggestion for %s: %s", agent, suggestion
            )

    def _categorise_error(self, error: str) -> str:
        error_lower = error.lower()
        if "timeout" in error_lower:
            return "timeout"
        if "connection" in error_lower or "network" in error_lower:
            return "network"
        if "permission" in error_lower or "auth" in error_lower:
            return "auth"
        if "not found" in error_lower or "404" in error_lower:
            return "not_found"
        if "rate limit" in error_lower or "quota" in error_lower:
            return "rate_limit"
        if "memory" in error_lower or "oom" in error_lower:
            return "memory"
        return "unknown"

    def _generate_suggestion(self, pattern: FailurePattern) -> str:
        suggestions = {
            "timeout": (
                f"Agent '{pattern.agent_name}' timed out {pattern.count}x. "
                "Consider increasing timeout_seconds or splitting into smaller subtasks."
            ),
            "network": (
                f"Agent '{pattern.agent_name}' has {pattern.count} network errors. "
                "Add retry logic with exponential backoff (max 3 retries, base 2s)."
            ),
            "rate_limit": (
                f"Agent '{pattern.agent_name}' hitting rate limits {pattern.count}x. "
                "Implement request throttling with asyncio-throttle or token bucket."
            ),
            "not_found": (
                f"Agent '{pattern.agent_name}' getting 404s ({pattern.count}x). "
                "Verify endpoint URLs, add circuit breaker to stop cascading failures."
            ),
            "auth": (
                f"Agent '{pattern.agent_name}' auth failures ({pattern.count}x). "
                "Rotate credentials, implement token refresh before expiry."
            ),
            "memory": (
                f"Agent '{pattern.agent_name}' OOM errors ({pattern.count}x). "
                "Profile memory usage, implement streaming for large payloads."
            ),
            "unknown": (
                f"Agent '{pattern.agent_name}' unknown errors ({pattern.count}x). "
                f"Sample error: {pattern.examples[-1] if pattern.examples else 'none'}. "
                "Add structured error logging with correlation IDs."
            ),
        }
        return suggestions.get(pattern.error_type, suggestions["unknown"])

    async def _run_analysis(self) -> None:
        """Periodic analysis and reporting."""
        total = self._total_completed + self._total_failed
        if total == 0:
            return

        failure_rate = self._total_failed / total * 100
        logger.info(
            "AuditorAgent analysis: %d tasks (%.1f%% failure rate), %d patterns tracked",
            total, failure_rate, len(self._patterns)
        )

        stats = self._db.get_task_stats()
        self._db.log_audit("audit_cycle", "system", {
            "failure_rate_pct": round(failure_rate, 2),
            "patterns": len(self._patterns),
            "db_stats": stats,
        })

        # Log top failure patterns
        top_patterns = sorted(
            self._patterns.values(), key=lambda p: p.count, reverse=True
        )[:5]
        for p in top_patterns:
            logger.info(
                "  Pattern %s:%s — %d failures", p.agent_name, p.error_type, p.count
            )

    async def start(self) -> None:
        self._running = True
        logger.info("AuditorAgent started (analysis_interval=%.0fs)",
                    self.ANALYSIS_INTERVAL_S)
        while self._running:
            await asyncio.sleep(self.ANALYSIS_INTERVAL_S)
            await self._run_analysis()

    def stop(self) -> None:
        self._running = False
        logger.info("AuditorAgent stopped. Total audited: completed=%d, failed=%d",
                    self._total_completed, self._total_failed)
