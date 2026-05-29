# -*- coding: utf-8 -*-
"""
core/governance_cli.py — Operator console for GovernanceLayer + CheckpointManager.

Usage (run from project root):
    python -m core.governance_cli status
    python -m core.governance_cli safe-mode on
    python -m core.governance_cli safe-mode off
    python -m core.governance_cli checkpoint list
    python -m core.governance_cli checkpoint load <id>
    python -m core.governance_cli recovery on
    python -m core.governance_cli recovery off
    python -m core.governance_cli reset-session
"""

from __future__ import annotations

import json
import sys


def _print(data: dict) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    args = (argv or sys.argv[1:])
    if not args:
        print(__doc__)
        return

    cmd = args[0].lower()

    # Lazy import to avoid circular imports when used standalone
    from core.governance import gov
    from core.checkpoint import checkpoints

    if cmd == "status":
        g = gov.status()
        c = checkpoints.status()
        _print({"governance": g, "checkpoints": c})

    elif cmd == "safe-mode":
        action = args[1].lower() if len(args) > 1 else "status"
        if action == "on":
            gov.activate_safe_mode("operator_activated")
            print("Safe mode ACTIVATED")
        elif action == "off":
            gov.deactivate_safe_mode()
            print("Safe mode DEACTIVATED")
        else:
            _print(gov.safe_mode_status())

    elif cmd == "checkpoint":
        sub = args[1].lower() if len(args) > 1 else "list"
        if sub == "list":
            labels = checkpoints.list_labels()
            for label in labels:
                items = checkpoints.list_checkpoints(label, limit=5)
                print(f"\n[{label}]")
                for item in items:
                    age_m = item["age_s"] / 60
                    print(f"  {item['checkpoint_id']}  hash={item['hash']}  "
                          f"age={age_m:.1f}m  verified={item['verified']}")
        elif sub == "load":
            ckpt_id = args[2] if len(args) > 2 else ""
            if not ckpt_id:
                print("Usage: checkpoint load <checkpoint_id>")
                return
            ckpt = checkpoints.load(ckpt_id)
            if ckpt:
                _print({"id": ckpt.checkpoint_id, "label": ckpt.label,
                        "hash": ckpt.hash, "state": ckpt.state})
            else:
                print(f"Checkpoint {ckpt_id!r} not found or integrity failed")
        elif sub == "latest":
            label = args[2] if len(args) > 2 else ""
            if not label:
                print("Usage: checkpoint latest <label>")
                return
            ckpt = checkpoints.latest(label)
            if ckpt:
                _print({"id": ckpt.checkpoint_id, "label": ckpt.label,
                        "hash": ckpt.hash, "state": ckpt.state})
            else:
                print(f"No verified checkpoint for label {label!r}")
        else:
            print(f"Unknown checkpoint subcommand: {sub!r}")

    elif cmd == "recovery":
        action = args[1].lower() if len(args) > 1 else "status"
        if action == "on":
            checkpoints.enter_recovery_mode()
            print("Recovery mode ACTIVATED — writes blocked")
        elif action == "off":
            checkpoints.exit_recovery_mode()
            print("Recovery mode DEACTIVATED — writes restored")
        else:
            _print({"recovery_mode": checkpoints.is_recovery_mode})

    elif cmd == "reset-session":
        gov.reset_session()
        print("Session counters reset")

    elif cmd == "token-usage":
        _print(gov.token_usage_summary())

    else:
        print(f"Unknown command: {cmd!r}")
        print(__doc__)


if __name__ == "__main__":
    main()
