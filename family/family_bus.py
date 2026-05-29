# -*- coding: utf-8 -*-
"""
family/family_bus.py — Cross-process event bus (SQLite-based).

Позволяет трём разным процессам (my_personal_ai, bybit-bot, telegram)
общаться через общую таблицу events без сетевого стека.

Почему SQLite:
  • Уже используется в обоих проектах
  • Не требует доп. сервисов (Redis/RabbitMQ)
  • WAL-mode = писатель не блокирует читателей
  • Простая поддержка offline-компонентов

Протокол:
  Издатель     → INSERT event
  Подписчик    → SELECT WHERE consumed=0 AND (target IN ('ai','all'))
  После обработки → UPDATE consumed=1

Таблица family_events (в shared/family.db):
  id          INTEGER PK
  kind        TEXT    — тип события (см. EventKind)
  source      TEXT    — кто отправил ('ai'|'trading'|'telegram')
  target      TEXT    — кому ('ai'|'trading'|'telegram'|'all')
  payload     TEXT    — JSON
  ts          REAL
  consumed    INTEGER — 0=новое, 1=обработано
  ttl_until   REAL    — unix ts истечения (0=бессрочно)

Использование:
    bus = FamilyBus.get()
    bus.publish(FamilyEvent(kind=EventKind.KNOWLEDGE_UPDATED, source='ai',
                            target='all', payload={'entry_id': 42}))
    for event in bus.consume(target='trading'):
        handle(event)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("family.bus")

# Единая БД для всей семьи — рядом с my_personal_ai/data/
_FAMILY_DB = Path(__file__).parent.parent / "data" / "family.db"

# TTL событий по умолчанию — 24 часа
_DEFAULT_TTL = 86400.0

# Максимум необработанных событий на один target (защита от завала)
_MAX_PENDING = 500


class EventKind(str, Enum):
    # Знания
    KNOWLEDGE_SAVED    = "knowledge_saved"      # новое знание сохранено
    KNOWLEDGE_UPDATED  = "knowledge_updated"    # знание обновлено
    KNOWLEDGE_ROLLED_BACK = "knowledge_rolled_back"  # откат
    KNOWLEDGE_CONFLICT = "knowledge_conflict"   # конфликт найден

    # Обучение
    TRAINING_CYCLE_DONE = "training_cycle_done"  # цикл завершён
    TRAINING_REJECTED   = "training_rejected"    # знание отклонено

    # Торговля
    TRADE_SIGNAL       = "trade_signal"         # сигнал от AI для торговли
    TRADE_EXECUTED     = "trade_executed"        # сделка выполнена
    TRADE_FAILED       = "trade_failed"          # сделка провалена
    RISK_ALERT         = "risk_alert"            # риск-предупреждение

    # Система
    COMPONENT_ONLINE   = "component_online"     # компонент запустился
    COMPONENT_OFFLINE  = "component_offline"    # компонент упал
    HEALTH_PING        = "health_ping"           # keepalive
    CONFIG_CHANGED     = "config_changed"        # конфиг обновлён

    # Telegram
    TG_COMMAND         = "tg_command"            # команда из Telegram
    TG_NOTIFICATION    = "tg_notification"       # уведомление в Telegram

    # Ошибки
    ERROR_DETECTED     = "error_detected"        # ошибка обнаружена
    ERROR_FIXED        = "error_fixed"           # ошибка исправлена


@dataclass
class FamilyEvent:
    kind:    EventKind
    source:  str               # 'ai' | 'trading' | 'telegram' | 'system'
    target:  str = "all"       # 'ai' | 'trading' | 'telegram' | 'all'
    payload: Dict[str, Any] = field(default_factory=dict)
    ts:      float = field(default_factory=time.time)
    id:      int = 0
    ttl:     float = _DEFAULT_TTL   # секунд жизни (0 = бессрочно)

    def to_dict(self) -> Dict:
        return {
            "kind":    self.kind.value,
            "source":  self.source,
            "target":  self.target,
            "payload": self.payload,
            "ts":      self.ts,
            "id":      self.id,
        }


class FamilyBus:
    """
    Singleton — cross-process event bus поверх SQLite.
    Безопасен для многопоточного доступа.
    """

    _instance: Optional["FamilyBus"] = None

    @classmethod
    def get(cls) -> "FamilyBus":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._ensure_schema()
        return cls._instance

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(_FAMILY_DB), timeout=10,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        _FAMILY_DB.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS family_events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind      TEXT NOT NULL,
                    source    TEXT NOT NULL,
                    target    TEXT NOT NULL DEFAULT 'all',
                    payload   TEXT DEFAULT '{}',
                    ts        REAL NOT NULL,
                    consumed  INTEGER DEFAULT 0,
                    ttl_until REAL DEFAULT 0
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fe_target_consumed "
                "ON family_events(target, consumed, ts)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS family_components (
                    name        TEXT PRIMARY KEY,
                    last_ping   REAL DEFAULT 0,
                    version     TEXT DEFAULT '',
                    status      TEXT DEFAULT 'unknown',
                    meta        TEXT DEFAULT '{}'
                )
            """)

    # ── Публикация ────────────────────────────────────────────────────────────

    def publish(self, event: FamilyEvent) -> int:
        """
        Опубликовать событие. Возвращает id новой записи.
        Если target завален (>MAX_PENDING) — удаляет старые необработанные.
        """
        ttl_until = event.ts + event.ttl if event.ttl > 0 else 0.0
        payload_json = json.dumps(event.payload, ensure_ascii=False)

        with self._conn() as conn:
            # Проверить/очистить переполнение
            pending = conn.execute(
                "SELECT COUNT(*) FROM family_events WHERE target=? AND consumed=0",
                (event.target,),
            ).fetchone()[0]
            if pending > _MAX_PENDING:
                # Удалить старейшие необработанные (половину от лимита)
                conn.execute("""
                    DELETE FROM family_events WHERE id IN (
                        SELECT id FROM family_events
                        WHERE target=? AND consumed=0
                        ORDER BY ts ASC LIMIT ?
                    )
                """, (event.target, _MAX_PENDING // 2))
                log.warning("FamilyBus: cleared %d stale events for target=%s",
                            _MAX_PENDING // 2, event.target)

            cur = conn.execute(
                "INSERT INTO family_events(kind, source, target, payload, ts, ttl_until) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event.kind.value, event.source, event.target,
                 payload_json, event.ts, ttl_until),
            )
            event_id = cur.lastrowid

        log.debug("Bus.publish: %s → %s (id=%d)", event.kind.value, event.target, event_id)
        return event_id

    def broadcast(self, kind: EventKind, source: str,
                  payload: Dict[str, Any] = None,
                  ttl: float = _DEFAULT_TTL) -> int:
        """Сокращение для publish с target='all'."""
        return self.publish(FamilyEvent(
            kind=kind, source=source, target="all",
            payload=payload or {}, ttl=ttl,
        ))

    # ── Потребление ───────────────────────────────────────────────────────────

    def consume(self, target: str, limit: int = 50) -> List[FamilyEvent]:
        """
        Вернуть необработанные события для данного target (включая 'all').
        Помечает их consumed=1. Истёкшие — автоматически удаляются.
        """
        now = time.time()
        events: List[FamilyEvent] = []

        with self._conn() as conn:
            # Удалить истёкшие
            conn.execute(
                "DELETE FROM family_events WHERE ttl_until > 0 AND ttl_until < ?",
                (now,),
            )

            rows = conn.execute("""
                SELECT * FROM family_events
                WHERE consumed = 0
                  AND (target = ? OR target = 'all')
                ORDER BY ts ASC
                LIMIT ?
            """, (target, limit)).fetchall()

            if rows:
                ids = [r["id"] for r in rows]
                conn.execute(
                    f"UPDATE family_events SET consumed=1 "
                    f"WHERE id IN ({','.join('?' * len(ids))})",
                    ids,
                )

        for row in rows:
            try:
                kind = EventKind(row["kind"])
            except ValueError:
                log.debug("Unknown event kind: %s", row["kind"])
                continue
            events.append(FamilyEvent(
                id=row["id"],
                kind=kind,
                source=row["source"],
                target=row["target"],
                payload=json.loads(row["payload"] or "{}"),
                ts=row["ts"],
            ))

        return events

    def peek(self, target: str, limit: int = 20) -> List[FamilyEvent]:
        """Просмотр без пометки consumed (для мониторинга)."""
        now = time.time()
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM family_events
                WHERE consumed = 0
                  AND (target = ? OR target = 'all')
                  AND (ttl_until = 0 OR ttl_until > ?)
                ORDER BY ts DESC LIMIT ?
            """, (target, now, limit)).fetchall()
        return [
            FamilyEvent(
                id=r["id"], kind=EventKind(r["kind"]),
                source=r["source"], target=r["target"],
                payload=json.loads(r["payload"] or "{}"), ts=r["ts"],
            )
            for r in rows if r["kind"] in {e.value for e in EventKind}
        ]

    # ── Компоненты (keepalive) ────────────────────────────────────────────────

    def ping(self, component: str, status: str = "online",
             version: str = "", meta: Dict = None) -> None:
        """Зарегистрировать что компонент жив."""
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO family_components(name, last_ping, version, status, meta)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    last_ping = excluded.last_ping,
                    version   = excluded.version,
                    status    = excluded.status,
                    meta      = excluded.meta
            """, (component, time.time(), version, status,
                  json.dumps(meta or {}, ensure_ascii=False)))

    def get_components(self) -> List[Dict]:
        """Список всех зарегистрированных компонентов."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM family_components ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Статистика ────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        with self._conn() as conn:
            total   = conn.execute("SELECT COUNT(*) FROM family_events").fetchone()[0]
            pending = conn.execute(
                "SELECT COUNT(*) FROM family_events WHERE consumed=0"
            ).fetchone()[0]
            expired = conn.execute(
                "SELECT COUNT(*) FROM family_events "
                "WHERE ttl_until > 0 AND ttl_until < ?", (time.time(),)
            ).fetchone()[0]
        return {"total": total, "pending": pending, "expired": expired}

    def cleanup(self, days: int = 3) -> int:
        """Удалить обработанные события старше N дней."""
        cutoff = time.time() - days * 86400
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM family_events WHERE consumed=1 AND ts < ?",
                (cutoff,),
            )
        return cur.rowcount
