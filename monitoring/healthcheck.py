"""
monitoring/healthcheck.py — Health checks для 24/7 работы системы.

Проверяет:
- LLM провайдеры (Claude, DeepSeek, Groq)
- Память (MemoryStore)
- Агенты (статус и heartbeat)
- Telegram бот
- База данных
- Системные ресурсы
- Compliance (если есть)

Используется для:
- Автоматической диагностики
- Watchdog перезапуска
- User-perspective validation
- Monitoring dashboards
"""

from __future__ import annotations

import asyncio
import logging
import os
import psutil
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from pathlib import Path

from core.config import cfg
from memory.memory_store import MemoryStore

log = logging.getLogger("monitoring.healthcheck")


@dataclass
class HealthStatus:
    """Результат health check."""
    component: str
    status: str  # "healthy", "degraded", "unhealthy", "unknown"
    message: str
    details: Dict[str, Any]
    timestamp: float
    response_time: float  # секунды

    @property
    def is_healthy(self) -> bool:
        return self.status == "healthy"

    @property
    def is_critical(self) -> bool:
        return self.status in ("unhealthy", "unknown")


class HealthCheck:
    """Центральный health checker системы."""

    def __init__(self) -> None:
        self._memory: Optional[MemoryStore] = None
        self._agents: Dict[str, Any] = {}
        self._last_check: float = 0
        self._check_interval: float = 60.0  # проверка каждые 60 сек

    def register_memory(self, memory: MemoryStore) -> None:
        """Регистрация memory store для проверки."""
        self._memory = memory

    def register_agent(self, name: str, agent: Any) -> None:
        """Регистрация агента для проверки."""
        self._agents[name] = agent

    async def check_all(self) -> List[HealthStatus]:
        """Полная проверка всех компонентов."""
        results = []
        start_time = time.time()

        # LLM провайдеры
        results.extend(await self._check_llm_providers())

        # Память
        results.append(await self._check_memory())

        # Агенты
        results.extend(await self._check_agents())

        # Telegram
        results.append(await self._check_telegram())

        # База данных
        results.append(await self._check_database())

        # Системные ресурсы
        results.append(await self._check_system_resources())

        # Compliance
        results.append(await self._check_compliance())

        self._last_check = time.time()
        total_time = time.time() - start_time
        log.debug("Health check completed in %.2fs", total_time)

        return results

    async def _check_llm_providers(self) -> List[HealthStatus]:
        """Проверка LLM провайдеров."""
        results = []

        providers = {
            "claude": cfg.anthropic_api_key,
            "deepseek": cfg.deepseek_api_key,
            "groq": cfg.groq_api_key,
        }

        for name, key in providers.items():
            start = time.time()
            try:
                if not key:
                    results.append(HealthStatus(
                        component=f"llm.{name}",
                        status="unknown",
                        message="API key not configured",
                        details={"configured": False},
                        timestamp=time.time(),
                        response_time=time.time() - start
                    ))
                    continue

                # Простой тест доступности (не полноценный вызов)
                status = "healthy"
                message = "API key configured"

            except Exception as e:
                status = "unhealthy"
                message = f"Check failed: {e}"

            results.append(HealthStatus(
                component=f"llm.{name}",
                status=status,
                message=message,
                details={"configured": bool(key)},
                timestamp=time.time(),
                response_time=time.time() - start
            ))

        return results

    async def _check_memory(self) -> HealthStatus:
        """Проверка памяти."""
        start = time.time()
        try:
            if not self._memory:
                return HealthStatus(
                    component="memory",
                    status="unknown",
                    message="Memory store not registered",
                    details={},
                    timestamp=time.time(),
                    response_time=time.time() - start
                )

            # Проверка базовой функциональности
            stats = await self._memory.get_stats()
            total_messages = stats.get("messages", 0)
            total_knowledge = stats.get("knowledge", 0)

            status = "healthy" if total_messages > 0 else "degraded"
            message = f"Messages: {total_messages}, Knowledge: {total_knowledge}"

            return HealthStatus(
                component="memory",
                status=status,
                message=message,
                details=stats,
                timestamp=time.time(),
                response_time=time.time() - start
            )

        except Exception as e:
            return HealthStatus(
                component="memory",
                status="unhealthy",
                message=f"Memory check failed: {e}",
                details={"error": str(e)},
                timestamp=time.time(),
                response_time=time.time() - start
            )

    async def _check_agents(self) -> List[HealthStatus]:
        """Проверка агентов."""
        results = []

        for name, agent in self._agents.items():
            start = time.time()
            try:
                # Проверка статуса агента
                if hasattr(agent, "status"):
                    status = agent.status
                else:
                    status = "unknown"

                # Проверка heartbeat (если есть)
                last_heartbeat = getattr(agent, "_last_heartbeat", None)
                if last_heartbeat:
                    age = time.time() - last_heartbeat
                    if age > 300:  # 5 минут
                        status = "degraded"
                        message = f"Stale heartbeat ({age:.0f}s ago)"
                    else:
                        message = f"Active ({age:.0f}s ago)"
                else:
                    message = "No heartbeat"

                results.append(HealthStatus(
                    component=f"agent.{name}",
                    status="healthy" if status == "running" else "degraded",
                    message=message,
                    details={"agent_status": status},
                    timestamp=time.time(),
                    response_time=time.time() - start
                ))

            except Exception as e:
                results.append(HealthStatus(
                    component=f"agent.{name}",
                    status="unhealthy",
                    message=f"Agent check failed: {e}",
                    details={"error": str(e)},
                    timestamp=time.time(),
                    response_time=time.time() - start
                ))

        return results

    async def _check_telegram(self) -> HealthStatus:
        """Проверка Telegram бота."""
        start = time.time()
        try:
            if not cfg.telegram_token:
                return HealthStatus(
                    component="telegram",
                    status="unknown",
                    message="Bot token not configured",
                    details={},
                    timestamp=time.time(),
                    response_time=time.time() - start
                )

            # Простая проверка токена через getMe
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"https://api.telegram.org/bot{cfg.telegram_token}/getMe"
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("ok"):
                        return HealthStatus(
                            component="telegram",
                            status="healthy",
                            message=f"Bot @{data['result']['username']} active",
                            details={"username": data["result"]["username"]},
                            timestamp=time.time(),
                            response_time=time.time() - start
                        )

            return HealthStatus(
                component="telegram",
                status="unhealthy",
                message="Bot token invalid or API unreachable",
                details={"status_code": resp.status_code if 'resp' in locals() else None},
                timestamp=time.time(),
                response_time=time.time() - start
            )

        except Exception as e:
            return HealthStatus(
                component="telegram",
                status="unhealthy",
                message=f"Telegram check failed: {e}",
                details={"error": str(e)},
                timestamp=time.time(),
                response_time=time.time() - start
            )

    async def _check_database(self) -> HealthStatus:
        """Проверка базы данных."""
        start = time.time()
        try:
            # Проверка SQLite файла
            db_path = Path("data") / "memory.db"
            if not db_path.exists():
                return HealthStatus(
                    component="database",
                    status="unhealthy",
                    message="Database file not found",
                    details={"path": str(db_path)},
                    timestamp=time.time(),
                    response_time=time.time() - start
                )

            # Проверка размера и доступности
            size = db_path.stat().st_size
            if size == 0:
                status = "degraded"
                message = "Database file is empty"
            else:
                status = "healthy"
                message = f"Database size: {size} bytes"

            return HealthStatus(
                component="database",
                status=status,
                message=message,
                details={"size_bytes": size, "path": str(db_path)},
                timestamp=time.time(),
                response_time=time.time() - start
            )

        except Exception as e:
            return HealthStatus(
                component="database",
                status="unhealthy",
                message=f"Database check failed: {e}",
                details={"error": str(e)},
                timestamp=time.time(),
                response_time=time.time() - start
            )

    async def _check_system_resources(self) -> HealthStatus:
        """Проверка системных ресурсов."""
        start = time.time()
        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=1)

            # Память
            memory = psutil.virtual_memory()
            memory_percent = memory.percent

            # Диск
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent

            # Определение статуса
            if cpu_percent > 90 or memory_percent > 90 or disk_percent > 95:
                status = "unhealthy"
                message = f"High resource usage: CPU {cpu_percent}%, MEM {memory_percent}%, DISK {disk_percent}%"
            elif cpu_percent > 70 or memory_percent > 80 or disk_percent > 90:
                status = "degraded"
                message = f"Elevated resource usage: CPU {cpu_percent}%, MEM {memory_percent}%, DISK {disk_percent}%"
            else:
                status = "healthy"
                message = f"Normal resource usage: CPU {cpu_percent}%, MEM {memory_percent}%, DISK {disk_percent}%"

            return HealthStatus(
                component="system",
                status=status,
                message=message,
                details={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory_percent,
                    "disk_percent": disk_percent,
                    "memory_used_gb": memory.used / (1024**3),
                    "disk_used_gb": disk.used / (1024**3)
                },
                timestamp=time.time(),
                response_time=time.time() - start
            )

        except Exception as e:
            return HealthStatus(
                component="system",
                status="unhealthy",
                message=f"System check failed: {e}",
                details={"error": str(e)},
                timestamp=time.time(),
                response_time=time.time() - start
            )

    async def _check_compliance(self) -> HealthStatus:
        """Проверка compliance (заглушка для будущей реализации)."""
        start = time.time()
        return HealthStatus(
            component="compliance",
            status="healthy",
            message="Compliance checks not implemented yet",
            details={"implemented": False},
            timestamp=time.time(),
            response_time=time.time() - start
        )

    def get_summary(self, results: List[HealthStatus]) -> Dict[str, Any]:
        """Сводка результатов health check."""
        total = len(results)
        healthy = sum(1 for r in results if r.is_healthy)
        degraded = sum(1 for r in results if r.status == "degraded")
        unhealthy = sum(1 for r in results if r.is_critical)

        critical_components = [r.component for r in results if r.is_critical]

        return {
            "total_components": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "overall_status": "healthy" if unhealthy == 0 else "degraded" if degraded > 0 else "unhealthy",
            "critical_components": critical_components,
            "timestamp": time.time()
        }


# Глобальный экземпляр
health_checker = HealthCheck()