# -*- coding: utf-8 -*-
"""
training/conflict_manager.py — Систематическое управление конфликтами знаний.

Конфликт = два знания противоречат друг другу, подрывая достоверность системы.

Типы конфликтов:
  • semantic     — содержат противоположные утверждения (не/нет/никогда vs да/всегда)
  • duplicate    — почти идентичное содержание (Jaccard >= 0.70)
  • version      — более новое знание заменяет более старое на ту же тему
  • importance   — одно знание помечено critical, другое — ignorable
  • category     — одна тема классифицирована по-разному

Стратегии разрешения:
  KEEP_NEWER      — сохранить более свежее, архивировать старое
  KEEP_CONFIDENT  — сохранить с более высоким confidence
  KEEP_IMPORTANT  — сохранить с более высоким importance
  MERGE           — объединить содержание (автоматически)
  ARCHIVE_BOTH    — оба помечаются deprecated, добавляется conflict-тег
  MANUAL          — отложить для ручного разрешения

Использование:
    cm = ConflictManager.get()
    result = cm.check_conflicts(new_entry)
    if result.has_conflict:
        cm.resolve(result.conflict_entry_id, new_entry_id, strategy=KEEP_NEWER)
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

log = logging.getLogger("training.conflict")

# ── Параметры ─────────────────────────────────────────────────────────────────

DUPLICATE_THRESHOLD  = 0.70   # Jaccard ≥ порог → дубликат
SEMANTIC_THRESHOLD   = 0.45   # Jaccard ≥ порог → семантически близкие
MIN_WORDS_FOR_CHECK  = 8      # меньше слов — не проверяем семантику
MAX_CANDIDATES       = 50     # сколько кандидатов проверить


# ── Семантические паттерны противоречий ──────────────────────────────────────

_NEGATION_WORDS = frozenset([
    "не ", "нет ", "никогда", "нельзя", "запрещено", "невозможно",
    "never", "not ", "no ", "impossible", "forbidden", "avoid",
])
_AFFIRMATION_WORDS = frozenset([
    "всегда", "обязательно", "необходимо", "нужно", "должен", "следует",
    "always", "must", "required", "should", "mandatory",
])


# ── Структуры данных ──────────────────────────────────────────────────────────

class ConflictType(str, Enum):
    DUPLICATE   = "duplicate"
    SEMANTIC    = "semantic"
    VERSION     = "version"
    NONE        = "none"


class ResolutionStrategy(str, Enum):
    KEEP_NEWER      = "keep_newer"
    KEEP_CONFIDENT  = "keep_confident"
    KEEP_IMPORTANT  = "keep_important"
    MERGE           = "merge"
    ARCHIVE_BOTH    = "archive_both"
    MANUAL          = "manual"


@dataclass
class ConflictResult:
    has_conflict: bool                 = False
    conflict_type: ConflictType        = ConflictType.NONE
    conflict_entry_id: int             = 0
    conflict_entry_title: str          = ""
    similarity: float                  = 0.0
    suggested_strategy: ResolutionStrategy = ResolutionStrategy.KEEP_NEWER
    details: str                       = ""


@dataclass
class ResolutionReport:
    entry_id_kept:    int     = 0
    entry_id_removed: int     = 0
    strategy:         str     = ""
    action_taken:     str     = ""
    success:          bool    = False
    details:          str     = ""


# ── Главный класс ─────────────────────────────────────────────────────────────

class ConflictManager:
    """
    Singleton — обнаружение и систематическое разрешение конфликтов в knowledge-базе.
    """

    _instance: Optional["ConflictManager"] = None

    @classmethod
    def get(cls) -> "ConflictManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _mem(self):
        from memory.memory_store import MemoryStore
        return MemoryStore.get()

    # ── Проверка конфликтов ───────────────────────────────────────────────────

    def check_conflicts(self, new_entry) -> ConflictResult:
        """
        Проверить новое знание на конфликты с существующими.
        Возвращает ConflictResult с деталями.
        """
        try:
            return self._check_conflicts_impl(new_entry)
        except Exception as e:
            log.warning("Conflict check error for '%s': %s",
                        getattr(new_entry, "title", "?"), e)
            return ConflictResult()   # нет конфликта по умолчанию (безопасно)

    def _check_conflicts_impl(self, new_entry) -> ConflictResult:
        mem = self._mem()

        # Поиск кандидатов по ключевым словам
        title_words = set(re.findall(r'\b\w{4,}\b', new_entry.title.lower()))
        if not title_words:
            return ConflictResult()

        query = " ".join(list(title_words)[:6])
        candidates = mem.search_knowledge(query, limit=MAX_CANDIDATES)

        new_words = set(re.findall(r'\b\w{4,}\b',
                                   f"{new_entry.title} {new_entry.content}".lower()))
        if len(new_words) < MIN_WORDS_FOR_CHECK:
            return ConflictResult()

        best: Optional[ConflictResult] = None

        for cand in candidates:
            if getattr(cand, "id", 0) == getattr(new_entry, "id", 0):
                continue
            if getattr(cand, "knowledge_type", "") == "deprecated":
                continue   # уже архивированные — игнорируем

            cand_words = set(re.findall(r'\b\w{4,}\b',
                                        f"{cand.title} {cand.content}".lower()))
            if not cand_words:
                continue

            similarity = self._jaccard(new_words, cand_words)

            if similarity >= DUPLICATE_THRESHOLD:
                result = ConflictResult(
                    has_conflict=True,
                    conflict_type=ConflictType.DUPLICATE,
                    conflict_entry_id=cand.id,
                    conflict_entry_title=cand.title,
                    similarity=round(similarity, 3),
                    suggested_strategy=self._suggest_strategy(new_entry, cand),
                    details=f"Jaccard={similarity:.2f} (≥{DUPLICATE_THRESHOLD})",
                )
                # Дубликат — самый серьёзный конфликт, сразу возвращаем
                return result

            elif similarity >= SEMANTIC_THRESHOLD:
                semantic_conflict = self._check_semantic_conflict(new_entry, cand)
                if semantic_conflict:
                    result = ConflictResult(
                        has_conflict=True,
                        conflict_type=ConflictType.SEMANTIC,
                        conflict_entry_id=cand.id,
                        conflict_entry_title=cand.title,
                        similarity=round(similarity, 3),
                        suggested_strategy=ResolutionStrategy.KEEP_CONFIDENT,
                        details=semantic_conflict,
                    )
                    if best is None or result.similarity > best.similarity:
                        best = result

        return best if best else ConflictResult()

    def check_pair(self, entry_a, entry_b) -> ConflictResult:
        """Проверить два конкретных знания на конфликт между собой."""
        words_a = set(re.findall(r'\b\w{4,}\b',
                                 f"{entry_a.title} {entry_a.content}".lower()))
        words_b = set(re.findall(r'\b\w{4,}\b',
                                 f"{entry_b.title} {entry_b.content}".lower()))
        if not words_a or not words_b:
            return ConflictResult()

        sim = self._jaccard(words_a, words_b)

        if sim >= DUPLICATE_THRESHOLD:
            return ConflictResult(
                has_conflict=True,
                conflict_type=ConflictType.DUPLICATE,
                conflict_entry_id=entry_b.id,
                conflict_entry_title=entry_b.title,
                similarity=round(sim, 3),
                suggested_strategy=self._suggest_strategy(entry_a, entry_b),
                details=f"Jaccard={sim:.2f}",
            )

        if sim >= SEMANTIC_THRESHOLD:
            sc = self._check_semantic_conflict(entry_a, entry_b)
            if sc:
                return ConflictResult(
                    has_conflict=True,
                    conflict_type=ConflictType.SEMANTIC,
                    conflict_entry_id=entry_b.id,
                    conflict_entry_title=entry_b.title,
                    similarity=round(sim, 3),
                    suggested_strategy=ResolutionStrategy.KEEP_CONFIDENT,
                    details=sc,
                )

        return ConflictResult()

    # ── Разрешение конфликтов ─────────────────────────────────────────────────

    def resolve(
        self,
        entry_id_keep: int,
        entry_id_remove: int,
        strategy: ResolutionStrategy = ResolutionStrategy.KEEP_NEWER,
        reason: str = "",
    ) -> ResolutionReport:
        """
        Разрешить конфликт между двумя знаниями.
        entry_id_keep — победитель; entry_id_remove — будет обработан по стратегии.
        """
        mem = self._mem()
        entries_keep   = [e for e in mem.get_knowledge(limit=1000)
                          if e.id == entry_id_keep]
        entries_remove = [e for e in mem.get_knowledge(limit=1000)
                          if e.id == entry_id_remove]

        if not entries_keep or not entries_remove:
            return ResolutionReport(
                success=False,
                details=f"Не найдены записи: keep={entry_id_keep}, remove={entry_id_remove}",
            )

        winner = entries_keep[0]
        loser  = entries_remove[0]

        if strategy == ResolutionStrategy.KEEP_NEWER:
            return self._apply_keep_winner(winner, loser, strategy, reason)

        elif strategy == ResolutionStrategy.KEEP_CONFIDENT:
            # Автоматически выбрать по confidence
            if winner.confidence >= loser.confidence:
                return self._apply_keep_winner(winner, loser, strategy, reason)
            else:
                return self._apply_keep_winner(loser, winner, strategy, reason)

        elif strategy == ResolutionStrategy.KEEP_IMPORTANT:
            if winner.importance >= loser.importance:
                return self._apply_keep_winner(winner, loser, strategy, reason)
            else:
                return self._apply_keep_winner(loser, winner, strategy, reason)

        elif strategy == ResolutionStrategy.MERGE:
            return self._apply_merge(winner, loser, reason)

        elif strategy == ResolutionStrategy.ARCHIVE_BOTH:
            return self._apply_archive_both(winner, loser, reason)

        elif strategy == ResolutionStrategy.MANUAL:
            return self._apply_mark_manual(winner, loser, reason)

        return ResolutionReport(
            success=False,
            details=f"Неизвестная стратегия: {strategy}",
        )

    def auto_resolve_all(self, dry_run: bool = False) -> List[ResolutionReport]:
        """
        Найти и автоматически разрешить все конфликты в базе.
        Использует стратегию KEEP_CONFIDENT.
        dry_run=True — только показать, не применять.
        """
        from cleaner.knowledge_cleaner import KnowledgeCleaner
        reports = []
        entries = self._mem().get_knowledge(limit=500)
        checked: set = set()

        for i, entry_a in enumerate(entries):
            if getattr(entry_a, "knowledge_type", "") == "deprecated":
                continue
            for entry_b in entries[i + 1:]:
                pair_key = tuple(sorted([entry_a.id, entry_b.id]))
                if pair_key in checked:
                    continue
                checked.add(pair_key)

                result = self.check_pair(entry_a, entry_b)
                if not result.has_conflict:
                    continue

                if dry_run:
                    log.info("[dry_run] Conflict: '%s' vs '%s' (%s sim=%.2f)",
                             entry_a.title[:40], entry_b.title[:40],
                             result.conflict_type, result.similarity)
                    reports.append(ResolutionReport(
                        entry_id_kept=entry_a.id,
                        entry_id_removed=entry_b.id,
                        strategy=str(result.suggested_strategy),
                        action_taken="dry_run",
                        success=True,
                        details=result.details,
                    ))
                else:
                    strategy = result.suggested_strategy
                    r = self.resolve(entry_a.id, entry_b.id, strategy,
                                     reason=f"auto_resolve: {result.conflict_type}")
                    reports.append(r)
                    if r.success:
                        log.info("Auto-resolved conflict between %d and %d via %s",
                                 entry_a.id, entry_b.id, strategy)

        return reports

    def stats(self) -> dict:
        """Статистика конфликтов в текущей базе."""
        entries = self._mem().get_knowledge(limit=500)
        conflict_tagged = sum(
            1 for e in entries
            if "conflict" in (getattr(e, "tags", None) or [])
        )
        deprecated = sum(
            1 for e in entries
            if getattr(e, "knowledge_type", "") == "deprecated"
        )
        return {
            "total_entries": len(entries),
            "conflict_tagged": conflict_tagged,
            "deprecated": deprecated,
        }

    # ── Вспомогательные ───────────────────────────────────────────────────────

    @staticmethod
    def _jaccard(set_a: set, set_b: set) -> float:
        if not set_a or not set_b:
            return 0.0
        inter = len(set_a & set_b)
        union = len(set_a | set_b)
        return inter / union if union else 0.0

    def _check_semantic_conflict(self, entry_a, entry_b) -> str:
        """
        Простая проверка семантического противоречия:
        одно утверждение содержит отрицание там, где другое — утверждение.
        Возвращает описание противоречия или пустую строку.
        """
        text_a = f"{entry_a.title} {entry_a.content}".lower()
        text_b = f"{entry_b.title} {entry_b.content}".lower()

        neg_a = any(w in text_a for w in _NEGATION_WORDS)
        neg_b = any(w in text_b for w in _NEGATION_WORDS)
        aff_a = any(w in text_a for w in _AFFIRMATION_WORDS)
        aff_b = any(w in text_b for w in _AFFIRMATION_WORDS)

        # A говорит "нельзя", B говорит "нужно" — или наоборот
        if (neg_a and aff_b) or (neg_b and aff_a):
            return (f"Семантическое противоречие: "
                    f"neg_a={neg_a}, aff_a={aff_a} vs neg_b={neg_b}, aff_b={aff_b}")
        return ""

    def _suggest_strategy(self, new_entry, existing_entry) -> ResolutionStrategy:
        """Рекомендовать стратегию разрешения на основе метаданных."""
        new_conf  = getattr(new_entry, "confidence", 0.5)
        ex_conf   = getattr(existing_entry, "confidence", 0.5)
        new_ts    = getattr(new_entry, "ts", 0.0)
        ex_ts     = getattr(existing_entry, "ts", 0.0)
        ex_uc     = getattr(existing_entry, "usage_count", 0)

        # Если существующее активно используется — предпочесть ручной выбор
        if ex_uc > 5:
            return ResolutionStrategy.KEEP_IMPORTANT

        # Если confidence сильно различается — выбрать по нему
        if abs(new_conf - ex_conf) > 0.2:
            return ResolutionStrategy.KEEP_CONFIDENT

        # Иначе — более свежее
        return ResolutionStrategy.KEEP_NEWER

    def _apply_keep_winner(self, winner, loser, strategy, reason: str) -> ResolutionReport:
        """Сохранить winner, архивировать loser."""
        mem = self._mem()
        try:
            # Добавить тег conflict к побеждённому и пометить deprecated
            loser_tags = list(getattr(loser, "tags", None) or [])
            if "conflict" not in loser_tags:
                loser_tags.append("conflict")

            mem.update_knowledge(
                loser.id,
                knowledge_type="deprecated",
                tags=loser_tags,
            )

            # Добавить тег resolved к победителю
            winner_tags = list(getattr(winner, "tags", None) or [])
            if "conflict_resolved" not in winner_tags:
                winner_tags.append("conflict_resolved")
            mem.update_knowledge(winner.id, tags=winner_tags)

            self._log_resolution(winner.id, loser.id, str(strategy), reason)
            return ResolutionReport(
                entry_id_kept=winner.id,
                entry_id_removed=loser.id,
                strategy=str(strategy),
                action_taken=f"Archived entry #{loser.id} as deprecated",
                success=True,
                details=f"Winner conf={winner.confidence:.2f}, loser conf={loser.confidence:.2f}",
            )
        except Exception as e:
            log.error("Resolution failed: %s", e)
            return ResolutionReport(success=False, details=str(e))

    def _apply_merge(self, entry_a, entry_b, reason: str) -> ResolutionReport:
        """Объединить контент двух записей в одну."""
        mem = self._mem()
        try:
            merged_content = (
                f"[MERGED от {time.strftime('%d.%m.%Y')}]\n\n"
                f"Версия 1 ({entry_a.title}):\n{entry_a.content}\n\n"
                f"Версия 2 ({entry_b.title}):\n{entry_b.content}"
            )
            merged_title = entry_a.title  # сохраняем более старый заголовок

            # Обновляем entry_a с объединённым контентом
            mem.update_knowledge(
                entry_a.id,
                title=merged_title,
                content=merged_content,
                importance=max(entry_a.importance, entry_b.importance),
                confidence=max(entry_a.confidence, entry_b.confidence),
                tags=list(set(
                    (entry_a.tags or []) + (entry_b.tags or []) + ["merged"]
                )),
            )

            # Архивируем entry_b
            b_tags = list(entry_b.tags or [])
            if "conflict" not in b_tags:
                b_tags.append("conflict")
            mem.update_knowledge(entry_b.id, knowledge_type="deprecated", tags=b_tags)

            self._log_resolution(entry_a.id, entry_b.id, "merge", reason)
            return ResolutionReport(
                entry_id_kept=entry_a.id,
                entry_id_removed=entry_b.id,
                strategy="merge",
                action_taken=f"Merged #{entry_b.id} into #{entry_a.id}",
                success=True,
                details="Contents merged",
            )
        except Exception as e:
            log.error("Merge failed: %s", e)
            return ResolutionReport(success=False, details=str(e))

    def _apply_archive_both(self, entry_a, entry_b, reason: str) -> ResolutionReport:
        """Оба знания архивируются как конфликтные — требуют ручного разрешения."""
        mem = self._mem()
        try:
            for entry in (entry_a, entry_b):
                tags = list(entry.tags or [])
                if "conflict" not in tags:
                    tags.append("conflict")
                mem.update_knowledge(
                    entry.id,
                    knowledge_type="deprecated",
                    tags=tags,
                )

            self._log_resolution(entry_a.id, entry_b.id, "archive_both", reason)
            return ResolutionReport(
                entry_id_kept=0,
                entry_id_removed=entry_b.id,
                strategy="archive_both",
                action_taken=f"Both #{entry_a.id} and #{entry_b.id} archived as conflicts",
                success=True,
            )
        except Exception as e:
            return ResolutionReport(success=False, details=str(e))

    def _apply_mark_manual(self, entry_a, entry_b, reason: str) -> ResolutionReport:
        """Пометить оба знания тегом 'needs_manual_review'."""
        mem = self._mem()
        try:
            for entry in (entry_a, entry_b):
                tags = list(entry.tags or [])
                if "needs_manual_review" not in tags:
                    tags.append("needs_manual_review")
                if "conflict" not in tags:
                    tags.append("conflict")
                mem.update_knowledge(entry.id, tags=tags)

            self._log_resolution(entry_a.id, entry_b.id, "manual", reason)
            return ResolutionReport(
                entry_id_kept=entry_a.id,
                entry_id_removed=entry_b.id,
                strategy="manual",
                action_taken="Both marked needs_manual_review",
                success=True,
            )
        except Exception as e:
            return ResolutionReport(success=False, details=str(e))

    def _log_resolution(self, winner_id: int, loser_id: int,
                        strategy: str, reason: str) -> None:
        """Записать разрешение конфликта в training_log."""
        try:
            from memory.memory_store import MemoryStore
            MemoryStore.get().log_training(
                action="conflict_resolve",
                entry_id=winner_id,
                reason=f"strategy={strategy} loser={loser_id} reason={reason}",
                agent="conflict_manager",
            )
        except Exception:
            pass
