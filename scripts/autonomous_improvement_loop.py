#!/usr/bin/env python3
"""
scripts/autonomous_improvement_loop.py
Runs every 15 minutes via cron. Drives continuous MaxAI growth:
1. Health check all services — auto-restart any failed
2. Monitor error count — trigger smart_trainer on spikes
3. Create next needed agent via AgentFactory
4. Report to Telegram only when changes happen
Designed to run 24/7 without human intervention.
"""
import json, logging, os, sys, subprocess, time
from pathlib import Path

sys.path.insert(0, '/root/my_personal_ai')
os.chdir('/root/my_personal_ai')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
log = logging.getLogger("auto_loop")

BASE = Path("/root/my_personal_ai")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "1985320458")
STATE_FILE = BASE / "data" / "auto_loop_state.json"
VENV_PY = "/root/venv/bin/python3"

SERVICES = ["personal-ai", "hyperion-engine", "hyperion-control-plane-v2", "hyperion-data-plane-v2"]


def tg(text):
    try:
        import urllib.request as ur
        data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode()
        req = ur.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}
        )
        ur.urlopen(req, timeout=8)
    except Exception:
        pass


def run_cmd(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode == 0
    except Exception as e:
        return str(e), False


def check_and_fix_services():
    fixed = []
    for svc in SERVICES:
        out, ok = run_cmd(f"systemctl is-active {svc}")
        if out != "active":
            log.warning("Service %s is %s — restarting", svc, out)
            run_cmd(f"systemctl restart {svc}", timeout=20)
            time.sleep(3)
            out2, _ = run_cmd(f"systemctl is-active {svc}")
            status = "restarted OK" if out2 == "active" else f"still {out2}"
            fixed.append(f"{'✅' if out2 == 'active' else '❌'} {svc}: {status}")
    return fixed


def get_recent_errors():
    try:
        err_log = BASE / "logs" / "errors.log"
        if err_log.exists():
            lines = err_log.read_text(errors="replace").split("\n")
            return sum(1 for l in lines[-300:] if "ERROR" in l or "CRITICAL" in l)
    except Exception:
        pass
    return 0


def get_hyperion_stats():
    try:
        import urllib.request as ur
        resp = ur.urlopen("http://localhost:8006/dashboard", timeout=5)
        return json.loads(resp.read())
    except Exception:
        return {}


def try_create_next_agent():
    try:
        from agents.agent_factory_agent import AgentFactoryAgent
        factory = AgentFactoryAgent()
        result = factory.create_next_agent()
        if "Created" in result:
            return result
    except Exception as e:
        log.debug("AgentFactory skip: %s", e)
    return None


def main():
    state = {}
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
        except Exception:
            pass

    state["runs"] = state.get("runs", 0) + 1
    changes = []

    log.info("=== Auto-Loop Run #%d ===", state["runs"])

    # 1. Service health
    fixes = check_and_fix_services()
    if fixes:
        changes.extend(fixes)
        state["total_fixes"] = state.get("total_fixes", 0) + len(fixes)
        log.info("Service fixes: %s", fixes)

    # 2. Error monitoring
    errors = get_recent_errors()
    prev_errors = state.get("last_error_count", 0)
    if errors > prev_errors + 15:
        changes.append(f"⚠️ Error spike: {errors} (was {prev_errors})")
        log.warning("Error spike %d->%d, triggering smart_trainer", prev_errors, errors)
        run_cmd(f"{VENV_PY} /root/my_personal_ai/agents/smart_trainer_agent.py", timeout=30)
    state["last_error_count"] = errors

    # 3. Auto-create next agent (every 5 runs)
    if state["runs"] % 5 == 0:
        result = try_create_next_agent()
        if result:
            changes.append(f"🏭 {result[:80]}")
            state["agents_created"] = state.get("agents_created", 0) + 1
            log.info("Agent created: %s", result[:80])

    # 4. Hyperion health
    h = get_hyperion_stats()
    caps = h.get("capabilities", 0)
    if caps > 0:
        log.info("Hyperion: %d capabilities, %d tasks, $%.0f revenue",
                 caps, h.get("total_tasks", 0), h.get("total_expected_revenue", 0))

    # 5. Report if meaningful changes or every 20 runs
    if changes or state["runs"] % 20 == 0:
        msg = f"🔄 AutoLoop #{state['runs']}\n"
        if changes:
            for c in changes[:5]:
                msg += f"  {c}\n"
        else:
            msg += f"  ✅ All systems ok | {caps} capabilities | {errors} errors\n"
        msg += f"  Total fixes: {state.get('total_fixes', 0)} | Agents created: {state.get('agents_created', 0)}"
        tg(msg)

    state["last_run"] = time.time()
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False))
    log.info("Loop #%d done. Changes: %d, Errors: %d, Caps: %d",
             state["runs"], len(changes), errors, caps)


if __name__ == "__main__":
    main()
