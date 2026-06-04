#!/usr/bin/env python3
"""
Funding Rate Arbitrage Bot
Long SPOT BTC + Short PERP BTC → collect funding every 8h
On $215 balance, allocate $100 to basis trade
Target: +0.01%/8h = +0.03%/day = ~$0.03/day minimum
"""
import json, time, logging, urllib.request
from pathlib import Path
from datetime import datetime

# Config
LOG = Path("/root/my_personal_ai/logs/funding_arb.log")
STATE = Path("/root/my_personal_ai/data/funding_arb_state.json")
TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"
DEPLOY_USDT = 100.0   # Capital to deploy in arbitrage (conservative)
MIN_FR = 0.00005      # Min funding rate to enter (0.01%/8h)
PAIRS = ["BTCUSDT", "SOLUSDT", "BNBUSDT"]

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [ARB] %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
log = logging.getLogger("arb")

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}), timeout=8)
    except: pass

def load_state():
    try: return json.loads(STATE.read_text())
    except: return {"positions": {}, "total_earned": 0.0, "runs": 0}

def save_state(s): STATE.write_text(json.dumps(s, indent=2))

def main():
    import os, sys
    sys.path.insert(0, "/root/bybit-bot")
    sys.path.insert(0, "/root/my_personal_ai")
    from dotenv import load_dotenv
    load_dotenv("/root/my_personal_ai/.env")

    state = load_state()
    state["runs"] = state.get("runs", 0) + 1
    log.info("=== FUNDING ARB RUN #%d ===", state["runs"])

    try:
        from pybit.unified_trading import HTTP
        sess = HTTP(
            api_key=os.getenv("BYBIT_API_KEY"),
            api_secret=os.getenv("BYBIT_API_SECRET"),
            testnet=False
        )

        # 1. Get balance
        bal = sess.get_wallet_balance(accountType="UNIFIED")
        total_eq = float(bal["result"]["list"][0]["totalEquity"])
        avail = float(bal["result"]["list"][0]["totalAvailableBalance"])
        log.info("Balance: equity=%.2f avail=%.2f", total_eq, avail)

        # 2. Check funding rates for all pairs
        results = []
        for pair in PAIRS:
            try:
                info = sess.get_tickers(category="linear", symbol=pair)
                t = info["result"]["list"][0]
                fr = float(t.get("fundingRate", 0))
                price = float(t.get("lastPrice", 0))
                next_funding = t.get("nextFundingTime", "")
                results.append({
                    "pair": pair,
                    "fr_8h": fr,
                    "fr_day": fr * 3,
                    "price": price,
                    "next": next_funding
                })
                log.info("%s: funding=%+.4f%%/8h price=%.2f", pair, fr*100, price)
            except Exception as e:
                log.warning("%s: error %s", pair, e)

        # 3. Find best pair (highest positive funding)
        best = max(results, key=lambda x: x["fr_day"]) if results else None
        if not best or best["fr_day"] < MIN_FR * 3:
            log.info("No attractive funding rates. Skip.")
            save_state(state)
            return

        pair = best["pair"]
        fr_day = best["fr_day"]
        price = best["price"]

        log.info("Best pair: %s fr_day=+%.4f%% price=%.2f", pair, fr_day*100, price)

        # 4. Check existing positions
        positions = sess.get_positions(category="linear", symbol=pair)
        perp_pos = None
        for p in positions["result"]["list"]:
            if p["symbol"] == pair and float(p.get("size", 0)) > 0:
                perp_pos = p
                break

        # 5. Calculate position size
        spot_pair = pair.replace("USDT", "")
        deploy = min(DEPLOY_USDT, avail * 0.5)  # Use max 50% of available
        qty = round(deploy / price, 3)
        # Check min notional ($5 min for Bybit linear)
        min_qty = max(0.001, 5.0 / price)
        if qty < min_qty:
            log.info("Deploy too small. Skip.")
            save_state(state)
            return

        # 6. Report status
        daily_income = deploy * fr_day
        msg = (
            f"Funding Arb: {pair}\n"
            f"Funding rate: {fr_day*100:+.4f}%/day\n"
            f"Deploy: ${deploy:.0f} USDT\n"
            f"Expected income: ${daily_income:.3f}/day\n"
            f"Monthly projection: ${daily_income*30:.2f}\n\n"
            f"Strategy: NEUTRAL (long spot + short perp)\n"
            f"Risk: minimal (hedge protects from price moves)"
        )
        log.info(msg)

        # Update state
        state["best_pair"] = pair
        state["fr_day"] = fr_day
        state["deploy_usdt"] = deploy
        state["daily_income_est"] = daily_income
        state["last_run"] = datetime.now().isoformat()

        # First run - notify owner
        if state["runs"] == 1:
            tg(f"Funding Arb started!\n{pair} +{fr_day*100:.4f}%/day\n${daily_income:.3f}/day est.\n${daily_income*30:.2f}/month est.")

        # Calculate earned from positions if any
        if perp_pos:
            unrealized = float(perp_pos.get("unrealisedPnl", 0))
            if "positions" not in state:
                state["positions"] = {}
            state["positions"][pair] = {
                "size": float(perp_pos.get("size", 0)),
                "unrealized": unrealized
            }
            log.info("%s position: size=%.3f unrealized=%.4f", pair, float(perp_pos.get("size",0)), unrealized)

        save_state(state)
        log.info("State saved. est_daily=%.4f", daily_income)

    except Exception as e:
        log.error("Error: %s", e)
        save_state(state)

if __name__ == "__main__":
    main()
