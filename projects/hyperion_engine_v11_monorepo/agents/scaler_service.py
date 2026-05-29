"""
agents/scaler_service.py  —  Auto-scaler for Корпорация MaxAI v11.

Monitors task queue depth and active worker count, then emits
scale-up / scale-down signals via MessageBus.  No Kubernetes
dependency required — uses a simple threshold policy.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict

from libs.messaging import bus

logger = logging.getLogger(__name__)


@dataclass
class ScalerConfig:
    check_interval_s: float = 5.0
    queue_high_watermark: int = 50      # scale up if queue > this
    queue_low_watermark: int = 5        # scale down if queue < this
    min_workers: int = 1
    max_workers: int = 16
    scale_up_step: int = 2
    scale_down_step: int = 1
    cooldown_s: float = 30.0            # min time between scale actions


class ScalerService:
    """
    Reads queue-depth metrics from the bus and emits scale signals.

    Downstream components subscribe to 'scaler.scale_up' / 'scaler.scale_down'
    and spin workers up/down accordingly.
    """

    def __init__(self, config: ScalerConfig | None = None) -> None:
        self._cfg = config or ScalerConfig()
        self._metrics: Dict[str, float] = {"queue_depth": 0, "active_workers": 0}
        self._last_scale_at: float = 0.0
        self._running = False

        bus.subscribe("metrics.queue_depth", self._on_queue_depth)
        bus.subscribe("metrics.active_workers", self._on_active_workers)

    async def _on_queue_depth(self, msg) -> None:
        self._metrics["queue_depth"] = float(msg.payload.get("value", 0))

    async def _on_active_workers(self, msg) -> None:
        self._metrics["active_workers"] = float(msg.payload.get("value", 0))

    def _in_cooldown(self) -> bool:
        return (time.time() - self._last_scale_at) < self._cfg.cooldown_s

    async def _evaluate(self) -> None:
        if self._in_cooldown():
            return

        depth = self._metrics["queue_depth"]
        workers = int(self._metrics["active_workers"])

        if depth > self._cfg.queue_high_watermark and workers < self._cfg.max_workers:
            new_count = min(workers + self._cfg.scale_up_step, self._cfg.max_workers)
            await bus.publish("scaler.scale_up", {
                "current_workers": workers,
                "target_workers": new_count,
                "reason": f"queue_depth={depth} > high_watermark={self._cfg.queue_high_watermark}",
            })
            logger.info("Scale UP: %d -> %d workers (queue=%d)", workers, new_count, depth)
            self._last_scale_at = time.time()

        elif depth < self._cfg.queue_low_watermark and workers > self._cfg.min_workers:
            new_count = max(workers - self._cfg.scale_down_step, self._cfg.min_workers)
            await bus.publish("scaler.scale_down", {
                "current_workers": workers,
                "target_workers": new_count,
                "reason": f"queue_depth={depth} < low_watermark={self._cfg.queue_low_watermark}",
            })
            logger.info("Scale DOWN: %d -> %d workers (queue=%d)", workers, new_count, depth)
            self._last_scale_at = time.time()

    async def start(self) -> None:
        self._running = True
        logger.info("ScalerService started (interval=%.1fs)", self._cfg.check_interval_s)
        while self._running:
            await self._evaluate()
            await asyncio.sleep(self._cfg.check_interval_s)

    def stop(self) -> None:
        self._running = False
        logger.info("ScalerService stopped")
