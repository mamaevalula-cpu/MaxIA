# -*- coding: utf-8 -*-
"""
training/rollback_manager.py — Откат изменений в базе знаний.

Перед каждой записью/обновлением/удалением создаётся снимок состояния.
Если outcome evaluation показывает отрицательный результат — откат.

Возможности:
  • snapshot_before_write(entry)    — сохранить снимок до изменения
  • rollback(entry_id)              — восстановить из последнего снимка
  • rollback_batch(entry_ids)       — откат нескольких записей
  • list_snapshots(entry_id)        — история снимков для записи
  • expire_old_snapshots(days=7)    — очистка старых снимков

Снимки хранятся в отдельной таблице `knowledge_snapshots` в той же БД.
Поддерживает до 5 снимков на одну запись (FIFO).

Использование:
    rm = RollbackManager.get()
    rm.snapshot_before_write(entry)
    # ... изменяем/сохраняем entry ...
    # если что-то пошло не так:
    rm.rollback(entry.id)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("training.rollback")

_DB_PATH = Path(__file__).parent.parent / "data" / "memory.db"
_MAX_SNAPSHOTS_PER_ENTRY = 5
_EXPIRE_DAYS = 7


class RollbackManager:
    """
    Singleton — управление откатами изменений в knowledge-базе.
    Создаёт снимки ДО изменения и восстанавливает при необходимости.
    """

    _instance: Optional["RollbackManager"] = None

    @classmethod
    def get(cls) -> "RollbackManager":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._ensure_table()
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_table(self) -> None:
        """Создать таблицу снимков если не существует."""
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_snapshots (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_id    INTEGER NOT NULL,
                    snapshot    TEXT    NOT NULL,   -- JSON всей KnowledgeEntry
                    reason      TEXT    DEFAULT '',  -- почему снимок сделан
                    ts          REAL    NOT NULL,
                    restored    INTEGER DEFAULT 0    -- 1 если уже откатывали
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_snap_entry "
                "ON knowledge_snapshots(entry_id, ts)"
            )

    # ── Создание снимков ──────────────────────────────────────────────────────

    def snapshot_before_write(self, entry, reason: str = "pre_write") -> int:
        """
        Сохранить снимок KnowledgeEntry перед любым изменением.
        Возвращает snapshot_id.
        """
        entry_id = getattr(entry, "id", 0)
        if not entry_id:
            return 0   # новая запись — откатывать нечего, только удалить

        data = self._entry_to_dict(entry)
        snap_json = json.dumps(data, ensure_ascii=False)

        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO knowledge_snapshots(entry_id, snapshot, reason, ts) "
                "VALUES (?, ?, ?, ?)",
                (entry_id, snap_json, reason, time.time()),
            )
            snap_id = cur.lastrowid

            # Удалить старые снимки сверх лимита (FIFO)
            conn.execute("""
                DELETE FROM knowledge_snapshots
                WHERE entry_id = ?
                  AND id NOT IN (
                      SELECT id FROM knowledge_snapshots
                      WHERE entry_id = ?
                      ORDER BY ts DESC
                      LIMIT ?
                  )
            """, (entry_id, entry_id, _MAX_SNAPSHOTS_PER_ENTRY))

        log.debug("Snapshot #%d created for entry_id=%d (reason=%s)",
                  snap_id, entry_id, reason)
        return snap_id

    def snapshot_new_entry(self, entry_id: int, reason: str = "new_entry") -> None:
        """
        Записать факт создания новой записи чтобы её можно было удалить при откате.
        Snapshot содержит только entry_id (для последующего DELETE).
        """
        if not entry_id:
            return
        data = {"__new_entry__": True, "id": entry_id, "ts_created": time.time()}
        snap_json = json.dumps(data)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO knowledge_snapshots(entry_id, snapshot, reason, ts) "
                "VALUES (?, ?, ?, ?)",
                (entry_id, snap_json, reason, time.time()),
            )
        log.debug("New-entry snapshot created for entry_id=%d", entry_id)

    # ── Откат ─────────────────────────────────────────────────────────────────

    def rollback(self, entry_id: int, reason: str = "outcome_negative") -> bool:
        """
        Откатить последний снимок для entry_id.
        Возвращает True если откат выполнен успешно.
        """
        snap = self._get_latest_snapshot(entry_id)
        if not snap:
            log.warning("Rollback requested for entry_id=%d but no snapshot found",
                        entry_id)
            return False

        data = json.loads(snap["snapshot"])

        # Если это была НОВАЯ запись — просто удалить
        if data.get("__new_entry__"):
            return self._delete_entry(entry_id, snap["id"], reason)

        # Иначе — восстановить все поля
        return self._restore_entry(data, snap["id"], reason)

    def rollback_batch(self, entry_ids: List[int],
                       reason: str = "batch_rollback") -> Dict[int, bool]:
        """Откатить несколько записей. Возвращает {entry_id: success}."""
        results = {}
        for eid in entry_ids:
            results[eid] = self.rollback(eid, reason=reason)
        return results

    def rollback_to_snapshot(self, snapshot_id: int) -> bool:
        """Откат к конкретному снимку по его id."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        if not row:
            log.warning("Snapshot id=%d not found", snapshot_id)
            return False

        data = json.loads(row["snapshot"])
        if data.get("__new_entry__"):
            return self._delete_entry(row["entry_id"], snapshot_id, "manual_rollback")
        return self._restore_entry(data, snapshot_id, "manual_rollback")

    # ── Информация ────────────────────────────────────────────────────────────

    def list_snapshots(self, entry_id: int) -> List[Dict]:
        """История снимков для конкретной записи."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, entry_id, reason, ts, restored FROM knowledge_snapshots "
                "WHERE entry_id=? ORDER BY ts DESC",
                (entry_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_snapshots(self) -> int:
        """Общее количество снимков в БД."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM knowledge_snapshots"
            ).fetchone()[0]

    def rollback_stats(self) -> Dict[str, int]:
        """Статистика откатов."""
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM knowledge_snapshots"
            ).fetchone()[0]
            restored = conn.execute(
                "SELECT COUNT(*) FROM knowledge_snapshots WHERE restored=1"
            ).fetchone()[0]
            entries_covered = conn.execute(
                "SELECT COUNT(DISTINCT entry_id) FROM knowledge_snapshots"
            ).fetchone()[0]
        return {
            "total_snapshots": total,
            "rollbacks_performed": restored,
            "entries_covered": entries_covered,
        }

    # ── Обслуживание ──────────────────────────────────────────────────────────

    def expire_old_snapshots(self, days: int = _EXPIRE_DAYS) -> int:
        """Удалить снимки старше N дней. Возвращает количество удалённых."""
        cutoff = time.time() - days * 86400
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM knowledge_snapshots WHERE ts < ? AND restored=0",
                (cutoff,),
            )
        deleted = cur.rowcount
        if deleted:
            log.info("Expired %d old snapshots (older than %d days)", deleted, days)
        return deleted

    # ── Вспомогательные ───────────────────────────────────────────────────────

    def _get_latest_snapshot(self, entry_id: int) -> Optional[sqlite3.Row]:
        with self._conn() as conn:
            return conn.execute(
                "SELECT * FROM knowledge_snapshots "
                "WHERE entry_id=? AND restored=0 "
                "ORDER BY ts DESC LIMIT 1",
                (entry_id,),
            ).fetchone()

    def _restore_entry(self, data: Dict, snap_id: int, reason: str) -> bool:
        """Восстановить KnowledgeEntry из словаря."""
        entry_id = data.get("id", 0)
        if not entry_id:
            return False
        try:
            with self._conn() as conn:
                conn.execute("""
                    UPDATE knowledge SET
                        category       = ?,
                        title          = ?,
                        content        = ?,
                        tags           = ?,
                        source         = ?,
                        importance     = ?,
                        confidence     = ?,
                        verified       = ?,
                        knowledge_type = ?,
                        usage_count    = ?,
                        last_used      = ?
                    WHERE id = ?
                """, (
                    data.get("category", ""),
                    data.get("title", ""),
                    data.get("content", ""),
                    json.dumps(data.get("tags", []), ensure_ascii=False),
                    data.get("source", ""),
                    data.get("importance", 0.5),
                    data.get("confidence", 0.5),
                    1 if data.get("verified") else 0,
                    data.get("knowledge_type", "auto"),
                    data.get("usage_count", 0),
                    data.get("last_used", 0.0),
                    entry_id,
                ))
                conn.execute(
                    "UPDATE knowledge_snapshots SET restored=1 WHERE id=?",
                    (snap_id,),
                )

            # Лог в training_journal
            self._log_rollback(entry_id, data.get("title", "?"), reason, "restore")
            log.info("Rolled back entry_id=%d (reason=%s)", entry_id, reason)
            return True
        except Exception as e:
            log.error("Rollback failed for entry_id=%d: %s", entry_id, e)
            return False

    def _delete_entry(self, entry_id: int, snap_id: int, reason: str) -> bool:
        """Удалить новую запись при откате (она не должна была существовать)."""
        try:
            with self._conn() as conn:
                conn.execute("DELETE FROM knowledge WHERE id=?", (entry_id,))
                conn.execute(
                    "UPDATE knowledge_snapshots SET restored=1 WHERE id=?",
                    (snap_id,),
                )
            self._log_rollback(entry_id, f"new_entry#{entry_id}", reason, "delete")
            log.info("Rolled back (deleted) new entry_id=%d (reason=%s)",
                     entry_id, reason)
            return True
        except Exception as e:
            log.error("Rollback-delete failed for entry_id=%d: %s", entry_id, e)
            return False

    def _entry_to_dict(self, entry) -> Dict[str, Any]:
        """Конвертировать KnowledgeEntry в словарь для снимка."""
        try:
            d = asdict(entry)
        except Exception:
            d = {
                "id":             getattr(entry, "id", 0),
                "category":       getattr(entry, "category", ""),
                "title":          getattr(entry, "title", ""),
                "content":        getattr(entry, "content", ""),
                "tags":           getattr(entry, "tags", []),
                "source":         getattr(entry, "source", ""),
                "importance":     getattr(entry, "importance", 0.5),
                "confidence":     getattr(entry, "confidence", 0.5),
                "verified":       getattr(entry, "verified", False),
                "knowledge_type": getattr(entry, "knowledge_type", "auto"),
                "usage_count":    getattr(entry, "usage_count", 0),
                "last_used":      getattr(entry, "last_used", 0.0),
                "ts":             getattr(entry, "ts", time.time()),
            }
        return d

    def _log_rollback(self, entry_id: int, title: str,
                      reason: str, action: str) -> None:
        """Записать откат в training_log."""
        try:
            from memory.memory_store import MemoryStore
            MemoryStore.get().log_training(
                action=f"rollback_{action}",
                entry_id=entry_id,
                entry_title=title,
                reason=reason,
                agent="rollback_manager",
            )
        except Exception:
            pass
