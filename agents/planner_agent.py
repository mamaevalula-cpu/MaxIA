# -*- coding: utf-8 -*-

"""

agents/planner_agent.py — Агент планирования и автономного выполнения задач.



Превращает высокоуровневую цель в исполняемый план:

  Goal → Decompose → Subtasks → Route → Execute → Synthesize → Result



Возможности:

  • Декомпозиция цели на подзадачи (до 8 шагов)

  • Автоматическое определение зависимостей между задачами

  • Параллельное выполнение независимых задач

  • Отслеживание прогресса через EventBus

  • Self-recovery при ошибках подзадач (retry + fallback)

  • Сохранение плана и результатов в MemoryStore

  • Приоритизация задач по критичности



Пример использования:

    planner = PlannerAgent()

    result = planner.process(

        "Создай Python библиотеку для анализа криптовалютных данных с тестами и документацией"

    )

"""



from __future__ import annotations



import concurrent.futures

import logging

import re

import threading

import time

import uuid

from dataclasses import dataclass, field

from enum import Enum

from typing import Any, Callable, Dict, List, Optional, Tuple



from agents.base_agent import AgentInfo, AgentStatus, BaseAgent

from core.event_bus import EventBus

from memory.memory_store import AgentTask, KnowledgeEntry, MemoryStore



log = logging.getLogger("agents.planner")



# Максимальное количество подзадач в плане

MAX_SUBTASKS = 8

# Максимальный параллелизм

MAX_PARALLEL = 5

# Timeout на выполнение одной подзадачи (секунды)

SUBTASK_TIMEOUT = 120

# Сложность — если запрос длиннее N слов → автоматически планируем

PLANNING_THRESHOLD_WORDS = 15





class TaskStatus(str, Enum):

    PENDING   = "pending"

    RUNNING   = "running"

    DONE      = "done"

    FAILED    = "failed"

    SKIPPED   = "skipped"





@dataclass

class Subtask:

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    title: str = ""

    description: str = ""

    agent_name: str = "chat"       # какой агент выполняет

    depends_on: List[str] = field(default_factory=list)  # IDs задач-предшественников

    priority: int = 5              # 1 (высший) – 10 (низший)

    status: TaskStatus = TaskStatus.PENDING

    result: str = ""

    error: str = ""

    started_at: float = 0.0

    completed_at: float = 0.0

    retry_count: int = 0



    @property

    def duration_ms(self) -> float:

        if self.started_at and self.completed_at:

            return (self.completed_at - self.started_at) * 1000

        return 0.0





@dataclass

class ExecutionPlan:

    goal: str

    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    subtasks: List[Subtask] = field(default_factory=list)

    created_at: float = field(default_factory=time.time)

    completed_at: float = 0.0

    final_result: str = ""



    @property

    def is_complete(self) -> bool:

        return all(t.status in (TaskStatus.DONE, TaskStatus.SKIPPED, TaskStatus.FAILED)

                   for t in self.subtasks)



    @property

    def success_rate(self) -> float:

        if not self.subtasks:

            return 1.0

        done = sum(1 for t in self.subtasks if t.status == TaskStatus.DONE)

        return done / len(self.subtasks)



    def get_ready_tasks(self) -> List[Subtask]:

        """Задачи готовые к выполнению (pending + зависимости resolved).

        FIX: FAILED/SKIPPED deps тоже считаются resolved — зависимые задачи не зависают.

        """

        resolved_ids = {t.id for t in self.subtasks

                        if t.status in (TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.SKIPPED)}

        return [

            t for t in self.subtasks

            if t.status == TaskStatus.PENDING

            and all(dep in resolved_ids for dep in t.depends_on)

        ]



    def to_summary(self) -> str:

        lines = [f"📋 **План**: {self.goal[:80]}", f"ID: {self.plan_id}", ""]

        for i, task in enumerate(self.subtasks, 1):

            emoji = {

                TaskStatus.DONE: "✅",

                TaskStatus.RUNNING: "🔄",

                TaskStatus.FAILED: "❌",

                TaskStatus.PENDING: "⏳",

                TaskStatus.SKIPPED: "⏭",

            }.get(task.status, "❓")

            lines.append(f"{emoji} {i}. [{task.agent_name}] {task.title}")

            if task.result and task.status == TaskStatus.DONE:

                lines.append(f"   → {task.result[:100]}")

            if task.error:

                lines.append(f"   ⚠️ {task.error[:80]}")

        return "\n".join(lines)





class PlannerAgent(BaseAgent):

    """

    Агент-планировщик. Декомпозирует сложные цели и координирует выполнение.

    """



    def __init__(self) -> None:

        super().__init__("planner")

        self._agents: Dict[str, Any] = {}          # ссылки на других агентов

        self._brain_callback: Optional[Callable] = None

        self._active_plans: Dict[str, ExecutionPlan] = {}

        self._rlock = threading.RLock()



    def info(self) -> AgentInfo:

        return AgentInfo(

            name="planner",

            description=(

                "Планировщик задач. Декомпозирует сложные цели на подзадачи, "

                "координирует агентов, отслеживает прогресс."

            ),

            capabilities=[

                "goal_decomposition", "task_routing", "parallel_execution",

                "progress_tracking", "self_recovery", "project_management",

            ],

            version="2.0.0",

        )



    def can_handle(self, text: str) -> bool:

        """Обрабатывать сложные многошаговые задачи."""

        patterns = [

            r"(создай|разработай|построй|реализуй).{10,}(с тестами|и задокументируй|pipeline)",

            r"(сделай|выполни) план\b",

            r"пошаговый план",

            r"разбей на этапы",

            r"(автономно|самостоятельно) (выполни|сделай|создай)",

            r"(проект|система|архитектура) .{10,}(с нуля|полностью|целиком)",

        ]

        text_len = len(text.split())

        if text_len > 30:  # длинные запросы часто multi-step

            return True

        return any(re.search(p, text, re.IGNORECASE) for p in patterns)



    def process(self, text: str, source: str = "internal") -> str:

        """Главный метод: создать план и выполнить."""

        self._set_status(AgentStatus.RUNNING)

        try:

            # Декомпозировать цель

            plan = self.create_plan(text)

            if not plan.subtasks:

                return f"Не удалось создать план для: {text[:100]}"



            # Выполнить план

            result = self.execute_plan(plan)

            self._set_status(AgentStatus.IDLE)

            return result

        except Exception as e:

            self._set_status(AgentStatus.ERROR)

            self._log_failure("plan_execution", str(e))

            return f"❌ Ошибка планирования: {e}"



    def register_agents(self, agents: Dict[str, Any]) -> None:

        """Зарегистрировать агентов для выполнения задач."""

        self._agents = agents



    def set_brain_callback(self, cb: Callable) -> None:

        """Подключить brain callback для передачи задач через оркестратор."""

        self._brain_callback = cb



    # ── Декомпозиция цели ─────────────────────────────────────────────────────



    def create_plan(self, goal: str) -> ExecutionPlan:

        """Создать план выполнения из высокоуровневой цели."""

        plan = ExecutionPlan(goal=goal)

        log.info("PlannerAgent: creating plan for: %r", goal[:80])



        # LLM-based декомпозиция

        subtasks_raw = self._decompose_with_llm(goal)



        if not subtasks_raw:

            # Fallback: создать единственную задачу

            subtasks_raw = [{"title": goal, "agent": "chat", "description": goal}]



        # Создать объекты Subtask с приоритетами

        for i, raw in enumerate(subtasks_raw[:MAX_SUBTASKS]):

            task = Subtask(

                title=raw.get("title", f"Шаг {i+1}"),

                description=raw.get("description", raw.get("title", "")),

                agent_name=raw.get("agent", self._infer_agent(raw.get("title", ""))),

                depends_on=raw.get("depends_on", []),

                priority=raw.get("priority", i + 1),

            )

            # FIX: apply _id from parse so depends_on IDs match task.id
            if "_id" in raw:
                task.id = raw["_id"]
            plan.subtasks.append(task)



        # Сохранить план в MemoryStore

        self._save_plan(plan)



        # Публикуем событие

        self._bus.publish("planner.plan_created", {

            "plan_id": plan.plan_id,

            "goal": goal[:100],

            "subtask_count": len(plan.subtasks),

        }, source="planner")



        log.info("Plan created: %s (%d subtasks)", plan.plan_id, len(plan.subtasks))

        return plan



    def _decompose_with_llm(self, goal: str) -> List[Dict]:

        """Использовать LLM для декомпозиции цели на подзадачи."""

        system = (

            "Ты — эксперт по планированию задач. Декомпозируй цель на конкретные выполнимые подзадачи.\n\n"

            "Доступные агенты:\n"

            "- coder: написание/изменение кода\n"

            "- project_creator: создание структуры проекта\n"

            "- analyzer: анализ данных/требований\n"

            "- search: поиск информации в интернете\n"

            "- browser: Tor browser (BTC, ETH price, web search, news)\n"

            "- trading: Bybit bot (balance, orders, status)\n"

            "- code_runner: запуск и тестирование кода\n"

            "- summarizer: суммаризация текста\n"

            "- math: математические вычисления\n"

            "- chat: общий анализ и рассуждение\n\n"

            "Ответь строго в формате JSON-массива:\n"

            '[\n'

            '  {"title": "название шага", "agent": "имя_агента", '

            '"description": "что делать", "priority": 1, "depends_on": []},\n'

            '  ...\n'

            ']\n'

            f"Максимум {MAX_SUBTASKS} шагов. Порядок важен — зависимые задачи должны идти после своих предшественников.\n"

            "depends_on содержит индексы (0-based) предшествующих задач."

        )

        prompt = f"Декомпозируй эту цель на подзадачи:\n\n{goal}"



        try:

            raw_response = self._ask_llm(prompt, system=system, task_type="analysis")

            return self._parse_json_plan(raw_response)

        except Exception as e:

            log.warning("LLM decomposition failed: %s", e)

            return []



    def _parse_json_plan(self, text: str) -> List[Dict]:

        """Извлечь JSON-план из ответа LLM."""

        import json



        # Стратегия 1: Весь текст — валидный JSON

        try:

            data = json.loads(text.strip())

            if isinstance(data, list):

                pass  # продолжаем обработку ниже

            else:

                data = None

        except Exception:

            data = None



        # Стратегия 2: Найти JSON массив в тексте (GREEDY — берём самый длинный)

        if data is None:

            # Найти первый [ и последний ] для greedy match

            start = text.find('[')

            end   = text.rfind(']')

            if start != -1 and end > start:

                try:

                    data = json.loads(text[start:end+1])

                    if not isinstance(data, list):

                        data = None

                except Exception:

                    data = None



        if not data:

            return []



        try:

            if not isinstance(data, list):

                return []



            result = []

            id_map = {}  # индекс → id для depends_on



            for i, item in enumerate(data):

                if not isinstance(item, dict):

                    continue

                task_id = uuid.uuid4().hex[:8]

                id_map[i] = task_id

                # Конвертировать числовые зависимости в ID

                deps_raw = item.get("depends_on", [])

                deps = [id_map[d] for d in deps_raw if isinstance(d, int) and d in id_map]

                result.append({

                    "title":       item.get("title", f"Шаг {i+1}"),

                    "description": item.get("description", ""),

                    "agent":       item.get("agent", "chat"),

                    "priority":    item.get("priority", i + 1),

                    "depends_on":  deps,

                    "_id":         task_id,

                })



            # Обновить id задач (они уже UUID в объектах)

            return result

        except Exception as e:

            log.warning("JSON parse failed: %s", e)

            return []



    def _infer_agent(self, title: str) -> str:

        """Определить агента по названию задачи."""

        title_lower = title.lower()

        if any(w in title_lower for w in ["код", "code", "функция", "класс", "скрипт", "программ"]):

            return "coder"

        if any(w in title_lower for w in ["анализ", "analysis", "оценка", "исследова"]):

            return "analyzer"

        if any(w in title_lower for w in ["найди", "поиск", "search", "информация"]):

            return "search"

        if any(w in title_lower for w in ["тест", "test", "запусти", "выполни", "run"]):

            return "code_runner"

        if any(w in title_lower for w in ["проект", "project", "структура", "папки"]):

            return "project_creator"

        if any(w in title_lower for w in ["сумм", "кратко", "rezume", "summary"]):

            return "summarizer"

        if any(w in title_lower for w in ["посчитай", "вычисли", "матем", "math"]):

            return "math"

        if any(w in title_lower for w in ["цена", "price", "курс", "btc", "eth", "крипто", "bitcoin", "ethereum", "bybit"]):

            return "browser"

        if any(w in title_lower for w in ["открой", "browse", "страниц", "url", "http", "tor", "новости", "news"]):

            return "browser"

        if any(w in title_lower for w in ["торг", "trading", "баланс", "balance", "ордер", "позици"]):

            return "trading"

        return "chat"



    # ── Выполнение плана ──────────────────────────────────────────────────────



    def execute_plan(self, plan: ExecutionPlan,

                     progress_callback: Optional[Callable] = None) -> str:

        """Выполнить план с параллельным исполнением независимых задач."""

        with self._rlock:

            self._active_plans[plan.plan_id] = plan



        log.info("Executing plan %s (%d tasks)", plan.plan_id, len(plan.subtasks))



        def _progress(msg: str) -> None:

            if progress_callback:

                try:

                    progress_callback(msg)

                except Exception:

                    pass



        completed_results: Dict[str, str] = {}

        max_rounds = MAX_SUBTASKS + 2



        for round_num in range(max_rounds):

            ready = plan.get_ready_tasks()

            if not ready:

                if plan.is_complete:

                    break

                # Возможно deadlock — помечаем оставшиеся как skipped

                stuck = [t for t in plan.subtasks

                         if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]

                if stuck:

                    log.warning("Plan %s: %d tasks stuck, marking failed",

                                plan.plan_id, len(stuck))

                    for t in stuck:

                        t.status = TaskStatus.FAILED

                        t.error = t.error or "Stuck: no ready tasks and plan incomplete"

                break



            _progress(f"🔄 Выполняю шаг {round_num+1}: {', '.join(t.title[:20] for t in ready)}")



            # Параллельное выполнение готовых задач

            batch = ready[:MAX_PARALLEL]

            results = self._execute_batch(batch, completed_results, plan, _progress)

            completed_results.update(results)



        # Синтез финального результата

        plan.completed_at = time.time()

        final = self._synthesize_results(plan, completed_results)

        plan.final_result = final



        # Обновляем план в памяти

        self._save_plan_result(plan)



        # Публикуем завершение

        self._bus.publish("planner.plan_completed", {

            "plan_id": plan.plan_id,

            "success_rate": plan.success_rate,

            "duration_s": plan.completed_at - plan.created_at,

        }, source="planner")



        with self._rlock:

            self._active_plans.pop(plan.plan_id, None)



        return final



    def _execute_batch(self, tasks: List[Subtask],

                        prev_results: Dict[str, str],

                        plan: ExecutionPlan,

                        _progress: Callable) -> Dict[str, str]:

        """Выполнить batch задач (параллельно или последовательно)."""

        results = {}



        if len(tasks) == 1:

            t = tasks[0]

            result = self._execute_task(t, prev_results, plan)

            results[t.id] = result

            return results



        # Параллельное выполнение

        with concurrent.futures.ThreadPoolExecutor(

            max_workers=min(len(tasks), MAX_PARALLEL),

            thread_name_prefix="planner-exec"

        ) as pool:

            futures = {

                pool.submit(self._execute_task, t, prev_results, plan): t

                for t in tasks

            }

            try:

                for fut in concurrent.futures.as_completed(

                    futures, timeout=SUBTASK_TIMEOUT * max(1, min(len(futures), 3))

                ):

                    task = futures[fut]

                    try:

                        result = fut.result()  # as_completed() already enforces outer timeout

                        results[task.id] = result

                        _progress(f"  ✅ {task.title[:40]}: завершено")

                    except Exception as e:

                        results[task.id] = f"Ошибка: {e}"

                        task.error = str(e)

                        task.status = TaskStatus.FAILED

                        _progress(f"  ❌ {task.title[:40]}: {e}")

            except concurrent.futures.TimeoutError:

                for fut, task in futures.items():

                    if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):

                        task.status = TaskStatus.FAILED

                        task.error = f"Batch timeout ({SUBTASK_TIMEOUT * len(tasks)}s)"

                        results[task.id] = "Timeout"

                        log.warning("Batch timeout — task %s [%s]",

                                    task.id[:8], task.title[:30])



        return results



    def _execute_task(self, task: Subtask,

                       prev_results: Dict[str, str],

                       plan: ExecutionPlan) -> str:

        """Выполнить одну подзадачу через соответствующего агента."""

        task.status = TaskStatus.RUNNING

        task.started_at = time.time()



        # Обогатить запрос контекстом предыдущих результатов

        context_parts = []

        for dep_id in task.depends_on:

            if dep_id in prev_results:

                context_parts.append(f"Результат предшественника: {prev_results[dep_id][:200]}")



        full_query = task.description

        if context_parts:

            full_query = "\n".join(context_parts) + "\n\n" + full_query



        # Попытка выполнения с retry

        last_error = ""

        for attempt in range(2):

            try:

                result = self._dispatch_to_agent(task.agent_name, full_query)

                task.status = TaskStatus.DONE

                task.result = result[:500]

                task.completed_at = time.time()

                log.debug("Task %s done: %r", task.id, result[:60])

                return result

            except Exception as e:

                last_error = str(e)

                task.retry_count += 1

                log.warning("Task %s attempt %d failed: %s", task.id, attempt+1, e)

                time.sleep(1)



        task.status = TaskStatus.FAILED

        task.error = last_error

        task.completed_at = time.time()

        return f"Ошибка после {task.retry_count} попыток: {last_error}"



    def _dispatch_to_agent(self, agent_name: str, query: str) -> str:

        """Отправить запрос агенту или LLM напрямую.

        

        NOTE: НЕ используем brain_callback здесь — это вызывает реентрантную блокировку

        (brain → planner → brain → deadlock). Subtasks всегда идут через LLM напрямую.

        """

        # Попробовать через registered agents (только light-weight агенты, не brain)

        agent = self._agents.get(agent_name)

        if agent and hasattr(agent, "process") and agent_name not in (

            "planner", "telegram"  # Only skip recursive planner + telegram (would block)

        ):

            try:

                return agent.process(query, source="planner")

            except Exception as e:

                log.warning("Agent %s failed: %s, falling back to LLM", agent_name, e)



        # Прямой LLM (без реентрантного brain callback)

        return self._ask_llm(query)



    # ── Синтез результатов ────────────────────────────────────────────────────



    def _synthesize_results(self, plan: ExecutionPlan,

                              results: Dict[str, str]) -> str:

        """Синтезировать финальный результат из всех подзадач."""

        if not results:

            return f"План {plan.plan_id} выполнен без результатов."



        done_tasks = [t for t in plan.subtasks if t.status == TaskStatus.DONE]

        failed_tasks = [t for t in plan.subtasks if t.status == TaskStatus.FAILED]



        if len(done_tasks) == 0:

            return f"❌ Все {len(plan.subtasks)} задач завершились ошибкой."



        # Краткий отчёт

        header = (

            f"✅ **Plan Complete** ({len(done_tasks)}/{len(plan.subtasks)} tasks)\n"

            f"Goal: {plan.goal[:100]}\n\n"

        )



        # Синтез через LLM если есть несколько результатов

        if len(done_tasks) > 1 and self._brain_callback:

            results_text = "\n\n".join(

                f"### {t.title}\n{results.get(t.id, '')[:500]}"

                for t in done_tasks

            )

            system = "Синтезируй результаты выполненных задач в единый связный ответ."

            prompt = (

                f"Цель: {plan.goal}\n\n"

                f"Результаты задач:\n{results_text[:3000]}\n\n"

                f"Дай итоговый связный ответ:"

            )

            try:

                synthesis = self._ask_llm(prompt, system=system, task_type="analysis")

                if len(synthesis) > 100:

                    return header + synthesis

            except Exception:

                pass



        # Fallback: конкатенация результатов

        parts = [header]

        for task in done_tasks:

            r = results.get(task.id, "")

            if r:

                parts.append(f"**{task.title}**\n{r[:400]}")

        if failed_tasks:

            parts.append(f"\n⚠️ Не выполнено: {', '.join(t.title for t in failed_tasks)}")



        return "\n\n".join(parts)



    # ── Персистентность ───────────────────────────────────────────────────────



    def _save_plan(self, plan: ExecutionPlan) -> None:

        """Сохранить план в MemoryStore."""

        try:

            import json

            self._memory.add_knowledge(KnowledgeEntry(

                category="context",

                title=f"Plan {plan.plan_id}: {plan.goal[:60]}",

                content=json.dumps({

                    "plan_id": plan.plan_id,

                    "goal": plan.goal,

                    "subtasks": [

                        {"id": t.id, "title": t.title, "agent": t.agent_name}

                        for t in plan.subtasks

                    ],

                }, ensure_ascii=False),

                tags=["plan", "execution"],

                importance=0.6,

                source="planner",

            ))

        except Exception as e:

            log.debug("Save plan failed: %s", e)



    def _save_plan_result(self, plan: ExecutionPlan) -> None:

        """Сохранить результат плана для обучения."""

        try:

            title = f"[PLAN RESULT] {plan.goal[:60]}"

            if not self._memory.knowledge_exists(title[:40]):

                self._memory.add_knowledge(KnowledgeEntry(

                    category="solution",

                    title=title,

                    content=(

                        f"Goal: {plan.goal}\n"

                        f"Success rate: {plan.success_rate:.1%}\n"

                        f"Tasks: {len(plan.subtasks)}\n"

                        f"Result: {plan.final_result[:600]}"

                    ),

                    tags=["plan", "result", "autonomous"],

                    importance=0.7,

                    source="planner",

                ))

        except Exception as e:

            log.debug("Save plan result failed: %s", e)



    # ── Status API ────────────────────────────────────────────────────────────



    def get_active_plans(self) -> List[Dict]:

        with self._rlock:

            return [

                {"plan_id": p.plan_id, "goal": p.goal[:60],

                 "progress": f"{sum(1 for t in p.subtasks if t.status == TaskStatus.DONE)}/{len(p.subtasks)}"}

                for p in self._active_plans.values()

            ]



    @staticmethod

    def should_plan(text: str) -> bool:

        """Стоит ли использовать PlannerAgent для этого запроса?"""

        # Сначала проверяем паттерны сложности (независимо от длины)

        complex_patterns = [

            # Russian

            r"(создай|разработай|построй|реализуй).{10,}",

            r"(и|затем|потом|после этого).{5,}(и|затем|потом)",

            r"пошаговый|по шагам|поэтапно",

            r"(тест|документация|деплой).{5,}(тест|документация|деплой)",

            r"(полностью|целиком|с нуля)",

            r"pipeline|workflow|автоматизация",

            r"с тестами|с документацией|и задеплой",

            # English

            r"(create|build|develop|implement).{10,}",

            r"(with tests|with documentation|and deploy|end.to.end)",

            r"step.by.step|step by step",

            r"(full|complete|entire|from scratch).{5,}",

            r"microservice|architecture|infrastructure",

        ]

        if any(re.search(p, text, re.IGNORECASE) for p in complex_patterns):

            return True

        # Длинные запросы тоже планируем

        words = len(text.split())

        return words >= PLANNING_THRESHOLD_WORDS

