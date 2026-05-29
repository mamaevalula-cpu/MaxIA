# -*- coding: utf-8 -*-
"""
agents/base_agent.py — Базовый класс для всех агентов системы.

Каждый агент:
  • Имеет имя, описание и список возможностей
  • Может быть запущен/остановлен
  • Публикует статус в EventBus
  • Сохраняет результаты в MemoryStore
  • Использует LLMRouter для AI-задач
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from brain.llm_router import LLMRequest, LLMRouter
from core.config import cfg
from core.event_bus import EventBus
from memory.memory_store import MemoryStore

log = logging.getLogger("agents.base")


class AgentStatus(str, Enum):
    IDLE     = "idle"
    RUNNING  = "running"
    WAITING  = "waiting"   # ожидание токенов / ресурсов
    ERROR    = "error"
    STOPPED  = "stopped"


@dataclass
class AgentInfo:
    name: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    version: str = "1.0.0"


class BaseAgent(ABC):
    """
    Базовый класс агента.

    Подклассы должны реализовать:
      • can_handle(text) — может ли агент обработать этот запрос
      • process(text, source) — обработать запрос, вернуть строку ответа
      • info() — вернуть AgentInfo
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._status = AgentStatus.IDLE
        self._llm = LLMRouter.get()
        self._memory = MemoryStore.get()
        self._bus = EventBus.get()
        self._rlock = threading.RLock()
        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._error_count = 0
        self._success_count = 0
        self._log = logging.getLogger(f"agents.{name}")

    # ── Абстрактные методы ────────────────────────────────────────────────────

    @abstractmethod
    def can_handle(self, text: str) -> bool:
        """Может ли агент обработать этот текст?"""

    @abstractmethod
    def process(self, text: str, source: str = "internal") -> str:
        """Обработать текст. Вернуть строку ответа."""

    @abstractmethod
    def info(self) -> AgentInfo:
        """Метаинформация об агенте."""

    # ── Жизненный цикл ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Запустить фоновую активность агента (если есть)."""
        self._stop_event.clear()
        self._set_status(AgentStatus.IDLE)
        self._log.info("Agent started")

    def stop(self) -> None:
        """Остановить агента."""
        self._stop_event.set()
        self._set_status(AgentStatus.STOPPED)
        self._log.info("Agent stopped")

    def is_running(self) -> bool:
        return self._status not in (AgentStatus.STOPPED, AgentStatus.ERROR)

    # ── Статус ────────────────────────────────────────────────────────────────

    def get_status(self) -> str:
        return self._status.value

    def _set_status(self, status: AgentStatus, message: str = "") -> None:
        with self._rlock:
            self._status = status
        self._bus.publish("agent.status", {
            "name": self.name,
            "status": status.value,
            "message": message,
        }, source=self.name)

    # ── LLM helpers ───────────────────────────────────────────────────────────

    def _ask_llm(self, prompt: str, system: str = "",
                 task_type: str = "general",
                 require_quality: bool = False) -> str:
        """Удобный метод для запроса к LLM."""
        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            task_type=task_type,
            require_quality=require_quality,
            max_tokens=3000,
        )
        resp = self._llm.ask(req)
        if not resp.success:
            return f"⚠️ LLM недоступен: {resp.error}"
        return resp.content

    # ── Логирование в память ──────────────────────────────────────────────────

    def _log_success(self, action: str, details: str = "") -> None:
        self._success_count += 1
        self._memory.log_agent(self.name, action, details, success=True)

    def _log_failure(self, action: str, error: str = "") -> None:
        """Логировать ошибку + сохранить в knowledge base для обучения."""
        self._error_count += 1
        self._memory.log_agent(self.name, action, error, success=False)
        # Сохраняем в knowledge для анализа SelfTrainingAgent
        if error and len(error) > 10:
            try:
                from memory.memory_store import KnowledgeEntry
                title = f"{self.name}: {action[:40]}"
                # Не дублируем одинаковые ошибки
                if not self._memory.knowledge_exists(title[:30], category="error"):
                    entry = KnowledgeEntry(
                        category="error",
                        title=title,
                        content=f"Агент: {self.name}\nДействие: {action}\nОшибка: {error}",
                        tags=["error", self.name, action[:20]],
                        importance=0.8,  # ошибки важны для обучения
                        source=self.name,
                    )
                    self._memory.add_knowledge(entry)
            except Exception:
                pass  # не мешаем основному логированию

    # ── Фоновый поток ─────────────────────────────────────────────────────────

    def _run_background(self, fn: Callable, interval: float = 60.0) -> None:
        """
        Запустить функцию fn в фоновом потоке с повторением каждые interval секунд.
        Останавливается при вызове stop().
        """
        def _loop():
            while not self._stop_event.is_set():
                try:
                    self._set_status(AgentStatus.RUNNING)
                    fn()
                    self._set_status(AgentStatus.IDLE)
                except Exception as e:
                    self._log.error("Background error: %s", e, exc_info=True)
                    self._log_failure("background_loop", str(e))
                    self._set_status(AgentStatus.ERROR)
                finally:
                    self._stop_event.wait(interval)

        self._background_thread = threading.Thread(
            target=_loop, name=f"agent-{self.name}", daemon=True
        )
        self._background_thread.start()

    # ── Представление ─────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        info = self.info()
        return (
            f"<{self.__class__.__name__} name={self.name!r} "
            f"status={self._status.value} "
            f"success={self._success_count} errors={self._error_count}>"
        )
