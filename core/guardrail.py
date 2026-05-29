# -*- coding: utf-8 -*-
"""
core/guardrail.py — Monotonic Progressive Kill Switch (5-Level Guardrail)

Levels (MONOTONIC — can only increase, never auto-decrease):
  0  NORMAL          : All systems go
  1  ALERT           : Cost > $3.00  | PnL drawdown > 2%   → Telegram warning
  2  THROTTLE        : Cost > $4.00  | PnL drawdown > 5%   → Add 2s execution delay
  3  FREEZE_TASKS    : Cost > $4.50  | PnL drawdown > 8%   → Reject new task ingestion
  4  FREEZE_TRADING  : Cost > $5.00  | PnL drawdown > 10%  → Halt Bybit execution
  5  GRACEFUL_SHUTDOWN: Cost > $6.00 | PnL drawdown > 15%  → Close positions → Terminate

Run via cron: */2 * * * * /root/venv/bin/python3 /root/my_personal_ai/core/guardrail.py
"""
from __future__ import annotations
import json, logging, os, sys, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

# Bootstrap path
sys.path.insert(0, "/root/my_personal_ai")
os.chdir("/root/my_personal_ai")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GUARDRAIL] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/root/my_personal_ai/logs/guardrail.log"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("guardrail")

_STATE_PATH = Path("/root/my_personal_ai/data/guardrail_state.json")

# ── Threshold matrix ─────────────────────────────────────────────────────────
LEVELS = {
    1: {"name": "ALERT",            "cost": 3.00, "drawdown": 0.02},
    2: {"name": "THROTTLE",         "cost": 4.00, "drawdown": 0.05},
    3: {"name": "FREEZE_TASKS",     "cost": 4.50, "drawdown": 0.08},
    4: {"name": "FREEZE_TRADING",   "cost": 5.00, "drawdown": 0.10},
    5: {"name": "GRACEFUL_SHUTDOWN","cost": 6.00, "drawdown": 0.15},
}

THROTTLE_DELAY_SEC = 2.0   # Level 2 execution delay (injected via env flag)


@dataclass
class GuardrailState:
    level:        int   = 0
    level_name:   str   = "NORMAL"
    triggered_at: float = 0.0
    reason:       str   = ""
    daily_cost:   float = 0.0
    pnl_drawdown: float = 0.0
    date:         str   = ""


def _load_state() -> GuardrailState:
    try:
        if _STATE_PATH.exists():
            d = json.loads(_STATE_PATH.read_text())
            return GuardrailState(**d)
    except Exception:
        pass
    return GuardrailState()


def _save_state(s: GuardrailState) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(asdict(s), indent=2))


def _send_telegram(msg: str) -> None:
    try:
        import httpx
        from dotenv import dotenv_values
        env = dotenv_values("/root/my_personal_ai/.env")
        tok = env.get("TELEGRAM_BOT_TOKEN", "")
        cid = env.get("TELEGRAM_CHAT_ID", "")
        if tok and cid:
            httpx.post(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id": cid, "text": msg},
                timeout=8
            )
    except Exception as e:
        log.error("Telegram send failed: %s", e)


def _get_daily_cost() -> float:
    """Read daily cost from LLMRouter singleton or cost log."""
    try:
        from brain.llm_router import LLMRouter
        router = LLMRouter.get()
        stats = router.get_cost_stats()
        return float(stats.get("daily_cost_usd", 0.0))
    except Exception as e:
        log.debug("Cost fetch from router failed: %s — reading log", e)
    # Fallback: sum today's costs from log
    try:
        today = time.strftime("%Y-%m-%d")
        log_path = Path("/root/my_personal_ai/logs/brain.log")
        if not log_path.exists():
            return 0.0
        total = 0.0
        for line in log_path.read_text(errors="replace").splitlines():
            if today in line and "cost" in line.lower():
                import re
                m = re.search(r'cost[=\s]+\$?([\d.]+)', line, re.I)
                if m:
                    total += float(m.group(1))
        return total
    except Exception:
        return 0.0


def _get_pnl_drawdown() -> float:
    """Return drawdown fraction (0.0 = no drawdown). Reads Bybit via trading_bridge."""
    try:
        from core.trading_bridge import TradingBridge
        tb = TradingBridge.get()
        stats = tb.get_session_stats() if hasattr(tb, "get_session_stats") else {}
        initial = stats.get("initial_balance", 0)
        current = stats.get("current_balance", 0)
        if initial and initial > 0 and current < initial:
            return (initial - current) / initial
    except Exception:
        pass
    return 0.0  # Unknown — assume no drawdown


def _determine_new_level(cost: float, drawdown: float, current_level: int) -> tuple:
    """Return (new_level, reason). MONOTONIC: new level >= current_level."""
    triggered = current_level  # start from current
    reason = ""
    for lvl in sorted(LEVELS.keys(), reverse=True):
        cfg = LEVELS[lvl]
        if cost >= cfg["cost"] or drawdown >= cfg["drawdown"]:
            if lvl > triggered:
                triggered = lvl
                parts = []
                if cost >= cfg["cost"]:
                    parts.append(f"cost=${cost:.4f}>=${cfg['cost']}")
                if drawdown >= cfg["drawdown"]:
                    parts.append(f"drawdown={drawdown*100:.1f}%>={cfg['drawdown']*100:.0f}%")
                reason = " | ".join(parts)
            break
    return triggered, reason


def _apply_level(state: GuardrailState, new_level: int, reason: str) -> None:
    """Apply guardrail actions for new level."""
    name = LEVELS.get(new_level, {}).get("name", "NORMAL")
    state.level       = new_level
    state.level_name  = name
    state.triggered_at = time.time()
    state.reason      = reason

    log.warning("GUARDRAIL LEVEL %d [%s] — %s", new_level, name, reason)

    tg_msgs = {
        1: f"⚠️ [APEX GUARDRAIL] LEVEL 1 — ALERT\nReason: {reason}\nMonitoring closely.",
        2: f"🔶 [APEX GUARDRAIL] LEVEL 2 — THROTTLE\nReason: {reason}\nExecution delay +{THROTTLE_DELAY_SEC}s active.",
        3: f"🛑 [APEX GUARDRAIL] LEVEL 3 — FREEZE TASKS\nReason: {reason}\nNo new tasks accepted.",
        4: f"🚨 [APEX GUARDRAIL] LEVEL 4 — FREEZE TRADING\nReason: {reason}\nBybit execution HALTED. Positions maintained.",
        5: f"💀 [APEX GUARDRAIL] LEVEL 5 — GRACEFUL SHUTDOWN\nReason: {reason}\nClosing positions → terminating workers → read-only mode.",
    }

    if new_level in tg_msgs:
        _send_telegram(tg_msgs[new_level])

    if new_level == 2:
        # Write throttle flag for orchestrator to read
        Path("/root/my_personal_ai/data/guardrail_throttle.flag").write_text(
            str(THROTTLE_DELAY_SEC)
        )

    elif new_level == 3:
        Path("/root/my_personal_ai/data/guardrail_freeze_tasks.flag").write_text(
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')} | {reason}"
        )

    elif new_level == 4:
        Path("/root/my_personal_ai/data/guardrail_freeze_trading.flag").write_text(
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')} | {reason}"
        )
        # Also signal trading agent to halt
        try:
            import subprocess
            subprocess.run(
                ["pkill", "-f", "auto_trading_gate.py"],
                capture_output=True, timeout=5
            )
        except Exception:
            pass

    elif new_level == 5:
        _graceful_shutdown(reason)


def _graceful_shutdown(reason: str) -> None:
    """Level 5: deterministic close-positions → terminate → read-only."""
    log.critical("GRACEFUL SHUTDOWN INITIATED: %s", reason)

    # Step 1: Write read-only recovery flag
    Path("/root/my_personal_ai/data/readonly_recovery.flag").write_text(
        f"{time.strftime('%Y-%m-%dT%H:%M:%SZ')} | shutdown_reason={reason}"
    )

    # Step 2: Attempt to close/hedge Bybit positions
    try:
        from core.trading_bridge import TradingBridge
        tb = TradingBridge.get()
        if hasattr(tb, "emergency_close_all"):
            tb.emergency_close_all()
            log.info("SHUTDOWN: positions closed via TradingBridge")
    except Exception as e:
        log.error("SHUTDOWN: position close failed: %s", e)

    # Step 3: Terminate trading-related cron jobs
    try:
        import subprocess
        for proc in ["auto_trading_gate", "bybit", "trading"]:
            subprocess.run(["pkill", "-f", proc], capture_output=True, timeout=5)
    except Exception:
        pass

    # Step 4: State checkpoint saved via _save_state (caller handles this)
    log.info("SHUTDOWN: system now in read-only recovery mode")


def _clear_stale_flags(state: GuardrailState) -> None:
    """Clean up flags if level has been manually reset."""
    if state.level < 2:
        Path("/root/my_personal_ai/data/guardrail_throttle.flag").unlink(missing_ok=True)
    if state.level < 3:
        Path("/root/my_personal_ai/data/guardrail_freeze_tasks.flag").unlink(missing_ok=True)
    if state.level < 4:
        Path("/root/my_personal_ai/data/guardrail_freeze_trading.flag").unlink(missing_ok=True)


def check_state() -> GuardrailState:
    """Return current guardrail state without triggering checks (for imports)."""
    return _load_state()


def is_frozen() -> bool:
    """Quick check: are tasks frozen?"""
    return Path("/root/my_personal_ai/data/guardrail_freeze_tasks.flag").exists()


def is_trading_frozen() -> bool:
    """Quick check: is trading frozen?"""
    return Path("/root/my_personal_ai/data/guardrail_freeze_trading.flag").exists()


def throttle_delay() -> float:
    """Returns delay seconds if throttle flag is active, else 0.0."""
    p = Path("/root/my_personal_ai/data/guardrail_throttle.flag")
    if p.exists():
        try:
            return float(p.read_text().strip())
        except Exception:
            return THROTTLE_DELAY_SEC
    return 0.0


def main() -> None:
    state = _load_state()
    today = time.strftime("%Y-%m-%d")

    # Daily reset: level resets to 0 at midnight (costs reset too)
    if state.date != today:
        log.info("New day — resetting guardrail state")
        state = GuardrailState(date=today)
        _clear_stale_flags(state)

    cost     = _get_daily_cost()
    drawdown = _get_pnl_drawdown()

    state.daily_cost   = cost
    state.pnl_drawdown = drawdown
    state.date         = today

    new_level, reason = _determine_new_level(cost, drawdown, state.level)

    if new_level > state.level:
        _apply_level(state, new_level, reason)
    else:
        log.info("GUARDRAIL OK — level=%s cost=$%.4f drawdown=%.1f%%",
                 state.level_name, cost, drawdown * 100)

    _save_state(state)


if __name__ == "__main__":
    main()
