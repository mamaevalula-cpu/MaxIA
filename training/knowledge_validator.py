# -*- coding: utf-8 -*-
"""
training/knowledge_validator.py — Валидатор знаний перед записью в память.

Каждое знание проходит проверку:
  1. Минимальные требования (длина, наличие содержания)
  2. Дедупликация (нет ли уже почти такого же)
  3. Качество контента (не мусор, не заглушка)
  4. Классификация типа знания (fact/rule/hypothesis/qa/error_fix)
  5. Расчёт уровня уверенности (confidence)

Результат: ValidationResult(ok, confidence, knowledge_type, reason)

Использование:
    validator = KnowledgeValidator.get()
    result = validator.validate(entry)
    if result.ok:
        entry.confidence = result.confidence
        entry.knowledge_type = result.knowledge_type
        memory.add_knowledge(entry)
    else:
        journal.record_reject(entry, result.reason)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

log = logging.getLogger("training.validator")

# ── Пороги ────────────────────────────────────────────────────────────────────

MIN_CONTENT_LEN    = 80    # минимум символов в content
MIN_TITLE_LEN      = 5     # минимум символов в title
MAX_CONTENT_LEN    = 8000  # если больше — обрезать, не отклонять
DUPLICATE_WINDOW   = 200   # max знаний для проверки дубликатов
SIMILARITY_CUTOFF  = 0.72  # jaccard similarity выше — дубликат

# Маркеры мусорного контента
_GARBAGE_PATTERNS = [
    r"^(todo|fixme|placeholder|заглушка|тест|test)\b",
    r"^\.{3,}$",
    r"lorem ipsum",
    r"<(no content|пусто|empty)>",
    r"^\s*(n/?a|none|нет данных)\s*$",
]
_GARBAGE_RE = re.compile("|".join(_GARBAGE_PATTERNS), re.IGNORECASE)

# Маркеры реальных ошибок / неудачных ответов (снижают confidence)
_ERROR_MARKERS = ("⚠️", "❌", "ошибка", "error", "traceback", "exception",
                  "не удалось", "недоступен", "api error")

# Классификация типа знания по сигналам в тексте/категории
_TYPE_SIGNALS: List[Tuple[str, List[str]]] = [
    ("error_fix",   ["fix", "ошибк", "error", "traceback", "исправ", "solution"]),
    ("qa",          ["вопрос:", "question:", "q:", "ответ:", "answer:", "a:"]),
    ("rule",        ["правило", "всегда", "никогда", "обязательно", "rule:", "must", "never"]),
    ("strategy",    ["стратег", "подход", "алгоритм", "strategy", "approach"]),
    ("fact",        ["факт", "является", "состоит", "определение", "fact:", "is a", "defined as"]),
    ("preference",  ["предпочт", "нравится", "люблю", "prefer", "favorite"]),
]


@dataclass
class ValidationResult:
    ok: bool
    confidence: float        = 0.5
    knowledge_type: str      = "auto"
    reason: str              = ""
    warnings: List[str]      = field(default_factory=list)
    quality_score: float     = 0.0   # 0..1 итоговый скор качества


class KnowledgeValidator:
    """
    Singleton-валидатор знаний.
    Проверяет каждое KnowledgeEntry перед записью в MemoryStore.
    """

    _instance: Optional["KnowledgeValidator"] = None

    @classmethod
    def get(cls) -> "KnowledgeValidator":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def validate(self, entry) -> ValidationResult:
        """
        Полная проверка KnowledgeEntry.
        Возвращает ValidationResult с решением ok/reject + метаданными.
        """
        warnings: List[str] = []
        score = 1.0  # начинаем с 1.0, снижаем при проблемах

        # ── 1. Минимальные требования ────────────────────────────────────────
        if not entry.title or len(entry.title.strip()) < MIN_TITLE_LEN:
            return ValidationResult(ok=False, reason="Слишком короткий заголовок",
                                    quality_score=0.0)

        content = (entry.content or "").strip()
        if len(content) < MIN_CONTENT_LEN:
            return ValidationResult(
                ok=False,
                reason=f"Контент слишком короткий ({len(content)} символов, минимум {MIN_CONTENT_LEN})",
                quality_score=0.1,
            )

        # ── 2. Проверка на мусор ─────────────────────────────────────────────
        if _GARBAGE_RE.search(content[:200]):
            return ValidationResult(ok=False, reason="Обнаружен мусорный контент",
                                    quality_score=0.0)

        # ── 3. Снижение скора при маркерах ошибок ───────────────────────────
        content_lower = content.lower()
        error_hits = sum(1 for m in _ERROR_MARKERS if m in content_lower)
        if error_hits >= 3:
            score -= 0.25
            warnings.append(f"Много маркеров ошибок ({error_hits})")

        # ── 4. Длина контента влияет на качество ────────────────────────────
        if len(content) < 150:
            score -= 0.15
            warnings.append("Контент короткий (<150 символов)")
        elif len(content) > 500:
            score += 0.05   # подробное знание ценнее

        # ── 5. Проверка дубликатов ───────────────────────────────────────────
        dup_result = self._check_duplicate(entry)
        if dup_result:
            return ValidationResult(
                ok=False,
                reason=f"Дубликат: '{dup_result}' (similarity ≥ {SIMILARITY_CUTOFF})",
                quality_score=0.2,
            )

        # ── 6. Теги добавляют доверие ────────────────────────────────────────
        if entry.tags and len(entry.tags) >= 2:
            score += 0.05

        # ── 7. Источник влияет на confidence ────────────────────────────────
        confidence = self._calc_confidence(entry, score)

        # ── 8. Классификация типа знания ────────────────────────────────────
        knowledge_type = self._classify_type(entry)

        # Гипотезы не блокируем, но снижаем importance при сохранении
        if knowledge_type == "hypothesis":
            score -= 0.1
            warnings.append("Классифицировано как гипотеза — importance будет снижена")

        quality_score = round(max(0.0, min(1.0, score)), 3)

        return ValidationResult(
            ok=True,
            confidence=confidence,
            knowledge_type=knowledge_type,
            reason="OK",
            warnings=warnings,
            quality_score=quality_score,
        )

    # ── Внутренние методы ─────────────────────────────────────────────────────

    def _check_duplicate(self, entry) -> Optional[str]:
        """
        Jaccard similarity по словам против существующих записей.
        Возвращает title дубликата или None.
        """
        try:
            from memory.memory_store import MemoryStore
            mem = MemoryStore.get()

            # Ищем похожие через FTS сначала (быстро)
            query_words = set(re.findall(r'\b\w{4,}\b', entry.title.lower()))
            if not query_words:
                return None

            candidates = mem.search_knowledge(
                " ".join(list(query_words)[:5]),
                limit=15,
            )
            new_words = set(re.findall(r'\b\w{4,}\b', entry.content.lower()))
            if not new_words:
                return None

            for c in candidates:
                if c.id == entry.id:
                    continue
                existing_words = set(re.findall(r'\b\w{4,}\b', c.content.lower()))
                if not existing_words:
                    continue
                intersection = len(new_words & existing_words)
                union = len(new_words | existing_words)
                similarity = intersection / union if union else 0.0
                if similarity >= SIMILARITY_CUTOFF:
                    return c.title[:60]
        except Exception as e:
            log.debug("Duplicate check error: %s", e)
        return None

    def _calc_confidence(self, entry, base_score: float) -> float:
        """Рассчитать уровень уверенности в знании."""
        conf = base_score * 0.7  # base

        # Источник
        source = (entry.source or "").lower()
        if source in ("user", "manual", "verified"):
            conf += 0.3    # ручной ввод — самый надёжный
        elif source in ("coder_agent", "analyzer_agent"):
            conf += 0.2    # специализированный агент
        elif "self_training" in source:
            conf += 0.05   # авто-генерация — менее надёжна
        else:
            conf += 0.1

        # Категория
        category = (entry.category or "").lower()
        if category in ("error", "solution"):
            conf += 0.1    # исправления ошибок — проверяемые
        elif category == "hypothesis":
            conf -= 0.15   # гипотезы — низкая уверенность

        # Importance как сигнал (если выставлен вручную — выше)
        if entry.importance >= 0.9:
            conf += 0.05

        return round(min(1.0, max(0.05, conf)), 3)

    def _classify_type(self, entry) -> str:
        """Классифицировать тип знания по содержимому."""
        text = f"{entry.title} {entry.content}".lower()

        # По категории
        cat = (entry.category or "").lower()
        if cat == "error":
            return "error_fix"
        if cat == "qa":
            return "qa"
        if cat == "hypothesis":
            return "hypothesis"
        if cat in ("strategy", "fact", "rule", "preference"):
            return cat

        # По сигналам в тексте
        scores: dict[str, int] = {}
        for ktype, signals in _TYPE_SIGNALS:
            hits = sum(1 for s in signals if s in text)
            if hits:
                scores[ktype] = hits

        if scores:
            return max(scores, key=scores.get)

        # По тегам
        tags = [t.lower() for t in (entry.tags or [])]
        for ktype, signals in _TYPE_SIGNALS:
            if any(s in " ".join(tags) for s in signals[:2]):
                return ktype

        return "auto"

    def validate_batch(self, entries: list) -> Tuple[list, list]:
        """
        Валидация списка записей.
        Возвращает (valid_entries_with_results, rejected_entries_with_reasons).
        """
        valid, rejected = [], []
        for entry in entries:
            result = self.validate(entry)
            if result.ok:
                valid.append((entry, result))
            else:
                rejected.append((entry, result))
        return valid, rejected
