# -*- coding: utf-8 -*-
"""
tools/analysis.py — Market analysis tools using pandas + ta library.

AI agents use these tools for:
  - Technical indicator calculation (RSI, MACD, EMA, BB, ATR...)
  - Market regime detection (trending/ranging)
  - Pattern recognition (support/resistance, candlestick patterns)
  - Statistical analysis (correlation, volatility, Z-score)
  - Simple backtesting

Usage example:
    from tools.analysis import analyze_market, calc_indicators

    # Get candles from Bybit
    candles = exchange.get_klines("BTCUSDT", "15", 200)

    # Full analysis
    result = analyze_market(candles, symbol="BTCUSDT")
    print(result["summary"])  # "BTC: RSI=65.2, Trend=UP, Signal=WAIT"

    # Just indicators
    df = calc_indicators(candles)
    print(df[["close","rsi","macd","bb_upper"]].tail(5))
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("tools.analysis")


def df_from_candles(candles: List[Dict]) -> pd.DataFrame:
    """Convert list of OHLCV dicts to DataFrame with datetime index."""
    df = pd.DataFrame(candles)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df = df.astype(float).sort_index()
    return df


def calc_indicators(candles: List[Dict], periods: Dict = None) -> pd.DataFrame:
    """
    Calculate common technical indicators.
    Returns DataFrame with all indicators as columns.

    Default periods:
      rsi=14, macd_fast=12, macd_slow=26, macd_signal=9
      ema_fast=9, ema_slow=21, ema_200=200
      bb_period=20, bb_std=2.0
      atr_period=14, stoch_k=14, stoch_d=3
    """
    p = {
        "rsi": 14, "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
        "ema_fast": 9, "ema_slow": 21, "ema_200": 200,
        "bb_period": 20, "bb_std": 2.0,
        "atr_period": 14, "stoch_k": 14, "stoch_d": 3,
        "vol_ma": 20,
    }
    if periods:
        p.update(periods)

    df = df_from_candles(candles)

    # ── Trend indicators ─────────────────────────────────────────
    df["ema_fast"]  = df["close"].ewm(span=p["ema_fast"],  adjust=False).mean()
    df["ema_slow"]  = df["close"].ewm(span=p["ema_slow"],  adjust=False).mean()
    df["ema_200"]   = df["close"].ewm(span=p["ema_200"],   adjust=False).mean()
    df["ema_trend"] = np.where(df["ema_fast"] > df["ema_slow"], 1, -1)

    # ── Momentum: RSI ────────────────────────────────────────────
    delta = df["close"].diff()
    gain  = delta.clip(lower=0).rolling(p["rsi"]).mean()
    loss  = (-delta.clip(upper=0)).rolling(p["rsi"]).mean()
    rs    = gain / loss.replace(0, 1e-10)
    df["rsi"] = 100 - (100 / (1 + rs))

    # ── MACD ─────────────────────────────────────────────────────
    ema_f = df["close"].ewm(span=p["macd_fast"], adjust=False).mean()
    ema_s = df["close"].ewm(span=p["macd_slow"], adjust=False).mean()
    df["macd"]        = ema_f - ema_s
    df["macd_signal"] = df["macd"].ewm(span=p["macd_signal"], adjust=False).mean()
    df["macd_hist"]   = df["macd"] - df["macd_signal"]

    # ── Bollinger Bands ──────────────────────────────────────────
    df["bb_mid"]   = df["close"].rolling(p["bb_period"]).mean()
    bb_std         = df["close"].rolling(p["bb_period"]).std()
    df["bb_upper"] = df["bb_mid"] + p["bb_std"] * bb_std
    df["bb_lower"] = df["bb_mid"] - p["bb_std"] * bb_std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_pct"]   = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, 1e-10)

    # ── ATR (Average True Range) ─────────────────────────────────
    hl  = df["high"] - df["low"]
    hpc = (df["high"] - df["close"].shift(1)).abs()
    lpc = (df["low"]  - df["close"].shift(1)).abs()
    df["atr"] = pd.concat([hl, hpc, lpc], axis=1).max(axis=1).rolling(p["atr_period"]).mean()

    # ── Stochastic ───────────────────────────────────────────────
    low_n  = df["low"].rolling(p["stoch_k"]).min()
    high_n = df["high"].rolling(p["stoch_k"]).max()
    df["stoch_k"] = 100 * (df["close"] - low_n) / (high_n - low_n + 1e-10)
    df["stoch_d"] = df["stoch_k"].rolling(p["stoch_d"]).mean()

    # ── Volume ───────────────────────────────────────────────────
    df["vol_ma"]    = df["volume"].rolling(p["vol_ma"]).mean()
    df["vol_ratio"] = df["volume"] / df["vol_ma"].replace(0, 1e-10)

    # ── Support / Resistance (simple pivot points) ───────────────
    df["pivot"]    = (df["high"] + df["low"] + df["close"]) / 3
    df["resist_1"] = 2 * df["pivot"] - df["low"]
    df["support_1"]= 2 * df["pivot"] - df["high"]

    return df


def detect_market_regime(df: pd.DataFrame) -> str:
    """
    Detect market regime: 'trending_up', 'trending_down', 'ranging', 'volatile'.
    Uses ADX-style calculation + BB width.
    """
    if len(df) < 50:
        return "unknown"

    cur = df.iloc[-1]
    last20 = df.iloc[-20:]

    # ADX proxy: directional movement
    price_range    = last20["close"].max() - last20["close"].min()
    avg_atr        = last20["atr"].mean() if "atr" in df.columns else 0
    atr_multiple   = price_range / avg_atr if avg_atr > 0 else 0

    # BB width vs its 50-period average
    bb_width_now   = cur.get("bb_width", 0)
    bb_width_avg   = df["bb_width"].rolling(50).mean().iloc[-1] if "bb_width" in df.columns else 0

    # EMA alignment
    ema_aligned_up  = (cur.get("ema_fast",0) > cur.get("ema_slow",0) > 0)
    ema_aligned_dn  = (cur.get("ema_fast",0) < cur.get("ema_slow",0))

    if atr_multiple > 3 and bb_width_now > bb_width_avg * 1.5:
        return "volatile"
    elif bb_width_now < bb_width_avg * 0.8:
        return "ranging"
    elif ema_aligned_up and atr_multiple > 1.5:
        return "trending_up"
    elif ema_aligned_dn and atr_multiple > 1.5:
        return "trending_down"
    return "ranging"


def find_support_resistance(df: pd.DataFrame, window: int = 20) -> Dict[str, List[float]]:
    """Find key support and resistance levels using local min/max."""
    highs = df["high"].rolling(window, center=True).max()
    lows  = df["low"].rolling(window, center=True).min()

    resistance_levels = sorted(set(
        round(v, 2) for v in highs.dropna().tail(100)
        if v == df["high"][highs == v].iloc[0] if len(df["high"][highs == v]) > 0
    ), reverse=True)[:5]

    support_levels = sorted(set(
        round(v, 2) for v in lows.dropna().tail(100)
        if v == df["low"][lows == v].iloc[0] if len(df["low"][lows == v]) > 0
    ), reverse=True)[:5]

    return {"resistance": resistance_levels, "support": support_levels}


def calc_correlation(series1: pd.Series, series2: pd.Series, periods: int = 30) -> float:
    """Calculate rolling correlation between two price series."""
    return float(series1.pct_change().rolling(periods).corr(series2.pct_change()).iloc[-1])


def calc_zscore(series: pd.Series, window: int = 20) -> pd.Series:
    """Calculate Z-score (how many std devs from mean)."""
    mean = series.rolling(window).mean()
    std  = series.rolling(window).std()
    return (series - mean) / std.replace(0, 1e-10)


def analyze_market(candles: List[Dict], symbol: str = "") -> Dict[str, Any]:
    """
    Full market analysis: indicators + regime + signals + summary.

    Returns dict with:
      summary: str    — human-readable one-line summary
      regime:  str    — 'trending_up'|'trending_down'|'ranging'|'volatile'
      signal:  str    — 'BUY'|'SELL'|'HOLD'
      strength: float — signal strength 0.0-1.0
      indicators: dict — all current indicator values
      support: list   — support levels
      resistance: list — resistance levels
    """
    df = calc_indicators(candles)
    cur = df.iloc[-1]
    regime = detect_market_regime(df)

    # Signal generation
    signal   = "HOLD"
    strength = 0.0
    reasons  = []

    rsi         = cur.get("rsi", 50)
    macd_hist   = cur.get("macd_hist", 0)
    bb_pct      = cur.get("bb_pct", 0.5)
    ema_trend   = cur.get("ema_trend", 0)
    vol_ratio   = cur.get("vol_ratio", 1.0)
    stoch_k     = cur.get("stoch_k", 50)

    bull_points = 0
    bear_points = 0

    if rsi < 35:       bull_points += 2; reasons.append(f"RSI oversold({rsi:.0f})")
    elif rsi > 65:     bear_points += 2; reasons.append(f"RSI overbought({rsi:.0f})")
    elif 45 < rsi < 60: bull_points += 1

    if macd_hist > 0:  bull_points += 1; reasons.append("MACD bullish")
    elif macd_hist < 0: bear_points += 1; reasons.append("MACD bearish")

    if bb_pct < 0.2:   bull_points += 2; reasons.append("BB lower touch")
    elif bb_pct > 0.8: bear_points += 2; reasons.append("BB upper touch")

    if ema_trend == 1: bull_points += 1
    elif ema_trend == -1: bear_points += 1

    if vol_ratio > 1.5: reasons.append(f"High volume({vol_ratio:.1f}x)")

    if stoch_k < 20:   bull_points += 1
    elif stoch_k > 80: bear_points += 1

    total = bull_points + bear_points
    if total > 0:
        if bull_points > bear_points + 1:
            signal   = "BUY"
            strength = min(bull_points / (total + 2), 0.95)
        elif bear_points > bull_points + 1:
            signal   = "SELL"
            strength = min(bear_points / (total + 2), 0.95)

    indicators = {
        "close":    round(float(cur["close"]), 6),
        "rsi":      round(float(rsi), 2),
        "macd":     round(float(cur.get("macd", 0)), 6),
        "macd_hist":round(float(macd_hist), 6),
        "ema_fast": round(float(cur.get("ema_fast", 0)), 4),
        "ema_slow": round(float(cur.get("ema_slow", 0)), 4),
        "bb_upper": round(float(cur.get("bb_upper", 0)), 4),
        "bb_lower": round(float(cur.get("bb_lower", 0)), 4),
        "bb_pct":   round(float(bb_pct), 3),
        "atr":      round(float(cur.get("atr", 0)), 4),
        "vol_ratio":round(float(vol_ratio), 2),
        "stoch_k":  round(float(stoch_k), 1),
    }

    summary = (
        f"{symbol + ': ' if symbol else ''}"
        f"RSI={rsi:.0f} | Regime={regime} | Signal={signal}({strength:.0%})"
        f"{' | ' + ', '.join(reasons[:3]) if reasons else ''}"
    )

    return {
        "symbol":     symbol,
        "summary":    summary,
        "regime":     regime,
        "signal":     signal,
        "strength":   round(strength, 3),
        "indicators": indicators,
        "candles":    len(candles),
    }


def backtest_simple(candles: List[Dict], strategy_fn,
                    initial_balance: float = 10000.0,
                    risk_per_trade: float = 0.01) -> Dict:
    """
    Simple backtest engine.
    strategy_fn: callable(df, i) → 'BUY'|'SELL'|'HOLD'

    Returns:
      total_return: float (e.g. 0.15 = +15%)
      trades: int
      win_rate: float
      max_drawdown: float
      sharpe: float
    """
    df = calc_indicators(candles)
    balance = initial_balance
    peak    = initial_balance
    in_pos  = False
    entry   = 0.0
    trades  = []

    for i in range(50, len(df)):
        price  = float(df["close"].iloc[i])
        action = strategy_fn(df, i)

        if action == "BUY" and not in_pos:
            risk_amt = balance * risk_per_trade
            qty      = risk_amt / (price * 0.015)  # 1.5% SL
            in_pos   = True
            entry    = price

        elif action == "SELL" and in_pos:
            pnl       = (price - entry) / entry * balance * risk_per_trade / 0.015
            balance  += pnl
            peak      = max(peak, balance)
            trades.append(pnl)
            in_pos    = False

    wins     = [t for t in trades if t > 0]
    losses   = [t for t in trades if t <= 0]
    total_r  = (balance - initial_balance) / initial_balance

    # Sharpe (annualized, assume 15m candles)
    if len(trades) > 1:
        daily_r  = pd.Series(trades) / initial_balance
        sharpe   = float(daily_r.mean() / daily_r.std() * (252 ** 0.5)) if daily_r.std() > 0 else 0
    else:
        sharpe   = 0.0

    drawdowns = []
    peak_bt   = initial_balance
    bal_cur   = initial_balance
    for t in trades:
        bal_cur  += t
        peak_bt   = max(peak_bt, bal_cur)
        drawdowns.append((peak_bt - bal_cur) / peak_bt)

    return {
        "total_return":   round(total_r, 4),
        "total_return_pct": f"{total_r*100:+.2f}%",
        "final_balance":  round(balance, 2),
        "trades":         len(trades),
        "win_rate":       round(len(wins) / len(trades), 3) if trades else 0,
        "avg_win":        round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss":       round(sum(losses) / len(losses), 2) if losses else 0,
        "max_drawdown":   round(max(drawdowns), 4) if drawdowns else 0,
        "sharpe":         round(sharpe, 3),
        "profit_factor":  round(abs(sum(wins) / sum(losses)), 3) if losses and sum(losses) != 0 else 0,
    }


class MarketAnalyzer:
    """
    High-level market analyzer for AI agents.
    Caches results to avoid redundant calculations.
    """

    def __init__(self):
        self._cache: Dict[str, Tuple] = {}
        self._cache_ttl = 60  # seconds

    def analyze(self, symbol: str, candles: List[Dict]) -> str:
        """
        Analyze market and return human-readable string for AI response.

        Example output:
        "BTCUSDT анализ (200 свечей, 15m):
         📊 Режим рынка: ranging (боковик)
         📈 RSI: 58.3 — нейтральный
         📉 MACD: гистограмма положительная (+12.4)
         🎯 EMA9=94,120 > EMA21=93,950 — краткосрочный бычий тренд
         📦 BB: цена в середине канала (pct=0.54)
         🔊 Объём: 1.2x от среднего
         💡 Сигнал: HOLD (слабый — нет подтверждения)"
        """
        cache_key = f"{symbol}:{len(candles)}"
        if cache_key in self._cache:
            result, ts = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return result

        import time as _time
        result_dict = analyze_market(candles, symbol)
        ind = result_dict["indicators"]
        regime_emoji = {
            "trending_up": "🚀", "trending_down": "📉",
            "ranging": "↔️", "volatile": "⚡", "unknown": "❓"
        }.get(result_dict["regime"], "❓")

        signal_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(result_dict["signal"], "⚪")

        text = f"""**{symbol} — Технический анализ** ({result_dict['candles']} свечей)

{regime_emoji} **Режим рынка:** {result_dict['regime']}
📊 **RSI({14}):** {ind['rsi']:.1f} {'🔴 перекуплен' if ind['rsi']>70 else '🟢 перепродан' if ind['rsi']<30 else '⚪ нейтральный'}
📈 **MACD гистограмма:** {ind['macd_hist']:+.4f} {'↑' if ind['macd_hist']>0 else '↓'}
🎯 **EMA9/21:** {ind['ema_fast']:.2f} / {ind['ema_slow']:.2f} — {'бычье' if ind['ema_fast']>ind['ema_slow'] else 'медвежье'} пересечение
📦 **BB позиция:** {ind['bb_pct']:.0%} ({'верх' if ind['bb_pct']>0.8 else 'низ' if ind['bb_pct']<0.2 else 'центр'})
🔊 **Объём:** {ind['vol_ratio']:.1f}x от среднего
📐 **ATR:** {ind['atr']:.4f} (волатильность)
🎲 **Stochastic:** {ind['stoch_k']:.0f} {'🔴' if ind['stoch_k']>80 else '🟢' if ind['stoch_k']<20 else '⚪'}

{signal_emoji} **Сигнал: {result_dict['signal']}** (сила: {result_dict['strength']:.0%})"""

        self._cache[cache_key] = (text, _time.time())
        return text


import time  # needed for cache TTL
_default_analyzer = MarketAnalyzer()
