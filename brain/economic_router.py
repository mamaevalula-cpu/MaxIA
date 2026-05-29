from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, List

import pika
from pika.exceptions import AMQPError

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from core.config import cfg
from brain.rabbitmq import rabbit_conn

log = logging.getLogger("brain.economic_router")

# In-memory metrics store (for production use Redis/Prometheus)
metrics_store: Dict[str, Any] = {
    "agents": {
        "total": 0,
        "active": 0,
        "idle": 0,
        "busy": 0,
        "by_channel": {}
    },
    "revenue": {
        "total_usd": 0.0,
        "today_usd": 0.0,
        "by_channel": {},
        "last_updated": None
    },
    "channels": {
        "high_priority": {"tasks_processed": 0, "revenue_generated": 0.0},
        "medium_priority": {"tasks_processed": 0, "revenue_generated": 0.0},
        "low_priority": {"tasks_processed": 0, "revenue_generated": 0.0}
    }
}

@dataclass
class TaskValuation:
    task_id: str
    urgency_score: float
    strategic_score: float
    expected_value: float
    channel: str = ""
    processed_at: Optional[datetime] = None

    def __post_init__(self):
        if self.processed_at is None:
            self.processed_at = datetime.utcnow()

class EconomicRouter:
    def __init__(self, rabbit_conn: pika.BlockingConnection):
        self.rabbit_conn = rabbit_conn
        self.channel = rabbit_conn.channel()
        self.channel.queue_declare(queue='receive', durable=True)

    def route_task(self, task_valuation: TaskValuation) -> None:
        """Route a task based on valuation metrics and update internal metrics."""
        try:
            if task_valuation.urgency_score > 5 and task_valuation.strategic_score > 5:
                routing_key = 'high_priority'
                exchange = 'hyperion.v12.1.core'
            elif task_valuation.expected_value > 10000:
                routing_key = 'medium_priority'
                exchange = 'hyperion.v12.1.core'
            else:
                routing_key = 'low_priority'
                exchange = 'hyperion.v12.1.dlx'

            task_valuation.channel = routing_key
            task_valuation.processed_at = datetime.utcnow()

            self.channel.basic_publish(
                exchange=exchange,
                routing_key=routing_key,
                body=json.dumps(task_valuation.__dict__, default=str)
            )

            # Update in-memory metrics
            self._update_metrics(task_valuation, routing_key)

            log.info(f"Task {task_valuation.task_id} routed to {routing_key}")
        except AMQPError as e:
            log.error(f"Error routing task {task_valuation.task_id}: {e}")

    def _update_metrics(self, task: TaskValuation, routing_key: str) -> None:
        """Update internal metrics when a task is processed."""
        global metrics_store

        # Revenue tracking
        metrics_store["revenue"]["total_usd"] += task.expected_value
        metrics_store["revenue"]["today_usd"] += task.expected_value
        metrics_store["revenue"]["last_updated"] = datetime.utcnow().isoformat()

        # Channel performance
        if routing_key in metrics_store["channels"]:
            metrics_store["channels"][routing_key]["tasks_processed"] += 1
            metrics_store["channels"][routing_key]["revenue_generated"] += task.expected_value

        # Revenue by channel
        if routing_key not in metrics_store["revenue"]["by_channel"]:
            metrics_store["revenue"]["by_channel"][routing_key] = 0.0
        metrics_store["revenue"]["by_channel"][routing_key] += task.expected_value

# FastAPI metrics endpoint
metrics_router = APIRouter(prefix="/maxai", tags=["metrics"])

@metrics_router.get("/metrics")
async def get_metrics() -> Dict[str, Any]:
    """Return current system metrics."""
    return JSONResponse(content=metrics_store, status_code=200)

@metrics_router.get("/metrics/agents")
async def get_agents_metrics() -> Dict[str, Any]:
    """Return agent-related metrics."""
    return JSONResponse(content=metrics_store["agents"], status_code=200)

@metrics_router.get("/metrics/revenue")
async def get_revenue_metrics() -> Dict[str, Any]:
    """Return revenue-related metrics."""
    return JSONResponse(content=metrics_store["revenue"], status_code=200)

@metrics_router.get("/metrics/channels")
async def get_channels_metrics() -> Dict[str, Any]:
    """Return channel performance metrics."""
    return JSONResponse(content=metrics_store["channels"], status_code=200)

def register_metrics_endpoint(app: FastAPI) -> None:
    """Register metrics router with a FastAPI application."""
    app.include_router(metrics_router)

def main() -> None:
    """Main entry point for testing."""
    rabbit_conn_instance = rabbit_conn()
    economic_router = EconomicRouter(rabbit_conn_instance)
    
    # Example usage
    task_valuation = TaskValuation("task_1", 6.0, 7.0, 15000.0)
    economic_router.route_task(task_valuation)
    
    # Print current metrics
    print("Current Metrics:")
    print(json.dumps(metrics_store, indent=2, default=str))

if __name__ == '__main__':
    main()
