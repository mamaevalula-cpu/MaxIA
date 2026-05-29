# -*- coding: utf-8 -*-
"""
core/logger.py — Структурированное логирование для всей системы.

Раздельные файлы на каждый модуль + единый aggregated log.
Формат: JSON (structlog) или human-readable для консоли.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional


_LOGS_DIR = Path(__file__).parent.parent / "logs"
_LOGS_DIR.mkdir(parents=True, exist_ok=True)

_FMT_CONSOLE = "%(asctime)s [%(levelname)-8s] %(name)-24s %(message)s"
_FMT_FILE    = "%(asctime)s [%(levelname)-8s] [%(name)s] %(message)s"
_DATE_FMT    = "%Y-%m-%d %H:%M:%S"

_initialised = False


def _make_file_handler(filename: str, level: int = logging.DEBUG) -> logging.Handler:
    path = _LOGS_DIR / filename
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_FMT_FILE, datefmt=_DATE_FMT))
    return handler


def setup_logging(level: str = "INFO") -> None:
    """Инициализировать систему логирования. Вызывается один раз при старте."""
    global _initialised
    if _initialised:
        return
    _initialised = True

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Консоль
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(_FMT_CONSOLE, datefmt=_DATE_FMT))
    root.addHandler(console)

    # Общий файл
    root.addHandler(_make_file_handler("system.log", logging.DEBUG))
    root.addHandler(_make_file_handler("errors.log", logging.ERROR))

    # Специализированные файлы по модулям
    for name, fname in [
        ("brain",    "brain.log"),
        ("agents",   "agents.log"),
        ("memory",   "memory.log"),
        ("vector",   "vector.log"),
        ("trading",  "trading.log"),
        ("auth",     "auth.log"),
        ("gui",      "gui.log"),
    ]:
        logger = logging.getLogger(name)
        logger.addHandler(_make_file_handler(fname))
        logger.propagate = True  # also goes to root

    # Заглушить шумные библиотеки
    for noisy in ("httpx", "httpcore", "urllib3", "telegram", "asyncio",
                  "chromadb", "qdrant_client"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info("Logging initialised (level=%s)", level)


def get_logger(name: str) -> logging.Logger:
    """Получить именованный логгер."""
    return logging.getLogger(name)
