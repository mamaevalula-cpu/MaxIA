from __future__ import annotations
import logging, os
log = logging.getLogger("agents.market_scanner")

class MarketScannerAgent:
    name = "market_scanner"
    def __init__(self): log.info("MarketScannerAgent OK")
    def scan(self) -> str:
        try:
            import httpx
            r = httpx.get("https://api.bybit.com/v5/market/tickers?category=linear", timeout=10)
            tickers = r.json().get("result",{}).get("list",[])
            sigs = []
            for t in tickers[:100]:
                sym = t.get("symbol","")
                if not sym.endswith("USDT"): continue
                chg = float(t.get("price24hPcnt",0) or 0)*100
                vol = float(t.get("volume24h",0) or 0)
                if vol > 500000 and abs(chg) > 4:
                    sigs.append(f"  {sym}: {chg:+.1f}% vol={vol/1e6:.0f}M")
            return "Market signals:" + chr(10) + chr(10).join(sigs[:8]) if sigs else "No strong signals"
        except Exception as e:
            return f"Scanner error: {e}"
    def process(self, text: str) -> str:
        return self.scan()
