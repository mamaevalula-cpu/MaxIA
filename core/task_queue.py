# -*- coding: utf-8 -*-
"""
core/task_queue.py — Персистентная очередь задач с приоритетами.

Решает проблему: длинные задачи блокируют поток, нет возможности очереди/отложенного запуска.

Возможности:
  • SQLite-backed: задачи не теряются при перезапуске
  • Priority queue: 1..10 (10 = срочно)
  • Фоновые workers (ThreadPool)
  • Retry с exponential backoff
  • Статусы: pending → running → done / failed / cancelled
  • Отложенный запуск (scheduled_at)
  • Callback по завершении

Использование:
    q = TaskQueue.get()
    task_id = q.enqueue("search", "найди новости о BTC", priority=7)
    status = q.get_status(task_id)
    result = q.get_result(task_id)

    # Отложенная задача
    q.enqueue("analysis", "проанализируй портфель",
              scheduled_at=time.time() + 3600)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("core.task_queue")

# ── Конфигурация ──────────────────────────────────────────────────────────────

DB_PATH        = Path("data/task_queue.db")
NUM_WORKERS    = 3          # параллельных workers
MAX_RETRIES    = 3          # максимум попыток при ошибке
RETRY_BASE_SEC = 5          # базовая пауза перед повтором (секунд)
TASK_TIMEOUT   = 300        # таймаут выполнения задачи (секунд)
CLEANUP_AFTER_DAYS = 7      # удалять завершённые задачи старше N дней
POLL_INTERVAL  = 1.0        # интервал опроса очереди (секунд)


class TaskStatus(Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"  # ожидает scheduled_at


@dataclass
class Task:
    """Задача в очереди."""
    task_id:      str
    tool_name:    str           # имя инструмента/агента
    query:        str           # запрос/команда
    priority:     int  = 5      # 1..10
    status:       TaskStatus = TaskStatus.PENDING
    retries:      int  = 0
    max_retries:  int  = MAX_RETRIES
    result:       str  = ""
    error:        str  = ""
    session_id:   str  = ""
    user_id:      str  = ""
    metadata:     Dict = field(default_factory=dict)
    created_at:   float = field(default_factory=time.time)
    scheduled_at: float = 0.0   # 0 = немедленно
    started_at:   float = 0.0
    completed_at: float = 0.0
    # Callback при завершении (не сохраняется в БД)
    on_complete:  Optional[Callable] = field(default=None, repr=False, compare=False)

    @property
    def age_sec(self) -> float:
        return time.time() - self.created_at

    @property
    def is_ready(self) -> bool:
        """Готова ли задача к выполнению."""
        if self.status not in (TaskStatus.PENDING, TaskStatus.SCHEDULED):
            return False
        if self.scheduled_at > 0 and time.time() < self.scheduled_at:
            return False
        return True

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        d.pop("on_complete", None)
        return d


class TaskQueue:
    """
    Singleton. Персистентная очередь задач с background workers.
    """

    _instance: Optional["TaskQueue"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(DB_PATH)
        self._local = threading.local()
        self._rlock = threading.RLock()
        self._callbacks: Dict[str, Callable] = {}   # task_id → on_complete
        self._tool_registry = None                  # подключается позже
        self._brain_callback = None                 # для общих задач
        self._workers: List[threading.Thread] = []
        self._stop_event = threading.Event()
        self._task_available = threading.Event()    # сигнал о новой задаче
        self._stats = {
            "enqueued": 0, "completed": 0, "failed": 0, "retried": 0
        }
        self._init_db()
        self._recover_running_tasks()
        log.info("TaskQueue initialized (workers=%d)", NUM_WORKERS)

    @classmethod
    def get(cls) -> "TaskQueue":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_tool_registry(self, registry: Any) -> None:
        """Подключить ToolRegistry для выполнения задач."""
        self._tool_registry = registry

    def set_brain_callback(self, cb: Callable) -> None:
        """Подключить callback для задач без конкретного инструмента."""
        self._brain_callback = cb

    # ── Инициализация БД ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id      TEXT PRIMARY KEY,
                    tool_name    TEXT NOT NULL,
                    query        TEXT NOT NULL,
                    priority     INTEGER DEFAULT 5,
                    status       TEXT DEFAULT 'pending',
                    retries      INTEGER DEFAULT 0,
                    max_retries  INTEGER DEFAULT 3,
                    result       TEXT DEFAULT '',
                    error        TEXT DEFAULT '',
                    session_id   TEXT DEFAULT '',
                    user_id      TEXT DEFAULT '',
                    metadata     TEXT DEFAULT '{}',
                    created_at   REAL NOT NULL,
                    scheduled_at REAL DEFAULT 0,
                    started_at   REAL DEFAULT 0,
                    completed_at REAL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_task_status_priority
                    ON tasks(status, priority DESC, scheduled_at);
                CREATE INDEX IF NOT EXISTS idx_task_session
                    ON tasks(session_id, created_at DESC);
            """)

    def _recover_running_tasks(self) -> None:
        """При старте — вернуть задачи 'running' в 'pending' (незавершённые из прошлого запуска)."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                count = conn.execute(
                    "UPDATE tasks SET status='pending', started_at=0 WHERE status='running'"
                ).rowcount
                conn.commit()
            if count:
                log.info("Recovered %d running tasks → pending", count)
        except Exception as e:
            log.warning("Task recovery failed: %s", e)

    # ── Enqueueing ────────────────────────────────────────────────────────────

    def enqueue(
        self,
        tool_name:    str,
        query:        str,
        priority:     int  = 5,
        session_id:   str  = "",
        user_id:      str  = "",
        scheduled_at: float = 0.0,
        metadata:     Dict  = None,
        on_complete:  Optional[Callable] = None,
        max_retries:  int  = MAX_RETRIES,
    ) -> str:
        """
        Добавить задачу в очередь.

        Returns: task_id
        """
        task_id = str(uuid.uuid4())[:16]
        now = time.time()
        status = TaskStatus.SCHEDULED if (scheduled_at and scheduled_at > now) else TaskStatus.PENDING

        task = Task(
            task_id=task_id,
            tool_name=tool_name,
            query=query[:1000],
            priority=max(1, min(10, priority)),
            status=status,
            max_retries=max_retries,
            session_id=session_id,
            user_id=user_id,
            metadata=metadata or {},
            created_at=now,
            scheduled_at=scheduled_at,
        )

        try:
            conn = self._conn()
            conn.execute(
                """INSERT INTO tasks
                   (task_id, tool_name, query, priority, status, retries, max_retries,
                    result, error, session_id, user_id, metadata, created_at, scheduled_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task.task_id, task.tool_name, task.query, task.priority,
                    task.status.value, 0, task.max_retries,
                    "", "", task.session_id, task.user_id,
                    json.dumps(task.metadata, ensure_ascii=False),
                    task.created_at, task.scheduled_at,
                )
            )
            conn.commit()

            with self._rlock:
                self._stats["enqueued"] += 1
                if on_complete:
                    self._callbacks[task_id] = on_complete

            self._task_available.set()
            log.debug("Task enqueued: %s [%s] p=%d", task_id[:8], tool_name, priority)

        except Exception as e:
            log.error("Enqueue failed: %s", e)

        return task_id

    def cancel(self, task_id: str) -> bool:
        """Отменить задачу. Returns True если успешно."""
        try:
            conn = self._conn()
            rows = conn.execute(
                """UPDATE tasks SET status='cancelled', completed_at=?
                   WHERE task_id=? AND status IN ('pending','scheduled')""",
                (time.time(), task_id)
            ).rowcount
            conn.commit()
            return rows > 0
        except Exception as e:
            log.warning("Cancel failed: %s", e)
            return False

    # ── Workers ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Запустить фоновые workers."""
        if self._workers:
            return
        self._stop_event.clear()
        for i in range(NUM_WORKERS):
            t = threading.Thread(
                target=self._worker_loop,
                args=(i,),
                daemon=True,
                name=f"task-worker-{i}",
            )
            t.start()
            self._workers.append(t)
        # Отдельный поток для cleanup
        threading.Thread(
            target=self._cleanup_loop, daemon=True, name="task-cleanup"
        ).start()
        log.info("TaskQueue started with %d workers", NUM_WORKERS)

    def stop(self) -> None:
        """Остановить workers."""
        self._stop_event.set()
        self._task_available.set()
        self._workers.clear()
        log.info("TaskQueue stopped")

    def _worker_loop(self, worker_id: int) -> None:
        """Основной цикл worker'а."""
        log.debug("Task worker-%d started", worker_id)
        while not self._stop_event.is_set():
            task = self._fetch_next_task()
            if task is None:
                self._task_available.wait(timeout=POLL_INTERVAL)
                self._task_available.clear()
                continue

            self._execute_task(task)

    def _fetch_next_task(self) -> Optional[Task]:
        """Взять следующую задачу из очереди (атомарно)."""
        try:
            now = time.time()
            conn = self._conn()
            # Берём самую приоритетную готовую задачу
            row = conn.execute(
                """SELECT * FROM tasks
                   WHERE status IN ('pending', 'scheduled')
                     AND (scheduled_at = 0 OR scheduled_at <= ?)
                   ORDER BY priority DESC, created_at ASC
                   LIMIT 1""",
                (now,)
            ).fetchone()

            if not row:
                return None

            # Атомарно пометить как running
            updated = conn.execute(
                """UPDATE tasks SET status='running', started_at=?
                   WHERE task_id=? AND status IN ('pending','scheduled')""",
                (now, row["task_id"])
            ).rowcount
            conn.commit()

            if updated == 0:
                return None  # другой worker уже взял

            return self._row_to_task(row)
        except Exception as e:
            log.debug("fetch_next_task error: %s", e)
            return None

    def _execute_task(self, task: Task) -> None:
        """Выполнить задачу."""
        log.debug("Executing task %s [%s]", task.task_id[:8], task.tool_name)
        t0 = time.time()

        try:
            result = self._run_task(task)
            elapsed = time.time() - t0

            self._complete_task(task.task_id, result=result, success=True)
            with self._rlock:
                self._stats["completed"] += 1
            log.debug("Task %s done in %.1fs", task.task_id[:8], elapsed)

            # Вызвать callback
            cb = self._callbacks.pop(task.task_id, None)
            if cb:
                try:
                    cb(task.task_id, result, None)
                except Exception as e:
                    log.debug("Task callback error: %s", e)

        except Exception as e:
            elapsed = time.time() - t0
            log.warning("Task %s failed (attempt %d): %s", task.task_id[:8], task.retries + 1, e)

            if task.retries < task.max_retries:
                # Retry с backoff
                delay = RETRY_BASE_SEC * (2 ** task.retries)
                self._retry_task(task.task_id, str(e), delay)
                with self._rlock:
                    self._stats["retried"] += 1
            else:
                self._complete_task(task.task_id, result="", error=str(e), success=False)
                with self._rlock:
                    self._stats["failed"] += 1
                # Callback с ошибкой
                cb = self._callbacks.pop(task.task_id, None)
                if cb:
                    try:
                        cb(task.task_id, "", e)
                    except Exception:
                        pass

    def _run_task(self, task: Task) -> str:
        """Фактически выполнить задачу через ToolRegistry или brain callback."""
        # Попробовать через ToolRegistry
        if self._tool_registry:
            tool = self._tool_registry.find_by_name(task.tool_name)
            if tool:
                result = self._tool_registry.execute(task.tool_name, task.query)
                if result.success:
                    return result.output
                raise RuntimeError(result.error or f"Tool {task.tool_name} failed")

        # Fallback: через brain callback
        if self._brain_callback:
            from brain.orchestrator import OrchestratorRequest
            req = OrchestratorRequest(
                text=task.query,
                source="task_queue",
                session_id=task.session_id,
                user_id=task.user_id,
            )
            resp = self._brain_callback(req)
            return resp.text if hasattr(resp, "text") else str(resp)

        raise RuntimeError(f"No executor for tool '{task.tool_name}'")

    def _complete_task(
        self, task_id: str, result: str = "", error: str = "", success: bool = True
    ) -> None:
        """Обновить статус задачи в БД."""
        status = TaskStatus.DONE.value if success else TaskStatus.FAILED.value
        try:
            conn = self._conn()
            conn.execute(
                """UPDATE tasks SET status=?, result=?, error=?, completed_at=?
                   WHERE task_id=?""",
                (status, result[:2000], error[:500], time.time(), task_id)
            )
            conn.commit()
        except Exception as e:
            log.debug("complete_task DB error: %s", e)

    def _retry_task(self, task_id: str, error: str, delay_sec: float) -> None:
        """Поставить задачу на повтор через delay_sec секунд."""
        try:
            conn = self._conn()
            conn.execute(
                """UPDATE tasks
                   SET status='scheduled', retries=retries+1,
                       error=?, scheduled_at=?, started_at=0
                   WHERE task_id=?""",
                (error[:500], time.time() + delay_sec, task_id)
            )
            conn.commit()
        except Exception as e:
            log.debug("retry_task DB error: %s", e)

    # ── Запросы ───────────────────────────────────────────────────────────────

    def get_status(self, task_id: str) -> Optional[Dict]:
        """Получить статус задачи."""
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if not row:
                return None
            t = self._row_to_task(row)
            return {
                "task_id":    t.task_id,
                "tool_name":  t.tool_name,
                "status":     t.status.value,
                "retries":    t.retries,
                "created_at": t.created_at,
                "started_at": t.started_at,
                "completed_at": t.completed_at,
            }
        except Exception as e:
            log.warning("get_status error: %s", e)
            return None

    def get_result(self, task_id: str) -> Optional[str]:
        """Получить результат завершённой задачи."""
        try:
            conn = self._conn()
            row = conn.execute(
                "SELECT result, status FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            if not row:
                return None
            if row["status"] != TaskStatus.DONE.value:
                return None
            return row["result"]
        except Exception:
            return None

    def wait_for(self, task_id: str, timeout_sec: float = TASK_TIMEOUT) -> Optional[str]:
        """
        Ждать завершения задачи (блокирующий вызов).
        Returns: результат или None если timeout / ошибка.
        """
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            status = self.get_status(task_id)
            if not status:
                return None
            if status["status"] == TaskStatus.DONE.value:
                return self.get_result(task_id)
            if status["status"] in (TaskStatus.FAILED.value, TaskStatus.CANCELLED.value):
                return None
            time.sleep(0.5)
        return None

    def list_tasks(
        self,
        session_id: str = "",
        status:     Optional[TaskStatus] = None,
        limit:      int = 20,
    ) -> List[Dict]:
        """Список задач."""
        try:
            conditions = []
            params: List = []
            if session_id:
                conditions.append("session_id = ?")
                params.append(session_id)
            if status:
                conditions.append("status = ?")
                params.append(status.value)

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            conn = self._conn()
            rows = conn.execute(
                f"""SELECT task_id, tool_name, query, priority, status,
                           retries, created_at, completed_at
                    FROM tasks {where}
                    ORDER BY created_at DESC LIMIT ?""",
                params + [limit]
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            log.warning("list_tasks error: %s", e)
            return []

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _cleanup_loop(self) -> None:
        """Периодически: завершать зависшие задачи + удалять старые."""
        while not self._stop_event.is_set():
            time.sleep(60)      # каждую минуту
            try:
                now  = time.time()
                conn = self._conn()

                # ── Зависшие running-задачи ────────────────────────────────
                stuck = conn.execute(
                    """SELECT task_id, tool_name, started_at FROM tasks
                       WHERE status = 'running'
                         AND started_at > 0
                         AND ? - started_at > ?""",
                    (now, TASK_TIMEOUT)
                ).fetchall()
                for row in stuck:
                    elapsed = now - float(row["started_at"])
                    conn.execute(
                        """UPDATE tasks SET status='failed', error=?, completed_at=?
                           WHERE task_id=?""",
                        (f"Timeout after {elapsed:.0f}s (max={TASK_TIMEOUT}s)",
                         now, row["task_id"])
                    )
                    log.warning("Task %s [%s] stuck %.0fs — marked failed",
                                row["task_id"][:8], row["tool_name"], elapsed)
                if stuck:
                    conn.commit()
                    with self._rlock:
                        self._stats["failed"] += len(stuck)

                # ── Старые завершённые задачи ──────────────────────────────
                cutoff  = now - CLEANUP_AFTER_DAYS * 86400
                deleted = conn.execute(
                    """DELETE FROM tasks
                       WHERE status IN ('done','failed','cancelled')
                         AND completed_at < ? AND completed_at > 0""",
                    (cutoff,)
                ).rowcount
                conn.commit()
                if deleted:
                    log.info("TaskQueue cleanup: removed %d old tasks", deleted)

            except Exception as e:
                log.debug("Cleanup loop error: %s", e)

    # ── Статистика ────────────────────────────────────────────────────────────

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        try:
            metadata = json.loads(row["metadata"] or "{}")
        except Exception:
            metadata = {}
        return Task(
            task_id=row["task_id"],
            tool_name=row["tool_name"],
            query=row["query"],
            priority=int(row["priority"]),
            status=TaskStatus(row["status"]),
            retries=int(row["retries"]),
            max_retries=int(row["max_retries"]),
            result=row["result"] or "",
            error=row["error"] or "",
            session_id=row["session_id"] or "",
            user_id=row["user_id"] or "",
            metadata=metadata,
            created_at=float(row["created_at"]),
            scheduled_at=float(row["scheduled_at"] or 0),
            started_at=float(row["started_at"] or 0),
            completed_at=float(row["completed_at"] or 0),
        )

    def get_stats(self) -> Dict:
        with self._rlock:
            s = dict(self._stats)
        try:
            conn = self._conn()
            pending = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('pending','scheduled')"
            ).fetchone()[0]
            running = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status='running'"
            ).fetchone()[0]
        except Exception:
            pending = running = 0
        s.update({"pending": pending, "running": running})
        return s

    def get_report(self) -> str:
        s = self.get_stats()
        return (
            f"📋 **Task Queue**\n"
            f"  В очереди: {s.get('pending', 0)}\n"
            f"  Выполняется: {s.get('running', 0)}\n"
            f"  Завершено: {s.get('completed', 0)}\n"
            f"  Ошибок: {s.get('failed', 0)}\n"
            f"  Повторов: {s.get('retried', 0)}"
        )