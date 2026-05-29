# -*- coding: utf-8 -*-
"""
core/token_saver.py — Master token-savings coordinator (components 1–8).

Single import point that wires together all 8 stack components:
  1. ChatHistory        — persistent chat/task history
  2. CheckpointManager  — lightweight SQLite checkpoints
  3. CacheRouter        — cache-first LLM routing
  4. ContextOptimizer   — semantic deduplication
  5. GovernanceLayer    — token budget guard
  6. Recovery mode      — read-only fallback (via CheckpointManager)
  7. CLI interface      — see scripts/tsave_cli.py
  8. Bounded orch.      — via GovernanceLayer MAX_AGENT_DEPTH

Usage:
    from core.token_saver import token_saver

    # Before an LLM call:
    result = token_saver.pre_call(
        prompt="Explain Python generators",
        session_id=sid,
        task_type="code",
        task_id="t-001",
    )
    if result.from_cache:
        return result.text       # zero cost, instant

    # After the call:
    token_saver.post_call(
        session_id=sid,
        task_id="t-001",
        role_response=llm_text,
        tokens_used=840,
        provider="deepseek",
    )

    # Full status:
    token_saver.status()
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

log = logging.getLogger("core.token_saver")


@dataclass
class PreCallResult:
    """Result of pre_call(). If from_cache=True, use .text directly."""
    from_cache:     bool   = False
    text:           str    = ""
    optimized_prompt: str  = ""   # deduped / trimmed prompt to send to LLM
    tokens_saved:   int    = 0
    blocked:        bool   = False   # True if governance blocked the call
    block_reason:   str    = ""


class TokenSaver:
    """
    Orchestrates all 8 token-savings stack components.
    Lazy-loads each component to avoid circular imports.
    """

    def __init__(self):
        self._history      = None
        self._checkpoints  = None
        self._cache_router = None
        self._gov          = None
        self._ctx_opt      = None
        self._ready        = False
        self._init()

    def _init(self) -> None:
        errors = []

        # 1 + 6: ChatHistory (persistent history)
        try:
            from core.chat_history import history
            self._history = history
        except Exception as e:
            errors.append(f"chat_history: {e}")

        # 2 + 6: CheckpointManager (includes recovery mode)
        try:
            from core.checkpoint import checkpoints
            self._checkpoints = checkpoints
        except Exception as e:
            errors.append(f"checkpoint: {e}")

        # 3 + 4: CacheRouter (cache-first + semantic dedup)
        try:
            from core.cache_router import cache_router
            self._cache_router = cache_router
        except Exception as e:
            errors.append(f"cache_router: {e}")

        # 5 + 8: GovernanceLayer (token budget + bounded orch)
        try:
            from core.governance import gov
            self._gov = gov
        except Exception as e:
            errors.append(f"governance: {e}")

        # 4 (supplementary): ContextOptimizer
        try:
            from core.context_optimizer import ContextOptimizer
            self._ctx_opt = ContextOptimizer()
        except Exception as e:
            errors.append(f"context_optimizer: {e}")

        if errors:
            log.warning("TokenSaver: %d component(s) unavailable: %s",
                        len(errors), "; ".join(errors))
        else:
            log.info("TokenSaver: all 8 components initialized")

        self._ready = True

    # ── Pre-call pipeline ─────────────────────────────────────────────────

    def pre_call(
        self,
        prompt:     str,
        session_id: str  = "",
        task_type:  str  = "general",
        task_id:    str  = "",
    ) -> PreCallResult:
        """
        Run all pre-call optimizations.
        Returns PreCallResult. Caller should check .from_cache and .blocked.
        """
        result = PreCallResult(optimized_prompt=prompt)

        # ── 5. Governance: check token budget ──────────────────────────────
        if self._gov:
            try:
                from core.governance import GovernanceViolation
                self._gov.check_token_budget(
                    estimated_tokens=len(prompt) // 4 + 200,
                    task_id=task_id or "anon",
                )
            except Exception as gv:
                result.blocked = True
                result.block_reason = str(gv)
                log.warning("TokenSaver: governance blocked | %s", gv)
                return result

        # ── 6. Recovery mode check ─────────────────────────────────────────
        if self._checkpoints:
            try:
                st = self._checkpoints.status()
                if st.get("recovery_mode"):
                    result.blocked = True
                    result.block_reason = "system in read-only recovery mode"
                    log.warning("TokenSaver: recovery mode active — blocking call")
                    return result
            except Exception:
                pass

        # ── 3 + 4. Cache lookup (with semantic dedup) ──────────────────────
        if self._cache_router:
            try:
                hit = self._cache_router.get(prompt, task_type)
                if hit:
                    result.from_cache   = True
                    result.text         = hit.text
                    result.tokens_saved = max(50, len(hit.text) // 4)
                    log.debug("TokenSaver: cache HIT | task=%s age=%.0fs",
                              task_type, hit.age_s)
                    return result

                # Dedup the prompt before sending to LLM
                clean, saved = self._cache_router.dedup_prompt(prompt)
                result.optimized_prompt = clean
                result.tokens_saved    += saved
            except Exception as e:
                log.debug("TokenSaver: cache_router error: %s", e)
                result.optimized_prompt = prompt

        return result

    # ── Post-call pipeline ────────────────────────────────────────────────

    def post_call(
        self,
        session_id:     str,
        task_id:        str,
        role_response:  str,
        tokens_used:    int  = 0,
        provider:       str  = "",
        original_prompt: str = "",
        task_type:      str  = "general",
    ) -> None:
        """
        Run all post-call bookkeeping:
        - Record to chat history
        - Store in cache
        - Report token usage to governance
        """

        # 1. Chat history
        if self._history and session_id:
            try:
                self._history.add_turn(
                    session_id, role="assistant",
                    content=role_response, tokens=tokens_used,
                    provider=provider,
                )
            except Exception as e:
                log.debug("TokenSaver: history write error: %s", e)

        # 3. Cache store
        if self._cache_router and original_prompt:
            try:
                self._cache_router.put(original_prompt, task_type,
                                       role_response, tokens_used)
            except Exception as e:
                log.debug("TokenSaver: cache put error: %s", e)

        # 5. Governance reporting
        if self._gov and tokens_used:
            try:
                self._gov.record_token_usage(
                    tokens_used=tokens_used,
                    provider=provider,
                    task_id=task_id or "anon",
                )
            except Exception as e:
                log.debug("TokenSaver: governance report error: %s", e)

    # ── Convenience: add user turn to history ─────────────────────────────

    def record_user_turn(
        self, session_id: str, content: str, tokens: int = 0
    ) -> None:
        if self._history and session_id:
            try:
                self._history.add_turn(session_id, "user", content, tokens)
            except Exception:
                pass

    def get_session_context(self, session_id: str, max_tokens: int = 1500) -> str:
        """Return compressed context string for injection into next prompt."""
        if self._history and session_id:
            try:
                return self._history.get_context(session_id, max_tokens)
            except Exception:
                pass
        return ""

    # ── Status ────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Aggregate status of all 8 components."""
        out: Dict[str, Any] = {
            "ready": self._ready,
            "components": {},
        }

        comp = out["components"]

        # 1. ChatHistory
        if self._history:
            try:
                comp["chat_history"] = self._history.stats()
            except Exception as e:
                comp["chat_history"] = {"error": str(e)}
        else:
            comp["chat_history"] = {"status": "unavailable"}

        # 2. Checkpoints
        if self._checkpoints:
            try:
                comp["checkpoint"] = self._checkpoints.status()
            except Exception as e:
                comp["checkpoint"] = {"error": str(e)}
        else:
            comp["checkpoint"] = {"status": "unavailable"}

        # 3+4. CacheRouter
        if self._cache_router:
            try:
                comp["cache_router"] = self._cache_router.stats()
            except Exception as e:
                comp["cache_router"] = {"error": str(e)}
        else:
            comp["cache_router"] = {"status": "unavailable"}

        # 5+8. Governance
        if self._gov:
            try:
                comp["governance"] = self._gov.status()
            except Exception as e:
                comp["governance"] = {"error": str(e)}
        else:
            comp["governance"] = {"status": "unavailable"}

        # 6. Recovery mode (from checkpoint)
        if self._checkpoints:
            try:
                st = self._checkpoints.status()
                comp["recovery_mode"] = {
                    "active": st.get("recovery_mode", False),
                    "age_s":  st.get("recovery_age_s", 0),
                }
            except Exception:
                comp["recovery_mode"] = {"active": False}
        else:
            comp["recovery_mode"] = {"status": "unavailable"}

        return out

    # ── Daily maintenance ─────────────────────────────────────────────────

    def daily_maintenance(self) -> Dict[str, int]:
        """Purge old sessions and expired cache entries."""
        result = {}
        if self._history:
            try:
                result["sessions_purged"] = self._history.purge_old_sessions()
            except Exception:
                pass
        if self._cache_router:
            try:
                result["cache_expired"] = self._cache_router._expire_old()
            except Exception:
                pass
        return result


# ── Singleton ─────────────────────────────────────────────────────────────────
token_saver = TokenSaver()
