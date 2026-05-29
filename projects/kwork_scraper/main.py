#!/usr/bin/env python3
"""
kwork_scraper - Парсер для сайта Kwork
"""

import os
import sys
import logging
from pathlib import Path
from typing import NoReturn

from dotenv import load_dotenv

# Константы
DATA_DIR = Path(__file__).parent / "data"
CONFIG_FILE = Path(__file__).parent / ".env"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(DATA_DIR / "scraper.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("kwork_scraper")


def load_config() -> dict:
    """
    Загружает конфигурацию из .env файла.

    Returns:
        dict: Словарь с настройками приложения.
    """
    if CONFIG_FILE.exists():
        load_dotenv(CONFIG_FILE)
        logger.info("Конфигурация загружена из %s", CONFIG_FILE)
    else:
        logger.warning("Файл .env не найден, используются переменные окружения")

    config = {
        "debug": os.getenv("DEBUG", "false").lower() == "true",
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "user_agent": os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        ),
        "base_url": os.getenv("BASE_URL", "https://kwork.ru"),
    }

    return config


def setup_environment() -> None:
    """
    Создаёт необходимые директории и проверяет окружение.
    """
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        logger.debug("Директория data: %s", DATA_DIR)
    except PermissionError:
        logger.error("Нет прав на создание директории %s", DATA_DIR)
        sys.exit(1)


def parse_kwork(config: dict) -> None:
    """
    Основная логика парсинга Kwork.

    Args:
        config: Словарь с настройками из конфигурации.
    
    TODO: Реализовать логику парсинга:
        - Аутентификация на Kwork
        - Сбор данных с категорий
        - Сохранение результатов в data/
    """
    logger.info("Запуск парсинга Kwork...")
    logger.debug("Конфигурация: %s", {k: v for k, v in config.items() if k != "password"})

    # TODO: Реализовать основную логику парсинга
    base_url = config.get("base_url", "https://kwork.ru")
    logger.info("Целевой URL: %s", base_url)

    # Заглушка для демонстрации
    logger.warning("Парсинг ещё не реализован. Проверьте TODO в коде.")
    print(f"[STUB] Парсинг {base_url} будет реализован позже.")


def main() -> NoReturn:
    """
    Главная функция приложения.
    """
    try:
        # Загрузка конфигурации
        config = load_config()

        # Настройка уровня логирования
        log_level = getattr(logging, config["log_level"].upper(), logging.INFO)
        logger.setLevel(log_level)
        logging.getLogger().setLevel(log_level)

        # Подготовка окружения
        setup_environment()

        # Запуск парсинга
        parse_kwork(config)

        logger.info("Работа программы завершена успешно.")
        sys.exit(0)

    except KeyboardInterrupt:
        logger.info("Получен сигнал прерывания (Ctrl+C). Завершение работы...")
        sys.exit(0)

    except Exception as e:
        logger.exception("Критическая ошибка: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()