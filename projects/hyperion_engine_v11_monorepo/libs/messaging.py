"""
libs/messaging.py  —  Lightweight in-process pub/sub message bus for Корпорация MaxAI v11.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    topic: str
    payload: Dict[str, Any]
    msg_id: str = field(default_factory=lambda: f"msg-{int(time.time()*1000)}")
    ts: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Message":
        return cls(**json.loads(raw))


Handler = Callable[[Message], Coroutine[Any, Any, None]]


class MessageBus:
    """Async pub/sub bus with topic-based subscriptions."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[Handler]] = defaultdict(list)
        self._queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=1000)
        self._running = False

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscribers[topic].append(handler)
        logger.debug("Subscribed handler %s to topic %s", handler.__name__, topic)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        try:
            self._subscribers[topic].remove(handler)
        except ValueError:
            pass

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        msg = Message(topic=topic, payload=payload)
        await self._queue.put(msg)
        logger.debug("Published to %s: %s", topic, msg.msg_id)

    async def start(self) -> None:
        self._running = True
        logger.info("MessageBus started")
        while self._running:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            handlers = self._subscribers.get(msg.topic, [])
            if not handlers:
                continue
            results = await asyncio.gather(
                *[h(msg) for h in handlers], return_exceptions=True
            )
            for r in results:
                if isinstance(r, Exception):
                    logger.error("Handler error on topic %s: %s", msg.topic, r)

    def stop(self) -> None:
        self._running = False
        logger.info("MessageBus stopped")


# Global singleton bus
bus = MessageBus()
