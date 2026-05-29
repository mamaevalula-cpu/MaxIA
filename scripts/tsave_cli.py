#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tsave_cli.py — CLI for the Token-Savings Stack (component 7/8).

Commands:
    status              Full status of all 8 components
    cache stats         Cache hit ratio and savings
    cache clear         Wipe the cache
    history stats       Chat history statistics
    history show <sid>  Show messages for a session
    checkpoint list     List saved checkpoints
    recovery on         Enter read-only recovery mode
    recovery off        Exit recovery mode
    budget status       Token budget usage
    budget reset        Reset session token counter
    safe on             Activate governance safe mode
    safe off            Deactivate governance safe mode
    maintenance         Run daily purge (old sessions + expired cache)

Usage (from project root):
    python scripts/tsave_cli.py status
    python scripts/tsave_cli.py cache stats
    python scripts/tsave_cli.py recovery on
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


def _pp(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def cmd_status() -> None:
    from core.token_saver import token_saver
    _pp(token_saver.status())


def cmd_cache(args: list) -> None:
    sub = args[0] if args else "stats"
    from core.cache_router import cache_router

    if sub == "stats":
        _pp(cache_router.stats())

    elif sub == "clear":
        count = cache_router.clear()
        print(f"Cleared {count} cache entries.")

    else:
        print(f"Unknown cache sub-command: {sub!r}")
        print("  cache stats | cache clear")


def cmd_history(args: list) -> None:
    sub = args[0] if args else "stats"
    from core.chat_history import history

    if sub == "stats":
        _pp(history.stats())

    elif sub == "show":
        sid = args[1] if len(args) > 1 else ""
        if not sid:
            print("Usage: history show <session_id>")
            return
        msgs = history.get_session(sid)
        summary = history.get_summary(sid)
        if summary:
            print(f"[SUMMARY]\n{summary}\n")
        if msgs:
            print(f"[MESSAGES: {len(msgs)}]")
            for m in msgs:
                ts = m.get("ts", 0)
                print(f"  [{m['role'].upper()}] {m['content'][:120]!r}  "
                      f"tokens={m.get('tokens',0)} provider={m.get('provider','')}")
        else:
            print("No messages found for session:", sid)

    elif sub == "sessions":
        user = args[1] if len(args) > 1 else ""
        sessions = history.recent_sessions(user_id=user, limit=20)
        for s in sessions:
            print(f"  {s['session_id'][:8]}...  user={s['user_id']!r}  "
                  f"turns={s['turn_count']}  tokens={s['total_tokens']}  "
                  f"compressed={bool(s['compressed'])}")

    else:
        print(f"Unknown history sub-command: {sub!r}")
        print("  history stats | history show <sid> | history sessions [user_id]")


def cmd_checkpoint(args: list) -> None:
    sub = args[0] if args else "list"
    from core.checkpoint import checkpoints

    if sub == "list":
        labels = checkpoints.list_labels()
        if not labels:
            print("No checkpoints saved.")
            return
        for label in labels:
            items = checkpoints.list_checkpoints(label, limit=5)
            print(f"\n[{label}]")
            for item in items:
                age_m = item["age_s"] / 60
                print(f"  {item['checkpoint_id']}  "
                      f"hash={item['hash']}  "
                      f"age={age_m:.1f}m  "
                      f"verified={item['verified']}")

    elif sub == "load":
        ckpt_id = args[1] if len(args) > 1 else ""
        if not ckpt_id:
            print("Usage: checkpoint load <checkpoint_id>")
            return
        ckpt = checkpoints.load(ckpt_id)
        if ckpt:
            _pp({"id": ckpt.checkpoint_id, "label": ckpt.label,
                 "hash": ckpt.hash, "state": ckpt.state})
        else:
            print(f"Checkpoint {ckpt_id!r} not found or integrity check failed.")

    else:
        print(f"Unknown checkpoint sub-command: {sub!r}")
        print("  checkpoint list | checkpoint load <id>")


def cmd_recovery(args: list) -> None:
    action = args[0] if args else "status"
    from core.checkpoint import checkpoints

    if action == "on":
        checkpoints.enter_recovery_mode()
        print("Recovery mode ACTIVATED — system is now READ-ONLY.")

    elif action == "off":
        checkpoints.exit_recovery_mode()
        print("Recovery mode DEACTIVATED — system is now READ-WRITE.")

    else:
        st = checkpoints.status()
        _pp({
            "recovery_mode": st.get("recovery_mode", False),
            "recovery_age_s": st.get("recovery_age_s", 0),
        })


def cmd_budget(args: list) -> None:
    sub = args[0] if args else "status"
    from core.governance import gov

    if sub == "status":
        _pp(gov.status())

    elif sub == "reset":
        gov.reset_session()
        print("Session token counter reset.")

    else:
        print(f"Unknown budget sub-command: {sub!r}")
        print("  budget status | budget reset")


def cmd_safe(args: list) -> None:
    action = args[0] if args else "status"
    from core.governance import gov

    if action == "on":
        gov.activate_safe_mode("operator_activated")
        print("Safe mode ACTIVATED.")

    elif action == "off":
        gov.deactivate_safe_mode()
        print("Safe mode DEACTIVATED.")

    else:
        _pp(gov.safe_mode_status())


def cmd_maintenance() -> None:
    from core.token_saver import token_saver
    result = token_saver.daily_maintenance()
    print("Maintenance complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0].lower()
    rest = args[1:]

    try:
        if cmd == "status":
            cmd_status()
        elif cmd == "cache":
            cmd_cache(rest)
        elif cmd == "history":
            cmd_history(rest)
        elif cmd == "checkpoint":
            cmd_checkpoint(rest)
        elif cmd == "recovery":
            cmd_recovery(rest)
        elif cmd == "budget":
            cmd_budget(rest)
        elif cmd == "safe":
            cmd_safe(rest)
        elif cmd == "maintenance":
            cmd_maintenance()
        else:
            print(f"Unknown command: {cmd!r}")
            print("Run without arguments to see help.")
            sys.exit(1)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
