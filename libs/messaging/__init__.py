#!/usr/bin/env python3
"""Ephemera

Разработать router-service (взвешенный подбор агента через scoring-engine), validator-service (проверка результатов, логика ретраев), auditor-service (анализ отказов, генерация кандидатов на улучшение), scaler-service (мониторинг глубины очереди RabbitMQ, триггеры для KEDA/HPA).
"""

import pika
from typing import Callable, Any

QUEUES = {
    "router": "ephemera.router",
    "validator": "ephemera.validator",
    "auditor": "ephemera.auditor",
    "scaler": "ephemera.scaler",
}

class EphemeralProducer:
    """Эфемерный продюсер для отправки сообщений в очереди."""

    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=queue_name, durable=False, auto_delete=True)

    def publish(self, message: str) -> None:
        """Отправить сообщение в очередь."""
        self.channel.basic_publish(exchange="", routing_key=self.queue_name, body=message.encode())

    def close(self) -> None:
        """Закрыть соединение."""
        self.connection.close()

class EphemeralConsumer:
    """Эфемерный консьюмер для получения сообщений из очереди."""

    def __init__(self, queue_name: str, callback: Callable[[str], Any]):
        self.queue_name = queue_name
        self.callback = callback
        self.connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue=queue_name, durable=False, auto_delete=True)
        self.channel.basic_consume(queue=queue_name, on_message_callback=self._callback_wrapper, auto_ack=True)

    def _callback_wrapper(self, ch: Any, method: Any, properties: Any, body: bytes) -> None:
        """Обертка для вызова callback с декодированным телом."""
        self.callback(body.decode())

    def start_consuming(self) -> None:
        """Начать потребление сообщений."""
        self.channel.start_consuming()

    def close(self) -> None:
        """Закрыть соединение."""
        self.channel.stop_consuming()
        self.connection.close()

def create_producers() -> dict:
    """Создать эфемерных продюсеров для всех четырех очередей."""
    return {name: EphemeralProducer(queue) for name, queue in QUEUES.items()}

def create_consumers(callbacks: dict[str, Callable[[str], Any]]) -> dict:
    """Создать эфемерных консьюмеров для всех очередей с заданными колбэками."""
    return {name: EphemeralConsumer(QUEUES[name], callbacks[name]) for name in QUEUES}

__all__ = ["EphemeralProducer", "EphemeralConsumer", "create_producers", "create_consumers", "QUEUES"]