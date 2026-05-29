# -*- coding: utf-8 -*-
"""
tools/bybit_loader.py — Safe Bybit exchange loader that avoids namespace collision.
"""
from __future__ import annotations
import importlib.util
import os
import sys
from pathlib import Path

_BYBIT_BOT_DIR = Path("/root/bybit-bot")
_exchange_cache = {}


def load_exchange():
    """Load BybitExchange from /root/bybit-bot/core/exchange.py safely."""
    if "bybit_exchange" in _exchange_cache:
        return _exchange_cache["bybit_exchange"]

    spec = importlib.util.spec_from_file_location(
        "bybit_core_exchange",
        str(_BYBIT_BOT_DIR / "core" / "exchange.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["bybit_core_exchange"] = module
    spec.loader.exec_module(module)
    _exchange_cache["bybit_exchange"] = module.BybitExchange
    return module.BybitExchange


def get_exchange():
    """Get configured BybitExchange instance using .env credentials."""
    BybitExchange = load_exchange()
    api_key    = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    testnet    = os.getenv("BYBIT_TESTNET", "true").lower() == "true"
    return BybitExchange(api_key, api_secret, testnet)
