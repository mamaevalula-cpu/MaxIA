# -*- coding: utf-8 -*-
"""
agents/coffee_sourcing_agent.py — Colombia Coffee Sourcing Pipeline

Deterministic margin calculator for 600kg green bean logistics.
Uses REAL-TIME COP/RUB exchange rates — never AI-estimated rates.

Pipeline:
  1. Fetch live COP/RUB rate from CBR (Bank of Russia) or exchangerate.host
  2. Calculate margin: purchase_COP → logistics → customs → RUB sale price
  3. Surface leads ONLY if net margin > MIN_MARGIN_PCT threshold
  4. All figures cited from external API sources (never self-reported)

== PROMPT CACHING STRUCTURE ==
Static: role, margin formula, output schema → TOP (cached)
Dynamic: current rates, batch size, supplier quotes → BOTTOM
"""
from __future__ import annotations
import json, logging, os, sys, time
from typing import Dict, Optional

sys.path.insert(0, "/root/my_personal_ai")
os.chdir("/root/my_personal_ai")

from agents.base_agent import BaseAgent

log = logging.getLogger("coffee_sourcing_agent")

# Sourcing parameters
_DEFAULT_BATCH_KG     = 600.0
_MIN_MARGIN_PCT       = 35.0   # Minimum acceptable margin %
_AVG_PRICE_COP_KG     = 18_000  # COP per kg green beans (market avg, update from API)
_LOGISTICS_RUB_KG     = 120.0   # ₽ per kg (shipping COP→RUS, customs, cert)
_SALE_PRICE_RUB_KG    = 1_800.0 # ₽ per kg target wholesale in Russia


class CoffeeSourcingAgent(BaseAgent):
    """
    Colombia coffee sourcing margin calculator.

    Static system prompt (cache-eligible at top):
      - Role definition
      - Margin formula
      - Output schema

    Dynamic context (appended at bottom):
      - Live COP/RUB rate
      - Current batch parameters
      - Supplier quote if provided
    """

    # ── STATIC SYSTEM PROMPT (Prompt Cache eligible) ─────────────────────
    _SYSTEM_STATIC = (
        "You are a commodity sourcing specialist for Colombia → Russia green coffee trade.\n"
        "Margin formula: NET_MARGIN = (SALE_RUB - PURCHASE_RUB - LOGISTICS_RUB) / SALE_RUB * 100\n"
        "PURCHASE_RUB = PRICE_COP_KG * BATCH_KG / COP_PER_RUB\n\n"
        "## OUTPUT SCHEMA\n"
        '{"decision": "...", "action": "...", "risk": "low|medium|high|critical",\n'
        ' "rollback": "...", "evidence": "<exchange rate source + date + rate used>"}\n\n'
        "RULE: evidence MUST cite the actual exchange rate source URL and rate.\n"
        "RULE: Never proceed with a deal if margin < 35%.\n"
        "RULE: Factor in 20% customs duty on CIF value for Russian import.\n"
    )

    def __init__(self):
        super().__init__("coffee_sourcing", "Colombia Coffee Sourcing Pipeline")

    def process(self, text: str, **kw) -> str:
        text_lower = text.lower()
        # Parse batch size if specified
        batch_kg = _DEFAULT_BATCH_KG
        import re
        m = re.search(r'(\d+)\s*(?:кг|kg)', text_lower)
        if m:
            batch_kg = float(m.group(1))

        # Parse supplier price if given
        price_cop = _AVG_PRICE_COP_KG
        m2 = re.search(r'(\d[\d,]+)\s*cop', text_lower)
        if m2:
            price_cop = float(m2.group(1).replace(",", ""))

        return self._margin_analysis(batch_kg, price_cop)

    # ── Core logic ──────────────────────────────────────────────────────────

    def _get_cop_rub_rate(self) -> tuple:
        """
        Fetch live COP/RUB rate.
        Priority: CBR (Bank of Russia) → exchangerate.host → fallback estimate.
        Returns (rate, source_url, timestamp).
        """
        # Source 1: CBR XML daily rates
        try:
            import httpx
            r = httpx.get(
                "https://www.cbr.ru/scripts/XML_daily.asp",
                timeout=10,
                headers={"User-Agent": "MaxAI/1.0 coffee-sourcing"}
            )
            if r.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(r.content)
                date_attr = root.attrib.get("Date", "?")
                for valute in root.findall("Valute"):
                    char_code = valute.findtext("CharCode", "")
                    if char_code == "COP":
                        nominal = float(valute.findtext("Nominal", "1000").replace(",","."))
                        value   = float(valute.findtext("Value", "0").replace(",","."))
                        rate_per_1 = value / nominal  # RUB per 1 COP
                        return (
                            rate_per_1,
                            f"https://www.cbr.ru/scripts/XML_daily.asp (date={date_attr})",
                            date_attr
                        )
        except Exception as e:
            log.debug("CBR fetch failed: %s", e)

        # Source 2: exchangerate.host (free tier)
        try:
            import httpx
            r = httpx.get(
                "https://api.exchangerate.host/convert",
                params={"from": "COP", "to": "RUB", "amount": 1},
                timeout=10
            )
            if r.status_code == 200:
                d = r.json()
                if d.get("success"):
                    rate = float(d["result"])
                    return (
                        rate,
                        "https://api.exchangerate.host/convert?from=COP&to=RUB",
                        d.get("date", time.strftime("%Y-%m-%d"))
                    )
        except Exception as e:
            log.debug("exchangerate.host failed: %s", e)

        # Source 3: OpenExchangeRates via USD pivot
        try:
            import httpx
            r = httpx.get(
                "https://open.er-api.com/v6/latest/COP",
                timeout=10
            )
            if r.status_code == 200:
                d = r.json()
                rub_per_cop = d.get("rates", {}).get("RUB", 0)
                if rub_per_cop:
                    return (
                        float(rub_per_cop),
                        "https://open.er-api.com/v6/latest/COP",
                        d.get("time_last_update_utc", "?")
                    )
        except Exception as e:
            log.debug("open.er-api.com failed: %s", e)

        # Fallback (estimated — explicitly flagged as such)
        return (0.022, "FALLBACK_ESTIMATE — no live API available", "N/A")

    def _margin_analysis(self, batch_kg: float, price_cop_kg: float) -> str:
        rate, source, rate_date = self._get_cop_rub_rate()

        # ── Margin calculation (deterministic) ──────────────────────────────
        purchase_cop_total  = price_cop_kg * batch_kg
        purchase_rub_total  = purchase_cop_total * rate

        # Logistics: shipping + customs (20% of CIF) + certification
        logistics_per_kg    = _LOGISTICS_RUB_KG
        logistics_total     = logistics_per_kg * batch_kg
        customs_duty        = purchase_rub_total * 0.20   # 20% of purchase value
        total_cost_rub      = purchase_rub_total + logistics_total + customs_duty

        # Revenue
        revenue_rub         = _SALE_PRICE_RUB_KG * batch_kg
        net_profit_rub      = revenue_rub - total_cost_rub
        margin_pct          = (net_profit_rub / revenue_rub) * 100 if revenue_rub > 0 else 0

        # Decision
        go_nogo = "PROCEED" if margin_pct >= _MIN_MARGIN_PCT else "NO-GO"
        risk    = "low" if margin_pct >= 45 else ("medium" if margin_pct >= 35 else "high")

        if go_nogo == "NO-GO":
            action   = f"Do not proceed — margin {margin_pct:.1f}% < minimum {_MIN_MARGIN_PCT}%"
            rollback = "no procurement initiated"
        else:
            action   = f"Initiate 600kg procurement — net profit ₽{net_profit_rub:,.0f}"
            rollback = "cancel PO within 48h before shipment confirmation"

        is_fallback = "FALLBACK" in source
        evidence = (
            f"Rate source: {source} | "
            f"COP/RUB={rate:.5f} (date={rate_date}) | "
            f"Purchase={price_cop_kg:,}COP/kg={purchase_rub_total:,.0f}₽ | "
            f"Logistics={logistics_total:,.0f}₽ | Customs={customs_duty:,.0f}₽ | "
            f"Revenue={revenue_rub:,.0f}₽ | Net={net_profit_rub:,.0f}₽"
            + (" | WARNING: using fallback rate — verify manually" if is_fallback else "")
        )

        return json.dumps({
            "decision":  f"{go_nogo}: {batch_kg:.0f}kg Colombia beans | margin={margin_pct:.1f}% | net=₽{net_profit_rub:,.0f}",
            "action":    action,
            "risk":      risk,
            "rollback":  rollback,
            "evidence":  evidence
        }, ensure_ascii=False, indent=2)
