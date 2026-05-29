# -*- coding: utf-8 -*-
"""
agents/self_training_agent.py — Агент самообучения ИИ.

Этот агент делает систему умнее со временем:

1. АНАЛИЗ КАЧЕСТВА — оценивает прошлые ответы, выявляет слабые места
2. ГЕНЕРАЦИЯ ЗНАНИЙ — создаёт новые KnowledgeEntry из успешных паттернов
3. СИНТЕТИЧЕСКИЕ ДАННЫЕ — генерирует Q&A пары по важным темам
4. ОПТИМИЗАЦИЯ ПАМЯТИ — пересчитывает importance score знаний
5. ОБНОВЛЕНИЕ ПРОМТА — предлагает улучшения системного промта
6. ОТЧЁТ ОБ ОБУЧЕНИИ — показывает что было улучшено

Запускается:
  • Автоматически каждый час в фоне
  • По команде пользователя: «обучи себя», «самообучение», «улучши себя»
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMProvider, LLMRequest
from memory.memory_store import KnowledgeEntry
from training.knowledge_validator import KnowledgeValidator
from training.training_journal import TrainingJournal
from training.learning_loop import LearningLoop

log = logging.getLogger("agents.self_training")

# Интервал фонового обучения (секунды)
TRAINING_INTERVAL = 3600  # 1 час

# Приоритетные темы для самообучения (elite programming + payments)
PRIORITY_TRAINING_TOPICS = [
    # Программирование
    "MaxAI rule: always read file before editing use edit_file not write_file check syntax after changes",
    "MaxAI routing: dashboard=dashboard/static/index.html agents=agents/ brain=brain/orchestrator.py",
    "MaxAI structure: 15 capabilities 7 patterns catalog data/agent_catalog.json manifest data/company_manifest.json",
    "MaxAI ai: claude_dev_agent has real tool use and reads files correctly use it for complex code tasks",
    "Python asyncio advanced patterns",
    "FastAPI production best practices",
    "PostgreSQL performance optimization",
    "Redis caching strategies",
    "Docker Kubernetes deployment",
    "React Next.js SSR patterns",
    "TypeScript advanced types",
    "Rust ownership and borrowing",
    "System design scalability",
    "Clean Architecture DDD",
    # Платежи
    "Stripe webhooks idempotency",
    "PayPal REST API integration",
    "Crypto USDT TRC20 payments",
    "Binance Pay API",
    "Open Banking PSD2 Plaid",
    "PCI DSS SAQ A compliance",
    "3D Secure 2 implementation",
    "Stripe Connect marketplace",
    # Фриланс
    "Upwork proposal writing",
    "Freelance project estimation",
    "Remote work pricing strategy",
    # Алгоритмы
    "Dynamic programming patterns",
    "Graph algorithms BFS DFS",
    "Distributed systems consensus",
]


@dataclass
class TrainingReport:
    analyzed: int = 0       # сколько разговоров проанализировано
    learned: int = 0         # новых knowledge entries
    updated: int = 0         # обновлённых importance scores
    weaknesses: List[str] = None
    improvements: List[str] = None

    def __post_init__(self) -> None:
        if self.weaknesses is None:
            self.weaknesses = []
        if self.improvements is None:
            self.improvements = []


class SelfTrainingAgent(BaseAgent):
    """
    Агент непрерывного самообучения.
    Анализирует взаимодействия, генерирует знания, улучшает систему.
    """

    def __init__(self) -> None:
        super().__init__("self_training")
        self._last_training = 0.0
        self._training_count = 0
        self._last_maintenance = 0.0    # последний запуск cleaner
        self._last_deferred_check = 0.0 # последняя проверка deferred (шаги 9-11)
        self._bg_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="self_training",
            description=(
                "Обучает ИИ на основе прошлых взаимодействий. "
                "Анализирует качество ответов, генерирует знания, улучшает память."
            ),
            capabilities=[
                "analyze_conversations", "generate_knowledge",
                "synthetic_qa", "optimize_memory",
                "suggest_improvements", "training_report",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(обучи|научи|улучши|прокачай|натренируй)\s+(себя|систему|ии|модель)",
            r"(самообучение|self.?train|auto.?learn)",
            r"(анализ.*разговоров|качество ответов|слабые места)",
            r"(generate.*knowledge|synthetic.*data|training.*report)",
            r"(отчёт.*обучени|журнал.*обучени|training.*journal|что.*выучил|чему.*научил)",
            r"(наведи порядок|очисти память|cleanup|cleaner|дубли|устаревш|карта памяти|слои памяти)",
            r"(learning.?loop|pipeline.*отчёт|отчёт.*pipeline|конвейер.*обучени|шаги.*обучени)",
            r"(откат.*знани|rollback.*знани|конфликт.*знани|conflict.*знани)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        """Запустить обучение, очистку или показать отчёты."""
        self._set_status(AgentStatus.RUNNING)
        try:
            tl = text.lower()

            # Карта памяти / слои
            if re.search(r"(карта памяти|слои памяти|memory.*layer|layer.*memory)", tl):
                from memory.memory_layers import MemoryLayers
                return MemoryLayers.get().layer_summary()

            # Очистка / cleaner
            if re.search(r"(наведи порядок|очисти память|cleanup|cleaner|дубли|устаревш)", tl):
                safe = "удали" in tl or "safe_delete" in tl
                from cleaner.knowledge_cleaner import KnowledgeCleaner
                cleaner = KnowledgeCleaner.get()
                report = cleaner.run_maintenance(safe_delete=safe)
                return cleaner.format_report(report)

            # Только отчёт — без нового цикла
            if re.search(r"(отчёт|журнал|что.*выучил|чему.*научил|report)", tl):
                return self._journal.full_report()

            # Отчёт learning loop (pipeline статистика)
            if re.search(r"(learning.?loop|pipeline.*отчёт|отчёт.*pipeline|конвейер|шаги.*обучени)", tl):
                return self._loop.get_pipeline_report()

            # Ручной запуск deferred checks (шаги 9-11)
            if re.search(r"(deferred|отложенн.*проверк|исход.*знани|outcome.*знани)", tl):
                results = self._loop.run_deferred_checks()
                if not results:
                    return "✅ Нет отложенных проверок или слишком рано (ждём 24ч после сохранения)"
                lines = [f"🔍 Выполнено проверок применения: {len(results)}"]
                for r in results:
                    icon = {"positive": "✅", "neutral": "⚪", "negative": "🔴"}.get(r.outcome, "?")
                    lines.append(f"  {icon} {r.entry_title[:50]} → {r.outcome}"
                                 + (" [ROLLBACK]" if r.rollback_done else ""))
                return "\n".join(lines)

            # Полный цикл обучения
            train_report = self._run_training_cycle(verbose=True)
            result = self._format_report(train_report)

            # После обучения — автопроверка cleaner раз в сутки
            maintenance_interval = 86400
            if time.time() - self._last_maintenance > maintenance_interval:
                try:
                    from cleaner.knowledge_cleaner import KnowledgeCleaner
                    cr = KnowledgeCleaner.get().run_maintenance(safe_delete=False)
                    if cr.duplicates or cr.stale or cr.low_quality:
                        result += (
                            f"\n\n🧹 Авто-очистка: "
                            f"найдено {len(cr.duplicates)} дублей, "
                            f"{len(cr.stale)} устаревших, "
                            f"{len(cr.low_quality)} низкокачественных. "
                            f"Выполнено: {len(cr.actions_taken)} действий. "
                            f"Запусти «наведи порядок» для подробностей."
                        )
                    self._last_maintenance = time.time()
                except Exception as ce:
                    log.debug("Auto-maintenance error: %s", ce)

            return result
        except Exception as e:
            self._log_failure("training", str(e))
            return f"❌ Ошибка обучения: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    def start_background_training(self) -> None:
        """Запустить фоновое обучение. Первый цикл через 5 мин, затем каждый час."""
        if self._bg_thread and self._bg_thread.is_alive():
            return
        self._stop_event.clear()
        self._bg_thread = threading.Thread(
            target=self._bg_loop, daemon=True, name="self-training"
        )
        self._bg_thread.start()
        log.info("SelfTrainingAgent: background training started (first in 5min, then every %ds)", TRAINING_INTERVAL)

    def stop_background_training(self) -> None:
        self._stop_event.set()

    # ── Вспомогательные свойства ─────────────────────────────────────────────

    @property
    def _validator(self) -> KnowledgeValidator:
        return KnowledgeValidator.get()

    @property
    def _journal(self) -> TrainingJournal:
        return TrainingJournal.get()

    @property
    def _loop(self) -> LearningLoop:
        return LearningLoop.get()

    # ── Главный цикл обучения ─────────────────────────────────────────────────

    def _run_training_cycle(self, verbose: bool = False) -> TrainingReport:
        """
        Полный цикл самообучения.
        Каждый шаг проходит валидацию и записывается в journal.
        """
        report = TrainingReport()
        t_start = time.time()
        cycle_num = self._training_count + 1
        log.info("SelfTraining: starting cycle #%d", cycle_num)

        # Шаг 1: Анализ последних разговоров
        messages = self._memory.get_messages(limit=100)
        report.analyzed = len(messages)
        self._journal.record_cycle_start(cycle_num, len(messages))

        if len(messages) < 3:
            report.improvements.append("Недостаточно данных. Продолжай общаться!")
            self._journal.record_cycle_end(cycle_num, 0, 0, 0,
                                           time.time() - t_start)
            self._training_count += 1
            self._last_training = time.time()
            return report

        # Шаг 2: Анализ ошибок — ГЛАВНЫЙ приоритет
        error_fixed = self._analyze_and_fix_errors(cycle_num)
        if error_fixed:
            report.improvements.append(f"Проанализировано ошибок: {error_fixed}")
            report.learned += error_fixed

        # Шаг 3: Выявить часто задаваемые темы + приоритетные темы
        topics = self._extract_popular_topics(messages)
        # Добавляем приоритетные темы если пользователь мало пишет
        if len(topics) < 3:
            import random
            topics = list(topics) + random.sample(PRIORITY_TRAINING_TOPICS, 3)
        if verbose:
            log.info("Popular topics: %s", topics[:5])

        # Шаг 4: Найти провалы (короткие/плохие ответы)
        weak_pairs = self._find_weak_responses(messages)
        report.weaknesses = [f"«{t[:60]}»: слабый ответ" for t in weak_pairs[:3]]

        # Шаг 5: Сгенерировать знания по новым темам (с валидацией!)
        rejected_count = 0
        for topic in topics[:3]:
            entry_id, was_rejected = self._generate_knowledge_entry(
                topic, cycle_num)
            if entry_id:
                report.learned += 1
            elif was_rejected:
                rejected_count += 1

        # Шаг 6: Синтетические Q&A для слабых мест (с валидацией!)
        if weak_pairs:
            qa_count, qa_rej = self._generate_synthetic_qa(
                weak_pairs[:2], cycle_num)
            report.learned += qa_count
            rejected_count += qa_rej

        # Шаг 7: Обновить importance scores
        updated = self._rerank_knowledge()
        report.updated = updated

        # Шаг 7.5: Активно изучать приоритетные темы (программирование, платежи)
        seeded = self._seed_priority_knowledge(cycle=cycle_num)
        if seeded:
            report.learned += seeded
            report.improvements.append(
                f"📚 Изучена приоритетная тема ({seeded} записей)"
            )

        # Шаг 8: Предложения по улучшению
        report.improvements = self._suggest_improvements(messages, topics)

        elapsed = time.time() - t_start
        self._journal.record_cycle_end(
            cycle_num, report.learned, rejected_count, updated, elapsed)

        self._training_count += 1
        self._last_training = time.time()
        log.info(
            "SelfTraining: cycle #%d done in %.1fs | +%d saved | -%d rejected | ~%d updated",
            cycle_num, elapsed, report.learned, rejected_count, updated,
        )
        return report

    # ── Анализ разговоров ─────────────────────────────────────────────────────

    def _extract_popular_topics(self, messages: List[Any]) -> List[str]:
        """Извлечь наиболее часто обсуждаемые темы."""
        user_msgs = [m.content for m in messages if m.role == "user"]
        if not user_msgs:
            return []

        # Используем LLM для извлечения тем
        sample = "\n".join(user_msgs[-20:])[:2000]
        prompt = (
            f"Проанализируй эти вопросы пользователя и выдели 5 основных тем:\n\n"
            f"{sample}\n\n"
            f"Верни JSON: [\"тема 1\", \"тема 2\", ...]\n"
            f"Только JSON."
        )
        try:
            resp = self._llm.ask_fast(prompt, task_type="classify")
            match = re.search(r'\[.*?\]', resp, re.DOTALL)
            if match:
                topics = json.loads(match.group())
                return [str(t) for t in topics[:5]]
        except Exception as e:
            log.debug("Topic extraction failed: %s", e)

        # Fallback — частотный анализ слов
        words = []
        for msg in user_msgs:
            words.extend(w.lower() for w in re.findall(r'\b[а-яёa-z]{4,}\b', msg))
        counter = Counter(words)
        stop = {"этот", "который", "можешь", "можно", "нужно", "хочу", "делай", "what", "that", "this"}
        return [w for w, _ in counter.most_common(20) if w not in stop][:5]

    def _find_weak_responses(self, messages: List[Any]) -> List[str]:
        """Найти темы где ответы были слабыми (короткими или содержат ошибки)."""
        pairs = []
        error_markers = ("⚠️", "❌", "Ошибка", "Error", "не удалось", "недоступен")
        for i in range(len(messages) - 1):
            if messages[i].role == "user" and i + 1 < len(messages):
                next_msg = messages[i + 1]
                if next_msg.role == "assistant":
                    is_short = len(next_msg.content) < 150
                    is_error = any(m in next_msg.content[:80] for m in error_markers)
                    if is_short or is_error:
                        pairs.append(messages[i].content[:100])
        return pairs[:5]

    def _analyze_and_fix_errors(self, cycle: int = 0) -> int:
        """
        Анализирует сохранённые ошибки и генерирует знания как их избежать.
        Теперь с валидацией и записью в journal.
        Возвращает количество обработанных ошибок.
        """
        try:
            error_entries = self._memory.get_error_patterns(limit=10)
            if not error_entries:
                return 0

            processed = 0
            for entry in error_entries:
                fix_title = f"[FIX] {entry.title[:50]}"
                if self._memory.knowledge_exists(fix_title[:40], category="solution"):
                    continue

                prompt = (
                    f"Проанализируй следующую ошибку AI-системы и предложи конкретное решение:\n\n"
                    f"ОШИБКА: {entry.content[:400]}\n\n"
                    f"Дай:\n"
                    f"1. Причину ошибки (1-2 предложения)\n"
                    f"2. Конкретное решение/исправление\n"
                    f"3. Как предотвратить повторение\n\n"
                    f"Будь конкретным, 200-300 слов."
                )
                resp = self._llm.ask(LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    task_type="analysis",
                    max_tokens=500,
                    preferred_provider=LLMProvider.DEEPSEEK,
                ))
                if not resp.success or len(resp.content) < 80:
                    continue

                candidate = KnowledgeEntry(
                    category="solution",
                    title=fix_title,
                    content=f"Ошибка:\n{entry.content[:300]}\n\nРешение:\n{resp.content}",
                    tags=["error-fix", "auto-generated", "self-training"],
                    importance=0.85,
                    source="self_training_agent",
                )
                from training.learning_loop import Verdict
                r = self._loop.process(candidate, cycle=cycle)
                if r.verdict in (Verdict.SAVED, Verdict.UPDATED):
                    processed += 1
                else:
                    log.debug("SelfTraining: error-fix not saved (verdict=%s): %s",
                              r.verdict, r.reason)
            return processed
        except Exception as e:
            log.debug("Error analysis failed: %s", e)
            return 0

    # ── Генерация знаний ──────────────────────────────────────────────────────

    def _generate_knowledge_entry(self, topic: str,
                                   cycle: int = 0) -> Tuple[Optional[int], bool]:
        """
        Сгенерировать знание по теме через LLM.
        Возвращает (entry_id или None, was_rejected_by_validator).
        """
        existing = self._memory.search_knowledge(topic, limit=2)
        if existing:
            return None, False  # Уже есть — не дублируем

        prompt = (
            f"Создай детальное руководство по теме: «{topic}»\n\n"
            f"Контекст: Это для персонального ИИ-ассистента.\n"
            f"Формат:\n"
            f"1. Краткое объяснение темы\n"
            f"2. Ключевые факты и принципы\n"
            f"3. Практические примеры\n"
            f"4. Типичные вопросы и ответы\n\n"
            f"Будь конкретным и полезным. 300-500 слов."
        )
        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="analysis",
            max_tokens=800,
            preferred_provider=LLMProvider.DEEPSEEK,
        ))
        if not resp.success or len(resp.content) < 100:
            return None, False

        entry = KnowledgeEntry(
            category="auto-learned",
            title=f"[Auto] {topic[:60]}",
            content=resp.content,
            tags=["self-training", "auto-generated"],
            importance=0.65,
            source="self_training_agent",
        )

        # Гипотезы получают сниженную importance
        entry.confidence = 0.5
        entry.knowledge_type = "auto"

        # Пропускаем через полный 11-шаговый pipeline
        result = self._loop.process(entry, cycle=cycle)

        from training.learning_loop import Verdict
        if result.verdict in (Verdict.SAVED, Verdict.UPDATED):
            log.info("SelfTraining: pipeline SAVED #%d '%s' "
                     "(type=%s conf=%.2f q=%.2f)",
                     result.entry_id, topic[:40],
                     result.knowledge_type, result.confidence, result.quality_score)
            return result.entry_id, False
        elif result.verdict == Verdict.REJECTED:
            log.debug("SelfTraining: topic knowledge rejected '%s': %s",
                      topic[:40], result.reason)
            return None, True  # rejected
        elif result.verdict in (Verdict.CONFLICT, Verdict.SKIPPED):
            return None, False  # конфликт обработан или дубликат
        else:
            return None, False

    def _generate_synthetic_qa(self, weak_topics: List[str],
                               cycle: int = 0) -> Tuple[int, int]:
        """
        Сгенерировать синтетические Q&A пары для слабых мест.
        Возвращает (saved_count, rejected_count).
        """
        saved = rejected = 0
        for topic in weak_topics:
            prompt = (
                f"Создай 3 вопроса-ответа по теме: «{topic}»\n\n"
                f"Формат JSON:\n"
                f"[{{\"q\": \"вопрос\", \"a\": \"подробный ответ не короче 3 предложений\"}}, ...]\n"
                f"Только JSON."
            )
            resp = self._llm.ask(LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                task_type="code",
                max_tokens=600,
                preferred_provider=LLMProvider.DEEPSEEK,
            ))
            if not resp.success:
                continue
            try:
                match = re.search(r'\[.*?\]', resp.content, re.DOTALL)
                if not match:
                    continue
                qa_pairs = json.loads(match.group())
                for qa in qa_pairs[:3]:
                    q, a = qa.get("q", ""), qa.get("a", "")
                    if not q or not a or len(a) < 50:
                        continue
                    entry = KnowledgeEntry(
                        category="qa",
                        title=f"[Q&A] {q[:60]}",
                        content=f"Вопрос: {q}\n\nОтвет: {a}",
                        tags=["synthetic-qa", "self-training"],
                        importance=0.6,
                        source="self_training_agent",
                    )
                    # Через полный pipeline
                    from training.learning_loop import Verdict
                    entry.knowledge_type = "qa"
                    r = self._loop.process(entry, cycle=cycle)
                    if r.verdict in (Verdict.SAVED, Verdict.UPDATED):
                        saved += 1
                    elif r.verdict == Verdict.REJECTED:
                        rejected += 1
                    # CONFLICT/SKIPPED — не считаем ни туда ни туда
            except Exception as e:
                log.debug("Synthetic QA parse error: %s", e)
        return saved, rejected

    # ── Оптимизация памяти ────────────────────────────────────────────────────

    def _rerank_knowledge(self) -> int:
        """
        Пересчитать importance scores на основе частоты использования.
        Знания, которые часто обсуждались → выше importance.
        Использует update_knowledge() для thread-safe обновления.
        """
        try:
            entries = self._memory.get_knowledge(limit=200)
            if not entries:
                return 0

            messages = self._memory.get_messages(limit=50)
            user_texts = " ".join(m.content for m in messages if m.role == "user").lower()
            user_words = set(re.findall(r'\b\w{4,}\b', user_texts))

            updated = 0
            for entry in entries:
                entry_words = set(re.findall(r'\b\w{4,}\b', entry.content.lower()))
                if not entry_words:
                    continue
                overlap = len(entry_words & user_words) / max(len(entry_words), 1)
                # Ошибки и решения всегда сохраняют высокий приоритет
                base = 0.8 if entry.category in ("error", "solution") else entry.importance
                new_importance = min(1.0, base + overlap * 0.12)
                if abs(new_importance - entry.importance) > 0.04:
                    if self._memory.update_knowledge(entry.id, importance=new_importance):
                        updated += 1
            return updated
        except Exception as e:
            log.debug("Rerank failed: %s", e)
            return 0

    # ── Предложения по улучшению ──────────────────────────────────────────────

    def _suggest_improvements(self, messages: List[Any],
                               topics: List[str]) -> List[str]:
        """Сформулировать конкретные предложения по улучшению системы."""
        improvements = []

        # Анализ длины ответов
        bot_msgs = [m for m in messages if m.role == "assistant"]
        if bot_msgs:
            avg_len = sum(len(m.content) for m in bot_msgs) / len(bot_msgs)
            if avg_len < 200:
                improvements.append(
                    f"📏 Средняя длина ответов {avg_len:.0f} символов — слишком короткие. "
                    f"Добавить в промт: 'Давай детальные ответы с примерами.'"
                )

        # Часто задаваемые темы без knowledge entries
        for topic in topics[:3]:
            existing = self._memory.search_knowledge(topic[:30], limit=1)
            if not existing:
                improvements.append(
                    f"📚 Тема «{topic[:40]}» часто спрашивается, но нет knowledge entry. "
                    f"Создано автоматически."
                )

        # Общие рекомендации
        improvements.append(
            "🔄 Рекомендуется: регулярно запускать 'обучи себя' для накопления знаний"
        )

        return improvements[:5]

    # ── Форматирование отчёта ─────────────────────────────────────────────────

    def _format_report(self, report: TrainingReport) -> str:
        last_ts = time.strftime("%H:%M:%S", time.localtime(self._last_training)) \
                  if self._last_training else "сейчас"
        lines = [
            f"🧠 **Отчёт о самообучении #{self._training_count}**",
            f"⏰ Время: {last_ts}",
            "",
            f"📊 **Статистика:**",
            f"• Проанализировано сообщений: {report.analyzed}",
            f"• Создано новых знаний: {report.learned}",
            f"• Обновлено importance scores: {report.updated}",
        ]
        if report.weaknesses:
            lines += ["", "⚠️ **Слабые места:**"]
            lines += [f"  • {w}" for w in report.weaknesses]

        if report.improvements:
            lines += ["", "💡 **Улучшения и рекомендации:**"]
            lines += [f"  • {imp}" for imp in report.improvements]

        lines += [
            "",
            f"🔁 Следующее автообучение через 1 час.",
            f"📈 Всего циклов обучения: {self._training_count}"
        ]
        return "\n".join(lines)

    # ── Целевое обучение программированию и платежам ─────────────────────────

    def _seed_priority_knowledge(self, cycle: int = 0) -> int:
        """
        Активно засеивает знания по приоритетным темам (программирование,
        платёжные системы, фриланс) если они ещё не изучены.
        Запускается каждые 6 циклов (~6 часов).
        """
        import random
        if cycle % 6 != 0:   # каждые 6 циклов
            return 0

        # Выбираем случайную приоритетную тему которую ещё не изучали
        candidates = [t for t in PRIORITY_TRAINING_TOPICS
                      if not self._memory.search_knowledge(t[:25], limit=1)]
        if not candidates:
            return 0

        topic = random.choice(candidates[:5])
        log.info("SelfTraining: seeding priority topic '%s'", topic[:50])
        entry_id, _ = self._generate_knowledge_entry(topic, cycle=cycle)
        return 1 if entry_id else 0

    # ── Фоновый цикл ─────────────────────────────────────────────────────────

    def _bg_loop(self) -> None:
        """
        Фоновый цикл автоматического обучения.
        Первый цикл — через 5 минут (чтобы собрать стартовые данные).
        Последующие — каждый час.
        """
        log.info("SelfTraining background loop started")
        # Первый цикл через 5 минут
        first_run_delay = 300
        self._stop_event.wait(timeout=first_run_delay)
        if self._stop_event.is_set():
            return
        # Выполняем первый цикл
        try:
            report = self._run_training_cycle(verbose=False)
            log.info("SelfTraining first cycle: +%d knowledge, %d updated",
                     report.learned, report.updated)
        except Exception as e:
            log.error("SelfTraining first cycle error: %s", e)

        # Основной цикл — каждый час
        MAINTENANCE_INTERVAL  = 86400  # раз в сутки
        DEFERRED_CHECK_INTERVAL = 21600  # раз в 6 часов (шаги 9-11)
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=TRAINING_INTERVAL)
            if self._stop_event.is_set():
                break
            try:
                report = self._run_training_cycle(verbose=False)
                log.info("SelfTraining auto-cycle #%d: +%d knowledge, %d updated",
                         self._training_count, report.learned, report.updated)
            except Exception as e:
                log.error("SelfTraining bg error: %s", e)

            # Отложенные проверки применения знаний (шаги 9-11) — каждые 6ч
            if time.time() - self._last_deferred_check > DEFERRED_CHECK_INTERVAL:
                try:
                    deferred_results = self._loop.run_deferred_checks()
                    if deferred_results:
                        pos = sum(1 for r in deferred_results if r.outcome == "positive")
                        neg = sum(1 for r in deferred_results if r.outcome == "negative")
                        rbs = sum(1 for r in deferred_results if r.rollback_done)
                        log.info(
                            "Deferred checks: %d processed | pos=%d neg=%d rollbacks=%d",
                            len(deferred_results), pos, neg, rbs,
                        )
                    self._last_deferred_check = time.time()
                except Exception as de:
                    log.error("Deferred check bg error: %s", de)

            # Авто-обслуживание памяти раз в сутки
            if time.time() - self._last_maintenance > MAINTENANCE_INTERVAL:
                try:
                    from cleaner.knowledge_cleaner import KnowledgeCleaner
                    cr = KnowledgeCleaner.get().run_maintenance(safe_delete=False)
                    self._last_maintenance = time.time()
                    log.info(
                        "Auto-maintenance: dupes=%d stale=%d lq=%d actions=%d",
                        len(cr.duplicates), len(cr.stale),
                        len(cr.low_quality), len(cr.actions_taken),
                    )
                except Exception as me:
                    log.error("Auto-maintenance bg error: %s", me)
