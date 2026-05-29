from __future__ import annotations
import logging, subprocess
log = logging.getLogger("agents.health_monitor")

class HealthMonitorAgent:
    name = "health_monitor"
    def __init__(self): log.info("HealthMonitorAgent OK")
    def report(self) -> str:
        lines = ["System Health:"]
        try:
            import psutil
            lines += [f"  CPU: {psutil.cpu_percent(1)}%", f"  RAM: {psutil.virtual_memory().percent}%",
                      f"  Disk: {psutil.disk_usage('/').percent}%"]
        except Exception:
            o,_ = subprocess.Popen(["free","-h"], stdout=subprocess.PIPE).communicate()
            lines.append(o.decode()[:200])
        for svc in ["personal-ai.service", "apex-watchdog.service"]:
            r = subprocess.run(["systemctl","is-active",svc], capture_output=True, text=True)
            lines.append(f"  {svc}: {r.stdout.strip()}")
        return chr(10).join(lines)
    def process(self, text: str) -> str:
        return self.report()
