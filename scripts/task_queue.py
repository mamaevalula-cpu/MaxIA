#!/usr/bin/env python3
import json, time, subprocess, os, sys

QUEUE_FILE = "/root/my_personal_ai/data/task_queue.jsonl"
DONE_FILE  = "/root/my_personal_ai/data/task_queue_done.jsonl"
LOG_FILE   = "/root/my_personal_ai/logs/task_queue.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = "[{}] {}".format(ts, msg)
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "a") as fh:
        fh.write(line + chr(10))

def add_task(task_type, params, priority=5):
    task = {"id": "t_{}".format(int(time.time())), "type": task_type,
            "params": params, "priority": priority, "created": time.time(), "status": "pending"}
    os.makedirs(os.path.dirname(QUEUE_FILE), exist_ok=True)
    with open(QUEUE_FILE, "a") as fh:
        fh.write(json.dumps(task) + chr(10))
    log("Task added: {} type={}".format(task["id"], task_type))
    return task["id"]

def execute_task(task):
    t = task["type"]
    p = task.get("params", {})
    if t == "shell":
        cmd = p.get("cmd", "echo ok")
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return (r.stdout or r.stderr or "")[:200]
    elif t == "restart_service":
        svc = p.get("service", "personal-ai")
        subprocess.run(["systemctl", "restart", svc], timeout=15)
        return "restarted {}".format(svc)
    elif t == "send_telegram":
        import urllib.request as ur
        token = ""
        if os.path.exists("/root/my_personal_ai/.env"):
            for line in open("/root/my_personal_ai/.env"):
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip(chr(34)).strip(chr(39))
        if not token: return "ERROR: no token"
        data = json.dumps({"chat_id": "1985320458", "text": p.get("text", ""), "parse_mode": "HTML"}).encode()
        req = ur.Request("https://api.telegram.org/bot{}/sendMessage".format(token),
                         data=data, headers={"Content-Type": "application/json"}, method="POST")
        with ur.urlopen(req, timeout=8): return "sent"
    elif t == "check_service":
        svc = p.get("service", "personal-ai")
        r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
        return r.stdout.strip()
    elif t == "ai_task":
        import urllib.request as ur
        data = json.dumps({"message": p.get("message", "")}).encode()
        req = ur.Request("http://localhost:8090/api/chat", data=data,
                         headers={"Content-Type": "application/json"}, method="POST")
        with ur.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
            return d.get("response", d.get("reply", ""))[:200]
    return "Unknown type: {}".format(t)

def process_queue():
    if not os.path.exists(QUEUE_FILE):
        log("Queue empty"); return
    tasks = [json.loads(l) for l in open(QUEUE_FILE) if l.strip()]
    pending = [t for t in tasks if t.get("status") == "pending"]
    pending.sort(key=lambda t: t.get("priority", 5))
    if pending: log("Processing {} pending tasks".format(len(pending)))
    completed = []
    for task in pending[:5]:
        log("Task {}: type={}".format(task["id"], task["type"]))
        try:
            result = execute_task(task)
            task["status"] = "done"; task["result"] = str(result)[:200]; task["completed_at"] = time.time()
            completed.append(task)
            log("  Done: {}".format(str(result)[:100]))
        except Exception as e:
            task["status"] = "failed"; task["error"] = str(e)[:100]
            log("  Failed: {}".format(e))
    remaining = [t for t in tasks if t.get("status") == "pending" and t not in completed]
    with open(QUEUE_FILE, "w") as fh:
        for t in remaining: fh.write(json.dumps(t) + chr(10))
    if completed:
        with open(DONE_FILE, "a") as fh:
            for t in completed: fh.write(json.dumps(t) + chr(10))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "add":
        tid = add_task("send_telegram", {"text": "Task Queue works!"}, priority=5)
        print("Added task: {}".format(tid))
    process_queue()
