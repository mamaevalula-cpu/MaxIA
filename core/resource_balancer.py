"""Resource balancer: monitors CPU/RAM and throttles agents under pressure."""
import threading, time, logging, os
log = logging.getLogger(__name__)

class ResourceBalancer:
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "ResourceBalancer":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._thread: threading.Thread = None
        self._running = False
        self._agents = {}
        self._cpu_high = 85.0
        self._ram_high = 85.0
        self._check_interval = 30.0

    def register_agent(self, name: str, pid: int = None):
        self._agents[name] = {"pid": pid, "throttled": False}

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="resource-balancer")
        self._thread.start()
        log.info("ResourceBalancer started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                self._check()
            except Exception as e:
                log.debug("ResourceBalancer error: %s", e)
            time.sleep(self._check_interval)

    def _check(self):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory().percent
            disk = psutil.disk_usage("/").percent

            if ram > self._ram_high or cpu > self._cpu_high:
                log.warning("Resource pressure: CPU=%.1f%% RAM=%.1f%%", cpu, ram)
                self._throttle_idle_agents()

            self._write_metrics(cpu, ram, disk)
        except ImportError:
            pass

    def _throttle_idle_agents(self):
        for name, info in self._agents.items():
            pid = info.get("pid")
            if pid and not info.get("throttled"):
                try:
                    os.nice(10)
                    info["throttled"] = True
                    log.info("Throttled agent %s (pid=%s)", name, pid)
                except:
                    pass

    def _write_metrics(self, cpu, ram, disk):
        try:
            path = "/root/my_personal_ai/data/metrics.json"
            os.makedirs(os.path.dirname(path), exist_ok=True)
            import json
            with open(path, "w") as f:
                json.dump({"cpu": cpu, "ram": ram, "disk": disk, "ts": time.time()}, f)
        except:
            pass

    def get_metrics(self) -> dict:
        try:
            import psutil
            return {
                "cpu": psutil.cpu_percent(interval=0.1),
                "ram": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage("/").percent,
            }
        except ImportError:
            return {"cpu": 0, "ram": 0, "disk": 0}
