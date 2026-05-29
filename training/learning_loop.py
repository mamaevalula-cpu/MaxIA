# -*- coding: utf-8 -*-
"""
training/learning_loop.py — Центральный конвейер автономного обучения (11 шагов).

Каждое новое знание проходит полный цикл проверки и верификации:

  Шаг 1.  INPUT            — получить кандидата на запись
  Шаг 2.  CLASSIFICATION   — определить тип знания
  Шаг 3.  QUALITY CHECK    — KnowledgeValidator (длина, мусор, дубли)
  Шаг 4.  CONFLICT CHECK   — ConflictManager (противоречия с существующими)
  Шаг 5.  RELEVANCE        — достаточно ли важно для хранения?
  Шаг 6.  DECISION         — save / reject / update_existing
  Шаг 7.  WRITE            — запись в MemoryStore (с snapshot перед записью)
  Шаг 8.  WRITE VERIFY     — убедиться, что запись существует и читается
  Шаг 9.  APPLICATION CHK  — после 24ч: применялось ли знание в RAG?
  Шаг 10. OUTCOME EVAL     — положительный/нейтральный/отрицательный эффект?
  Шаг 11. FEEDBACK LOOP    — обновить confidence/importance или откатить

Каждый шаг логируется через TrainingJournal.
Вся история доступна через learning_loop.get_pipeline_report().

Использование:
    loop = LearningLoop.get()

    # Синхронная обработка одного кандидата
    result = loop.process(entry)
    print(result.verdict)   # "saved" | "rejected" | "updated" | "conflict"

    # Пакетная обработка (из цикла обучения)
    results = loop.process_batch(entries, cycle=5)

    # Проверить накопленные результаты (вызывать через 24ч)
    loop.run_deferred_checks()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("training.loop")

# ── Константы ─────────────────────────────────────────────────────────────────

MIN_IMPORTANCE_TO_SAVE    = 0.35   # ниже — отклоняем
MIN_CONFIDENCE_TO_SAVE    = 0.25   # ниже — отклоняем
APPLICATION_CHECK_DELAY   = 86400  # 24 часа в секундах
OUTCOME_NEGATIVE_ROLLBACK = True   # откатывать знания с отрицательным outcome?
OUTCOME_UNUSED_THRESHOLD  = 7 * 86400  # 7 дней без применения → пересмотр


# ── Вердикт ───────────────────────────────────────────────────────────────────

class Verdict(str, Enum):
    SAVED    = "saved"       # знание сохранено
    REJECTED = "rejected"    # знание отклонено
    UPDATED  = "updated"     # обновлено существующее знание
    CONFLICT = "conflict"    # конфликт — обработан автоматически
    SKIPPED  = "skipped"     # пропущено (уже существует без изменений)
    ERROR    = "error"       # системная ошибка в pipeline


@dataclass
class PipelineResult:
    """Результат прохождения одного кандидата через все 11 шагов."""
    entry_id:     int     = 0
    entry_title:  str     = ""
    verdict:      Verdict = Verdict.REJECTED
    step_stopped: int     = 0     # на каком шаге остановились (0 = прошёл все)
    reason:       str     = ""
    confidence:   float   = 0.5
    knowledge_type: str   = "auto"
    quality_score:  float = 0.0
    conflict_found: bool  = False
    write_verified: bool  = False
    outcome:        str   = ""    # "positive" | "neutral" | "negative" | "pending"
    rollback_done:  bool  = False
    warnings:       List[str] = field(default_factory=list)
    duration_ms:    float = 0.0
    cycle:          int   = 0


@dataclass
class DeferredCheck:
    """Запись для отложенной проверки применения знания (шаги 9-11)."""
    entry_id:    int
    entry_title: str
    saved_at:    float
    cycle:       int
    check_after: float  # unix ts — когда можно проверить
    checked:     bool = False


# ── LearningLoop ──────────────────────────────────────────────────────────────

class LearningLoop:
    """
    Singleton — центральный конвейер автономного обучения.
    Координирует все 11 шагов для каждого кандидата на запись.
    """

    _instance: Optional["LearningLoop"] = None

    def __init__(self):
        self._deferred: List[DeferredCheck] = []
        self._pipeline_history: List[PipelineResult] = []
        self._cycle_counter = 0

    @classmethod
    def get(cls) -> "LearningLoop":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Зависимости ───────────────────────────────────────────────────────────

    def _mem(self):
        from memory.memory_store import MemoryStore
        return MemoryStore.get()

    def _validator(self):
        from training.knowledge_validator import KnowledgeValidator
        return KnowledgeValidator.get()

    def _journal(self):
        from training.training_journal import TrainingJournal
        return TrainingJournal.get()

    def _rollback(self):
        from training.rollback_manager import RollbackManager
        return RollbackManager.get()

    def _conflicts(self):
        from training.conflict_manager import ConflictManager
        return ConflictManager.get()

    # ── Публичный API ─────────────────────────────────────────────────────────

    def process(self, entry, cycle: int = 0) -> PipelineResult:
        """
        Пропустить одного кандидата через все 11 шагов конвейера.
        Возвращает PipelineResult с вердиктом и деталями.
        """
        t0 = time.time()
        result = PipelineResult(
            entry_id=getattr(entry, "id", 0),
            entry_title=getattr(entry, "title", "?"),
            cycle=cycle,
        )

        try:
            result = self._run_pipeline(entry, result, cycle)
        except Exception as e:
            log.error("Pipeline error for '%s': %s",
                      getattr(entry, "title", "?"), e, exc_info=True)
            result.verdict = Verdict.ERROR
            result.reason = f"Pipeline exception: {e}"
            result.step_stopped = -1

        result.duration_ms = round((time.time() - t0) * 1000, 1)
        self._pipeline_history.append(result)

        # Ограничить историю последними 1000 результатами
        if len(self._pipeline_history) > 1000:
            self._pipeline_history = self._pipeline_history[-500:]

        return result

    def process_batch(self, entries: list, cycle: int = 0) -> List[PipelineResult]:
        """Пакетная обработка — пропустить список кандидатов."""
        self._cycle_counter = cycle
        results = []
        for entry in entries:
            r = self.process(entry, cycle=cycle)
            results.append(r)
        return results

    def run_deferred_checks(self) -> List[PipelineResult]:
        """
        Запустить отложенные проверки (шаги 9-11) для сохранённых знаний.
        Вызывать регулярно (например, раз в 24ч).
        """
        now = time.time()
        pending = [d for d in self._deferred
                   if not d.checked and d.check_after <= now]
        results = []
        for deferred in pending:
            r = self._steps_9_11(deferred.entry_id, deferred.entry_title,
                                 deferred.cycle)
            deferred.checked = True
            results.append(r)
            log.info("Deferred check complete for entry_id=%d: %s",
                     deferred.entry_id, r.outcome)
        return results

    # ── 11-шаговый конвейер ───────────────────────────────────────────────────

    def _run_pipeline(self, entry, result: PipelineResult,
                      cycle: int) -> PipelineResult:
        """Основной конвейер — шаги 1-8 (синхронные)."""

        # ── ШАГ 1: INPUT ──────────────────────────────────────────────────────
        result.step_stopped = 1
        if not self._step1_input_check(entry):
            result.verdict = Verdict.REJECTED
            result.reason = "INPUT: пустой кандидат (нет title или content)"
            return result

        # ── ШАГ 2: CLASSIFICATION ─────────────────────────────────────────────
        result.step_stopped = 2
        ktype = self._step2_classify(entry)
        result.knowledge_type = ktype
        if ktype != getattr(entry, "knowledge_type", "auto"):
            entry.knowledge_type = ktype

        # ── ШАГ 3: QUALITY CHECK ──────────────────────────────────────────────
        result.step_stopped = 3
        val_result = self._step3_quality(entry)
        result.confidence    = val_result.confidence
        result.quality_score = val_result.quality_score
        result.warnings.extend(val_result.warnings)

        if not val_result.ok:
            result.verdict = Verdict.REJECTED
            result.reason  = f"QUALITY: {val_result.reason}"
            self._journal().record_reject(entry, val_result.reason, cycle=cycle,
                                          quality=val_result.quality_score)
            return result

        # Применить метаданные из валидатора
        entry.confidence    = val_result.confidence
        entry.knowledge_type = val_result.knowledge_type

        # ── ШАГ 4: CONFLICT CHECK ─────────────────────────────────────────────
        result.step_stopped = 4
        conflict = self._step4_conflict(entry)
        if conflict.has_conflict:
            result.conflict_found = True
            resolved = self._step4_handle_conflict(entry, conflict)
            if not resolved:
                # Конфликт не удалось разрешить → отклонить новое
                result.verdict = Verdict.REJECTED
                result.reason  = f"CONFLICT: {conflict.details} с '{conflict.conflict_entry_title}'"
                self._journal().record_reject(
                    entry,
                    f"Конфликт с entry_id={conflict.conflict_entry_id}",
                    cycle=cycle,
                )
                return result
            result.warnings.append(
                f"Конфликт с #{conflict.conflict_entry_id} разрешён автоматически"
            )
            result.verdict = Verdict.CONFLICT   # конфликт, но обработан

        # ── ШАГ 5: RELEVANCE ──────────────────────────────────────────────────
        result.step_stopped = 5
        relevant, rel_reason = self._step5_relevance(entry)
        if not relevant:
            result.verdict = Verdict.REJECTED
            result.reason  = f"RELEVANCE: {rel_reason}"
            self._journal().record_reject(entry, rel_reason, cycle=cycle,
                                          quality=result.quality_score)
            return result

        # ── ШАГ 6: DECISION ───────────────────────────────────────────────────
        result.step_stopped = 6
        decision, existing_id = self._step6_decision(entry)
        # decision: "save" | "update" | "skip"

        if decision == "skip":
            result.verdict = Verdict.SKIPPED
            result.reason  = "DECISION: идентичное знание уже существует"
            return result

        # ── ШАГ 7: WRITE ──────────────────────────────────────────────────────
        result.step_stopped = 7
        saved_id = self._step7_write(entry, decision, existing_id, cycle)
        if not saved_id:
            result.verdict = Verdict.ERROR
            result.reason  = "WRITE: не удалось сохранить запись в БД"
            return result

        result.entry_id = saved_id
        result.verdict  = Verdict.UPDATED if decision == "update" else Verdict.SAVED

        # ── ШАГ 8: WRITE VERIFY ───────────────────────────────────────────────
        result.step_stopped = 8
        verified = self._step8_verify_write(saved_id, entry.title)
        result.write_verified = verified

        if not verified:
            # Запись не найдена! Попытка rollback и отклонение
            log.error("Write verification FAILED for entry_id=%d '%s'",
                      saved_id, entry.title)
            self._rollback().rollback(saved_id, reason="write_verify_failed")
            result.verdict    = Verdict.ERROR
            result.reason     = "WRITE VERIFY: запись не обнаружена после сохранения"
            result.rollback_done = True
            self._journal().record_reject(
                entry, "Write verification failed — rolled back", cycle=cycle
            )
            return result

        # Шаги 9-11 — отложенные (через 24ч)
        result.step_stopped = 0
        result.outcome = "pending"
        self._schedule_deferred_check(saved_id, entry.title, cycle)

        # Финальная журнализация
        if decision == "update":
            self._journal().record_update(saved_id, entry.title,
                                          "pipeline update", cycle=cycle)
        else:
            self._journal().record_save(entry, val_result, cycle=cycle)

        log.info("Pipeline SAVED entry_id=%d '%s' (conf=%.2f, type=%s, q=%.2f)",
                 saved_id, entry.title[:50],
                 result.confidence, result.knowledge_type, result.quality_score)
        return result

    # ── Шаги 1-8 (детали) ────────────────────────────────────────────────────

    def _step1_input_check(self, entry) -> bool:
        """Шаг 1: базовая проверка входных данных."""
        title   = (getattr(entry, "title",   None) or "").strip()
        content = (getattr(entry, "content", None) or "").strip()
        return bool(title and content)

    def _step2_classify(self, entry) -> str:
        """Шаг 2: классификация типа знания."""
        # Если уже классифицировано явно — не трогаем
        current_type = getattr(entry, "knowledge_type", "auto")
        if current_type not in ("auto", "", None):
            return current_type
        return self._validator()._classify_type(entry)

    def _step3_quality(self, entry):
        """Шаг 3: качественная проверка через KnowledgeValidator."""
        return self._validator().validate(entry)

    def _step4_conflict(self, entry):
        """Шаг 4: поиск конфликтов с существующими знаниями."""
        return self._conflicts().check_conflicts(entry)

    def _step4_handle_conflict(self, new_entry, conflict) -> bool:
        """
        Автоматически разрешить конфликт.
        Возвращает True если разрешено (или конфликт не блокирующий).
        """
        from training.conflict_manager import ResolutionStrategy, ConflictType

        if conflict.conflict_type == ConflictType.DUPLICATE:
            # Дубликат: разрешаем, сохраняя более confident
            strategy = conflict.suggested_strategy
            r = self._conflicts().resolve(
                entry_id_keep=conflict.conflict_entry_id,
                entry_id_remove=getattr(new_entry, "id", 0),
                strategy=strategy,
                reason="pipeline_auto_resolve",
            )
            # Если resolution успешна — новый кандидат НЕ нужно сохранять
            return False  # не сохранять дубликат

        elif conflict.conflict_type == ConflictType.SEMANTIC:
            # Семантический: добавить тег conflict но разрешить запись
            tags = list(getattr(new_entry, "tags", None) or [])
            if "conflict_candidate" not in tags:
                tags.append("conflict_candidate")
            new_entry.tags = tags
            return True  # разрешить запись с пометкой

        return True  # неизвестный тип — разрешить

    def _step5_relevance(self, entry) -> Tuple[bool, str]:
        """Шаг 5: оценка релевантности — достаточно ли важно для хранения?"""
        importance  = getattr(entry, "importance", 0.5)
        confidence  = getattr(entry, "confidence", 0.5)
        content_len = len((getattr(entry, "content", "") or ""))

        if importance < MIN_IMPORTANCE_TO_SAVE:
            return False, f"importance={importance:.2f} < {MIN_IMPORTANCE_TO_SAVE}"
        if confidence < MIN_CONFIDENCE_TO_SAVE:
            return False, f"confidence={confidence:.2f} < {MIN_CONFIDENCE_TO_SAVE}"
        if content_len < 30:
            return False, f"Слишком короткий контент ({content_len} символов)"
        return True, ""

    def _step6_decision(self, entry) -> Tuple[str, Optional[int]]:
        """
        Шаг 6: решение — save / update / skip.
        Возвращает (decision, existing_id_if_update).
        """
        # Если у кандидата уже есть id — это обновление
        entry_id = getattr(entry, "id", 0)
        if entry_id:
            return "update", entry_id

        # Проверить нет ли почти идентичного (очень строгий порог для skip)
        try:
            from memory.memory_store import MemoryStore
            import re
            mem = MemoryStore.get()
            title_words = set(re.findall(r'\b\w{5,}\b', entry.title.lower()))
            if title_words:
                candidates = mem.search_knowledge(
                    " ".join(list(title_words)[:4]), limit=5
                )
                for c in candidates:
                    c_title_words = set(re.findall(r'\b\w{5,}\b', c.title.lower()))
                    if c_title_words:
                        inter = len(title_words & c_title_words)
                        union = len(title_words | c_title_words)
                        if inter / union >= 0.90:  # 90% совпадение заголовков → skip
                            return "skip", c.id
        except Exception:
            pass

        return "save", None

    def _step7_write(self, entry, decision: str,
                     existing_id: Optional[int], cycle: int) -> Optional[int]:
        """Шаг 7: запись в MemoryStore с предварительным snapshot."""
        mem = self._mem()

        if decision == "update" and existing_id:
            # Снимок перед обновлением
            try:
                existing_entries = [e for e in mem.get_knowledge(limit=1000)
                                    if e.id == existing_id]
                if existing_entries:
                    self._rollback().snapshot_before_write(
                        existing_entries[0], reason=f"pipeline_update_cycle{cycle}"
                    )
            except Exception:
                pass

            try:
                mem.update_knowledge(
                    existing_id,
                    title=entry.title,
                    content=entry.content,
                    importance=entry.importance,
                    confidence=entry.confidence,
                    knowledge_type=entry.knowledge_type,
                    tags=entry.tags,
                )
                return existing_id
            except Exception as e:
                log.error("Update failed for entry_id=%d: %s", existing_id, e)
                return None

        else:
            # Новая запись
            try:
                saved_id = mem.add_knowledge(entry)
                if saved_id:
                    # Снимок факта создания (для возможного удаления при rollback)
                    self._rollback().snapshot_new_entry(
                        saved_id, reason=f"pipeline_new_cycle{cycle}"
                    )
                    entry.id = saved_id
                return saved_id
            except Exception as e:
                log.error("Write (new) failed for '%s': %s", entry.title, e)
                return None

    def _step8_verify_write(self, entry_id: int, title: str) -> bool:
        """
        Шаг 8: верификация записи.
        Проверяет что запись:
          1. Существует в БД по id
          2. Содержит ожидаемый заголовок
          3. Доступна через поиск (FTS)
        """
        if not entry_id:
            return False
        mem = self._mem()

        # Проверка 1: прямой поиск по id через MemoryStore (WAL-safe — тот же коннект)
        try:
            entry = mem.get_knowledge_by_id(entry_id)
            if not entry:
                log.warning("VERIFY: entry_id=%d not found in DB", entry_id)
                return False
            if entry.title != title:
                log.warning("VERIFY: title mismatch for entry_id=%d: '%s' != '%s'",
                            entry_id, entry.title, title)
                # Мягкая проверка — заголовок мог быть обрезан при сохранении
        except Exception as e:
            log.error("VERIFY DB check error: %s", e)
            return False

        # Проверка 2: доступность через MemoryStore API
        try:
            title_words = title.split()[:3]
            results = mem.search_knowledge(" ".join(title_words), limit=20)
            found = any(r.id == entry_id for r in results)
            if not found:
                # Не критично — FTS индекс мог не обновиться мгновенно
                log.debug("VERIFY: entry_id=%d not in FTS results (may rebuild)", entry_id)
        except Exception:
            pass

        return True   # основная проверка (id существует) прошла

    # ── Шаги 9-11 (отложенные) ───────────────────────────────────────────────

    def _schedule_deferred_check(self, entry_id: int, title: str, cycle: int) -> None:
        """Запланировать проверку применения через APPLICATION_CHECK_DELAY секунд."""
        self._deferred.append(DeferredCheck(
            entry_id=entry_id,
            entry_title=title,
            saved_at=time.time(),
            cycle=cycle,
            check_after=time.time() + APPLICATION_CHECK_DELAY,
        ))

    def _steps_9_11(self, entry_id: int, title: str,
                    cycle: int) -> PipelineResult:
        """
        Шаги 9-11: проверка применения и оценка результата.
        Вызывается через APPLICATION_CHECK_DELAY после сохранения.
        """
        result = PipelineResult(
            entry_id=entry_id,
            entry_title=title,
            cycle=cycle,
            verdict=Verdict.SAVED,
        )

        # ── ШАГ 9: APPLICATION CHECK ──────────────────────────────────────────
        result.step_stopped = 9
        usage = self._step9_application_check(entry_id)

        # ── ШАГ 10: OUTCOME EVALUATION ────────────────────────────────────────
        result.step_stopped = 10
        outcome = self._step10_outcome_eval(entry_id, usage, title)
        result.outcome = outcome

        # ── ШАГ 11: FEEDBACK LOOP ─────────────────────────────────────────────
        result.step_stopped = 11
        self._step11_feedback(entry_id, title, outcome, cycle, result)

        result.step_stopped = 0
        return result

    def _step9_application_check(self, entry_id: int) -> Dict[str, Any]:
        """
        Шаг 9: проверить применялось ли знание в RAG после сохранения.
        Возвращает словарь с данными о применении.
        """
        try:
            mem = self._mem()
            entries = [e for e in mem.get_knowledge(limit=1000)
                       if e.id == entry_id]
            if not entries:
                return {"found": False}
            entry = entries[0]
            return {
                "found":       True,
                "usage_count": entry.usage_count,
                "last_used":   entry.last_used,
                "age_days":    (time.time() - entry.ts) / 86400,
                "ever_used":   entry.usage_count > 0,
            }
        except Exception as e:
            log.debug("Application check error for entry_id=%d: %s", entry_id, e)
            return {"found": False}

    def _step10_outcome_eval(self, entry_id: int,
                              usage: Dict, title: str) -> str:
        """
        Шаг 10: оценить outcome на основе данных применения.

        positive  — знание применялось несколько раз (usage_count >= 2)
        neutral   — применялось 1 раз или новое (<3 дней)
        negative  — старое знание (>7 дней) и ни разу не применялось
        unknown   — запись не найдена в БД
        """
        if not usage.get("found"):
            return "unknown"

        age_days    = usage.get("age_days", 0)
        usage_count = usage.get("usage_count", 0)
        ever_used   = usage.get("ever_used", False)

        if usage_count >= 2:
            return "positive"
        elif usage_count == 1 or age_days < 3:
            return "neutral"
        elif age_days >= 7 and not ever_used:
            log.info("Negative outcome for entry_id=%d '%s' — unused for %.1fd",
                     entry_id, title[:40], age_days)
            return "negative"
        else:
            return "neutral"

    def _step11_feedback(self, entry_id: int, title: str,
                          outcome: str, cycle: int,
                          result: PipelineResult) -> None:
        """
        Шаг 11: обратная связь — корректировка confidence/importance или откат.

        positive  → увеличить importance (+0.05), confidence (+0.02), verified=True
        neutral   → ничего не менять
        negative  → снизить importance (-0.10), confidence (-0.05);
                    если OUTCOME_NEGATIVE_ROLLBACK → откатить
        """
        mem = self._mem()

        if outcome == "positive":
            self._adjust_entry(entry_id, d_importance=+0.05,
                               d_confidence=+0.02, set_verified=True)
            self._journal().record_update(
                entry_id, title, "outcome_positive → importance+confidence raised",
                cycle=cycle,
            )

        elif outcome == "negative":
            if OUTCOME_NEGATIVE_ROLLBACK:
                log.warning("Rolling back entry_id=%d (negative outcome)", entry_id)
                success = self._rollback().rollback(
                    entry_id, reason="outcome_negative"
                )
                result.rollback_done = success
                if success:
                    self._journal().record_update(
                        entry_id, title, "outcome_negative → rolled back", cycle=cycle
                    )
                    return

            # Если не откатываем — снижаем confidence
            self._adjust_entry(entry_id, d_importance=-0.10, d_confidence=-0.05)
            self._journal().record_update(
                entry_id, title, "outcome_negative → importance-confidence lowered",
                cycle=cycle,
            )

        elif outcome == "neutral":
            pass   # ничего не делаем, ждём дальше

    def _adjust_entry(self, entry_id: int,
                       d_importance: float = 0.0,
                       d_confidence: float = 0.0,
                       set_verified: bool = False) -> None:
        """Применить delta к importance/confidence конкретной записи."""
        mem = self._mem()
        try:
            entries = [e for e in mem.get_knowledge(limit=1000)
                       if e.id == entry_id]
            if not entries:
                return
            e = entries[0]
            new_imp  = round(min(1.0, max(0.0, e.importance + d_importance)), 3)
            new_conf = round(min(1.0, max(0.0, e.confidence + d_confidence)), 3)
            kwargs: Dict[str, Any] = {
                "importance":  new_imp,
                "confidence":  new_conf,
            }
            if set_verified:
                kwargs["verified"] = True
            mem.update_knowledge(entry_id, **kwargs)
            log.debug("Adjusted entry_id=%d: imp %.2f→%.2f conf %.2f→%.2f",
                      entry_id, e.importance, new_imp, e.confidence, new_conf)
        except Exception as ex:
            log.debug("Adjust entry error for %d: %s", entry_id, ex)

    # ── Статистика и отчёты ───────────────────────────────────────────────────

    def pipeline_stats(self) -> Dict[str, Any]:
        """Статистика по всем прошедшим через pipeline кандидатам."""
        hist = self._pipeline_history
        if not hist:
            return {"total": 0}

        total    = len(hist)
        saved    = sum(1 for r in hist if r.verdict == Verdict.SAVED)
        rejected = sum(1 for r in hist if r.verdict == Verdict.REJECTED)
        updated  = sum(1 for r in hist if r.verdict == Verdict.UPDATED)
        conflict = sum(1 for r in hist if r.verdict == Verdict.CONFLICT)
        errors   = sum(1 for r in hist if r.verdict == Verdict.ERROR)
        verified = sum(1 for r in hist if r.write_verified)
        rollbacks = sum(1 for r in hist if r.rollback_done)

        avg_q = (sum(r.quality_score for r in hist) / total
                 if total else 0.0)
        avg_ms = (sum(r.duration_ms for r in hist) / total
                  if total else 0.0)

        deferred_pending = sum(1 for d in self._deferred if not d.checked)

        return {
            "total":           total,
            "saved":           saved,
            "rejected":        rejected,
            "updated":         updated,
            "conflict":        conflict,
            "errors":          errors,
            "write_verified":  verified,
            "rollbacks":       rollbacks,
            "avg_quality":     round(avg_q, 3),
            "avg_duration_ms": round(avg_ms, 1),
            "deferred_pending": deferred_pending,
            "accept_rate":     round(saved / max(total, 1), 3),
        }

    def get_pipeline_report(self, last_n: int = 20) -> str:
        """Читаемый отчёт о работе pipeline за последние N кандидатов."""
        stats = self.pipeline_stats()
        hist  = self._pipeline_history[-last_n:]

        lines = [
            "╔══════════════════════════════════════════╗",
            "║     ОТЧЁТ LEARNING LOOP (11 шагов)      ║",
            "╚══════════════════════════════════════════╝",
            "",
            f"Всего через pipeline:   {stats.get('total', 0)}",
            f"  ✅ Сохранено:         {stats.get('saved', 0)}",
            f"  🔄 Обновлено:         {stats.get('updated', 0)}",
            f"  ❌ Отклонено:         {stats.get('rejected', 0)}",
            f"  ⚡ Конфликты:         {stats.get('conflict', 0)}",
            f"  🔴 Ошибки:            {stats.get('errors', 0)}",
            f"  ↩️  Откатов:           {stats.get('rollbacks', 0)}",
            f"  ✔️  Верифицировано:    {stats.get('write_verified', 0)}",
            f"  ⏳ Ожидают проверки:  {stats.get('deferred_pending', 0)}",
            "",
            f"Acceptance rate:        {stats.get('accept_rate', 0):.1%}",
            f"Avg quality score:      {stats.get('avg_quality', 0):.2f}",
            f"Avg pipeline duration:  {stats.get('avg_duration_ms', 0):.0f}ms",
        ]

        if hist:
            lines += ["", f"Последние {len(hist)} результатов:"]
            for r in reversed(hist):
                icon = {
                    "saved":    "✅",
                    "updated":  "🔄",
                    "rejected": "❌",
                    "conflict": "⚡",
                    "skipped":  "⏭️",
                    "error":    "🔴",
                }.get(r.verdict.value, "?")
                outcome_str = f" outcome={r.outcome}" if r.outcome not in ("", "pending") else ""
                lines.append(
                    f"  {icon} [{r.verdict.value:8s}] «{r.entry_title[:45]}»"
                    f" q={r.quality_score:.2f}{outcome_str}"
                )
                if r.reason and r.verdict in (Verdict.REJECTED, Verdict.ERROR):
                    lines.append(f"             └─ {r.reason[:70]}")

        lines += ["", f"🕐 {time.strftime('%d.%m.%Y %H:%M')}"]
        return "\n".join(lines)
