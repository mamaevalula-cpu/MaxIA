#!/usr/bin/env python3
"""
trading_signal_watch.py
Runs every 5 minutes via cron.

Checks BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT for signals.
- If strong signal (confidence > 0.7): send Telegram alert
- Monitors SOLUSDT stop-loss proximity
- Reports risk level

Cron: */5 * * * * /root/venv/bin/python3 /root/my_personal_ai/scripts/trading_signal_watch.py
"""
import asyncio
import json
import logging
import os
import time
import urllib.request
from dotenv import load_dotenv

load_dotenv("/root/my_personal_ai/.env")

BYBIT_BASE     = os.getenv("BYBIT_BASE", "https://api.bybit.com")
BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_ID       = os.getenv("TELEGRAM_CHAT_ID", "")  # same as TELEGRAM_OWNER_ID
BYBIT_KEY      = os.getenv("BYBIT_API_KEY", "")
BYBIT_SECRET   = os.getenv("BYBIT_API_SECRET", "")

WATCH_SYMBOLS        = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
SIGNAL_THRESHOLD     = 0.7   # alert if confidence > this
SOLUSDT_SL_ALERT_USD = 81.00  # alert if SOLUSDT price crosses this
STATE_FILE           = "/root/my_personal_ai/data/signal_watch_state.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("signal_watch")


def send_telegram(msg: str):
    if not BOT_TOKEN or not OWNER_ID:
        log.warning("Telegram not configured")
        return
    try:
        body = json.dumps({"chat_id": OWNER_ID, "text": msg, "parse_mode": "HTML"})
        req  = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=body.encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            result = json.loads(r.read())
        if result.get("ok"):
            log.info("Telegram sent: %s...", msg[:60])
        else:
            log.error("Telegram error: %s", result)
    except Exception as e:
        log.error("Telegram send failed: %s", e)


def load_state() -> dict:
    try:
        if os.path.exists(STATE_FILE):
            return json.loads(open(STATE_FILE).read())
    except Exception:
        pass
    return {"last_alerts": {}, "last_sol_sl_alert": 0}


def save_state(state: dict):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        log.error("State save error: %s", e)


def ema(prices: list, period: int) -> float:
    k      = 2 / (period + 1)
    result = prices[0]
    for p in prices[1:]:
        result = p * k + result * (1 - k)
    return result


async def get_signal(symbol: str) -> dict:
    """Generate RSI+EMA signal for a symbol."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.get(
                f"{BYBIT_BASE}/v5/market/kline",
                params={"category": "linear", "symbol": symbol, "interval": "15", "limit": 200}
            )
            if r.status_code != 200:
                return {}
            candles = r.json().get("result", {}).get("list", [])
            if len(candles) < 50:
                return {}

            closes = [float(c[4]) for c in reversed(candles)]
            highs  = [float(c[2]) for c in reversed(candles)]
            lows   = [float(c[3]) for c in reversed(candles)]

            # RSI(14)
            gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, 15)]
            losses = [max(closes[i-1] - closes[i], 0) for i in range(1, 15)]
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            rs  = avg_gain / avg_loss if avg_loss > 0 else 100
            rsi = 100 - (100 / (1 + rs))

            ema20         = ema(closes, 20)
            ema50         = ema(closes, 50)
            current_price = closes[-1]

            trs = [
                max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
                for i in range(1, 15)
            ]
            atr = sum(trs) / 14

            signal     = "HOLD"
            confidence = 0.0

            if current_price > ema20 > ema50 and 40 < rsi < 65:
                signal     = "BUY"
                confidence = min((rsi - 40) / 25 * 0.6 + ((current_price - ema50) / ema50) * 5, 0.95)
            elif current_price < ema20 < ema50 and 35 < rsi < 60:
                signal     = "SELL"
                confidence = min((60 - rsi) / 25 * 0.6 + ((ema50 - current_price) / ema50) * 5, 0.95)
            elif rsi > 75:
                signal = "SELL"; confidence = 0.7
            elif rsi < 25:
                signal = "BUY";  confidence = 0.7

            trend = "uptrend" if current_price > ema20 > ema50 else (
                "downtrend" if current_price < ema20 < ema50 else "neutral"
            )

            return {
                "symbol":            symbol,
                "signal":            signal,
                "confidence":        round(confidence, 3),
                "rsi":               round(rsi, 2),
                "ema20":             round(ema20, 4),
                "ema50":             round(ema50, 4),
                "atr":               round(atr, 4),
                "price":             current_price,
                "trend":             trend,
                "stop_loss_long":    round(current_price - 2 * atr, 4),
                "stop_loss_short":   round(current_price + 2 * atr, 4),
                "take_profit_long":  round(current_price + 3 * atr, 4),
                "take_profit_short": round(current_price - 3 * atr, 4),
            }
    except Exception as e:
        log.debug("get_signal %s: %s", symbol, e)
        return {}


async def get_positions() -> list:
    """Get open positions from Bybit."""
    if not BYBIT_KEY or not BYBIT_SECRET:
        return []
    import hashlib, hmac as _hmac
    ts       = str(int(time.time() * 1000))
    params   = "category=linear&settleCoin=USDT"
    sign_str = ts + BYBIT_KEY + "5000" + params
    sig      = _hmac.new(BYBIT_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    headers  = {
        "X-BAPI-API-KEY":     BYBIT_KEY,
        "X-BAPI-TIMESTAMP":   ts,
        "X-BAPI-SIGN":        sig,
        "X-BAPI-RECV-WINDOW": "5000",
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as cli:
            r = await cli.get(
                f"{BYBIT_BASE}/v5/position/list?{params}",
                headers=headers
            )
            if r.status_code == 200:
                return [p for p in r.json().get("result", {}).get("list", [])
                        if float(p.get("size", 0)) > 0]
    except Exception as e:
        log.error("get_positions: %s", e)
    return []


async def main():
    state = load_state()
    now   = time.time()

    # 1. Get signals for all watched symbols
    tasks   = [get_signal(s) for s in WATCH_SYMBOLS]
    signals = await asyncio.gather(*tasks, return_exceptions=True)
    signals = [s for s in signals if isinstance(s, dict) and s]

    log.info("Got %d signals", len(signals))

    # 2. Check for strong signals and send alerts
    for sig in signals:
        symbol     = sig["symbol"]
        signal     = sig["signal"]
        confidence = sig["confidence"]
        rsi        = sig["rsi"]
        price      = sig["price"]
        trend      = sig["trend"]
        ema20      = sig["ema20"]
        ema50      = sig["ema50"]
        atr        = sig["atr"]

        last_alert = state["last_alerts"].get(f"{symbol}_{signal}", 0)
        # Don't spam: alert max once per 30 minutes per symbol+signal
        if confidence >= SIGNAL_THRESHOLD and (now - last_alert) > 1800:
            if signal == "BUY":
                sl = sig["stop_loss_long"]
                tp = sig["take_profit_long"]
                emoji = "LONG"
                direction = "LONG (BUY)"
            else:
                sl = sig["stop_loss_short"]
                tp = sig["take_profit_short"]
                emoji = "SHORT"
                direction = "SHORT (SELL)"

            msg = (
                f"SIGNAL: {symbol} {direction}\n\n"
                f"Confidence: {confidence:.0%}\n"
                f"Price: ${price:,.4f}\n"
                f"Trend: {trend}\n"
                f"RSI: {rsi:.1f}\n"
                f"EMA20: ${ema20:,.4f} | EMA50: ${ema50:,.4f}\n"
                f"ATR: ${atr:,.4f}\n\n"
                f"Entry: ${price:,.4f}\n"
                f"Stop Loss: ${sl:,.4f}\n"
                f"Take Profit: ${tp:,.4f}\n"
                f"R:R = 1:1.5\n\n"
                f"Panel: https://maxai.fyi"
            )
            send_telegram(msg)
            state["last_alerts"][f"{symbol}_{signal}"] = now
            log.info("Alert sent for %s %s confidence=%.2f", symbol, signal, confidence)

    # 3. Monitor SOLUSDT stop-loss proximity
    sol_signal = next((s for s in signals if s["symbol"] == "SOLUSDT"), None)
    if sol_signal:
        sol_price = sol_signal["price"]
        # Check if we have an open SHORT on SOLUSDT near stop-loss
        if sol_price >= SOLUSDT_SL_ALERT_USD:
            last_sl_alert = state.get("last_sol_sl_alert", 0)
            # Alert every 15 minutes while price stays near SL
            if (now - last_sl_alert) > 900:
                # Get actual positions to confirm SL level
                positions = await get_positions()
                sol_pos = next(
                    (p for p in positions if p.get("symbol") == "SOLUSDT" and p.get("side") == "Sell"),
                    None
                )
                if sol_pos:
                    entry_price = float(sol_pos.get("avgPrice", 0))
                    stop_loss   = float(sol_pos.get("stopLoss", 0))
                    pnl         = float(sol_pos.get("unrealisedPnl", 0))
                    qty         = float(sol_pos.get("size", 0))
                    gap         = stop_loss - sol_price if stop_loss > 0 else "UNKNOWN"
                    gap_str     = f"${gap:.2f}" if isinstance(gap, float) else gap

                    msg = (
                        f"WARNING: SOLUSDT SHORT — Stop Loss Imminent!\n\n"
                        f"Current Price: ${sol_price:,.2f}\n"
                        f"Stop Loss: ${stop_loss:,.2f}\n"
                        f"Gap to SL: {gap_str}\n"
                        f"Entry: ${entry_price:,.2f}\n"
                        f"Size: {qty} contracts\n"
                        f"Unrealized PnL: ${pnl:,.2f}\n\n"
                        f"RSI: {sol_signal['rsi']:.1f} | Trend: {sol_signal['trend']}\n\n"
                        f"Action: Consider closing manually or adjusting SL.\n"
                        f"Panel: https://maxai.fyi"
                    )
                    send_telegram(msg)
                    state["last_sol_sl_alert"] = now
                    log.info("SOLUSDT SL alert sent, price=%.2f sl=%.2f", sol_price, stop_loss)
                else:
                    # No confirmed position but price is high — alert anyway
                    last_sl_alert = state.get("last_sol_sl_alert", 0)
                    if (now - last_sl_alert) > 900:
                        msg = (
                            f"WARNING: SOLUSDT price ${sol_price:,.2f} has crossed ${SOLUSDT_SL_ALERT_USD:.2f}\n"
                            f"RSI: {sol_signal['rsi']:.1f} | Trend: {sol_signal['trend']}\n"
                            f"Check open positions: http://77.90.2.171"
                        )
                        send_telegram(msg)
                        state["last_sol_sl_alert"] = now

    # 4. Log summary
    summary = [
        f"  {s['symbol']:12s} {s['signal']:4s} conf={s['confidence']:.2f} rsi={s['rsi']:.1f} trend={s['trend']}"
        for s in signals
    ]
    log.info("Signal summary:\n%s", "\n".join(summary))

    save_state(state)


if __name__ == "__main__":
    asyncio.run(main())
