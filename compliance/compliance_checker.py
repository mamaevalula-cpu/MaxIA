"""
compliance/compliance_checker.py — Compliance layer для проверки законов.

Проверяет:
- Юрисдикцию использования
- Запрещенные действия по странам
- Регулируемые операции
- Безопасность данных
- Экспортные ограничения

Поддерживает:
- Россия (ФЗ-152, 187-ФЗ)
- США (CFAA, DMCA)
- ЕС (GDPR)
- Китай (Великий файрвол)
"""

from __future__ import annotations

import logging
import ipaddress
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Set, Any
from pathlib import Path

log = logging.getLogger("compliance")


class Jurisdiction(Enum):
    """Юрисдикции."""
    RUSSIA = "RU"
    USA = "US"
    EU = "EU"
    CHINA = "CN"
    UNKNOWN = "UNKNOWN"


class ComplianceLevel(Enum):
    """Уровень compliance."""
    ALLOWED = "allowed"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"
    REQUIRES_APPROVAL = "requires_approval"


@dataclass
class ComplianceRule:
    """Правило compliance."""
    jurisdiction: Jurisdiction
    category: str
    action: str
    level: ComplianceLevel
    description: str
    requires_approval: bool = False
    auto_block: bool = True


@dataclass
class ComplianceCheck:
    """Результат проверки compliance."""
    action: str
    jurisdiction: Jurisdiction
    level: ComplianceLevel
    allowed: bool
    message: str
    requires_approval: bool
    blocked_actions: List[str]


class ComplianceChecker:
    """Проверяет compliance действий системы."""

    def __init__(self) -> None:
        self._rules: List[ComplianceRule] = []
        self._current_jurisdiction = self._detect_jurisdiction()
        self._load_rules()

    def _detect_jurisdiction(self) -> Jurisdiction:
        """Определение текущей юрисдикции по IP."""
        try:
            import requests
            # Получение внешнего IP
            response = requests.get("https://api.ipify.org?format=json", timeout=5)
            ip = response.json()["ip"]

            # Определение страны по IP (упрощенная версия)
            # В реальности нужен сервис вроде MaxMind GeoIP
            if ipaddress.ip_address(ip).is_private:
                return Jurisdiction.UNKNOWN

            # Заглушка: определение по первым октетам
            octets = ip.split(".")
            if octets[0] == "5":  # Пример для РФ (AS8342 RTComm.RU)
                return Jurisdiction.RUSSIA
            elif octets[0] in ("8", "23", "35"):  # Примеры для США
                return Jurisdiction.USA
            else:
                return Jurisdiction.UNKNOWN

        except Exception as e:
            log.warning("Failed to detect jurisdiction: %s", e)
            return Jurisdiction.UNKNOWN

    def _load_rules(self) -> None:
        """Загрузка правил compliance."""
        self._rules = [

            # Россия
            ComplianceRule(
                jurisdiction=Jurisdiction.RUSSIA,
                category="data_processing",
                action="store_personal_data",
                level=ComplianceLevel.REQUIRES_APPROVAL,
                description="Хранение персональных данных требует согласия (ФЗ-152)",
                requires_approval=True
            ),
            ComplianceRule(
                jurisdiction=Jurisdiction.RUSSIA,
                category="network",
                action="access_blocked_sites",
                level=ComplianceLevel.PROHIBITED,
                description="Доступ к заблокированным сайтам запрещен",
                auto_block=True
            ),
            ComplianceRule(
                jurisdiction=Jurisdiction.RUSSIA,
                category="ai",
                action="generate_political_content",
                level=ComplianceLevel.RESTRICTED,
                description="Генерация политического контента ограничена",
                requires_approval=True
            ),

            # США
            ComplianceRule(
                jurisdiction=Jurisdiction.USA,
                category="copyright",
                action="copy_protected_content",
                level=ComplianceLevel.PROHIBITED,
                description="Копирование защищенного контента нарушает DMCA",
                auto_block=True
            ),
            ComplianceRule(
                jurisdiction=Jurisdiction.USA,
                category="security",
                action="unauthorized_access",
                level=ComplianceLevel.PROHIBITED,
                description="Несанкционированный доступ нарушает CFAA",
                auto_block=True
            ),

            # ЕС
            ComplianceRule(
                jurisdiction=Jurisdiction.EU,
                category="privacy",
                action="process_personal_data",
                level=ComplianceLevel.REQUIRES_APPROVAL,
                description="Обработка персональных данных требует GDPR compliance",
                requires_approval=True
            ),

            # Китай
            ComplianceRule(
                jurisdiction=Jurisdiction.CHINA,
                category="network",
                action="access_foreign_services",
                level=ComplianceLevel.RESTRICTED,
                description="Доступ к иностранным сервисам через Great Firewall",
                requires_approval=True
            ),

            # Общие правила
            ComplianceRule(
                jurisdiction=Jurisdiction.UNKNOWN,
                category="security",
                action="store_sensitive_data",
                level=ComplianceLevel.REQUIRES_APPROVAL,
                description="Хранение чувствительных данных требует проверки",
                requires_approval=True
            ),
        ]

    def check_action(self, action: str, category: str = "general",
                    context: Optional[Dict[str, Any]] = None) -> ComplianceCheck:
        """
        Проверка действия на compliance.

        Args:
            action: Действие для проверки
            category: Категория действия
            context: Дополнительный контекст

        Returns:
            Результат проверки
        """
        context = context or {}

        # Поиск подходящих правил
        applicable_rules = []
        for rule in self._rules:
            if (rule.jurisdiction in (self._current_jurisdiction, Jurisdiction.UNKNOWN) and
                (rule.category == category or rule.category == "general") and
                (rule.action == action or rule.action == "general")):
                applicable_rules.append(rule)

        if not applicable_rules:
            # Нет специфических правил - разрешено
            return ComplianceCheck(
                action=action,
                jurisdiction=self._current_jurisdiction,
                level=ComplianceLevel.ALLOWED,
                allowed=True,
                message="No specific compliance rules found",
                requires_approval=False,
                blocked_actions=[]
            )

        # Выбор самого строгого правила
        strictest_rule = max(applicable_rules,
                           key=lambda r: ["allowed", "requires_approval", "restricted", "prohibited"].index(r.level.value))

        allowed = strictest_rule.level != ComplianceLevel.PROHIBITED
        requires_approval = (strictest_rule.level == ComplianceLevel.REQUIRES_APPROVAL or
                           strictest_rule.requires_approval)

        blocked_actions = []
        if not allowed and strictest_rule.auto_block:
            blocked_actions = [action]

        return ComplianceCheck(
            action=action,
            jurisdiction=self._current_jurisdiction,
            level=strictest_rule.level,
            allowed=allowed,
            message=strictest_rule.description,
            requires_approval=requires_approval,
            blocked_actions=blocked_actions
        )

    def check_content(self, content: str) -> ComplianceCheck:
        """Проверка контента на compliance."""
        # Проверка на запрещенные паттерны
        prohibited_patterns = [
            r"(?i)hack|crack|exploit",  # Хакинг
            r"(?i)illegal|наркотики|оружие",  # Незаконные действия
            r"(?i)personal.*data|персональные.*данные",  # Персональные данные
        ]

        for pattern in prohibited_patterns:
            if re.search(pattern, content):
                return ComplianceCheck(
                    action="generate_content",
                    jurisdiction=self._current_jurisdiction,
                    level=ComplianceLevel.PROHIBITED,
                    allowed=False,
                    message=f"Content matches prohibited pattern: {pattern}",
                    requires_approval=False,
                    blocked_actions=["generate_content"]
                )

        return ComplianceCheck(
            action="generate_content",
            jurisdiction=self._current_jurisdiction,
            level=ComplianceLevel.ALLOWED,
            allowed=True,
            message="Content appears compliant",
            requires_approval=False,
            blocked_actions=[]
        )

    def get_jurisdiction_info(self) -> Dict[str, Any]:
        """Информация о текущей юрисдикции."""
        return {
            "detected_jurisdiction": self._current_jurisdiction.value,
            "rules_count": len(self._rules),
            "jurisdictions_covered": list(set(r.jurisdiction.value for r in self._rules)),
            "auto_block_enabled": any(r.auto_block for r in self._rules)
        }

    def add_custom_rule(self, rule: ComplianceRule) -> None:
        """Добавление кастомного правила."""
        self._rules.append(rule)
        log.info("Added custom compliance rule: %s", rule.description)

    def export_rules(self, filepath: Path) -> None:
        """Экспорт правил в файл."""
        import json

        rules_data = [
            {
                "jurisdiction": r.jurisdiction.value,
                "category": r.category,
                "action": r.action,
                "level": r.level.value,
                "description": r.description,
                "requires_approval": r.requires_approval,
                "auto_block": r.auto_block
            }
            for r in self._rules
        ]

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(rules_data, f, indent=2, ensure_ascii=False)

        log.info("Exported %d compliance rules to %s", len(rules_data), filepath)


# Глобальный экземпляр
compliance_checker = ComplianceChecker()