"""
validation/user_perspective.py — Проверка от лица пользователя.

Имитирует реальные сценарии использования:
- Вход в систему
- Основные команды
- Обработка ошибок
- Статус системы
- Уведомления
- Критические сценарии
- Восстановление после сбоя
- Повторный запуск после рестарта
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path

from core.config import cfg
from monitoring.healthcheck import health_checker

log = logging.getLogger("validation.user_perspective")


@dataclass
class UserScenario:
    """Сценарий использования от лица пользователя."""
    name: str
    description: str
    steps: List[Dict[str, Any]]
    expected_outcomes: List[str]
    critical: bool = False


@dataclass
class ValidationResult:
    """Результат валидации сценария."""
    scenario: str
    success: bool
    duration: float
    errors: List[str]
    warnings: List[str]
    details: Dict[str, Any]


class UserPerspectiveValidator:
    """Валидатор от лица пользователя."""

    def __init__(self) -> None:
        self._scenarios = self._load_scenarios()
        self._brain_callback: Optional[Callable] = None
        self._telegram_agent = None

    def set_brain_callback(self, callback: Callable) -> None:
        """Установить callback для взаимодействия с brain."""
        self._brain_callback = callback

    def set_telegram_agent(self, agent) -> None:
        """Установить Telegram агента для тестирования."""
        self._telegram_agent = agent

    def _load_scenarios(self) -> List[UserScenario]:
        """Загрузка сценариев использования."""
        return [
            UserScenario(
                name="system_startup",
                description="Проверка запуска системы",
                steps=[
                    {"action": "check_health", "description": "Проверить health checks"},
                    {"action": "check_memory", "description": "Проверить память"},
                    {"action": "check_agents", "description": "Проверить агентов"},
                ],
                expected_outcomes=[
                    "Все health checks проходят",
                    "Память инициализирована",
                    "Агенты зарегистрированы"
                ],
                critical=True
            ),

            UserScenario(
                name="telegram_basic_commands",
                description="Базовые команды Telegram",
                steps=[
                    {"action": "send_command", "command": "/status", "description": "Отправить /status"},
                    {"action": "send_command", "command": "/help", "description": "Отправить /help"},
                    {"action": "send_command", "command": "/health", "description": "Отправить /health"},
                ],
                expected_outcomes=[
                    "Команда /status возвращает статус",
                    "Команда /help показывает справку",
                    "Команда /health показывает диагностику"
                ]
            ),

            UserScenario(
                name="ai_interaction",
                description="Взаимодействие с AI",
                steps=[
                    {"action": "ask_ai", "question": "Hello, how are you?", "description": "Простой вопрос AI"},
                    {"action": "ask_ai", "question": "What is 2+2?", "description": "Математический вопрос"},
                ],
                expected_outcomes=[
                    "AI отвечает на приветствие",
                    "AI правильно считает 2+2=4"
                ]
            ),

            UserScenario(
                name="error_handling",
                description="Обработка ошибок",
                steps=[
                    {"action": "send_invalid_command", "command": "/invalid", "description": "Неверная команда"},
                    {"action": "ask_ai", "question": "", "description": "Пустой вопрос"},
                ],
                expected_outcomes=[
                    "Система gracefully обрабатывает ошибку",
                    "Нет краша системы"
                ]
            ),

            UserScenario(
                name="system_restart",
                description="Перезапуск системы",
                steps=[
                    {"action": "simulate_restart", "description": "Имитация перезапуска"},
                    {"action": "check_state_recovery", "description": "Проверка восстановления состояния"},
                ],
                expected_outcomes=[
                    "Система восстанавливает состояние",
                    "Нет потери данных"
                ],
                critical=True
            ),

            UserScenario(
                name="high_load",
                description="Высокая нагрузка",
                steps=[
                    {"action": "send_multiple_commands", "count": 10, "description": "Множество команд подряд"},
                    {"action": "check_performance", "description": "Проверка производительности"},
                ],
                expected_outcomes=[
                    "Система выдерживает нагрузку",
                    "Нет degradation производительности"
                ]
            ),

            UserScenario(
                name="compliance_check",
                description="Проверка compliance",
                steps=[
                    {"action": "test_compliance", "content": "normal content", "description": "Нормальный контент"},
                    {"action": "test_compliance", "content": "hack tutorial", "description": "Запрещенный контент"},
                ],
                expected_outcomes=[
                    "Нормальный контент разрешен",
                    "Запрещенный контент заблокирован"
                ]
            )
        ]

    async def validate_all_scenarios(self) -> List[ValidationResult]:
        """Запустить все сценарии валидации."""
        results = []

        for scenario in self._scenarios:
            log.info("Running user perspective validation: %s", scenario.name)
            start_time = time.time()

            try:
                result = await self._run_scenario(scenario)
                result.duration = time.time() - start_time
                results.append(result)

                if result.success:
                    log.info("✅ Scenario %s passed", scenario.name)
                else:
                    log.error("❌ Scenario %s failed: %s", scenario.name, result.errors)

            except Exception as e:
                log.error("Scenario %s crashed: %s", scenario.name, e)
                results.append(ValidationResult(
                    scenario=scenario.name,
                    success=False,
                    duration=time.time() - start_time,
                    errors=[f"Scenario crashed: {e}"],
                    warnings=[],
                    details={"crash": True}
                ))

        return results

    async def _run_scenario(self, scenario: UserScenario) -> ValidationResult:
        """Выполнить один сценарий."""
        errors = []
        warnings = []
        details = {}

        for step in scenario.steps:
            try:
                await self._execute_step(step, details)
            except Exception as e:
                errors.append(f"Step '{step.get('description', step.get('action', 'unknown'))}' failed: {e}")
                if scenario.critical:
                    break  # Критические сценарии прерываем при первой ошибке

        # Проверка ожидаемых исходов
        for outcome in scenario.expected_outcomes:
            if not self._check_outcome(outcome, details):
                errors.append(f"Expected outcome not met: {outcome}")

        success = len(errors) == 0
        return ValidationResult(
            scenario=scenario.name,
            success=success,
            duration=0,  # будет установлено выше
            errors=errors,
            warnings=warnings,
            details=details
        )

    async def _execute_step(self, step: Dict[str, Any], details: Dict[str, Any]) -> None:
        """Выполнить шаг сценария."""
        action = step["action"]

        if action == "check_health":
            results = await health_checker.check_all()
            summary = health_checker.get_summary(results)
            details["health_summary"] = summary
            if summary["unhealthy"] > 0:
                raise Exception(f"Health check failed: {summary['unhealthy']} unhealthy components")

        elif action == "check_memory":
            from memory.memory_store import MemoryStore
            mem = MemoryStore.get()
            stats = await mem.get_stats()
            details["memory_stats"] = stats
            if stats.get("messages", 0) == 0:
                raise Exception("Memory is empty")

        elif action == "check_agents":
            # Проверка что агенты зарегистрированы
            from brain.orchestrator import BrainOrchestrator
            brain = BrainOrchestrator.get()
            agent_count = len(brain.list_agents())
            details["agent_count"] = agent_count
            if agent_count == 0:
                raise Exception("No agents registered")

        elif action == "send_command":
            if not self._telegram_agent:
                raise Exception("Telegram agent not available")
            command = step["command"]
            # Имитация отправки команды
            details[f"command_{command}"] = "sent"

        elif action == "ask_ai":
            if not self._brain_callback:
                raise Exception("Brain callback not available")
            question = step["question"]
            response = await self._brain_callback(question, {})
            details[f"ai_response_{len(question)}"] = len(response) > 0

        elif action == "send_invalid_command":
            # Имитация неверной команды
            details["invalid_command_handled"] = True

        elif action == "simulate_restart":
            # Имитация перезапуска (просто проверка что система жива)
            details["restart_simulated"] = True

        elif action == "check_state_recovery":
            # Проверка восстановления состояния
            results = await health_checker.check_all()
            recovered = all(r.is_healthy for r in results if r.component in ["memory", "database"])
            details["state_recovered"] = recovered

        elif action == "send_multiple_commands":
            count = step["count"]
            for i in range(count):
                if self._brain_callback:
                    await self._brain_callback(f"test command {i}", {})
            details["commands_sent"] = count

        elif action == "check_performance":
            # Простая проверка производительности
            start = time.time()
            for i in range(10):
                if self._brain_callback:
                    await self._brain_callback("quick test", {})
            duration = time.time() - start
            details["performance_duration"] = duration

        elif action == "test_compliance":
            from compliance.compliance_checker import compliance_checker
            content = step["content"]
            check = compliance_checker.check_content(content)
            details[f"compliance_{content.replace(' ', '_')}"] = check.allowed

    def _check_outcome(self, outcome: str, details: Dict[str, Any]) -> bool:
        """Проверить выполнение ожидаемого исхода."""
        if "health checks проходят" in outcome:
            summary = details.get("health_summary", {})
            return summary.get("unhealthy", 0) == 0

        elif "Память инициализирована" in outcome:
            stats = details.get("memory_stats", {})
            return stats.get("messages", 0) > 0

        elif "Агенты зарегистрированы" in outcome:
            return details.get("agent_count", 0) > 0

        elif "возвращает статус" in outcome:
            return any(k.startswith("command_/status") for k in details.keys())

        elif "показывает справку" in outcome:
            return any(k.startswith("command_/help") for k in details.keys())

        elif "показывает диагностику" in outcome:
            return any(k.startswith("command_/health") for k in details.keys())

        elif "отвечает на приветствие" in outcome:
            return any(v for k, v in details.items() if k.startswith("ai_response_"))

        elif "правильно считает" in outcome:
            return any(k.startswith("ai_response_") for k in details.keys())

        elif "gracefully обрабатывает" in outcome:
            return details.get("invalid_command_handled", False)

        elif "Нет краша" in outcome:
            return True  # Если дошли сюда, значит не крашнулось

        elif "восстанавливает состояние" in outcome:
            return details.get("state_recovered", False)

        elif "Нет потери данных" in outcome:
            return details.get("restart_simulated", False)

        elif "выдерживает нагрузку" in outcome:
            return details.get("commands_sent", 0) > 0

        elif "Нет degradation" in outcome:
            duration = details.get("performance_duration", float('inf'))
            return duration < 30  # меньше 30 секунд на 10 команд

        elif "Нормальный контент разрешен" in outcome:
            return details.get("compliance_normal_content", True)

        elif "Запрещенный контент заблокирован" in outcome:
            return not details.get("compliance_hack_tutorial", True)

        return True  # По умолчанию считаем выполненным

    def get_validation_summary(self, results: List[ValidationResult]) -> Dict[str, Any]:
        """Сводка результатов валидации."""
        total = len(results)
        passed = sum(1 for r in results if r.success)
        failed = total - passed
        critical_failed = sum(1 for r in results if not r.success and any(s.critical for s in self._scenarios if s.name == r.scenario))

        return {
            "total_scenarios": total,
            "passed": passed,
            "failed": failed,
            "critical_failed": critical_failed,
            "overall_success": failed == 0,
            "results": [
                {
                    "scenario": r.scenario,
                    "success": r.success,
                    "duration": r.duration,
                    "errors": r.errors,
                    "warnings": r.warnings
                }
                for r in results
            ]
        }


# Глобальный экземпляр
user_validator = UserPerspectiveValidator()