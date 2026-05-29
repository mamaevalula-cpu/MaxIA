#!/usr/bin/env python3
"""Order Agent — сервисный слой для создания и управления заказами.

Предоставляет:
- создание заказа (create_order)
- получение заказа по ID (get_order)
- список заказов пользователя (list_orders)
- отмену заказа (cancel_order)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & Data classes
# ---------------------------------------------------------------------------

class OrderStatus(str, Enum):
    """Статус заказа."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


@dataclass
class OrderItem:
    """Позиция в заказе."""
    product_id: int
    name: str
    quantity: int
    unit_price: float

    @property
    def subtotal(self) -> float:
        """Стоимость позиции."""
        return round(self.quantity * self.unit_price, 2)


@dataclass
class Order:
    """Модель заказа (in-memory, без ORM)."""
    id: int
    user_id: int
    items: list[OrderItem] = field(default_factory=list)
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = ""

    @property
    def total(self) -> float:
        """Итоговая сумма заказа."""
        return round(sum(item.subtotal for item in self.items), 2)

    def to_dict(self) -> dict:
        """Сериализация в словарь."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status.value,
            "items": [
                {
                    "product_id": i.product_id,
                    "name": i.name,
                    "quantity": i.quantity,
                    "unit_price": i.unit_price,
                    "subtotal": i.subtotal,
                }
                for i in self.items
            ],
            "total": self.total,
            "notes": self.notes,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class OrderNotFoundError(Exception):
    """Заказ не найден."""


class OrderAlreadyCancelledError(Exception):
    """Попытка отменить уже отменённый заказ."""


class EmptyOrderError(Exception):
    """Попытка создать заказ без позиций."""


# ---------------------------------------------------------------------------
# OrderAgent
# ---------------------------------------------------------------------------

class OrderAgent:
    """Агент управления заказами.

    Хранит заказы в памяти (dict). Для production замените
    _store на вызовы к БД / внешнему сервису.

    Example::

        agent = OrderAgent()
        order = agent.create_order(
            user_id=42,
            items=[
                {"product_id": 1, "name": "Widget", "quantity": 2, "unit_price": 9.99},
            ],
            notes="Срочно",
        )
        print(order.to_dict())
    """

    def __init__(self) -> None:
        self._store: dict[int, Order] = {}
        self._next_id: int = 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_order(
        self,
        user_id: int,
        items: list[dict],
        notes: str = "",
    ) -> Order:
        """Создать новый заказ.

        Args:
            user_id: Идентификатор пользователя.
            items: Список позиций. Каждый элемент — dict с ключами:
                   product_id, name, quantity, unit_price.
            notes: Произвольный комментарий к заказу.

        Returns:
            Созданный объект :class:`Order`.

        Raises:
            EmptyOrderError: Если список позиций пуст.
            ValueError: Если данные позиции некорректны.
        """
        if not items:
            raise EmptyOrderError("Нельзя создать заказ без позиций.")

        order_items = [self._parse_item(raw) for raw in items]
        order = Order(
            id=self._next_id,
            user_id=user_id,
            items=order_items,
            notes=notes,
        )
        self._store[order.id] = order
        self._next_id += 1

        logger.info(
            "Заказ #%d создан для user_id=%d, позиций=%d, сумма=%.2f",
            order.id, user_id, len(order_items), order.total,
        )
        return order

    def get_order(self, order_id: int) -> Order:
        """Получить заказ по ID.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Объект :class:`Order`.

        Raises:
            OrderNotFoundError: Если заказ не найден.
        """
        order = self._store.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"Заказ #{order_id} не найден.")
        return order

    def list_orders(
        self,
        user_id: int,
        status: Optional[OrderStatus] = None,
    ) -> list[Order]:
        """Список заказов пользователя.

        Args:
            user_id: Идентификатор пользователя.
            status: Фильтр по статусу (опционально).

        Returns:
            Список объектов :class:`Order`, отсортированных по дате создания (desc).
        """
        orders = [
            o for o in self._store.values()
            if o.user_id == user_id
            and (status is None or o.status == status)
        ]
        return sorted(orders, key=lambda o: o.created_at, reverse=True)

    def cancel_order(self, order_id: int) -> Order:
        """Отменить заказ.

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Обновлённый объект :class:`Order`.

        Raises:
            OrderNotFoundError: Если заказ не найден.
            OrderAlreadyCancelledError: Если заказ уже отменён.
        """
        order = self.get_order(order_id)
        if order.status == OrderStatus.CANCELLED:
            raise OrderAlreadyCancelledError(
                f"Заказ #{order_id} уже отменён."
            )
        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)
        logger.info("Заказ #%d отменён.", order_id)
        return order

    def confirm_order(self, order_id: int) -> Order:
        """Подтвердить заказ (перевести в CONFIRMED).

        Args:
            order_id: Идентификатор заказа.

        Returns:
            Обновлённый объект :class:`Order`.

        Raises:
            OrderNotFoundError: Если заказ не найден.
            ValueError: Если заказ не в статусе PENDING.
        """
        order = self.get_order(order_id)
        if order.status != OrderStatus.PENDING:
            raise ValueError(
                f"Подтвердить можно только заказ в статусе PENDING. "
                f"Текущий статус: {order.status.value}"
            )
        order.status = OrderStatus.CONFIRMED
        order.updated_at = datetime.now(timezone.utc)
        logger.info("Заказ #%d подтверждён.", order_id)
        return order

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_item(raw: dict) -> OrderItem:
        """Разобрать сырой dict в :class:`OrderItem`.

        Args:
            raw: Словарь с ключами product_id, name, quantity, unit_price.

        Returns:
            Объект :class:`OrderItem`.

        Raises:
            ValueError: При отсутствии обязательных полей или некорректных значениях.
        """
        required = {"product_id", "name", "quantity", "unit_price"}
        missing = required - raw.keys()
        if missing:
            raise ValueError(f"Отсутствуют обязательные поля: {missing}")

        quantity = int(raw["quantity"])
        unit_price = float(raw["unit_price"])

        if quantity <= 0:
            raise ValueError(f"quantity должен быть > 0, получено: {quantity}")
        if unit_price < 0:
            raise ValueError(f"unit_price не может быть отрицательным: {unit_price}")

        return OrderItem(
            product_id=int(raw["product_id"]),
            name=str(raw["name"]).strip(),
            quantity=quantity,
            unit_price=unit_price,
        )


# ---------------------------------------------------------------------------
# Singleton (опционально)
# ---------------------------------------------------------------------------

_agent_instance: Optional[OrderAgent] = None


def get_order_agent() -> OrderAgent:
    """Вернуть глобальный экземпляр :class:`OrderAgent` (lazy singleton)."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = OrderAgent()
    return _agent_instance


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------


    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        """Orchestrator bridge — auto-added."""
        for m in ["run","execute","work","handle","daily_cycle","check","scan","analyze","report","daily_report"]:
            fn = getattr(self, m, None)
            if fn and callable(fn):
                try:
                    r = fn()
                    return str(r)[:400] if r else self.__class__.__name__ + ": ok"
                except Exception as e:
                    return self.__class__.__name__ + f" error: {e}"
        return self.__class__.__name__ + ": ready"

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    agent = OrderAgent()

    # Создаём заказ
    o = agent.create_order(
        user_id=1,
        items=[
            {"product_id": 10, "name": "Laptop", "quantity": 1, "unit_price": 999.99},
            {"product_id": 11, "name": "Mouse",  "quantity": 2, "unit_price": 29.50},
        ],
        notes="Доставить до 18:00",
    )
    print("Создан:", o.to_dict())

    # Подтверждаем
    o = agent.confirm_order(o.id)
    print("Подтверждён:", o.status)

    # Список заказов
    orders = agent.list_orders(user_id=1)
    print("Заказов у user_id=1:", len(orders))

    # Отмена
    o = agent.cancel_order(o.id)
    print("Отменён:", o.status)