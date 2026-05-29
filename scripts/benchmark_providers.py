#!/usr/bin/env python3
"""
Provider Benchmark — tests all available providers and updates routing data.
Run: python scripts/benchmark_providers.py
Or ask AI: "запусти benchmark всех провайдеров"
"""
import sys, os, time, json
sys.path.insert(0, "/root/my_personal_ai")
os.chdir("/root/my_personal_ai")

from dotenv import load_dotenv
load_dotenv()

from brain.llm_router import LLMRouter, LLMRequest, LLMProvider

TASKS = [
    ("chat",     "биткоин одним словом",         30),
    ("math",     "127 * 48 = ?",                 20),
    ("classify", "intent: расскажи о погоде",    10),
    ("code",     "python: print hello world",    50),
]

# Provider -> internal _call_* method name
PROVIDER_METHODS = {
    LLMProvider.CEREBRAS:    "_call_cerebras",
    LLMProvider.GROQ:        "_call_groq",
    LLMProvider.DEEPSEEK:    "_call_deepseek",
    LLMProvider.GEMINI:      "_call_gemini",
    LLMProvider.GROK:        "_call_grok",
    LLMProvider.TOGETHER:    "_call_together",
    LLMProvider.OPENROUTER:  "_call_openrouter",
}

results = {}
router = LLMRouter.get()
print("Provider Benchmark " + "=" * 50)

for task_type, prompt, max_tokens in TASKS:
    print(f"\nTask: {task_type} | {prompt[:40]}")
    for provider, method_name in PROVIDER_METHODS.items():
        pname = provider.value
        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type=task_type,
            max_tokens=max_tokens,
        )
        t0 = time.time()
        try:
            # Check availability first
            if not router._is_available(provider):
                print(f"  {pname:<14} SKIP (unavailable/no key)")
                continue

            # Call the provider-specific method directly
            fn = getattr(router, method_name, None)
            if fn is None:
                print(f"  {pname:<14} SKIP (method {method_name} not found)")
                continue

            text, model, tokens = fn(req)
            lat = (time.time() - t0) * 1000
            print(f"  {pname:<14} {lat:>5.0f}ms {tokens:>4}tok [{model[:20]}]  {str(text)[:35]}")
            key = f"{pname}/{task_type}"
            results[key] = {
                "latency_ms": round(lat, 1),
                "tokens": tokens,
                "model": model,
                "ok": True
            }
        except Exception as e:
            lat = (time.time() - t0) * 1000
            err_str = str(e)[:80]
            print(f"  {pname:<14} ERROR: {err_str}")
            results[f"{pname}/{task_type}"] = {"latency_ms": round(lat, 1), "ok": False, "error": err_str}
        time.sleep(0.3)

# Save results
os.makedirs("data", exist_ok=True)
with open("data/benchmark_results.json", "w") as f:
    json.dump({"ts": time.time(), "results": results}, f, indent=2, ensure_ascii=False)

print("\n" + "=" * 50)
ok = sum(1 for v in results.values() if v.get("ok"))
total = len(results)
print(f"✅ Results saved to data/benchmark_results.json  ({ok}/{total} success)")

# Summary: best provider per task
print("\nBest provider per task type:")
for task_type, _, _ in TASKS:
    task_res = {k.split("/")[0]: v for k, v in results.items()
                if k.endswith(f"/{task_type}") and v.get("ok")}
    if task_res:
        best = min(task_res.items(), key=lambda x: x[1]["latency_ms"])
        print(f"  {task_type:<10}: {best[0]:<14} {best[1]['latency_ms']:.0f}ms  model={best[1].get('model','?')[:25]}")
    else:
        print(f"  {task_type:<10}: no successful results")
