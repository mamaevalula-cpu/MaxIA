"""
Validation layer — проверка системы от лица пользователя.

Обеспечивает:
- Имитацию реальных сценариев использования
- Проверку UX и функциональности
- Валидацию после изменений
- Автоматическое тестирование
"""

from .user_perspective import UserPerspectiveValidator, user_validator

__all__ = ["UserPerspectiveValidator", "user_validator"]