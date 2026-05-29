# -*- coding: utf-8 -*-
"""
training/training_journal.py — Журнал обучения системы.

Отвечает на вопросы:
  • Чему система научилась?         → get_learned_summary()
  • Что было отклонено и почему?    → get_rejected_summary()
  • Применяются ли знания на деле?  → get_application_report()
  • Есть ли незакрытые гипотезы?    → get_unverified()
  • Качество обучения со временем?  → get_quality_trend()

Каждая операция записывается через MemoryStore.log_training().
Журнал читается отсюда и форматируется в отчёты.

Использование:
    journal = TrainingJournal.get()
    journal.record_save(entry, result, cycle=3)
    journal.record_reject(entry, reason="дубликат", cycle=3)
    journal.record_apply(entry_id, query="как настроить...")
    print(journal.full_report())
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger("training.journal")


class TrainingJournal:
    """
    Singleton-журнал обучения.
    Тонкая обёртка над MemoryStore.log_training() с методами отчётности.
    """

    _instance: Optional["TrainingJournal"] = None

    @classmethod
    def get(cls) -> "TrainingJournal":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _mem(self):
        from memory.memory_store import MemoryStore
        return MemoryStore.get()

    # ── Запись событий ────────────────────────────────────────────────────────

    def record_save(self, entry, result, cycle: int = 0) -> None:
        """Знание прошло валидацию и сохранено."""
        self._mem().log_training(
            action="save",
            entry_id=entry.id,
            entry_title=entry.title,
            reason=result.reason,
            quality=result.quality_score,
            agent=entry.source or "unknown",
            cycle=cycle,
            details={
                "category":       entry.category,
                "knowledge_type": result.knowledge_type,
                "confidence":     result.confidence,
                "warnings":       result.warnings,
                "content_len":    len(entry.content),
            },
        )

    def record_reject(self, entry, reason: str, cycle: int = 0,
                      quality: float = 0.0) -> None:
        """Знание отклонено валидатором."""
        self._mem().log_training(
            action="reject",
            entry_id=getattr(entry, "id", 0),
            entry_title=getattr(entry, "title", "?"),
            reason=reason,
            quality=quality,
            agent=getattr(entry, "source", "unknown"),
            cycle=cycle,
            details={
                "category": getattr(entry, "category", ""),
                "content_preview": (getattr(entry, "content", "") or "")[:100],
            },
        )

    def record_apply(self, entry_id: int, query: str = "",
                     agent: str = "rag") -> None:
        """Знание было применено в RAG-контексте."""
        self._mem().log_training(
            action="apply",
            entry_id=entry_id,
            reason=f"RAG применил для: {query[:80]}",
            agent=agent,
            quality=1.0,
        )

    def record_update(self, entry_id: int, title: str, what: str,
                      cycle: int = 0) -> None:
        """Importance/confidence знания обновлены."""
        self._mem().log_training(
            action="update",
            entry_id=entry_id,
            entry_title=title,
            reason=what,
            cycle=cycle,
        )

    def record_cycle_start(self, cycle: int, messages_count: int) -> None:
        """Начало цикла обучения."""
        self._mem().log_training(
            action="cycle_start",
            cycle=cycle,
            reason=f"Анализ {messages_count} сообщений",
            agent="self_training",
        )

    def record_cycle_end(self, cycle: int, saved: int, rejected: int,
                         updated: int, duration_s: float) -> None:
        """Конец цикла обучения."""
        self._mem().log_training(
            action="cycle_end",
            cycle=cycle,
            reason=f"+{saved} сохранено, -{rejected} отклонено, ~{updated} обновлено",
            quality=saved / max(saved + rejected, 1),
            agent="self_training",
            details={"duration_s": round(duration_s, 1)},
        )

    # ── Отчёты ────────────────────────────────────────────────────────────────

    def full_report(self, cycles_back: int = 5) -> str:
        """
        Полный читаемый отчёт о состоянии обучения.
        Отвечает на все 8 вопросов системы качества.
        """
        mem = self._mem()
        stats = mem.training_stats()
        log_rows = mem.get_training_log(limit=500)

        lines = [
            "═══════════════════════════════════════",
            "  ОТЧЁТ О КАЧЕСТВЕ ОБУЧЕНИЯ СИСТЕМЫ",
            "═══════════════════════════════════════",
            "",
            "📊 СТАТИСТИКА ЖУРНАЛА:",
            f"  Всего событий:            {stats['total_events']}",
            f"  Сохранено знаний:         {stats['saved']}",
            f"  Отклонено:                {stats['rejected']}",
            f"  Применено в RAG:          {stats['applied_in_rag']}",
            f"  Средн. quality сохранённых: {stats['avg_quality_saved']:.2f}",
            "",
            "⚠️  РИСКИ:",
            f"  Непроверенных (importance>0.5): {stats['unverified_high_importance']}",
            f"  Знаний без применения:           {stats['knowledge_never_used']}",
        ]

        # Последние сохранения
        saved_rows = [r for r in log_rows if r["action"] == "save"][:10]
        if saved_rows:
            lines += ["", "✅ ПОСЛЕДНИЕ СОХРАНЁННЫЕ ЗНАНИЯ:"]
            for r in saved_rows:
                ts = time.strftime("%d.%m %H:%M", time.localtime(r["ts"]))
                lines.append(
                    f"  [{ts}] «{r['entry_title'][:55]}» "
                    f"q={r['quality']:.2f}"
                )

        # Последние отказы
        rejected_rows = [r for r in log_rows if r["action"] == "reject"][:8]
        if rejected_rows:
            lines += ["", "❌ ПОСЛЕДНИЕ ОТКЛОНЁННЫЕ:"]
            for r in rejected_rows:
                ts = time.strftime("%d.%m %H:%M", time.localtime(r["ts"]))
                lines.append(
                    f"  [{ts}] «{r['entry_title'][:45]}» — {r['reason'][:60]}"
                )

        # Последние применения
        apply_rows = [r for r in log_rows if r["action"] == "apply"][:5]
        if apply_rows:
            lines += ["", "🔍 ПОСЛЕДНИЕ ПРИМЕНЕНИЯ ЗНАНИЙ (RAG):"]
            for r in apply_rows:
                ts = time.strftime("%d.%m %H:%M", time.localtime(r["ts"]))
                lines.append(f"  [{ts}] entry_id={r['entry_id']} — {r['reason'][:70]}")

        # Тренд по циклам
        cycle_ends = [r for r in log_rows if r["action"] == "cycle_end"][:cycles_back]
        if cycle_ends:
            lines += ["", "📈 ПОСЛЕДНИЕ ЦИКЛЫ ОБУЧЕНИЯ:"]
            for r in reversed(cycle_ends):
                ts = time.strftime("%d.%m %H:%M", time.localtime(r["ts"]))
                lines.append(
                    f"  [{ts}] цикл #{r['cycle']} — {r['reason']} "
                    f"(q={r['quality']:.2f})"
                )

        # Диагноз: есть ли знания которые никогда не применялись
        if stats["knowledge_never_used"] > 20:
            lines += [
                "",
                "💡 РЕКОМЕНДАЦИЯ: Много знаний ни разу не применялись. "
                "Возможно стоит снизить их importance или удалить устаревшие.",
            ]

        if stats["unverified_high_importance"] > 10:
            lines += [
                "",
                "💡 РЕКОМЕНДАЦИЯ: Много высокоприоритетных непроверенных знаний. "
                "Запусти 'обучи себя' для верификации или вручную проверь через GUI.",
            ]

        lines.append("")
        lines.append("═══════════════════════════════════════")
        return "\n".join(lines)

    def get_unverified(self, importance_threshold: float = 0.6) -> List[Dict]:
        """Вернуть непроверенные знания с высокой important — требуют внимания."""
        mem = self._mem()
        entries = mem.get_knowledge(limit=200)
        return [
            {"id": e.id, "title": e.title, "category": e.category,
             "importance": e.importance, "confidence": e.confidence,
             "source": e.source}
            for e in entries
            if not e.verified and e.importance >= importance_threshold
        ]

    def get_never_applied(self) -> List[Dict]:
        """Вернуть знания которые ни разу не были применены в RAG."""
        mem = self._mem()
        entries = mem.get_knowledge(limit=500)
        return [
            {"id": e.id, "title": e.title, "importance": e.importance,
             "ts": e.ts, "category": e.category}
            for e in entries if e.usage_count == 0
        ]
