"""
core/agent_registry.py  —  Agent Registry for Корпорация MaxAI v11.

Stores registered agents, their capabilities, status and version.
Backed by SQLite for persistence across restarts.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "agent_registry.db"


class AgentStatus(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    OFFLINE = "offline"
    ERROR = "error"


@dataclass
class AgentRecord:
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    capabilities: List[str] = field(default_factory=list)
    version: str = "1.0.0"
    status: AgentStatus = AgentStatus.IDLE
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    tasks_completed: int = 0
    tasks_failed: int = 0
    metadata: Dict = field(default_factory=dict)


class AgentRegistry:
    """
    Persistent registry for agents.

    Usage:
        registry = AgentRegistry()
        registry.init()
        agent_id = registry.register(name="summarizer", capabilities=["text", "summarize"])
    """

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                capabilities TEXT,
                version TEXT,
                status TEXT,
                registered_at REAL,
                last_seen REAL,
                tasks_completed INTEGER DEFAULT 0,
                tasks_failed INTEGER DEFAULT 0,
                metadata TEXT
            )
        """)
        self._conn.commit()
        logger.info("AgentRegistry initialised at %s", self._db_path)

    def register(self, name: str, description: str = "",
                  capabilities: List[str] | None = None,
                  version: str = "1.0.0",
                  metadata: Dict | None = None) -> str:
        rec = AgentRecord(
            name=name,
            description=description,
            capabilities=capabilities or [],
            version=version,
            metadata=metadata or {},
        )
        self._conn.execute("""
            INSERT OR REPLACE INTO agents
            (agent_id, name, description, capabilities, version, status,
             registered_at, last_seen, tasks_completed, tasks_failed, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec.agent_id, rec.name, rec.description,
            json.dumps(rec.capabilities), rec.version, rec.status.value,
            rec.registered_at, rec.last_seen,
            rec.tasks_completed, rec.tasks_failed,
            json.dumps(rec.metadata),
        ))
        self._conn.commit()
        logger.info("Agent registered: %s (%s)", name, rec.agent_id)
        return rec.agent_id

    def update_status(self, agent_id: str, status: AgentStatus) -> None:
        self._conn.execute(
            "UPDATE agents SET status=?, last_seen=? WHERE agent_id=?",
            (status.value, time.time(), agent_id)
        )
        self._conn.commit()

    def increment_counter(self, agent_id: str, success: bool = True) -> None:
        col = "tasks_completed" if success else "tasks_failed"
        self._conn.execute(
            f"UPDATE agents SET {col}={col}+1, last_seen=? WHERE agent_id=?",
            (time.time(), agent_id)
        )
        self._conn.commit()

    def get(self, agent_id: str) -> Optional[AgentRecord]:
        row = self._conn.execute(
            "SELECT * FROM agents WHERE agent_id=?", (agent_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def list_active(self) -> List[AgentRecord]:
        rows = self._conn.execute(
            "SELECT * FROM agents WHERE status != 'offline' ORDER BY last_seen DESC"
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def _row_to_record(self, row) -> AgentRecord:
        cols = ["agent_id", "name", "description", "capabilities", "version",
                "status", "registered_at", "last_seen", "tasks_completed",
                "tasks_failed", "metadata"]
        d = dict(zip(cols, row))
        d["capabilities"] = json.loads(d["capabilities"] or "[]")
        d["metadata"] = json.loads(d["metadata"] or "{}")
        d["status"] = AgentStatus(d["status"])
        return AgentRecord(**d)
