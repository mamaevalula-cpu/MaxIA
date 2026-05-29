# -*- coding: utf-8 -*-
"""
brain/reflection_engine.py — Двигатель саморефлексии и самокоррекции.

После каждого важного ответа система:
  1. Оценивает качество (score 0..1)
  2. Обнаруживает логические ошибки
  3. Запускает цикл самокоррекции (до 2 итераций)
  4. Сохраняет паттерны улучшений в memory
  5. Обновляет ModelProfiler по результатам

Архитектура:
  Ответ → Scorer → (score < threshold) → Critic → Corrector → Ответ v2
                                       ↓
                           Сохранить в knowledge base

Использование в orchestrator:
    engine = ReflectionEngine.get()
    result = engine.reflect_and_improve(
        original_query=text,
        original_response=resp.text,
        intent=intent,
        context=rag_context,
    )
    if result.improved:
        resp.text = result.final_response
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("brain.reflection")

# Порог качества — ниже этого запускаем самокоррекцию
QUALITY_THRESHOLD = 0.45
# Максимум итераций самокоррекции
MAX_CORRECTION_ITERATIONS = 2
# Минимальная длина ответа для запуска reflection (не тратим токены на короткие)
MIN_RESPONSE_LENGTH = 80
# Интенты где reflection обязателен (независимо от длины)
ALWAYS_REFLECT_INTENTS = {"code_change", "analysis", "trading", "project_create"}
# Интенты где reflection не нужен (быстрые ответы)
SKIP_REFLECT_INTENTS = {"status", "memory", "monitor", "image", "key_manager"}

# Паттерны ошибочных ответов (для быстрого detection без LLM)
_ERROR_PATTERNS = [
    r"⚠️",
    r"❌",
    r"не могу\b",
    r"невозможно\b",
    r"ошибк[аи]\b",
    r"недоступен",
    r"API error",
    r"Exception:",
    r"Traceback",
    r"нет данных",
    r"не удалось",
]

# Паттерны хорошего ответа (увеличивают score)
_QUALITY_SIGNALS = [
    r"```",           # код
    r"\d+\.",         # нумерованный список
    r"•|\-\s",        # маркированный список
    r"\*\*[^*]+\*\*", # bold text
    r"например",
    r"таким образом",
    r"следовательно",
    r"шаг \d+",
]


@dataclass
class ReflectionResult:
    """Результат рефлексии."""
    original_response: str
    final_response: str
    quality_score: float          # 0.0 – 1.0
    improved: bool = False
    iterations: int = 0
    critique: str = ""
    improvements: List[str] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def improvement_summary(self) -> str:
        if not self.improved:
            return f"No improvement needed (score={self.quality_score:.2f})"
        return (
            f"Improved in {self.iterations} iter(s), "
            f"score={self.quality_score:.2f}, "
            f"improvements: {'; '.join(self.improvements[:3])}"
        )


class ReflectionEngine:
    """
    Singleton. Запускает рефлексию и самокоррекцию ответов.
    """

    _instance: Optional["ReflectionEngine"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._llm_callback: Optional[Callable] = None  # будет подключён
        self._memory = None
        self._reflection_stats: Dict[str, int] = {
            "total": 0, "improved": 0, "skipped": 0
        }
        log.info("ReflectionEngine initialized")

    @classmethod
    def get(cls) -> "ReflectionEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_llm_callback(self, cb: Callable) -> None:
        """Подключить LLM для генерации critique и corrections."""
        self._llm_callback = cb

    def set_memory(self, memory: Any) -> None:
        """Подключить MemoryStore для сохранения паттернов."""
        self._memory = memory

    # ── Главный метод ─────────────────────────────────────────────────────────

    def reflect_and_improve(
        self,
        original_query: str,
        original_response: str,
        intent: str = "chat",
        context: str = "",
        force: bool = False,
    ) -> ReflectionResult:
        """
        Запустить рефлексию и при необходимости улучшить ответ.

        Args:
            original_query:    исходный запрос пользователя
            original_response: ответ который надо оценить/улучшить
            intent:            классифицированный intent
            context:           RAG контекст (для validation)
            force:             принудительно запустить даже для коротких ответов

        Returns:
            ReflectionResult с (возможно улучшенным) ответом
        """
        t0 = time.time()
        self._reflection_stats["total"] += 1

        # Быстрые проверки на необходимость reflection
        if intent in SKIP_REFLECT_INTENTS and not force:
            self._reflection_stats["skipped"] += 1
            return ReflectionResult(
                original_response=original_response,
                final_response=original_response,
                quality_score=1.0,
                latency_ms=0.0,
            )

        if (len(original_response) < MIN_RESPONSE_LENGTH
                and intent not in ALWAYS_REFLECT_INTENTS
                and not force):
            self._reflection_stats["skipped"] += 1
            return ReflectionResult(
                original_response=original_response,
                final_response=original_response,
                quality_score=0.8,
                latency_ms=0.0,
            )

        # Быстрая оценка качества (без LLM)
        score = self._score_response_fast(original_query, original_response, intent)

        # Если качество достаточное — не тратим токены
        if score >= QUALITY_THRESHOLD and intent not in ALWAYS_REFLECT_INTENTS:
            return ReflectionResult(
                original_response=original_response,
                final_response=original_response,
                quality_score=score,
                latency_ms=(time.time() - t0) * 1000,
            )

        # LLM-based reflection (более точная оценка + коррекция)
        if self._llm_callback is None:
            return ReflectionResult(
                original_response=original_response,
                final_response=original_response,
                quality_score=score,
                latency_ms=(time.time() - t0) * 1000,
            )

        try:
            result = self._llm_reflect_loop(
                original_query, original_response, intent, context, score
            )
        except Exception as e:
            log.warning("Reflection loop failed: %s", e)
            result = ReflectionResult(
                original_response=original_response,
                final_response=original_response,
                quality_score=score,
                latency_ms=(time.time() - t0) * 1000,
            )

        result.latency_ms = (time.time() - t0) * 1000

        if result.improved:
            self._reflection_stats["improved"] += 1
            self._save_improvement_pattern(
                query=original_query,
                original=original_response,
                improved=result.final_response,
                critique=result.critique,
                intent=intent,
            )
            log.info(
                "Reflection: improved response [%s] score %.2f→%.2f in %.0fms",
                intent, score, result.quality_score, result.latency_ms
            )

        return result

    # ── Быстрая оценка качества (без LLM) ────────────────────────────────────

    def _score_response_fast(self, query: str, response: str, intent: str) -> float:
        """
        Эвристическая оценка качества ответа без вызова LLM.
        Быстро, дёшево, достаточно точно для фильтрации плохих ответов.
        """
        score = 0.5  # базовый score

        # Проверка наличия ошибок
        for pattern in _ERROR_PATTERNS:
            if re.search(pattern, response, re.IGNORECASE):
                score -= 0.2
                break

        # Сигналы качества
        quality_count = sum(
            1 for p in _QUALITY_SIGNALS
            if re.search(p, response)
        )
        score += min(quality_count * 0.05, 0.25)

        # Длина ответа (слишком короткий — плохо)
        words = len(response.split())
        if words < 10:
            score -= 0.25
        elif words < 20:
            score -= 0.1
        elif words > 50:
            score += 0.1
        elif words > 150:
            score += 0.15

        # Отвечает ли на вопрос (простая проверка)
        query_key_words = set(re.findall(r'\w{4,}', query.lower()))
        response_words = set(re.findall(r'\w{4,}', response.lower()))
        overlap = len(query_key_words & response_words)
        if query_key_words:
            score += min(overlap / len(query_key_words) * 0.2, 0.2)

        # Специфика по intent
        if intent == "code_change" and "```" not in response:
            score -= 0.15  # код должен содержать code block
        if intent == "math":
            if re.search(r'\d+[\+\-\*\/\=]\d+', response):
                score += 0.1
        if intent == "analysis" and words < 150:
            score -= 0.1  # анализ должен быть развёрнутым

        return max(0.0, min(1.0, score))

    # ── LLM-based reflection loop ─────────────────────────────────────────────

    def _llm_reflect_loop(
        self,
        query: str,
        response: str,
        intent: str,
        context: str,
        initial_score: float,
    ) -> ReflectionResult:
        """Запустить LLM-based critique + correction loop."""
        current_response = response
        current_score = initial_score
        improvements = []
        critique_text = ""

        for iteration in range(MAX_CORRECTION_ITERATIONS):
            # Critique pass
            critique = self._run_critique(query, current_response, intent, context)
            critique_text = critique

            # Если critique говорит что всё ОК — останавливаемся
            if self._critique_is_positive(critique):
                current_score = min(1.0, current_score + 0.2)
                break

            # Correction pass
            improved = self._run_correction(query, current_response, critique, intent)

            if not improved or improved == current_response:
                break

            # Проверяем что улучшение реальное
            new_score = self._score_response_fast(query, improved, intent)
            if new_score <= current_score:
                break  # не улучшилось — останавливаемся

            improvements.append(f"iter{iteration+1}: {critique[:100]}")
            current_response = improved
            current_score = new_score

        improved = current_response != response
        return ReflectionResult(
            original_response=response,
            final_response=current_response,
            quality_score=current_score,
            improved=improved,
            iterations=len(improvements),
            critique=critique_text,
            improvements=improvements,
        )

    def _run_critique(self, query: str, response: str, intent: str, context: str) -> str:
        """Получить critique через LLM."""
        system = (
            "Ты — технический критик AI-системы. Твоя задача — найти проблемы в ответе.\n"
            "Будь конкретен. Если ответ хорош — напиши 'КАЧЕСТВО: ХОРОШЕЕ'.\n"
            "Если есть проблемы — перечисли их кратко (1-3 пункта)."
        )
        ctx_part = f"\nКонтекст: {context[:300]}" if context else ""
        prompt = (
            f"Запрос: {query[:300]}\n"
            f"Intent: {intent}{ctx_part}\n\n"
            f"Ответ для оценки:\n{response[:1500]}\n\n"
            f"Оцени качество ответа. Найди ошибки, неточности, пропуски."
        )
        try:
            return self._llm_callback(prompt, system=system, max_tokens=500)
        except Exception as e:
            return f"Critique failed: {e}"

    def _run_correction(self, query: str, response: str, critique: str, intent: str) -> str:
        """Исправить ответ с учётом critique."""
        system = (
            "Ты — senior AI engineer. Улучши ответ с учётом critique.\n"
            "Исправь только указанные проблемы. Не меняй то что работает.\n"
            "Верни ТОЛЬКО улучшенный ответ, без пояснений."
        )
        prompt = (
            f"Запрос: {query[:300]}\n\n"
            f"Текущий ответ:\n{response[:1500]}\n\n"
            f"Critique:\n{critique[:400]}\n\n"
            f"Улучши ответ:"
        )
        try:
            return self._llm_callback(prompt, system=system, max_tokens=2000)
        except Exception as e:
            log.warning("Correction failed: %s", e)
            return response

    @staticmethod
    def _critique_is_positive(critique: str) -> bool:
        """Проверить что critique положительный (улучшения не нужны)."""
        positive_markers = [
            "КАЧЕСТВО: ХОРОШЕЕ",
            "ответ хорош",
            "всё правильно",
            "no issues",
            "GOOD QUALITY",
            "качество высокое",
        ]
        critique_lower = critique.lower()
        return any(m.lower() in critique_lower for m in positive_markers)

    # ── Сохранение паттернов ──────────────────────────────────────────────────

    def _save_improvement_pattern(self, query: str, original: str,
                                   improved: str, critique: str, intent: str) -> None:
        """Сохранить паттерн улучшения для самообучения."""
        if self._memory is None:
            return
        try:
            from memory.memory_store import KnowledgeEntry
            title = f"[REFLECTION] {intent}: {query[:50]}"
            if not self._memory.knowledge_exists(title[:40], category="solution"):
                self._memory.add_knowledge(KnowledgeEntry(
                    category="solution",
                    title=title,
                    content=(
                        f"Запрос: {query[:200]}\n"
                        f"Critique: {critique[:200]}\n"
                        f"Улучшение: {improved[:400]}"
                    ),
                    tags=["reflection", "improvement", intent],
                    importance=0.75,
                    source="reflection_engine",
                ))
        except Exception as e:
            log.debug("Save improvement failed: %s", e)

    # ── Публичный API ─────────────────────────────────────────────────────────

    def get_stats(self) -> Dict:
        s = self._reflection_stats
        total = s.get("total", 1)
        return {
            **s,
            "improvement_rate_pct": round(s.get("improved", 0) / max(total, 1) * 100, 1),
        }

    def get_report(self) -> str:
        s = self.get_stats()
        return (
            f"🔍 **Reflection Engine**\n"
            f"  Всего проверок: {s['total']}\n"
            f"  Улучшено: {s['improved']} ({s['improvement_rate_pct']}%)\n"
            f"  Пропущено: {s['skipped']}"
        )
