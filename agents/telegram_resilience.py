# -*- coding: utf-8 -*-
"""
agents/telegram_resilience.py — Отказоустойчивость Telegram-агента.

Компоненты:
  • TelegramRetrySender  — tenacity-обёртка для send_message/send_photo
  • MessageQueue         — очередь при недоступности AI или перегрузке
  • ConnectionGuard      — автоматический reconnect при потере связи
  • ResilientBot         — полная обёртка, объединяет три компонента

Использование:
    from agents.telegram_resilience import ResilientBot
    bot = ResilientBot(raw_send_fn=bot.send_message)
    await bot.send(chat_id, text)          # с ретраями
    bot.enqueue(chat_id, text, priority=1) # в очередь
"""

from __future__ import annotations

import asyncio
import logging
import queue
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

log = logging.getLogger("telegram.resilience")

# ── Попытка импорта tenacity ──────────────────────────────────────────────────

try:
    from tenacity import (
        AsyncRetrying,
        RetryError,
        retry,
        retry_if_exception_type,
        stop_after_attempt,
        wait_exponential,
        wait_random,
        before_sleep_log,
    )
    _TENACITY_OK = True
except ImportError:
    _TENACITY_OK = False
    log.warning("tenacity not installed — basic retry only. pip install tenacity")


# ── Константы ─────────────────────────────────────────────────────────────────

MAX_RETRIES        = 7           # максимальных попыток
RETRY_MIN_WAIT     = 1.0         # секунд минимум между попытками
RETRY_MAX_WAIT     = 120.0       # секунд максимум
RETRY_JITTER       = 2.0         # секунд случайного jitter
QUEUE_MAX_SIZE     = 500         # максимум сообщений в очереди
QUEUE_DRAIN_DELAY  = 0.15        # секунд между отправками из очереди
DEAD_LETTER_LIMIT  = 100         # сообщений в dead-letter хранилище


# ── Исключения ────────────────────────────────────────────────────────────────

class TelegramRateLimitError(Exception):
    """429 Too Many Requests."""
    def __init__(self, retry_after: float = 30.0):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after}s")


class TelegramNetworkError(Exception):
    """Сетевая ошибка или timeout."""


class TelegramFatalError(Exception):
    """Неисправимая ошибка (400 Bad Request, невалидный chat_id и т.д.)."""


# ── Очереди сообщений ─────────────────────────────────────────────────────────

@dataclass(order=True)
class QueuedMessage:
    """Сообщение в очереди с приоритетом."""
    priority:   int              # 0 = высший, 9 = низший
    created_at: float = field(default_factory=time.time, compare=False)
    chat_id:    Any    = field(default=None, compare=False)
    text:       str    = field(default="", compare=False)
    kwargs:     Dict   = field(default_factory=dict, compare=False)
    attempts:   int    = field(default=0, compare=False)

    def age_sec(self) -> float:
        return time.time() - self.created_at


class MessageQueue:
    """
    Приоритетная очередь Telegram-сообщений.
    Используется когда AI занят или соединение временно недоступно.
    """

    def __init__(self, max_size: int = QUEUE_MAX_SIZE) -> None:
        self._q: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_size)
        self._dead_letters: List[QueuedMessage] = []
        self._sent_count   = 0
        self._failed_count = 0
        self._lock         = threading.Lock()

    def put(self, chat_id: Any, text: str, priority: int = 5, **kwargs) -> bool:
        """Добавить сообщение. Возвращает False если очередь заполнена."""
        msg = QueuedMessage(priority=priority, chat_id=chat_id, text=text, kwargs=kwargs)
        try:
            self._q.put_nowait(msg)
            return True
        except queue.Full:
            log.warning("Message queue full (%d), dropping message to %s", QUEUE_MAX_SIZE, chat_id)
            with self._lock:
                self._dead_letters.append(msg)
                if len(self._dead_letters) > DEAD_LETTER_LIMIT:
                    self._dead_letters = self._dead_letters[-DEAD_LETTER_LIMIT:]
            return False

    def get(self, timeout: float = 1.0) -> Optional[QueuedMessage]:
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "queued":       self._q.qsize(),
                "sent":         self._sent_count,
                "failed":       self._failed_count,
                "dead_letters": len(self._dead_letters),
            }

    def mark_sent(self) -> None:
        with self._lock:
            self._sent_count += 1

    def mark_failed(self) -> None:
        with self._lock:
            self._failed_count += 1


# ── Retry sender ──────────────────────────────────────────────────────────────

class TelegramRetrySender:
    """
    Обёртка над async send_message с tenacity exponential backoff + jitter.
    Handles: NetworkError, RateLimitError, transient 5xx.
    Does NOT retry: 400 Bad Request, invalid chat_id (TelegramFatalError).
    """

    def __init__(
        self,
        send_fn: Callable[..., Coroutine],
        max_retries: int = MAX_RETRIES,
        min_wait:    float = RETRY_MIN_WAIT,
        max_wait:    float = RETRY_MAX_WAIT,
        jitter:      float = RETRY_JITTER,
    ) -> None:
        self._send_fn    = send_fn
        self._max_retries = max_retries
        self._min_wait   = min_wait
        self._max_wait   = max_wait
        self._jitter     = jitter

    async def send(self, *args, **kwargs) -> Any:
        """Отправить с автоматическим повтором."""
        if _TENACITY_OK:
            return await self._send_with_tenacity(*args, **kwargs)
        return await self._send_basic(*args, **kwargs)

    async def _send_with_tenacity(self, *args, **kwargs) -> Any:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type((TelegramNetworkError, TelegramRateLimitError)),
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=1, min=self._min_wait, max=self._max_wait)
              + wait_random(0, self._jitter),
            before_sleep=before_sleep_log(log, logging.WARNING),
            reraise=False,
        ):
            with attempt:
                try:
                    return await self._send_fn(*args, **kwargs)
                except TelegramRateLimitError as e:
                    # Respect Retry-After header
                    wait = min(e.retry_after + random.uniform(0, 2), self._max_wait)
                    log.warning("Rate limited — sleeping %.1fs", wait)
                    await asyncio.sleep(wait)
                    raise  # tenacity will retry
                except TelegramFatalError:
                    raise  # не повторяем 400/chat-not-found
                except Exception as e:
                    raise TelegramNetworkError(str(e)) from e

    async def _send_basic(self, *args, **kwargs) -> Any:
        """Fallback без tenacity: простой exponential backoff."""
        last_err: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                return await self._send_fn(*args, **kwargs)
            except TelegramFatalError:
                raise
            except Exception as e:
                last_err = e
                delay = min(self._min_wait * (2 ** attempt) + random.uniform(0, self._jitter),
                            self._max_wait)
                log.warning("Send failed (attempt %d/%d): %s — retry in %.1fs",
                            attempt + 1, self._max_retries, e, delay)
                await asyncio.sleep(delay)
        raise TelegramNetworkError(f"All {self._max_retries} attempts failed") from last_err


# ── Connection Guard ──────────────────────────────────────────────────────────

class ConnectionGuard:
    """
    Мониторит health Telegram-соединения.
    При потере — пытается переподключиться с exponential backoff.
    """

    _RECONNECT_DELAYS = [5, 15, 30, 60, 120, 300, 600]

    def __init__(
        self,
        reconnect_fn: Callable[[], Any],
        health_check_fn: Optional[Callable[[], bool]] = None,
        alert_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._reconnect_fn   = reconnect_fn
        self._health_check   = health_check_fn
        self._alert          = alert_fn
        self._connected      = False
        self._reconnect_idx  = 0
        self._last_ping      = 0.0
        self._lock           = threading.Lock()
        self._stop_event     = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="tg-conn-guard")
        self._thread.start()
        log.debug("ConnectionGuard started")

    def stop(self) -> None:
        self._stop_event.set()

    def mark_connected(self) -> None:
        with self._lock:
            self._connected = True
            self._reconnect_idx = 0
            self._last_ping = time.time()

    def mark_disconnected(self) -> None:
        with self._lock:
            self._connected = False

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                if not self.is_connected:
                    self._attempt_reconnect()
                elif self._health_check and time.time() - self._last_ping > 60:
                    ok = self._run_health_check()
                    if not ok:
                        log.warning("Health check failed — marking disconnected")
                        self.mark_disconnected()
            except Exception as e:
                log.error("ConnectionGuard loop error: %s", e)
            self._stop_event.wait(10)

    def _attempt_reconnect(self) -> None:
        idx = min(self._reconnect_idx, len(self._RECONNECT_DELAYS) - 1)
        delay = self._RECONNECT_DELAYS[idx]
        log.info("Telegram reconnect attempt %d (delay=%ds)", self._reconnect_idx + 1, delay)
        time.sleep(delay)
        try:
            self._reconnect_fn()
            self.mark_connected()
            log.info("Telegram reconnected successfully")
            if self._alert:
                self._alert("✅ Telegram reconnected")
        except Exception as e:
            log.warning("Reconnect failed: %s", e)
            with self._lock:
                self._reconnect_idx = min(self._reconnect_idx + 1, len(self._RECONNECT_DELAYS))
            if self._reconnect_idx >= 3 and self._alert:
                self._alert(f"⚠️ Telegram offline (attempt {self._reconnect_idx}): {e}")

    def _run_health_check(self) -> bool:
        try:
            result = self._health_check()
            with self._lock:
                self._last_ping = time.time()
            return bool(result)
        except Exception as e:
            log.debug("Health check exception: %s", e)
            return False


# ── Resilient Bot ─────────────────────────────────────────────────────────────

class ResilientBot:
    """
    Полная отказоустойчивая обёртка для Telegram-бота.

    Объединяет:
      • TelegramRetrySender — повторы с exponential backoff + jitter
      • MessageQueue        — буфер при недоступности
      • ConnectionGuard     — автоматический reconnect

    Использование:
        resilient = ResilientBot(send_fn=bot.send_message)
        resilient.start_queue_drainer(event_loop)

        # Из async context:
        await resilient.send(chat_id, "текст")

        # Из sync context (добавить в очередь):
        resilient.enqueue(chat_id, "текст", priority=3)
    """

    def __init__(
        self,
        send_fn: Optional[Callable] = None,
        reconnect_fn: Optional[Callable] = None,
        health_check_fn: Optional[Callable[[], bool]] = None,
        alert_fn: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._queue  = MessageQueue()
        self._sender = TelegramRetrySender(send_fn) if send_fn else None
        self._guard  = ConnectionGuard(
            reconnect_fn   = reconnect_fn   or (lambda: None),
            health_check_fn= health_check_fn,
            alert_fn       = alert_fn,
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._drainer: Optional[threading.Thread] = None
        self._running = False

    def set_send_fn(self, fn: Callable) -> None:
        self._sender = TelegramRetrySender(fn)

    def start_queue_drainer(self, loop: asyncio.AbstractEventLoop) -> None:
        """Запустить фоновый поток для опустошения очереди."""
        self._loop    = loop
        self._running = True
        self._guard.start()
        self._drainer = threading.Thread(target=self._drain_loop, daemon=True,
                                         name="tg-queue-drainer")
        self._drainer.start()
        log.info("ResilientBot queue drainer started")

    def stop(self) -> None:
        self._running = False
        self._guard.stop()

    def mark_connected(self) -> None:
        self._guard.mark_connected()

    def mark_disconnected(self) -> None:
        self._guard.mark_disconnected()

    # ── Async send ────────────────────────────────────────────────────────────

    async def send(self, chat_id: Any, text: str, **kwargs) -> bool:
        """Отправить с ретраями. Возвращает True при успехе."""
        if not self._sender:
            log.error("ResilientBot: send_fn not set")
            return False
        try:
            await self._sender.send(chat_id=chat_id, text=text, **kwargs)
            self._queue.mark_sent()
            return True
        except TelegramFatalError as e:
            log.error("Fatal Telegram error for chat %s: %s", chat_id, e)
            self._queue.mark_failed()
            return False
        except Exception as e:
            log.warning("send() failed after all retries: %s — enqueuing", e)
            self.enqueue(chat_id, text, priority=2, **kwargs)
            return False

    async def send_safe(self, chat_id: Any, text: str, **kwargs) -> bool:
        """Никогда не бросает исключение."""
        try:
            return await self.send(chat_id, text, **kwargs)
        except Exception as e:
            log.error("send_safe swallowed error: %s", e)
            return False

    # ── Sync enqueue ─────────────────────────────────────────────────────────

    def enqueue(self, chat_id: Any, text: str, priority: int = 5, **kwargs) -> bool:
        """Добавить в очередь (thread-safe, sync)."""
        ok = self._queue.put(chat_id, text, priority=priority, **kwargs)
        if not ok:
            log.warning("Queue full — message to %s dropped", chat_id)
        return ok

    # ── Queue drainer (background thread) ────────────────────────────────────

    def _drain_loop(self) -> None:
        """Фоновый поток: вытягивает сообщения из очереди и отправляет."""
        while self._running:
            msg = self._queue.get(timeout=1.0)
            if msg is None:
                continue
            try:
                if self._sender and self._loop and self._loop.is_running():
                    fut = asyncio.run_coroutine_threadsafe(
                        self.send(msg.chat_id, msg.text, **msg.kwargs),
                        self._loop,
                    )
                    try:
                        result = fut.result(timeout=35.0)
                        if result:
                            self._queue.task_done()
                        else:
                            # re-queue with lower priority if not fatal
                            msg.attempts += 1
                            if msg.attempts < 3:
                                self._queue.put(msg.chat_id, msg.text,
                                               priority=min(msg.priority + 1, 9),
                                               **msg.kwargs)
                            self._queue.task_done()
                    except Exception as e:
                        log.warning("Drainer future error: %s", e)
                        self._queue.task_done()
                else:
                    # Loop not available — re-enqueue
                    self._queue.put(msg.chat_id, msg.text,
                                   priority=msg.priority, **msg.kwargs)
                    self._queue.task_done()
                    time.sleep(2.0)
            except Exception as e:
                log.error("Drainer error: %s", e)
                try:
                    self._queue.task_done()
                except Exception:
                    pass
            time.sleep(QUEUE_DRAIN_DELAY)

    # ── Stats ─────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict:
        return {
            "connected": self._guard.is_connected,
            "queue":     self._queue.stats,
        }


# ── Декоратор для отдельных методов TelegramAgent ─────────────────────────────

def telegram_retry(
    max_attempts: int = MAX_RETRIES,
    min_wait:     float = RETRY_MIN_WAIT,
    max_wait:     float = RETRY_MAX_WAIT,
):
    """
    Decorator: оборачивает async метод в retry с exponential backoff.

    Применяется к методам TelegramAgent, которые вызывают Telegram API:
        @telegram_retry(max_attempts=5)
        async def _send_reply(self, update, text):
            await update.message.reply_text(text)
    """
    def decorator(fn):
        async def wrapper(*args, **kwargs):
            if _TENACITY_OK:
                async for attempt in AsyncRetrying(
                    retry=retry_if_exception_type(Exception),
                    stop=stop_after_attempt(max_attempts),
                    wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait)
                       + wait_random(0, RETRY_JITTER),
                    before_sleep=before_sleep_log(log, logging.WARNING),
                    reraise=True,
                ):
                    with attempt:
                        return await fn(*args, **kwargs)
            else:
                last = None
                for i in range(max_attempts):
                    try:
                        return await fn(*args, **kwargs)
                    except Exception as e:
                        last = e
                        delay = min(min_wait * (2 ** i) + random.uniform(0, RETRY_JITTER), max_wait)
                        await asyncio.sleep(delay)
                raise last
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


# ── Хелпер для классификации ошибок Telegram ─────────────────────────────────

def classify_telegram_error(exc: Exception) -> type:
    """
    Определить тип ошибки по исключению python-telegram-bot.
    Возвращает TelegramRateLimitError / TelegramFatalError / TelegramNetworkError.
    """
    err_str = str(exc).lower()
    # 429
    if "429" in err_str or "too many requests" in err_str or "flood" in err_str:
        retry_after = 30.0
        import re
        m = re.search(r"retry.{0,10}(\d+)", err_str)
        if m:
            retry_after = float(m.group(1))
        return TelegramRateLimitError(retry_after)

    # Fatal: bad request, chat not found, bot blocked
    fatal_patterns = ["400", "bad request", "chat not found",
                      "bot was blocked", "user is deactivated", "forbidden"]
    if any(p in err_str for p in fatal_patterns):
        return TelegramFatalError(str(exc))

    # Network / timeout
    return TelegramNetworkError(str(exc))


# ── Глобальный singleton ──────────────────────────────────────────────────────

_resilient_bot: Optional[ResilientBot] = None


def get_resilient_bot() -> ResilientBot:
    global _resilient_bot
    if _resilient_bot is None:
        _resilient_bot = ResilientBot()
    return _resilient_bot
