# -*- coding: utf-8 -*-
"""
monitoring/metrics.py — Система метрик и observability.

Production-grade мониторинг системы:
  • Счётчики LLM вызовов, токенов, ошибок
  • Гистограммы latency
  • Gauges состояния агентов и провайдеров
  • Prometheus-совместимый экспорт (опционально)
  • In-memory fallback без внешних зависимостей
  • Thread-safe

Использование:
    from monitoring.metrics import metrics
    metrics.llm_call(provider="deepseek", task_type="code",
                     tokens=1500, latency_ms=340, success=True)
    metrics.agent_event("coder", "process", success=True)
    report = metrics.get_report()

Prometheus (опционально):
    pip install prometheus-client
    # Автоматически запустится /metrics HTTP endpoint на порту 8080
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("monitoring.metrics")

# Порт для Prometheus HTTP endpoint (0 = отключён)
PROMETHEUS_PORT = int(os.getenv("PROMETHEUS_PORT", "0"))

# Максимальная история для гистограмм
HISTOGRAM_WINDOW = 1000


@dataclass
class LatencyHistogram:
    """Скользящая гистограмма latency."""
    name: str
    _values: deque = field(default_factory=lambda: deque(maxlen=HISTOGRAM_WINDOW))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, value_ms: float) -> None:
        with self._lock:
            self._values.append(value_ms)

    @property
    def count(self) -> int:
        return len(self._values)

    @property
    def mean_ms(self) -> float:
        if not self._values:
            return 0.0
        return sum(self._values) / len(self._values)

    @property
    def p50_ms(self) -> float:
        return self._percentile(50)

    @property
    def p95_ms(self) -> float:
        return self._percentile(95)

    @property
    def p99_ms(self) -> float:
        return self._percentile(99)

    def _percentile(self, p: float) -> float:
        with self._lock:
            if not self._values:
                return 0.0
            sorted_vals = sorted(self._values)
            idx = max(0, int(len(sorted_vals) * p / 100) - 1)
            return sorted_vals[idx]

    def to_dict(self) -> Dict:
        return {
            "count": self.count,
            "mean_ms": round(self.mean_ms, 1),
            "p50_ms": round(self.p50_ms, 1),
            "p95_ms": round(self.p95_ms, 1),
            "p99_ms": round(self.p99_ms, 1),
        }


class MetricsCollector:
    """
    Singleton. Сбор и хранение всех метрик системы.
    Thread-safe.
    """

    _instance: Optional["MetricsCollector"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._rlock = threading.RLock()
        self._start_time = time.time()

        # ── LLM Metrics ───────────────────────────────────────────────────────
        self._llm_calls:    Dict[str, int]   = defaultdict(int)   # provider → count
        self._llm_errors:   Dict[str, int]   = defaultdict(int)
        self._llm_tokens:   Dict[str, int]   = defaultdict(int)
        self._llm_latency:  Dict[str, LatencyHistogram] = {}
        self._task_type_calls: Dict[str, int] = defaultdict(int)
        self._cache_hits:   int = 0
        self._cache_misses: int = 0

        # ── Agent Metrics ──────────────────────────────────────────────────────
        self._agent_calls:   Dict[str, int] = defaultdict(int)
        self._agent_errors:  Dict[str, int] = defaultdict(int)
        self._agent_latency: Dict[str, LatencyHistogram] = {}

        # ── Reflection Metrics ────────────────────────────────────────────────
        self._reflections_total:    int = 0
        self._reflections_improved: int = 0

        # ── Planning Metrics ──────────────────────────────────────────────────
        self._plans_created:   int = 0
        self._plans_completed: int = 0
        self._plans_failed:    int = 0

        # ── System Events ─────────────────────────────────────────────────────
        self._errors_total: int = 0
        self._restarts: Dict[str, int] = defaultdict(int)
        self._circuit_breaker_opens: int = 0

        # ── Token Budget ──────────────────────────────────────────────────────
        self._tokens_total:  int = 0
        self._tokens_saved:  int = 0   # через cache + context optimizer

        # Prometheus (optional)
        self._prom_counters: Dict[str, Any] = {}
        self._init_prometheus()

        log.info("MetricsCollector initialized (prometheus=%s)",
                 "enabled" if PROMETHEUS_PORT else "disabled")

    @classmethod
    def get(cls) -> "MetricsCollector":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _init_prometheus(self) -> None:
        """Инициализировать Prometheus (если доступен и порт задан)."""
        if not PROMETHEUS_PORT:
            return
        try:
            import prometheus_client as prom

            self._prom_counters = {
                "llm_calls": prom.Counter(
                    "personal_ai_llm_calls_total",
                    "Total LLM API calls", ["provider", "task_type", "status"]
                ),
                "llm_tokens": prom.Counter(
                    "personal_ai_llm_tokens_total",
                    "Total LLM tokens used", ["provider"]
                ),
                "agent_calls": prom.Counter(
                    "personal_ai_agent_calls_total",
                    "Agent processing calls", ["agent", "status"]
                ),
                "llm_latency": prom.Histogram(
                    "personal_ai_llm_latency_ms",
                    "LLM call latency in ms", ["provider"],
                    buckets=[50, 100, 200, 500, 1000, 2000, 5000, 10000]
                ),
                "agent_latency": prom.Histogram(
                    "personal_ai_agent_latency_ms",
                    "Agent processing latency in ms", ["agent"],
                    buckets=[100, 500, 1000, 5000, 15000, 30000]
                ),
                "cache_hits": prom.Counter(
                    "personal_ai_cache_hits_total", "Response cache hits"
                ),
                "errors": prom.Counter(
                    "personal_ai_errors_total", "Total errors", ["component"]
                ),
            }
            prom.start_http_server(PROMETHEUS_PORT)
            log.info("Prometheus metrics server started on :%d", PROMETHEUS_PORT)
        except ImportError:
            log.debug("prometheus-client not installed, using in-memory metrics only")
        except Exception as e:
            log.warning("Prometheus init failed: %s", e)

    # ── LLM Metrics ───────────────────────────────────────────────────────────

    def llm_call(self, provider: str, task_type: str = "general",
                  tokens: int = 0, latency_ms: float = 0,
                  success: bool = True, from_cache: bool = False) -> None:
        """Записать метрику LLM вызова."""
        with self._rlock:
            key = provider
            self._llm_calls[key] += 1
            self._task_type_calls[task_type] += 1
            if not success:
                self._llm_errors[key] += 1
            if tokens:
                self._llm_tokens[key] += tokens
                self._tokens_total += tokens
            if from_cache:
                self._cache_hits += 1
                self._tokens_saved += tokens  # считаем сэкономленными
            else:
                if success:
                    self._cache_misses += 1

            # Histogram
            if latency_ms and not from_cache:
                if key not in self._llm_latency:
                    self._llm_latency[key] = LatencyHistogram(name=key)
                self._llm_latency[key].observe(latency_ms)

        # Prometheus
        if self._prom_counters:
            try:
                status = "success" if success else "error"
                self._prom_counters["llm_calls"].labels(
                    provider=provider, task_type=task_type, status=status
                ).inc()
                if tokens:
                    self._prom_counters["llm_tokens"].labels(provider=provider).inc(tokens)
                if latency_ms and not from_cache:
                    self._prom_counters["llm_latency"].labels(provider=provider).observe(latency_ms)
                if from_cache:
                    self._prom_counters["cache_hits"].inc()
            except Exception:
                pass

    # ── Agent Metrics ──────────────────────────────────────────────────────────

    def agent_event(self, agent_name: str, action: str = "process",
                     success: bool = True, latency_ms: float = 0) -> None:
        """Записать метрику работы агента."""
        with self._rlock:
            self._agent_calls[agent_name] += 1
            if not success:
                self._agent_errors[agent_name] += 1
                self._errors_total += 1
            if latency_ms:
                if agent_name not in self._agent_latency:
                    self._agent_latency[agent_name] = LatencyHistogram(name=agent_name)
                self._agent_latency[agent_name].observe(latency_ms)

        if self._prom_counters:
            try:
                status = "success" if success else "error"
                self._prom_counters["agent_calls"].labels(
                    agent=agent_name, status=status
                ).inc()
                if latency_ms:
                    self._prom_counters["agent_latency"].labels(
                        agent=agent_name
                    ).observe(latency_ms)
            except Exception:
                pass

    # ── System Events ──────────────────────────────────────────────────────────

    def record_reflection(self, improved: bool) -> None:
        with self._rlock:
            self._reflections_total += 1
            if improved:
                self._reflections_improved += 1

    def record_plan(self, event: str) -> None:
        """event: 'created' | 'completed' | 'failed'"""
        with self._rlock:
            if event == "created":
                self._plans_created += 1
            elif event == "completed":
                self._plans_completed += 1
            elif event == "failed":
                self._plans_failed += 1

    def record_agent_restart(self, agent_name: str) -> None:
        with self._rlock:
            self._restarts[agent_name] += 1

    def record_circuit_breaker_open(self) -> None:
        with self._rlock:
            self._circuit_breaker_opens += 1

    def record_error(self, component: str) -> None:
        with self._rlock:
            self._errors_total += 1
        if self._prom_counters:
            try:
                self._prom_counters["errors"].labels(component=component).inc()
            except Exception:
                pass

    def record_tokens_saved(self, count: int) -> None:
        with self._rlock:
            self._tokens_saved += count

    # ── Reports ───────────────────────────────────────────────────────────────

    def get_snapshot(self) -> Dict:
        """Полный снимок всех метрик."""
        with self._rlock:
            uptime_h = (time.time() - self._start_time) / 3600

            total_llm_calls = sum(self._llm_calls.values())
            total_llm_errors = sum(self._llm_errors.values())
            total_tokens = sum(self._llm_tokens.values())

            cache_total = self._cache_hits + self._cache_misses
            cache_ratio = self._cache_hits / cache_total if cache_total > 0 else 0.0

            llm_latencies = {}
            for prov, hist in self._llm_latency.items():
                llm_latencies[prov] = hist.to_dict()

            agent_latencies = {}
            for agent, hist in self._agent_latency.items():
                agent_latencies[agent] = hist.to_dict()

            return {
                "uptime_hours":      round(uptime_h, 2),
                "llm": {
                    "total_calls":   total_llm_calls,
                    "total_errors":  total_llm_errors,
                    "error_rate":    round(total_llm_errors / max(total_llm_calls, 1) * 100, 2),
                    "total_tokens":  total_tokens,
                    "tokens_saved":  self._tokens_saved,
                    "cache_hits":    self._cache_hits,
                    "cache_ratio":   round(cache_ratio * 100, 1),
                    "by_provider":   dict(self._llm_calls),
                    "by_task_type":  dict(self._task_type_calls),
                    "latency":       llm_latencies,
                },
                "agents": {
                    "by_calls":    dict(self._agent_calls),
                    "by_errors":   dict(self._agent_errors),
                    "latency":     agent_latencies,
                },
                "reflection": {
                    "total":        self._reflections_total,
                    "improved":     self._reflections_improved,
                    "improvement_rate": round(
                        self._reflections_improved / max(self._reflections_total, 1) * 100, 1
                    ),
                },
                "planning": {
                    "created":   self._plans_created,
                    "completed": self._plans_completed,
                    "failed":    self._plans_failed,
                },
                "system": {
                    "errors_total":         self._errors_total,
                    "circuit_breaker_opens": self._circuit_breaker_opens,
                    "agent_restarts":       dict(self._restarts),
                },
            }

    def get_report(self) -> str:
        """Читаемый отчёт о метриках."""
        s = self.get_snapshot()
        llm = s["llm"]
        refl = s["reflection"]
        plan = s["planning"]
        sys_ = s["system"]

        lines = [
            f"📊 **Metrics Report** (uptime: {s['uptime_hours']:.1f}h)\n",

            f"🧠 **LLM:**",
            f"  Вызовов: {llm['total_calls']} (ошибок: {llm['error_rate']}%)",
            f"  Токенов: {llm['total_tokens']:,} (сэкономлено: {llm['tokens_saved']:,})",
            f"  Cache: {llm['cache_hits']} hits ({llm['cache_ratio']}%)",
        ]

        if llm["latency"]:
            best = min(llm["latency"].items(), key=lambda x: x[1].get("p50_ms", 9999))
            lines.append(f"  Лучший провайдер: {best[0]} (p50={best[1].get('p50_ms')}ms)")

        if llm["by_provider"]:
            top = sorted(llm["by_provider"].items(), key=lambda x: x[1], reverse=True)[:3]
            lines.append("  Топ провайдеры: " + ", ".join(f"{p}={n}" for p, n in top))

        lines += [
            f"\n🔍 **Reflection:**",
            f"  Проверок: {refl['total']}, улучшено: {refl['improved']} ({refl['improvement_rate']}%)",

            f"\n📋 **Planning:**",
            f"  Создано: {plan['created']}, выполнено: {plan['completed']}, ошибок: {plan['failed']}",

            f"\n⚠️ **System:**",
            f"  Ошибок: {sys_['errors_total']}, CB opens: {sys_['circuit_breaker_opens']}",
        ]

        if sys_["agent_restarts"]:
            lines.append("  Рестартов: " + ", ".join(
                f"{a}={n}" for a, n in sys_["agent_restarts"].items()
            ))

        return "\n".join(lines)


# Глобальный синглтон — удобный импорт
metrics = MetricsCollector.get()
