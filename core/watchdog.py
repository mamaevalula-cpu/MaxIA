#!/usr/bin/env python3
"""apex-watchdog: monitors personal-ai.service and auto-restarts if frozen."""
import time, subprocess, os, logging
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/root/my_personal_ai/logs/watchdog_auto.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("watchdog")

CHECK_INTERVAL = 60
MAX_LOG_SILENCE = 3600  # 60 min without brain.log update = frozen (idle is normal)
RESTART_COOLDOWN = 180  # min seconds between restarts
_last_restart = 0.0

def service_active():
    try:
        r = subprocess.run(["systemctl", "is-active", "personal-ai.service"],
            capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except Exception:
        return False

def http_alive():
    """Check if the panel HTTP endpoint is responding."""
    try:
        import urllib.request as _ur
        with _ur.urlopen("http://127.0.0.1:8090/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False

def log_fresh():
    # If HTTP endpoint is alive, service is considered healthy regardless of log
    if http_alive():
        return True
    try:
        mtime = os.path.getmtime("/root/my_personal_ai/logs/brain.log")
        return (time.time() - mtime) < MAX_LOG_SILENCE
    except Exception:
        return True

def tg_alert(msg):
    try:
        import httpx
        from dotenv import load_dotenv
        load_dotenv("/root/my_personal_ai/.env")
        tok = os.getenv("TELEGRAM_BOT_TOKEN", "")
        cid = os.getenv("TELEGRAM_CHAT_ID", "")
        if tok and cid:
            httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id": cid, "text": msg}, timeout=6)
    except Exception:
        pass

def do_restart(reason):
    global _last_restart
    if time.time() - _last_restart < RESTART_COOLDOWN:
        log.warning("Restart skipped (cooldown)")
        return
    _last_restart = time.time()
    log.warning("RESTART: %s", reason)
    subprocess.run(["systemctl", "restart", "personal-ai.service"], timeout=30)
    time.sleep(10)
    status = "active" if service_active() else "FAILED"
    tg_alert(f"[WATCHDOG] Бот перезапущен ({reason}). Статус: {status}")
    log.info("Restart done, service=%s", status)





# ── SystemWatchdog class (singleton, used by main.py & routes.py) ─────────────
import threading as _threading
from typing import List, Callable, Any, Optional as _Optional

class SystemWatchdog:
    """Singleton watchdog class — wraps the standalone watchdog logic."""
    _instance: '_Optional[SystemWatchdog]' = None

    def __init__(self):
        self._agents: List[Any] = []
        self._callbacks: List[Callable] = []
        self._started = False
        self._thread: _Optional[_threading.Thread] = None

    @classmethod
    def get(cls) -> 'SystemWatchdog':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register_agents(self, agents) -> None:
        """Register agents for monitoring."""
        if hasattr(agents, '_agents'):
            self._agents = list(agents._agents.values())
        elif isinstance(agents, (list, dict)):
            self._agents = list(agents) if isinstance(agents, list) else list(agents.values())

    def add_alert_callback(self, callback: Callable) -> None:
        """Add a callback to be called on alerts."""
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start watchdog in a daemon thread (non-blocking)."""
        if self._started:
            return
        self._started = True
        self._thread = _threading.Thread(
            target=self._run_loop, daemon=True, name="SystemWatchdog"
        )
        self._thread.start()
        log.info("Watchdog started")
        tg_alert("[WATCHDOG] Старт — бот под наблюдением")

    def _run_loop(self) -> None:
        """Background monitoring loop."""
        import time
        _fails = 0
        while True:
            try:
                alive = service_active()
                fresh = log_fresh()
                if not alive:
                    _fails += 1
                    log.warning("Service not active (fail #%d)", _fails)
                    if _fails >= 2:
                        do_restart("service not active")
                        _fails = 0
                elif not fresh:
                    _fails += 1
                    log.warning("brain.log stale >10min (fail #%d)", _fails)
                    if _fails >= 2:
                        do_restart("bot frozen (no log updates)")
                        _fails = 0
                else:
                    if _fails > 0:
                        log.info("Recovered after %d fails", _fails)
                    _fails = 0
            except Exception as e:
                log.error("Watchdog error: %s", e)
            time.sleep(CHECK_INTERVAL)

    @property
    def is_running(self) -> bool:
        return self._started and self._thread is not None and self._thread.is_alive()

if __name__ == '__main__':
    fails = 0
    log.info("Watchdog started")
    tg_alert("[WATCHDOG] Старт — бот под наблюдением")
    
    while True:
        try:
            alive = service_active()
            fresh = log_fresh()
            if not alive:
                fails += 1
                log.warning("Service not active (fail #%d)", fails)
                if fails >= 2:
                    do_restart("service not active")
                    fails = 0
            elif not fresh:
                fails += 1
                log.warning("brain.log stale >10min (fail #%d)", fails)
                if fails >= 2:
                    do_restart("bot frozen (no log updates)")
                    fails = 0
            else:
                if fails > 0:
                    log.info("Recovered after %d fails", fails)
                fails = 0
        except Exception as e:
            log.error("Watchdog error: %s", e)
        time.sleep(CHECK_INTERVAL)
    