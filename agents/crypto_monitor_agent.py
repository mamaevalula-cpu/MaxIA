from __future__ import annotations
import logging, time, os, sqlite3
log = logging.getLogger("agents.crypto_monitor")
DB = "/root/my_personal_ai/data/crypto_prices.db"

class CryptoMonitorAgent:
    name = "crypto_monitor"
    def __init__(self):
        conn = sqlite3.connect(DB)
        conn.execute("CREATE TABLE IF NOT EXISTS prices(coin TEXT, price REAL, ts REAL)")
        conn.commit(); conn.close()
        log.info("CryptoMonitorAgent OK")
    def get_prices(self):
        try:
            import httpx
            r = httpx.get("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum,solana&vs_currencies=usd", timeout=10)
            return r.json()
        except Exception as e:
            log.error("CoinGecko: %s", e); return {}
    def check(self):
        prices = self.get_prices()
        if not prices: return "No price data"
        lines = [f"{c}: ${d.get('usd',0):,.0f}" for c,d in prices.items()]
        return "Crypto Prices:" + chr(10) + chr(10).join(lines)
    def process(self, text: str) -> str:
        return self.check()
