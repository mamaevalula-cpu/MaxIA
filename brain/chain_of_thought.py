# -*- coding: utf-8 -*-
"""
brain/chain_of_thought.py — Движок цепочек рассуждений (Chain-of-Thought).

Архитектура:
  Запрос → Decompose → Reasoning Steps → Confidence Scoring → Verification → Ответ

Режимы:
  • CoT  — линейная цепочка шагов (быстро, надёжно)
  • ToT  — Tree-of-Thought: ветвление N путей → оценка → лучший (сложные задачи)
  • Auto — автоматический выбор режима по сложности запроса

Интеграция:
    engine = ChainOfThoughtEngine.get()
    result = engine.reason(query, context="", intent="analysis")
    if result.confidence >= 0.75:
        use result.final_answer
    else:
        fallback to debate
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("brain.cot")

# ── Конфигурация ──────────────────────────────────────────────────────────────

COT_MAX_STEPS        = 6      # максимум шагов в цепочке
TOT_BRANCHES         = 3      # количество ветвей в Tree-of-Thought
TOT_DEPTH            = 2      # глубина дерева
CONFIDENCE_THRESHOLD = 0.70   # минимальная уверенность для финального ответа
MIN_QUERY_LEN_COT    = 30     # минимальная длина запроса для запуска CoT
VERIFICATION_PASSES  = 2      # количество проходов верификации

# Интенты где CoT всегда запускается
ALWAYS_COT_INTENTS = {"math", "project_create"}  # code_change removed — Claude handles it directly — uses length threshold instead
# Интенты где CoT не нужен (быстрые ответы)
SKIP_COT_INTENTS   = {"status", "memory", "monitor", "image", "key_manager", "rollback"}

# Паттерны «сложных» запросов (требуют ToT)
_TOT_PATTERNS = [
    r"лучш(ий|ая|ее|ие) способ",
    r"сравни .{5,} и .{5,}",
    r"архитектур[аы]",
    r"трейдоф|trade.?off",
    r"pros and cons|плюс.* и минус",
    r"оптимальн",
    r"best (approach|strategy|way|architecture)",
    r"should i (use|choose|pick|implement)",
    r"что лучше",
    r"как правильно",
]
_TOT_RE = re.compile("|".join(_TOT_PATTERNS), re.IGNORECASE)


class ReasoningMode(Enum):
    COT  = "chain_of_thought"
    TOT  = "tree_of_thought"
    FAST = "fast"  # без CoT (короткие/простые запросы)


@dataclass
class ReasoningStep:
    """Один шаг рассуждения."""
    step_num:   int
    thought:    str          # рассуждение на этом шаге
    conclusion: str          # вывод шага
    confidence: float = 0.5  # уверенность 0..1
    verified:   bool  = False


@dataclass
class ThoughtBranch:
    """Ветвь в Tree-of-Thought."""
    branch_id:   int
    hypothesis:  str          # гипотеза / подход
    reasoning:   List[ReasoningStep] = field(default_factory=list)
    score:       float = 0.0  # итоговая оценка ветви
    selected:    bool  = False


@dataclass
class CoTResult:
    """Результат работы движка CoT/ToT."""
    query:          str
    mode:           ReasoningMode
    steps:          List[ReasoningStep]  = field(default_factory=list)
    branches:       List[ThoughtBranch] = field(default_factory=list)
    final_answer:   str   = ""
    confidence:     float = 0.0
    verified:       bool  = False
    latency_ms:     float = 0.0
    reasoning_trace: str  = ""  # полная цепочка для сохранения в памяти

    @property
    def succeeded(self) -> bool:
        return bool(self.final_answer) and self.confidence >= CONFIDENCE_THRESHOLD

    def format_trace(self) -> str:
        """Форматировать полный трейс рассуждения для вставки в промпт/память."""
        lines = [f"[{self.mode.value.upper()}] Query: {self.query[:100]}"]
        if self.mode == ReasoningMode.TOT and self.branches:
            for b in self.branches:
                mark = "★" if b.selected else "○"
                lines.append(f"\n{mark} Branch {b.branch_id}: {b.hypothesis[:80]}")
                lines.append(f"   Score: {b.score:.2f}")
                for s in b.reasoning:
                    lines.append(f"   Step {s.step_num}: {s.conclusion[:100]}")
        else:
            for s in self.steps:
                conf_bar = "█" * int(s.confidence * 5) + "░" * (5 - int(s.confidence * 5))
                lines.append(f"\nStep {s.step_num} [{conf_bar}] {s.thought[:80]}")
                lines.append(f"  → {s.conclusion[:120]}")
        lines.append(f"\nFinal (confidence={self.confidence:.2f}): {self.final_answer[:200]}")
        return "\n".join(lines)


class ChainOfThoughtEngine:
    """
    Singleton. Движок цепочек рассуждений.

    Использование:
        engine = ChainOfThoughtEngine.get()
        result = engine.reason(query, context, intent)
        if result.succeeded:
            use result.final_answer
    """

    _instance: Optional["ChainOfThoughtEngine"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._llm_callback: Optional[Callable] = None
        self._stats = {"cot": 0, "tot": 0, "fast": 0, "improved": 0}
        self._rlock = threading.RLock()
        log.info("ChainOfThoughtEngine initialized")

    @classmethod
    def get(cls) -> "ChainOfThoughtEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_llm_callback(self, cb: Callable) -> None:
        """Подключить LLM callback(prompt, system, max_tokens) → str."""
        self._llm_callback = cb

    # ── Главный метод ─────────────────────────────────────────────────────────

    def reason(
        self,
        query:   str,
        context: str = "",
        intent:  str = "chat",
        force_mode: Optional[ReasoningMode] = None,
    ) -> CoTResult:
        """
        Запустить рассуждение по запросу.

        Args:
            query:      текст запроса
            context:    RAG контекст (опционально)
            intent:     классифицированный intent
            force_mode: принудительно задать режим

        Returns:
            CoTResult с цепочкой рассуждений и финальным ответом
        """
        t0 = time.time()

        # Выбрать режим
        mode = force_mode or self._select_mode(query, intent)

        if mode == ReasoningMode.FAST or self._llm_callback is None:
            with self._rlock:
                self._stats["fast"] += 1
            return CoTResult(
                query=query, mode=ReasoningMode.FAST, confidence=0.0, latency_ms=0.0
            )

        try:
            if mode == ReasoningMode.TOT:
                result = self._run_tot(query, context, intent)
                with self._rlock:
                    self._stats["tot"] += 1
            else:
                result = self._run_cot(query, context, intent)
                with self._rlock:
                    self._stats["cot"] += 1
        except Exception as e:
            log.warning("CoT reasoning failed: %s", e)
            return CoTResult(query=query, mode=mode, confidence=0.0)

        result.latency_ms = (time.time() - t0) * 1000
        result.reasoning_trace = result.format_trace()

        if result.confidence >= CONFIDENCE_THRESHOLD:
            with self._rlock:
                self._stats["improved"] += 1

        log.debug(
            "CoT [%s] confidence=%.2f steps=%d latency=%.0fms",
            mode.value, result.confidence, len(result.steps), result.latency_ms
        )
        return result

    # ── Выбор режима ─────────────────────────────────────────────────────────

    def _select_mode(self, query: str, intent: str) -> ReasoningMode:
        """Автоматически выбрать режим рассуждения."""
        if intent in SKIP_COT_INTENTS:
            return ReasoningMode.FAST

        if len(query) < MIN_QUERY_LEN_COT and intent not in ALWAYS_COT_INTENTS:
            return ReasoningMode.FAST

        # Tree-of-Thought для задач выбора/архитектуры
        if _TOT_RE.search(query):
            return ReasoningMode.TOT

        # CoT для всего остального из списка "всегда"
        if intent in ALWAYS_COT_INTENTS:
            return ReasoningMode.COT

        # CoT для длинных/сложных запросов
        if len(query) > 100:
            return ReasoningMode.COT

        return ReasoningMode.FAST

    # ── Chain-of-Thought (линейный) ───────────────────────────────────────────

    def _run_cot(self, query: str, context: str, intent: str) -> CoTResult:
        """Запустить линейную цепочку рассуждений."""
        steps: List[ReasoningStep] = []

        # Шаг 1: декомпозиция задачи
        decomp = self._decompose(query, context, intent)
        if not decomp:
            return CoTResult(query=query, mode=ReasoningMode.COT, confidence=0.0)

        # Шаги 2..N: рассуждение по каждому аспекту
        sub_tasks = self._parse_subtasks(decomp)[:COT_MAX_STEPS - 1]
        cumulative_context = context

        for i, sub in enumerate(sub_tasks, 1):
            thought, conclusion, conf = self._reason_step(
                step_num=i,
                sub_task=sub,
                original_query=query,
                context=cumulative_context,
                intent=intent,
                prev_steps=steps,
            )
            step = ReasoningStep(
                step_num=i,
                thought=thought,
                conclusion=conclusion,
                confidence=conf,
            )
            steps.append(step)
            # Накапливаем контекст для следующего шага
            cumulative_context += f"\n[Step {i}]: {conclusion}"

        if not steps:
            return CoTResult(query=query, mode=ReasoningMode.COT, confidence=0.0)

        # Финальный синтез
        final, confidence = self._synthesize_cot(query, steps, context, intent)

        # Верификация
        if confidence >= 0.5:
            final, confidence = self._verify_answer(query, final, steps, intent)

        return CoTResult(
            query=query,
            mode=ReasoningMode.COT,
            steps=steps,
            final_answer=final,
            confidence=confidence,
            verified=confidence >= CONFIDENCE_THRESHOLD,
        )

    def _decompose(self, query: str, context: str, intent: str) -> str:
        """Декомпозировать задачу на подзадачи."""
        ctx_part = f"\nКонтекст:\n{context[:500]}" if context else ""
        system = (
            "Ты — аналитический движок. Твоя задача — декомпозировать вопрос "
            "на 3-5 логических шагов рассуждения. "
            "Формат ответа: нумерованный список шагов, каждый шаг на новой строке. "
            "Пример:\n1. Определить контекст задачи\n2. Выявить ключевые факторы\n"
            "3. Применить соответствующий метод\n4. Сформулировать вывод"
        )
        prompt = (
            f"Вопрос/задача: {query}{ctx_part}\n\n"
            f"Intent: {intent}\n\n"
            f"Декомпозируй на шаги рассуждения:"
        )
        return self._call_llm(prompt, system=system, max_tokens=400)

    def _parse_subtasks(self, decomp_text: str) -> List[str]:
        """Извлечь список подзадач из текста декомпозиции."""
        lines = decomp_text.strip().splitlines()
        tasks = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Убрать нумерацию: "1.", "1)", "Step 1:", etc.
            cleaned = re.sub(r'^[\d]+[.):\s]+', '', line).strip()
            if len(cleaned) > 5:
                tasks.append(cleaned)
        return tasks if tasks else [decomp_text[:200]]

    def _reason_step(
        self,
        step_num: int,
        sub_task: str,
        original_query: str,
        context: str,
        intent: str,
        prev_steps: List[ReasoningStep],
    ) -> Tuple[str, str, float]:
        """Выполнить один шаг рассуждения. Возвращает (thought, conclusion, confidence)."""
        prev_context = ""
        if prev_steps:
            prev_context = "\nПредыдущие выводы:\n" + "\n".join(
                f"Шаг {s.step_num}: {s.conclusion[:150]}"
                for s in prev_steps[-3:]  # последние 3 шага
            )

        system = (
            "Ты — логический движок рассуждений. Рассуждай чётко и конкретно. "
            "Давай вывод в конце, начинающийся с 'Вывод:'. "
            "Оцени свою уверенность от 0.0 до 1.0 в формате 'Уверенность: 0.X'."
        )
        ctx_part = f"\nКонтекст: {context[:400]}" if context else ""
        prompt = (
            f"Исходный запрос: {original_query[:200]}"
            f"{ctx_part}"
            f"{prev_context}\n\n"
            f"Шаг {step_num}: {sub_task}\n\n"
            f"Выполни этот шаг рассуждения:"
        )
        raw = self._call_llm(prompt, system=system, max_tokens=600)

        thought    = raw
        conclusion = ""
        confidence = 0.5

        # Извлечь вывод
        m = re.search(r'[Вв]ывод[:\s]+(.+?)(?:\n|$)', raw, re.DOTALL)
        if m:
            conclusion = m.group(1).strip()[:300]
        else:
            # Берём последнее предложение
            sentences = [s.strip() for s in re.split(r'[.!?]', raw) if s.strip()]
            conclusion = sentences[-1][:300] if sentences else raw[:200]

        # Извлечь уверенность
        m_conf = re.search(r'[Уу]веренность[:\s]+([\d.]+)', raw)
        if m_conf:
            try:
                confidence = max(0.0, min(1.0, float(m_conf.group(1))))
            except ValueError:
                pass

        return thought, conclusion, confidence

    def _synthesize_cot(
        self,
        query: str,
        steps: List[ReasoningStep],
        context: str,
        intent: str,
    ) -> Tuple[str, float]:
        """Синтезировать финальный ответ из шагов CoT."""
        steps_text = "\n".join(
            f"Шаг {s.step_num} (уверенность={s.confidence:.2f}):\n"
            f"  Рассуждение: {s.thought[:200]}\n"
            f"  Вывод: {s.conclusion}"
            for s in steps
        )
        avg_confidence = sum(s.confidence for s in steps) / max(len(steps), 1)

        system = (
            "Ты — синтезатор рассуждений. Создай финальный ответ на основе "
            "всех шагов рассуждения. Ответ должен быть чётким, структурированным "
            "и напрямую отвечать на исходный вопрос."
        )
        ctx_part = f"\nКонтекст: {context[:300]}" if context else ""
        prompt = (
            f"Исходный запрос: {query}"
            f"{ctx_part}\n\n"
            f"Шаги рассуждения:\n{steps_text}\n\n"
            f"Синтезируй финальный ответ:"
        )
        final = self._call_llm(prompt, system=system, max_tokens=1500)

        # Уверенность финального ответа — средняя по шагам, скорректированная
        confidence = min(1.0, avg_confidence + 0.1)  # синтез немного повышает уверенность
        if len(steps) >= 3:
            confidence = min(1.0, confidence + 0.05)

        return final, confidence

    # ── Tree-of-Thought ───────────────────────────────────────────────────────

    def _run_tot(self, query: str, context: str, intent: str) -> CoTResult:
        """Запустить Tree-of-Thought: N ветвей → оценка → лучшая."""
        # 1. Генерировать гипотезы
        hypotheses = self._generate_hypotheses(query, context, intent)
        if not hypotheses:
            # Откат к CoT
            return self._run_cot(query, context, intent)

        # 2. Развить каждую ветвь
        branches: List[ThoughtBranch] = []
        for i, hyp in enumerate(hypotheses[:TOT_BRANCHES], 1):
            branch = ThoughtBranch(branch_id=i, hypothesis=hyp)
            # Краткое рассуждение для каждой ветви
            reasoning, score = self._develop_branch(hyp, query, context, intent)
            branch.reasoning = reasoning
            branch.score = score
            branches.append(branch)
            log.debug("ToT branch %d score=%.2f: %s", i, score, hyp[:60])

        # 3. Выбрать лучшую ветвь
        if not branches:
            return self._run_cot(query, context, intent)

        best = max(branches, key=lambda b: b.score)
        best.selected = True

        # 4. Генерировать финальный ответ на основе лучшей ветви
        final, confidence = self._synthesize_tot(query, best, context, intent)

        # Все шаги из лучшей ветви
        all_steps = best.reasoning

        return CoTResult(
            query=query,
            mode=ReasoningMode.TOT,
            steps=all_steps,
            branches=branches,
            final_answer=final,
            confidence=confidence,
            verified=confidence >= CONFIDENCE_THRESHOLD,
        )

    def _generate_hypotheses(
        self, query: str, context: str, intent: str
    ) -> List[str]:
        """Сгенерировать N альтернативных подходов к задаче."""
        ctx_part = f"\nКонтекст: {context[:400]}" if context else ""
        system = (
            "Ты — генератор альтернативных подходов. "
            f"Придумай ровно {TOT_BRANCHES} разных способа решить задачу/ответить на вопрос. "
            "Каждый подход — одна строка, начинается с цифры и точки. "
            "Подходы должны принципиально отличаться (разные угловые точки зрения)."
        )
        prompt = (
            f"Задача: {query}{ctx_part}\n\n"
            f"Сгенерируй {TOT_BRANCHES} принципиально разных подхода:"
        )
        raw = self._call_llm(prompt, system=system, max_tokens=400)

        hypotheses = []
        for line in raw.splitlines():
            line = line.strip()
            cleaned = re.sub(r'^[\d]+[.):\s]+', '', line).strip()
            if len(cleaned) > 10:
                hypotheses.append(cleaned)

        return hypotheses[:TOT_BRANCHES]

    def _develop_branch(
        self,
        hypothesis: str,
        query: str,
        context: str,
        intent: str,
    ) -> Tuple[List[ReasoningStep], float]:
        """Развить одну ветвь рассуждения и оценить её."""
        system = (
            "Ты — аналитик. Развей данный подход решения задачи (2-3 шага рассуждения). "
            "В конце дай оценку от 0.0 до 1.0 насколько этот подход хорош "
            "в формате 'Оценка подхода: 0.X'. "
            "Учитывай: полноту, корректность, практичность."
        )
        ctx_part = f"\nКонтекст: {context[:300]}" if context else ""
        prompt = (
            f"Задача: {query}{ctx_part}\n\n"
            f"Подход: {hypothesis}\n\n"
            f"Развей этот подход (2-3 шага рассуждения) и оцени его качество:"
        )
        raw = self._call_llm(prompt, system=system, max_tokens=600)

        # Извлечь оценку
        score = 0.5
        m = re.search(r'[Оо]ценка\s+подхода[:\s]+([\d.]+)', raw)
        if m:
            try:
                score = max(0.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass

        # Создать шаги из рассуждения
        steps: List[ReasoningStep] = []
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        for i, line in enumerate(lines[:TOT_DEPTH + 1], 1):
            if 'оценка' in line.lower():
                continue
            steps.append(ReasoningStep(
                step_num=i,
                thought=line[:200],
                conclusion=line[:150],
                confidence=score,
            ))

        return steps, score

    def _synthesize_tot(
        self,
        query: str,
        best_branch: ThoughtBranch,
        context: str,
        intent: str,
    ) -> Tuple[str, float]:
        """Создать финальный ответ на основе лучшей ветви ToT."""
        steps_text = "\n".join(
            f"  • {s.conclusion[:150]}" for s in best_branch.reasoning
        )
        system = (
            "Ты — синтезатор решений. Создай полный и конкретный ответ на вопрос "
            "на основе выбранного подхода и его обоснования."
        )
        ctx_part = f"\nКонтекст: {context[:300]}" if context else ""
        prompt = (
            f"Вопрос: {query}"
            f"{ctx_part}\n\n"
            f"Лучший подход (оценка={best_branch.score:.2f}): {best_branch.hypothesis}\n"
            f"Обоснование:\n{steps_text}\n\n"
            f"Дай полный ответ на основе этого подхода:"
        )
        final = self._call_llm(prompt, system=system, max_tokens=1500)

        confidence = min(1.0, best_branch.score + 0.15)
        return final, confidence

    # ── Верификация ───────────────────────────────────────────────────────────

    def _verify_answer(
        self,
        query: str,
        answer: str,
        steps: List[ReasoningStep],
        intent: str,
    ) -> Tuple[str, float]:
        """
        Верифицировать финальный ответ через дополнительный проход.
        Ищет противоречия, фактические ошибки, пропуски.
        """
        system = (
            "Ты — верификатор ответов. Твоя задача — проверить ответ на:\n"
            "1. Логические противоречия\n"
            "2. Фактические ошибки (если знаешь)\n"
            "3. Пропущенные важные аспекты\n\n"
            "Если ответ корректен — напиши 'ВЕРИФИКАЦИЯ: ПРОЙДЕНА'.\n"
            "Если есть проблемы — опиши их и дай исправленный ответ."
        )
        steps_summary = " → ".join(
            s.conclusion[:80] for s in steps[-3:]
        ) if steps else ""

        prompt = (
            f"Вопрос: {query[:200]}\n\n"
            f"Цепочка рассуждений: {steps_summary}\n\n"
            f"Ответ для проверки:\n{answer[:1000]}\n\n"
            f"Верифицируй ответ:"
        )
        verify_result = self._call_llm(prompt, system=system, max_tokens=800)

        if "ВЕРИФИКАЦИЯ: ПРОЙДЕНА" in verify_result.upper() or "ПРОЙДЕНА" in verify_result:
            # Ответ прошёл проверку — повысить уверенность
            avg_conf = sum(s.confidence for s in steps) / max(len(steps), 1) if steps else 0.5
            return answer, min(1.0, avg_conf + 0.2)

        # Извлечь исправленный ответ (после маркера)
        for marker in ["Исправленный ответ:", "Ответ:", "Corrected:", "Fixed:"]:
            if marker in verify_result:
                corrected = verify_result.split(marker, 1)[1].strip()
                if len(corrected) > 50:
                    avg_conf = sum(s.confidence for s in steps) / max(len(steps), 1) if steps else 0.5
                    return corrected, min(1.0, avg_conf + 0.1)

        # Верификация нашла проблемы но не дала чёткого исправления
        avg_conf = sum(s.confidence for s in steps) / max(len(steps), 1) if steps else 0.5
        return answer, max(0.3, avg_conf - 0.05)

    # ── LLM вызов ─────────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str, system: str = "", max_tokens: int = 800) -> str:
        """Безопасный вызов LLM с fallback."""
        if self._llm_callback is None:
            return ""
        try:
            return self._llm_callback(prompt, system=system, max_tokens=max_tokens) or ""
        except Exception as e:
            log.warning("CoT LLM call failed: %s", e)
            return ""

    # ── Вспомогательные ───────────────────────────────────────────────────────

    @staticmethod
    def should_use_cot(query: str, intent: str) -> bool:
        """Быстрая проверка — нужен ли CoT для этого запроса."""
        if intent in SKIP_COT_INTENTS:
            return False
        if intent in ALWAYS_COT_INTENTS:
            return True
        # analysis: only use CoT for genuinely complex queries (>200 chars)
        if intent == "analysis" and len(query) > 200:
            return True
        if intent == "analysis":
            return False  # short analysis questions → fast path
        if len(query) > 150:
            return True
        if _TOT_RE.search(query):
            return True
        return False

    def get_stats(self) -> Dict:
        with self._rlock:
            s = dict(self._stats)
        total = max(s.get("cot", 0) + s.get("tot", 0), 1)
        s["success_rate_pct"] = round(s.get("improved", 0) / total * 100, 1)
        return s

    def get_report(self) -> str:
        s = self.get_stats()
        return (
            f"🧠 **Chain-of-Thought Engine**\n"
            f"  CoT runs:  {s.get('cot', 0)}\n"
            f"  ToT runs:  {s.get('tot', 0)}\n"
            f"  Fast skip: {s.get('fast', 0)}\n"
            f"  Success rate: {s.get('success_rate_pct', 0)}%"
        )
