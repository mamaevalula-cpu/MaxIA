"""
core/orchestrator.py  —  Task Orchestrator for Корпорация MaxAI v11.

Receives task requests, validates them, selects the best agent
from the registry, and dispatches via MessageBus.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.agent_registry import AgentRegistry, AgentStatus
from libs.messaging import bus

logger = logging.getLogger(__name__)


@dataclass
class TaskRequest:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    capability: str = ""          # required agent capability
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5             # 1=high, 10=low
    timeout_seconds: float = 60.0
    max_retries: int = 3
    submitted_at: float = field(default_factory=time.time)


class Orchestrator:
    """
    Routes task requests to appropriate agents.

    Lifecycle:
        orch = Orchestrator(registry)
        await orch.submit(TaskRequest(capability="summarize", payload={...}))
    """

    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry
        self._pending: asyncio.PriorityQueue[tuple[int, TaskRequest]] =             asyncio.PriorityQueue(maxsize=1000)
        self._running = False

        bus.subscribe("task.completed", self._on_task_result)
        bus.subscribe("task.failed", self._on_task_result)

    async def submit(self, request: TaskRequest) -> str:
        await self._pending.put((request.priority, request))
        logger.info("Task %s submitted (cap=%s, prio=%d)",
                    request.task_id, request.capability, request.priority)
        return request.task_id

    def _select_agent(self, capability: str) -> Optional[str]:
        agents = self._registry.list_active()
        candidates = [
            a for a in agents
            if capability in a.capabilities and a.status == AgentStatus.IDLE
        ]
        if not candidates:
            # Fall back to any active agent with the capability
            candidates = [a for a in agents if capability in a.capabilities]
        if not candidates:
            return None
        # Pick agent with highest success rate
        best = max(candidates, key=lambda a: (
            a.tasks_completed / max(a.tasks_completed + a.tasks_failed, 1)
        ))
        return best.agent_id

    async def _dispatch(self, request: TaskRequest) -> None:
        agent_id = self._select_agent(request.capability)
        if not agent_id:
            logger.warning("No agent available for capability: %s", request.capability)
            await bus.publish("task.no_agent", {
                "task_id": request.task_id,
                "capability": request.capability,
            })
            return

        self._registry.update_status(agent_id, AgentStatus.ACTIVE)
        await bus.publish("task.dispatch", {
            "task_id": request.task_id,
            "agent_id": agent_id,
            "agent_name": request.capability,
            "payload": request.payload,
            "timeout_seconds": request.timeout_seconds,
            "max_retries": request.max_retries,
        })
        logger.info("Task %s dispatched to agent %s", request.task_id, agent_id)

    async def _on_task_result(self, msg) -> None:
        # Update agent status back to idle on result
        agent_id = msg.payload.get("agent_id")
        if agent_id:
            success = msg.topic == "task.completed"
            self._registry.update_status(agent_id, AgentStatus.IDLE)
            self._registry.increment_counter(agent_id, success=success)

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestrator started")
        while self._running:
            try:
                _, request = await asyncio.wait_for(
                    self._pending.get(), timeout=1.0
                )
                asyncio.create_task(self._dispatch(request))
            except asyncio.TimeoutError:
                continue


    def get_stats(self) -> dict:
        """Return task statistics grouped by agent from the persistent DB."""
        try:
            conn = None
            # Try to get stats from HyperionDB if available
            from storage.db import HyperionDB, DB_PATH
            db = HyperionDB(DB_PATH)
            db.init()
            return db.get_task_stats()
        except Exception as exc:
            logger.warning("get_stats error: %s", exc)
            return {}

    def stop(self) -> None:
        self._running = False
        logger.info("Orchestrator stopped")



class SelfImprovementLoop:
    """
    Reads improvement suggestions from the DB and logs them.
    Runs every 60s; in production, suggestions could be auto-applied.
    """

    def __init__(self, db, check_interval_s: float = 60.0) -> None:
        self._db = db
        self._interval = check_interval_s
        self._running = False
        self._last_id = 0

    async def start(self) -> None:
        self._running = True
        logger.info("SelfImprovementLoop started")
        while self._running:
            await asyncio.sleep(self._interval)
            self._process_suggestions()

    def _process_suggestions(self) -> None:
        try:
            conn = self._db._conn
            if conn is None:
                return
            rows = conn.execute(
                "SELECT id, agent_id, suggestion, created_at FROM agent_improvement "
                "WHERE id > ? AND applied = 0 ORDER BY id",
                (self._last_id,)
            ).fetchall()
            for row in rows:
                sid, agent_id, suggestion, created_at = row
                logger.info(
                    "SelfImprovement [%d] agent=%s: %s", sid, agent_id, suggestion
                )
                self._last_id = sid
        except Exception as exc:
            logger.error("SelfImprovementLoop error: %s", exc)

    def stop(self) -> None:
        self._running = False
        logger.info("SelfImprovementLoop stopped")

