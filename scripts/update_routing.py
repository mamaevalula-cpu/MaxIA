#!/usr/bin/env python3
"""
update_routing.py — Reads benchmark_results.json and shows optimal routing.
Run after benchmark: python scripts/update_routing.py
Or ask AI: "обнови роутинг на основе бенчмарка"
"""
import sys, os, json, time
sys.path.insert(0, "/root/my_personal_ai")
os.chdir("/root/my_personal_ai")

from dotenv import load_dotenv
load_dotenv()

BENCH_FILE  = "data/benchmark_results.json"
REPORT_FILE = "data/routing_report.json"

def load_bench():
    if not os.path.exists(BENCH_FILE):
        print("Benchmark file not found: " + BENCH_FILE)
        print("Run: python scripts/benchmark_providers.py")
        return None
    with open(BENCH_FILE) as f:
        return json.load(f)

def analyze(data):
    results = data.get("results", {})
    task_types = set(k.split("/")[1] for k in results)
    recommendations = {}
    for task in task_types:
        candidates = []
        for key, val in results.items():
            if key.endswith("/" + task) and val.get("ok"):
                provider = key.split("/")[0]
                candidates.append({
                    "provider": provider,
                    "latency_ms": val["latency_ms"],
                    "model": val.get("model", "?")
                })
        if candidates:
            candidates.sort(key=lambda x: x["latency_ms"])
            recommendations[task] = candidates
    return recommendations

def print_recommendations(recs):
    medals = ["1", "2", "3"]
    print("\nRouting Recommendations (sorted by latency):")
    print("=" * 60)
    for task in sorted(recs.keys()):
        providers = recs[task]
        print("  " + task + ":")
        for i, p in enumerate(providers[:3]):
            m = medals[i] if i < len(medals) else "-"
            print("    [" + m + "] " + p["provider"].ljust(14) + str(round(p["latency_ms"])).rjust(5) + "ms  [" + p["model"][:25] + "]")

def save_report(recs, bench_ts):
    report = {
        "generated_at": time.time(),
        "benchmark_ts": bench_ts,
        "recommendations": recs,
        "routing_summary": {
            task: [p["provider"] for p in providers]
            for task, providers in recs.items()
        }
    }
    os.makedirs("data", exist_ok=True)
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print("\nSaved: " + REPORT_FILE)

def check_router_status():
    try:
        from brain.llm_router import LLMRouter
        router = LLMRouter.get()
        report = router.status_report()
        print("\nCurrent Router Status:")
        providers = report.get("providers", {})
        for p, info in providers.items():
            status = info.get("status", "?")
            calls  = info.get("calls_total", 0)
            rate   = info.get("success_rate", 1.0)
            print("  " + p.ljust(14) + " " + status.ljust(12) + " calls=" + str(calls) + "  rate=" + str(round(rate*100)) + "%")
    except Exception as e:
        print("Router status error: " + str(e))

def main():
    print("Provider Routing Optimizer")
    print("=" * 60)
    data = load_bench()
    if not data:
        return
    age = time.time() - data.get("ts", 0)
    print("Benchmark age: " + str(round(age/3600, 1)) + "h")
    if age > 3600:
        print("WARNING: Benchmark older than 1h, re-run: python scripts/benchmark_providers.py")
    recs = analyze(data)
    print_recommendations(recs)
    save_report(recs, data.get("ts", 0))
    check_router_status()
    print("\nDone. Router uses data/benchmark_results.json automatically.")

if __name__ == "__main__":
    main()
