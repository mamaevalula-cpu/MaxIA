# -*- coding: utf-8 -*-
"""
brain/model_profiler.py — Профилировщик моделей.

Отслеживает производительность каждой LLM-модели по типу задачи:
  • Качество ответа (0.0-1.0)
  • Задержка (мс)
  • Процент успеха
  • Специализация по задачам (code, analysis, trading, chat, creative, math)

Используется LLMRouter для интеллектуального выбора модели.
Данные накапливаются в data/model_profiles.json.

Автоматически обновляется после каждого LLM-вызова.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("brain.model_profiler")

PROFILE_FILE = Path(__file__).parent.parent / "data" / "model_profiles.json"

# ── База знаний о моделях (обновляется из исследований) ──────────────────────

MODEL_KNOWLEDGE: Dict[str, Dict] = {
    # OpenAI
    "gpt-4o": {
        "provider": "openai",
        "strengths": ["универсальность", "coding", "reasoning", "vision", "json"],
        "best_for": ["code", "analysis", "chat", "image", "general"],
        "speed": "medium",    # ~2-5s
        "cost": "high",
        "context_tokens": 128000,
        "description": "Лучший универсальный ИИ от OpenAI. Мультимодальный.",
    },
    "o3": {
        "provider": "openai",
        "strengths": ["глубокое рассуждение", "математика", "сложный код", "логика"],
        "best_for": ["analysis", "code", "math", "quality"],
        "speed": "slow",      # ~10-30s (думает дольше)
        "cost": "very_high",
        "context_tokens": 200000,
        "description": "Лучший reasoning-модель OpenAI. Думает дольше, ответ точнее.",
    },
    "o4-mini": {
        "provider": "openai",
        "strengths": ["быстрое рассуждение", "код", "математика"],
        "best_for": ["code", "math", "fast_quality"],
        "speed": "fast",
        "cost": "medium",
        "context_tokens": 128000,
        "description": "Быстрый reasoning от OpenAI. Баланс скорости и качества.",
    },
    # Anthropic Claude
    "claude-opus-4-7": {
        "provider": "claude",
        "strengths": ["письмо", "анализ", "длинный контекст", "человечность", "coding"],
        "best_for": ["analysis", "creative", "code", "quality"],
        "speed": "slow",
        "cost": "very_high",
        "context_tokens": 200000,
        "description": "Флагман Anthropic. Лучший для длинных документов и анализа.",
    },
    "claude-3-5-sonnet-20241022": {
        "provider": "claude",
        "strengths": ["coding", "анализ", "баланс скорость/качество"],
        "best_for": ["code", "analysis", "chat"],
        "speed": "medium",
        "cost": "high",
        "context_tokens": 200000,
        "description": "Оптимальный Claude. Лучший выбор для большинства задач.",
    },
    "claude-haiku-4-5-20251001": {
        "provider": "claude",
        "strengths": ["скорость", "краткость", "простые задачи"],
        "best_for": ["fast", "classify", "chat"],
        "speed": "very_fast",
        "cost": "low",
        "context_tokens": 200000,
        "description": "Самый быстрый Claude. Для простых задач и классификации.",
    },
    # Google Gemini
    "gemini-2.5-flash": {
        "provider": "gemini",
        "strengths": ["логика", "наука", "мультимодальность", "видео", "огромный контекст"],
        "best_for": ["analysis", "math", "image", "multimodal", "quality"],
        "speed": "medium",
        "cost": "high",
        "context_tokens": 1000000,
        "description": "Лучший Gemini. Огромный контекст (1M токен). Силён в науке.",
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "strengths": ["скорость", "мультимодальность", "цена"],
        "best_for": ["fast", "chat", "image", "summarize"],
        "speed": "very_fast",
        "cost": "very_low",
        "context_tokens": 1000000,
        "description": "Быстрый и дешёвый Gemini. Лучший по цена/качество.",
    },
    # xAI Grok
    "grok-3-mini": {
        "provider": "grok",
        "strengths": ["актуальные новости", "Twitter/X данные", "быстрые ответы", "coding"],
        "best_for": ["news", "chat", "trading", "current_events"],
        "speed": "fast",
        "cost": "medium",
        "context_tokens": 131072,
        "description": "Grok от xAI. Доступ к данным X/Twitter. Актуальная информация.",
    },
    "grok-3-mini": {
        "provider": "grok",
        "strengths": ["скорость", "reasoning lite"],
        "best_for": ["fast", "classify"],
        "speed": "very_fast",
        "cost": "low",
        "context_tokens": 131072,
        "description": "Быстрый Grok для простых задач.",
    },
    # DeepSeek
    "deepseek-reasoner": {
        "provider": "deepseek",
        "strengths": ["математика", "код", "глубокое рассуждение", "цена"],
        "best_for": ["code", "math", "analysis", "quality"],
        "speed": "medium",
        "cost": "very_low",
        "context_tokens": 64000,
        "description": "DeepSeek R1. Лучший по цена/качество. Отличный кодинг и математика.",
    },
    "deepseek-chat": {
        "provider": "deepseek",
        "strengths": ["код", "скорость", "цена"],
        "best_for": ["code", "fast", "chat"],
        "speed": "fast",
        "cost": "very_low",
        "context_tokens": 64000,
        "description": "DeepSeek V3. Быстрый и дешёвый для обычных задач.",
    },
    # Meta Llama (через Groq)
    "llama-4-scout-17b-16e-instruct": {
        "provider": "groq",
        "strengths": ["мультимодальность", "скорость", "open-source"],
        "best_for": ["fast", "chat", "multimodal"],
        "speed": "very_fast",
        "cost": "free",
        "context_tokens": 131072,
        "description": "Llama 4 Scout от Meta через Groq. Бесплатный, быстрый.",
    },
    "llama-3.3-70b-versatile": {
        "provider": "groq",
        "strengths": ["универсальность", "открытость", "бесплатность"],
        "best_for": ["chat", "analysis", "code"],
        "speed": "very_fast",
        "cost": "free",
        "context_tokens": 128000,
        "description": "Llama 3.3 70B через Groq. Бесплатный, надёжный.",
    },
    # Mistral (через Together или Groq)
    "mistral-large-latest": {
        "provider": "mistral",
        "strengths": ["европейский", "многоязычность", "код", "скорость"],
        "best_for": ["code", "multilingual", "chat"],
        "speed": "fast",
        "cost": "medium",
        "context_tokens": 32000,
        "description": "Лучший Mistral. Европейский лидер. Хорош для многоязычных задач.",
    },
    "mixtral-8x7b-32768": {
        "provider": "groq",
        "strengths": ["MoE архитектура", "скорость", "эффективность"],
        "best_for": ["fast", "chat", "code"],
        "speed": "very_fast",
        "cost": "free",
        "context_tokens": 32768,
        "description": "Mixtral 8x7B через Groq. MoE модель, быстрая и эффективная.",
    },
    # Qwen (через Together)
    "Qwen/Qwen3-235B-A22B": {
        "provider": "together",
        "strengths": ["многоязычность", "код", "математика", "open-source"],
        "best_for": ["multilingual", "code", "math", "analysis"],
        "speed": "medium",
        "cost": "low",
        "context_tokens": 128000,
        "description": "Qwen 3 235B от Alibaba. Сильный в CJK языках, математике и коде.",
    },
}

# ── Матрица лучших моделей по задачам ────────────────────────────────────────

TASK_MODEL_MATRIX: Dict[str, List[Tuple[str, str]]] = {
    # (provider_enum_value, model_name)
    "code": [
        ("deepseek",  "deepseek-reasoner"),
        ("openai",    "o3"),
        ("openai",    "o4-mini"),
        ("claude",    "claude-3-5-sonnet-20241022"),
        ("together",  "Qwen/Qwen3-235B-A22B"),
        ("groq",      "llama-3.3-70b-versatile"),
        ("mistral",   "mistral-large-latest"),
    ],
    "analysis": [
        ("claude",    "claude-opus-4-7"),
        ("openai",    "o3"),
        ("gemini",    "gemini-2.5-flash"),
        ("grok",      "grok-3-mini"),
        ("deepseek",  "deepseek-reasoner"),
        ("claude",    "claude-3-5-sonnet-20241022"),
    ],
    "math": [
        ("openai",    "o3"),
        ("deepseek",  "deepseek-reasoner"),
        ("gemini",    "gemini-2.5-flash"),
        ("together",  "Qwen/Qwen3-235B-A22B"),
        ("claude",    "claude-opus-4-7"),
    ],
    "trading": [
        ("deepseek",  "deepseek-reasoner"),
        ("grok",      "grok-3-mini"),
        ("groq",      "llama-3.3-70b-versatile"),
        ("openai",    "gpt-4o"),
    ],
    "creative": [
        ("claude",    "claude-opus-4-7"),
        ("openai",    "gpt-4o"),
        ("gemini",    "gemini-2.5-flash"),
        ("grok",      "grok-3-mini"),
    ],
    "news": [
        ("grok",      "grok-3-mini"),          # доступ к X/Twitter
        ("perplexity","llama-3.1-sonar-small-128k-online"),
        ("openai",    "gpt-4o"),
        ("groq",      "llama-3.3-70b-versatile"),
    ],
    "fast": [
        ("groq",      "llama-4-scout-17b-16e-instruct"),
        ("groq",      "llama-3.3-70b-versatile"),
        ("claude",    "claude-haiku-4-5-20251001"),
        ("gemini",    "gemini-2.5-flash"),
        ("openai",    "o4-mini"),
        ("grok",      "grok-3-mini"),
    ],
    "image": [
        ("claude",    "claude-3-5-sonnet-20241022"),   # vision
        ("openai",    "gpt-4o"),              # vision
        ("gemini",    "gemini-2.5-flash"),  # vision
    ],
    "multilingual": [
        ("together",  "Qwen/Qwen3-235B-A22B"),
        ("mistral",   "mistral-large-latest"),
        ("gemini",    "gemini-2.5-flash"),
        ("openai",    "gpt-4o"),
    ],
    "quality": [
        ("openai",    "o3"),
        ("claude",    "claude-opus-4-7"),
        ("gemini",    "gemini-2.5-flash"),
        ("deepseek",  "deepseek-reasoner"),
    ],
    "chat": [
        ("deepseek",  "deepseek-reasoner"),
        ("openai",    "gpt-4o"),
        ("claude",    "claude-3-5-sonnet-20241022"),
        ("grok",      "grok-3-mini"),
        ("gemini",    "gemini-2.5-flash"),
        ("groq",      "llama-3.3-70b-versatile"),
    ],
}


@dataclass
class ModelStats:
    """Статистика производительности одной модели."""
    provider: str
    model: str
    task_type: str
    calls: int = 0
    successes: int = 0
    total_quality: float = 0.0
    total_latency_ms: float = 0.0
    last_call: float = 0.0

    @property
    def avg_quality(self) -> float:
        return self.total_quality / max(self.calls, 1)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(self.calls, 1)

    @property
    def success_rate(self) -> float:
        return self.successes / max(self.calls, 1)

    def score(self) -> float:
        """Итоговый score: качество * success_rate * speed_bonus."""
        speed_bonus = max(0.5, 1.0 - self.avg_latency_ms / 30000)
        return self.avg_quality * self.success_rate * speed_bonus


class ModelProfiler:
    """
    Singleton для отслеживания производительности моделей.
    Используется LLMRouter для оптимального выбора.
    """

    _instance: Optional["ModelProfiler"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._stats: Dict[str, ModelStats] = {}
        self._rlock = threading.RLock()
        self._load()

    @classmethod
    def get(cls) -> "ModelProfiler":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def record(self, provider: str, model: str, task_type: str,
               quality: float, latency_ms: float, success: bool) -> None:
        """Записать результат вызова модели."""
        key = f"{provider}/{model}/{task_type}"
        with self._rlock:
            if key not in self._stats:
                self._stats[key] = ModelStats(
                    provider=provider, model=model, task_type=task_type
                )
            s = self._stats[key]
            s.calls += 1
            if success:
                s.successes += 1
            s.total_quality += quality
            s.total_latency_ms += latency_ms
            s.last_call = time.time()
        # Сохраняем асинхронно
        threading.Thread(target=self._save, daemon=True).start()

    def get_best_providers(self, task_type: str,
                           available_providers: List[str]) -> List[Tuple[str, str]]:
        """
        Вернуть список (provider, model) отсортированный по performance.
        Сначала берём из TASK_MODEL_MATRIX, потом сортируем по реальным данным.
        """
        matrix_entries = TASK_MODEL_MATRIX.get(task_type,
                         TASK_MODEL_MATRIX.get("chat", []))

        # Фильтруем по доступным провайдерам
        available = [
            (p, m) for p, m in matrix_entries
            if p in available_providers
        ]

        if not available:
            # Fallback: берём из chat матрицы
            available = [
                (p, m) for p, m in TASK_MODEL_MATRIX.get("chat", [])
                if p in available_providers
            ]

        # Сортируем по реальной производительности если есть данные
        with self._rlock:
            def sort_key(pm: Tuple[str, str]) -> float:
                p, m = pm
                key = f"{p}/{m}/{task_type}"
                if key in self._stats and self._stats[key].calls >= 3:
                    return -self._stats[key].score()  # отрицательный = DESC
                return 0.0  # новые — оставляем на своём месте

            available.sort(key=sort_key)

        return available

    def get_model_info(self, model: str) -> Dict:
        """Получить знания о модели."""
        return MODEL_KNOWLEDGE.get(model, {})

    def get_stats_report(self) -> str:
        """Форматированный отчёт о производительности всех моделей."""
        if not self._stats:
            return "📊 Статистика моделей пуста (ещё не было вызовов)"

        lines = ["📊 **Профили моделей (реальная статистика)**\n"]
        # Группируем по провайдеру
        by_provider: Dict[str, List[ModelStats]] = {}
        for s in self._stats.values():
            by_provider.setdefault(s.provider, []).append(s)

        for provider, stats_list in sorted(by_provider.items()):
            lines.append(f"\n**{provider.upper()}**")
            # Суммируем по модели (разные task_type)
            by_model: Dict[str, List[ModelStats]] = {}
            for s in stats_list:
                by_model.setdefault(s.model, []).append(s)

            for model, model_stats in sorted(by_model.items()):
                total_calls = sum(s.calls for s in model_stats)
                avg_quality = sum(s.avg_quality * s.calls for s in model_stats) / max(total_calls, 1)
                avg_lat = sum(s.avg_latency_ms * s.calls for s in model_stats) / max(total_calls, 1)
                success_rate = sum(s.successes for s in model_stats) / max(total_calls, 1)
                lines.append(
                    f"  • {model[:35]}: "
                    f"{total_calls} calls | "
                    f"quality={avg_quality:.0%} | "
                    f"speed={avg_lat:.0f}ms | "
                    f"ok={success_rate:.0%}"
                )

        return "\n".join(lines)

    def get_model_knowledge_text(self) -> str:
        """Текстовое описание всех моделей для системного промта."""
        lines = ["ЗНАНИЯ О ДОСТУПНЫХ AI-МОДЕЛЯХ:\n"]
        by_provider: Dict[str, List[Dict]] = {}
        for model_name, info in MODEL_KNOWLEDGE.items():
            p = info.get("provider", "?")
            by_provider.setdefault(p, []).append({**info, "model": model_name})

        for provider, models in sorted(by_provider.items()):
            lines.append(f"\n{provider.upper()}:")
            for m in models:
                strengths = ", ".join(m.get("strengths", [])[:3])
                lines.append(
                    f"  • {m['model']}: {m.get('description', '')} "
                    f"[{strengths}] speed={m.get('speed','?')} cost={m.get('cost','?')}"
                )
        return "\n".join(lines)

    def _save(self) -> None:
        try:
            PROFILE_FILE.parent.mkdir(exist_ok=True)
            with self._rlock:
                data = {k: asdict(v) for k, v in self._stats.items()}
            PROFILE_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            log.debug("Profile save failed: %s", e)

    def _load(self) -> None:
        try:
            if PROFILE_FILE.exists():
                data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
                for key, d in data.items():
                    self._stats[key] = ModelStats(**d)
                log.info("Loaded %d model profile entries", len(self._stats))
        except Exception as e:
            log.debug("Profile load failed: %s", e)
