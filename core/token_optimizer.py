"""
Token Optimizer — tracks real costs per provider, auto-ranks providers.
Runs as background task every 30 min, writes results to data/provider_stats.json
"""
import json, time, os, logging
from typing import Dict, List, Tuple
from pathlib import Path

log = logging.getLogger(__name__)
DATA_FILE = Path(__file__).parent.parent / "data" / "provider_stats.json"

# Real-time pricing (update when providers change) USD per 1M tokens
PROVIDER_PRICES = {
    # provider: (input_price, output_price)
    "cerebras":   (0.0,    0.0),     # FREE tier
    "groq":       (0.0,    0.0),     # FREE tier
    "ollama":     (0.0,    0.0),     # LOCAL free
    "together":   (0.18,   0.18),    # Qwen3-72B
    "deepseek":   (0.27,   1.10),    # deepseek-chat V3
    "gemini":     (0.075,  0.30),    # gemini-2.5-flash
    "mistral":    (0.40,   1.20),    # mistral-medium
    "grok":       (0.30,   0.50),    # grok-3-mini
    "perplexity": (1.0,    1.0),
    "openai":     (3.0,    12.0),    # gpt-4o
    "claude":     (3.0,    15.0),    # claude-sonnet/opus
    "openrouter": (0.20,   0.20),    # avg cheapest
}

# Quality scores (0-10, subjective, update based on experience)
PROVIDER_QUALITY = {
    "cerebras":   6,   # Good for chat, fast
    "groq":       7,   # llama-3.3-70b is solid
    "ollama":     5,   # Depends on local model
    "together":   7,   # Qwen3-72B is strong
    "deepseek":   8,   # deepseek-chat is excellent value
    "gemini":     8,   # gemini-2.5-flash is very good
    "mistral":    7,
    "grok":       8,   # Real-time knowledge
    "perplexity": 8,   # Search-augmented
    "openai":     9,   # GPT-4o
    "claude":     9,   # Best reasoning
    "openrouter": 7,
}

class TokenOptimizer:
    """
    Tracks token usage and costs per provider.
    Auto-suggests best provider per task type based on cost×quality.
    """

    def __init__(self):
        self._session_stats: Dict[str, Dict] = {}
        self._load()

    def _load(self):
        try:
            if DATA_FILE.exists():
                with open(DATA_FILE) as f:
                    self._session_stats = json.load(f)
        except Exception:
            self._session_stats = {}

    def save(self):
        DATA_FILE.parent.mkdir(exist_ok=True)
        try:
            with open(DATA_FILE, "w") as f:
                json.dump(self._session_stats, f, indent=2)
        except Exception as e:
            log.warning("TokenOptimizer save failed: %s", e)

    def record(self, provider: str, model: str, task_type: str,
               input_tokens: int, output_tokens: int, latency_ms: float,
               success: bool) -> float:
        """Record a call, return cost in USD."""
        inp_price, out_price = PROVIDER_PRICES.get(provider, (5.0, 15.0))
        cost = (input_tokens * inp_price + output_tokens * out_price) / 1_000_000

        key = f"{provider}/{task_type}"
        if key not in self._session_stats:
            self._session_stats[key] = {
                "calls": 0, "tokens_in": 0, "tokens_out": 0,
                "cost_usd": 0.0, "avg_latency_ms": 0.0,
                "errors": 0, "last_updated": 0
            }
        s = self._session_stats[key]
        s["calls"] += 1
        s["tokens_in"] += input_tokens
        s["tokens_out"] += output_tokens
        s["cost_usd"] += cost
        n = s["calls"]
        s["avg_latency_ms"] = (s["avg_latency_ms"] * (n-1) + latency_ms) / n
        if not success:
            s["errors"] += 1
        s["last_updated"] = time.time()
        return cost

    def best_provider_for(self, task_type: str,
                           available: List[str]) -> str:
        """
        Return best provider for task type based on:
        score = quality / (cost_per_1k_tokens × latency_weight)
        """
        scores = []
        for provider in available:
            if provider not in PROVIDER_PRICES:
                continue
            inp_p, out_p = PROVIDER_PRICES[provider]
            cost = inp_p + out_p * 0.5  # estimate: 1:0.5 in:out ratio
            quality = PROVIDER_QUALITY.get(provider, 5)
            # Get real latency if tracked
            key = f"{provider}/{task_type}"
            s = self._session_stats.get(key, {})
            lat = s.get("avg_latency_ms", 2000)  # default 2s
            # Normalize: higher is better
            # free tier gets huge bonus
            cost_score = 10.0 / (cost + 0.01)   # $0 → 1000, $1 → 10
            lat_score  = 1000.0 / (lat + 100)    # 100ms → 9, 2000ms → 0.5
            total = quality * 0.5 + cost_score * 0.3 + lat_score * 0.2
            scores.append((provider, total))

        if not scores:
            return available[0] if available else "groq"
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[0][0]

    def cost_report(self) -> str:
        """Human-readable cost report."""
        lines = ["Provider/Task           | Calls | Tokens | Cost($) | Avg ms"]
        lines.append("-" * 65)
        total_cost = 0.0
        for key, s in sorted(self._session_stats.items()):
            tokens = s["tokens_in"] + s["tokens_out"]
            cost = s["cost_usd"]
            total_cost += cost
            lines.append(
                f"{key:<22} | {s['calls']:>5} | {tokens:>6} | "
                f"${cost:.4f}  | {s['avg_latency_ms']:>6.0f}"
            )
        lines.append("-" * 65)
        lines.append(f"TOTAL COST THIS SESSION: ${total_cost:.4f}")
        return "\n".join(lines)

    def token_budget_check(self, provider: str, estimated_tokens: int,
                            budget_usd: float = 0.01) -> bool:
        """Return True if this call fits within budget."""
        inp_p, out_p = PROVIDER_PRICES.get(provider, (5.0, 15.0))
        est_cost = estimated_tokens * (inp_p + out_p * 0.3) / 1_000_000
        return est_cost <= budget_usd


# Global singleton
token_optimizer = TokenOptimizer()
