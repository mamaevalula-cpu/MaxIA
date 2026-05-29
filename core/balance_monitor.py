"""
Provider Balance Monitor
Checks remaining balance/quota on all LLM providers.
Switches to cheaper/free providers when balance is low.
"""
import os, json, time, logging
from typing import Dict, Optional, Tuple
from pathlib import Path
import httpx

log = logging.getLogger(__name__)

# Balance thresholds — switch to free tier when below
BALANCE_THRESHOLDS = {
    "anthropic":  1.0,   # Switch to groq/cerebras when < $1
    "openai":     1.0,
    "deepseek":   0.5,
    "gemini":     1.0,
    "grok":       0.5,
    "together":   0.5,
    "mistral":    0.5,
    "perplexity": 0.5,
}

# Free providers — always available when quota not exhausted
FREE_PROVIDERS = ["cerebras", "groq", "ollama"]

DATA_FILE = Path("/root/my_personal_ai/data/provider_balances.json")

_http = httpx.Client(timeout=10)
_cache: Dict[str, Tuple[float, float]] = {}  # provider → (balance, ts)
_CACHE_TTL = 300  # 5 min


def _load_env() -> Dict[str, str]:
    from dotenv import dotenv_values
    return dotenv_values("/root/my_personal_ai/.env")


def check_anthropic(api_key: str) -> Optional[float]:
    """Check Anthropic balance (they don't have a balance API, use usage)"""
    try:
        r = _http.get(
            "https://api.anthropic.com/v1/usage",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
        )
        if r.status_code == 200:
            d = r.json()
            # Anthropic returns usage, not balance — estimate from last month
            return d.get("data", {}).get("remaining_credits", None)
    except Exception:
        pass
    return None


def check_openai(api_key: str) -> Optional[float]:
    try:
        r = _http.get(
            "https://api.openai.com/v1/dashboard/billing/credit_grants",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if r.status_code == 200:
            d = r.json()
            return d.get("total_available", None)
    except Exception:
        pass
    return None


def check_deepseek(api_key: str) -> Optional[float]:
    try:
        r = _http.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if r.status_code == 200:
            d = r.json()
            balances = d.get("balance_infos", [])
            for b in balances:
                if b.get("currency") == "USD":
                    return float(b.get("total_balance", 0))
    except Exception:
        pass
    return None


def check_groq_quota(api_key: str) -> Optional[str]:
    """Groq free tier — check if quota available via test request"""
    try:
        r = _http.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "llama-3.3-70b-versatile",
                  "messages": [{"role": "user", "content": "1"}],
                  "max_tokens": 1},
            timeout=5
        )
        if r.status_code == 200:
            return "free_available"
        elif r.status_code == 429:
            return "rate_limited"
        return f"error_{r.status_code}"
    except Exception:
        return "unreachable"


def check_xai(api_key: str) -> Optional[float]:
    """Check xAI/Grok — no public balance API, verify key works via test call"""
    if not api_key:
        return None
    try:
        r = _http.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "grok-3-mini", "messages": [{"role": "user", "content": "1+1"}], "max_tokens": 2},
            timeout=15,
        )
        if r.status_code == 200:
            return -1.0  # Key works, balance unknown (xAI has no balance API)
        if r.status_code == 402:
            return 0.0   # Payment required — out of credits
    except Exception:
        pass
    return None


def get_all_balances() -> Dict[str, any]:
    """Check all providers and return status dict"""
    env = _load_env()
    results = {}
    now = time.time()

    checks = [
        ("anthropic", env.get("ANTHROPIC_API_KEY", ""), check_anthropic),
        ("openai",    env.get("OPENAI_API_KEY", ""),    check_openai),
        ("deepseek",  env.get("DEEPSEEK_API_KEY", ""),  check_deepseek),
        ("xai",       env.get("XAI_API_KEY", ""),       check_xai),
    ]

    for name, key, fn in checks:
        if not key:
            results[name] = {"status": "no_key", "balance": None}
            continue
        cached = _cache.get(name)
        if cached and now - cached[1] < _CACHE_TTL:
            results[name] = {"status": "cached", "balance": cached[0]}
            continue
        balance = fn(key)
        _cache[name] = (balance, now)
        if balance is None:
            results[name] = {"status": "api_error", "balance": None}
        elif balance == -1.0:
            results[name] = {"status": "key_valid", "balance": "unknown",
                            "note": "Balance API not available for this provider"}
        elif balance < BALANCE_THRESHOLDS.get(name, 0.5):
            results[name] = {"status": "LOW", "balance": balance}
        else:
            results[name] = {"status": "ok", "balance": balance}

    # Groq quota check
    groq_key = env.get("GROQ_API_KEY", "")
    if groq_key:
        results["groq"] = {"status": check_groq_quota(groq_key), "balance": "free"}

    # Cerebras
    cb_key = env.get("CEREBRAS_API_KEY", "")
    results["cerebras"] = {
        "status": "key_missing" if not cb_key else "ok",
        "balance": "free" if cb_key else None,
        "note": "Get free key at console.cerebras.ai" if not cb_key else ""
    }

    return results


def recommend_provider(task_type: str = "chat") -> str:
    """Return best available provider based on current balances"""
    balances = get_all_balances()

    # Priority: free first, then by remaining balance
    if balances.get("cerebras", {}).get("status") == "ok":
        return "cerebras"
    if balances.get("groq", {}).get("status") in ("free_available", "ok"):
        return "groq"
    if balances.get("deepseek", {}).get("status") == "ok":
        return "deepseek"
    if balances.get("xai", {}).get("status") == "ok":
        return "grok"
    return "claude"  # last resort


def save_report() -> str:
    """Save balance report to file and return summary string"""
    balances = get_all_balances()
    DATA_FILE.parent.mkdir(exist_ok=True)
    data = {"ts": time.time(), "balances": balances, "recommended": recommend_provider()}
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

    lines = ["Provider Balance Report:"]
    for name, info in balances.items():
        bal = info.get("balance")
        status = info.get("status", "?")
        bal_str = f"${bal:.2f}" if isinstance(bal, float) else str(bal)
        flag = "⚠️ LOW" if status == "LOW" else ("❌" if status == "no_key" else "✅")
        lines.append(f"  {flag} {name:<12} {bal_str:<10} [{status}]")
    return "\n".join(lines)


if __name__ == "__main__":
    print(save_report())
