#!/usr/bin/env python3
"""Agent Family Coordinator — strict hierarchy, shared state, decision bus."""
import threading, time, logging, json
from pathlib import Path
from typing import Dict, List, Any, Optional, Callable

log = logging.getLogger("agent_coordinator")
FAMILY_LOG = Path("/root/my_personal_ai/logs/family_decisions.jsonl")

ROLE_PRIORITY = {
    "chief_orchestrator": 10, "planner": 8, "analyzer": 7,
    "trading": 6, "fin_agent": 6, "sales_agent": 5,
    "key_manager": 5, "monitor": 4, "telegram": 4,
    "self_training": 3, "coder": 5, "browser": 3,
}

class AgentCoordinator:
    """Central bus for agent family — routes events, resolves conflicts."""
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self):
        self._subscribers: Dict[str, List] = {}
        self._shared: Dict[str, Any] = {
            "market_sentiment": "neutral",
            "active_strategies": [],
            "risk_level": "normal",
            "last_prices": {},
            "learning_insights": [],
            "active_leads": {},
            "pending_invoices": [],
        }
        self._state_lock = threading.Lock()
        log.info("AgentCoordinator: family initialized")

    def subscribe(self, event_type: str, agent_name: str, callback: Callable):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append((agent_name, callback))

    def broadcast(self, event_type: str, sender: str, data: Any):
        self._log("broadcast", sender, event_type, data)
        for agent, cb in self._subscribers.get(event_type, []):
            if agent != sender:
                try: cb(sender, event_type, data)
                except Exception as e: log.error("Broadcast to %s: %s", agent, e)

    def update_shared(self, key: str, value: Any, sender: str = "system"):
        with self._state_lock:
            old = self._shared.get(key)
            self._shared[key] = value
        self._log("state_update", sender, key, {"old": str(old)[:50], "new": str(value)[:50]})

    def get_shared(self, key: str = None) -> Any:
        with self._state_lock:
            return self._shared.get(key) if key else dict(self._shared)

    def decide(self, topic: str, proposals: Dict[str, Any]) -> Any:
        """Multi-agent decision: ChiefOrchestrator wins, else highest priority."""
        if "chief_orchestrator" in proposals:
            winner, decision = "chief_orchestrator", proposals["chief_orchestrator"]
        else:
            winner = max(proposals, key=lambda a: ROLE_PRIORITY.get(a, 0))
            decision = proposals[winner]
        self._log("family_decision", winner, topic, {
            "proposals": {k: str(v)[:80] for k,v in proposals.items()},
            "decision": str(decision)[:200],
        })
        return decision

    def _log(self, etype: str, sender: str, topic: str, data: Any):
        entry = {"ts": time.time(), "event": etype, "sender": sender,
                 "topic": topic, "data": data}
        FAMILY_LOG.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(FAMILY_LOG, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except Exception: pass

    def status(self) -> dict:
        return {
            "shared_state": self.get_shared(),
            "subscriptions": {k: [a for a,_ in v] for k,v in self._subscribers.items()},
        }
