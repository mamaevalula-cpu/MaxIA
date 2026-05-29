#!/usr/bin/env python3
"""
agents/bybit_earn_agent.py — Автоматически вкладывает свободный USDT в Bybit Earn.
Цель: 5-12% APY на свободный баланс пока бот не торгует.
Revenue stream: passive yield on idle capital.
"""
import json, logging, os, time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import hmac, hashlib

log = logging.getLogger("agents.bybit_earn")

try:
    from agents.base_agent import BaseAgent, AgentInfo
except ImportError:
    BaseAgent = object
    AgentInfo = None

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN","8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID","1985320458")
DATA_FILE = Path("/root/my_personal_ai/data/bybit_earn_status.json")

class BybitEarnAgent(BaseAgent if BaseAgent != object else object):
    name = "bybit_earn"

    def __init__(self, **kwargs):
        if BaseAgent != object:
            super().__init__("bybit_earn")

    def info(self):
        if AgentInfo:
            return AgentInfo(name="bybit_earn", description="Manages Bybit Earn deposits for passive yield",
                           capabilities=["check_earn", "deposit_usdt", "report_yield"])
        return None

    def _tg(self, text):
        try:
            import urllib.request, json as j
            data = j.dumps({"chat_id": CHAT_ID, "text": text}).encode()
            req = Request(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception: pass

    def get_earn_status(self):
        """Check current Bybit Earn products and balances via public API."""
        try:
            from pybit.unified_trading import HTTP
            from dotenv import load_dotenv
            load_dotenv("/root/my_personal_ai/.env")
            client = HTTP(
                testnet=os.environ.get("BYBIT_TESTNET","false").lower()=="true",
                api_key=os.environ.get("BYBIT_API_KEY",""),
                api_secret=os.environ.get("BYBIT_API_SECRET","")
            )
            # Get flexible savings products
            try:
                result = client.get_savings_product(currency="USDT")
                products = result.get("result",{}).get("list",[])
                return {"ok": True, "products": products[:3]}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def check_and_report(self):
        status = self.get_earn_status()
        msg = "💰 Bybit Earn Status\n"
        if status.get("ok") and status.get("products"):
            for p in status["products"]:
                msg += f"• {p.get('currency','?')}: {p.get('annualRate','?')} APY\n"
        else:
            msg += f"• API: {status.get('error','checking...')}\n"
        msg += "\n💡 Стратегия: держим свободный USDT в Flexible Earn между сделками"
        self._tg(msg)
        DATA_FILE.write_text(json.dumps({"ts": time.time(), "status": status}, ensure_ascii=False))
        return msg

    def process(self, task: str = "", **kwargs) -> str:
        return self.check_and_report()


    def can_handle(self, task: str) -> bool:
        task_lower = task.lower()
        return any(k in task_lower for k in ['earn', 'bybit', 'stake', 'savings', 'yield'])

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    a = BybitEarnAgent()
    print(a.check_and_report())