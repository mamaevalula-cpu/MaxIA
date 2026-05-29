# -*- coding: utf-8 -*-
"""
memory/episodic_memory.py — Эпизодическая память через сессии.

Что это:
  Эпизодическая память хранит «что происходило» с привязкой ко времени и контексту.
  В отличие от MemoryStore (семантические знания), эта память помнит события сессий:
  — Что пользователь спрашивал час/день/неделю назад
  — Какие задачи были выполнены
  — Какие ошибки возникали и как решались
  — Прогресс по долгосрочным проектам

Архитектура:
  Episode → SQLite → Retrieval (по смыслу / времени / тегам)
                   → Consolidation (старые эпизоды → обобщённые)
                   → Forgetting (старые нерелевантные → удаление)

Использование:
    em = EpisodicMemory.get()
    em.record_episode(session_id, query, response, intent, tags)
    episodes = em.recall(query, limit=5)
    context_str = em.get_session_context(session_id)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("memory.episodic")

# ── Конфигурация ──────────────────────────────────────────────────────────────

DB_PATH            = Path("data/episodic_memory.db")
MAX_EPISODES       = 10_000    # максимум эпизодов в базе
CONSOLIDATE_AFTER  = 50        # консолидировать после N эпизодов в сессии
FORGET_AFTER_DAYS  = 30        # удалять нерелевантные эпизоды старше N дней
IMPORTANCE_DECAY   = 0.95      # коэффициент затухания важности со временем
MIN_IMPORTANCE     = 0.1       # минимальная важность для хранения
RECALL_LIMIT       = 10        # лимит по умолчанию при retrieval


@dataclass
class Episode:
    """Один эпизод взаимодействия."""
    session_id:   str
    query:        str
    response:     str
    intent:       str
    tags:         List[str] = field(default_factory=list)
    importance:   float     = 0.5   # 0..1, затухает со временем
    outcome:      str       = ""    # positive / negative / neutral
    created_at:   float     = field(default_factory=time.time)
    episode_id:   str       = ""    # UUID-like fingerprint

    def __post_init__(self) -> None:
        if not self.episode_id:
            raw = f"{self.session_id}:{self.query[:50]}:{self.created_at}"
            self.episode_id = hashlib.md5(raw.encode()).hexdigest()[:16]

    def to_summary(self, max_len: int = 200) -> str:
        """Краткое описание эпизода."""
        q = self.query[:80]
        r = self.response[:max_len - 80]
        return f"[{self.intent}] Q: {q} → A: {r}"

    @property
    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400

    @property
    def decayed_importance(self) -> float:
        """Важность с учётом временно́го затухания."""
        return self.importance * (IMPORTANCE_DECAY ** self.age_days)


@dataclass
class ConsolidatedMemory:
    """Обобщённая память из нескольких эпизодов."""
    session_id:    str
    summary:       str
    episode_count: int
    intents:       List[str] = field(default_factory=list)
    key_facts:     List[str] = field(default_factory=list)
    created_at:    float     = field(default_factory=time.time)


class EpisodicMemory:
    """
    Singleton. Эпизодическая память через сессии.

    Хранит историю взаимодействий в SQLite с возможностью:
    - Retrieval по смыслу (keyword matching)
    - Консолидации старых эпизодов
    - Забывания нерелевантных записей
    """

    _instance: Optional["EpisodicMemory"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(DB_PATH)
        self._local = threading.local()
        self._rlock = threading.RLock()
        self._init_db()
        self._llm_callback = None
        log.info("EpisodicMemory initialized at %s", self._db_path)

    @classmethod
    def get(cls) -> "EpisodicMemory":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_llm_callback(self, cb) -> None:
        """Подключить LLM для генерации консолидированных резюме."""
        self._llm_callback = cb

    # ── Инициализация БД ──────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Thread-local соединение с БД."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    def _init_db(self) -> None:
        """Создать таблицы если не существуют."""
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id   TEXT PRIMARY KEY,
                    session_id   TEXT NOT NULL,
                    query        TEXT NOT NULL,
                    response     TEXT NOT NULL,
                    intent       TEXT DEFAULT 'chat',
                    tags         TEXT DEFAULT '[]',
                    importance   REAL DEFAULT 0.5,
                    outcome      TEXT DEFAULT 'neutral',
                    created_at   REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_ep_session
                    ON episodes(session_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ep_intent
                    ON episodes(intent, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ep_importance
                    ON episodes(importance DESC, created_at DESC);

                CREATE TABLE IF NOT EXISTS consolidated (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id   TEXT NOT NULL,
                    summary      TEXT NOT NULL,
                    episode_count INTEGER DEFAULT 0,
                    intents      TEXT DEFAULT '[]',
                    key_facts    TEXT DEFAULT '[]',
                    created_at   REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_con_session
                    ON consolidated(session_id, created_at DESC);
            """)

    # ── Запись эпизодов ───────────────────────────────────────────────────────

    def record_episode(
        self,
        session_id: str,
        query:      str,
        response:   str,
        intent:     str  = "chat",
        tags:       List[str] = None,
        importance: float = 0.5,
        outcome:    str   = "neutral",
    ) -> str:
        """
        Записать новый эпизод.

        Returns: episode_id
        """
        ep = Episode(
            session_id=session_id,
            query=query[:500],
            response=response[:1000],
            intent=intent,
            tags=tags or [],
            importance=importance,
            outcome=outcome,
        )
        try:
            conn = self._conn()
            conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (episode_id, session_id, query, response, intent, tags,
                    importance, outcome, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    ep.episode_id, ep.session_id, ep.query, ep.response,
                    ep.intent, json.dumps(ep.tags, ensure_ascii=False),
                    ep.importance, ep.outcome, ep.created_at,
                )
            )
            conn.commit()
            log.debug("Episode recorded: %s [%s]", ep.episode_id[:8], intent)

            # Периодически запускать housekeeping
            self._maybe_housekeep(session_id)

        except Exception as e:
            log.warning("Episode record failed: %s", e)

        return ep.episode_id

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def recall(
        self,
        query:      str,
        session_id: str = "",
        intent:     str = "",
        limit:      int = RECALL_LIMIT,
        min_importance: float = 0.1,
    ) -> List[Episode]:
        """
        Вспомнить релевантные эпизоды.

        Стратегия:
        1. Keyword matching по тексту запроса
        2. Фильтр по сессии / интенту (если указано)
        3. Сортировка по (relevance * importance * recency)
        """
        try:
            # Извлечь ключевые слова (4+ символов)
            keywords = list(set(re.findall(r'\w{4,}', query.lower())))[:8]

            conn = self._conn()
            conditions = ["importance >= ?"]
            params: List = [min_importance]

            if session_id:
                conditions.append("session_id = ?")
                params.append(session_id)

            if intent:
                conditions.append("intent = ?")
                params.append(intent)

            where_clause = " AND ".join(conditions)

            rows = conn.execute(
                f"""SELECT * FROM episodes
                    WHERE {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ?""",
                params + [limit * 5]  # берём больше для ранжирования
            ).fetchall()

            if not rows:
                return []

            # Ранжировать по keyword overlap + importance
            scored: List[Tuple[float, Episode]] = []
            for row in rows:
                ep = self._row_to_episode(row)
                score = self._relevance_score(ep, keywords)
                scored.append((score, ep))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [ep for _, ep in scored[:limit]]

        except Exception as e:
            log.warning("Recall failed: %s", e)
            return []

    def _relevance_score(self, ep: Episode, keywords: List[str]) -> float:
        """Оценить релевантность эпизода к запросу."""
        text = (ep.query + " " + ep.response[:200]).lower()
        text_words = set(re.findall(r'\w{4,}', text))

        if not keywords:
            overlap = 0.0
        else:
            matches = sum(1 for kw in keywords if kw in text_words)
            overlap = matches / len(keywords)

        # Recency bonus: свежие эпизоды важнее
        recency = 1.0 / (1.0 + ep.age_days * 0.1)

        return overlap * 0.6 + ep.decayed_importance * 0.2 + recency * 0.2

    def get_session_context(
        self,
        session_id: str,
        max_episodes: int = 10,
        max_tokens_approx: int = 800,
    ) -> str:
        """
        Получить контекст текущей сессии для вставки в промпт.

        Returns: форматированная строка с историей сессии
        """
        try:
            conn = self._conn()
            rows = conn.execute(
                """SELECT * FROM episodes
                   WHERE session_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (session_id, max_episodes)
            ).fetchall()

            if not rows:
                return ""

            episodes = [self._row_to_episode(r) for r in reversed(rows)]

            parts = []
            total_len = 0
            for ep in episodes:
                line = f"[{ep.intent}] {ep.query[:100]} → {ep.response[:150]}"
                if total_len + len(line) > max_tokens_approx * 4:
                    break
                parts.append(line)
                total_len += len(line)

            if not parts:
                return ""

            return "История сессии:\n" + "\n".join(parts)

        except Exception as e:
            log.warning("get_session_context failed: %s", e)
            return ""

    def get_cross_session_context(
        self,
        query: str,
        current_session_id: str = "",
        limit: int = 5,
    ) -> str:
        """
        Найти релевантный контекст из ДРУГИХ сессий.
        Используется для кросс-сессионной памяти.
        """
        try:
            conn = self._conn()
            # Исключаем текущую сессию, берём из других
            conditions = ["importance >= 0.4"]
            params: List = []

            if current_session_id:
                conditions.append("session_id != ?")
                params.append(current_session_id)

            where = " AND ".join(conditions)
            rows = conn.execute(
                f"""SELECT * FROM episodes
                    WHERE {where}
                    ORDER BY importance DESC, created_at DESC
                    LIMIT ?""",
                params + [limit * 4]
            ).fetchall()

            if not rows:
                return ""

            keywords = list(set(re.findall(r'\w{4,}', query.lower())))[:6]
            scored: List[Tuple[float, Episode]] = []
            for row in rows:
                ep = self._row_to_episode(row)
                score = self._relevance_score(ep, keywords)
                if score > 0.2:  # только реально похожие
                    scored.append((score, ep))

            if not scored:
                return ""

            scored.sort(key=lambda x: x[0], reverse=True)
            best = [ep for _, ep in scored[:limit]]

            parts = [
                f"[Из прошлой сессии, {ep.age_days:.0f}д назад] "
                f"{ep.query[:80]} → {ep.response[:100]}"
                for ep in best
            ]
            return "Из предыдущих сессий:\n" + "\n".join(parts)

        except Exception as e:
            log.warning("cross_session_context failed: %s", e)
            return ""

    # ── Консолидация ─────────────────────────────────────────────────────────

    def consolidate_session(
        self, session_id: str, force: bool = False
    ) -> Optional[ConsolidatedMemory]:
        """
        Консолидировать эпизоды сессии в обобщённую память.

        Запускается автоматически когда в сессии накопилось CONSOLIDATE_AFTER эпизодов.
        """
        try:
            conn = self._conn()
            count = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE session_id = ?",
                (session_id,)
            ).fetchone()[0]

            if not force and count < CONSOLIDATE_AFTER:
                return None

            # Проверить нет ли уже актуальной консолидации
            last_con = conn.execute(
                """SELECT episode_count FROM consolidated
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            ).fetchone()

            if last_con and last_con[0] >= count - 10:
                return None  # уже актуально

            # Загрузить последние N эпизодов
            rows = conn.execute(
                """SELECT * FROM episodes
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (session_id, CONSOLIDATE_AFTER)
            ).fetchall()

            episodes = [self._row_to_episode(r) for r in rows]

            # Генерировать резюме
            summary = self._generate_summary(episodes)
            intents  = list(set(ep.intent for ep in episodes))
            key_facts = self._extract_key_facts(episodes)

            mem = ConsolidatedMemory(
                session_id=session_id,
                summary=summary,
                episode_count=count,
                intents=intents,
                key_facts=key_facts,
            )
            conn.execute(
                """INSERT INTO consolidated
                   (session_id, summary, episode_count, intents, key_facts, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    session_id, summary, count,
                    json.dumps(intents, ensure_ascii=False),
                    json.dumps(key_facts, ensure_ascii=False),
                    time.time()
                )
            )
            conn.commit()
            log.info("Session %s consolidated: %d episodes", session_id[:8], count)
            return mem

        except Exception as e:
            log.warning("Consolidation failed: %s", e)
            return None

    def _generate_summary(self, episodes: List[Episode]) -> str:
        """Сгенерировать текстовое резюме группы эпизодов."""
        if self._llm_callback:
            try:
                text = "\n".join(
                    f"[{ep.intent}] {ep.query[:80]} → {ep.response[:120]}"
                    for ep in episodes[-20:]
                )
                prompt = (
                    f"Создай краткое резюме этих взаимодействий (5-7 ключевых пунктов):\n\n"
                    f"{text}\n\nРезюме:"
                )
                result = self._llm_callback(prompt, max_tokens=400)
                if result and len(result) > 20:
                    return result
            except Exception:
                pass

        # Fallback: извлечь самые важные ответы
        important = sorted(episodes, key=lambda e: e.importance, reverse=True)[:5]
        parts = [f"• [{ep.intent}] {ep.query[:60]}" for ep in important]
        return "Ключевые взаимодействия:\n" + "\n".join(parts)

    def _extract_key_facts(self, episodes: List[Episode]) -> List[str]:
        """Извлечь ключевые факты из группы эпизодов."""
        facts = []
        for ep in episodes:
            if ep.importance >= 0.7 and ep.outcome != "negative":
                fact = f"{ep.query[:50]} → {ep.response[:80]}"
                facts.append(fact)
        return facts[:10]

    def get_consolidated(self, session_id: str) -> Optional[str]:
        """Получить последнее консолидированное резюме сессии."""
        try:
            conn = self._conn()
            row = conn.execute(
                """SELECT summary, key_facts FROM consolidated
                   WHERE session_id = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (session_id,)
            ).fetchone()
            if not row:
                return None
            summary = row[0]
            try:
                facts = json.loads(row[1] or "[]")
                if facts:
                    summary += "\n\nКлючевые факты:\n" + "\n".join(f"• {f}" for f in facts[:5])
            except Exception:
                pass
            return summary
        except Exception as e:
            log.warning("get_consolidated failed: %s", e)
            return None

    # ── Housekeeping ─────────────────────────────────────────────────────────

    def _maybe_housekeep(self, session_id: str) -> None:
        """Запустить housekeeping в фоне если нужно."""
        import random
        if random.random() < 0.05:  # 5% вероятность при каждой записи
            threading.Thread(
                target=self._housekeep, daemon=True, name="ep-housekeep"
            ).start()

    def _housekeep(self) -> None:
        """Удалить старые нерелевантные эпизоды."""
        try:
            cutoff = time.time() - FORGET_AFTER_DAYS * 86400
            conn = self._conn()

            # Удалить старые нерелевантные (importance < порога)
            deleted = conn.execute(
                """DELETE FROM episodes
                   WHERE created_at < ? AND importance < ?""",
                (cutoff, MIN_IMPORTANCE * 2)
            ).rowcount
            conn.commit()

            if deleted:
                log.debug("Episodic housekeep: deleted %d old episodes", deleted)

            # Если всё равно много — удалить самые старые и неважные
            total = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            if total > MAX_EPISODES:
                excess = total - int(MAX_EPISODES * 0.9)
                conn.execute(
                    """DELETE FROM episodes WHERE episode_id IN (
                        SELECT episode_id FROM episodes
                        ORDER BY (importance * 1.0 / (1.0 + (? - created_at)/86400)) ASC
                        LIMIT ?
                    )""",
                    (time.time(), excess)
                )
                conn.commit()
                log.info("Episodic trim: removed %d excess episodes", excess)

        except Exception as e:
            log.debug("Housekeep error: %s", e)

    # ── Вспомогательные ───────────────────────────────────────────────────────

    def _row_to_episode(self, row: sqlite3.Row) -> Episode:
        """Конвертировать строку БД в Episode."""
        try:
            tags = json.loads(row["tags"] or "[]")
        except Exception:
            tags = []
        return Episode(
            episode_id=row["episode_id"],
            session_id=row["session_id"],
            query=row["query"],
            response=row["response"],
            intent=row["intent"],
            tags=tags,
            importance=float(row["importance"]),
            outcome=row["outcome"] or "neutral",
            created_at=float(row["created_at"]),
        )

    def update_outcome(self, episode_id: str, outcome: str, importance_boost: float = 0.0) -> None:
        """Обновить исход эпизода (positive/negative/neutral) и важность."""
        try:
            conn = self._conn()
            if importance_boost != 0.0:
                conn.execute(
                    """UPDATE episodes
                       SET outcome = ?, importance = MIN(1.0, importance + ?)
                       WHERE episode_id = ?""",
                    (outcome, importance_boost, episode_id)
                )
            else:
                conn.execute(
                    "UPDATE episodes SET outcome = ? WHERE episode_id = ?",
                    (outcome, episode_id)
                )
            conn.commit()
        except Exception as e:
            log.debug("update_outcome failed: %s", e)

    def get_stats(self) -> Dict:
        """Статистика эпизодической памяти."""
        try:
            conn = self._conn()
            total     = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            sessions  = conn.execute("SELECT COUNT(DISTINCT session_id) FROM episodes").fetchone()[0]
            con_count = conn.execute("SELECT COUNT(*) FROM consolidated").fetchone()[0]
            avg_imp   = conn.execute("SELECT AVG(importance) FROM episodes").fetchone()[0] or 0
            return {
                "total_episodes": total,
                "unique_sessions": sessions,
                "consolidated": con_count,
                "avg_importance": round(avg_imp, 3),
            }
        except Exception:
            return {}

    def get_report(self) -> str:
        s = self.get_stats()
        return (
            f"📖 **Episodic Memory**\n"
            f"  Эпизодов: {s.get('total_episodes', 0):,}\n"
            f"  Сессий: {s.get('unique_sessions', 0)}\n"
            f"  Консолидировано: {s.get('consolidated', 0)}\n"
            f"  Средняя важность: {s.get('avg_importance', 0)}"
        )
