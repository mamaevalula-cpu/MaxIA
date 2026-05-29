#!/usr/bin/env python3
"""
agents/master_control_agent.py
ГЛАВНЫЙ АГЕНТ - контролирует все агенты 24/7
Запускает, мониторит, перезапускает, отчитывается в Telegram.
"""
import asyncio, json, logging, time, os
from pathlib import Path
from typing import Dict, List, Tuple

log = logging.getLogger("agents.master_control")
BASE = Path("/root/my_personal_ai")
DATA = BASE / "data"
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "1985320458")

# Расписание агентов (час: [агент, задача])
SCHEDULE: Dict[int, List[Tuple[str, str]]] = {
    0:  [("earn_agent",      "авто-реинвест Bybit Earn USDT")],
    6:  [("crypto_monitor",  "утренний анализ рынка BTC/ETH/SOL")],
    7:  [("freelance_agent", "парсинг заказов Kwork/Upwork")],
    8:  [("market_scanner",  "мониторинг цен Wildberries конкурентов")],
    9:  [("telegram_agent",  "утренний отчёт P&L владельцу")],
    10: [("coffee_sourcing", "поиск B2B покупателей кофе")],
    12: [("trading_agent",   "проверка funding rates + grid бот")],
    14: [("market_scanner",  "сканирование новых сигналов")],
    16: [("crypto_monitor",  "крипто-сигнал в Telegram канал")],
    18: [("freelance_agent", "вечерний парсинг заказов")],
    20: [("trading_agent",   "ночная проверка funding + grid")],
    21: [("telegram_agent",  "вечерний отчёт PnL + баланс")],
    23: [("health_monitor",  "ночная диагностика всех агентов")],
}

# Проекты которые нужно вести
PROJECTS = {
    "Bybit Grid Bot v2":      {"agent": "trading_agent",   "check_every_h": 1},
    "AI Micro-SaaS Bot":      {"agent": "telegram_agent",  "check_every_h": 6},
    "Bybit Earn":             {"agent": "trading_agent",   "check_every_h": 24},
    "Funding Rate Arbitrage": {"agent": "trading_agent",   "check_every_h": 8},
    "Wildberries CLEANS SKIN":{"agent": "market_scanner",  "check_every_h": 12},
    "Coffee Export":          {"agent": "email_agent",     "check_every_h": 24},
    "AI Freelance":           {"agent": "freelance_agent", "check_every_h": 12},
    "Crypto Signals":         {"agent": "crypto_monitor",  "check_every_h": 6},
}

class MasterControlAgent:
    """Главный агент - контролирует все агенты 24/7"""

    def __init__(self):
        self.name = "MasterControlAgent"
        self.status = "idle"
        self.last_report = 0
        self.stats = {"checks": 0, "restarts": 0, "reports_sent": 0, "earnings_usd": 0}

    def can_handle(self, text: str) -> bool:
        """Проверяет, может ли этот агент обработать сообщение"""
        keywords = ["мастер агент", "главный агент", "контроль агентов",
                    "запусти всех", "статус агентов", "master control",
                    "проверь всех агентов", "все агенты работают"]
        return any(k in text.lower() for k in keywords)

    def get_status(self) -> Dict:
        """Возвращает статус агента"""
        return {
            "name": self.name,
            "status": self.status,
            "stats": self.stats,
            "projects": len(PROJECTS),
            "schedule_hours": list(SCHEDULE.keys()),
        }

    def info(self) -> Dict:
        """Возвращает информацию об агенте"""
        return {
            "name": self.name,
            # TODO: дополнить информацию
        }