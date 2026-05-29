# -*- coding: utf-8 -*-
"""config.py — Конфигурация maxai_marketplace_promotion."""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# ── Основные настройки ────────────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── API ключи ─────────────────────────────────────────────────────────────────
# Добавь свои ключи в .env
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
