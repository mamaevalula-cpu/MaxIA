# -*- coding: utf-8 -*-
"""
TradingBridge — IPC bridge between bybit-bot and my_personal_ai.

Provides read-only access to bybit-bot's state:
  • SQLite journal (execution_journal table) — trade history
  • HTTP /health endpoint — bot liveness + silence
  • Shared status cache — balance, positions, PnL, strategy states

Architecture:
  bybit-bot (SQLite + HTTP:8080)
      ↕  [SQLite read-only / aiohttp GET]
  TradingBridge (singleton, thread-safe)
      ↕  [dict snapshot]
  GUI Trading tab / TradingAgent / Orchestrator

Design rules:
  - NEVER writes to bybit-bot's database
  - NEVER imports bybit-bot modules (avoids circular deps / version conflicts)
  - All reads wrapped in try/except — bot may be offline
  - Cached with configurable TTL (default 15 s) to avoid hammering SQLite
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import urlopen
from urllib.error import URLError
import json
import os

# ── Constants ────────────────────────────────────────────────────────────────

# Bybit-bot SQLite path (relative to this repo root, or absolute env override)
_DEFAULT_BOT_DB = os.environ.get(
    "BYBIT_BOT_DB",
    str(Path(__file__).parent.parent.parent / "bybit-bot" / "data" / "bybit_bot.db"),
)

# Bybit-bot health endpoint
_DEFAULT_HEALTH_URL = os.environ.get("BYBIT_BOT_HEALTH_URL", "http://127.0.0.1:8001/health")

CACHE_TTL_SEC   = 15      # seconds between full refreshes
HISTORY_LIMIT   = 50      # last N trades to pull from journal
CONNECT_TIMEOUT = 2.0     # HTTP timeout (seconds)


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    """Single entry from execution_journal."""
    id:           int
    client_oid:   str
    exchange_oid: Optional[str]
    symbol:       str
    side:         str          # "Buy" | "Sell"
    qty:          str
    order_type:   str
    category:     str          # "linear" | "spot" | "inverse"
    status:       str          # "filled" | "cancelled" | ...
    stop_loss:    Optional[str]
    take_profit:  Optional[str]
    latency_ms:   Optional[float]
    submitted_at: float
    filled_at:    Optional[float]
    recorded_at:  float

    @property
    def age_seconds(self) -> float:
        return time.time() - self.recorded_at

    @property
    def submitted_dt(self) -> str:
        import datetime
        return datetime.datetime.fromtimestamp(self.submitted_at).strftime("%H:%M:%S")


@dataclass
class BotStatus:
    """Snapshot of bybit-bot's current state."""
    # Liveness
    online:         bool   = False
    silence_s:      float  = 0.0
    healthy:        bool   = False
    last_check:     float  = field(default_factory=time.time)

    # Trading summary (populated from journal aggregation)
    total_trades:   int    = 0
    trades_today:   int    = 0
    winning_trades: int    = 0
    losing_trades:  int    = 0

    # Balance / PnL  (populated by bybit-bot IPC file if available)
    balance_usdt:   float  = 0.0
    daily_pnl:      float  = 0.0
    daily_pnl_pct:  float  = 0.0
    open_positions: int    = 0

    # Recent trades
    recent_trades: List[TradeRecord] = field(default_factory=list)

    # Bot mode
    mode:           str    = "unknown"   # "live" | "paper" | "backtest" | "offline"
    active_pairs:   List[str] = field(default_factory=list)
    active_strategies: List[str] = field(default_factory=list)

    # Raw health JSON from /health endpoint
    health_raw:     Dict[str, Any] = field(default_factory=dict)

    @property
    def win_rate(self) -> float:
        total = self.winning_trades + self.losing_trades
        return self.winning_trades / total if total else 0.0

    @property
    def status_emoji(self) -> str:
        if not self.online:
            return "🔴"
        if self.healthy:
            return "🟢"
        return "🟡"

    @property
    def mode_label(self) -> str:
        labels = {"live": "🔴 LIVE", "paper": "📄 Paper", "backtest": "📊 Backtest"}
        return labels.get(self.mode, "❓ Offline")

    def summary_text(self) -> str:
        lines = [
            f"{self.status_emoji} Bot: {self.mode_label}",
        ]
        if self.online:
            lines += [
                f"💰 Balance: {self.balance_usdt:.2f} USDT",
                f"📈 Daily PnL: {self.daily_pnl:+.2f} USDT ({self.daily_pnl_pct:+.2f}%)",
                f"📂 Open positions: {self.open_positions}",
                f"🔁 Trades today: {self.trades_today}  (Win: {self.winning_trades} / Loss: {self.losing_trades})",
            ]
            if self.active_pairs:
                lines.append(f"🎯 Pairs: {', '.join(self.active_pairs[:5])}")
            if self.active_strategies:
                lines.append(f"🧠 Strategies: {', '.join(self.active_strategies)}")
        else:
            lines.append("⚠️  Bot is offline or unreachable")
        return "\n".join(lines)


# ── IPC status file (bybit-bot writes, we read) ──────────────────────────────

_IPC_STATUS_FILE = os.environ.get(
    "BYBIT_BOT_IPC_FILE",
    str(Path(__file__).parent.parent.parent / "bybit-bot" / "data" / "bot_status.json"),
)


# ── TradingBridge ─────────────────────────────────────────────────────────────

class TradingBridge:
    """
    Thread-safe singleton bridge to bybit-bot.

    Usage:
        bridge = TradingBridge.get()
        status = bridge.get_status()          # BotStatus (cached)
        trades = bridge.get_recent_trades(20) # List[TradeRecord]
        bridge.refresh()                      # force refresh
    """

    _instance: Optional["TradingBridge"] = None
    _lock:     threading.Lock = threading.Lock()

    # ── Singleton ────────────────────────────────────────────────────────────

    @classmethod
    def get(cls) -> "TradingBridge":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(
        self,
        db_path:    str = _DEFAULT_BOT_DB,
        health_url: str = _DEFAULT_HEALTH_URL,
        ipc_file:   str = _IPC_STATUS_FILE,
    ) -> None:
        self._db_path    = db_path
        self._health_url = health_url
        self._ipc_file   = ipc_file

        self._cache:     Optional[BotStatus] = None
        self._cache_ts:  float = 0.0
        self._rw_lock    = threading.RLock()

        # Optional callback: called when new trade arrives
        self._on_new_trade_cb = None

    # ── Public API ────────────────────────────────────────────────────────────

    def configure(self, db_path: str | None = None,
                  health_url: str | None = None,
                  ipc_file: str | None = None) -> None:
        """Override paths at runtime (e.g. from settings dialog)."""
        with self._rw_lock:
            if db_path:    self._db_path    = db_path
            if health_url: self._health_url = health_url
            if ipc_file:   self._ipc_file   = ipc_file
            self._cache = None  # invalidate

    def set_on_new_trade(self, callback) -> None:
        """Register callback(trade: TradeRecord) → called when a new trade appears."""
        self._on_new_trade_cb = callback

    def add_event_callback(self, callback) -> None:
        """
        Register callback(payload: dict) for trade events.
        payload keys: symbol, side, qty, price, status, pnl, ts
        Called by FamilyController to forward events to the family bus.
        """
        if not hasattr(self, "_event_callbacks"):
            self._event_callbacks: list = []
        self._event_callbacks.append(callback)

    def _fire_event_callbacks(self, trade: "TradeRecord") -> None:
        """Fire all registered event callbacks with a dict payload."""
        callbacks = getattr(self, "_event_callbacks", [])
        if not callbacks:
            return
        payload = {
            "symbol":   getattr(trade, "symbol", ""),
            "side":     getattr(trade, "side", ""),
            "qty":      getattr(trade, "qty", 0),
            "price":    getattr(trade, "price", 0),
            "status":   getattr(trade, "status", ""),
            "pnl":      getattr(trade, "realized_pnl", 0),
            "ts":       getattr(trade, "submitted_ts", 0),
        }
        for cb in callbacks:
            try:
                cb(payload)
            except Exception as e:
                import logging
                logging.getLogger("core.trading_bridge").warning("Event callback error: %s", e)

    def get_status(self, force: bool = False) -> BotStatus:
        """
        Return cached BotStatus, refreshing if TTL expired.
        Always returns a valid object (even if offline).
        """
        with self._rw_lock:
            age = time.time() - self._cache_ts
            if force or self._cache is None or age > CACHE_TTL_SEC:
                self._cache = self._refresh()
                self._cache_ts = time.time()
            return self._cache

    def refresh(self) -> BotStatus:
        """Force a full refresh and return new status."""
        return self.get_status(force=True)

    def get_recent_trades(self, limit: int = 20) -> List[TradeRecord]:
        """Return last N trades from journal (cached in status)."""
        status = self.get_status()
        return status.recent_trades[:limit]

    def is_online(self) -> bool:
        return self.get_status().online

    def get_report(self) -> str:
        """Human-readable report for Telegram / status command."""
        s = self.get_status()
        lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "📊 Trading Bridge Report",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            s.summary_text(),
            "",
            f"📋 Recent trades: {len(s.recent_trades)}",
        ]
        if s.recent_trades:
            lines.append("")
            for t in s.recent_trades[:5]:
                side_emoji = "🟢" if t.side.lower() == "buy" else "🔴"
                lat = f" {t.latency_ms:.0f}ms" if t.latency_ms else ""
                lines.append(
                    f"  {side_emoji} {t.symbol} {t.side} {t.qty}"
                    f" [{t.status}]{lat} @ {t.submitted_dt}"
                )
        lines += [
            "",
            f"🔗 DB: {Path(self._db_path).name}",
            f"🌐 Health: {self._health_url}",
            f"⏱ Cache TTL: {CACHE_TTL_SEC}s",
        ]
        return "\n".join(lines)

    # ── Internal refresh ──────────────────────────────────────────────────────

    def _refresh(self) -> BotStatus:
        status = BotStatus()

        # 1. HTTP health check
        self._check_health(status)

        # 2. IPC status file (written by bybit-bot's StatusExporter)
        self._read_ipc_file(status)

        # 3. SQLite journal
        self._read_journal(status)

        # 4. Notify if new trades arrived
        self._fire_new_trade_callbacks(status)

        return status

    def _check_health(self, status: BotStatus) -> None:
        """GET /health from bybit-bot's aiohttp server, then enrich from /status."""
        try:
            with urlopen(self._health_url, timeout=CONNECT_TIMEOUT) as resp:
                data = json.loads(resp.read().decode())
            status.online    = True
            status.healthy   = data.get("healthy", data.get("status") == "ok")
            status.silence_s = data.get("silence_s", 0.0)
            status.health_raw = data
        except (URLError, OSError, json.JSONDecodeError):
            status.online  = False
            status.healthy = False
            return
        # Enrich with full status from /status endpoint (bybit_monitor)
        try:
            _status_url = self._health_url.replace("/health", "/status")
            with urlopen(_status_url, timeout=CONNECT_TIMEOUT) as resp2:
                s = json.loads(resp2.read().decode())
            # Paper balance takes priority if real balance is 0
            bal = float(s.get("balance_usdt", 0) or 0)
            if bal == 0:
                bal = float(s.get("paper_balance", s.get("balance_display", 0)) or 0)
            status.balance_usdt      = bal
            status.daily_pnl         = float(s.get("daily_pnl", 0))
            status.daily_pnl_pct     = float(s.get("daily_pnl_pct", 0))
            status.open_positions    = int(s.get("open_positions", 0))
            status.active_pairs      = s.get("active_pairs", [])
            status.active_strategies = s.get("active_strategies", [])
            status.mode              = s.get("mode", "paper")
            status.trades_today      = int(s.get("paper_trades_today", s.get("trades_today", 0)))
            status.winning_trades    = int(s.get("winning_trades", 0))
            status.losing_trades     = int(s.get("losing_trades", 0))
        except Exception:
            pass

    def _read_ipc_file(self, status: BotStatus) -> None:
        """
        Read bot_status.json written by bybit-bot.
        Format (example):
        {
          "mode": "paper",
          "balance_usdt": 1234.56,
          "daily_pnl": 12.34,
          "daily_pnl_pct": 1.02,
          "open_positions": 2,
          "active_pairs": ["BTCUSDT", "ETHUSDT"],
          "active_strategies": ["momentum", "grid"],
          "ts": 1700000000.0
        }
        """
        try:
            p = Path(self._ipc_file)
            if not p.exists():
                return
            age = time.time() - p.stat().st_mtime
            if age > 120:  # file older than 2 min → stale
                status.mode = "offline"
                return
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            status.mode              = data.get("mode", "unknown")
            status.balance_usdt      = float(data.get("balance_usdt", 0))
            status.daily_pnl         = float(data.get("daily_pnl", 0))
            status.daily_pnl_pct     = float(data.get("daily_pnl_pct", 0))
            status.open_positions    = int(data.get("open_positions", 0))
            status.active_pairs      = data.get("active_pairs", [])
            status.active_strategies = data.get("active_strategies", [])
            if not status.online:
                # If HTTP offline but file is fresh → partially online
                status.online = True
        except Exception:
            pass

    def _read_journal(self, status: BotStatus) -> None:
        """Read execution_journal from bybit-bot's SQLite."""
        db_path = Path(self._db_path)
        if not db_path.exists():
            return
        try:
            # Read-only URI connection to avoid locking bybit-bot
            uri = f"file:{db_path}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=2.0,
                                   check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # Total trades
            cur.execute("SELECT COUNT(*) FROM execution_journal")
            row = cur.fetchone()
            status.total_trades = row[0] if row else 0

            # Today's trades (since midnight)
            import datetime
            today_start = datetime.datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            cur.execute(
                "SELECT COUNT(*) FROM execution_journal WHERE submitted_at >= ?",
                (today_start,),
            )
            row = cur.fetchone()
            status.trades_today = row[0] if row else 0

            # Win/loss from filled trades today
            cur.execute(
                """
                SELECT COUNT(*) FROM execution_journal
                WHERE submitted_at >= ? AND status = 'filled' AND side = 'Buy'
                """,
                (today_start,),
            )
            r = cur.fetchone()
            status.winning_trades = r[0] if r else 0

            cur.execute(
                """
                SELECT COUNT(*) FROM execution_journal
                WHERE submitted_at >= ? AND status = 'filled' AND side = 'Sell'
                """,
                (today_start,),
            )
            r = cur.fetchone()
            status.losing_trades = r[0] if r else 0

            # Recent trades (last HISTORY_LIMIT)
            cur.execute(
                """
                SELECT id, client_oid, exchange_oid, symbol, side, qty,
                       order_type, category, status, stop_loss, take_profit,
                       latency_ms, submitted_at, filled_at, recorded_at
                FROM execution_journal
                ORDER BY id DESC
                LIMIT ?
                """,
                (HISTORY_LIMIT,),
            )
            trades = []
            for row in cur.fetchall():
                trades.append(TradeRecord(
                    id          = row["id"],
                    client_oid  = row["client_oid"],
                    exchange_oid= row["exchange_oid"],
                    symbol      = row["symbol"],
                    side        = row["side"],
                    qty         = row["qty"],
                    order_type  = row["order_type"],
                    category    = row["category"],
                    status      = row["status"],
                    stop_loss   = row["stop_loss"],
                    take_profit = row["take_profit"],
                    latency_ms  = row["latency_ms"],
                    submitted_at= row["submitted_at"],
                    filled_at   = row["filled_at"],
                    recorded_at = row["recorded_at"],
                ))
            status.recent_trades = trades
            conn.close()

        except sqlite3.OperationalError:
            # Table may not exist yet (bot hasn't traded)
            pass
        except Exception:
            pass

    def _fire_new_trade_callbacks(self, status: BotStatus) -> None:
        """Notify if a trade appeared since last check."""
        if not self._cache or not status.recent_trades:
            return
        old_ids = {t.id for t in (self._cache.recent_trades or [])}
        for trade in status.recent_trades:
            if trade.id not in old_ids:
                if self._on_new_trade_cb:
                    try:
                        self._on_new_trade_cb(trade)
                    except Exception:
                        pass
                self._fire_event_callbacks(trade)


# ── StatusExporter (runs INSIDE bybit-bot, writes IPC file) ──────────────────

class StatusExporter:
    """
    Writes bot_status.json every N seconds.
    Should be started as an asyncio task inside bybit-bot.

    Usage in bybit-bot/main.py:
        from core.trading_bridge import StatusExporter
        exporter = StatusExporter(portfolio_mgr, risk_mgr, live_runner)
        asyncio.create_task(exporter.run())
    """

    def __init__(
        self,
        portfolio_manager=None,
        risk_manager=None,
        runner=None,
        output_path: str = _IPC_STATUS_FILE,
        interval_sec: float = 10.0,
    ) -> None:
        self._pm        = portfolio_manager
        self._rm        = risk_manager
        self._runner    = runner
        self._out       = Path(output_path)
        self._interval  = interval_sec
        self._running   = False

    async def run(self) -> None:
        import asyncio
        self._running = True
        self._out.parent.mkdir(parents=True, exist_ok=True)
        while self._running:
            try:
                await self._export()
            except Exception:
                pass
            await asyncio.sleep(self._interval)

    def stop(self) -> None:
        self._running = False

    async def _export(self) -> None:
        data: Dict[str, Any] = {"ts": time.time(), "mode": "unknown"}

        # Mode detection (runner attribute)
        if self._runner:
            mode_attr = getattr(self._runner, "mode", None)
            if mode_attr:
                data["mode"] = str(mode_attr)
            elif hasattr(self._runner, "_paper") and self._runner._paper:
                data["mode"] = "paper"
            else:
                data["mode"] = "live"

            # Active pairs / strategies
            pairs = getattr(self._runner, "_pairs", [])
            data["active_pairs"] = [str(p) for p in (pairs or [])]

            strategies = getattr(self._runner, "_strategies", {})
            data["active_strategies"] = list(strategies.keys()) if strategies else []

            # Open positions count
            positions = getattr(self._runner, "_positions", {})
            data["open_positions"] = len(positions) if positions else 0

        # Balance from portfolio manager
        if self._pm:
            try:
                snap = getattr(self._pm, "_total_balance", 0)
                data["balance_usdt"] = float(snap)
            except Exception:
                pass

        # Risk / PnL from risk manager
        if self._rm:
            try:
                data["daily_pnl"]     = float(getattr(self._rm, "_daily_pnl", 0))
                data["daily_pnl_pct"] = float(getattr(self._rm, "_daily_pnl_pct", 0))
            except Exception:
                pass

        with open(self._out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# ── Convenience function ──────────────────────────────────────────────────────

def get_trading_status_text() -> str:
    """Quick one-liner for orchestrator/agents: returns formatted status string."""
    try:
        return TradingBridge.get().get_status().summary_text()
    except Exception as e:
        return f"Trading bridge error: {e}"