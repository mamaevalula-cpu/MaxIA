from __future__ import annotations
import logging
log = logging.getLogger("agents.business_intel")
FREE_APIS = [
    ("CoinGecko","https://api.coingecko.com/api/v3/ping","Crypto data free"),
    ("Groq","https://api.groq.com/openai/v1/models","Free LLM 500k/day"),
    ("Cerebras","https://api.cerebras.ai/v1/models","Free LLM ultrafast"),
    ("Bybit","https://api.bybit.com/v5/market/tickers?category=spot","Market data"),
]

class BusinessIntelAgent:
    name = "business_intel"
    def __init__(self): log.info("BusinessIntelAgent OK")
    def check_apis(self) -> str:
        results = []
        try:
            import httpx
            for name,url,desc in FREE_APIS:
                try:
                    r = httpx.get(url,timeout=5); st = "UP" if r.status_code < 400 else f"HTTP{r.status_code}"
                except Exception: st = "DOWN"
                results.append(f"  {name}: {st} - {desc}")
        except Exception as e:
            return f"Error: {e}"
        return "Free APIs:" + chr(10) + chr(10).join(results)
    def process(self, text: str) -> str:
        return self.check_apis()
