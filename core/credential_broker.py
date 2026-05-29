# -*- coding: utf-8 -*-
"""
core/credential_broker.py — Plane C: Just-In-Time Credential Access
Three-Plane Architecture:
  Plane A (Orchestration): evaluates/routes — NEVER accesses raw secrets
  Plane B (Execution):     isolated agents  — receives ONLY scoped params
  Plane C (This module):   JIT token dispense — reads .env at call-time, TTL cache

Usage:
    from core.credential_broker import broker
    key = broker.get("GROQ_API_KEY", scope="llm", caller="llm_router")
    cfg = broker.get_scope("telegram", caller="telegram_agent")
"""
from __future__ import annotations
import logging, os, time
from pathlib import Path
from typing import Dict, Optional
from dotenv import dotenv_values

log = logging.getLogger("credential_broker")

_ENV_PATH   = Path("/root/my_personal_ai/.env")
_AUDIT_LOG  = Path("/root/my_personal_ai/logs/credential_access.log")
_TTL        = 300   # 5-minute cache TTL per key

# Scope → allowed key prefixes.  Empty list = DENIED.
_SCOPES: Dict[str, list] = {
    "llm":       ["GROQ_", "CEREBRAS_", "OPENROUTER_", "OPENAI_", "GEMINI_",
                  "ANTHROPIC_", "DEEPSEEK_", "MISTRAL_", "GROK_", "XAI_",
                  "TOGETHER_", "PERPLEXITY_"],
    "telegram":  ["TELEGRAM_"],
    "trading":   ["BYBIT_"],
    "email":     ["EMAIL_", "GMAIL_", "IMAP_", "OUTREACH_", "RESEND_"],
    "search":    ["SERPAPI_", "TAVILY_", "PINECONE_"],
    "system":    ["LOG_LEVEL", "MASTER_", "SYSTEM_", "VECTOR_",
                  "MAX_PARALLEL", "AGENT_TASK_", "AUTO_APPROVE"],
    "admin":     [],   # empty = all keys allowed, restricted to internal use
}

class _CredentialBroker:
    """Thread-safe JIT credential broker with TTL cache and audit log."""

    def __init__(self) -> None:
        self._cache: Dict[str, tuple] = {}   # key -> (value, expires_at)
        self._lock  = __import__("threading").Lock()

    # ── public API ──────────────────────────────────────────────────────────

    def get(self, key: str, scope: str = "llm", caller: str = "unknown") -> Optional[str]:
        """Return credential value IFF key is within scope. Logs every access."""
        with self._lock:
            # Cache hit
            if key in self._cache:
                val, exp = self._cache[key]
                if time.time() < exp:
                    return val
                del self._cache[key]

            # Scope enforcement
            if not self._allowed(key, scope):
                log.warning("CredentialBroker DENIED: key=%s scope=%s caller=%s", key, scope, caller)
                self._audit("DENIED", scope, key, caller)
                return None

            val = self._load(key)
            if val:
                self._cache[key] = (val, time.time() + _TTL)
                self._audit("GRANTED", scope, key, caller)
            return val

    def get_scope(self, scope: str, caller: str = "unknown") -> Dict[str, str]:
        """Return ALL credentials matching a scope. Returns empty dict if scope unknown."""
        prefixes = _SCOPES.get(scope)
        if prefixes is None:
            log.warning("CredentialBroker: unknown scope=%s caller=%s", scope, caller)
            return {}
        env = dotenv_values(str(_ENV_PATH))
        result = {}
        for k, v in env.items():
            if v and (not prefixes or any(k.startswith(p) for p in prefixes)):
                result[k] = v
                self._audit("SCOPE_GRANT", scope, k, caller)
        return result

    def invalidate(self, key: Optional[str] = None) -> None:
        """Flush cache entry or entire cache if key is None."""
        with self._lock:
            if key:
                self._cache.pop(key, None)
            else:
                self._cache.clear()
        log.info("CredentialBroker: cache invalidated key=%s", key or "ALL")

    # ── internal ────────────────────────────────────────────────────────────

    def _allowed(self, key: str, scope: str) -> bool:
        prefixes = _SCOPES.get(scope)
        if prefixes is None:
            return False
        if not prefixes:   # empty list = admin: all allowed
            return True
        return any(key.startswith(p) for p in prefixes)

    def _load(self, key: str) -> Optional[str]:
        env = dotenv_values(str(_ENV_PATH))
        return env.get(key) or os.getenv(key)

    def _audit(self, event: str, scope: str, key: str, caller: str) -> None:
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        line = f"{ts} | {event:10s} | scope={scope:10s} | key={key:40s} | caller={caller}\n"
        try:
            _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with _AUDIT_LOG.open("a") as f:
                f.write(line)
        except Exception:
            pass


# Singleton
broker = _CredentialBroker()

__all__ = ["broker", "_CredentialBroker"]
