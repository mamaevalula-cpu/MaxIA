# -*- coding: utf-8 -*-
"""
core/event_bus.py — Внутренняя шина событий (publish/subscribe).

Компоненты общаются ТОЛЬКО через EventBus — никакого прямого вызова.
Потокобезопасна. Поддерживает синхронные и async обработчики.

Пример:
    bus = EventBus.get()
    bus.subscribe("trading.signal", my_handler)
    bus.publish("trading.signal", {"symbol": "BTCUSDT", "side": "buy"})
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

log = logging.getLogger("core.event_bus")


@dataclass
class Event:
    topic:      str
    payload:    Any
    source:     str           = "unknown"
    event_id:   str           = field(default_factory=lambda: uuid4().hex[:8])
    timestamp:  float         = field(default_factory=time.time)


class EventBus:
    """
    Синглтон-шина событий.

    Topics (рекомендуемые):
        brain.task          — задача для мозга
        brain.result        — результат мозга
        agent.status        — статус агента {name, status, message}
        agent.task          — задача для конкретного агента {agent, task}
        trading.signal      — торговый сигнал
        trading.status      — статус торговли
        memory.save         — сохранить в память
        memory.query        — запрос к памяти
        gui.update          — обновить GUI {widget, data}
        gui.chat            — сообщение в чат {role, text}
        auth.request        — запрос авторизации {service}
        project.created     — новый проект создан
        system.shutdown     — завершение работы
    """

    _instance: Optional["EventBus"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)
        self._history: List[Event] = []
        self._max_history = 500
        self._rlock = threading.RLock()

    @classmethod
    def get(cls) -> "EventBus":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Подписка ──────────────────────────────────────────────────────────────

    def subscribe(self, topic: str, handler: Callable, once: bool = False) -> None:
        """
        Подписаться на тему.
        handler может быть sync или async функцией.
        once=True — обработчик удаляется после первого вызова.
        """
        with self._rlock:
            if once:
                original = handler
                def _once_wrapper(event: Event):
                    self.unsubscribe(topic, _once_wrapper)
                    return original(event)
                _once_wrapper.__name__ = getattr(handler, "__name__", "once_handler")
                self._subscribers[topic].append(_once_wrapper)
            else:
                self._subscribers[topic].append(handler)
        log.debug("Subscribed %s → %s", getattr(handler, '__name__', str(handler)), topic)

    def unsubscribe(self, topic: str, handler: Callable) -> None:
        with self._rlock:
            subs = self._subscribers.get(topic, [])
            self._subscribers[topic] = [h for h in subs if h is not handler]

    def subscribe_all(self, handler: Callable) -> None:
        """Подписаться на ВСЕ события (wildcard)."""
        self.subscribe("*", handler)

    # ── Публикация ────────────────────────────────────────────────────────────

    def publish(self, topic: str, payload: Any = None, source: str = "unknown") -> str:
        """
        Опубликовать событие синхронно.
        Возвращает event_id.
        """
        event = Event(topic=topic, payload=payload, source=source)
        self._store(event)

        with self._rlock:
            handlers = list(self._subscribers.get(topic, []))
            handlers += list(self._subscribers.get("*", []))

        for h in handlers:
            try:
                if inspect.iscoroutinefunction(h):
                    # Async-обработчики вызываем через asyncio если есть loop
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(h(event))
                    except RuntimeError:
                        asyncio.run(h(event))
                else:
                    h(event)
            except Exception as exc:
                log.error("Handler %s failed for topic %s: %s",
                          getattr(h, '__name__', str(h)), topic, exc, exc_info=True)

        return event.event_id

    async def publish_async(self, topic: str, payload: Any = None, source: str = "unknown") -> str:
        """Async-версия publish."""
        event = Event(topic=topic, payload=payload, source=source)
        self._store(event)

        with self._rlock:
            handlers = list(self._subscribers.get(topic, []))
            handlers += list(self._subscribers.get("*", []))

        for h in handlers:
            try:
                if inspect.iscoroutinefunction(h):
                    await h(event)
                else:
                    h(event)
            except Exception as exc:
                log.error("Async handler %s failed: %s",
                          getattr(h, '__name__', str(h)), exc, exc_info=True)

        return event.event_id

    # ── История ───────────────────────────────────────────────────────────────

    def _store(self, event: Event) -> None:
        with self._rlock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

    def get_history(self, topic: Optional[str] = None, limit: int = 50) -> List[Event]:
        with self._rlock:
            history = self._history if topic is None else [
                e for e in self._history if e.topic == topic
            ]
            return history[-limit:]

    def clear_history(self) -> None:
        with self._rlock:
            self._history.clear()

    # ── Диагностика ───────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        with self._rlock:
            return {
                "topics": list(self._subscribers.keys()),
                "subscribers": {t: len(h) for t, h in self._subscribers.items()},
                "history_size": len(self._history),
            }
