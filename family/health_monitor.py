# -*- coding: utf-8 -*-
"""
family/health_monitor.py — Мониторинг всех компонентов семьи.

Отслеживает состояние:
  • personal_ai    — основной процесс (этот процесс)
  • bybit_trading  — торговый бот (через HTTP /health + SQLite journal)
  • telegram       — Telegram-агент (через FamilyBus ping)
  • memory_db      — SQLite memory.db (доступность и целостность)
  • family_bus     — семейная шина (доступность)

Каждый компонент получает статус:
  ONLINE     — работает нормально
  DEGRADED   — работает, но с проблемами
  OFFLINE    — недоступен
  UNKNOWN    — нет данных

Использование:
    monitor = FamilyHealthMonitor.get()
    report  = monitor.check_all()
    print(monitor.format_report(report))

    # Фоновый мониторинг
    monitor.start_background()
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import urlopen
from urllib.error import URLError

log = logging.getLogger("family.health")

# Timeouts
PING_TIMEOUT   = 2.0    # HTTP
SILENCE_WARN   = 300    # секунд без ping → DEGRADED
SILENCE_CRIT   = 900    # секунд без ping → OFFLINE

# Пути
_AI_DB_PATH     = Path(__file__).parent.parent / "data" / "memory.db"
_FAMILY_DB_PATH = Path(__file__).parent.parent / "data" / "family.db"
_TRADING_HEALTH = "http://127.0.0.1:8080/health"
_TRADING_DB     = Path(__file__).parent.parent.parent / "bybit-bot" / "data" / "bybit_bot.db"


class ComponentStatus(str, Enum):
    ONLINE   = "online"
    DEGRADED = "degraded"
    OFFLINE  = "offline"
    UNKNOWN  = "unknown"


@dataclass
class ComponentHealth:
    name:        str
    status:      ComponentStatus = ComponentStatus.UNKNOWN
    last_seen:   float = 0.0
    silence_sec: float = 0.0
    details:     str = ""
    metrics:     Dict[str, Any] = field(default_factory=dict)

    @property
    def is_ok(self) -> bool:
        return self.status == ComponentStatus.ONLINE

    @property
    def age_str(self) -> str:
        if not self.last_seen:
            return "никогда"
        age = time.time() - self.last_seen
        if age < 60:
            return f"{age:.0f}с назад"
        if age < 3600:
            return f"{age/60:.0f}мин назад"
        return f"{age/3600:.1f}ч назад"


@dataclass
class FamilyHealthReport:
    ts:          float = field(default_factory=time.time)
    components:  List[ComponentHealth] = field(default_factory=list)
    overall:     ComponentStatus = ComponentStatus.UNKNOWN

    @property
    def online_count(self) -> int:
        return sum(1 for c in self.components if c.status == ComponentStatus.ONLINE)

    @property
    def total_count(self) -> int:
        return len(self.components)


class FamilyHealthMonitor:
    """
    Singleton — мониторинг состояния всей семьи.
    """

    _instance: Optional["FamilyHealthMonitor"] = None

    def __init__(self):
        self._last_report: Optional[FamilyHealthReport] = None
        self._bg_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._bg_interval = 60   # секунд между проверками

    @classmethod
    def get(cls) -> "FamilyHealthMonitor":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Проверки ──────────────────────────────────────────────────────────────

    def check_all(self) -> FamilyHealthReport:
        """Проверить все компоненты. Обновить кэш."""
        components = [
            self._check_personal_ai(),
            self._check_memory_db(),
            self._check_family_bus(),
            self._check_trading_bot(),
            self._check_telegram(),
        ]
        # Общий статус — худший из компонентов критических
        critical = [c for c in components if c.name in ("personal_ai", "memory_db")]
        if any(c.status == ComponentStatus.OFFLINE for c in critical):
            overall = ComponentStatus.OFFLINE
        elif any(c.status in (ComponentStatus.OFFLINE, ComponentStatus.DEGRADED)
                 for c in components):
            overall = ComponentStatus.DEGRADED
        elif all(c.status == ComponentStatus.ONLINE for c in components):
            overall = ComponentStatus.ONLINE
        else:
            overall = ComponentStatus.UNKNOWN

        report = FamilyHealthReport(components=components, overall=overall)
        self._last_report = report

        # Публикуем ping в FamilyBus
        try:
            from family.family_bus import EventKind, FamilyBus
            FamilyBus.get().ping("personal_ai", status=overall.value)
        except Exception:
            pass

        return report

    def _check_personal_ai(self) -> ComponentHealth:
        """Этот процесс — всегда online."""
        try:
            from memory.memory_store import MemoryStore
            mem = MemoryStore.get()
            stats = mem.stats()
            return ComponentHealth(
                name="personal_ai",
                status=ComponentStatus.ONLINE,
                last_seen=time.time(),
                details="Running",
                metrics={
                    "knowledge": stats.get("knowledge", 0),
                    "messages":  stats.get("messages", 0),
                },
            )
        except Exception as e:
            return ComponentHealth(
                name="personal_ai",
                status=ComponentStatus.DEGRADED,
                details=f"MemoryStore error: {e}",
            )

    def _check_memory_db(self) -> ComponentHealth:
        """Проверить доступность и целостность memory.db."""
        if not _AI_DB_PATH.exists():
            return ComponentHealth(
                name="memory_db",
                status=ComponentStatus.OFFLINE,
                details=f"File not found: {_AI_DB_PATH}",
            )
        try:
            conn = sqlite3.connect(str(_AI_DB_PATH), timeout=3)
            cnt = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            conn.close()
            return ComponentHealth(
                name="memory_db",
                status=ComponentStatus.ONLINE,
                last_seen=time.time(),
                details=f"{cnt} knowledge entries",
                metrics={"knowledge_count": cnt},
            )
        except Exception as e:
            return ComponentHealth(
                name="memory_db",
                status=ComponentStatus.DEGRADED,
                details=f"DB error: {e}",
            )

    def _check_family_bus(self) -> ComponentHealth:
        """Проверить доступность family bus."""
        if not _FAMILY_DB_PATH.exists():
            return ComponentHealth(
                name="family_bus",
                status=ComponentStatus.OFFLINE,
                details="family.db не создан (запустится при первом использовании)",
            )
        try:
            from family.family_bus import FamilyBus
            stats = FamilyBus.get().stats()
            components = FamilyBus.get().get_components()
            return ComponentHealth(
                name="family_bus",
                status=ComponentStatus.ONLINE,
                last_seen=time.time(),
                details=f"pending={stats['pending']} total={stats['total']}",
                metrics={**stats, "components": len(components)},
            )
        except Exception as e:
            return ComponentHealth(
                name="family_bus",
                status=ComponentStatus.DEGRADED,
                details=f"Bus error: {e}",
            )

    def _check_trading_bot(self) -> ComponentHealth:
        """Проверить торговый бот через HTTP + SQLite."""
        # Метод 1: HTTP health
        try:
            with urlopen(_TRADING_HEALTH, timeout=PING_TIMEOUT) as resp:
                body = resp.read().decode()
                import json
                data = json.loads(body) if body.startswith("{") else {}
                silence = data.get("silence_s", 0)
                if silence > SILENCE_CRIT:
                    return ComponentHealth(
                        name="bybit_trading",
                        status=ComponentStatus.DEGRADED,
                        last_seen=time.time() - silence,
                        silence_sec=silence,
                        details=f"Silent {silence:.0f}s",
                    )
                return ComponentHealth(
                    name="bybit_trading",
                    status=ComponentStatus.ONLINE,
                    last_seen=time.time(),
                    details="HTTP OK",
                    metrics=data,
                )
        except (URLError, Exception):
            pass

        # Метод 2: SQLite journal
        if _TRADING_DB.exists():
            try:
                conn = sqlite3.connect(str(_TRADING_DB), timeout=2)
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM execution_journal"
                ).fetchone()[0]
                last = conn.execute(
                    "SELECT MAX(recorded_at) FROM execution_journal"
                ).fetchone()[0]
                conn.close()
                silence = time.time() - (last or 0)
                status = (ComponentStatus.ONLINE if silence < SILENCE_WARN
                          else ComponentStatus.DEGRADED if silence < SILENCE_CRIT
                          else ComponentStatus.OFFLINE)
                return ComponentHealth(
                    name="bybit_trading",
                    status=status,
                    last_seen=last or 0,
                    silence_sec=silence,
                    details=f"DB OK, {cnt} trades, last {silence:.0f}s ago",
                    metrics={"trade_count": cnt},
                )
            except Exception as e:
                pass

        return ComponentHealth(
            name="bybit_trading",
            status=ComponentStatus.OFFLINE,
            details="HTTP и SQLite недоступны",
        )

    def _check_telegram(self) -> ComponentHealth:
        """Проверить Telegram-агент через FamilyBus ping."""
        try:
            from family.family_bus import FamilyBus
            components = FamilyBus.get().get_components()
            tg = next((c for c in components
                       if c["name"] in ("telegram", "telegram_agent")), None)
            if tg:
                silence = time.time() - tg["last_ping"]
                status = (ComponentStatus.ONLINE if silence < SILENCE_WARN
                          else ComponentStatus.DEGRADED if silence < SILENCE_CRIT
                          else ComponentStatus.OFFLINE)
                return ComponentHealth(
                    name="telegram",
                    status=status,
                    last_seen=tg["last_ping"],
                    silence_sec=silence,
                    details=f"Last ping {silence:.0f}s ago, status={tg['status']}",
                )
        except Exception:
            pass

        return ComponentHealth(
            name="telegram",
            status=ComponentStatus.UNKNOWN,
            details="Нет ping в FamilyBus (Telegram не запущен?)",
        )

    # ── Форматирование ────────────────────────────────────────────────────────

    def format_report(self, report: Optional[FamilyHealthReport] = None) -> str:
        if report is None:
            report = self._last_report or self.check_all()

        icons = {
            ComponentStatus.ONLINE:   "✅",
            ComponentStatus.DEGRADED: "⚠️ ",
            ComponentStatus.OFFLINE:  "❌",
            ComponentStatus.UNKNOWN:  "❓",
        }
        overall_icon = icons.get(report.overall, "❓")

        lines = [
            "╔══════════════════════════════════════════╗",
            f"║   СЕМЬЯ AI — СТАТУС  {overall_icon} {report.overall.value.upper():12s}  ║",
            "╚══════════════════════════════════════════╝",
            f"  {time.strftime('%d.%m.%Y %H:%M', time.localtime(report.ts))}",
            f"  Онлайн: {report.online_count}/{report.total_count} компонентов",
            "",
        ]
        for comp in report.components:
            icon = icons.get(comp.status, "❓")
            line = f"  {icon} {comp.name:<16s} {comp.status.value:<10s}"
            if comp.details:
                line += f" — {comp.details}"
            lines.append(line)
            if comp.metrics:
                for k, v in list(comp.metrics.items())[:2]:
                    lines.append(f"       {k}: {v}")

        return "\n".join(lines)

    def get_cached_report(self) -> Optional[FamilyHealthReport]:
        return self._last_report

    # ── Фоновый мониторинг ────────────────────────────────────────────────────

    def start_background(self, interval: int = 60) -> None:
        """Запустить фоновую проверку каждые N секунд."""
        if self._bg_thread and self._bg_thread.is_alive():
            return
        self._bg_interval = interval
        self._stop.clear()
        self._bg_thread = threading.Thread(
            target=self._bg_loop, daemon=True, name="family-health"
        )
        self._bg_thread.start()
        log.info("FamilyHealthMonitor background started (interval=%ds)", interval)

    def stop_background(self) -> None:
        self._stop.set()

    def _bg_loop(self) -> None:
        while not self._stop.is_set():
            try:
                report = self.check_all()
                if report.overall != ComponentStatus.ONLINE:
                    log.warning("Family health: %s (%d/%d online)",
                                report.overall.value,
                                report.online_count, report.total_count)
                    # Публикуем в шину
                    from family.family_bus import EventKind, FamilyBus
                    FamilyBus.get().broadcast(
                        EventKind.COMPONENT_OFFLINE, source="health_monitor",
                        payload={"status": report.overall.value,
                                 "offline": [c.name for c in report.components
                                             if c.status != ComponentStatus.ONLINE]},
                    )
            except Exception as e:
                log.error("Health check error: %s", e)
            self._stop.wait(timeout=self._bg_interval)
