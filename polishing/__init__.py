"""
Polishing layer — автоматическое улучшение системы.

Обеспечивает:
- Поиск и исправление слабых мест
- Оптимизацию производительности
- Улучшение пользовательского опыта
- Автоматическое тестирование после изменений
"""

from .polisher import SystemPolisher, system_polisher

__all__ = ["SystemPolisher", "system_polisher"]