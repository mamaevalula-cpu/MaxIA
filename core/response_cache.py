# -*- coding: utf-8 -*-
"""
core/response_cache.py — TTL-based LRU кэш ответов LLM.

Предотвращает дублирующиеся вызовы к LLM для идентичных запросов.
Экономит токены и снижает latency для повторяющихся вопросов.

Особенности:
  • Thread-safe (RLock)
  • LRU eviction при достижении max_size
  • TTL-based invalidation (разный для разных типов задач)
  • Нормализация ключей (lowercase, trim, deduplicate whitespace)
  • Статистика hit/miss ratio
  • Не кэширует: ошибки, торговые сигналы, данные о ценах (volatile)
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

log = logging.getLogger("core.cache")

# TTL по умолчанию (секунды) для разных типов задач
_DEFAULT_TTL: Dict[str, float] = {
    "chat":     300.0,   # 5 минут — общие вопросы
    "code":     600.0,   # 10 минут — код меняется реже
    "analysis": 180.0,   # 3 минуты — аналитика устаревает быстро
    "math":    3600.0,   # 1 час — математика детерминирована
    "trading":   30.0,   # 30 секунд — торговля очень волатильна
    "search":   120.0,   # 2 минуты — поисковые результаты
    "general":  300.0,   # 5 минут — дефолт
}

# Задачи, для которых кэш ЗАПРЕЩЁН
_NOCACHE_TASK_TYPES = {"trading", "price", "orderbook"}

# Слова в запросе, при которых НЕ кэшируем (контентно-чувствительные)
_NOCACHE_KEYWORDS = {
    "сейчас", "now", "цена", "price", "курс", "котировка",
    "last", "live", "real-time", "актуальный", "текущий",
    "какой сейчас", "погода", "weather",
}


@dataclass
class CacheEntry:
    content: str
    task_type: str
    created_at: float = field(default_factory=time.time)
    ttl: float = 300.0
    hits: int = 0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.created_at) > self.ttl

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expired_removals: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_ratio(self) -> float:
        return self.hits / self.total_requests if self.total_requests > 0 else 0.0

    def __str__(self) -> str:
        return (
            f"Cache: {self.hits}H/{self.misses}M "
            f"({self.hit_ratio:.1%} hit rate), "
            f"{self.evictions} evictions, {self.expired_removals} expired"
        )


class ResponseCache:
    """
    Singleton TTL-based LRU кэш для ответов LLM.

    Использование:
        cache = ResponseCache.get()
        cached = cache.get(query, task_type="math")
        if cached:
            return cached
        result = llm.ask(...)
        cache.set(query, result, task_type="math")
    """

    _instance: Optional["ResponseCache"] = None
    _lock = threading.Lock()

    def __init__(self, max_size: int = 500) -> None:
        self._max_size = max_size
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._rlock = threading.RLock()
        self._stats = CacheStats()
        log.info("ResponseCache initialized (max_size=%d)", max_size)

    @classmethod
    def get(cls, max_size: int = 500) -> "ResponseCache":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(max_size)
        return cls._instance

    # ── Нормализация ключа ────────────────────────────────────────────────────

    @staticmethod
    def _make_key(text: str, task_type: str = "general") -> str:
        """
        Создать детерминированный ключ кэша из текста запроса.
        Нормализует: lowercase, trim, deduplicate whitespace.
        """
        normalized = " ".join(text.lower().strip().split())
        raw = f"{task_type}::{normalized}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _should_cache(text: str, task_type: str) -> bool:
        """Определить — стоит ли кэшировать этот запрос."""
        # Запрещённые типы задач
        if task_type in _NOCACHE_TASK_TYPES:
            return False
        # Ключевые слова, указывающие на volatile данные
        text_lower = text.lower()
        for kw in _NOCACHE_KEYWORDS:
            if kw in text_lower:
                return False
        # Очень короткие запросы (< 5 символов) — слишком широкие
        if len(text.strip()) < 5:
            return False
        return True

    # ── Основной API ──────────────────────────────────────────────────────────

    def lookup(self, text: str, task_type: str = "general") -> Optional[str]:
        """
        Получить кэшированный ответ.
        Возвращает None если промах или запись устарела.
        """
        if not self._should_cache(text, task_type):
            return None

        key = self._make_key(text, task_type)

        with self._rlock:
            entry = self._store.get(key)
            if entry is None:
                self._stats.misses += 1
                return None

            if entry.is_expired:
                del self._store[key]
                self._stats.expired_removals += 1
                self._stats.misses += 1
                return None

            # LRU: переместить в конец (самый свежий)
            self._store.move_to_end(key)
            entry.hits += 1
            self._stats.hits += 1

            log.debug(
                "Cache HIT [%s] age=%.0fs hits=%d",
                task_type, entry.age_seconds, entry.hits
            )
            return entry.content

    def set(self, text: str, content: str, task_type: str = "general") -> bool:
        """
        Сохранить ответ в кэш.
        Возвращает False если кэширование не применимо.
        """
        if not self._should_cache(text, task_type):
            return False

        # Не кэшируем ошибки LLM
        if content.startswith("⚠️") or content.startswith("❌"):
            return False
        if "LLM недоступен" in content or "нет провайдеров" in content.lower():
            return False

        key = self._make_key(text, task_type)
        ttl = _DEFAULT_TTL.get(task_type, _DEFAULT_TTL["general"])

        with self._rlock:
            # LRU eviction при переполнении
            if len(self._store) >= self._max_size and key not in self._store:
                # Удаляем самую старую запись (первую в OrderedDict)
                self._store.popitem(last=False)
                self._stats.evictions += 1

            entry = CacheEntry(
                content=content,
                task_type=task_type,
                ttl=ttl,
            )
            self._store[key] = entry
            self._store.move_to_end(key)

        log.debug("Cache SET [%s] ttl=%.0fs size=%d", task_type, ttl, len(self._store))
        return True

    def invalidate(self, task_type: str = "") -> int:
        """Инвалидировать записи: по типу задачи или все."""
        with self._rlock:
            if task_type:
                keys_to_del = [
                    k for k, v in self._store.items()
                    if v.task_type == task_type
                ]
            else:
                keys_to_del = list(self._store.keys())

            for k in keys_to_del:
                del self._store[k]

        log.info("Cache invalidated: %d entries (type=%r)", len(keys_to_del), task_type)
        return len(keys_to_del)

    def cleanup_expired(self) -> int:
        """Удалить все просроченные записи. Вызывается периодически."""
        with self._rlock:
            expired = [k for k, v in self._store.items() if v.is_expired]
            for k in expired:
                del self._store[k]
        self._stats.expired_removals += len(expired)
        if expired:
            log.debug("Cache cleanup: removed %d expired entries", len(expired))
        return len(expired)

    # ── Статистика ────────────────────────────────────────────────────────────

    @property
    def stats(self) -> CacheStats:
        return self._stats

    @property
    def size(self) -> int:
        with self._rlock:
            return len(self._store)

    def get_report(self) -> str:
        """Текстовый отчёт о состоянии кэша."""
        with self._rlock:
            total = len(self._store)
            expired = sum(1 for v in self._store.values() if v.is_expired)
            by_type: Dict[str, int] = {}
            for v in self._store.values():
                by_type[v.task_type] = by_type.get(v.task_type, 0) + 1

        lines = [
            f"📦 **Response Cache**",
            f"  Записей: {total - expired}/{total} (активных/всего)",
            f"  Hit ratio: {self._stats.hit_ratio:.1%} "
            f"({self._stats.hits}H / {self._stats.misses}M)",
            f"  Evictions: {self._stats.evictions}",
        ]
        if by_type:
            lines.append("  По типам: " + ", ".join(
                f"{t}={n}" for t, n in sorted(by_type.items())
            ))
        return "\n".join(lines)