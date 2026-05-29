# -*- coding: utf-8 -*-
"""
cleaner/knowledge_cleaner.py — Автоматическая самоорганизация памяти.

Запускается:
  • Автоматически каждые 24 часа (из SelfTrainingAgent)
  • После важных изменений
  • После ошибок
  • По команде: «наведи порядок», «очисти память», «cleaner»

Что делает:
  1. backfill_metadata()    — заполняет knowledge_type/confidence у старых записей
  2. find_duplicates()      — пары с Jaccard similarity > порога
  3. find_stale()           — старые неиспользуемые записи
  4. find_low_quality()     — мусорные/слабые записи
  5. find_conflicts()       — противоречия (title/content heuristic)
  6. run_maintenance()      — полный цикл: анализ → действия → отчёт
  7. cleanup_report()       — читаемый отчёт о состоянии памяти
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("cleaner.knowledge")

# ── Пороги ────────────────────────────────────────────────────────────────────

DUPLICATE_THRESHOLD   = 0.70   # Jaccard similarity → дубль
STALE_DAYS            = 30     # дней без применения → устаревшее
STALE_IMPORTANCE_MAX  = 0.55   # устаревшие записи не удаляем если важность высокая
LOW_QUALITY_CONF      = 0.25   # confidence < N → плохое качество
LOW_QUALITY_IMP       = 0.35   # importance < N → низкая ценность
MIN_CONTENT_LEN       = 80     # короче → удалить
MAX_DEPRECATED_AGE    = 90     # дней в deprecated → физическое удаление
BATCH_LIMIT           = 500    # максимум записей для анализа дублей


# ── Типы проблем ──────────────────────────────────────────────────────────────

@dataclass
class DuplicatePair:
    id_a: int
    id_b: int
    title_a: str
    title_b: str
    similarity: float
    recommendation: str  # "merge_into_a" | "remove_b" | "review"


@dataclass
class StaleEntry:
    id: int
    title: str
    category: str
    importance: float
    age_days: float
    usage_count: int
    recommendation: str  # "deprecate" | "delete" | "keep"


@dataclass
class LowQualityEntry:
    id: int
    title: str
    confidence: float
    importance: float
    reason: str
    recommendation: str  # "delete" | "demote" | "mark_hypothesis"


@dataclass
class ConflictPair:
    id_a: int
    id_b: int
    title_a: str
    title_b: str
    signal: str   # почему считаем конфликтом
    recommendation: str  # "keep_a" | "keep_b" | "merge" | "review"


@dataclass
class MaintenanceReport:
    run_at: float            = field(default_factory=time.time)
    duration_s: float        = 0.0
    total_knowledge: int     = 0
    backfilled: int          = 0
    duplicates: List[DuplicatePair]       = field(default_factory=list)
    stale: List[StaleEntry]               = field(default_factory=list)
    low_quality: List[LowQualityEntry]    = field(default_factory=list)
    conflicts: List[ConflictPair]         = field(default_factory=list)
    actions_taken: List[str]              = field(default_factory=list)
    errors: List[str]                     = field(default_factory=list)


class KnowledgeCleaner:
    """
    Singleton — анализирует и очищает базу знаний.
    Не удаляет ничего без явного флага safe_delete=True.
    По умолчанию: помечает, понижает importance, пишет в training_log.
    """

    _instance: Optional["KnowledgeCleaner"] = None
    _last_run: float = 0.0

    @classmethod
    def get(cls) -> "KnowledgeCleaner":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _mem(self):
        from memory.memory_store import MemoryStore
        return MemoryStore.get()

    def _journal(self):
        from training.training_journal import TrainingJournal
        return TrainingJournal.get()

    # ══════════════════════════════════════════════════════════════════════════
    # ПУБЛИЧНЫЙ API
    # ══════════════════════════════════════════════════════════════════════════

    def run_maintenance(self, safe_delete: bool = False,
                        verbose: bool = True) -> MaintenanceReport:
        """
        Полный цикл обслуживания:
          1. Backfill метаданных (knowledge_type / confidence)
          2. Поиск дублей
          3. Поиск устаревших
          4. Поиск низкокачественных
          5. Поиск конфликтов
          6. Применение безопасных исправлений
          7. Запись в training_log

        safe_delete=True → физически удаляет подтверждённый мусор (осторожно!)
        """
        t0 = time.time()
        report = MaintenanceReport()

        try:
            entries = self._mem().get_knowledge(limit=BATCH_LIMIT)
            report.total_knowledge = len(entries)

            if not entries:
                log.info("KnowledgeCleaner: nothing to clean")
                return report

            # 1. Backfill
            report.backfilled = self.backfill_metadata(entries)

            # 2-5. Анализ
            report.duplicates  = self.find_duplicates(entries)
            report.stale       = self.find_stale(entries)
            report.low_quality = self.find_low_quality(entries)
            report.conflicts   = self.find_conflicts(entries)

            # 6. Применяем безопасные исправления
            actions = self._apply_fixes(
                report, safe_delete=safe_delete)
            report.actions_taken = actions

        except Exception as e:
            report.errors.append(str(e))
            log.error("KnowledgeCleaner error: %s", e)
        finally:
            report.duration_s = round(time.time() - t0, 2)
            KnowledgeCleaner._last_run = time.time()

        # 7. Журнал
        try:
            self._journal().record_cycle_end(
                cycle=0,
                saved=report.backfilled,
                rejected=len(report.low_quality),
                updated=len(report.actions_taken),
                duration_s=report.duration_s,
            )
            self._mem().log_training(
                action="maintenance",
                reason=(
                    f"dupes={len(report.duplicates)} stale={len(report.stale)} "
                    f"low_q={len(report.low_quality)} conflicts={len(report.conflicts)} "
                    f"actions={len(report.actions_taken)}"
                ),
                quality=self._health_score(report),
                agent="knowledge_cleaner",
            )
        except Exception as e:
            log.debug("Maintenance log error: %s", e)

        log.info(
            "KnowledgeCleaner: done in %.1fs | dupes=%d stale=%d low_q=%d conflicts=%d",
            report.duration_s, len(report.duplicates),
            len(report.stale), len(report.low_quality), len(report.conflicts),
        )
        return report

    def cleanup_report(self) -> str:
        """Текстовый отчёт о текущем состоянии памяти."""
        entries = self._mem().get_knowledge(limit=BATCH_LIMIT)
        report = MaintenanceReport(total_knowledge=len(entries))
        if entries:
            report.duplicates  = self.find_duplicates(entries)
            report.stale       = self.find_stale(entries)
            report.low_quality = self.find_low_quality(entries)
            report.conflicts   = self.find_conflicts(entries)
        return self._format_report(report)

    # ══════════════════════════════════════════════════════════════════════════
    # АНАЛИЗ
    # ══════════════════════════════════════════════════════════════════════════

    def backfill_metadata(self, entries: list) -> int:
        """
        Заполняет knowledge_type и confidence для старых записей
        у которых стоит дефолт 'auto' / 0.5.
        Возвращает количество обновлённых записей.
        """
        from training.knowledge_validator import KnowledgeValidator
        validator = KnowledgeValidator.get()
        updated = 0

        for e in entries:
            needs_type = (e.knowledge_type in ("auto", "", None))
            needs_conf = (abs(e.confidence - 0.5) < 0.001)

            if not (needs_type or needs_conf):
                continue

            try:
                # Определяем тип через валидатор
                new_type = validator._classify_type(e) if needs_type else e.knowledge_type
                new_conf = validator._calc_confidence(e, 0.7) if needs_conf else e.confidence

                self._mem().update_knowledge(
                    e.id,
                    knowledge_type=new_type if needs_type else None,
                    confidence=new_conf if needs_conf else None,
                )
                updated += 1
            except Exception as ex:
                log.debug("Backfill error id=%d: %s", e.id, ex)

        if updated:
            log.info("KnowledgeCleaner: backfilled %d entries", updated)
        return updated

    def find_duplicates(self, entries: list) -> List[DuplicatePair]:
        """
        Jaccard similarity по словам между парами записей.
        Анализирует только пары с похожими title-словами (pre-filter).
        """
        pairs: List[DuplicatePair] = []
        seen_ids: Set[int] = set()

        # Pre-index: title words → entry ids
        title_idx: Dict[str, List[int]] = {}
        word_sets: Dict[int, Set[str]] = {}

        for e in entries:
            words = set(re.findall(r'\b\w{4,}\b', (e.title + " " + e.content[:300]).lower()))
            word_sets[e.id] = words
            title_words = set(re.findall(r'\b\w{4,}\b', e.title.lower()))
            for w in title_words:
                title_idx.setdefault(w, []).append(e.id)

        # Candidate pairs via title word overlap
        candidate_pairs: Set[Tuple[int, int]] = set()
        for ids in title_idx.values():
            if len(ids) < 2:
                continue
            for i in range(len(ids)):
                for j in range(i + 1, min(i + 6, len(ids))):
                    a, b = min(ids[i], ids[j]), max(ids[i], ids[j])
                    candidate_pairs.add((a, b))

        # Score candidates
        entry_by_id = {e.id: e for e in entries}
        for id_a, id_b in candidate_pairs:
            if id_a in seen_ids and id_b in seen_ids:
                continue
            wa = word_sets.get(id_a, set())
            wb = word_sets.get(id_b, set())
            if not wa or not wb:
                continue
            intersection = len(wa & wb)
            union = len(wa | wb)
            sim = intersection / union if union else 0.0
            if sim >= DUPLICATE_THRESHOLD:
                ea = entry_by_id.get(id_a)
                eb = entry_by_id.get(id_b)
                if not ea or not eb:
                    continue
                # Keep the higher importance one
                if ea.importance >= eb.importance:
                    rec = "remove_b"
                else:
                    rec = "remove_a_keep_b"
                pairs.append(DuplicatePair(
                    id_a=id_a, id_b=id_b,
                    title_a=ea.title[:60], title_b=eb.title[:60],
                    similarity=round(sim, 3),
                    recommendation=rec,
                ))
                seen_ids.add(id_b)

        return pairs[:30]  # не перегружаем отчёт

    def find_stale(self, entries: list) -> List[StaleEntry]:
        """
        Устаревшие знания:
          - usage_count = 0
          - возраст > STALE_DAYS
          - importance < STALE_IMPORTANCE_MAX
        """
        now = time.time()
        stale_ts = now - STALE_DAYS * 86400
        results: List[StaleEntry] = []

        for e in entries:
            if e.ts >= stale_ts:
                continue  # молодая запись — не трогаем
            if e.importance > STALE_IMPORTANCE_MAX:
                continue  # высокая ценность — сохраняем
            if e.usage_count > 0:
                continue  # применялась — не устаревшая

            age_days = (now - e.ts) / 86400
            if e.importance < 0.3:
                rec = "delete"
            elif e.knowledge_type in ("hypothesis", "auto"):
                rec = "deprecate"
            else:
                rec = "keep"  # review needed

            results.append(StaleEntry(
                id=e.id, title=e.title[:60],
                category=e.category,
                importance=e.importance,
                age_days=round(age_days, 1),
                usage_count=e.usage_count,
                recommendation=rec,
            ))

        return results

    def find_low_quality(self, entries: list) -> List[LowQualityEntry]:
        """
        Записи с низким качеством:
          - confidence < LOW_QUALITY_CONF
          - очень короткий контент
          - importance < LOW_QUALITY_IMP и никогда не применялись
        """
        results: List[LowQualityEntry] = []
        for e in entries:
            reasons = []
            if len(e.content) < MIN_CONTENT_LEN:
                reasons.append(f"content too short ({len(e.content)} chars)")
            if e.confidence < LOW_QUALITY_CONF:
                reasons.append(f"very low confidence ({e.confidence:.2f})")
            if e.importance < LOW_QUALITY_IMP and e.usage_count == 0:
                reasons.append(f"low importance ({e.importance:.2f}) + never used")

            if not reasons:
                continue

            if len(e.content) < MIN_CONTENT_LEN:
                rec = "delete"
            elif e.confidence < 0.15:
                rec = "delete"
            elif e.importance < 0.3:
                rec = "demote"
            else:
                rec = "mark_hypothesis"

            results.append(LowQualityEntry(
                id=e.id, title=e.title[:60],
                confidence=e.confidence, importance=e.importance,
                reason="; ".join(reasons),
                recommendation=rec,
            ))

        return results[:50]

    def find_conflicts(self, entries: list) -> List[ConflictPair]:
        """
        Эвристический поиск конфликтов:
        Две записи по схожей теме содержат противоречивые утверждения.
        Без LLM — на основе паттернов противоречий.
        """
        # Противоречивые маркеры: "всегда X" vs "никогда X", "нужно Y" vs "нельзя Y"
        _OPPOSE = [
            (r'\bвсегда\b',   r'\bникогда\b'),
            (r'\bнужно\b',    r'\bнельзя\b'),
            (r'\bможно\b',    r'\bзапрещено\b'),
            (r'\bиспользуй\b', r'\bне\s+используй\b'),
            (r'\benabled\b',  r'\bdisabled\b'),
            (r'\btrue\b',     r'\bfalse\b'),
        ]

        entry_by_id = {e.id: e for e in entries}
        title_idx: Dict[str, List[int]] = {}

        for e in entries:
            title_words = set(re.findall(r'\b\w{5,}\b', e.title.lower()))
            for w in title_words:
                title_idx.setdefault(w, []).append(e.id)

        seen: Set[Tuple[int, int]] = set()
        results: List[ConflictPair] = []

        for ids in title_idx.values():
            if len(ids) < 2:
                continue
            for i in range(len(ids)):
                for j in range(i + 1, min(i + 5, len(ids))):
                    id_a, id_b = ids[i], ids[j]
                    pair_key = (min(id_a, id_b), max(id_a, id_b))
                    if pair_key in seen:
                        continue
                    seen.add(pair_key)
                    ea = entry_by_id.get(id_a)
                    eb = entry_by_id.get(id_b)
                    if not ea or not eb:
                        continue
                    text_a = ea.content.lower()
                    text_b = eb.content.lower()
                    for pat_a, pat_b in _OPPOSE:
                        has_a_in_a = bool(re.search(pat_a, text_a))
                        has_b_in_b = bool(re.search(pat_b, text_b))
                        has_a_in_b = bool(re.search(pat_a, text_b))
                        has_b_in_a = bool(re.search(pat_b, text_a))
                        if (has_a_in_a and has_b_in_b) or (has_a_in_b and has_b_in_a):
                            rec = "keep_a" if ea.importance >= eb.importance else "keep_b"
                            results.append(ConflictPair(
                                id_a=id_a, id_b=id_b,
                                title_a=ea.title[:55], title_b=eb.title[:55],
                                signal=f"{pat_a!r} vs {pat_b!r}",
                                recommendation=rec,
                            ))
                            break

        return results[:20]

    # ══════════════════════════════════════════════════════════════════════════
    # ПРИМЕНЕНИЕ ИСПРАВЛЕНИЙ
    # ══════════════════════════════════════════════════════════════════════════

    def _apply_fixes(self, report: MaintenanceReport,
                     safe_delete: bool = False) -> List[str]:
        """Применяет безопасные исправления и возвращает список действий."""
        mem = self._mem()
        actions: List[str] = []

        # 1. Понизить importance дублей (не удаляем без safe_delete)
        for dup in report.duplicates:
            try:
                remove_id = dup.id_b if "remove_b" in dup.recommendation else dup.id_a
                keep_id   = dup.id_a if "remove_b" in dup.recommendation else dup.id_b
                if safe_delete:
                    with mem._rlock, mem._connect() as c:
                        c.execute("DELETE FROM knowledge WHERE id=?", (remove_id,))
                    actions.append(f"DELETED duplicate id={remove_id} (kept id={keep_id})")
                else:
                    # Понижаем importance и помечаем тип как дубль
                    mem.update_knowledge(remove_id, importance=0.15,
                                         knowledge_type="deprecated")
                    actions.append(
                        f"DEMOTED duplicate id={remove_id} sim={dup.similarity:.2f}"
                    )
            except Exception as e:
                report.errors.append(f"dup fix id={dup.id_b}: {e}")

        # 2. Пометить устаревшие
        for s in report.stale:
            try:
                if s.recommendation == "delete" and safe_delete:
                    with mem._rlock, mem._connect() as c:
                        c.execute("DELETE FROM knowledge WHERE id=?", (s.id,))
                    actions.append(f"DELETED stale id={s.id} age={s.age_days}d")
                elif s.recommendation in ("deprecate", "delete"):
                    mem.update_knowledge(s.id, importance=0.1,
                                         knowledge_type="deprecated")
                    actions.append(f"DEPRECATED stale id={s.id} age={s.age_days}d")
            except Exception as e:
                report.errors.append(f"stale fix id={s.id}: {e}")

        # 3. Понизить/пометить низкокачественные
        for lq in report.low_quality:
            try:
                if lq.recommendation == "delete" and safe_delete:
                    with mem._rlock, mem._connect() as c:
                        c.execute("DELETE FROM knowledge WHERE id=?", (lq.id,))
                    actions.append(f"DELETED low-quality id={lq.id}")
                elif lq.recommendation == "mark_hypothesis":
                    mem.update_knowledge(lq.id, knowledge_type="hypothesis",
                                         importance=min(lq.importance, 0.4))
                    actions.append(f"→hypothesis id={lq.id}")
                elif lq.recommendation == "demote":
                    mem.update_knowledge(lq.id, importance=max(0.1, lq.importance * 0.6))
                    actions.append(f"DEMOTED id={lq.id} importance→{lq.importance*0.6:.2f}")
            except Exception as e:
                report.errors.append(f"lq fix id={lq.id}: {e}")

        return actions

    # ══════════════════════════════════════════════════════════════════════════
    # ФОРМАТИРОВАНИЕ
    # ══════════════════════════════════════════════════════════════════════════

    def _format_report(self, report: MaintenanceReport) -> str:
        score = self._health_score(report)
        health_emoji = "🟢" if score >= 0.8 else "🟡" if score >= 0.5 else "🔴"

        lines = [
            "═══════════════════════════════════════════",
            "  ОТЧЁТ: СОСТОЯНИЕ БАЗЫ ЗНАНИЙ",
            f"  {time.strftime('%d.%m.%Y %H:%M')}",
            "═══════════════════════════════════════════",
            "",
            f"📊 Всего знаний: {report.total_knowledge}",
            f"{health_emoji} Здоровье: {score:.0%}",
        ]

        if report.backfilled:
            lines.append(f"🔧 Заполнено метаданных: {report.backfilled} записей")

        # Дубли
        if report.duplicates:
            lines += ["", f"⚠️  ДУБЛИ ({len(report.duplicates)}):"]
            for d in report.duplicates[:5]:
                lines.append(
                    f"  sim={d.similarity:.0%}  «{d.title_a[:40]}»"
                    f" ↔ «{d.title_b[:40]}»"
                )
            if len(report.duplicates) > 5:
                lines.append(f"  ... и ещё {len(report.duplicates)-5}")

        # Устаревшие
        if report.stale:
            lines += ["", f"🕰️  УСТАРЕВШИЕ ({len(report.stale)}):"]
            for s in report.stale[:5]:
                lines.append(
                    f"  [{s.recommendation}] «{s.title[:45]}»"
                    f" age={s.age_days:.0f}d imp={s.importance:.2f}"
                )

        # Низкокачественные
        if report.low_quality:
            lines += ["", f"🗑️  НИЗКОЕ КАЧЕСТВО ({len(report.low_quality)}):"]
            for lq in report.low_quality[:5]:
                lines.append(
                    f"  [{lq.recommendation}] «{lq.title[:45]}»"
                    f" conf={lq.confidence:.2f} — {lq.reason[:50]}"
                )

        # Конфликты
        if report.conflicts:
            lines += ["", f"⚡ КОНФЛИКТЫ ({len(report.conflicts)}):"]
            for c in report.conflicts[:4]:
                lines.append(
                    f"  «{c.title_a[:35]}» vs «{c.title_b[:35]}»"
                    f" → {c.recommendation}"
                )

        # Действия
        if report.actions_taken:
            lines += ["", f"✅ ВЫПОЛНЕНО ({len(report.actions_taken)}):"]
            for a in report.actions_taken[:8]:
                lines.append(f"  {a}")

        # Ошибки
        if report.errors:
            lines += ["", f"❌ ОШИБКИ ({len(report.errors)}):"]
            for e in report.errors[:3]:
                lines.append(f"  {e}")

        # Рекомендация
        if score < 0.6:
            lines += [
                "", "💡 РЕКОМЕНДАЦИИ:",
                "  Запусти «очисти память» с параметром safe_delete=True",
                "  для физического удаления подтверждённого мусора.",
            ]
        elif not any([report.duplicates, report.stale, report.low_quality, report.conflicts]):
            lines += ["", "✨ База знаний в хорошем состоянии. Проблем не найдено."]

        lines += [
            "",
            f"⏱️  Время анализа: {report.duration_s:.1f}с",
            "═══════════════════════════════════════════",
        ]
        return "\n".join(lines)

    def format_report(self, report: MaintenanceReport) -> str:
        return self._format_report(report)

    def _health_score(self, report: MaintenanceReport) -> float:
        """0..1 — общее здоровье базы знаний."""
        if report.total_knowledge == 0:
            return 1.0
        n = report.total_knowledge
        penalty = (
            len(report.duplicates)  * 0.8 +
            len(report.stale)       * 0.4 +
            len(report.low_quality) * 0.3 +
            len(report.conflicts)   * 1.5
        )
        score = max(0.0, 1.0 - penalty / max(n, 1))
        return round(score, 3)
