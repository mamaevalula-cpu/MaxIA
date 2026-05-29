#!/usr/bin/env python3
"""paper_trading_monitor.py - Check if paper trading passes criteria."""
import json, urllib.request, time, sys

CHECKPOINT_FILE = '/root/my_personal_ai/data/paper_trading_checkpoint.json'
PASS_WIN_RATE = 0.55
PASS_DRAWDOWN = 5.0

try:
    with open(CHECKPOINT_FILE) as f:
        chk = json.load(f)
except Exception as e:
    print(f"No checkpoint: {e}")
    sys.exit(1)

try:
    with urllib.request.urlopen("http://localhost:8090/api/status", timeout=5) as r:
        s = json.loads(r.read())
except Exception as e:
    print(f"Monitor offline: {e}")
    sys.exit(1)

hours_running = (time.time() - chk['start_ts']) / 3600
win_rate = s.get('win_rate', 0)
paper_pnl = s.get('daily_pnl', 0)
trades = s.get('paper_trades_today', 0)
balance = s.get('paper_balance', 10000)
drawdown = max(0, (10000 - balance) / 10000 * 100)

print(f"=== Paper Trading Monitor ===")
print(f"Running: {hours_running:.1f}h / 48h")
print(f"Win rate: {win_rate*100:.0f}% (need >{PASS_WIN_RATE*100:.0f}%)")
print(f"PnL: ${paper_pnl:+.2f}")
print(f"Trades: {trades}")
print(f"Drawdown: {drawdown:.1f}% (max {PASS_DRAWDOWN}%)")

READY = (
    hours_running >= 48 and
    win_rate >= PASS_WIN_RATE and
    drawdown <= PASS_DRAWDOWN and
    trades >= 20
)
print()
print("VERDICT:", "✅ READY FOR LIVE" if READY else f"⏳ WAIT ({48 - hours_running:.0f}h remaining)")
