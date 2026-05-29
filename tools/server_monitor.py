# -*- coding: utf-8 -*-
"""
tools/server_monitor.py — Real-time server resource monitoring.

Uses psutil to provide AI agents with system resource info.
"""
from __future__ import annotations
import logging, time, threading
from typing import Dict, Any, Optional
import psutil

log = logging.getLogger("tools.server_monitor")


class ServerMonitor:
    """
    Singleton. Monitors CPU, RAM, disk, network in real-time.
    Runs in background thread, exposes metrics to AI agents.
    """

    _instance: Optional["ServerMonitor"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._stats: Dict[str, Any] = {}
        self._stop  = threading.Event()
        self._poll_interval = 30  # seconds
        threading.Thread(target=self._loop, daemon=True, name="server-monitor").start()
        log.info("ServerMonitor started")

    @classmethod
    def get(cls) -> "ServerMonitor":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._collect()
            except Exception as e:
                log.debug("Monitor collect error: %s", e)
            self._stop.wait(self._poll_interval)

    def _collect(self):
        cpu_pct  = psutil.cpu_percent(interval=1)
        mem      = psutil.virtual_memory()
        disk     = psutil.disk_usage('/')
        net      = psutil.net_io_counters()
        load     = psutil.getloadavg()

        self._stats = {
            "cpu_pct":        round(cpu_pct, 1),
            "cpu_count":      psutil.cpu_count(),
            "load_1m":        round(load[0], 2),
            "load_5m":        round(load[1], 2),
            "load_15m":       round(load[2], 2),
            "ram_total_gb":   round(mem.total / 1e9, 1),
            "ram_used_gb":    round(mem.used / 1e9, 1),
            "ram_avail_gb":   round(mem.available / 1e9, 1),
            "ram_pct":        mem.percent,
            "disk_total_gb":  round(disk.total / 1e9, 0),
            "disk_used_gb":   round(disk.used / 1e9, 1),
            "disk_free_gb":   round(disk.free / 1e9, 1),
            "disk_pct":       disk.percent,
            "net_sent_mb":    round(net.bytes_sent / 1e6, 1),
            "net_recv_mb":    round(net.bytes_recv / 1e6, 1),
            "ts":             time.time(),
        }

    def get_stats(self) -> Dict[str, Any]:
        if not self._stats:
            self._collect()
        return self._stats.copy()

    def get_summary(self) -> str:
        """Return human-readable resource summary for AI responses."""
        s = self.get_stats()
        cpu_alert  = "⚠️" if s["cpu_pct"] > 80 else ""
        ram_alert  = "⚠️" if s["ram_pct"] > 85 else ""
        disk_alert = "⚠️" if s["disk_pct"] > 90 else ""

        return (
            f"🖥️ **Сервер AMD Ryzen 9 9950X3D**\n"
            f"• CPU: {s['cpu_pct']}% ({s['cpu_count']} ядер) {cpu_alert} | Load: {s['load_1m']}/{s['load_5m']}/{s['load_15m']}\n"
            f"• RAM: {s['ram_used_gb']:.1f}/{s['ram_total_gb']:.0f} GB ({s['ram_pct']:.0f}%) {ram_alert} | Свободно: {s['ram_avail_gb']:.1f} GB\n"
            f"• Диск: {s['disk_used_gb']:.0f}/{s['disk_total_gb']:.0f} GB ({s['disk_pct']:.0f}%) {disk_alert}\n"
            f"• Сеть: ↑{s['net_sent_mb']:.0f} MB / ↓{s['net_recv_mb']:.0f} MB"
        )

    def check_alerts(self) -> list:
        """Return list of resource alert strings."""
        s = self.get_stats()
        alerts = []
        if s["cpu_pct"] > 85:   alerts.append(f"🔴 CPU перегружен: {s['cpu_pct']}%")
        if s["ram_pct"] > 90:   alerts.append(f"🔴 RAM почти заполнена: {s['ram_pct']}%")
        if s["disk_pct"] > 90:  alerts.append(f"🔴 Диск почти заполнен: {s['disk_pct']}%")
        if s["load_1m"] > s["cpu_count"] * 2:
            alerts.append(f"🟡 Высокая нагрузка: load={s['load_1m']}")
        return alerts
