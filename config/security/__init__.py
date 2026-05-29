# -*- coding: utf-8 -*-
"""Security configuration module."""

from .security_domains import (
    DOMAIN_A,
    DOMAIN_B,
    DOMAIN_FIREWALL,
    SecurityDomain,
    can_agent_access_internet,
    can_agent_access_keys,
    can_agent_execute_code,
    get_agent_policy,
    requires_firewall_check,
    requires_user_confirmation,
)

__all__ = [
    "SecurityDomain",
    "DOMAIN_A",
    "DOMAIN_B",
    "DOMAIN_FIREWALL",
    "get_agent_policy",
    "can_agent_access_internet",
    "can_agent_access_keys",
    "can_agent_execute_code",
    "requires_firewall_check",
    "requires_user_confirmation",
]
