# -*- coding: utf-8 -*-
"""
memory/memory_store.py — Постоянная SQLite-память агента.

Хранит:
  • messages    — полная история диалогов (GUI, Telegram, внутренние)
  • knowledge   — структурированные знания (стратегии, ошибки, решения)
  • tasks       — очередь задач агента (ожидающие, выполненные, неудавшиеся)
  • projects    — метаданные проектов
  • agent_logs  — детальные логи работы агентов

Поддерживает RAG-запросы через простой keyword-поиск (FTS5).
Для полноценного семантического поиска — VectorStoreManager.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("memory.store")

_DB_PATH = Path(__file__).parent.parent / "data" / "memory.db"


@dataclass
class Message:
    role: str             # "user" | "assistant" | "system" | "agent"
    content: str
    source: str           # "gui" | "telegram" | "internal" | agent_name
    session_id: str = ""
    metadata: Dict = None
    ts: float = 0.0
    id: int = 0

    def __post_init__(self):
        if self.ts == 0.0:
            self.ts = time.time()
        if self.metadata is None:
            self.metadata = {}


@dataclass
class KnowledgeEntry:
    category: str         # "strategy"|"error"|"solution"|"fact"|"qa"|"auto-learned"|"hypothesis"
    title: str
    content: str
    tags: List[str] = None
    source: str = ""
    importance: float = 0.5      # 0.0 – 1.0, пересчитывается при usage
    confidence: float = 0.5      # уверенность в достоверности знания
    verified: bool = False        # прошло ли ручную или LLM-валидацию
    knowledge_type: str = "auto"  # "fact"|"rule"|"strategy"|"hypothesis"|"preference"|"error_fix"|"qa"
    usage_count: int = 0          # сколько раз применялось в RAG
    last_used: float = 0.0        # unix ts последнего применения
    # ── Family fields ────────────────────────────────────────────────────────
    scope: str = "ai"            # "private"|"ai"|"trading"|"telegram"|"all"
    applies_to: str = ""         # JSON list: ["ai","trading"] или "" = scope
    ts: float = 0.0
    id: int = 0

    def __post_init__(self):
        if self.ts == 0.0:
            self.ts = time.time()
        if self.tags is None:
            self.tags = []


@dataclass
class AgentTask:
    agent_name: str
    task_text: str
    status: str           # "pending" | "running" | "done" | "failed" | "waiting_tokens"
    priority: int = 5     # 1 (highest) – 10 (lowest)
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    id: int = 0

    def __post_init__(self):
        now = time.time()
        if self.created_at == 0.0:
            self.created_at = now
        if self.updated_at == 0.0:
            self.updated_at = now


class MemoryStore:
    """
    Singleton SQLite-хранилище памяти агента.
    Потокобезопасно через threading.RLock.
    """

    _instance: Optional["MemoryStore"] = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._rlock = threading.RLock()
        self._init_db()
        log.info("MemoryStore ready: %s", db_path)

    @classmethod
    def get(cls, db_path: Path = _DB_PATH) -> "MemoryStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(db_path)
        return cls._instance

    # ── Thread-local connection pool ─────────────────────────────────────────
    # Each thread keeps one persistent connection; avoids per-call open/close
    # overhead while staying thread-safe (SQLite WAL mode).
    _tl: threading.local = threading.local()

    def _connect(self) -> sqlite3.Connection:
        """Return (or create) the thread-local SQLite connection."""
        conn = getattr(self._tl, "conn", None)
        if conn is not None:
            try:
                conn.execute("SELECT 1")  # ping — detects closed/corrupt conn
                return conn
            except Exception:
                pass  # fall through to re-create
        conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=30,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")   # safe + faster than FULL
        conn.execute("PRAGMA cache_size=-8000")     # 8 MB page cache per thread
        conn.execute("PRAGMA temp_store=MEMORY")
        self._tl.conn = conn
        return conn

    def _migrate_db(self, conn: sqlite3.Connection) -> None:
        """Безопасная миграция — добавляет новые колонки если их ещё нет."""
        migrations = [
            ("knowledge", "confidence",     "REAL DEFAULT 0.5"),
            ("knowledge", "verified",       "INTEGER DEFAULT 0"),
            ("knowledge", "knowledge_type", "TEXT DEFAULT 'auto'"),
            ("knowledge", "usage_count",    "INTEGER DEFAULT 0"),
            ("knowledge", "last_used",      "REAL DEFAULT 0"),
            # Family fields
            ("knowledge", "scope",          "TEXT DEFAULT 'ai'"),
            ("knowledge", "applies_to",     "TEXT DEFAULT ''"),
        ]
        existing_cols: Dict[str, set] = {}
        for table, col, typedef in migrations:
            if table not in existing_cols:
                rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
                existing_cols[table] = {r[1] for r in rows}
            if col not in existing_cols[table]:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
                    log.info("MemoryStore migration: added %s.%s", table, col)
                except Exception as e:
                    log.debug("Migration skip %s.%s: %s", table, col, e)

    def _init_db(self) -> None:
        with self._rlock, self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    role        TEXT NOT NULL,
                    content     TEXT NOT NULL,
                    source      TEXT DEFAULT '',
                    session_id  TEXT DEFAULT '',
                    metadata    TEXT DEFAULT '{}',
                    ts          REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS knowledge (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    category       TEXT NOT NULL,
                    title          TEXT NOT NULL,
                    content        TEXT NOT NULL,
                    tags           TEXT DEFAULT '[]',
                    source         TEXT DEFAULT '',
                    importance     REAL DEFAULT 0.5,
                    confidence     REAL DEFAULT 0.5,
                    verified       INTEGER DEFAULT 0,
                    knowledge_type TEXT DEFAULT 'auto',
                    usage_count    INTEGER DEFAULT 0,
                    last_used      REAL DEFAULT 0,
                    ts             REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS training_log (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts           REAL NOT NULL,
                    cycle        INTEGER DEFAULT 0,
                    action       TEXT NOT NULL,
                    entry_id     INTEGER DEFAULT 0,
                    entry_title  TEXT DEFAULT '',
                    reason       TEXT DEFAULT '',
                    quality      REAL DEFAULT 0.0,
                    agent        TEXT DEFAULT '',
                    details      TEXT DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name  TEXT NOT NULL,
                    task_text   TEXT NOT NULL,
                    status      TEXT DEFAULT 'pending',
                    priority    INTEGER DEFAULT 5,
                    result      TEXT DEFAULT '',
                    error       TEXT DEFAULT '',
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT UNIQUE NOT NULL,
                    description TEXT DEFAULT '',
                    path        TEXT DEFAULT '',
                    status      TEXT DEFAULT 'active',
                    metadata    TEXT DEFAULT '{}',
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agent_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name  TEXT NOT NULL,
                    action      TEXT NOT NULL,
                    details     TEXT DEFAULT '',
                    success     INTEGER DEFAULT 1,
                    ts          REAL NOT NULL
                );

                -- Full-text search по сообщениям и знаниям
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                    USING fts5(content, source, session_id, content=messages, content_rowid=id);
                CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
                    USING fts5(title, content, tags, content=knowledge, content_rowid=id);

                -- Триггеры для синхронизации FTS
                CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
                    INSERT INTO messages_fts(rowid, content, source, session_id)
                    VALUES (new.id, new.content, new.source, new.session_id);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
                    INSERT INTO knowledge_fts(rowid, title, content, tags)
                    VALUES (new.id, new.title, new.content, new.tags);
                END;

                -- UPDATE triggers: delete old FTS entry, insert new
                CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, source, session_id)
                    VALUES ('delete', old.id, old.content, old.source, old.session_id);
                    INSERT INTO messages_fts(rowid, content, source, session_id)
                    VALUES (new.id, new.content, new.source, new.session_id);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags)
                    VALUES ('delete', old.id, old.title, old.content, old.tags);
                    INSERT INTO knowledge_fts(rowid, title, content, tags)
                    VALUES (new.id, new.title, new.content, new.tags);
                END;

                -- DELETE triggers: remove from FTS
                CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
                    INSERT INTO messages_fts(messages_fts, rowid, content, source, session_id)
                    VALUES ('delete', old.id, old.content, old.source, old.session_id);
                END;
                CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
                    INSERT INTO knowledge_fts(knowledge_fts, rowid, title, content, tags)
                    VALUES ('delete', old.id, old.title, old.content, old.tags);
                END;
            """)
            # Rebuild FTS index if out of sync (safe no-op if already in sync)
            try:
                conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
                conn.execute("INSERT INTO knowledge_fts(knowledge_fts) VALUES('rebuild')")
                conn.commit()
                log.info("MemoryStore: FTS index rebuild complete")
            except Exception as e:
                log.debug("MemoryStore: FTS rebuild skipped: %s", e)
            # Миграция существующих БД без новых колонок
            self._migrate_db(conn)

    # ── Messages ──────────────────────────────────────────────────────────────

    def add_message(self, msg: Message) -> int:
        with self._rlock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO messages (role,content,source,session_id,metadata,ts) VALUES (?,?,?,?,?,?)",
                (msg.role, msg.content, msg.source, msg.session_id,
                 json.dumps(msg.metadata), msg.ts)
            )
            return cur.lastrowid

    def get_messages(self, session_id: str = "", source: str = "",
                     limit: int = 100, offset: int = 0) -> List[Message]:
        query = "SELECT * FROM messages WHERE 1=1"
        params = []
        if session_id:
            query += " AND session_id=?"
            params.append(session_id)
        if source:
            query += " AND source=?"
            params.append(source)
        query += " ORDER BY ts DESC LIMIT ? OFFSET ?"
        params += [limit, offset]

        with self._rlock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_message(r) for r in reversed(rows)]

    def search_messages(self, query: str, limit: int = 20) -> List[Message]:
        """FTS-поиск по тексту сообщений."""
        sql = """
            SELECT m.* FROM messages m
            JOIN messages_fts f ON m.id = f.rowid
            WHERE messages_fts MATCH ?
            ORDER BY m.ts DESC LIMIT ?
        """
        with self._rlock, self._connect() as conn:
            try:
                rows = conn.execute(sql, (query, limit)).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE content LIKE ? ORDER BY ts DESC LIMIT ?",
                    (f"%{query}%", limit)
                ).fetchall()
        return [self._row_to_message(r) for r in rows]

    def _row_to_message(self, row) -> Message:
        return Message(
            id=row["id"], role=row["role"], content=row["content"],
            source=row["source"], session_id=row["session_id"],
            metadata=json.loads((row["metadata"] or "").strip() or "{}"), ts=row["ts"]
        )

    # ── Knowledge ─────────────────────────────────────────────────────────────

    def add_knowledge(self, entry: KnowledgeEntry) -> int:
        """Сохранить знание. При совпадении title — обновить, не дублировать."""
        with self._rlock, self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO knowledge
                   (category,title,content,tags,source,importance,confidence,
                    verified,knowledge_type,usage_count,last_used,
                    scope,applies_to,ts)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(title) DO UPDATE SET
                       content     = CASE WHEN excluded.importance >= knowledge.importance
                                         THEN excluded.content ELSE knowledge.content END,
                       category    = excluded.category,
                       importance  = MAX(knowledge.importance, excluded.importance),
                       confidence  = MAX(knowledge.confidence, excluded.confidence),
                       tags        = excluded.tags,
                       source      = excluded.source,
                       ts          = excluded.ts,
                       usage_count = knowledge.usage_count + 1""",
                (entry.category, entry.title, entry.content,
                 json.dumps(entry.tags), entry.source, entry.importance,
                 entry.confidence, int(entry.verified), entry.knowledge_type,
                 entry.usage_count, entry.last_used,
                 getattr(entry, "scope", "ai"),
                 getattr(entry, "applies_to", ""),
                 entry.ts)
            )
            # lastrowid = 0 при UPDATE (conflict) → получаем реальный id
            if cur.lastrowid:
                return cur.lastrowid
            row = conn.execute(
                "SELECT id FROM knowledge WHERE title=?", (entry.title,)
            ).fetchone()
            return row[0] if row else 0

    def search_knowledge(self, query: str, category: str = "", limit: int = 10) -> List[KnowledgeEntry]:
        """FTS-поиск по базе знаний."""
        sql = """
            SELECT k.* FROM knowledge k
            JOIN knowledge_fts f ON k.id = f.rowid
            WHERE knowledge_fts MATCH ?
            {cat_filter}
            ORDER BY k.importance DESC, k.ts DESC LIMIT ?
        """
        params: List[Any] = [query]
        cat_filter = ""
        if category:
            cat_filter = "AND k.category=?"
            params.append(category)
        params.append(limit)

        with self._rlock, self._connect() as conn:
            try:
                rows = conn.execute(sql.format(cat_filter=cat_filter), params).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT * FROM knowledge WHERE content LIKE ? ORDER BY importance DESC LIMIT ?",
                    (f"%{query}%", limit)
                ).fetchall()
        return [self._row_to_knowledge(r) for r in rows]

    def get_knowledge(self, category: str = "", limit: int = 50) -> List[KnowledgeEntry]:
        query = "SELECT * FROM knowledge"
        params: List[Any] = []
        if category:
            query += " WHERE category=?"
            params.append(category)
        query += " ORDER BY importance DESC, ts DESC LIMIT ?"
        params.append(limit)
        with self._rlock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_knowledge(r) for r in rows]

    def get_knowledge_by_id(self, entry_id: int) -> Optional[KnowledgeEntry]:
        """Return a knowledge entry by id using the singleton connection (WAL-safe)."""
        with self._rlock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge WHERE id=?", (entry_id,)
            ).fetchone()
        return self._row_to_knowledge(row) if row else None

    def _safe_parse_tags(self, raw) -> list:
        """Safely parse tags field — handles plain strings, JSON arrays, and empty values."""
        s = (raw or "").strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            return parsed if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            # Plain string like "system" or "trading" — wrap in list
            return [s]

    def _row_to_knowledge(self, row) -> KnowledgeEntry:
        keys = row.keys()
        return KnowledgeEntry(
            id=row["id"], category=row["category"], title=row["title"],
            content=row["content"], tags=self._safe_parse_tags(row["tags"]),
            source=row["source"], importance=row["importance"], ts=row["ts"],
            confidence=row["confidence"] if "confidence" in keys else 0.5,
            verified=bool(row["verified"]) if "verified" in keys else False,
            knowledge_type=row["knowledge_type"] if "knowledge_type" in keys else "auto",
            usage_count=row["usage_count"] if "usage_count" in keys else 0,
            last_used=row["last_used"] if "last_used" in keys else 0.0,
            scope=row["scope"] if "scope" in keys else "ai",
            applies_to=row["applies_to"] if "applies_to" in keys else "",
        )

    # ── Tasks ─────────────────────────────────────────────────────────────────

    def add_task(self, task: AgentTask) -> int:
        with self._rlock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO tasks (agent_name,task_text,status,priority,result,error,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (task.agent_name, task.task_text, task.status, task.priority,
                 task.result, task.error, task.created_at, task.updated_at)
            )
            return cur.lastrowid

    def update_task(self, task_id: int, status: str, result: str = "", error: str = "") -> None:
        with self._rlock, self._connect() as conn:
            conn.execute(
                "UPDATE tasks SET status=?,result=?,error=?,updated_at=? WHERE id=?",
                (status, result, error, time.time(), task_id)
            )

    def get_pending_tasks(self, agent_name: str = "") -> List[AgentTask]:
        query = "SELECT * FROM tasks WHERE status IN ('pending','waiting_tokens')"
        params: List[Any] = []
        if agent_name:
            query += " AND agent_name=?"
            params.append(agent_name)
        query += " ORDER BY priority ASC, created_at ASC"
        with self._rlock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_task(r) for r in rows]

    def _row_to_task(self, row) -> AgentTask:
        return AgentTask(
            id=row["id"], agent_name=row["agent_name"], task_text=row["task_text"],
            status=row["status"], priority=row["priority"], result=row["result"],
            error=row["error"], created_at=row["created_at"], updated_at=row["updated_at"]
        )

    # ── Projects ──────────────────────────────────────────────────────────────

    def save_project(self, name: str, description: str = "",
                     path: str = "", metadata: Dict = None) -> None:
        now = time.time()
        with self._rlock, self._connect() as conn:
            conn.execute("""
                INSERT INTO projects (name,description,path,status,metadata,created_at,updated_at)
                VALUES (?,?,?,'active',?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    description=excluded.description, path=excluded.path,
                    metadata=excluded.metadata, updated_at=excluded.updated_at
            """, (name, description, path, json.dumps(metadata or {}), now, now))

    def get_projects(self, status: str = "active") -> List[Dict]:
        with self._rlock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE status=? ORDER BY updated_at DESC", (status,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Agent logs ────────────────────────────────────────────────────────────

    def log_agent(self, agent_name: str, action: str,
                  details: str = "", success: bool = True) -> None:
        with self._rlock, self._connect() as conn:
            conn.execute(
                "INSERT INTO agent_logs (agent_name,action,details,success,ts) VALUES (?,?,?,?,?)",
                (agent_name, action, details, int(success), time.time())
            )

    def get_agent_history(self, agent_name: str = "", limit: int = 50) -> List[Dict]:
        with self._rlock, self._connect() as conn:
            if agent_name:
                rows = conn.execute(
                    "SELECT * FROM agent_logs WHERE agent_name=? ORDER BY ts DESC LIMIT ?",
                    (agent_name, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_logs ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def update_knowledge(self, entry_id: int, importance: float = None,
                         content: str = None, tags: List[str] = None,
                         confidence: float = None, verified: bool = None,
                         knowledge_type: str = None, title: str = None,
                         scope: str = None, applies_to: str = None) -> bool:
        """Обновить существующую запись знания."""
        parts: List[str] = []
        params: List[Any] = []
        if importance is not None:
            parts.append("importance=?"); params.append(min(1.0, max(0.0, importance)))
        if content is not None:
            parts.append("content=?"); params.append(content)
        if title is not None:
            parts.append("title=?"); params.append(title)
        if tags is not None:
            parts.append("tags=?"); params.append(json.dumps(tags))
        if confidence is not None:
            parts.append("confidence=?"); params.append(min(1.0, max(0.0, confidence)))
        if verified is not None:
            parts.append("verified=?"); params.append(int(verified))
        if knowledge_type is not None:
            parts.append("knowledge_type=?"); params.append(knowledge_type)
        if scope is not None:
            parts.append("scope=?"); params.append(scope)
        if applies_to is not None:
            parts.append("applies_to=?"); params.append(applies_to)
        if not parts:
            return False
        params.append(entry_id)
        with self._rlock, self._connect() as conn:
            conn.execute(f"UPDATE knowledge SET {', '.join(parts)} WHERE id=?", params)
        return True

    def record_knowledge_used(self, entry_id: int) -> None:
        """Отметить что знание было применено в RAG (трекинг usage)."""
        with self._rlock, self._connect() as conn:
            conn.execute(
                "UPDATE knowledge SET usage_count=usage_count+1, last_used=? WHERE id=?",
                (time.time(), entry_id)
            )

    # ── Training log ──────────────────────────────────────────────────────────

    def log_training(self, action: str, entry_id: int = 0, entry_title: str = "",
                     reason: str = "", quality: float = 0.0,
                     agent: str = "self_training", cycle: int = 0,
                     details: Dict = None) -> None:
        """Записать событие обучения в training_log (аудит-трейл)."""
        with self._rlock, self._connect() as conn:
            conn.execute(
                """INSERT INTO training_log
                   (ts,cycle,action,entry_id,entry_title,reason,quality,agent,details)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (time.time(), cycle, action, entry_id, entry_title[:120],
                 reason[:300], quality, agent,
                 json.dumps(details or {}))
            )

    def get_training_log(self, limit: int = 100, action: str = "") -> List[Dict]:
        """Получить журнал обучения."""
        query = "SELECT * FROM training_log"
        params: List[Any] = []
        if action:
            query += " WHERE action=?"; params.append(action)
        query += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        with self._rlock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def training_stats(self) -> Dict[str, Any]:
        """Статистика обучения: сколько сохранено/отклонено/применено."""
        with self._rlock, self._connect() as conn:
            total     = conn.execute("SELECT COUNT(*) FROM training_log").fetchone()[0]
            saved     = conn.execute("SELECT COUNT(*) FROM training_log WHERE action='save'").fetchone()[0]
            rejected  = conn.execute("SELECT COUNT(*) FROM training_log WHERE action='reject'").fetchone()[0]
            applied   = conn.execute("SELECT COUNT(*) FROM training_log WHERE action='apply'").fetchone()[0]
            avg_qual  = conn.execute(
                "SELECT AVG(quality) FROM training_log WHERE action='save' AND quality>0"
            ).fetchone()[0] or 0.0
            unverified = conn.execute(
                "SELECT COUNT(*) FROM knowledge WHERE verified=0 AND importance>0.5"
            ).fetchone()[0]
            unused = conn.execute(
                "SELECT COUNT(*) FROM knowledge WHERE usage_count=0"
            ).fetchone()[0]
        return {
            "total_events": total,
            "saved": saved,
            "rejected": rejected,
            "applied_in_rag": applied,
            "avg_quality_saved": round(avg_qual, 3),
            "unverified_high_importance": unverified,
            "knowledge_never_used": unused,
        }

    def knowledge_exists(self, title_substr: str, category: str = "") -> bool:
        """Проверить — есть ли уже похожее знание (дедупликация)."""
        query = "SELECT COUNT(*) FROM knowledge WHERE title LIKE ?"
        params: List[Any] = [f"%{title_substr[:40]}%"]
        if category:
            query += " AND category=?"
            params.append(category)
        with self._rlock, self._connect() as conn:
            count = conn.execute(query, params).fetchone()[0]
        return count > 0

    def get_error_patterns(self, limit: int = 20) -> List[KnowledgeEntry]:
        """Получить сохранённые паттерны ошибок для обучения."""
        return self.get_knowledge(category="error", limit=limit)

    def get_recent_errors(self, limit: int = 50) -> List[Dict]:
        """Получить последние ошибки агентов из логов."""
        with self._rlock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_logs WHERE success=0 ORDER BY ts DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # ── Статистика ────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, int]:
        with self._rlock, self._connect() as conn:
            return {
                "messages": conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                "knowledge": conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0],
                "tasks_total": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
                "tasks_pending": conn.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0],
                "projects": conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                "agent_logs": conn.execute("SELECT COUNT(*) FROM agent_logs").fetchone()[0],
            }
