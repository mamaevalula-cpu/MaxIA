#!/usr/bin/env python3
"""
RabbitMQ configuration for hyperion.v12.1.
Defines exchanges, queues, DLQ, and FastAPI integration via aio-pika.
"""

import asyncio
import logging
from typing import Dict, Optional

import aio_pika
from aio_pika import Exchange, Queue, Message, DeliveryMode
from aio_pika.abc import AbstractRobustConnection, AbstractChannel

logger = logging.getLogger(__name__)

RABBITMQ_URL = "amqp://guest:guest@localhost:5672/"  # override via env/config

EXCHANGE_MAIN = "hyperion.v12.1.core"
EXCHANGE_DLX = "hyperion.v12.1.dlx"

QUEUE_CONFIG: Dict[str, dict] = {
    "received": {
        "routing_keys": ["received.#"],
        "dlq": "received.dlq",
        "durable": True,
    },
    "valuated": {
        "routing_keys": ["valuated.#"],
        "dlq": "valuated.dlq",
        "durable": True,
    },
    "dispatch.track": {
        "routing_keys": ["dispatch.track.#"],
        "dlq": "dispatch.track.dlq",
        "durable": True,
    },
    "validation": {
        "routing_keys": ["validation.#"],
        "dlq": "validation.dlq",
        "durable": True,
    },
    "evolution": {
        "routing_keys": ["evolution.#"],
        "dlq": "evolution.dlq",
        "durable": True,
    },
}


class RabbitMQConnector:
    """
    Manages RabbitMQ connection, exchanges, queues, and DLQ setup.
    Designed for FastAPI lifespan integration.
    """

    def __init__(self, url: str = RABBITMQ_URL) -> None:
        self.url: str = url
        self.connection: Optional[AbstractRobustConnection] = None
        self.channel: Optional[AbstractChannel] = None
        self.exchange_main: Optional[Exchange] = None
        self.exchange_dlx: Optional[Exchange] = None
        self.queues: Dict[str, Queue] = {}

    async def connect(self) -> None:
        """Establish connection and channel."""
        self.connection = await aio_pika.connect_robust(self.url)
        self.channel = await self.connection.channel()
        logger.info("Connected to RabbitMQ")

    async def setup_exchanges(self) -> None:
        """Declare main topic exchange and DLX direct exchange."""
        if self.channel is None:
            raise RuntimeError("Channel not initialized. Call connect() first.")

        self.exchange_main = await self.channel.declare_exchange(
            name=EXCHANGE_MAIN,
            type=aio_pika.ExchangeType.TOPIC,
            durable=True,
        )
        self.exchange_dlx = await self.channel.declare_exchange(
            name=EXCHANGE_DLX,
            type=aio_pika.ExchangeType.DIRECT,
            durable=True,
        )
        logger.info("Exchanges declared: %s (topic), %s (direct)", EXCHANGE_MAIN, EXCHANGE_DLX)

    async def setup_queues(self) -> None:
        """
        Declare queues with DLQ, bind to main exchange.
        Each queue gets a DLQ bound to DLX exchange.
        """
        if self.channel is None or self.exchange_main is None or self.exchange_dlx is None:
            raise RuntimeError("Exchanges not set up. Call setup_exchanges() first.")

        for queue_name, config in QUEUE_CONFIG.items():
            # Declare DLQ first
            dlq_name: str = config["dlq"]
            dlq = await self.channel.declare_queue(
                name=dlq_name,
                durable=True,
            )
            await dlq.bind(self.exchange_dlx, routing_key=dlq_name)
            logger.debug("DLQ '%s' bound to %s", dlq_name, EXCHANGE_DLX)

            # Declare main queue with DLX arguments
            args = {
                "x-dead-letter-exchange": EXCHANGE_DLX,
                "x-dead-letter-routing-key": dlq_name,
            }
            queue = await self.channel.declare_queue(
                name=queue_name,
                durable=config["durable"],
                arguments=args,
            )
            # Bind to main exchange with each routing key
            for rk in config["routing_keys"]:
                await queue.bind(self.exchange_main, routing_key=rk)
            self.queues[queue_name] = queue
            logger.debug("Queue '%s' bound to %s with keys %s", queue_name, EXCHANGE_MAIN, config["routing_keys"])

        logger.info("All queues and DLQs configured.")

    async def setup_all(self) -> None:
        """Convenience method: connect + exchanges + queues."""
        await self.connect()
        await self.setup_exchanges()
        await self.setup_queues()

    async def close(self) -> None:
        """Close channel and connection gracefully."""
        if self.channel:
            await self.channel.close()
        if self.connection:
            await self.connection.close()
        logger.info("RabbitMQ connection closed")


# Singleton instance for FastAPI lifespan
rabbit: RabbitMQConnector = RabbitMQConnector()


async def publish(
    routing_key: str,
    message_body: str,
    exchange: Optional[Exchange] = None,
    delivery_mode: DeliveryMode = DeliveryMode.PERSISTENT,
) -> None:
    """Publish a message to the main exchange."""
    ex = exchange or rabbit.exchange_main
    if ex is None:
        raise RuntimeError("Exchange not initialized")
    message = Message(
        body=message_body.encode(),
        delivery_mode=delivery_mode,
    )
    await ex.publish(message, routing_key=routing_key)
    logger.debug("Published message to %s with key %s", ex.name, routing_key)
