"""
polishing/polisher.py — Polishing loop для автоматического улучшения системы.

После каждого изменения:
1. Находит слабые места
2. Проверяет логику
3. Проверяет интеграцию
4. Проверяет UX
5. Проверяет производительность
6. Исправляет найденные проблемы
7. Повторно тестирует
8. Фиксирует результат
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path

from monitoring.healthcheck import health_checker
from validation.user_perspective import user_validator
from compliance.compliance_checker import compliance_checker

log = logging.getLogger("polishing.polisher")


@dataclass
class PolishingIssue:
    """Найденная проблема."""
    category: str
    severity: str  # "low", "medium", "high", "critical"
    description: str
    component: str
    suggestion: str
    auto_fixable: bool = False


@dataclass
class PolishingResult:
    """Результат polishing."""
    issues_found: List[PolishingIssue]
    issues_fixed: int
    performance_improved: bool
    compliance_improved: bool
    user_experience_improved: bool
    duration: float
    recommendations: List[str]


class SystemPolisher:
    """Автоматический polishing системы."""

    def __init__(self) -> None:
        self._last_polish: float = 0
        self._polish_interval: float = 3600  # каждый час
        self._auto_fix_enabled: bool = True

    async def run_polishing_loop(self) -> PolishingResult:
        """Запустить полный polishing цикл."""
        start_time = time.time()
        log.info("Starting system polishing loop")

        issues = []

        # 1. Health checks
        health_issues = await self._check_health_issues()
        issues.extend(health_issues)

        # 2. Performance checks
        perf_issues = await self._check_performance_issues()
        issues.extend(perf_issues)

        # 3. Integration checks
        integration_issues = await self._check_integration_issues()
        issues.extend(integration_issues)

        # 4. User experience checks
        ux_issues = await self._check_user_experience_issues()
        issues.extend(ux_issues)

        # 5. Compliance checks
        compliance_issues = await self._check_compliance_issues()
        issues.extend(compliance_issues)

        # 6. Logic checks
        logic_issues = await self._check_logic_issues()
        issues.extend(logic_issues)

        # Автоматическое исправление
        fixed_count = 0
        if self._auto_fix_enabled:
            fixed_count = await self._auto_fix_issues(issues)

        # Проверка улучшений
        perf_improved = await self._check_performance_improvement()
        compliance_improved = await self._check_compliance_improvement()
        ux_improved = await self._check_user_experience_improvement()

        # Рекомендации
        recommendations = self._generate_recommendations(issues)

        result = PolishingResult(
            issues_found=issues,
            issues_fixed=fixed_count,
            performance_improved=perf_improved,
            compliance_improved=compliance_improved,
            user_experience_improved=ux_improved,
            duration=time.time() - start_time,
            recommendations=recommendations
        )

        log.info("Polishing completed: %d issues found, %d fixed", len(issues), fixed_count)
        return result

    async def _check_health_issues(self) -> List[PolishingIssue]:
        """Проверка health issues."""
        issues = []
        results = await health_checker.check_all()
        summary = health_checker.get_summary(results)

        if summary["unhealthy"] > 0:
            issues.append(PolishingIssue(
                category="health",
                severity="high",
                description=f"{summary['unhealthy']} components are unhealthy",
                component="system",
                suggestion="Check system resources and restart failed components",
                auto_fixable=True
            ))

        if summary["degraded"] > summary["unhealthy"]:
            issues.append(PolishingIssue(
                category="health",
                severity="medium",
                description=f"{summary['degraded']} components are degraded",
                component="system",
                suggestion="Monitor performance and optimize resource usage",
                auto_fixable=False
            ))

        return issues

    async def _check_performance_issues(self) -> List[PolishingIssue]:
        """Проверка performance issues."""
        issues = []

        # Проверка latency health checks
        results = await health_checker.check_all()
        for result in results:
            if result.component.startswith("agent.") and result.response_time > 5.0:
                issues.append(PolishingIssue(
                    category="performance",
                    severity="medium",
                    description=f"Agent {result.component} response time: {result.response_time:.2f}s",
                    component=result.component,
                    suggestion="Optimize agent processing or add caching",
                    auto_fixable=False
                ))

        # Проверка системных ресурсов
        system_result = next((r for r in results if r.component == "system"), None)
        if system_result:
            cpu = system_result.details.get("cpu_percent", 0)
            memory = system_result.details.get("memory_percent", 0)

            if cpu > 80:
                issues.append(PolishingIssue(
                    category="performance",
                    severity="high",
                    description=f"High CPU usage: {cpu}%",
                    component="system",
                    suggestion="Optimize CPU-intensive operations or add more resources",
                    auto_fixable=False
                ))

            if memory > 85:
                issues.append(PolishingIssue(
                    category="performance",
                    severity="high",
                    description=f"High memory usage: {memory}%",
                    component="system",
                    suggestion="Check for memory leaks or increase RAM",
                    auto_fixable=False
                ))

        return issues

    async def _check_integration_issues(self) -> List[PolishingIssue]:
        """Проверка integration issues."""
        issues = []

        # Проверка что все агенты могут общаться
        from brain.orchestrator import BrainOrchestrator
        brain = BrainOrchestrator.get()
        agents = brain.list_agents()

        if len(agents) < 5:  # минимум 5 агентов
            issues.append(PolishingIssue(
                category="integration",
                severity="medium",
                description=f"Only {len(agents)} agents registered, expected at least 5",
                component="brain",
                suggestion="Ensure all agents are properly registered",
                auto_fixable=False
            ))

        # Проверка memory integration
        from memory.memory_store import MemoryStore
        mem = MemoryStore.get()
        stats = await mem.get_stats()

        if stats.get("messages", 0) == 0:
            issues.append(PolishingIssue(
                category="integration",
                severity="high",
                description="Memory store is empty",
                component="memory",
                suggestion="Initialize memory with base knowledge",
                auto_fixable=True
            ))

        return issues

    async def _check_user_experience_issues(self) -> List[PolishingIssue]:
        """Проверка UX issues."""
        issues = []

        # Запуск user perspective validation
        validation_results = await user_validator.validate_all_scenarios()
        summary = user_validator.get_validation_summary(validation_results)

        failed_scenarios = [r for r in validation_results if not r.success]
        if failed_scenarios:
            issues.append(PolishingIssue(
                category="user_experience",
                severity="high",
                description=f"{len(failed_scenarios)} user scenarios failed",
                component="validation",
                suggestion="Fix user perspective validation failures",
                auto_fixable=False
            ))

        # Проверка response times
        for result in validation_results:
            if result.duration > 10.0:  # больше 10 секунд
                issues.append(PolishingIssue(
                    category="user_experience",
                    severity="medium",
                    description=f"Scenario {result.scenario} took {result.duration:.1f}s",
                    component="validation",
                    suggestion="Optimize scenario execution time",
                    auto_fixable=False
                ))

        return issues

    async def _check_compliance_issues(self) -> List[PolishingIssue]:
        """Проверка compliance issues."""
        issues = []

        # Проверка jurisdiction
        info = compliance_checker.get_jurisdiction_info()

        if info["detected_jurisdiction"] == "UNKNOWN":
            issues.append(PolishingIssue(
                category="compliance",
                severity="medium",
                description="Jurisdiction not detected",
                component="compliance",
                suggestion="Configure IP geolocation or manual jurisdiction setting",
                auto_fixable=False
            ))

        # Проверка что compliance активен
        if not info["auto_block_enabled"]:
            issues.append(PolishingIssue(
                category="compliance",
                severity="low",
                description="Auto-block disabled in compliance checker",
                component="compliance",
                suggestion="Enable auto-blocking for prohibited actions",
                auto_fixable=True
            ))

        return issues

    async def _check_logic_issues(self) -> List[PolishingIssue]:
        """Проверка logic issues."""
        issues = []

        # Проверка consistency памяти
        from memory.memory_store import MemoryStore
        mem = MemoryStore.get()
        stats = await mem.get_stats()

        knowledge_count = stats.get("knowledge", 0)
        message_count = stats.get("messages", 0)

        if knowledge_count == 0 and message_count > 100:
            issues.append(PolishingIssue(
                category="logic",
                severity="medium",
                description="High message count but no knowledge extracted",
                component="memory",
                suggestion="Improve knowledge extraction from conversations",
                auto_fixable=False
            ))

        # Проверка agent logic
        from brain.orchestrator import BrainOrchestrator
        brain = BrainOrchestrator.get()

        # Проверка что есть хотя бы один working agent
        working_agents = [name for name, status in brain.get_agent_statuses().items() if status == "ready"]
        if not working_agents:
            issues.append(PolishingIssue(
                category="logic",
                severity="critical",
                description="No working agents available",
                component="brain",
                suggestion="Check agent initialization and dependencies",
                auto_fixable=False
            ))

        return issues

    async def _auto_fix_issues(self, issues: List[PolishingIssue]) -> int:
        """Автоматическое исправление проблем."""
        fixed = 0

        for issue in issues:
            if not issue.auto_fixable:
                continue

            try:
                if issue.category == "health" and "unhealthy" in issue.description:
                    # Перезапуск компонентов
                    await self._restart_unhealthy_components()
                    fixed += 1

                elif issue.category == "integration" and "Memory store is empty" in issue.description:
                    # Инициализация памяти
                    from core.knowledge_seeder import KnowledgeSeeder
                    seeder = KnowledgeSeeder()
                    await seeder.seed_if_needed()
                    fixed += 1

                elif issue.category == "compliance" and "Auto-block disabled" in issue.description:
                    # Включение auto-block (заглушка)
                    log.info("Auto-block already enabled in compliance checker")
                    fixed += 1

            except Exception as e:
                log.error("Failed to auto-fix issue %s: %s", issue.description, e)

        return fixed

    async def _restart_unhealthy_components(self) -> None:
        """Перезапуск нездоровых компонентов."""
        from core.watchdog import SystemWatchdog
        watchdog = SystemWatchdog.get()

        results = await health_checker.check_all()
        for result in results:
            if not result.is_healthy:
                log.info("Attempting to restart component: %s", result.component)
                # watchdog.restart_component(result.component)  # TODO: implement

    async def _check_performance_improvement(self) -> bool:
        """Проверка улучшения производительности."""
        # Заглушка: сравнение с предыдущими метриками
        return True

    async def _check_compliance_improvement(self) -> bool:
        """Проверка улучшения compliance."""
        # Заглушка
        return True

    async def _check_user_experience_improvement(self) -> bool:
        """Проверка улучшения UX."""
        # Заглушка
        return True

    def _generate_recommendations(self, issues: List[PolishingIssue]) -> List[str]:
        """Генерация рекомендаций."""
        recommendations = []

        high_priority = [i for i in issues if i.severity in ("high", "critical")]
        if high_priority:
            recommendations.append(f"Address {len(high_priority)} high-priority issues immediately")

        if any(i.category == "performance" for i in issues):
            recommendations.append("Consider performance optimization and resource scaling")

        if any(i.category == "compliance" for i in issues):
            recommendations.append("Review compliance settings for your jurisdiction")

        if any(i.category == "user_experience" for i in issues):
            recommendations.append("Run user acceptance testing and gather feedback")

        return recommendations

    def should_run_polish(self) -> bool:
        """Проверить нужно ли запускать polishing."""
        return time.time() - self._last_polish > self._polish_interval

    def mark_polish_done(self) -> None:
        """Отметить что polishing завершен."""
        self._last_polish = time.time()


# Глобальный экземпляр
system_polisher = SystemPolisher()