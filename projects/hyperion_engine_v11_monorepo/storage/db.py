"""
storage/db.py  —  Database helpers for Корпорация MaxAI v11.

SQLite-based persistent task journal and replay snapshots.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "hyperion.db"


class HyperionDB:
    """Persistent storage for tasks and audit events."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS task_journal (
                task_id     TEXT PRIMARY KEY,
                agent_name  TEXT,
                capability  TEXT,
                payload     TEXT,
                status      TEXT,
                result      TEXT,
                error       TEXT,
                retries     INTEGER DEFAULT 0,
                created_at  REAL,
                updated_at  REAL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type  TEXT,
                entity_id   TEXT,
                details     TEXT,
                ts          REAL
            );

            CREATE TABLE IF NOT EXISTS agent_improvement (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id     TEXT,
                suggestion   TEXT,
                applied      INTEGER DEFAULT 0,
                created_at   REAL
            );
        """)
        self._conn.commit()
        logger.info("HyperionDB initialised at %s", self._db_path)

    def log_task(self, task_id: str, agent_name: str, capability: str,
                  payload: Dict, status: str, result: Any = None,
                  error: str = None, retries: int = 0) -> None:
        now = time.time()
        self._conn.execute("""
            INSERT OR REPLACE INTO task_journal
            (task_id, agent_name, capability, payload, status, result, error,
             retries, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(
                (SELECT created_at FROM task_journal WHERE task_id=?), ?
            ), ?)
        """, (task_id, agent_name, capability, json.dumps(payload), status,
                json.dumps(result), error, retries, task_id, now, now))
        self._conn.commit()

    def log_audit(self, event_type: str, entity_id: str,
                   details: Dict | None = None) -> None:
        self._conn.execute(
            "INSERT INTO audit_log (event_type, entity_id, details, ts) VALUES (?, ?, ?, ?)",
            (event_type, entity_id, json.dumps(details or {}), time.time())
        )
        self._conn.commit()

    def add_improvement(self, agent_id: str, suggestion: str) -> None:
        self._conn.execute(
            "INSERT INTO agent_improvement (agent_id, suggestion, created_at) VALUES (?, ?, ?)",
            (agent_id, suggestion, time.time())
        )
        self._conn.commit()

    def get_task_stats(self) -> Dict[str, int]:
        row = self._conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status='timeout' THEN 1 ELSE 0 END) as timeout
            FROM task_journal
        """).fetchone()
        return {"total": row[0], "completed": row[1], "failed": row[2], "timeout": row[3]}
