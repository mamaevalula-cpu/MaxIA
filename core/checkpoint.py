# -*- coding: utf-8 -*-
"""
core/checkpoint.py — Lightweight checkpoint & recovery system.

Provides:
  - Save named checkpoints to SQLite (non-production-mutating)
  - Load latest verified checkpoint
  - Read-only recovery mode
  - Checkpoint integrity validation (hash)
  - Auto-expiry of stale checkpoints

Usage:
    from core.checkpoint import checkpoints

    # Save before a mutation
    ckpt_id = checkpoints.save("before_deploy", {"stage": "routing_change", "config": {...}})

    # Restore
    state = checkpoints.load(ckpt_id)

    # Get latest verified checkpoint
    state = checkpoints.latest("before_deploy")

    # Read-only mode (stops mutations)
    checkpoints.enter_recovery_mode()
    checkpoints.exit_recovery_mode()  # operator only
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("core.checkpoint")

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH             = Path("data/checkpoints.db")
MAX_CHECKPOINTS     = 100       # per label
RETENTION_DAYS      = 7         # auto-expire after N days
RECOVERY_MODE_TTL   = 3600      # max recovery mode duration (seconds)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class Checkpoint:
    checkpoint_id:  str
    label:          str
    state:          Dict[str, Any]
    created_at:     float
    hash:           str
    verified:       bool = False

    def verify_integrity(self) -> bool:
        """Recompute hash and compare."""
        expected = _compute_hash(self.state)
        ok = expected == self.hash
        if not ok:
            log.error("Checkpoint integrity FAILED: id=%s label=%s", self.checkpoint_id, self.label)
        return ok


def _compute_hash(state: Dict[str, Any]) -> str:
    raw = json.dumps(state, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


# ── CheckpointManager ─────────────────────────────────────────────────────────

class CheckpointManager:
    """
    Thread-safe checkpoint manager backed by SQLite.
    Singleton — use `checkpoints` module-level export.
    """

    _instance: Optional[CheckpointManager] = None
    _init_lock = threading.Lock()

    def __new__(cls) -> CheckpointManager:
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._ready = False
            return cls._instance

    def __init__(self) -> None:
        if self._ready:
            return
        self._ready = True
        self._lock = threading.Lock()
        self._recovery_mode = False
        self._recovery_started: Optional[float] = None
        self._db: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                label         TEXT NOT NULL,
                state_json    TEXT NOT NULL,
                hash          TEXT NOT NULL,
                created_at    REAL NOT NULL,
                verified      INTEGER NOT NULL DEFAULT 0
            )
        """)
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_label ON checkpoints(label, created_at DESC)")
        self._db.commit()
        log.info("CheckpointManager initialized: db=%s", DB_PATH)

    # ── Save / Load ───────────────────────────────────────────────────────────

    def save(self, label: str, state: Dict[str, Any]) -> str:
        """
        Save a checkpoint. Returns checkpoint_id.
        Thread-safe. Does NOT mutate production state.
        """
        ckpt_id = str(uuid.uuid4())[:8]
        h = _compute_hash(state)
        ts = time.time()
        state_json = json.dumps(state, ensure_ascii=False)

        with self._lock:
            self._db.execute(
                "INSERT INTO checkpoints VALUES (?,?,?,?,?,?)",
                (ckpt_id, label, state_json, h, ts, 1)
            )
            self._db.commit()
            self._prune_old(label)

        log.info("Checkpoint saved: id=%s label=%s hash=%s", ckpt_id, label, h)
        return ckpt_id

    def load(self, checkpoint_id: str) -> Optional[Checkpoint]:
        """Load checkpoint by ID and verify integrity."""
        with self._lock:
            row = self._db.execute(
                "SELECT checkpoint_id, label, state_json, hash, created_at, verified "
                "FROM checkpoints WHERE checkpoint_id=?",
                (checkpoint_id,)
            ).fetchone()

        if not row:
            log.warning("Checkpoint not found: id=%s", checkpoint_id)
            return None

        ckpt = Checkpoint(
            checkpoint_id=row[0],
            label=row[1],
            state=json.loads(row[2]),
            hash=row[3],
            created_at=row[4],
            verified=bool(row[5]),
        )
        if not ckpt.verify_integrity():
            log.error("Checkpoint integrity check FAILED for id=%s — refusing to return", checkpoint_id)
            return None
        return ckpt

    def latest(self, label: str) -> Optional[Checkpoint]:
        """Return the most recent verified checkpoint for a label."""
        with self._lock:
            row = self._db.execute(
                "SELECT checkpoint_id FROM checkpoints "
                "WHERE label=? AND verified=1 ORDER BY created_at DESC LIMIT 1",
                (label,)
            ).fetchone()
        if not row:
            return None
        return self.load(row[0])

    def list_labels(self) -> list[str]:
        """List all distinct checkpoint labels."""
        with self._lock:
            rows = self._db.execute(
                "SELECT DISTINCT label FROM checkpoints ORDER BY label"
            ).fetchall()
        return [r[0] for r in rows]

    def list_checkpoints(self, label: str, limit: int = 10) -> list[dict]:
        """List recent checkpoints for a label."""
        with self._lock:
            rows = self._db.execute(
                "SELECT checkpoint_id, label, hash, created_at, verified "
                "FROM checkpoints WHERE label=? ORDER BY created_at DESC LIMIT ?",
                (label, limit)
            ).fetchall()
        return [
            {
                "checkpoint_id": r[0], "label": r[1],
                "hash": r[2], "created_at": r[3], "verified": bool(r[4]),
                "age_s": round(time.time() - r[3], 0),
            }
            for r in rows
        ]

    # ── Recovery Mode ─────────────────────────────────────────────────────────

    def enter_recovery_mode(self) -> None:
        """Stop all mutations. Operator must call exit_recovery_mode() to resume."""
        with self._lock:
            if not self._recovery_mode:
                self._recovery_mode = True
                self._recovery_started = time.time()
                log.warning("READ-ONLY RECOVERY MODE activated")

    def exit_recovery_mode(self) -> None:
        """Operator: restore normal write access."""
        with self._lock:
            if self._recovery_mode:
                self._recovery_mode = False
                elapsed = time.time() - (self._recovery_started or time.time())
                log.info("Recovery mode deactivated after %.0fs", elapsed)
                self._recovery_started = None

    def assert_not_recovery(self) -> None:
        """Raise RuntimeError if in recovery mode. Call before any write operation."""
        with self._lock:
            if self._recovery_mode:
                elapsed = time.time() - (self._recovery_started or time.time())
                # Auto-exit if TTL exceeded
                if elapsed > RECOVERY_MODE_TTL:
                    self._recovery_mode = False
                    log.warning("Recovery mode auto-expired after %.0fs", elapsed)
                    return
                raise RuntimeError(
                    f"System is in READ-ONLY RECOVERY MODE "
                    f"(active for {elapsed:.0f}s). "
                    "Call checkpoints.exit_recovery_mode() to resume writes."
                )

    @property
    def is_recovery_mode(self) -> bool:
        return self._recovery_mode

    # ── Maintenance ───────────────────────────────────────────────────────────

    def _prune_old(self, label: str) -> None:
        """Keep only MAX_CHECKPOINTS per label, remove expired ones."""
        cutoff = time.time() - RETENTION_DAYS * 86400
        self._db.execute(
            "DELETE FROM checkpoints WHERE created_at < ? AND label=?",
            (cutoff, label)
        )
        # Keep only most recent MAX_CHECKPOINTS
        rows = self._db.execute(
            "SELECT checkpoint_id FROM checkpoints WHERE label=? ORDER BY created_at DESC",
            (label,)
        ).fetchall()
        if len(rows) > MAX_CHECKPOINTS:
            old_ids = [r[0] for r in rows[MAX_CHECKPOINTS:]]
            self._db.executemany(
                "DELETE FROM checkpoints WHERE checkpoint_id=?",
                [(i,) for i in old_ids]
            )
        self._db.commit()

    def status(self) -> dict:
        with self._lock:
            count = self._db.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            labels = self._db.execute(
                "SELECT DISTINCT label FROM checkpoints"
            ).fetchall()
        return {
            "total_checkpoints":  count,
            "labels":             [r[0] for r in labels],
            "recovery_mode":      self._recovery_mode,
            "recovery_age_s":     round(time.time() - self._recovery_started, 1)
                                  if self._recovery_started else None,
            "db_path":            str(DB_PATH),
        }


# ── Singleton export ──────────────────────────────────────────────────────────

checkpoints = CheckpointManager()
