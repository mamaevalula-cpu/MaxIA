from typing import Callable, Dict, Any
import asyncio
import logging

logger = logging.getLogger(__name__)

class MessageBus:
    """Event-driven message bus for inter-agent communication."""

    def __init__(self):
        self._subscribers: Dict[str, list[Callable]] = {}

    def subscribe(self, event_type: str, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Subscribe a callback to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed callback to event '{event_type}'")

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish an event to all subscribers."""
        if event_type not in self._subscribers:
            return
        for callback in self._subscribers[event_type]:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(payload)
                else:
                    callback(payload)
            except Exception as e:
                logger.error(f"Error in subscriber for {event_type}: {e}", exc_info=True)

    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe a callback from an event type."""
        if event_type in self._subscribers and callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)
            logger.debug(f"Unsubscribed callback from event '{event_type}'")

# Global message bus instance
message_bus = MessageBus()