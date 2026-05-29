# -*- coding: utf-8 -*-
"""
core/config.py — Централизованная конфигурация всей системы my_personal_ai.

Поддерживаемые LLM провайдеры (2026):
  OpenAI   — GPT-5, GPT-4o, o3, o4-mini
  Anthropic — Claude Opus/Sonnet/Haiku
  Google   — Gemini 2.5 Pro/Flash/Ultra
  xAI      — Grok 4, Grok Mini
  DeepSeek — R1, V3
  Meta     — Llama 4 Scout/Maverick (через Groq/Together)
  Mistral  — Large, Mixtral
  Qwen     — Qwen 3, Max (через Together)
  Groq     — быстрый inference (Llama, Mixtral, Gemma)
  Together — агрегатор open-source моделей
  Perplexity — онлайн-поиск
  Ollama   — локальные модели
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import List, Optional

BASE_DIR = Path(__file__).parent.parent  # my_personal_ai/

try:
    from dotenv import load_dotenv
    # Priority: .env.local (overrides) → .env → system env
    _env_local = BASE_DIR / ".env.local"
    if _env_local.exists():
        load_dotenv(_env_local, override=True)
    load_dotenv(BASE_DIR / ".env", override=False)
except ImportError:
    pass


class LLMProvider(str, Enum):
    # ── Топовые платные ──────────────────────────────────────────
    OPENAI      = "openai"       # GPT-5, GPT-4o, o3, o4-mini
    CLAUDE      = "claude"       # Claude Opus 4.7, Sonnet 4.6, Haiku
    GEMINI      = "gemini"       # Gemini 2.5 Pro/Flash/Ultra
    GROK        = "grok"         # Grok 4, Grok Mini (xAI)
    # ── Лучшие бесплатные / дешёвые ─────────────────────────────
    DEEPSEEK    = "deepseek"     # DeepSeek R1, V3
    GROQ        = "groq"         # Llama 4, Mixtral, Gemma (быстрый inference)
    TOGETHER    = "together"     # Llama 4, Qwen 3, Mistral Large (Together AI)
    CEREBRAS    = "cerebras"    # Ultra-fast free tier
    OPENROUTER  = "openrouter"  # 100+ models, cheapest
    MISTRAL     = "mistral"      # Mistral Large, Small
    PERPLEXITY  = "perplexity"   # Поиск + генерация
    # ── Локальные ────────────────────────────────────────────────
    OLLAMA      = "ollama"       # Любая локальная модель


class VectorBackend(str, Enum):
    CHROMA   = "chroma"
    QDRANT   = "qdrant"
    FAISS    = "faiss"
    PINECONE = "pinecone"
    SQLITE   = "sqlite"


class SystemConfig:
    """Единый конфиг системы."""

    BASE_DIR:     Path = BASE_DIR
    DATA_DIR:     Path = BASE_DIR / "data"
    LOGS_DIR:     Path = BASE_DIR / "logs"
    MEMORY_DIR:   Path = BASE_DIR / "memory"
    PROJECTS_DIR: Path = BASE_DIR / "projects"
    VECTOR_DIR:   Path = BASE_DIR / "vector_stores" / "data"

    # ── OpenAI ────────────────────────────────────────────────────────────────
    @property
    def openai_api_key(self) -> str:
        return os.getenv("OPENAI_API_KEY", "")

    @property
    def openai_model(self) -> str:
        return os.getenv("OPENAI_MODEL", "gpt-4o")

    # ── Anthropic / Claude ────────────────────────────────────────────────────
    @property
    def claude_api_key(self) -> str:
        return os.getenv("ANTHROPIC_API_KEY", "")

    @property
    def claude_model(self) -> str:
        return os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20241022")

    # ── Google Gemini ─────────────────────────────────────────────────────────
    @property
    def gemini_api_key(self) -> str:
        return os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")

    @property
    def gemini_model(self) -> str:
        return os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-05-20")

    # ── xAI / Grok ────────────────────────────────────────────────────────────
    @property
    def grok_api_key(self) -> str:
        return os.getenv("XAI_API_KEY", "") or os.getenv("GROK_API_KEY", "")

    @property
    def grok_model(self) -> str:
        return os.getenv("GROK_MODEL", "grok-3-mini")

    # ── DeepSeek ──────────────────────────────────────────────────────────────
    @property
    def deepseek_api_key(self) -> str:
        return os.getenv("DEEPSEEK_API_KEY", "")

    @property
    def deepseek_model(self) -> str:
        return os.getenv("DEEPSEEK_MODEL", "deepseek-reasoner")

    # ── Groq (Llama/Mistral/Gemma быстрый inference) ──────────────────────────
    @property
    def groq_api_key(self) -> str:
        return os.getenv("GROQ_API_KEY", "")

    @property
    def groq_model(self) -> str:
        return os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # ── Cerebras (ultra-fast free tier, 500 tok/s) ────────────────────────────
    @property
    def cerebras_api_key(self) -> str:
        return os.getenv("CEREBRAS_API_KEY", "")

    # ── OpenRouter (100+ models, auto-cheapest) ───────────────────────────────
    @property
    def openrouter_api_key(self) -> str:
        return os.getenv("OPENROUTER_API_KEY", "")

    # ── Together AI (Llama 4, Qwen 3, Mistral Large) ─────────────────────────
    @property
    def together_api_key(self) -> str:
        return os.getenv("TOGETHER_API_KEY", "")

    @property
    def together_model(self) -> str:
        return os.getenv("TOGETHER_MODEL", "meta-llama/Llama-4-Scout-17B-16E-Instruct")

    # ── Mistral ───────────────────────────────────────────────────────────────
    @property
    def mistral_api_key(self) -> str:
        return os.getenv("MISTRAL_API_KEY", "")

    @property
    def mistral_model(self) -> str:
        return os.getenv("MISTRAL_MODEL", "mistral-large-latest")

    # ── Perplexity ────────────────────────────────────────────────────────────
    @property
    def perplexity_api_key(self) -> str:
        return os.getenv("PERPLEXITY_API_KEY", "")

    # ── Ollama (локально) ─────────────────────────────────────────────────────
    @property
    def ollama_url(self) -> str:
        return os.getenv("OLLAMA_URL", "http://localhost:11434")

    @property
    def ollama_model(self) -> str:
        return os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    # ── Векторные базы ────────────────────────────────────────────────────────
    @property
    def default_vector_backend(self) -> VectorBackend:
        backend = os.getenv("VECTOR_BACKEND", "sqlite").lower()
        try:
            return VectorBackend(backend)
        except ValueError:
            return VectorBackend.SQLITE

    @property
    def pinecone_api_key(self) -> str:
        return os.getenv("PINECONE_API_KEY", "")

    @property
    def pinecone_environment(self) -> str:
        return os.getenv("PINECONE_ENVIRONMENT", "gcp-starter")

    @property
    def qdrant_url(self) -> str:
        return os.getenv("QDRANT_URL", "http://localhost:6333")

    # ── Telegram ──────────────────────────────────────────────────────────────
    @property
    def telegram_token(self) -> str:
        return os.getenv("TELEGRAM_BOT_TOKEN", "")

    @property
    def telegram_chat_id(self) -> str:
        return os.getenv("TELEGRAM_CHAT_ID", "")

    @property
    def telegram_admin_ids(self) -> str:
        """Дополнительные admin IDs через запятую: '123456789,987654321'"""
        return os.getenv("TELEGRAM_ADMIN_IDS", "")

    @property
    def telegram_invite_ttl_hours(self) -> int:
        """Срок действия инвайт-ссылки по умолчанию (часы)."""
        return int(os.getenv("TELEGRAM_INVITE_TTL_HOURS", "24"))

    # ── Bybit ─────────────────────────────────────────────────────────────────
    @property
    def bybit_api_key(self) -> str:
        return os.getenv("BYBIT_API_KEY", "")

    @property
    def bybit_api_secret(self) -> str:
        return os.getenv("BYBIT_API_SECRET", "")

    @property
    def bybit_testnet(self) -> bool:
        return os.getenv("BYBIT_TESTNET", "true").lower() == "true"

    # ── Почта ─────────────────────────────────────────────────────────────────
    @property
    def email_address(self) -> str:
        return os.getenv("EMAIL_ADDRESS", "")

    @property
    def email_password(self) -> str:
        return os.getenv("EMAIL_PASSWORD", "")

    @property
    def imap_server(self) -> str:
        return os.getenv("IMAP_SERVER", "imap.gmail.com")

    @property
    def imap_port(self) -> int:
        return int(os.getenv("IMAP_PORT", "993"))

    # ── Система ───────────────────────────────────────────────────────────────
    @property
    def log_level(self) -> str:
        return os.getenv("LOG_LEVEL", "INFO").upper()

    @property
    def max_parallel_agents(self) -> int:
        return int(os.getenv("MAX_PARALLEL_AGENTS", "5"))

    @property
    def agent_task_timeout(self) -> int:
        return int(os.getenv("AGENT_TASK_TIMEOUT", "120"))

    @property
    def master_password(self) -> str:
        return os.getenv("MASTER_PASSWORD", "")

    @property
    def trading_live_confirmed(self) -> bool:
        return os.getenv("TRADING_LIVE_CONFIRMED", "false").lower() == "true"

    @property
    def gui_theme(self) -> str:
        return os.getenv("GUI_THEME", "light")

    @property
    def gui_accent_color(self) -> str:
        return os.getenv("GUI_ACCENT_COLOR", "#2563EB")

    def ensure_dirs(self) -> None:
        for d in [
            self.DATA_DIR, self.LOGS_DIR,
            self.VECTOR_DIR, self.PROJECTS_DIR,
            self.DATA_DIR / "backups",
            self.DATA_DIR / "cache",
        ]:
            Path(d).mkdir(parents=True, exist_ok=True)

    def available_llm_providers(self) -> List[LLMProvider]:
        """Вернуть список провайдеров с настроенными ключами."""
        available = []
        if self.openai_api_key:
            available.append(LLMProvider.OPENAI)
        if self.claude_api_key:
            available.append(LLMProvider.CLAUDE)
        if self.gemini_api_key:
            available.append(LLMProvider.GEMINI)
        if self.grok_api_key:
            available.append(LLMProvider.GROK)
        if self.deepseek_api_key:
            available.append(LLMProvider.DEEPSEEK)
        if self.groq_api_key:
            available.append(LLMProvider.GROQ)
        if self.together_api_key:
            available.append(LLMProvider.TOGETHER)
        if self.mistral_api_key:
            available.append(LLMProvider.MISTRAL)
        if self.perplexity_api_key:
            available.append(LLMProvider.PERPLEXITY)
        available.append(LLMProvider.OLLAMA)  # всегда пробуем локальный
        return available


cfg = SystemConfig()
cfg.ensure_dirs()
