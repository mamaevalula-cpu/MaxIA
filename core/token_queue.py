#!/usr/bin/env python3
"""Token Queue Manager — LLM fallback + premium re-run when tokens recover."""
import threading, time, logging, queue
from dataclasses import dataclass, field
from typing import Callable, Optional, Any
from enum import IntEnum

log = logging.getLogger("token_queue")

class Priority(IntEnum):
    CRITICAL = 1
    HIGH     = 2
    NORMAL   = 3
    LOW      = 4

@dataclass
class QueuedTask:
    task_id:    str
    prompt:     str
    system:     str
    priority:   Priority = Priority.NORMAL
    created_at: float = field(default_factory=time.time)
    attempts:   int   = 0
    callback:   Optional[Callable] = None

class TokenQueueManager:
    """Priority queue with economy fallback + premium re-run on token recovery."""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._q: queue.PriorityQueue = queue.PriorityQueue()
        self._premium_blocked_until: float = 0
        self._results: dict = {}
        threading.Thread(target=self._worker, daemon=True).start()
        log.info("TokenQueueManager ready")

    def submit(self, task_id: str, prompt: str, system: str = "",
               priority: Priority = Priority.NORMAL, callback=None) -> str:
        self._q.put((int(priority), time.time(), QueuedTask(
            task_id=task_id, prompt=prompt, system=system,
            priority=priority, callback=callback
        )))
        return task_id

    def _execute(self, task: QueuedTask) -> str:
        now = time.time()
        try:
            from brain.llm_router import LLMRouter, LLMRequest
            router = LLMRouter.get()
            if now > self._premium_blocked_until:
                try:
                    return router.ask_simple(task.prompt, system=task.system)
                except Exception as e:
                    if "429" in str(e) or "rate" in str(e).lower():
                        self._premium_blocked_until = now + 60
                        log.warning("Premium rate limited 60s, using economy")
                    else:
                        raise
            # Economy fallback
            result = router.ask_fast(task.prompt, system=task.system)
            if task.priority <= Priority.HIGH and now <= self._premium_blocked_until:
                self._schedule_rerun(task)
            return result
        except Exception as e:
            return f"[TokenQueue error: {e}]"

    def _schedule_rerun(self, task: QueuedTask):
        def _rerun():
            wait = max(0, self._premium_blocked_until - time.time())
            if wait: time.sleep(wait + 5)
            self.submit(task.task_id + "_rerun", task.prompt, task.system, task.priority, task.callback)
        threading.Thread(target=_rerun, daemon=True).start()

    def _worker(self):
        while True:
            try:
                _, _, task = self._q.get(timeout=5)
                task.attempts += 1
                result = self._execute(task)
                self._results[task.task_id] = result
                if task.callback:
                    try: task.callback(task.task_id, result)
                    except Exception as e: log.error("Callback error: %s", e)
                self._q.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                log.error("Worker: %s", e)

    def get_result(self, task_id: str, timeout: float = 30) -> Optional[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if task_id in self._results:
                return self._results.pop(task_id)
            time.sleep(0.2)
        return None
