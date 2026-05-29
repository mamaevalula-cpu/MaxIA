# -*- coding: utf-8 -*-
"""
core/chat_history.py — Persistent chat & task history (component 1/8).

Stores every conversation turn and task run in SQLite with WAL mode.
Auto-compresses sessions older than COMPRESS_AFTER_MESSAGES into summaries
to keep the DB lean and context cheap.

Usage:
    from core.chat_history import history

    sid = history.new_session(user_id="tg:12345", task_type="chat")
    history.add_turn(sid, role="user",    content="Hello", tokens=5)
    history.add_turn(sid, role="assistant", content="Hi!", tokens=8, provider="deepseek")

    msgs = history.get_session(sid)          # list of dicts
    summary = history.get_summary(sid)       # compressed text (if compressed)
    stats = history.stats()                  # global stats dict
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("core.chat_history")

# ── Config ────────────────────────────────────────────────────────────────────
DB_PATH                = Path("data/chat_history.db")
COMPRESS_AFTER_MESSAGES = 30      # auto-compress session after N turns
MAX_SUMMARY_LEN        = 800      # max chars in a session summary
RETENTION_DAYS         = 30       # drop sessions older than N days


# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL DEFAULT '',
    task_type    TEXT NOT NULL DEFAULT 'chat',
    created_at   REAL NOT NULL,
    updated_at   REAL NOT NULL,
    turn_count   INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    compressed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    msg_id       TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL REFERENCES sessions(session_id),
    role         TEXT NOT NULL,
    content      TEXT NOT NULL,
    tokens       INTEGER NOT NULL DEFAULT 0,
    provider     TEXT NOT NULL DEFAULT '',
    ts           REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    session_id   TEXT PRIMARY KEY REFERENCES sessions(session_id),
    summary_text TEXT NOT NULL,
    token_count  INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
"""


# ── ChatHistory ───────────────────────────────────────────────────────────────

class ChatHistory:
    """Thread-safe persistent chat & task history backed by SQLite."""

    def __init__(self, db_path: Path = DB_PATH):
        self._db_path = db_path
        self._lock = threading.RLock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        log.info("ChatHistory initialized | db=%s", db_path)

    # ── DB helpers ─────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                conn.executescript(_SCHEMA)
                conn.commit()
            finally:
                conn.close()

    # ── Public API ─────────────────────────────────────────────────────────

    def new_session(self, user_id: str = "", task_type: str = "chat") -> str:
        """Create a new session; returns session_id."""
        sid = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO sessions VALUES (?,?,?,?,?,0,0,0)",
                    (sid, user_id, task_type, now, now)
                )
                conn.commit()
            finally:
                conn.close()
        return sid

    def add_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        tokens: int = 0,
        provider: str = "",
    ) -> str:
        """Append a message turn; returns msg_id. Auto-compresses if needed."""
        msg_id = str(uuid.uuid4())
        now = time.time()
        with self._lock:
            conn = self._conn()
            try:
                conn.execute(
                    "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                    (msg_id, session_id, role, content, tokens, provider, now)
                )
                conn.execute(
                    """UPDATE sessions
                       SET turn_count=turn_count+1,
                           total_tokens=total_tokens+?,
                           updated_at=?
                       WHERE session_id=?""",
                    (tokens, now, session_id)
                )
                conn.commit()

                # Check if we should compress
                row = conn.execute(
                    "SELECT turn_count, compressed FROM sessions WHERE session_id=?",
                    (session_id,)
                ).fetchone()
                if row and row["turn_count"] >= COMPRESS_AFTER_MESSAGES and not row["compressed"]:
                    self._compress_session(conn, session_id)
            finally:
                conn.close()
        return msg_id

    def get_session(
        self, session_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Return recent messages for a session (newest last)."""
        with self._lock:
            conn = self._conn()
            try:
                rows = conn.execute(
                    """SELECT role, content, tokens, provider, ts
                       FROM messages WHERE session_id=?
                       ORDER BY ts DESC LIMIT ?""",
                    (session_id, limit)
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in reversed(rows)]

    def get_summary(self, session_id: str) -> Optional[str]:
        """Return compressed summary for a session (if compressed)."""
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT summary_text FROM summaries WHERE session_id=?",
                    (session_id,)
                ).fetchone()
            finally:
                conn.close()
        return row["summary_text"] if row else None

    def get_context(self, session_id: str, max_tokens: int = 1500) -> str:
        """
        Build compact context string for LLM prompt injection.
        Uses summary + last few turns, staying under max_tokens.
        """
        parts: List[str] = []
        budget = max_tokens

        # Try summary first
        summary = self.get_summary(session_id)
        if summary:
            summary_tokens = len(summary) // 4
            if summary_tokens < budget:
                parts.append(f"[Session summary]\n{summary}")
                budget -= summary_tokens

        # Append recent turns fitting in remaining budget
        msgs = self.get_session(session_id, limit=20)
        for msg in reversed(msgs):
            text = f"{msg['role'].upper()}: {msg['content']}"
            t = len(text) // 4
            if t > budget:
                break
            parts.insert(0 if not summary else 1, text)
            budget -= t

        return "\n".join(parts)

    def recent_sessions(self, user_id: str = "", limit: int = 10) -> List[Dict]:
        """List recent sessions for a user."""
        with self._lock:
            conn = self._conn()
            try:
                q = "SELECT * FROM sessions WHERE 1=1"
                args: list = []
                if user_id:
                    q += " AND user_id=?"
                    args.append(user_id)
                q += " ORDER BY updated_at DESC LIMIT ?"
                args.append(limit)
                rows = conn.execute(q, args).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        """Global statistics."""
        with self._lock:
            conn = self._conn()
            try:
                total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
                total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                total_tokens   = conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM sessions").fetchone()[0]
                compressed     = conn.execute("SELECT COUNT(*) FROM sessions WHERE compressed=1").fetchone()[0]
                day_ago        = time.time() - 86400
                recent_sess    = conn.execute(
                    "SELECT COUNT(*) FROM sessions WHERE updated_at>?", (day_ago,)
                ).fetchone()[0]
            finally:
                conn.close()
        return {
            "total_sessions":    total_sessions,
            "total_messages":    total_messages,
            "total_tokens_seen": total_tokens,
            "compressed_sessions": compressed,
            "active_last_24h":   recent_sess,
            "db_path":           str(self._db_path),
        }

    def purge_old_sessions(self, days: int = RETENTION_DAYS) -> int:
        """Delete sessions older than N days; returns count deleted."""
        cutoff = time.time() - days * 86400
        with self._lock:
            conn = self._conn()
            try:
                # Delete messages first (no ON DELETE CASCADE in older SQLite)
                conn.execute(
                    """DELETE FROM messages WHERE session_id IN
                       (SELECT session_id FROM sessions WHERE updated_at < ?)""",
                    (cutoff,)
                )
                conn.execute(
                    """DELETE FROM summaries WHERE session_id IN
                       (SELECT session_id FROM sessions WHERE updated_at < ?)""",
                    (cutoff,)
                )
                cur = conn.execute(
                    "DELETE FROM sessions WHERE updated_at < ?", (cutoff,)
                )
                conn.commit()
                count = cur.rowcount
            finally:
                conn.close()
        if count:
            log.info("Purged %d old sessions (>%d days)", count, days)
        return count

    # ── Internal ───────────────────────────────────────────────────────────

    def _compress_session(self, conn: sqlite3.Connection, session_id: str) -> None:
        """Compress a session into a summary (called inside lock, reuses conn)."""
        rows = conn.execute(
            """SELECT role, content FROM messages
               WHERE session_id=? ORDER BY ts ASC""",
            (session_id,)
        ).fetchall()

        # Build simple summary: keep first exchange + last 5 exchanges
        turns = [(r["role"], r["content"]) for r in rows]
        keep = turns[:2] + turns[-10:] if len(turns) > 12 else turns
        text_parts = [f"{role.upper()}: {content[:200]}" for role, content in keep]
        summary = "\n".join(text_parts)[:MAX_SUMMARY_LEN]

        token_count = len(summary) // 4

        # Upsert summary
        conn.execute(
            """INSERT INTO summaries VALUES (?,?,?,?)
               ON CONFLICT(session_id) DO UPDATE SET
               summary_text=excluded.summary_text,
               token_count=excluded.token_count,
               created_at=excluded.created_at""",
            (session_id, summary, token_count, time.time())
        )

        # Delete old messages (keep last 10 for live context)
        keep_ids = conn.execute(
            """SELECT msg_id FROM messages WHERE session_id=?
               ORDER BY ts DESC LIMIT 10""",
            (session_id,)
        ).fetchall()
        keep_id_list = [r["msg_id"] for r in keep_ids]
        if keep_id_list:
            placeholders = ",".join("?" * len(keep_id_list))
            conn.execute(
                f"DELETE FROM messages WHERE session_id=? AND msg_id NOT IN ({placeholders})",
                [session_id] + keep_id_list
            )

        conn.execute(
            "UPDATE sessions SET compressed=1 WHERE session_id=?",
            (session_id,)
        )
        conn.commit()
        log.info("Session compressed | sid=%s turns=%d", session_id, len(turns))


# ── Singleton ─────────────────────────────────────────────────────────────────
history = ChatHistory()
