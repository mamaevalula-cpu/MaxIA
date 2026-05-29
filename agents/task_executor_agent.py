# -*- coding: utf-8 -*-
"""
agents/task_executor_agent.py — Autonomous task executor.

Обёртка над AgentHarness, которая:
  • Принимает задачи из Telegram, GUI, CLI или API
  • Запускает ReAct loop в фоновом потоке
  • Публикует прогресс через on_progress callback
  • Хранит историю выполненных задач
  • Поддерживает отмену через cancel_task(task_id)

Использование:
    agent = TaskExecutorAgent.get()
    task_id = await agent.submit("Найди все TODO в проекте")
    # Получить результат:
    result = await agent.wait(task_id)
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

from core.agent_harness import AgentHarness, HarnessResult, StepResult

log = logging.getLogger("agents.task_executor")


# ── Task status ───────────────────────────────────────────────────────────────


class TaskStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskRecord:
    task_id:    str
    task:       str
    status:     TaskStatus = TaskStatus.PENDING
    steps:      List[StepResult] = field(default_factory=list)
    result:     Optional[HarnessResult] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    ended_at:   Optional[float] = None
    error:      str = ""
    _future:    Optional[asyncio.Future] = field(default=None, repr=False)
    _cancel:    asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.ended_at or time.time()
        return end - self.started_at

    def to_dict(self) -> dict:
        return {
            "task_id":  self.task_id,
            "task":     self.task,
            "status":   self.status.value,
            "steps":    len(self.steps),
            "elapsed":  f"{self.elapsed():.1f}s",
            "error":    self.error,
            "answer":   self.result.answer[:200] if self.result else "",
        }


# ── Progress event ────────────────────────────────────────────────────────────


@dataclass
class ProgressEvent:
    task_id:     str
    task:        str
    step_num:    int
    tool_name:   Optional[str]
    observation: str
    is_final:    bool
    status:      TaskStatus


# ── TaskExecutorAgent ─────────────────────────────────────────────────────────


class TaskExecutorAgent:
    """
    Manages a pool of running agent tasks.
    Each task runs in its own asyncio Task.
    """

    MAX_HISTORY = 50

    _instance: Optional["TaskExecutorAgent"] = None

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._progress_callbacks: List[Callable[[ProgressEvent], None]] = []

    @classmethod
    def get(cls) -> "TaskExecutorAgent":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Submit ────────────────────────────────────────────────────────────────

    async def submit(
        self,
        task: str,
        extra_context: str = "",
        max_steps: int = 20,
        on_progress: Optional[Callable[[ProgressEvent], None]] = None,
    ) -> str:
        """Submit a task. Returns task_id immediately."""
        task_id = str(uuid.uuid4())[:8]
        record = TaskRecord(task_id=task_id, task=task)
        self._tasks[task_id] = record

        if on_progress:
            self._progress_callbacks.append(on_progress)

        asyncio.create_task(
            self._run_task(record, extra_context, max_steps),
            name=f"task-{task_id}",
        )
        log.info("Submitted task %s: %s", task_id, task[:60])
        return task_id

    # ── Wait ──────────────────────────────────────────────────────────────────

    async def wait(self, task_id: str, timeout: float = 600.0) -> Optional[HarnessResult]:
        """Wait for a task to complete. Returns HarnessResult or None if timeout."""
        record = self._tasks.get(task_id)
        if record is None:
            return None

        deadline = time.monotonic() + timeout
        while record.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            if time.monotonic() > deadline:
                return None
            await asyncio.sleep(0.5)
        return record.result

    # ── Cancel ────────────────────────────────────────────────────────────────

    def cancel_task(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if record is None:
            return False
        if record.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False
        record._cancel.set()
        record.status = TaskStatus.CANCELLED
        log.info("Cancelled task %s", task_id)
        return True

    # ── Status ────────────────────────────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[dict]:
        """List all tasks (newest first)."""
        return [
            r.to_dict()
            for r in sorted(self._tasks.values(), key=lambda r: r.created_at, reverse=True)
        ]

    def running_count(self) -> int:
        return sum(1 for r in self._tasks.values() if r.status == TaskStatus.RUNNING)

    # ── Internal runner ───────────────────────────────────────────────────────

    async def _run_task(
        self,
        record: TaskRecord,
        extra_context: str,
        max_steps: int,
    ) -> None:
        record.status = TaskStatus.RUNNING
        record.started_at = time.time()

        def _on_step(sr: StepResult) -> None:
            record.steps.append(sr)
            evt = ProgressEvent(
                task_id=record.task_id,
                task=record.task,
                step_num=sr.step,
                tool_name=sr.tool_call.name if sr.tool_call else None,
                observation=sr.observation[:300],
                is_final=sr.is_final,
                status=record.status,
            )
            for cb in self._progress_callbacks:
                try:
                    cb(evt)
                except Exception:
                    pass

        harness = AgentHarness(max_steps=max_steps, on_step=_on_step)

        try:
            result = await harness.run(record.task, extra_context)
            record.result = result
            record.status = TaskStatus.DONE if result.ok else TaskStatus.FAILED
            record.error  = result.error
        except Exception as e:
            record.status = TaskStatus.FAILED
            record.error  = str(e)
            log.exception("Task %s crashed: %s", record.task_id, e)
        finally:
            record.ended_at = time.time()

        # Trim history
        if len(self._tasks) > self.MAX_HISTORY:
            old_keys = sorted(self._tasks, key=lambda k: self._tasks[k].created_at)
            for k in old_keys[:len(self._tasks) - self.MAX_HISTORY]:
                del self._tasks[k]

        log.info("Task %s → %s (%.1fs)", record.task_id, record.status.value, record.elapsed())


# ── CLI helper ────────────────────────────────────────────────────────────────


async def run_task_cli(task: str) -> None:
    """Quick CLI runner: submit task, stream progress, print result."""
    import sys

    agent = TaskExecutorAgent.get()
    step_count = [0]

    def show_progress(evt: ProgressEvent) -> None:
        step_count[0] = evt.step_num
        tool = evt.tool_name or "thinking"
        obs_short = evt.observation[:120].replace("\n", " ")
        print(f"  [{evt.step_num}] {tool}: {obs_short}", flush=True)
        if evt.is_final:
            print(f"\n✅ Done in {evt.step_num} steps", flush=True)

    print(f"\n🤖 Task: {task}\n{'─'*60}", flush=True)
    task_id = await agent.submit(task, on_progress=show_progress)
    result = await agent.wait(task_id, timeout=300.0)

    print(f"\n{'─'*60}", flush=True)
    if result and result.ok:
        print(f"✅ Answer:\n{result.answer}", flush=True)
    else:
        err = result.error if result else "timeout"
        print(f"❌ Failed: {err}", file=sys.stderr, flush=True)
        sys.exit(1)



    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        """Orchestrator bridge — auto-added."""
        for m in ["run","execute","work","handle","daily_cycle","check","scan","analyze","report","daily_report"]:
            fn = getattr(self, m, None)
            if fn and callable(fn):
                try:
                    r = fn()
                    return str(r)[:400] if r else self.__class__.__name__ + ": ok"
                except Exception as e:
                    return self.__class__.__name__ + f" error: {e}"
        return self.__class__.__name__ + ": ready"

if __name__ == "__main__":
    import sys
    task_text = " ".join(sys.argv[1:]) or "List all Python files in the project"
    asyncio.run(run_task_cli(task_text))