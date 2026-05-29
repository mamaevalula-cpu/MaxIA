# -*- coding: utf-8 -*-
"""
core/project_registry.py — Persistent project registry.

Every "project" in APEX AI has a lifecycle:
  created → running → paused / failed / archived

Registry survives restarts, tracks state, allows rollback.
Used by: dashboard, telegram_agent, orchestrator, self_healing.

Usage:
    reg = ProjectRegistry.get()
    pid = reg.create("coffee_ui", "UI for coffee tracking", {"url": "..."})
    reg.set_status(pid, "running")
    projects = reg.list_active()
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("core.project_registry")

DB_PATH = Path("data/projects.db")


class ProjectStatus(str, Enum):
    CREATED  = "created"
    RUNNING  = "running"
    PAUSED   = "paused"
    FAILED   = "failed"
    ARCHIVED = "archived"


@dataclass
class Project:
    project_id:   str
    name:         str
    description:  str
    project_type: str           # "ui" | "bot" | "trading" | "task" | "custom"
    status:       ProjectStatus = ProjectStatus.CREATED
    config:       Dict[str, Any] = field(default_factory=dict)
    tags:         List[str]      = field(default_factory=list)
    created_at:   float          = field(default_factory=time.time)
    updated_at:   float          = field(default_factory=time.time)
    started_at:   float          = 0.0
    error:        str            = ""
    version:      int            = 1   # increments on each config change

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class ProjectRegistry:
    """Singleton. Persistent SQLite-backed project registry."""

    _instance: Optional["ProjectRegistry"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db   = str(DB_PATH)
        self._rlock = threading.RLock()
        self._local = threading.local()
        self._init_db()
        self._recover()
        log.info("ProjectRegistry initialized (db=%s)", self._db)

    @classmethod
    def get(cls) -> "ProjectRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            c = sqlite3.connect(self._db, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            self._local.conn = c
        return self._local.conn

    def _init_db(self) -> None:
        with sqlite3.connect(self._db) as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    project_id   TEXT PRIMARY KEY,
                    name         TEXT NOT NULL,
                    description  TEXT DEFAULT '',
                    project_type TEXT DEFAULT 'custom',
                    status       TEXT DEFAULT 'created',
                    config       TEXT DEFAULT '{}',
                    tags         TEXT DEFAULT '[]',
                    created_at   REAL NOT NULL,
                    updated_at   REAL NOT NULL,
                    started_at   REAL DEFAULT 0,
                    error        TEXT DEFAULT '',
                    version      INTEGER DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_proj_status ON projects(status);
                CREATE INDEX IF NOT EXISTS idx_proj_type   ON projects(project_type);

                CREATE TABLE IF NOT EXISTS project_events (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    event      TEXT NOT NULL,
                    detail     TEXT DEFAULT '',
                    ts         REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evt_proj ON project_events(project_id, ts DESC);
            """)

    def _recover(self) -> None:
        """On startup: mark crash-failed projects (were running but service restarted)."""
        try:
            with sqlite3.connect(self._db) as c:
                rows = c.execute(
                    "SELECT project_id FROM projects WHERE status='running'"
                ).fetchall()
                if rows:
                    # Keep autonomous/always-on projects running across restarts
                    c.execute(
                        "UPDATE projects SET status='paused', updated_at=? "
                        "WHERE status='running' "
                        "AND config NOT LIKE '%\"autonomous\": true%' "
                        "AND config NOT LIKE '%\"run_24_7\": true%'",
                        (time.time(),)
                    )
                    log.info("ProjectRegistry: projects moved running->paused on restart (autonomous kept running)")
        except Exception as e:
            log.debug("Registry recover error: %s", e)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create(
        self,
        name:         str,
        description:  str  = "",
        project_type: str  = "custom",
        config:       Dict = None,
        tags:         List = None,
    ) -> str:
        """Create a new project. Returns project_id."""
        pid  = str(uuid.uuid4())[:16]
        now  = time.time()
        proj = Project(
            project_id   = pid,
            name         = name,
            description  = description,
            project_type = project_type,
            config       = config or {},
            tags         = tags or [],
            created_at   = now,
            updated_at   = now,
        )
        try:
            c = self._conn()
            c.execute(
                """INSERT INTO projects
                   (project_id, name, description, project_type, status,
                    config, tags, created_at, updated_at, version)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (pid, name, description, project_type, proj.status.value,
                 json.dumps(proj.config), json.dumps(proj.tags), now, now, 1)
            )
            c.commit()
            self._log_event(pid, "created", f"type={project_type}")
            log.info("Project created: %s [%s] '%s'", pid[:8], project_type, name)
        except Exception as e:
            log.error("create project failed: %s", e)
        return pid

    def set_status(self, project_id: str, status: str, error: str = "") -> bool:
        """Transition project status. Returns True if updated."""
        try:
            now = time.time()
            st  = ProjectStatus(status)
            extras = ""
            params: list = [st.value, error, now]
            if st == ProjectStatus.RUNNING:
                extras = ", started_at=?"
                params.append(now)
            c = self._conn()
            rows = c.execute(
                f"UPDATE projects SET status=?, error=?, updated_at=?{extras}, version=version+1 "
                f"WHERE project_id=?",
                params + [project_id]
            ).rowcount
            c.commit()
            if rows:
                self._log_event(project_id, f"status→{status}", error[:100] if error else "")
            return rows > 0
        except Exception as e:
            log.warning("set_status error: %s", e)
            return False

    def update_config(self, project_id: str, config: Dict) -> bool:
        """Update project config and bump version."""
        try:
            now = time.time()
            c   = self._conn()
            rows = c.execute(
                "UPDATE projects SET config=?, updated_at=?, version=version+1 WHERE project_id=?",
                (json.dumps(config, ensure_ascii=False), now, project_id)
            ).rowcount
            c.commit()
            if rows:
                self._log_event(project_id, "config_updated", "")
            return rows > 0
        except Exception as e:
            log.warning("update_config error: %s", e)
            return False

    def get_project(self, project_id: str) -> Optional[Project]:
        try:
            row = self._conn().execute(
                "SELECT * FROM projects WHERE project_id=?", (project_id,)
            ).fetchone()
            return self._row(row) if row else None
        except Exception:
            return None

    def list_all(self, status: str = None, project_type: str = None,
                 limit: int = 50) -> List[Dict]:
        try:
            conds, params = [], []
            if status:
                conds.append("status=?"); params.append(status)
            if project_type:
                conds.append("project_type=?"); params.append(project_type)
            where = ("WHERE " + " AND ".join(conds)) if conds else ""
            rows = self._conn().execute(
                f"SELECT * FROM projects {where} ORDER BY updated_at DESC LIMIT ?",
                params + [limit]
            ).fetchall()
            return [self._row(r).to_dict() for r in rows]
        except Exception as e:
            log.warning("list_all error: %s", e)
            return []

    def list_active(self) -> List[Dict]:
        return self.list_all(status="running")

    def delete(self, project_id: str) -> bool:
        try:
            c = self._conn()
            rows = c.execute("DELETE FROM projects WHERE project_id=?", (project_id,)).rowcount
            c.commit()
            return rows > 0
        except Exception:
            return False

    def get_events(self, project_id: str, limit: int = 20) -> List[Dict]:
        try:
            rows = self._conn().execute(
                "SELECT * FROM project_events WHERE project_id=? ORDER BY ts DESC LIMIT ?",
                (project_id, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    def get_stats(self) -> Dict:
        try:
            c = self._conn()
            total   = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            running = c.execute("SELECT COUNT(*) FROM projects WHERE status='running'").fetchone()[0]
            failed  = c.execute("SELECT COUNT(*) FROM projects WHERE status='failed'").fetchone()[0]
            return {"total": total, "running": running, "failed": failed}
        except Exception:
            return {}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _log_event(self, project_id: str, event: str, detail: str) -> None:
        try:
            self._conn().execute(
                "INSERT INTO project_events (project_id, event, detail, ts) VALUES (?,?,?,?)",
                (project_id, event, detail, time.time())
            )
            self._conn().commit()
        except Exception:
            pass

    def _row(self, row: sqlite3.Row) -> Project:
        try:
            config = json.loads(row["config"] or "{}")
            tags   = json.loads(row["tags"]   or "[]")
        except Exception:
            config, tags = {}, []
        return Project(
            project_id   = row["project_id"],
            name         = row["name"],
            description  = row["description"] or "",
            project_type = row["project_type"] or "custom",
            status       = ProjectStatus(row["status"]),
            config       = config,
            tags         = tags,
            created_at   = float(row["created_at"]),
            updated_at   = float(row["updated_at"]),
            started_at   = float(row["started_at"] or 0),
            error        = row["error"] or "",
            version      = int(row["version"] or 1),
        )
