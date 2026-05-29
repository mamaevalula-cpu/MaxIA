#!/usr/bin/env python3
"""
Модуль для сохранения структурированных данных о найденных заказах в JSON.

Сохраняет обновлённые данные в файл data/freelance_applications.json с отступами.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FreelanceDataSaver:
    """
    Класс для сохранения данных о фриланс-заказах в JSON-файл.
    """

    def __init__(self, file_path: str = "data/freelance_applications.json") -> None:
        """
        Инициализация с указанием пути к JSON-файлу.

        Args:
            file_path: Путь к файлу для сохранения (относительно корня проекта).
        """
        self.file_path = Path(file_path)
        self._ensure_data_dir()

    def _ensure_data_dir(self) -> None:
        """
        Создаёт директорию data, если она не существует.
        """
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def load_existing_data(self) -> List[Dict[str, Any]]:
        """
        Загружает существующие данные из JSON-файла, если он есть.

        Returns:
            Список заказов (пустой список, если файла нет или он пуст).
        """
        if not self.file_path.exists():
            logger.info("Файл %s не найден, начинаем с пустого списка", self.file_path)
            return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                data = json.loads(content)
                if isinstance(data, list):
                    return data
                else:
                    logger.warning("JSON содержит не список, возвращаем пустой список")
                    return []
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Ошибка загрузки данных из %s: %s", self.file_path, e)
            return []

    def save_data(self, new_orders: List[Dict[str, Any]]) -> None:
        """
        Сохраняет (обновляет) данные в JSON-файл.

        Сначала загружает существующие заказы, добавляет новые (без дубликатов),
        затем записывает результат с отступами для читаемости.

        Args:
            new_orders: Список новых найденных заказов (каждый — словарь).
        """
        existing_orders = self.load_existing_data()

        # Собираем идентификаторы существующих заказов (по полю 'id', если есть)
        existing_ids: set = set()
        for order in existing_orders:
            if "id" in order:
                existing_ids.add(order["id"])

        # Добавляем только те новые заказы, которых ещё нет
        added_count = 0
        for order in new_orders:
            order_id = order.get("id")
            if order_id is None or order_id not in existing_ids:
                existing_orders.append(order)
                if order_id is not None:
                    existing_ids.add(order_id)
                added_count += 1

        # Запись обратно в файл
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(existing_orders, f, ensure_ascii=False, indent=2)
            logger.info(
                "Данные сохранены в %s. Добавлено %d новых заказов, всего %d",
                self.file_path,
                added_count,
                len(existing_orders),
            )
        except OSError as e:
            logger.error("Ошибка записи в %s: %s", self.file_path, e)
            raise

    def overwrite_data(self, orders: List[Dict[str, Any]]) -> None:
        """
        Полностью перезаписывает файл переданным списком заказов.

        Args:
            orders: Список заказов для записи.
        """
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(orders, f, ensure_ascii=False, indent=2)
            logger.info("Данные перезаписаны в %s (%d заказов)", self.file_path, len(orders))
        except OSError as e:
            logger.error("Ошибка перезаписи %s: %s", self.file_path, e)
            raise


# Пример использования при запуске модуля как скрипта
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    saver = FreelanceDataSaver()

    # Пример тестовых данных
    test_orders: List[Dict[str, Any]] = [
        {
            "id": "12345",
            "title": "Разработка парсера на Python",
            "description": "Нужно написать парсер для сайта...",
            "budget": "30000 руб.",
            "platform": "freelance.ru",
            "url": "https://freelance.ru/projects/12345",
            "date_found": "2025-04-05T12:00:00",
        }
    ]

    saver.save_data(test_orders)
    print(f"Тестовые данные сохранены в {saver.file_path.resolve()}")
