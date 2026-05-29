# -*- coding: utf-8 -*-
"""
memory/memory_layers.py — Слоёный доступ к памяти.

Организует единое хранилище (MemoryStore) по логическим слоям:

  short_term      — последние 50 сообщений активной сессии
  long_term       — KnowledgeEntry с importance >= 0.7 и verified=True
  decision_log    — записи с category="decision"
  training_log    — training_log таблица
  error_log       — agent_logs с success=False + knowledge category="error"
  project_memory  — знания привязанные к проектам
  preference      — category="preference" | knowledge_type="preference"
  verified        — verified=True знания
  hypothesis      — knowledge_type="hypothesis"
  deprecated      — knowledge_type="deprecated"
  conflict_log    — entries помеченные тегом "conflict"

Использование:
    layers = MemoryLayers.get()
    recent = layers.short_term()
    facts  = layers.verified_knowledge()
    hypo   = layers.hypotheses()
    report = layers.layer_summary()
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("memory.layers")


class MemoryLayers:
    """
    Singleton — организует MemoryStore по слоям.
    Не создаёт новых таблиц, работает поверх существующего хранилища.
    """

    _instance: Optional["MemoryLayers"] = None

    @classmethod
    def get(cls) -> "MemoryLayers":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _mem(self):
        from memory.memory_store import MemoryStore
        return MemoryStore.get()

    # ── Слои ──────────────────────────────────────────────────────────────────

    def short_term(self, session_id: str = "", limit: int = 50) -> list:
        """Краткосрочная память — последние сообщения текущей сессии."""
        return self._mem().get_messages(session_id=session_id, limit=limit)

    def long_term(self, limit: int = 100) -> list:
        """
        Долговременная память — высокоценные подтверждённые знания.
        importance >= 0.7 ИЛИ verified=True.
        """
        mem = self._mem()
        entries = mem.get_knowledge(limit=500)
        return [
            e for e in entries
            if e.importance >= 0.7 or e.verified
        ][:limit]

    def decision_log(self, limit: int = 50) -> list:
        """Лог решений — знания категории decision."""
        return self._mem().get_knowledge(category="decision", limit=limit)

    def training_log(self, limit: int = 100, action: str = "") -> List[Dict]:
        """Журнал обучения."""
        return self._mem().get_training_log(limit=limit, action=action)

    def error_log(self, limit: int = 50) -> Dict[str, list]:
        """
        Лог ошибок — из двух источников:
          • agent_logs (success=False)
          • knowledge с category="error"
        """
        mem = self._mem()
        return {
            "agent_errors": mem.get_recent_errors(limit=limit),
            "error_knowledge": mem.get_knowledge(category="error", limit=limit),
        }

    def project_memory(self, project_name: str = "") -> Dict[str, Any]:
        """Память по проектам."""
        mem = self._mem()
        if project_name:
            projects = [p for p in mem.get_projects() if p["name"] == project_name]
        else:
            projects = mem.get_projects()
        return {"projects": projects}

    def preferences(self, limit: int = 30) -> list:
        """Предпочтения пользователя."""
        mem = self._mem()
        entries = mem.get_knowledge(limit=500)
        return [
            e for e in entries
            if e.category == "preference" or e.knowledge_type == "preference"
        ][:limit]

    def verified_knowledge(self, limit: int = 100) -> list:
        """Проверенные знания (verified=True)."""
        entries = self._mem().get_knowledge(limit=500)
        return [e for e in entries if e.verified][:limit]

    def hypotheses(self, limit: int = 50) -> list:
        """Гипотезы — непроверенные идеи."""
        entries = self._mem().get_knowledge(limit=500)
        return [
            e for e in entries
            if e.knowledge_type == "hypothesis" or e.category == "hypothesis"
        ][:limit]

    def deprecated(self, limit: int = 50) -> list:
        """Устаревшие / помеченные на удаление."""
        entries = self._mem().get_knowledge(limit=500)
        return [e for e in entries if e.knowledge_type == "deprecated"][:limit]

    def conflict_log(self, limit: int = 30) -> list:
        """Знания с тегом conflict."""
        entries = self._mem().get_knowledge(limit=500)
        return [
            e for e in entries
            if "conflict" in (e.tags or [])
        ][:limit]

    # ── Сводка ────────────────────────────────────────────────────────────────

    def layer_summary(self) -> str:
        """Текстовая сводка по всем слоям памяти."""
        mem = self._mem()
        stats = mem.stats()
        entries = mem.get_knowledge(limit=500)

        total     = len(entries)
        verified  = sum(1 for e in entries if e.verified)
        hypo      = sum(1 for e in entries if e.knowledge_type == "hypothesis")
        depr      = sum(1 for e in entries if e.knowledge_type == "deprecated")
        used      = sum(1 for e in entries if e.usage_count > 0)
        high_imp  = sum(1 for e in entries if e.importance >= 0.7)
        errors_k  = sum(1 for e in entries if e.category == "error")
        solutions = sum(1 for e in entries if e.category == "solution")
        strategy  = sum(1 for e in entries if e.category in ("strategy", "architecture"))
        pref      = sum(1 for e in entries
                        if e.knowledge_type == "preference" or e.category == "preference")

        training_stats = mem.training_stats()

        lines = [
            "╔══════════════════════════════════════════╗",
            "║         КАРТА ПАМЯТИ СИСТЕМЫ             ║",
            "╚══════════════════════════════════════════╝",
            "",
            f"📬 Краткосрочная (сообщения):  {stats['messages']}",
            f"🧠 Долговременная (knowledge): {total}",
            "",
            "  По слоям:",
            f"  ✅ verified_knowledge:     {verified}",
            f"  💡 hypotheses:             {hypo}",
            f"  🗄️  deprecated:             {depr}",
            f"  🔧 solutions/error_fixes:  {solutions}",
            f"  ⚙️  strategy/architecture:  {strategy}",
            f"  ❌ error_knowledge:        {errors_k}",
            f"  ⭐ preferences:            {pref}",
            f"  🔥 high_importance (≥0.7): {high_imp}",
            f"  📈 ever_applied_in_rag:    {used}",
            "",
            "📋 Обучение (training_log):",
            f"  Сохранено:    {training_stats['saved']}",
            f"  Отклонено:    {training_stats['rejected']}",
            f"  Применено:    {training_stats['applied_in_rag']}",
            f"  Avg quality:  {training_stats['avg_quality_saved']:.2f}",
            "",
            f"🔄 Проекты: {stats['projects']}",
            f"📝 Задачи:  {stats['tasks_total']} (ожидают: {stats['tasks_pending']})",
        ]

        # Предупреждения
        warnings = []
        if verified == 0 and total > 20:
            warnings.append("⚠️  Нет ни одного verified знания — запусти 'отчёт обучения'")
        if depr > 20:
            warnings.append(f"⚠️  {depr} устаревших записей — запусти 'очисти память'")
        unused_pct = (total - used) / max(total, 1)
        if unused_pct > 0.9 and total > 30:
            warnings.append(
                f"⚠️  {unused_pct:.0%} знаний ни разу не применялись в RAG"
            )

        if warnings:
            lines += ["", "⚠️  ВНИМАНИЕ:"] + [f"  {w}" for w in warnings]

        lines += ["", f"🕐 {time.strftime('%d.%m.%Y %H:%M')}"]
        return "\n".join(lines)
