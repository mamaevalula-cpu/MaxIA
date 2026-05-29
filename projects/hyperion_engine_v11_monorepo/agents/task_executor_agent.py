"""
agents/task_executor_agent.py  —  Task Executor for Корпорация MaxAI v11.

Pulls tasks from the internal queue, routes to registered agent handlers,
reports results via MessageBus, handles retries and timeouts.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Optional

from libs.messaging import bus, Message

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class Task:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3
    timeout_seconds: float = 60.0


AgentHandler = Callable[[Task], Coroutine[Any, Any, Any]]


class TaskExecutorAgent:
    """
    Executes tasks dispatched by the Orchestrator.

    Usage:
        executor = TaskExecutorAgent()
        executor.register_agent("summarizer", my_summarizer_fn)
        await executor.start()
    """

    def __init__(self, concurrency: int = 4) -> None:
        self._registry: Dict[str, AgentHandler] = {}
        self._queue: asyncio.Queue[Task] = asyncio.Queue(maxsize=500)
        self._running = False
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        bus.subscribe("task.dispatch", self._on_task_dispatch)

    def register_agent(self, agent_name: str, handler: AgentHandler) -> None:
        self._registry[agent_name] = handler
        logger.info("Agent registered: %s", agent_name)

    async def _on_task_dispatch(self, msg: Message) -> None:
        task = Task(
            task_id=msg.payload.get("task_id", str(uuid.uuid4())),
            agent_name=msg.payload.get("agent_name", ""),
            payload=msg.payload.get("payload", {}),
            timeout_seconds=float(msg.payload.get("timeout_seconds", 60)),
            max_retries=int(msg.payload.get("max_retries", 3)),
        )
        await self._queue.put(task)
        logger.debug("Task enqueued: %s -> %s", task.task_id, task.agent_name)

    async def _execute_task(self, task: Task) -> None:
        async with self._semaphore:
            handler = self._registry.get(task.agent_name)
            if not handler:
                task.status = TaskStatus.FAILED
                task.error = f"No handler for agent: {task.agent_name}"
                await self._publish_result(task)
                return

            task.status = TaskStatus.RUNNING
            await bus.publish("task.started", {"task_id": task.task_id})

            for attempt in range(task.max_retries + 1):
                try:
                    result = await asyncio.wait_for(
                        handler(task), timeout=task.timeout_seconds
                    )
                    task.status = TaskStatus.COMPLETED
                    task.result = result
                    task.completed_at = time.time()
                    logger.info("Task %s completed in %.2fs",
                                task.task_id, task.completed_at - task.created_at)
                    break
                except asyncio.TimeoutError:
                    task.error = f"Timeout after {task.timeout_seconds}s"
                    if attempt >= task.max_retries:
                        task.status = TaskStatus.TIMEOUT
                        break
                    task.retries += 1
                    await asyncio.sleep(2 ** attempt)
                except Exception as exc:
                    task.error = str(exc)
                    if attempt >= task.max_retries:
                        task.status = TaskStatus.FAILED
                        break
                    task.retries += 1
                    await asyncio.sleep(2 ** attempt)

            await self._publish_result(task)

    async def _publish_result(self, task: Task) -> None:
        topic = "task.completed" if task.status == TaskStatus.COMPLETED else "task.failed"
        await bus.publish(topic, {
            "task_id": task.task_id,
            "agent_name": task.agent_name,
            "status": task.status.value,
            "result": task.result,
            "error": task.error,
            "retries": task.retries,
            "duration_s": (task.completed_at or time.time()) - task.created_at,
        })

    async def start(self) -> None:
        self._running = True
        logger.info("TaskExecutorAgent started (concurrency=%d)", self._concurrency)
        workers = [asyncio.create_task(self._worker()) for _ in range(self._concurrency)]
        await asyncio.gather(*workers)

    async def _worker(self) -> None:
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                asyncio.create_task(self._execute_task(task))
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._running = False
        logger.info("TaskExecutorAgent stopped")
