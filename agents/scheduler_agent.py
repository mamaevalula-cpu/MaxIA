from __future__ import annotations
import logging, time, threading, json, os
log = logging.getLogger("agents.scheduler")
SCHED_FILE = "/root/my_personal_ai/data/schedule.json"

class SchedulerAgent:
    name = "scheduler"
    def __init__(self):
        self._tasks = {}
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True, name="scheduler").start()
        log.info("SchedulerAgent OK")
    def schedule(self, name: str, hour: int, minute: int, action: str) -> str:
        self._tasks[name] = {"hour": hour, "minute": minute, "action": action}
        return f"Scheduled {name} at {hour:02d}:{minute:02d}"
    def list_tasks(self) -> str:
        if not self._tasks: return "No tasks"
        return chr(10).join(f"  {n}: {t['hour']:02d}:{t['minute']:02d} -> {t['action']}" for n,t in self._tasks.items())
    def _run(self):
        while not self._stop.is_set():
            try:
                now = time.localtime()
                for n,t in list(self._tasks.items()):
                    if now.tm_hour == t["hour"] and now.tm_min == t["minute"]:
                        log.info("Run scheduled: %s", n)
            except Exception as e:
                log.error("Scheduler: %s", e)
            self._stop.wait(60)
    def process(self, text: str) -> str:
        if "список" in text.lower() or "list" in text.lower():
            return self.list_tasks()
        return "Scheduler active." + chr(10) + self.list_tasks()
