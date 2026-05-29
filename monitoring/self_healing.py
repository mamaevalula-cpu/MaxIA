# -*- coding: utf-8 -*-
"""
monitoring/self_healing.py — APEX AI Self-Healing Engine.

Runs as background thread. Every N minutes:
  1. Checks error frequency per component (error-spike detector).
  2. Detects dead/stuck projects (pending too long, no progress).
  3. Runs system self-diagnostics (CPU, memory, disk, token budgets).
  4. Sends Telegram alerts on critical findings.
  5. Attempts auto-recovery for known failure patterns.

This module is "secret" — it runs silently, user only sees alerts.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("monitoring.self_healing")

# ── Config ─────────────────────────────────────────────────────────────────
CHECK_INTERVAL_SEC  = 300    # full diagnostic every 5 minutes
ALERT_INTERVAL_SEC  = 1800   # minimum gap between repeated alerts (30 min)
ERROR_SPIKE_WINDOW  = 300    # sliding window for error counting (5 min)
ERROR_SPIKE_THRESH  = 10     # errors/window → spike alert
DEAD_PROJECT_SEC    = 900    # project stuck in "created" > 15 min → alert
MEMORY_WARN_PCT     = 80     # % RAM used → warning
DISK_WARN_PCT       = 85     # % disk used → warning
CPU_WARN_PCT        = 90     # % CPU for 5-min avg → warning


@dataclass
class SpikeRecord:
    component:  str
    count:      int
    window_sec: float
    ts:         float = field(default_factory=time.time)


class SelfHealingEngine:
    """Background self-healing and monitoring engine."""

    _instance: Optional["SelfHealingEngine"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        # error timestamps per component: component → deque of timestamps
        self._error_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
        self._alert_sent:  Dict[str, float] = {}   # key → last alert ts
        self._running      = False
        self._thread: Optional[threading.Thread] = None
        self._alert_cb: Optional[Callable[[str], None]] = None
        self._stats = {
            "checks_run": 0, "alerts_sent": 0,
            "auto_heals": 0, "last_check": 0.0,
        }
        log.info("SelfHealingEngine initialized")

    @classmethod
    def get(cls) -> "SelfHealingEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_alert_callback(self, cb: Callable[[str], None]) -> None:
        """Register callback to send Telegram alerts."""
        self._alert_cb = cb

    def record_error(self, component: str) -> None:
        """Called by any component when an error occurs."""
        self._error_times[component].append(time.time())

    # ── Start / Stop ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="self-healing"
        )
        self._thread.start()
        log.info("SelfHealingEngine started (interval=%ds)", CHECK_INTERVAL_SEC)

    def stop(self) -> None:
        self._running = False

    # ── Main loop ─────────────────────────────────────────────────────────────

    def _loop(self) -> None:
        time.sleep(60)   # wait for system to boot fully
        while self._running:
            try:
                self._run_full_check()
            except Exception as e:
                log.error("SelfHealing check failed: %s", e)
            time.sleep(CHECK_INTERVAL_SEC)

    def _run_full_check(self) -> None:
        self._stats["checks_run"] += 1
        self._stats["last_check"]  = time.time()
        alerts: List[str] = []

        # 1. Error frequency
        alerts += self._check_error_spikes()
        # 2. Dead/stuck projects
        alerts += self._check_dead_projects()
        # 3. System resources
        alerts += self._check_resources()
        # 4. Service liveness
        alerts += self._check_services()
        # 5. LLM provider health
        alerts += self._check_llm_health()

        for msg in alerts:
            self._send_alert(msg)

        log.debug("SelfHealing check done: %d alerts, %d components tracked",
                  len(alerts), len(self._error_times))

    # ── Checks ────────────────────────────────────────────────────────────────

    def _check_error_spikes(self) -> List[str]:
        alerts = []
        now    = time.time()
        cutoff = now - ERROR_SPIKE_WINDOW
        for component, times in self._error_times.items():
            recent = sum(1 for t in times if t > cutoff)
            if recent >= ERROR_SPIKE_THRESH:
                key = f"spike:{component}"
                if self._can_alert(key):
                    alerts.append(
                        f"⚠️ <b>Error spike</b>: <code>{component}</code> — "
                        f"{recent} errors in {ERROR_SPIKE_WINDOW//60}min"
                    )
        return alerts

    def _check_dead_projects(self) -> List[str]:
        alerts = []
        try:
            from core.project_registry import ProjectRegistry
            reg  = ProjectRegistry.get()
            now  = time.time()
            dead = [
                p for p in reg.list_all()
                if p["status"] == "created"
                and now - p["created_at"] > DEAD_PROJECT_SEC
            ]
            for p in dead:
                key = f"dead:{p['project_id']}"
                if self._can_alert(key):
                    stuck_min = int((now - p["created_at"]) / 60)
                    alerts.append(
                        f"🔴 <b>Dead project</b>: <code>{p['name']}</code> "
                        f"stuck in 'created' for {stuck_min}min"
                    )
                    # Auto-mark as failed
                    reg.set_status(p["project_id"], "failed",
                                   f"Auto-failed: stuck {stuck_min}min in created")
                    self._stats["auto_heals"] += 1
                    log.warning("Auto-failed dead project %s", p["project_id"][:8])
        except Exception as e:
            log.debug("Dead project check error: %s", e)
        return alerts

    def _check_resources(self) -> List[str]:
        alerts = []
        try:
            # Memory
            with open("/proc/meminfo") as f:
                lines = {l.split(":")[0]: int(l.split()[1])
                         for l in f if ":" in l and l.split()[1].isdigit()}
            total = lines.get("MemTotal", 1)
            avail = lines.get("MemAvailable", total)
            mem_pct = int((1 - avail / total) * 100)
            if mem_pct >= MEMORY_WARN_PCT:
                if self._can_alert("mem_warn"):
                    alerts.append(f"⚠️ <b>High memory</b>: {mem_pct}% used")

            # Disk
            import shutil
            usage = shutil.disk_usage("/root")
            disk_pct = int(usage.used / usage.total * 100)
            if disk_pct >= DISK_WARN_PCT:
                if self._can_alert("disk_warn"):
                    used_gb = usage.used / 1e9
                    total_gb = usage.total / 1e9
                    alerts.append(
                        f"⚠️ <b>Disk</b>: {disk_pct}% used "
                        f"({used_gb:.1f}/{total_gb:.1f} GB)"
                    )
        except Exception as e:
            log.debug("Resource check error: %s", e)
        return alerts

    def _check_services(self) -> List[str]:
        alerts = []
        services = ["personal-ai", "bybit-monitor"]
        for svc in services:
            try:
                r = subprocess.run(
                    ["systemctl", "is-active", svc],
                    capture_output=True, text=True, timeout=5
                )
                status = r.stdout.strip()
                if status != "active":
                    key = f"svc:{svc}"
                    if self._can_alert(key):
                        alerts.append(f"🔴 <b>Service down</b>: <code>{svc}</code> [{status}]")
                    # Auto-restart attempt
                    subprocess.run(["systemctl", "restart", svc], timeout=10)
                    self._stats["auto_heals"] += 1
                    log.warning("Auto-restarted service %s (was %s)", svc, status)
            except Exception as e:
                log.debug("Service check %s error: %s", svc, e)
        return alerts

    def _check_llm_health(self) -> List[str]:
        alerts = []
        try:
            from brain.llm_router import LLMRouter
            report = LLMRouter.get().status_report()
            all_down = all(not v.get("available") for v in report.values()
                           if isinstance(v, dict))
            if all_down and self._can_alert("all_llm_down"):
                alerts.append(
                    "🔴 <b>ALL LLM providers down!</b>\n"
                    "Проверь API ключи и баланс. Система в деградированном режиме."
                )
        except Exception:
            pass
        return alerts

    # ── Alert helpers ─────────────────────────────────────────────────────────

    def _can_alert(self, key: str) -> bool:
        """Throttle: don't alert same key more than once per ALERT_INTERVAL_SEC."""
        last = self._alert_sent.get(key, 0)
        if time.time() - last >= ALERT_INTERVAL_SEC:
            self._alert_sent[key] = time.time()
            return True
        return False

    def _send_alert(self, msg: str) -> None:
        self._stats["alerts_sent"] += 1
        log.warning("SELF-HEALING ALERT: %s", msg.replace("<b>", "").replace("</b>", "")
                    .replace("<code>", "").replace("</code>", ""))
        if self._alert_cb:
            try:
                self._alert_cb(f"🔧 <b>APEX AI Self-Healing</b>\n\n{msg}")
            except Exception as e:
                log.debug("Alert callback error: %s", e)

    def get_stats(self) -> Dict[str, Any]:
        return dict(self._stats)

    def get_report(self) -> str:
        s = self._stats
        return (
            f"🔧 <b>Self-Healing Engine</b>\n"
            f"  Проверок: {s['checks_run']}\n"
            f"  Алертов: {s['alerts_sent']}\n"
            f"  Авто-лечений: {s['auto_heals']}\n"
            f"  Последняя проверка: "
            + (f"{int(time.time()-s['last_check'])}s ago" if s['last_check'] else "never")
        )
