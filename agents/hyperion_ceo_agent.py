#!/usr/bin/env python3
"""
agents/hyperion_ceo_agent.py — HyperionCEO: Strategic AI Orchestrator
24/7 autonomous company management. Monitors KPIs, makes decisions,
drives growth, fixes issues, and guides MaxAI to world-corporation level.
"""
import json, logging, os, time, subprocess
from pathlib import Path
from datetime import datetime

log = logging.getLogger("agents.hyperion_ceo")
BASE = Path("/root/my_personal_ai")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "1985320458")
CEO_LOG   = BASE / "data" / "ceo_decisions.json"

try:
    from agents.base_agent import BaseAgent, AgentInfo
    HAS_BASE = True
except ImportError:
    BaseAgent = object
    AgentInfo = None
    HAS_BASE = False


class HyperionCEOAgent(BaseAgent if HAS_BASE else object):
    name = "hyperion_ceo"
    VERSION = "2.0"

    def __init__(self, **kwargs):
        if HAS_BASE:
            super().__init__("hyperion_ceo")

    def can_handle(self, text: str) -> bool:
        kw = ["ceo", "стратегия", "рост", "компания", "расширение", "метрики", "kpi", "growth"]
        return any(k in text.lower() for k in kw)

    def info(self):
        if AgentInfo:
            return AgentInfo(
                name="hyperion_ceo",
                description="Strategic AI CEO — runs MaxAI company 24/7 autonomously",
                capabilities=["strategic_decisions", "kpi_monitoring", "crisis_management",
                              "growth_planning", "auto_fix_services", "hiring"]
            )
        return None

    def _tg(self, text):
        try:
            import urllib.request as ur
            data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
            req = ur.Request(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                data=data, headers={"Content-Type": "application/json"}
            )
            ur.urlopen(req, timeout=8)
        except Exception:
            pass

    def _run(self, cmd, timeout=10):
        try:
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return r.stdout.strip()
        except Exception:
            return ""

    def get_company_metrics(self):
        metrics = {
            "timestamp": datetime.now().isoformat(),
            "services": {},
            "hyperion": {},
            "bybit": {},
            "agents_count": 0,
            "errors": 0,
        }
        # Services
        for svc in ["personal-ai", "hyperion-engine", "hyperion-control-plane-v2", "hyperion-data-plane-v2"]:
            out = self._run(f"systemctl is-active {svc}")
            metrics["services"][svc] = out or "unknown"

        # Hyperion v12
        try:
            import urllib.request as ur
            resp = ur.urlopen("http://localhost:8006/dashboard", timeout=5)
            metrics["hyperion"] = json.loads(resp.read())
        except Exception:
            pass

        # Bybit
        try:
            import urllib.request as ur
            resp = ur.urlopen("http://localhost:8001/status", timeout=5)
            d = json.loads(resp.read())
            metrics["bybit"] = {
                "balance": d.get("balance_usdt", 0),
                "daily_pnl": d.get("daily_pnl", 0),
                "active": d.get("trading_active", False),
            }
        except Exception:
            pass

        # Errors
        try:
            err_log = BASE / "logs" / "errors.log"
            if err_log.exists():
                lines = err_log.read_text(errors="replace").split("\n")
                metrics["errors"] = sum(1 for l in lines[-500:] if "ERROR" in l or "CRITICAL" in l)
        except Exception:
            pass

        # Agents
        try:
            metrics["agents_count"] = len(list((BASE / "agents").glob("*.py")))
        except Exception:
            pass

        return metrics

    def make_decisions(self, metrics):
        decisions = []
        actions = []

        for svc, status in metrics.get("services", {}).items():
            if status != "active":
                decisions.append(f"RESTART {svc} (was: {status})")
                self._run(f"systemctl restart {svc}")
                time.sleep(2)
                new_status = self._run(f"systemctl is-active {svc}")
                actions.append(f"{'OK' if new_status == 'active' else 'FAIL'} restart {svc}")

        if metrics.get("errors", 0) > 30:
            decisions.append(f"HIGH ERRORS: {metrics['errors']} — trigger smart trainer")

        h = metrics.get("hyperion", {})
        if h.get("capabilities", 0) < 15:
            decisions.append("ADD CAPABILITIES: below 15 target")

        b = metrics.get("bybit", {})
        if b.get("daily_pnl", 0) < -10:
            decisions.append(f"TRADING LOSS: {b['daily_pnl']:.2f} today")

        return decisions, actions

    def growth_strategy(self):
        strategies = [
            "Expand KZ market — RU agents serve Kazakh businesses (100M+ population)",
            "Launch Fiverr gig: 'AI Telegram Bot in 24h' targeting EN market",
            "Add 5 new capabilities to Hyperion catalog",
            "Run B2B outreach: 20 restaurants/cafes — Telegram bot offer",
            "Start Telegram channel with daily AI tips (revenue: ads + subscribers)",
            "Launch crypto payment gateway (USDT) for instant payments",
            "Partner with 3 dev agencies for white-label AI services",
            "Build showcase portfolio — 10 completed projects with results",
        ]
        return strategies[datetime.now().weekday() % len(strategies)]

    def daily_report(self):
        metrics = self.get_company_metrics()
        decisions, actions = self.make_decisions(metrics)
        growth = self.growth_strategy()

        svcs_ok = sum(1 for s in metrics.get("services", {}).values() if s == "active")
        svcs_total = len(metrics.get("services", {}))
        h = metrics.get("hyperion", {})
        b = metrics.get("bybit", {})

        msg = "<b>👔 HyperionCEO Daily Report</b>\n"
        msg += f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"

        msg += "<b>🏢 Company Status</b>\n"
        msg += f"  Services: {svcs_ok}/{svcs_total} active\n"
        msg += f"  Agents deployed: {metrics.get('agents_count', 0)}\n"
        msg += f"  Error rate: {metrics.get('errors', 0)} recent\n\n"

        msg += "<b>⚡ Корпорация MaxAI v12</b>\n"
        msg += f"  Capabilities: {h.get('capabilities', '?')}\n"
        msg += f"  Tasks processed: {h.get('total_tasks', '?')}\n"
        msg += f"  Revenue forecast: ${h.get('total_expected_revenue', 0):.0f}\n\n"

        msg += "<b>💹 Trading Status</b>\n"
        msg += f"  Balance: ${b.get('balance', 0):.2f}\n"
        msg += f"  Daily PnL: ${b.get('daily_pnl', 0):.4f}\n\n"

        if decisions:
            msg += f"<b>⚠️ Decisions ({len(decisions)})</b>\n"
            for d in decisions[:3]:
                msg += f"  • {d[:80]}\n"
            msg += "\n"

        if actions:
            msg += "<b>✅ Actions Taken</b>\n"
            for a in actions[:3]:
                msg += f"  {a}\n"
            msg += "\n"

        msg += f"<b>🚀 Growth Focus Today</b>\n{growth}"

        self._tg(msg)

        # Persist decisions
        history = []
        if CEO_LOG.exists():
            try:
                history = json.loads(CEO_LOG.read_text())
            except Exception:
                pass
        history.append({
            "ts": time.time(),
            "decisions": decisions,
            "actions": actions,
            "services_ok": svcs_ok,
            "balance": b.get("balance", 0),
        })
        CEO_LOG.write_text(json.dumps(history[-30:], ensure_ascii=False))

        return f"CEO Report sent. Decisions: {len(decisions)}, Actions: {len(actions)}"

    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        return self.daily_report()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(HyperionCEOAgent().daily_report())
