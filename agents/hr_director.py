#!/usr/bin/env python3
"""
HRDirector — автоматический спавн новых агентов на основе метрик marketplace и revenue goals.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from agents.base_agent import BaseAgent
from agents.agent_factory_agent import AgentFactory
try:
    from core.metrics import MetricsCollector
except ImportError:
    pass
try:
    from core.revenue_goals import RevenueGoals
except ImportError:
    pass
try:
    from tasks.sub import TaskSub
except ImportError:
    pass

logger = logging.getLogger(__name__)


class HRDirector(BaseAgent):
    """HRDirector управляет жизненным циклом агентов на основе бизнес-метрик."""

    def __init__(
        self,
        agent_id: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(agent_id=agent_id, config=config)
        self.metrics_collector: MetricsCollector = MetricsCollector()
        self.revenue_goals: RevenueGoals = RevenueGoals()
        self.task_sub: TaskSub = TaskSub()
        self.factory: AgentFactory = AgentFactory()
        self._spawn_threshold_revenue_gap: float = 0.15  # spawn if gap > 15%
        self._spawn_threshold_market_volatility: float = 0.2
        self._cooldown_minutes: int = 30
        self._last_spawn_time: Optional[datetime] = None
        self._running: bool = False

    async def start(self) -> None:
        """Запуск главного цикла управления."""
        logger.info("HRDirector started for agent %s", self.agent_id)
        self._running = True
        while self._running:
            try:
                await self._evaluate_and_spawn()
                await asyncio.sleep(60)  # check every minute
            except Exception as exc:
                logger.error("HRDirector loop error: %s", exc)
                await asyncio.sleep(5)

    async def stop(self) -> None:
        """Остановка главного цикла."""
        logger.info("HRDirector stopped for agent %s", self.agent_id)
        self._running = False

    async def _evaluate_and_spawn(self) -> None:
        """Оценка метрик и спавн новых агентов при необходимости."""
        current_time = datetime.utcnow()
        if self._last_spawn_time and (current_time - self._last_spawn_time) < timedelta(minutes=self._cooldown_minutes):
            logger.debug("Cooldown active, skipping spawn evaluation")
            return

        metrics = await self.metrics_collector.collect()
        goals = await self.revenue_goals.get_current_goals()

        if not metrics or not goals:
            logger.warning("No metrics or goals available, skipping spawn")
            return

        # Логика спавна: если разрыв между текущим revenue и целью большой,
        # или рыночная волатильность высокая — спавним нового агента.
        should_spawn = False
        reasons: List[str] = []

        # 1. Revenue gap evaluation
        current_revenue = metrics.get("current_revenue", 0.0)
        target_revenue = goals.get("target_revenue", 1.0)
        if target_revenue > 0:
            revenue_gap = (target_revenue - current_revenue) / target_revenue
            if revenue_gap > self._spawn_threshold_revenue_gap:
                should_spawn = True
                reasons.append(f"Revenue gap {revenue_gap:.2%} > threshold {self._spawn_threshold_revenue_gap:.0%}")

        # 2. Market volatility evaluation
        market_volatility = metrics.get("market_volatility", 0.0)
        if market_volatility > self._spawn_threshold_market_volatility:
            should_spawn = True
            reasons.append(f"Market volatility {market_volatility:.2%} > threshold {self._spawn_threshold_market_volatility:.0%}")

        # 3. Если нет явных причин, но количество агентов ниже минимума — тоже спавним
        active_agents_count = metrics.get("active_agents_count", 0)
        min_agents = goals.get("min_agents", 1)
        if active_agents_count < min_agents:
            should_spawn = True
            reasons.append(f"Active agents {active_agents_count} < min required {min_agents}")

        if not should_spawn:
            logger.debug("No conditions met for spawning new agent")
            return

        new_agent = await self.factory.create_agent(
            agent_type="trader",
            config={
                "spawn_reason": "; ".join(reasons),
                "spawned_by": self.agent_id,
                "spawn_timestamp": current_time.isoformat(),
            },
        )
        if new_agent:
            await self.task_sub.register_agent(new_agent)
            logger.info("Spawned new agent %s due to: %s", new_agent.agent_id, "; ".join(reasons))
            self._last_spawn_time = current_time
        else:
            logger.error("Failed to spawn new agent")

    async def get_status(self) -> Dict[str, Any]:
        """Получить статус HRDirector."""
        return {
            "agent_id": self.agent_id,
            "running": self._running,
            "last_spawn_time": self._last_spawn_time.isoformat() if self._last_spawn_time else None,
            "spawn_thresholds": {
                "revenue_gap": self._spawn_threshold_revenue_gap,
                "market_volatility": self._spawn_threshold_market_volatility,
                "cooldown_minutes": self._cooldown_minutes,
            },
        }

    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        """Orchestrator bridge — auto-added."""
        for m in ["run","execute","work","handle","daily_cycle","check","scan","analyze","report","daily_report"]:
            fn = getattr(self, m, None)
            if fn and callable(fn):
                try:
                    r = fn()
                    return str(r)[:400] if r else self.__class__.__name__ + ": ok"
                except Exception as e:
                    return self.__class__.__name__ + f" error: {e}"
        return self.__class__.__name__ + ": ready"
