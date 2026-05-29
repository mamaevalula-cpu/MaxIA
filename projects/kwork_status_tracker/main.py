"""
kwork_status_tracker - Скрипт для сохранения прогресса в файл data/kwork_status.json
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Константы
DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "kwork_status.json"
ENV_FILE = Path(".env")


def load_config() -> Dict[str, Any]:
    """Загружает конфигурацию из .env файла.

    Returns:
        Словарь с конфигурационными параметрами.
    """
    load_dotenv(ENV_FILE)
    config = {
        "debug": os.getenv("DEBUG", "false").lower() == "true",
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "data_dir": os.getenv("DATA_DIR", str(DATA_DIR)),
        "data_file": os.getenv("DATA_FILE", str(DATA_FILE)),
    }
    logger.debug(f"Конфигурация загружена: {config}")
    return config


def ensure_data_dir() -> None:
    """Создаёт директорию для данных, если она не существует."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(f"Директория {DATA_DIR} готова")


def read_json(file_path: Path) -> Dict[str, Any]:
    """Читает JSON-файл и возвращает его содержимое.

    Args:
        file_path: Путь к JSON-файлу.

    Returns:
        Словарь с данными или пустой словарь, если файл не существует.
    """
    if not file_path.exists():
        logger.warning(f"Файл {file_path} не найден, возвращаю пустые данные")
        return {}
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            data = json.load(file)
            logger.info(f"Файл {file_path} успешно прочитан")
            return data
    except (json.JSONDecodeError, OSError) as error:
        logger.error(f"Ошибка чтения файла {file_path}: {error}")
        return {}


def write_json(file_path: Path, data: Dict[str, Any]) -> None:
    """Записывает словарь в JSON-файл.

    Args:
        file_path: Путь к JSON-файлу.
        data: Данные для записи.
    """
    try:
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=4, ensure_ascii=False)
            logger.info(f"Данные успешно записаны в {file_path}")
    except OSError as error:
        logger.error(f"Ошибка записи в файл {file_path}: {error}")


def update_progress(status_data: Dict[str, Any], key: str, value: Any) -> Dict[str, Any]:
    """Обновляет конкретное поле в данных прогресса.

    Args:
        status_data: Текущие данные прогресса.
        key: Ключ для обновления.
        value: Новое значение.

    Returns:
        Обновлённый словарь с данными.
    """
    status_data[key] = value
    logger.debug(f"Обновлён ключ '{key}' со значением {value}")
    return status_data


def get_progress(status_data: Dict[str, Any], key: str) -> Optional[Any]:
    """Получает значение прогресса по ключу.

    Args:
        status_data: Данные прогресса.
        key: Ключ для поиска.

    Returns:
        Значение по ключу или None, если ключ отсутствует.
    """
    return status_data.get(key)


def main() -> None:
    """Основная функция для запуска скрипта."""
    config = load_config()

    # Устанавливаем уровень логирования из конфига
    logging.getLogger().setLevel(getattr(logging, config["log_level"].upper(), logging.INFO))

    logger.info("Запуск kwork_status_tracker")

    # Создаём директорию для данных
    ensure_data_dir()

    # Загружаем существующие данные
    data_file_path = Path(config["data_file"])
    status_data = read_json(data_file_path)

    # TODO: Реализовать основную логику получения/обновления прогресса
    # Пример: обновление тестового поля
    status_data = update_progress(status_data, "last_run", "2024-01-01 00:00:00")
    status_data = update_progress(status_data, "progress", 42)

    # Сохраняем обновлённые данные
    write_json(data_file_path, status_data)

    logger.info("Завершение kwork_status_tracker")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Скрипт остановлен пользователем (Ctrl+C)")
        sys.exit(0)
    except Exception as error:
        logger.exception(f"Неожиданная ошибка: {error}")
        sys.exit(1)