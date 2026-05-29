# family/__init__.py
"""
Unified AI Family — единое ядро всех компонентов.

Архитектура:
  FamilyBus            → cross-process SQLite event bus
  FamilyController     → главный координатор семьи
  KnowledgeBroadcaster → безопасное распространение знаний
  FamilyHealthMonitor  → мониторинг всех компонентов
"""
from family.family_bus import FamilyBus, FamilyEvent, EventKind
from family.family_controller import FamilyController
from family.knowledge_broadcaster import KnowledgeBroadcaster, KnowledgeScope
from family.health_monitor import FamilyHealthMonitor, ComponentStatus

__all__ = [
    "FamilyBus", "FamilyEvent", "EventKind",
    "FamilyController",
    "KnowledgeBroadcaster", "KnowledgeScope",
    "FamilyHealthMonitor", "ComponentStatus",
]
