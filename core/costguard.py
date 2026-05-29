# -*- coding: utf-8 -*-
"""
core/costguard.py — CostGuard: API cost limits + structured output enforcement.

Output Schema (enforced for all non-chat agent responses):
    {
        "decision":  str,   # what was decided
        "action":    str,   # specific next action
        "risk":      "low" | "medium" | "high" | "critical",
        "rollback":  str,   # how to undo if wrong
        "evidence":  str    # external source/metric this is based on
    }

Integrates with LLMRouter cost tracking.
"""
from __future__ import annotations
import json, logging, re, time
from dataclasses import dataclass
from typing import Any, Dict, Optional

log = logging.getLogger("costguard")

# Thresholds (USD/day) — align with guardrail.py levels
LIMIT_WARN   = 3.00
LIMIT_HARD   = 5.00

# Response schema fields
_SCHEMA_FIELDS = ("decision", "action", "risk", "rollback", "evidence")
_RISK_VALUES   = {"low", "medium", "high", "critical"}

# Intents that MUST return structured JSON
_STRUCTURED_INTENTS = {
    "trading", "code_change", "analysis", "project_create",
    "server", "payment", "order", "key_manager",
}

class CostLimitError(Exception):
    """Raised when daily API cost exceeds LIMIT_HARD."""

@dataclass
class SchemaResponse:
    decision:  str = ""
    action:    str = ""
    risk:      str = "low"
    rollback:  str = "revert last change"
    evidence:  str = ""
    raw:       str = ""
    valid:     bool = False

    def to_dict(self) -> Dict[str, str]:
        return {
            "decision": self.decision,
            "action":   self.action,
            "risk":     self.risk,
            "rollback": self.rollback,
            "evidence": self.evidence,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class CostGuard:
    """Singleton that tracks cost and enforces structured output."""

    _instance: Optional["CostGuard"] = None

    @classmethod
    def get(cls) -> "CostGuard":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._daily_cost: float = 0.0
        self._date: str = ""
        self._calls: int = 0

    # ── cost tracking ───────────────────────────────────────────────────────

    def record_call(self, provider: str, tokens: int) -> None:
        """Called after each LLM call to track cost."""
        today = time.strftime("%Y-%m-%d")
        if self._date != today:
            self._daily_cost = 0.0
            self._date = today
            self._calls = 0

        # Approximate cost per provider (USD per 1M tokens)
        _rates = {
            "groq": 0.0,      "cerebras": 0.0,  "ollama": 0.0,
            "claude": 15.0,   "openai": 5.0,    "gemini": 0.35,
            "deepseek": 0.28, "openrouter": 1.0,"mistral": 1.0,
        }
        rate = _rates.get(provider.lower().split(".")[0], 1.0)
        self._daily_cost += (tokens / 1_000_000) * rate
        self._calls += 1

        if self._daily_cost > LIMIT_HARD:
            log.critical("CostGuard: daily cost $%.4f > LIMIT $%.2f", self._daily_cost, LIMIT_HARD)
            raise CostLimitError(
                f"Daily cost ${self._daily_cost:.4f} exceeds hard limit ${LIMIT_HARD:.2f}"
            )

    @property
    def daily_cost(self) -> float:
        return self._daily_cost

    # ── structured output ───────────────────────────────────────────────────

    def parse_structured(self, raw: str, intent: str = "") -> SchemaResponse:
        """
        Try to extract structured JSON from LLM output.
        For non-structured intents returns a synthetic wrapper.
        Prompt-cache compatible: static schema defined at top of system prompt.
        """
        resp = SchemaResponse(raw=raw)

        # Try to find JSON block in response
        json_match = re.search(r'\{[^{}]*"decision"[^{}]*\}', raw, re.DOTALL)
        if not json_match:
            # Try fenced code block
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
            if json_match:
                json_match = type('M', (), {'group': lambda s, n=0: json_match.group(1)})()

        if json_match:
            try:
                data = json.loads(json_match.group())
                resp.decision  = str(data.get("decision", ""))[:500]
                resp.action    = str(data.get("action", ""))[:500]
                resp.risk      = data.get("risk", "low") if data.get("risk") in _RISK_VALUES else "low"
                resp.rollback  = str(data.get("rollback", "revert last change"))[:200]
                resp.evidence  = str(data.get("evidence", ""))[:300]
                resp.valid     = True
                return resp
            except (json.JSONDecodeError, AttributeError):
                pass

        # Fallback: synthesize from raw text for non-structured intents
        if intent not in _STRUCTURED_INTENTS:
            resp.decision = raw[:300] if raw else "no response"
            resp.action   = "continue"
            resp.risk     = "low"
            resp.rollback = "no action taken"
            resp.evidence = "conversational response — no external source required"
            resp.valid    = True
        else:
            # Structured intent but no JSON found — partial parse
            resp.decision = raw[:300] if raw else "no response"
            resp.action   = "manual review required"
            resp.risk     = "medium"
            resp.rollback = "revert to last checkpoint"
            resp.evidence = "raw LLM output — not externally verified"
            resp.valid    = False
            log.warning("CostGuard: structured intent=%s returned unstructured response", intent)

        return resp

    def system_prompt_schema_block(self) -> str:
        """
        Static block to prepend to agent system prompts.
        Placed at TOP of prompt → benefits from Anthropic prompt caching.
        """
        return (
            "## OUTPUT SCHEMA (MANDATORY for action intents)\n"
            "For any decision involving code, trading, server, payments, or projects,\n"
            "respond ONLY with valid JSON matching this schema:\n"
            "```json\n"
            '{"decision": "<what you decided>",\n'
            ' "action":   "<specific next step>",\n'
            ' "risk":     "low|medium|high|critical",\n'
            ' "rollback": "<how to undo>",\n'
            ' "evidence": "<external source or metric this is based on>"}\n'
            "```\n"
            "For conversational/status responses: plain text is acceptable.\n"
        )


# Singleton
costguard = CostGuard.get()

__all__ = ["costguard", "CostGuard", "CostLimitError", "SchemaResponse"]
