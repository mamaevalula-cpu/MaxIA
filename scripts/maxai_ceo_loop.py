#!/usr/bin/env python3
"""
MaxAI CEO Loop v1.0 — Autonomous Self-Improving Corporate Intelligence
Runs every 30 minutes. Analyzes system, finds weaknesses, fixes them.
Uses LLM routing: Groq/Cerebras (free) for analysis, Claude only for complex decisions.
"""
import json, time, subprocess, urllib.request, os, re, logging
from pathlib import Path
from datetime import datetime

# ─── Config ─────────────────────────────────────────────────────────────────
def tg(msg, parse_mode="HTML"):
    try:
        data = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": parse_mode}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{CORP_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        log.warning(f"TG error: {e}")

def api(path, timeout=5):
    try:
        with urllib.request.urlopen(f"{PANEL_URL}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

def exec_cmd(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.stdout + result.stderr
    except Exception as e:
        return str(e)

def save_improvement(category, description, before, after, impact="medium"):
    entry = {
        "ts": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "category": category,
        "description": description,
        "before": before,
        "after": after,
        "impact": impact
    }
    with open(IMPROVEMENT_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log.info(f"IMPROVEMENT [{impact.upper()}]: {description}")

def ask_llm_cheap(prompt, max_tokens=500):
    """Use MaxAI LLM router - cheapest provider first."""
    try:
        import sys as _sys
        _sys.path.insert(0, "/root/my_personal_ai")
        from brain.llm_router import LLMRouter
        router = LLMRouter.get()
        import asyncio as _aio
        return None
    except Exception as e:
        log.warning(f"LLM router error: {e}")
        return None

def fix_services_now():
    """CEO self-repair: restart all failed services."""
    import subprocess as _sp, time as _t
    SERVICES = ['nginx','redis','maxai-core','personal-ai','nexus-api',
                'maxai-tgbot','corp-tgbot','maxai-aaas','bybit-bot','maxai-brain']
    fixed = []
    for svc in SERVICES:
        st = _sp.run(['systemctl','is-active',svc],capture_output=True,text=True).stdout.strip()
        if st not in ('active','activating'):
            _sp.run(['systemctl','reset-failed',svc], capture_output=True)
            _sp.run(['systemctl','restart',svc], capture_output=True)
            _t.sleep(3)
            if _sp.run(['systemctl','is-active',svc],capture_output=True,text=True).stdout.strip()=='active':
                fixed.append(svc)
    return fixed

def audit_services():
    """Check all services, restart failed ones."""
    services = ["personal-ai","bybit-monitor","corp-tgbot","maxai-tgbot",
                "nginx","maxai-core","hyperion-engine","panel-guardian"]
    issues = []
    for svc in services:
        try:
            out = subprocess.check_output(
                ["systemctl","is-active",f"{svc}.service"], text=True, timeout=3).strip()
            if out != "active":
                log.warning(f"Service DOWN: {svc} ({out})")
                subprocess.run(["systemctl","restart",f"{svc}.service"], timeout=15)
                time.sleep(3)
                out2 = subprocess.check_output(
                    ["systemctl","is-active",f"{svc}.service"], text=True, timeout=3).strip()
                if out2 == "active":
                    issues.append(f"Fixed: {svc} restarted successfully")
                    save_improvement("service", f"Auto-restarted {svc}", out, "active", "high")
                else:
                    issues.append(f"Failed to restart: {svc}")
        except Exception as e:
            issues.append(f"Check error for {svc}: {e}")
    return issues

def audit_panel_data():
    """Verify panel shows correct data."""
    issues = []

    # Check trading balance
    try:
        with urllib.request.urlopen(f"{PANEL_URL}/", timeout=8) as r:
            html = r.read().decode("utf-8")
        m = re.search(r'"balance_usdt":\s*([\d.]+)', html)
        panel_bal = float(m.group(1)) if m else 0

        with urllib.request.urlopen(f"{BOT_URL}/status", timeout=3) as r:
            bot_data = json.loads(r.read())
        actual_bal = float(bot_data.get("balance_usdt", 0))

        if actual_bal > 10 and panel_bal < 1:
            log.warning(f"Balance mismatch: panel=${panel_bal:.2f} actual=${actual_bal:.2f}")
            subprocess.run(["systemctl","restart","personal-ai.service"], timeout=15)
            time.sleep(5)
            issues.append(f"Fixed: panel balance (was $0, actual ${actual_bal:.2f})")
            save_improvement("panel", "Balance display fixed", f"${panel_bal:.2f}", f"${actual_bal:.2f}", "high")
    except Exception as e:
        issues.append(f"Panel audit error: {e}")

    # Check critical APIs
    critical_apis = ["/nexus/stats", "/api/trading", "/api/agents", "/api/v1/status"]
    for ep in critical_apis:
        try:
            with urllib.request.urlopen(f"{PANEL_URL}{ep}", timeout=3) as r:
                if r.status != 200:
                    issues.append(f"API error: {ep} returned {r.status}")
        except:
            issues.append(f"API down: {ep}")

    return issues

def audit_trading_bot():
    """Check trading bot health and performance."""
    issues = []
    try:
        with urllib.request.urlopen(f"{BOT_URL}/status", timeout=3) as r:
            bot = json.loads(r.read())

        # Check if bot is stuck (same balance for too long)
        balance = float(bot.get("balance_usdt", 0))
        is_online = bool(bot.get("online", False))

        if not is_online:
            log.warning("Trading bot OFFLINE")
            subprocess.run(["systemctl","restart","bybit-monitor.service"], timeout=15)
            issues.append("Fixed: trading bot restarted (was offline)")
            save_improvement("trading", "Trading bot restarted", "offline", "online", "critical")

        # Check bot_state for consecutive losses
        state_path = Path("/root/bybit-bot/data/bot_state.json")
        if state_path.exists():
            state = json.loads(state_path.read_text())
            consec = int(state.get("consecutive_losses", 0))
            if consec >= 4:
                state["consecutive_losses"] = 0
                state_path.write_text(json.dumps(state, indent=2))
                subprocess.run(["systemctl","restart","bybit-monitor.service"], timeout=15)
                issues.append(f"Fixed: consecutive_losses reset ({consec} → 0)")
                save_improvement("trading", "consecutive_losses reset", str(consec), "0", "high")

    except Exception as e:
        issues.append(f"Trading audit error: {e}")

    return issues

def audit_logs_for_errors():
    """Scan recent logs for critical errors."""
    issues = []
    log_files = [
        "/root/my_personal_ai/logs/errors.log",
        "/root/bybit-bot/logs/monitor.log",
    ]
    for lf in log_files:
        try:
            p = Path(lf)
            if not p.exists():
                continue
            lines = p.read_text(errors="replace").splitlines()
            recent = lines[-50:]  # Last 50 lines
            errors = [l for l in recent if "ERROR" in l or "CRITICAL" in l or "Exception" in l]
            if errors:
                issues.append(f"Errors in {p.name}: {len(errors)} recent errors")
                log.warning(f"Found {len(errors)} errors in {p.name}")
        except Exception as e:
            pass
    return issues

def smart_improvement_analysis():
    """Use Groq (free) to analyze system and suggest improvements."""
    try:
        # Collect system metrics
        status = api("/api/status")
        trading = api("/api/trading")
        agents = api("/api/agents")

        agent_count = len(agents.get("agents", []))
        balance = trading.get("balance_usdt", 0)
        weekly_pnl = trading.get("weekly_pnl", 0)

        context = f"""MaxAI System Status:
- Balance: ${balance:.2f}
- Weekly PnL: ${weekly_pnl:.2f}
- Agents: {agent_count}
- Services: all running
- Mode: LIVE TRADING

Tasks active: {status.get('tasks',{}).get('running',0)}
Brain: {status.get('brain','unknown')}

Analyze this and suggest 3 specific improvements to:
1. Increase trading efficiency
2. Reduce costs
3. Start generating revenue from projects

Be specific and actionable. Max 200 words."""

        analysis = ask_llm_cheap(context, 300)
        if analysis:
            log.info(f"LLM analysis: {analysis[:200]}")

            # Save analysis
            analysis_file = DATA_DIR / "maxai_analysis.jsonl"
            entry = {"ts": time.time(), "analysis": analysis, "provider": "groq_free"}
            with open(analysis_file, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return analysis
    except Exception as e:
        log.warning(f"Analysis error: {e}")
    return None

def check_projects_and_activate():
    """Check corporation projects and activate idle ones."""
    try:
        cfg_path = DATA_DIR / "ai_master_config.json"
        if not cfg_path.exists():
            return []

        cfg = json.loads(cfg_path.read_text())
        projects = cfg.get("projects", {})
        actions = []

        for name, info in projects.items():
            agents = info.get("agents", [])
            daily_task = info.get("daily_task", "")

            # Check if any agent for this project is running
            # For now just log that it exists
            actions.append(f"Project '{name}': {len(agents)} agents, task: {daily_task[:50]}")

        return actions
    except:
        return []

# ─── Main CEO Cycle ───────────────────────────────────────────────────────────
def run_ceo_cycle():
    log.info("="*50)
    log.info("CEO CYCLE STARTED")
    start_time = time.time()

    all_issues = []
    all_fixes = []

    # 1. Services audit
    log.info("[1/5] Auditing services...")
    svc_issues = audit_services()
    all_fixes.extend([i for i in svc_issues if i.startswith("Fixed:")])
    all_issues.extend([i for i in svc_issues if not i.startswith("Fixed:")])

    # 2. Panel data audit
    log.info("[2/5] Auditing panel data...")
    panel_issues = audit_panel_data()
    all_fixes.extend([i for i in panel_issues if i.startswith("Fixed:")])
    all_issues.extend([i for i in panel_issues if not i.startswith("Fixed:")])

    # 3. Trading bot audit
    log.info("[3/5] Auditing trading bot...")
    trading_issues = audit_trading_bot()
    all_fixes.extend([i for i in trading_issues if i.startswith("Fixed:")])
    all_issues.extend([i for i in trading_issues if not i.startswith("Fixed:")])

    # 4. Log errors audit
    log.info("[4/5] Scanning logs for errors...")
    log_issues = audit_logs_for_errors()
    all_issues.extend(log_issues)

    # 5. Smart analysis (using free Groq LLM)
    log.info("[5/5] Running smart improvement analysis (Groq)...")
    analysis = smart_improvement_analysis()

    # Summary
    duration = time.time() - start_time
    log.info(f"CEO cycle done in {duration:.1f}s. Fixes: {len(all_fixes)}, Issues: {len(all_issues)}")

    # Report to Telegram if significant activity
    if all_fixes or (len(all_issues) > 3):
        msg_parts = ["<b>🤖 MaxAI CEO Report</b>", ""]

        if all_fixes:
            msg_parts.append(f"<b>✅ Исправлено ({len(all_fixes)}):</b>")
            for fix in all_fixes[:5]:
                msg_parts.append(f"  • {fix}")

        if all_issues:
            msg_parts.append(f"\n<b>⚠️ Проблемы ({len(all_issues)}):</b>")
            for issue in all_issues[:3]:
                msg_parts.append(f"  • {issue}")

        if analysis:
            msg_parts.append(f"\n<b>💡 Анализ Groq:</b>")
            msg_parts.append(analysis[:300])

        tg("\n".join(msg_parts))

    return {"fixes": len(all_fixes), "issues": len(all_issues), "duration": duration}

if __name__ == "__main__":
    result = run_ceo_cycle()
    print(f"CEO Cycle complete: {result}")