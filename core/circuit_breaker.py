"""Circuit Breaker for agent processes."""
import threading, time, logging
from enum import Enum
from typing import Callable, Optional

log = logging.getLogger(__name__)

class CBState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

class CircuitBreaker:
    def __init__(self, name: str, fail_threshold: int = 3,
                 reset_timeout: float = 60.0,
                 alert_callback: Optional[Callable] = None):
        self.name = name
        self.fail_threshold = fail_threshold
        self.reset_timeout = reset_timeout
        self.alert_callback = alert_callback
        self._state = CBState.CLOSED
        self._failures = 0
        self._last_fail = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CBState:
        with self._lock:
            if self._state == CBState.OPEN:
                if time.time() - self._last_fail >= self.reset_timeout:
                    self._state = CBState.HALF_OPEN
                    log.info("CircuitBreaker %s -> HALF_OPEN", self.name)
            return self._state

    def record_success(self):
        with self._lock:
            self._failures = 0
            self._state = CBState.CLOSED

    def record_failure(self):
        with self._lock:
            self._failures += 1
            self._last_fail = time.time()
            if self._failures >= self.fail_threshold:
                prev = self._state
                self._state = CBState.OPEN
                if prev != CBState.OPEN:
                    log.warning("CircuitBreaker %s OPEN after %d failures", self.name, self._failures)
                    self._write_log()
                    if self.alert_callback:
                        try: self.alert_callback(f"[CIRCUIT OPEN] {self.name}: {self._failures} failures")
                        except: pass

    def _write_log(self):
        try:
            import os
            os.makedirs("/root/my_personal_ai/logs", exist_ok=True)
            with open("/root/my_personal_ai/logs/circuit.log", "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} OPEN {self.name} failures={self._failures}\n")
        except: pass

    def is_allowed(self) -> bool:
        return self.state != CBState.OPEN

    def __repr__(self):
        return f"CB({self.name},{self.state.value},{self._failures}fails)"


class ProcessCircuitBreaker:
    """Registry of circuit breakers per agent/process."""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "ProcessCircuitBreaker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._breakers: dict = {}
        self._alert_cb = None

    def set_alert_callback(self, cb: Callable):
        self._alert_cb = cb
        for b in self._breakers.values():
            b.alert_callback = cb

    def get_or_create(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, alert_callback=self._alert_cb)
        return self._breakers[name]

    def record_success(self, name: str):
        self.get_or_create(name).record_success()

    def record_failure(self, name: str):
        self.get_or_create(name).record_failure()

    def is_allowed(self, name: str) -> bool:
        return self.get_or_create(name).is_allowed()

    def status_all(self) -> dict:
        return {n: {"state": b.state.value, "failures": b._failures}
                for n, b in self._breakers.items()}
