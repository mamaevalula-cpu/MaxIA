# -*- coding: utf-8 -*-
"""
monitoring/watchdog.py — DELEGATOR to core/watchdog.py (canonical implementation).

This module exists for backwards compatibility. All new code should import
from core.watchdog directly:
    from core.watchdog import SystemWatchdog, CircuitBreaker, HealthCheck

The original full Watchdog/ComponentInfo/ComponentState classes are kept here
for any legacy code that may import them, but they delegate to SystemWatchdog
where possible.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("monitoring.watchdog")

# ── Re-export canonical implementations ──────────────────────────────────────

from core.watchdog import SystemWatchdog, CircuitBreaker, HealthCheck

__all__ = [
    "SystemWatchdog", "CircuitBreaker", "HealthCheck",
    "Watchdog", "ComponentState", "ComponentInfo",
]


# ── Legacy shims (kept for backward compat) ───────────────────────────────────

class ComponentState(Enum):
    STARTING  = "starting"
    RUNNING   = "running"
    DEGRADED  = "degraded"
    STOPPED   = "stopped"
    FAILED    = "failed"
    RESTARTING= "restarting"


@dataclass
class ComponentInfo:
    """Lightweight component descriptor — delegates health checks to SystemWatchdog."""
    name:           str
    start_fn:       Optional[Callable] = None
    stop_fn:        Optional[Callable] = None
    health_check:   Optional[Callable[[], bool]] = None
    restart_limit:  int = 3
    restart_delay:  float = 5.0

    state:          ComponentState = ComponentState.STOPPED
    start_time:     float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    restart_count:  int = 0

    def uptime(self) -> float:
        return time.time() - self.start_time

    def time_since_heartbeat(self) -> float:
        return time.time() - self.last_heartbeat

    def is_healthy(self) -> bool:
        if self.health_check:
            try:
                return bool(self.health_check())
            except Exception:
                return False
        return self.state == ComponentState.RUNNING


class Watchdog:
    """
    Legacy Watchdog — thin wrapper around SystemWatchdog.
    New code should use SystemWatchdog directly.
    """

    def __init__(self) -> None:
        self._components: Dict[str, ComponentInfo] = {}
        self._lock = threading.Lock()
        self._system = SystemWatchdog.get()
        log.debug("monitoring.Watchdog created (delegates to core.SystemWatchdog)")

    def register_component(
        self,
        name: str,
        start_fn: Optional[Callable] = None,
        stop_fn: Optional[Callable] = None,
        health_check: Optional[Callable[[], bool]] = None,
        restart_limit: int = 3,
        restart_delay: float = 5.0,
    ) -> None:
        with self._lock:
            self._components[name] = ComponentInfo(
                name=name,
                start_fn=start_fn,
                stop_fn=stop_fn,
                health_check=health_check,
                restart_limit=restart_limit,
                restart_delay=restart_delay,
            )

    def start_component(self, name: str) -> bool:
        with self._lock:
            comp = self._components.get(name)
        if not comp:
            return False
        try:
            if comp.start_fn:
                comp.start_fn()
            comp.state = ComponentState.RUNNING
            comp.last_heartbeat = time.time()
            return True
        except Exception as e:
            log.error("start_component %s failed: %s", name, e)
            comp.state = ComponentState.FAILED
            return False

    def stop_component(self, name: str, graceful: bool = True) -> bool:
        with self._lock:
            comp = self._components.get(name)
        if not comp:
            return False
        try:
            if comp.stop_fn:
                comp.stop_fn()
            comp.state = ComponentState.STOPPED
            return True
        except Exception as e:
            log.error("stop_component %s failed: %s", name, e)
            return False

    def restart_component(self, name: str) -> bool:
        self.stop_component(name)
        time.sleep(0.5)
        return self.start_component(name)

    def send_heartbeat(self, name: str) -> None:
        with self._lock:
            comp = self._components.get(name)
            if comp:
                comp.last_heartbeat = time.time()
                comp.state = ComponentState.RUNNING

    def start_monitoring(self) -> None:
        """Delegate to SystemWatchdog.start()."""
        self._system.start()

    def stop_monitoring(self) -> None:
        """Delegate to SystemWatchdog.stop()."""
        self._system.stop()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                name: {
                    "state":     comp.state.value,
                    "uptime":    comp.uptime(),
                    "restarts":  comp.restart_count,
                    "healthy":   comp.is_healthy(),
                }
                for name, comp in self._components.items()
            }
