"""
Compliance layer — проверка законов и регуляций.

Обеспечивает:
- Соответствие законам разных стран
- Защиту от рискованных действий
- Автоматическую блокировку запрещенных операций
"""

from .compliance_checker import ComplianceChecker, compliance_checker

__all__ = ["ComplianceChecker", "compliance_checker"]