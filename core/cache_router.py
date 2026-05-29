"""
Semantic response cache with Redis backend + in-memory fallback.
Auto-switches between Redis (persistent) and dict (in-memory).

Cache key = hash(provider + model + normalized_prompt[:200])
TTL: chat=300s, analysis=600s, code=120s
"""
import hashlib, time, json, logging
from typing import Optional, Dict, Any
from functools import lru_cache

log = logging.getLogger(__name__)

# ── Redis backend ──────────────────────────────────────────
_redis_client = None
_redis_ok = False

def _get_redis():
    global _redis_client, _redis_ok
    if _redis_client is not None:
        return _redis_client if _redis_ok else None
    try:
        import redis
        _redis_client = redis.Redis(host="127.0.0.1", port=6379, db=0,
                                    decode_responses=True, socket_timeout=1)
        _redis_client.ping()
        _redis_ok = True
        log.info("SemanticCache: Redis connected ✅")
    except Exception as e:
        _redis_ok = False
        log.debug("SemanticCache: Redis unavailable (%s), using in-memory", e)
    return _redis_client if _redis_ok else None

# ── In-memory fallback (LRU, max 500 entries) ─────────────
_mem_cache: Dict[str, tuple] = {}  # key → (response, expires_at)
_MAX_MEM = 500

_TTL_BY_TASK = {
    "chat":     300,   # 5 min
    "general":  300,
    "math":     600,   # 10 min (deterministic)
    "classify": 600,
    "fast":     600,
    "analysis": 300,
    "code":     120,   # 2 min (may change)
    "news":     60,    # 1 min (stale quickly)
    "trading":  30,    # 30s
}

def _make_key(provider: str, model: str, prompt: str, task_type: str) -> str:
    norm = prompt.lower().strip()[:200]
    raw = f"{task_type}:{provider}:{model}:{norm}"
    return "scache:" + hashlib.sha256(raw.encode()).hexdigest()[:24]

def get(provider: str, model: str, prompt: str, task_type: str = "general") -> Optional[str]:
    key = _make_key(provider, model, prompt, task_type)
    rc = _get_redis()
    if rc:
        try:
            val = rc.get(key)
            if val:
                log.debug("SemanticCache HIT (redis): %s", key[:16])
                return val
        except Exception:
            pass
    # in-memory
    entry = _mem_cache.get(key)
    if entry:
        response, exp = entry
        if time.time() < exp:
            log.debug("SemanticCache HIT (mem): %s", key[:16])
            return response
        else:
            del _mem_cache[key]
    return None

def put(provider: str, model: str, prompt: str, response: str, task_type: str = "general") -> None:
    key = _make_key(provider, model, prompt, task_type)
    ttl = _TTL_BY_TASK.get(task_type, 300)
    rc = _get_redis()
    if rc:
        try:
            rc.setex(key, ttl, response)
            return
        except Exception:
            pass
    # in-memory fallback
    if len(_mem_cache) >= _MAX_MEM:
        # evict oldest
        oldest = min(_mem_cache.items(), key=lambda x: x[1][1])
        del _mem_cache[oldest[0]]
    _mem_cache[key] = (response, time.time() + ttl)

def stats() -> Dict[str, Any]:
    rc = _get_redis()
    mem_hits = len([v for v in _mem_cache.values() if time.time() < v[1]])
    result = {"backend": "redis" if rc else "memory", "mem_entries": mem_hits}
    if rc:
        try:
            result["redis_keys"] = rc.dbsize()
        except Exception:
            pass
    return result

def clear() -> int:
    """Clear all cache entries, return count cleared."""
    count = 0
    rc = _get_redis()
    if rc:
        try:
            keys = rc.keys("scache:*")
            if keys:
                rc.delete(*keys)
                count += len(keys)
        except Exception:
            pass
    count += len(_mem_cache)
    _mem_cache.clear()
    return count
