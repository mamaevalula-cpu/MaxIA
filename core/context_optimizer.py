# -*- coding: utf-8 -*-
"""
core/context_optimizer.py — Оптимизатор контекста для LLM-промптов.

Решает главный bottleneck: токены тратятся впустую на нерелевантный/повторяющийся контекст.

Функции:
  • Semantic deduplication — убирает дублирующийся контент из RAG
  • Conversation compression — сжимает старую историю в summary
  • Token budget enforcement — строгий лимит токенов на контекст
  • Working memory extraction — выделяет активный контекст задачи
  • Adaptive context loading — загружает только релевантные части
  • Session summarization — периодически сжимает длинные сессии

Экономия токенов: до 60-70% при длинных сессиях.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("core.context_optimizer")

# Токен-лимиты
MAX_CONTEXT_TOKENS   = 2000   # максимум RAG контекста в промпте
MAX_HISTORY_TOKENS   = 1500   # максимум истории диалога в промпте
MAX_WORKING_TOKENS   = 800    # максимум рабочей памяти текущей задачи
SUMMARY_TRIGGER      = 20     # сжимать сессию после N сообщений
DEDUP_THRESHOLD      = 0.70   # порог сходства для дедупликации (0..1)


def _token_count(text: str) -> int:
    """Быстрый подсчёт токенов (1 токен ≈ 4 символа)."""
    return max(1, len(text) // 4)


def _similarity(a: str, b: str) -> float:
    """Простая Jaccard-similarity по словам (без тяжёлых зависимостей)."""
    wa = set(re.findall(r'\w+', a.lower()))
    wb = set(re.findall(r'\w+', b.lower()))
    if not wa or not wb:
        return 0.0
    inter = wa & wb
    union = wa | wb
    return len(inter) / len(union)


def _fingerprint(text: str) -> str:
    """Быстрый fingerprint первых 200 символов."""
    return hashlib.md5(text[:200].lower().strip().encode()).hexdigest()


@dataclass
class WorkingMemory:
    """Рабочая память текущей задачи — активный контекст."""
    task_description: str = ""
    key_facts: List[str] = field(default_factory=list)
    recent_results: List[str] = field(default_factory=list)
    error_context: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_text(self) -> str:
        parts = []
        if self.task_description:
            parts.append(f"Текущая задача: {self.task_description}")
        if self.key_facts:
            parts.append("Ключевые факты:\n" + "\n".join(f"• {f}" for f in self.key_facts[-5:]))
        if self.recent_results:
            parts.append("Последние результаты:\n" + "\n".join(self.recent_results[-3:]))
        if self.error_context:
            parts.append("Ошибки в контексте:\n" + "\n".join(self.error_context[-3:]))
        return "\n\n".join(parts)

    @property
    def token_count(self) -> int:
        return _token_count(self.to_text())


@dataclass
class SessionSummary:
    """Сжатое резюме сессии."""
    session_id: str
    summary: str
    message_count: int
    created_at: float = field(default_factory=time.time)

    @property
    def token_count(self) -> int:
        return _token_count(self.summary)


class ContextOptimizer:
    """
    Singleton. Оптимизирует контекст перед передачей в LLM.

    Использование:
        opt = ContextOptimizer.get()
        optimized_context = opt.optimize_rag_context(raw_context, query)
        optimized_history = opt.compress_history(messages, budget=1500)
    """

    _instance: Optional["ContextOptimizer"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._working_memory: Dict[str, WorkingMemory] = {}  # session_id → WM
        self._session_summaries: Dict[str, SessionSummary] = {}
        self._message_counts: Dict[str, int] = {}
        self._dedup_cache: Dict[str, str] = {}   # fingerprint → first_seen content
        self._rlock = threading.RLock()
        # Статистика экономии токенов
        self._tokens_saved = 0
        self._tokens_total = 0
        log.info("ContextOptimizer initialized")

    @classmethod
    def get(cls) -> "ContextOptimizer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── RAG Context Optimization ──────────────────────────────────────────────

    def optimize_rag_context(self, raw_context: str, query: str,
                              max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
        """
        Оптимизировать RAG контекст перед вставкой в промпт.

        1. Семантическая дедупликация
        2. Обрезка по релевантности
        3. Token budget enforcement

        Returns: оптимизированная строка контекста
        """
        if not raw_context:
            return ""

        original_tokens = _token_count(raw_context)
        self._tokens_total += original_tokens

        # Разбить на блоки (по разделителю RAGEngine)
        blocks = [b.strip() for b in re.split(r'\n\n---\n\n', raw_context) if b.strip()]

        # Дедупликация
        blocks = self._deduplicate_blocks(blocks)

        # Ранжирование по релевантности к запросу
        blocks = self._rank_blocks(blocks, query)

        # Обрезка по budget
        result_blocks = []
        used = 0
        for block in blocks:
            t = _token_count(block)
            if used + t > max_tokens:
                break
            result_blocks.append(block)
            used += t

        optimized = "\n\n---\n\n".join(result_blocks)

        # Статистика
        saved = original_tokens - _token_count(optimized)
        if saved > 0:
            self._tokens_saved += saved
            log.debug("Context optimized: %d→%d tokens (saved %d)",
                      original_tokens, _token_count(optimized), saved)

        return optimized

    def _deduplicate_blocks(self, blocks: List[str]) -> List[str]:
        """Убрать дублирующиеся блоки по similarity."""
        unique: List[str] = []
        for block in blocks:
            is_dup = False
            for existing in unique:
                if _similarity(block, existing) >= DEDUP_THRESHOLD:
                    is_dup = True
                    break
            if not is_dup:
                unique.append(block)
        return unique

    def _rank_blocks(self, blocks: List[str], query: str) -> List[str]:
        """Ранжировать блоки по релевантности к запросу."""
        query_words = set(re.findall(r'\w+', query.lower()))
        if not query_words:
            return blocks

        scored = []
        for block in blocks:
            block_words = set(re.findall(r'\w+', block.lower()))
            overlap = len(query_words & block_words) / max(len(query_words), 1)
            scored.append((overlap, block))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored]

    # ── History Compression ───────────────────────────────────────────────────

    def compress_history(self, messages: List[Dict], budget: int = MAX_HISTORY_TOKENS,
                          session_id: str = "") -> List[Dict]:
        """
        Сжать историю диалога до token budget.

        Стратегия:
        1. Если история умещается — вернуть как есть
        2. Если нет — взять summary (если есть) + свежие сообщения
        3. Приоритет: последние сообщения важнее старых

        Args:
            messages: список dict {role, content}
            budget: лимит токенов
            session_id: для хранения summary

        Returns: сжатый список сообщений
        """
        if not messages:
            return []

        total_tokens = sum(_token_count(m.get("content", "")) for m in messages)

        if total_tokens <= budget:
            return messages

        # Подсчёт от новых к старым, пока не превысим budget
        result = []
        used = 0
        for msg in reversed(messages):
            t = _token_count(msg.get("content", ""))
            if used + t > budget:
                break
            result.insert(0, msg)
            used += t

        # Если есть summary для пропущенных — добавить в начало
        if session_id and session_id in self._session_summaries:
            summary = self._session_summaries[session_id]
            if len(result) < len(messages):  # что-то обрезали
                result.insert(0, {
                    "role": "system",
                    "content": f"[Краткое содержание предыдущего разговора]:\n{summary.summary}"
                })

        saved = total_tokens - used
        if saved > 0:
            self._tokens_saved += saved
            log.debug("History compressed: %d→%d tokens (saved %d), %d/%d messages",
                      total_tokens, used, saved, len(result), len(messages))

        return result

    def build_compressed_messages(self, history: List[Dict], current_query: str,
                                   rag_context: str = "", budget: int = 3000) -> List[Dict]:
        """
        Построить оптимальный список сообщений для LLM.

        Распределение бюджета:
        - RAG context: до 35% бюджета
        - History: до 45% бюджета
        - Current query: остаток

        Returns: финальный список messages для LLM API
        """
        rag_budget  = int(budget * 0.35)
        hist_budget = int(budget * 0.45)

        # Оптимизировать RAG
        opt_rag = self.optimize_rag_context(rag_context, current_query, rag_budget)

        # Сжать историю
        compressed_hist = self.compress_history(history, hist_budget)

        # Собрать финальный список
        result = list(compressed_hist)

        # Добавить RAG как системный контекст если есть
        if opt_rag:
            # Вставить перед последним user message (или в начало)
            insert_pos = 0
            for i, m in enumerate(result):
                if m.get("role") == "user":
                    insert_pos = i
                    break
            result.insert(insert_pos, {
                "role": "system",
                "content": f"Релевантный контекст:\n{opt_rag}"
            })

        # Убедиться что текущий запрос последний
        if not result or result[-1].get("content") != current_query:
            result.append({"role": "user", "content": current_query})

        return result

    # ── Working Memory ────────────────────────────────────────────────────────

    def get_working_memory(self, session_id: str) -> WorkingMemory:
        """Получить рабочую память сессии (создать если нет)."""
        with self._rlock:
            if session_id not in self._working_memory:
                self._working_memory[session_id] = WorkingMemory()
            return self._working_memory[session_id]

    def update_working_memory(self, session_id: str,
                               task: str = "",
                               fact: str = "",
                               result: str = "",
                               error: str = "") -> None:
        """Обновить рабочую память сессии."""
        with self._rlock:
            wm = self.get_working_memory(session_id)
            wm.updated_at = time.time()
            if task:
                wm.task_description = task[:300]
            if fact:
                wm.key_facts.append(fact[:200])
                wm.key_facts = wm.key_facts[-10:]  # держим последние 10
            if result:
                wm.recent_results.append(result[:300])
                wm.recent_results = wm.recent_results[-5:]
            if error:
                wm.error_context.append(error[:200])
                wm.error_context = wm.error_context[-3:]

    def clear_working_memory(self, session_id: str) -> None:
        """Очистить рабочую память (после завершения задачи)."""
        with self._rlock:
            self._working_memory.pop(session_id, None)

    # ── Session Summarization ─────────────────────────────────────────────────

    def maybe_summarize_session(self, session_id: str, messages: List[Dict],
                                  llm_callback: Optional[callable] = None) -> bool:
        """
        Сжать сессию в summary если превышен порог.

        Args:
            session_id: ID сессии
            messages: история сообщений
            llm_callback: callable(prompt) → str для генерации summary через LLM

        Returns: True если summary был создан
        """
        count = len(messages)
        self._message_counts[session_id] = count

        # Проверяем порог
        if count < SUMMARY_TRIGGER:
            return False

        # Проверяем что summary не устарел (не для этого же количества)
        existing = self._session_summaries.get(session_id)
        if existing and existing.message_count >= count - 5:
            return False  # уже актуальный summary

        if llm_callback is None:
            # Простой summary без LLM — ключевые факты из ассистента
            summary_parts = []
            for m in messages[-SUMMARY_TRIGGER:]:
                if m.get("role") == "assistant":
                    content = m.get("content", "")[:150]
                    if content:
                        summary_parts.append(content)
            summary_text = " | ".join(summary_parts[:5])
        else:
            # LLM-based summary
            try:
                history_text = "\n".join(
                    f"{m.get('role','?')}: {m.get('content','')[:200]}"
                    for m in messages[-min(count, 30):]
                )
                prompt = (
                    f"Сделай краткое резюме этого разговора (3-5 ключевых пунктов, "
                    f"не более 300 слов):\n\n{history_text}"
                )
                summary_text = llm_callback(prompt)
            except Exception as e:
                log.warning("Session summary failed: %s", e)
                return False

        summary = SessionSummary(
            session_id=session_id,
            summary=summary_text,
            message_count=count,
        )
        with self._rlock:
            self._session_summaries[session_id] = summary

        log.info("Session %s summarized (%d messages → %d tokens)",
                 session_id[:8], count, summary.token_count)
        return True

    # ── Статистика ────────────────────────────────────────────────────────────

    @property
    def efficiency_ratio(self) -> float:
        """Доля сэкономленных токенов (0..1)."""
        if self._tokens_total == 0:
            return 0.0
        return self._tokens_saved / self._tokens_total

    def get_stats(self) -> Dict:
        return {
            "tokens_total":    self._tokens_total,
            "tokens_saved":    self._tokens_saved,
            "efficiency_pct":  round(self.efficiency_ratio * 100, 1),
            "active_sessions": len(self._working_memory),
            "session_summaries": len(self._session_summaries),
        }

    def get_report(self) -> str:
        s = self.get_stats()
        return (
            f"⚡ **Context Optimizer**\n"
            f"  Токенов обработано: {s['tokens_total']:,}\n"
            f"  Сэкономлено: {s['tokens_saved']:,} ({s['efficiency_pct']}%)\n"
            f"  Активных сессий: {s['active_sessions']}\n"
            f"  Session summaries: {s['session_summaries']}"
        )
