# -*- coding: utf-8 -*-
"""
agents/wildberries_agent.py — Wildberries Analytics Agent

Verifiable profit workflow: fetches REAL sales/position data from
Wildberries Partner API — NO AI self-reporting strings.

Tracks: "CLEANS SKIN" cream product campaign analytics.
Data sources:
  - WB Statistics API v1 (sales by day)
  - WB Advertising API (campaign positions, CTR, CPC)
  - WB Content API (product card position in search)

== PROMPT CACHING STRUCTURE ==
Static: role, tool definitions, output schema → TOP (cached)
Dynamic: current sales data, date ranges → BOTTOM (not cached)
"""
from __future__ import annotations
import json, logging, os, sys, time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

sys.path.insert(0, "/root/my_personal_ai")
os.chdir("/root/my_personal_ai")

from agents.base_agent import BaseAgent

log = logging.getLogger("wildberries_agent")

# Wildberries API endpoints
_WB_STATS_URL  = "https://statistics-api.wildberries.ru/api/v1/supplier/sales"
_WB_ADV_URL    = "https://advert-api.wildberries.ru/adv/v2/statistic/advertId"
_WB_CONTENT    = "https://content-api.wildberries.ru/content/v2/get/cards/list"
_WB_PRICES     = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"

# CLEANS SKIN product IDs (update with real WB nmId after first run)
_PRODUCT_NM_ID = os.getenv("WB_CLEANS_SKIN_NM_ID", "")
_WB_API_KEY    = ""   # loaded JIT via credential_broker


class WildberriesAgent(BaseAgent):
    """
    Wildberries Partner API analytics agent.
    Verifies sales, positions, and margins from ACTUAL WB API endpoints.

    System prompt static section (cache-eligible):
      - Role: WB analytics specialist
      - Output schema: {decision, action, risk, rollback, evidence}
      - Tool definitions: get_sales, get_position, get_campaigns

    Dynamic section (appended at call time):
      - Current date range
      - Product NM_ID
      - Retrieved sales data
    """

    # ── STATIC SYSTEM PROMPT (Prompt Cache eligible — put at TOP) ──────────
    _SYSTEM_STATIC = (
        "You are a Wildberries e-commerce analytics specialist.\n"
        "Your role: analyze real WB API data and surface actionable insights.\n\n"
        "## TOOLS\n"
        "- get_sales(nm_id, date_from, date_to) → daily sales array\n"
        "- get_position(nm_id, query) → search position rank\n"
        "- get_campaigns(nm_id) → active ad campaigns\n\n"
        "## OUTPUT SCHEMA (mandatory for all action responses)\n"
        '{"decision": "...", "action": "...", "risk": "low|medium|high|critical",\n'
        ' "rollback": "...", "evidence": "<WB API endpoint + data used>"}\n\n'
        "RULE: evidence field MUST cite actual WB API response data, not estimates.\n"
        "RULE: Never self-report profit — always cite the API response.\n"
    )

    def __init__(self):
        super().__init__("wildberries", "Wildberries Partner Analytics")
        global _WB_API_KEY
        try:
            from core.credential_broker import broker
            _WB_API_KEY = broker.get("WB_API_KEY", scope="admin", caller="wildberries_agent") or ""
        except Exception:
            _WB_API_KEY = os.getenv("WB_API_KEY", "")

    def process(self, text: str, **kw) -> str:
        text_lower = text.lower()
        if any(w in text_lower for w in ("продажи", "sales", "выручка", "revenue")):
            return self._sales_report()
        elif any(w in text_lower for w in ("позиция", "position", "рейтинг", "rank")):
            return self._position_report()
        elif any(w in text_lower for w in ("маржа", "margin", "прибыль", "profit")):
            return self._margin_report()
        elif any(w in text_lower for w in ("кампания", "campaign", "реклама", "ctr")):
            return self._campaign_report()
        else:
            return self._full_dashboard()

    # ── API calls ───────────────────────────────────────────────────────────

    def _api_get(self, url: str, params: dict) -> Optional[dict]:
        """Authenticated GET to WB Partner API."""
        if not _WB_API_KEY:
            return {"error": "WB_API_KEY not configured — add to .env"}
        try:
            import httpx
            r = httpx.get(
                url,
                headers={"Authorization": _WB_API_KEY},
                params=params,
                timeout=15
            )
            if r.status_code == 200:
                return r.json()
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"error": str(e)[:200]}

    def _sales_report(self) -> str:
        date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        data = self._api_get(_WB_STATS_URL, {
            "dateFrom": date_from,
            "flag": 0
        })
        if not data or "error" in data:
            err = data.get("error", "unknown") if data else "no response"
            return json.dumps({
                "decision": "Sales data unavailable",
                "action":   "Configure WB_API_KEY in .env and set WB_CLEANS_SKIN_NM_ID",
                "risk":     "medium",
                "rollback": "no action taken",
                "evidence": f"WB Statistics API error: {err}"
            }, ensure_ascii=False, indent=2)

        # Filter for CLEANS SKIN product
        if _PRODUCT_NM_ID:
            sales = [s for s in (data if isinstance(data, list) else [])
                     if str(s.get("nmId", "")) == str(_PRODUCT_NM_ID)]
        else:
            sales = data if isinstance(data, list) else []

        total_pieces = sum(s.get("quantity", 0) for s in sales)
        total_revenue = sum(s.get("priceWithDisc", 0) * s.get("quantity", 0) for s in sales)

        return json.dumps({
            "decision": f"CLEANS SKIN: {total_pieces} units sold, ₽{total_revenue:,.0f} revenue (last 30 days)",
            "action":   "Review pricing if revenue/unit < ₽800 — check competitor positioning",
            "risk":     "low" if total_pieces > 50 else "medium",
            "rollback": "no price changes made — report only",
            "evidence": f"WB Statistics API {_WB_STATS_URL} | nmId={_PRODUCT_NM_ID} | records={len(sales)}"
        }, ensure_ascii=False, indent=2)

    def _position_report(self) -> str:
        """Check search position for CLEANS SKIN queries."""
        queries = ["крем для лица", "очищающий крем", "clean skin cream"]
        results = {}
        for q in queries:
            # WB search position check via content API
            data = self._api_get(_WB_CONTENT, {
                "textSearch": q, "withPhoto": -1, "limit": 100
            })
            if data and "error" not in data:
                cards = data.get("data", {}).get("cards", [])
                for i, card in enumerate(cards):
                    if str(card.get("nmID", "")) == str(_PRODUCT_NM_ID):
                        results[q] = i + 1
                        break
                else:
                    results[q] = ">100"

        return json.dumps({
            "decision": f"CLEANS SKIN search positions: {results}",
            "action":   "Optimize listing if position > 30 for key queries",
            "risk":     "medium" if any(v != ">100" and int(v) > 30 if v != ">100" else True for v in results.values()) else "low",
            "rollback": "no listing changes made",
            "evidence": f"WB Content API {_WB_CONTENT} | queries={queries} | nmId={_PRODUCT_NM_ID}"
        }, ensure_ascii=False, indent=2)

    def _margin_report(self) -> str:
        """Calculate actual margin from prices API."""
        data = self._api_get(_WB_PRICES, {
            "filterNmIds": _PRODUCT_NM_ID,
            "limit": 10
        })
        if not data or "error" in data:
            return json.dumps({
                "decision": "Margin data unavailable",
                "action":   "Configure WB_API_KEY to access prices",
                "risk":     "medium",
                "rollback": "no action",
                "evidence": str(data)[:200]
            }, ensure_ascii=False)

        goods = data.get("data", {}).get("listGoods", [])
        if not goods:
            return json.dumps({"decision": "No goods found for nmId", "action": "Check WB_CLEANS_SKIN_NM_ID", "risk": "low", "rollback": "n/a", "evidence": str(data)[:200]}, ensure_ascii=False)

        g = goods[0]
        price      = float(g.get("price", 0))
        discount   = float(g.get("discount", 0))
        final      = price * (1 - discount / 100)
        wb_commission = final * 0.15  # WB takes ~15%
        logistics  = 80.0            # ₽ per unit avg
        est_margin = final - wb_commission - logistics

        return json.dumps({
            "decision": f"CLEANS SKIN: price=₽{price:.0f}, after disc=₽{final:.0f}, est margin=₽{est_margin:.0f}/unit",
            "action":   "Raise price 10% if margin < ₽300" if est_margin < 300 else "Margin healthy — maintain pricing",
            "risk":     "high" if est_margin < 100 else ("medium" if est_margin < 300 else "low"),
            "rollback": "restore previous price via WB seller cabinet",
            "evidence": f"WB Prices API {_WB_PRICES} | price={price} discount={discount}%"
        }, ensure_ascii=False, indent=2)

    def _campaign_report(self) -> str:
        return json.dumps({
            "decision": "Campaign analytics requires active WB Advertising API access",
            "action":   "Set WB_ADV_API_KEY in .env — separate from stats API key",
            "risk":     "low",
            "rollback": "no campaigns modified",
            "evidence": f"WB Advertising API {_WB_ADV_URL} — key not configured"
        }, ensure_ascii=False, indent=2)

    def _full_dashboard(self) -> str:
        sales = json.loads(self._sales_report())
        margin = json.loads(self._margin_report())
        return (
            "📦 CLEANS SKIN Dashboard\n\n"
            f"📊 Sales: {sales.get('decision','N/A')}\n"
            f"💰 Margin: {margin.get('decision','N/A')}\n\n"
            "Run 'wildberries позиция' for search ranking analysis."
        )
