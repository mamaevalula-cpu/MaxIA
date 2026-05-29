"""MaxAI Core — central controller with HUD, self-test, emergency response."""
import threading, time, os, logging, json
from typing import Optional, Callable
log = logging.getLogger(__name__)

class MaxAICore:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "MaxAICore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._brain = None
        self._alert_cb: Optional[Callable] = None
        self._start_time = time.time()

    def init(self, brain):
        self._brain = brain
        log.info("MaxAICore initialized")

    def set_alert_callback(self, cb: Callable):
        self._alert_cb = cb

    def get_hud(self) -> str:
        """Return one-line HUD status string."""
        try:
            b = self._brain
            if not b:
                return "[APEX] ⚡ Starting..."
            agents = getattr(b, "_agents", {})
            active = sum(1 for a in agents.values() if getattr(a, "status", "") == "working")
            total = len(agents)
            uptime = int(time.time() - self._start_time)
            h, m = divmod(uptime // 60, 60)
            try:
                from brain.llm_router import LLMRouter
                costs = LLMRouter.get().get_cost_stats()
                cost = costs.get("daily_cost_usd", 0)
            except:
                cost = 0
            return f"[APEX] ⚡ UP {h:02d}:{m:02d} | 🤖 {active}/{total} агентов | 💰 ${cost:.4f} | 🕐 {time.strftime('%H:%M:%S')}"
        except Exception as e:
            return f"[APEX] ⚡ HUD error: {e}"

    def self_test(self) -> dict:
        """Run system self-test. Returns dict with results."""
        results = {}
        passed = 0
        failed = 0

        tests = [
            ("brain_import", self._test_brain),
            ("llm_router", self._test_llm_router),
            ("disk_space", self._test_disk),
            ("log_dir", self._test_logs),
            ("agents_load", self._test_agents),
        ]

        for name, fn in tests:
            try:
                ok, msg = fn()
                results[name] = {"ok": ok, "msg": msg}
                if ok: passed += 1
                else: failed += 1
            except Exception as e:
                results[name] = {"ok": False, "msg": str(e)}
                failed += 1

        return {
            "passed": failed == 0,
            "total": len(tests),
            "passed_count": passed,
            "failed_count": failed,
            "results": results,
            "timestamp": time.time(),
        }

    def _test_brain(self):
        from brain.orchestrator import Orchestrator
        o = Orchestrator.get()
        return (o is not None, "Orchestrator OK" if o else "No orchestrator")

    def _test_llm_router(self):
        from brain.llm_router import LLMRouter
        r = LLMRouter.get()
        report = r.status_report()
        avail = [k for k, v in report.items() if v.get("available")]
        return (len(avail) > 0, f"{len(avail)} providers available: {avail}")

    def _test_disk(self):
        import shutil
        free = shutil.disk_usage("/").free / (1024**3)
        return (free > 1.0, f"{free:.1f}GB free")

    def _test_logs(self):
        d = "/root/my_personal_ai/logs"
        return (os.path.isdir(d), f"Log dir {'exists' if os.path.isdir(d) else 'MISSING'}")

    def _test_agents(self):
        b = self._brain
        if not b:
            return (False, "Brain not initialized")
        agents = getattr(b, "_agents", {})
        return (len(agents) > 0, f"{len(agents)} agents registered")

    def get_config_masked(self) -> dict:
        """Return config with secrets masked."""
        cfg = {}
        sensitive = ["token", "key", "password", "secret", "pass"]
        try:
            from dotenv import dotenv_values
            env = dotenv_values("/root/my_personal_ai/.env")
            for k, v in env.items():
                if any(s in k.lower() for s in sensitive):
                    cfg[k] = "***" + str(v)[-4:] if v and len(v) > 4 else "***"
                else:
                    cfg[k] = v
        except Exception as e:
            cfg["_error"] = str(e)
        return cfg

    def send_emergency_response(self, reason: str):
        """Send emergency alert via all channels."""
        msg = f"🚨 [APEX EMERGENCY] {reason}
⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}"
        log.critical("EMERGENCY: %s", reason)
        if self._alert_cb:
            try: self._alert_cb(msg)
            except: pass
        try:
            with open("/root/my_personal_ai/logs/emergency.log", "a") as f:
                f.write(msg + "\n")
        except: pass
