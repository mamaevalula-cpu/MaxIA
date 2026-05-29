# -*- coding: utf-8 -*-
"""
config/security/security_domains.py — Zero-Trust Security Architecture v2026.4

Разделяет агентов на два изолированных контура безопасности:
  - Контур А [DATA-INSECURE]: доступ в интернет, БЕЗ доступа к API-ключам и локальным файлам
  - Контур Б [EXECUTION-SECURE]: доступ к ключам и выполнению кода, БЕЗ прямого доступа в интернет
  
Коммуникация между контурами ТОЛЬКО через Семантический Файрвол (monitor_agent).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Set

class SecurityDomain(Enum):
    """Уровни изоляции агентов."""
    DATA_INSECURE = "data_insecure"       # Контур А: работа с внешними данными
    EXECUTION_SECURE = "execution_secure" # Контур Б: критичные операции
    FIREWALL = "firewall"                 # Семантический фильтр

@dataclass
class DomainPolicy:
    """Политика безопасности для домена."""
    domain: SecurityDomain
    agents: Set[str]
    
    # Разрешения
    internet_access: bool = False
    filesystem_access: bool = False
    api_keys_access: bool = False
    code_execution: bool = False
    payment_execution: bool = False
    
    # Ограничения
    requires_firewall: bool = False  # Требуется прохождение через firewall
    user_confirmation: bool = False  # Требуется подтверждение пользователя

# ══════════════════════════════════════════════════════════════════════════════
# КОНТУР А [DATA-INSECURE] — Работа с внешними данными
# ══════════════════════════════════════════════════════════════════════════════

DOMAIN_A = DomainPolicy(
    domain=SecurityDomain.DATA_INSECURE,
    agents={
        "search",          # Поиск в интернете
        "browser",         # Браузерная навигация
        "news",            # Новостные агрегаторы
        "web_automation",  # Веб-автоматизация
        "telegram",        # Telegram интеграция
        "email",           # Email обработка
        "summarizer",      # Суммаризация текстов
        "image",           # Обработка изображений
    },
    internet_access=True,
    filesystem_access=False,      # ЗАПРЕТ на доступ к проекту
    api_keys_access=False,        # ЗАПРЕТ на доступ к ключам
    code_execution=False,         # ЗАПРЕТ на выполнение кода
    payment_execution=False,      # ЗАПРЕТ на платежи
    requires_firewall=True,       # Все данные через firewall
)

# ══════════════════════════════════════════════════════════════════════════════
# КОНТУР Б [EXECUTION-SECURE] — Критичные операции
# ══════════════════════════════════════════════════════════════════════════════

DOMAIN_B = DomainPolicy(
    domain=SecurityDomain.EXECUTION_SECURE,
    agents={
        "planner",         # Планирование задач
        "trading",         # Торговые операции
        "payment",         # Платежи
        "key_manager",     # Управление ключами
        "code_runner",     # Выполнение кода
        "coder",           # Генерация кода
        "project_creator", # Создание проектов
        "analyzer",        # Финансовый анализ
        "math",            # Математические расчёты
    },
    internet_access=False,        # ЗАПРЕТ на прямой интернет
    filesystem_access=True,
    api_keys_access=True,
    code_execution=True,
    payment_execution=True,
    requires_firewall=False,      # Работает только с очищенными данными
    user_confirmation=True,       # Критичные действия требуют подтверждения
)

# ══════════════════════════════════════════════════════════════════════════════
# СЕМАНТИЧЕСКИЙ ФАЙРВОЛ — Агент-посредник
# ══════════════════════════════════════════════════════════════════════════════

DOMAIN_FIREWALL = DomainPolicy(
    domain=SecurityDomain.FIREWALL,
    agents={"monitor"},
    internet_access=False,
    filesystem_access=True,  # Для логирования
    api_keys_access=False,
    code_execution=False,
    payment_execution=False,
)

# Полный маппинг агент → политика безопасности
SECURITY_POLICIES = {}
for policy in [DOMAIN_A, DOMAIN_B, DOMAIN_FIREWALL]:
    for agent in policy.agents:
        SECURITY_POLICIES[agent] = policy

def get_agent_policy(agent_name: str) -> DomainPolicy:
    """Получить политику безопасности для агента."""
    return SECURITY_POLICIES.get(agent_name, DOMAIN_B)  # По умолчанию самый строгий

def can_agent_access_internet(agent_name: str) -> bool:
    """Проверить разрешение на доступ в интернет."""
    policy = get_agent_policy(agent_name)
    return policy.internet_access

def can_agent_access_keys(agent_name: str) -> bool:
    """Проверить разрешение на доступ к API-ключам."""
    policy = get_agent_policy(agent_name)
    return policy.api_keys_access

def can_agent_execute_code(agent_name: str) -> bool:
    """Проверить разрешение на выполнение кода."""
    policy = get_agent_policy(agent_name)
    return policy.code_execution

def requires_firewall_check(agent_name: str) -> bool:
    """Проверить необходимость прохождения через firewall."""
    policy = get_agent_policy(agent_name)
    return policy.requires_firewall

def requires_user_confirmation(agent_name: str) -> bool:
    """Проверить необходимость подтверждения пользователя."""
    policy = get_agent_policy(agent_name)
    return policy.user_confirmation
