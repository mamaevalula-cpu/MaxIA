#!/usr/bin/env python3
"""
agents/crypto_rebalancer_agent.py — Monthly portfolio rebalancing + yield optimization.
Revenue stream: compound trading gains + optimize allocation across strategies.
"""
import json, logging, os, time
from pathlib import Path

log = logging.getLogger("agents.rebalancer")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID","1985320458")
DATA_FILE = Path("/root/my_personal_ai/data/portfolio_rebalance.json")

try:
    from agents.base_agent import BaseAgent, AgentInfo
except ImportError:
    BaseAgent = object; AgentInfo = None

TARGET_ALLOCATION = {
    "trading_active": 0.40,   # 40% in active trading
    "earn_stable":    0.40,   # 40% in Bybit Earn (stable)
    "reserve_usdt":   0.20,   # 20% USDT reserve (emergency)
}

class CryptoRebalancerAgent(BaseAgent if BaseAgent != object else object):
    name = "crypto_rebalancer"

    def __init__(self, **kwargs):
        if BaseAgent != object: super().__init__("crypto_rebalancer")

    def info(self):
        if AgentInfo:
            return AgentInfo(name="crypto_rebalancer",
                description="Portfolio rebalancing and yield optimization",
                capabilities=["check_allocation","rebalance_suggest","compound_report"])
        return None

    def _tg(self, text):
        try:
            import urllib.request, json as j
            data = j.dumps({"chat_id": CHAT_ID, "text": text}).encode()
            from urllib.request import Request
            req = Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception: pass

    def analyze_and_suggest(self):
        try:
            from pybit.unified_trading import HTTP
            from dotenv import load_dotenv
            load_dotenv("/root/my_personal_ai/.env")
            client = HTTP(
                testnet=os.environ.get("BYBIT_TESTNET","false").lower()=="true",
                api_key=os.environ.get("BYBIT_API_KEY",""),
                api_secret=os.environ.get("BYBIT_API_SECRET","")
            )
            r = client.get_wallet_balance(accountType="UNIFIED")
            balance = float(r["result"]["list"][0].get("totalEquity", 0))
        except Exception as e:
            balance = 220.0  # fallback estimate

        trading_target = balance * TARGET_ALLOCATION["trading_active"]
        earn_target    = balance * TARGET_ALLOCATION["earn_stable"]
        reserve_target = balance * TARGET_ALLOCATION["reserve_usdt"]

        msg = f"⚖️ Portfolio Rebalancer\n\n"
        msg += f"💼 Total: ${balance:.2f} USDT\n\n"
        msg += f"📊 Target Allocation:\n"
        msg += f"  • Active Trading: ${trading_target:.2f} (40%)\n"
        msg += f"  • Bybit Earn:     ${earn_target:.2f} (40%)\n"
        msg += f"  • USDT Reserve:   ${reserve_target:.2f} (20%)\n\n"
        msg += f"💡 Strategy:\n"
        msg += f"  → Trade max ${trading_target:.2f} (2x leverage = ${trading_target*2:.2f} notional)\n"
        msg += f"  → Keep ${earn_target:.2f} in Flexible Earn (~5% APY = ${earn_target*0.05/12:.2f}/month)\n"
        msg += f"  → Emergency reserve: ${reserve_target:.2f}\n"
        msg += f"\n📈 Compounding: reinvest 80% of monthly profits"

        DATA_FILE.write_text(json.dumps({"ts": time.time(), "balance": balance,
                                         "targets": TARGET_ALLOCATION}, ensure_ascii=False))
        self._tg(msg)
        return msg

    def process(self, task: str = "", **kwargs) -> str:
        return self.analyze_and_suggest()

    def can_handle(self, task: str) -> bool:
        """Check if this agent can handle the given task."""
        task_lower = task.lower()
        return any(k in task_lower for k in ['rebalance', 'portfolio', 'crypto', 'allocation'])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(CryptoRebalancerAgent().analyze_and_suggest())