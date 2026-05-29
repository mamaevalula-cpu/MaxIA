# -*- coding: utf-8 -*-
"""
tools/data_tools.py — Data manipulation utilities for AI agents.

Provides wrappers around pandas/numpy for common data tasks.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any


def df_from_candles(candles: List[Dict]) -> pd.DataFrame:
    """Convert OHLCV candle list to DataFrame."""
    df = pd.DataFrame(candles)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("ts")
    return df[["open","high","low","close","volume"]].astype(float).sort_index()


def resample_ohlcv(df: pd.DataFrame, rule: str = "1h") -> pd.DataFrame:
    """
    Resample OHLCV DataFrame to higher timeframe.
    rule: '1h', '4h', '1d', etc.
    """
    return df.resample(rule).agg({
        "open":   "first",
        "high":   "max",
        "low":    "min",
        "close":  "last",
        "volume": "sum",
    }).dropna()


def describe_series(s: pd.Series, name: str = "") -> str:
    """Return human-readable statistics for a Series."""
    stats = s.describe()
    return (
        f"{name + ': ' if name else ''}"
        f"count={int(stats['count'])}, "
        f"mean={stats['mean']:.4f}, "
        f"std={stats['std']:.4f}, "
        f"min={stats['min']:.4f}, "
        f"max={stats['max']:.4f}, "
        f"median={s.median():.4f}"
    )


def detect_pattern(df: pd.DataFrame) -> List[str]:
    """
    Detect common candlestick patterns.
    Returns list of detected pattern names.
    """
    patterns = []
    if len(df) < 3:
        return patterns

    c = df.iloc[-1]
    p = df.iloc[-2]
    pp = df.iloc[-3]

    body     = abs(c["close"] - c["open"])
    candle_r = c["high"] - c["low"]
    upper_sh = c["high"] - max(c["close"], c["open"])
    lower_sh = min(c["close"], c["open"]) - c["low"]

    # Doji — tiny body
    if candle_r > 0 and body / candle_r < 0.1:
        patterns.append("doji")

    # Hammer — small body, long lower shadow
    if candle_r > 0 and lower_sh / candle_r > 0.6 and upper_sh / candle_r < 0.1:
        patterns.append("hammer" if c["close"] > c["open"] else "hanging_man")

    # Shooting star — small body, long upper shadow
    if candle_r > 0 and upper_sh / candle_r > 0.6 and lower_sh / candle_r < 0.1:
        patterns.append("shooting_star")

    # Engulfing
    if (c["close"] > c["open"] and p["close"] < p["open"] and
            c["close"] > p["open"] and c["open"] < p["close"]):
        patterns.append("bullish_engulfing")
    elif (c["close"] < c["open"] and p["close"] > p["open"] and
              c["close"] < p["open"] and c["open"] > p["close"]):
        patterns.append("bearish_engulfing")

    # Morning star / Evening star
    if (pp["close"] < pp["open"] and
            abs(p["close"] - p["open"]) / (p["high"] - p["low"] + 1e-10) < 0.3 and
            c["close"] > c["open"] and c["close"] > (pp["open"] + pp["close"]) / 2):
        patterns.append("morning_star")

    return patterns


def find_swing_levels(df: pd.DataFrame, window: int = 10) -> Dict[str, float]:
    """Find recent swing high and swing low."""
    recent = df.tail(50)
    swing_high = float(recent["high"].rolling(window, center=True).max().max())
    swing_low  = float(recent["low"].rolling(window, center=True).min().min())
    return {"swing_high": round(swing_high, 4), "swing_low": round(swing_low, 4)}


def calc_position_size(balance: float, risk_pct: float,
                        entry: float, stop_loss: float) -> Dict[str, float]:
    """
    Calculate optimal position size based on risk management.

    Args:
        balance:   account balance in USDT
        risk_pct:  risk per trade (e.g. 0.01 for 1%)
        entry:     entry price
        stop_loss: stop loss price

    Returns:
        qty:         number of contracts/coins
        risk_usdt:   actual risk in USDT
        risk_pct:    actual risk percentage
    """
    risk_usdt  = balance * risk_pct
    price_diff = abs(entry - stop_loss)
    if price_diff == 0:
        return {"qty": 0, "risk_usdt": 0, "risk_pct": 0}
    qty = risk_usdt / price_diff
    return {
        "qty":      round(qty, 6),
        "risk_usdt": round(risk_usdt, 2),
        "risk_pct": risk_pct,
        "notional": round(qty * entry, 2),
    }


def volatility_regime(df: pd.DataFrame, window: int = 20) -> Dict[str, Any]:
    """
    Assess current volatility regime.
    Returns: regime, current_vol, avg_vol, percentile
    """
    returns   = df["close"].pct_change().dropna()
    current   = float(returns.tail(window).std() * (252 * 96) ** 0.5)  # annualized (15m)
    all_vols  = returns.rolling(window).std() * (252 * 96) ** 0.5
    avg_vol   = float(all_vols.mean())
    pct       = float((all_vols < current).sum() / len(all_vols) * 100)

    if current > avg_vol * 1.5:
        regime = "high_volatility"
    elif current < avg_vol * 0.5:
        regime = "low_volatility"
    else:
        regime = "normal"

    return {
        "regime":      regime,
        "current_vol": round(current, 4),
        "avg_vol":     round(avg_vol, 4),
        "percentile":  round(pct, 1),
    }
