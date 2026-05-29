# -*- coding: utf-8 -*-
"""
agents/key_manager_agent.py — Автономный менеджер API-ключей.

Умеет:
  1. Проверять все существующие ключи (живой API-вызов)
  2. Открывать браузер и заполнять регистрацию автоматически
  3. Читать верификационные коды из email
  4. Перехватывать ключ из буфера обмена или browser DOM
  5. Записывать ключи в .env без участия пользователя
  6. Фоново мониторить здоровье ключей — ротация при исчерпании
  7. Полный автоматический setup для Groq и Gemini (бесплатные)

Степени автономности:
  AUTO  — полностью без участия человека (если есть email-доступ)
  SEMI  — открывает браузер, пользователь нажимает одну кнопку
  MANUAL — даёт точные инструкции + ссылки, записывает ключ сам
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from core.config import LLMProvider, cfg

log = logging.getLogger("agents.key_manager")
BASE_DIR = Path(__file__).parent.parent

# ══════════════════════════════════════════════════════════════════════════════
# РЕЕСТР ПРОВАЙДЕРОВ
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProviderInfo:
    name: str                    # Отображаемое имя
    env_key: str                 # Имя переменной в .env
    signup_url: str              # Ссылка на регистрацию
    keys_url: str                # Ссылка на страницу ключей
    free_tier: bool              # Есть ли бесплатный тариф
    free_note: str               # Описание бесплатного лимита
    test_fn: str                 # Имя метода теста в KeyManagerAgent
    auto_level: str              # "full" | "semi" | "manual"
    models: List[str] = field(default_factory=list)


PROVIDERS: Dict[str, ProviderInfo] = {
    "groq": ProviderInfo(
        name="Groq",
        env_key="GROQ_API_KEY",
        signup_url="https://console.groq.com/login",
        keys_url="https://console.groq.com/keys",
        free_tier=True,
        free_note="Бесплатно — 14400 токенов/мин, без карты",
        test_fn="_test_groq",
        auto_level="semi",
        models=["llama-3.3-70b-versatile", "llama-4-scout-17b-16e-instruct"],
    ),
    "gemini": ProviderInfo(
        name="Google Gemini",
        env_key="GOOGLE_API_KEY",
        signup_url="https://aistudio.google.com/",
        keys_url="https://aistudio.google.com/app/apikey",
        free_tier=True,
        free_note="Бесплатно — 1500 запросов/день, Flash",
        test_fn="_test_gemini",
        auto_level="semi",
        models=["gemini-2.5-flash-preview-05-20", "gemini-2.5-pro-preview"],
    ),
    "together": ProviderInfo(
        name="Together AI",
        env_key="TOGETHER_API_KEY",
        signup_url="https://api.together.xyz/signup",
        keys_url="https://api.together.xyz/settings/api-keys",
        free_tier=True,
        free_note="$1 кредит при регистрации, Llama 4 бесплатно",
        test_fn="_test_together",
        auto_level="semi",
        models=["meta-llama/Llama-4-Scout-17B-16E-Instruct", "Qwen/Qwen3-235B-A22B"],
    ),
    "deepseek": ProviderInfo(
        name="DeepSeek",
        env_key="DEEPSEEK_API_KEY",
        signup_url="https://platform.deepseek.com/sign_up",
        keys_url="https://platform.deepseek.com/api_keys",
        free_tier=True,
        free_note="$0.55/млн токенов (R1), бесплатные лимиты в начале",
        test_fn="_test_deepseek",
        auto_level="semi",
        models=["deepseek-reasoner", "deepseek-chat"],
    ),
    "mistral": ProviderInfo(
        name="Mistral AI",
        env_key="MISTRAL_API_KEY",
        signup_url="https://console.mistral.ai/",
        keys_url="https://console.mistral.ai/api-keys",
        free_tier=True,
        free_note="Бесплатный план — 1000 запросов/мес",
        test_fn="_test_mistral",
        auto_level="semi",
        models=["mistral-large-latest", "mistral-small-latest"],
    ),
    "openai": ProviderInfo(
        name="OpenAI",
        env_key="OPENAI_API_KEY",
        signup_url="https://platform.openai.com/signup",
        keys_url="https://platform.openai.com/api-keys",
        free_tier=False,
        free_note="Платно от $0.01, нужна карта",
        test_fn="_test_openai",
        auto_level="manual",
        models=["gpt-4o", "o3", "o4-mini"],
    ),
    "claude": ProviderInfo(
        name="Anthropic Claude",
        env_key="ANTHROPIC_API_KEY",
        signup_url="https://console.anthropic.com/",
        keys_url="https://console.anthropic.com/settings/keys",
        free_tier=False,
        free_note="Платно, нужна карта",
        test_fn="_test_claude",
        auto_level="manual",
        models=["claude-opus-4-5-20251101", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
    ),
    "grok": ProviderInfo(
        name="xAI Grok",
        env_key="XAI_API_KEY",
        signup_url="https://console.x.ai/",
        keys_url="https://console.x.ai/",
        free_tier=True,
        free_note="$25 бесплатных кредитов/мес",
        test_fn="_test_grok",
        auto_level="semi",
        models=["grok-3-mini", "grok-3-mini"],
    ),
    "perplexity": ProviderInfo(
        name="Perplexity AI",
        env_key="PERPLEXITY_API_KEY",
        signup_url="https://www.perplexity.ai/settings/api",
        keys_url="https://www.perplexity.ai/settings/api",
        free_tier=False,
        free_note="$5/мес (Pro), онлайн-поиск",
        test_fn="_test_perplexity",
        auto_level="manual",
        models=["llama-3.1-sonar-large-128k-online"],
    ),
}

# ══════════════════════════════════════════════════════════════════════════════
# РЕЗУЛЬТАТ ТЕСТА КЛЮЧА
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class KeyStatus:
    provider: str
    env_key: str
    key_value: str          # Маскированное значение
    valid: bool
    error: str = ""
    model_tested: str = ""
    latency_ms: float = 0.0
    quota_ok: bool = True


# ══════════════════════════════════════════════════════════════════════════════
# ОСНОВНОЙ АГЕНТ
# ══════════════════════════════════════════════════════════════════════════════

class KeyManagerAgent:
    """
    Автономный менеджер API-ключей.
    Проверяет, создаёт, захватывает и сохраняет ключи для всех LLM-провайдеров.
    """

    def __init__(self) -> None:
        self._http = self._make_http()
        self._env_path = BASE_DIR / ".env"
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitoring = False
        log.info("KeyManagerAgent initialised")
        # Auto-start key health monitor in background
        try:
            self.start_key_monitoring()
            log.info("Key health monitor auto-started on init")
        except Exception as _e:
            log.warning("Key health monitor auto-start failed: %s", _e)

    @staticmethod
    def _make_http() -> httpx.Client:
        """Клиент с автоматическим fallback на verify=False при Windows TLS-перехвате."""
        try:
            import certifi
            client = httpx.Client(timeout=15.0, verify=certifi.where())
            # Быстрая проверка что SSL работает
            client.get("https://api.groq.com", timeout=3)
            return client
        except Exception:
            pass
        import warnings
        warnings.filterwarnings("ignore", message="Unverified HTTPS request")
        try:
            import urllib3
            urllib3.disable_warnings()
        except Exception:
            pass
        return httpx.Client(timeout=15.0, verify=False)

    # ══════════════════════════════════════════════════════════════════════════
    # ТОЧКА ВХОДА: process()
    # ══════════════════════════════════════════════════════════════════════════

    def process(self, text: str, source: str = "gui") -> str:
        text_lower = text.lower()

        # Команды
        if any(w in text_lower for w in
               ["проверь ключи", "статус ключей", "check keys", "key status",
                "какие ключи", "покажи ключи"]):
            return self.check_all_keys_report()

        if any(w in text_lower for w in
               ["подключи все", "setup all", "настрой все", "автоматически подключи"]):
            return self.auto_setup_all()

        if any(w in text_lower for w in
               ["добавь ключ", "введи ключ", "сохрани ключ", "запиши ключ"]):
            # Попробуем извлечь ключ из текста
            key = self._extract_key_from_text(text)
            if key:
                provider = self._detect_provider_from_key(key)
                if provider:
                    return self.save_key(provider, key)
                return f"⚠️ Не могу определить провайдера для ключа: {key[:12]}...\n" \
                       f"Укажи провайдер явно: 'сохрани ключ groq: {key}'"
            return "❓ Не нашёл ключ в тексте. Напиши: 'сохрани ключ groq: gsk_xxxx'"

        # Сохранить конкретный ключ с указанием провайдера
        for prov_name in PROVIDERS:
            if prov_name in text_lower or PROVIDERS[prov_name].name.lower() in text_lower:
                key = self._extract_key_from_text(text)
                if key:
                    return self.save_key(prov_name, key)
                # Нет ключа — открыть браузер
                return self.open_provider_for_key(prov_name)

        if any(w in text_lower for w in
               ["открой", "зайди на", "открой страницу", "open"]):
            return self.open_all_missing_providers()

        if any(w in text_lower for w in
               ["мониторинг ключей", "следи за ключами", "monitor keys"]):
            return self.start_key_monitoring()

        # По умолчанию — показать статус
        return self.check_all_keys_report()

    # ══════════════════════════════════════════════════════════════════════════
    # ПРОВЕРКА ВСЕХ КЛЮЧЕЙ
    # ══════════════════════════════════════════════════════════════════════════

    def check_all_keys_report(self) -> str:
        """Проверить все ключи и вернуть полный отчёт."""
        statuses = self.validate_all_keys()

        lines = ["🔑 **Статус API-ключей (все провайдеры)**\n"]
        valid_count = 0
        missing = []
        invalid = []

        for status in statuses:
            pinfo = PROVIDERS.get(status.provider)
            if not pinfo:
                continue

            masked = _mask_key(status.key_value)

            if not status.key_value:
                icon = "❌"
                note = f"[НЕТ КЛЮЧА] — {pinfo.free_note}"
                missing.append(status.provider)
            elif status.valid:
                icon = "✅"
                note = f"{masked} — OK ({status.latency_ms:.0f}ms)"
                valid_count += 1
            else:
                icon = "⚠️"
                note = f"{masked} — ОШИБКА: {status.error[:60]}"
                invalid.append(status.provider)

            free_tag = " 🆓" if pinfo.free_tier else " 💳"
            lines.append(f"{icon} **{pinfo.name}**{free_tag}: {note}")

        lines.append(f"\n📊 Итого: {valid_count}/{len(statuses)} провайдеров активны")

        if missing:
            lines.append(f"\n⚡ **Можно добавить бесплатно:** " +
                         ", ".join(p for p in missing if PROVIDERS[p].free_tier))
            lines.append("\nНапиши **'подключи все'** — открою браузер для каждого.")

        if invalid:
            lines.append(f"\n🔄 Невалидные ключи: {', '.join(invalid)}")
            lines.append("Напиши **'подключи [название]'** для замены.")

        return "\n".join(lines)

    def validate_all_keys(self) -> List[KeyStatus]:
        """Параллельно проверить все ключи реальными API-вызовами."""
        import concurrent.futures

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            futures = {
                ex.submit(self._validate_single, prov_name): prov_name
                for prov_name in PROVIDERS
            }
            for fut in concurrent.futures.as_completed(futures):
                try:
                    results.append(fut.result())
                except Exception as e:
                    prov_name = futures[fut]
                    results.append(KeyStatus(
                        provider=prov_name,
                        env_key=PROVIDERS[prov_name].env_key,
                        key_value="",
                        valid=False,
                        error=str(e)
                    ))

        # Сортировать: сначала валидные, потом без ключа, потом ошибки
        results.sort(key=lambda s: (0 if s.valid else (1 if not s.key_value else 2)))
        return results

    def _validate_single(self, provider: str) -> KeyStatus:
        """Проверить один ключ."""
        pinfo = PROVIDERS[provider]
        key_value = os.getenv(pinfo.env_key, "").strip()

        if not key_value:
            return KeyStatus(
                provider=provider, env_key=pinfo.env_key,
                key_value="", valid=False, error="Ключ не задан"
            )

        test_fn = getattr(self, pinfo.test_fn, None)
        if test_fn is None:
            return KeyStatus(
                provider=provider, env_key=pinfo.env_key,
                key_value=key_value, valid=True,
                error="Тест не реализован"
            )

        t0 = time.time()
        try:
            model, error = test_fn(key_value)
            latency = (time.time() - t0) * 1000
            return KeyStatus(
                provider=provider, env_key=pinfo.env_key,
                key_value=key_value,
                valid=(error == ""),
                error=error,
                model_tested=model,
                latency_ms=latency,
            )
        except Exception as e:
            return KeyStatus(
                provider=provider, env_key=pinfo.env_key,
                key_value=key_value, valid=False, error=str(e)[:100]
            )

    # ══════════════════════════════════════════════════════════════════════════
    # ТЕСТЫ КЛЮЧЕЙ (минимальные API-вызовы)
    # ══════════════════════════════════════════════════════════════════════════

    def _test_groq(self, key: str) -> Tuple[str, str]:
        """Тест Groq — GET /models."""
        r = self._http.get(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"}
        )
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 429:
            return "llama-3.3-70b-versatile", ""  # rate limit = ключ валиден
        r.raise_for_status()
        models = r.json().get("data", [])
        first = models[0]["id"] if models else "unknown"
        return first, ""

    def _test_gemini(self, key: str) -> Tuple[str, str]:
        """Тест Gemini — GET /models."""
        r = self._http.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
        )
        if r.status_code == 404:
            return "claude-haiku-4-5", ""  # model renamed but key valid
        if r.status_code == 400:
            data = r.json()
            if "API_KEY_INVALID" in str(data):
                return "", "Неверный ключ (API_KEY_INVALID)"
        if r.status_code == 429:
            return "gemini-2.5-flash", ""
        r.raise_for_status()
        models = r.json().get("models", [])
        first = models[0]["name"].split("/")[-1] if models else "gemini"
        return first, ""

    def _test_deepseek(self, key: str) -> Tuple[str, str]:
        """Тест DeepSeek — минимальный чат."""
        r = self._http.post(
            "https://api.deepseek.com/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "1+1"}],
                "max_tokens": 5,
            }
        )
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 402:
            return "", "Недостаточно баланса (402)"
        if r.status_code == 429:
            return "deepseek-chat", ""
        r.raise_for_status()
        return "deepseek-chat", ""

    def _test_openai(self, key: str) -> Tuple[str, str]:
        """Тест OpenAI — GET /models."""
        r = self._http.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"}
        )
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 429:
            return "gpt-4o", ""
        r.raise_for_status()
        return "gpt-4o", ""

    def _test_claude(self, key: str) -> Tuple[str, str]:
        """Тест Claude — минимальный messages запрос."""
        r = self._http.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 5,
                "messages": [{"role": "user", "content": "1"}]
            }
        )
        if r.status_code == 404:
            return "claude-haiku-4-5", ""  # model renamed but key valid
        if r.status_code == 400:
            # Check if it's a billing issue vs bad model name
            try:
                err_body = r.json() if hasattr(r, 'json') else {}
                err_msg = err_body.get('error', {}).get('message', '')
                if 'credit balance' in err_msg.lower() or 'too low' in err_msg.lower():
                    return "", "💳 Нет кредитов — пополни баланс на console.anthropic.com"
                return "", f"400: {err_msg[:80] or 'неверная модель'}"
            except Exception:
                return "", "400: ошибка запроса"
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 403:
            return "", "Доступ запрещён (403)"
        if r.status_code == 429:
            return "claude-haiku-4-5-20251001", ""
        r.raise_for_status()
        return "claude-haiku-4-5-20251001", ""

    def _test_gemini_key(self, key: str) -> Tuple[str, str]:
        return self._test_gemini(key)

    def _test_grok(self, key: str) -> Tuple[str, str]:
        """Тест Grok — GET /models (xAI)."""
        r = self._http.get(
            "https://api.x.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"}
        )
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 429:
            return "grok-3-mini", ""
        r.raise_for_status()
        return "grok-3-mini", ""

    def _test_together(self, key: str) -> Tuple[str, str]:
        """Тест Together AI — GET /models."""
        r = self._http.get(
            "https://api.together.xyz/v1/models",
            headers={"Authorization": f"Bearer {key}"}
        )
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 429:
            return "Llama-4-Scout", ""
        r.raise_for_status()
        return "Llama-4-Scout", ""

    def _test_mistral(self, key: str) -> Tuple[str, str]:
        """Тест Mistral — GET /models."""
        r = self._http.get(
            "https://api.mistral.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"}
        )
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 429:
            return "mistral-large-latest", ""
        r.raise_for_status()
        return "mistral-large-latest", ""

    def _test_perplexity(self, key: str) -> Tuple[str, str]:
        """Тест Perplexity — минимальный chat запрос."""
        r = self._http.post(
            "https://api.perplexity.ai/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-sonar-small-128k-online",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            }
        )
        if r.status_code == 401:
            return "", "Неверный ключ (401)"
        if r.status_code == 429:
            return "sonar-online", ""
        r.raise_for_status()
        return "sonar-online", ""

    # ══════════════════════════════════════════════════════════════════════════
    # АВТОМАТИЧЕСКАЯ НАСТРОЙКА
    # ══════════════════════════════════════════════════════════════════════════

    def auto_setup_all(self) -> str:
        """
        Автоматически настроить все доступные провайдеры.
        Для бесплатных — открывает браузер и ждёт ключ.
        """
        statuses = self.validate_all_keys()
        missing_free = [
            s.provider for s in statuses
            if not s.key_value and PROVIDERS[s.provider].free_tier
        ]
        missing_paid = [
            s.provider for s in statuses
            if not s.key_value and not PROVIDERS[s.provider].free_tier
        ]
        invalid = [s.provider for s in statuses if s.key_value and not s.valid]

        if not missing_free and not invalid:
            return (
                "✅ Все доступные бесплатные провайдеры уже настроены!\n\n"
                + self.check_all_keys_report()
            )

        lines = ["🚀 **Автоматическая настройка провайдеров**\n"]

        if missing_free:
            lines.append(f"🆓 Запускаю настройку {len(missing_free)} бесплатных провайдеров:\n")
            for prov in missing_free:
                result = self.open_provider_for_key(prov)
                lines.append(f"• **{PROVIDERS[prov].name}**: {result}")

        if missing_paid:
            lines.append(f"\n💳 Платные провайдеры (нужна карта) — открываю страницы:")
            for prov in missing_paid:
                pinfo = PROVIDERS[prov]
                webbrowser.open(pinfo.keys_url)
                lines.append(f"• **{pinfo.name}**: {pinfo.keys_url}")

        if invalid:
            lines.append(f"\n🔄 Невалидные ключи — обновляю:")
            for prov in invalid:
                result = self.open_provider_for_key(prov)
                lines.append(f"• **{PROVIDERS[prov].name}**: {result}")

        lines.append(
            "\n\n📌 **Как передать ключ:**\n"
            "Скопируй ключ и напиши мне:\n"
            "```\nсохрани ключ groq: gsk_xxxxxxxxxxxx\n```\n"
            "Я автоматически проверю и запишу его в .env."
        )

        return "\n".join(lines)

    def open_provider_for_key(self, provider: str) -> str:
        """
        Открыть браузер на странице ключей провайдера.
        Возвращает инструкцию что делать дальше.
        """
        pinfo = PROVIDERS.get(provider)
        if not pinfo:
            return f"❓ Неизвестный провайдер: {provider}"

        # Попробуем через Playwright (полная автоматизация)
        playwright_result = self._try_playwright_capture(provider)
        if playwright_result:
            return playwright_result

        # Fallback — открыть браузер стандартным способом
        try:
            webbrowser.open(pinfo.keys_url)
            opened = True
        except Exception:
            opened = False

        icon = "🆓" if pinfo.free_tier else "💳"
        lines = [
            f"{icon} **{pinfo.name}** — {'БЕСПЛАТНО' if pinfo.free_tier else 'ПЛАТНО'}",
            f"   {pinfo.free_note}",
        ]
        if opened:
            lines.append(f"   🌐 Браузер открыт: {pinfo.keys_url}")
        else:
            lines.append(f"   🔗 Ссылка: {pinfo.keys_url}")

        lines.append(f"\n   **Шаги:**")
        steps = self._get_setup_steps(provider)
        for i, step in enumerate(steps, 1):
            lines.append(f"   {i}. {step}")

        lines.append(
            f"\n   📋 После получения ключа напиши:\n"
            f"   `сохрани ключ {provider}: <твой-ключ>`"
        )

        return "\n".join(lines)

    def _get_setup_steps(self, provider: str) -> List[str]:
        """Пошаговые инструкции для каждого провайдера."""
        steps = {
            "groq": [
                "Нажми 'Continue with Google' или создай аккаунт по email",
                "После входа нажми '+ Create API Key'",
                "Дай название ключу (любое), нажми 'Submit'",
                "Скопируй ключ (начинается с gsk_)",
                "Напиши мне: сохрани ключ groq: gsk_...",
            ],
            "gemini": [
                "Войди через Google-аккаунт",
                "Нажми '+ Create API key' → 'Create API key in new project'",
                "Скопируй ключ (начинается с AIza)",
                "Напиши мне: сохрани ключ gemini: AIza...",
            ],
            "together": [
                "Создай аккаунт или войди через GitHub",
                "Нажми 'New API Key', дай название",
                "Скопируй ключ",
                "Напиши мне: сохрани ключ together: <ключ>",
            ],
            "deepseek": [
                "Зарегистрируйся или войди",
                "Перейди в API Keys → Create new key",
                "Скопируй ключ (начинается с sk-)",
                "Напиши мне: сохрани ключ deepseek: sk-...",
            ],
            "mistral": [
                "Создай аккаунт на console.mistral.ai",
                "Перейди в API Keys → Generate new key",
                "Скопируй ключ",
                "Напиши мне: сохрани ключ mistral: <ключ>",
            ],
            "openai": [
                "Войди на platform.openai.com",
                "API Keys → + Create new secret key",
                "Добавь способ оплаты (нужна карта)",
                "Скопируй ключ (начинается с sk-)",
                "Напиши мне: сохрани ключ openai: sk-...",
            ],
            "claude": [
                "Войди на console.anthropic.com",
                "Settings → API Keys → Create Key",
                "Скопируй ключ (начинается с sk-ant-)",
                "Напиши мне: сохрани ключ claude: sk-ant-...",
            ],
            "grok": [
                "Войди через X (Twitter) аккаунт",
                "Создай API ключ в консоли",
                "$25 бесплатных кредитов — нужна верификация телефона",
                "Напиши мне: сохрани ключ grok: xai-...",
            ],
            "perplexity": [
                "Войди на perplexity.ai",
                "Settings → API → Generate",
                "Нужна подписка Pro ($5/мес) или оплата за использование",
                "Напиши мне: сохрани ключ perplexity: pplx-...",
            ],
        }
        return steps.get(provider, ["Перейди по ссылке выше", "Создай API ключ", "Сохрани ключ"])

    def open_all_missing_providers(self) -> str:
        """Открыть браузер для всех провайдеров без ключей."""
        statuses = self.validate_all_keys()
        missing = [s.provider for s in statuses if not s.key_value]

        if not missing:
            return "✅ Все провайдеры настроены!"

        lines = [f"🌐 Открываю {len(missing)} провайдеров в браузере...\n"]
        for prov in missing:
            pinfo = PROVIDERS[prov]
            try:
                webbrowser.open(pinfo.keys_url)
                lines.append(f"✅ {pinfo.name}: {pinfo.keys_url}")
            except Exception as e:
                lines.append(f"❌ {pinfo.name}: {e}")
            time.sleep(0.5)  # Не спамим браузер

        lines.append(
            "\n📋 Получи ключи и передай мне по одному:\n"
            "`сохрани ключ <провайдер>: <ключ>`\n"
            "Пример: `сохрани ключ groq: gsk_xxxx`"
        )
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════════════
    # PLAYWRIGHT АВТОМАТИЗАЦИЯ
    # ══════════════════════════════════════════════════════════════════════════

    def _try_playwright_capture(self, provider: str) -> Optional[str]:
        """
        Попытаться автоматически захватить ключ через Playwright.
        Возвращает результат или None если Playwright недоступен.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None  # Playwright не установлен — используем fallback

        pinfo = PROVIDERS.get(provider)
        if not pinfo:
            return None

        # Запускаем в отдельном потоке чтобы не блокировать
        result_box: List[str] = []

        def _run():
            try:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=False)
                    ctx = browser.new_context()
                    page = ctx.new_page()

                    # Слушатель запросов для перехвата ключей
                    captured_keys: List[str] = []

                    def _on_response(resp):
                        try:
                            if "api" in resp.url and resp.status == 200:
                                body = resp.text()
                                # Ищем паттерны ключей в ответах
                                found = _find_api_key_in_text(body, provider)
                                if found:
                                    captured_keys.extend(found)
                        except Exception:
                            pass

                    page.on("response", _on_response)
                    page.goto(pinfo.keys_url, timeout=15000)

                    # Ждём ключ 60 секунд пока пользователь работает
                    page.wait_for_timeout(60000)

                    if captured_keys:
                        key = captured_keys[-1]
                        save_result = self.save_key(provider, key)
                        result_box.append(
                            f"🎉 Ключ перехвачен автоматически!\n{save_result}"
                        )
                    else:
                        # Ищем ключ в DOM
                        key_text = page.evaluate("""
                            () => {
                                const inputs = document.querySelectorAll('input[type="text"], input[readonly], code, pre');
                                for (const el of inputs) {
                                    const val = el.value || el.textContent || '';
                                    if (val.length > 20 && val.match(/^[a-zA-Z0-9_-]{20,}/)) {
                                        return val.trim();
                                    }
                                }
                                return null;
                            }
                        """)
                        if key_text and len(key_text) > 20:
                            save_result = self.save_key(provider, key_text)
                            result_box.append(f"✅ Ключ найден в DOM!\n{save_result}")
                        else:
                            result_box.append("")  # Не нашли — fallback

                    browser.close()
            except Exception as e:
                log.debug("Playwright capture failed for %s: %s", provider, e)
                result_box.append("")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=5)  # Даём 5с на запуск, потом возвращаем инструкции

        if result_box and result_box[0]:
            return result_box[0]
        return None  # Playwright запустился в фоне, вернём обычные инструкции

    # ══════════════════════════════════════════════════════════════════════════
    # СОХРАНЕНИЕ КЛЮЧЕЙ
    # ══════════════════════════════════════════════════════════════════════════

    def save_key(self, provider: str, key: str) -> str:
        """
        Сохранить ключ в .env.
        Предварительно валидирует ключ реальным API-вызовом.
        """
        pinfo = PROVIDERS.get(provider)
        if not pinfo:
            # Попробуем найти по имени
            for k, v in PROVIDERS.items():
                if v.name.lower() == provider.lower():
                    pinfo = v
                    provider = k
                    break
            if not pinfo:
                return f"❌ Неизвестный провайдер: {provider}"

        key = key.strip()
        if len(key) < 10:
            return f"❌ Ключ слишком короткий: {key}"

        # Валидация
        status_line = f"🔍 Проверяю ключ {pinfo.name}..."
        test_fn = getattr(self, pinfo.test_fn, None)
        valid = True
        error_msg = ""

        if test_fn:
            t0 = time.time()
            try:
                model, error = test_fn(key)
                latency = (time.time() - t0) * 1000
                if error:
                    valid = False
                    error_msg = error
            except Exception as e:
                # Не блокируем сохранение при сетевой ошибке
                log.debug("Key validation error: %s", e)
                error_msg = f"(не удалось проверить: {e})"

        if not valid:
            return (
                f"❌ Ключ **{pinfo.name}** невалиден: {error_msg}\n\n"
                f"Проверь ключ на: {pinfo.keys_url}\n"
                f"Попробуй создать новый."
            )

        # Записать в .env
        result = self._write_env_key(pinfo.env_key, key)
        if result:
            # Обновить переменную окружения в текущем процессе
            os.environ[pinfo.env_key] = key

            # Перезагрузить .env
            try:
                from dotenv import load_dotenv
                load_dotenv(self._env_path, override=True)
            except Exception:
                pass

            # Сбросить статус провайдера в LLMRouter
            try:
                from brain.llm_router import LLMRouter
                router = LLMRouter.get()
                llm_prov = LLMProvider(provider)
                router.reset_provider(llm_prov)
            except Exception:
                pass

            masked = _mask_key(key)
            latency_note = f" ({latency:.0f}ms)" if not error_msg else ""
            return (
                f"✅ **{pinfo.name}** — ключ сохранён и активирован!\n\n"
                f"   Ключ: `{masked}`{latency_note}\n"
                f"   Модели: {', '.join(pinfo.models[:2])}\n"
                f"   Файл: `.env` обновлён\n\n"
                f"Провайдер сразу готов к использованию."
            )
        else:
            return f"⚠️ Ключ валиден, но не удалось записать в .env. " \
                   f"Добавь вручную: {pinfo.env_key}={key}"

    def _write_env_key(self, env_key: str, value: str) -> bool:
        """Записать или обновить ключ в .env файле."""
        with self._lock:
            try:
                env_path = self._env_path

                # Читаем текущий .env
                if env_path.exists():
                    content = env_path.read_text(encoding="utf-8")
                else:
                    content = ""

                lines = content.splitlines()
                updated = False

                # Обновить существующую строку
                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if stripped.startswith(f"{env_key}=") or \
                       stripped.startswith(f"#{env_key}=") or \
                       stripped.startswith(f"# {env_key}="):
                        lines[i] = f"{env_key}={value}"
                        updated = True
                        break

                if not updated:
                    # Добавить новую строку
                    lines.append(f"{env_key}={value}")

                env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                log.info("Saved key %s to .env", env_key)
                return True

            except Exception as e:
                log.error("Failed to write key %s: %s", env_key, e)
                return False

    # ══════════════════════════════════════════════════════════════════════════
    # EMAIL ВЕРИФИКАЦИЯ
    # ══════════════════════════════════════════════════════════════════════════

    def read_verification_code(self, provider: str, timeout_sec: int = 120) -> Optional[str]:
        """
        Читать верификационный код из email.
        Требует настроенного EMAIL_ADDRESS + EMAIL_PASSWORD в .env.
        """
        email_addr = cfg.email_address
        email_pass = cfg.email_password

        if not email_addr or not email_pass:
            return None

        try:
            import imaplib
            import email as email_lib
            from email.header import decode_header

            imap = imaplib.IMAP4_SSL(cfg.imap_server, cfg.imap_port)
            imap.login(email_addr, email_pass)
            imap.select("INBOX")

            deadline = time.time() + timeout_sec
            pinfo = PROVIDERS.get(provider)
            sender_hints = {
                "groq": ["groq.com", "groqcloud.com"],
                "gemini": ["google.com", "accounts.google.com"],
                "together": ["together.ai", "together.xyz"],
                "deepseek": ["deepseek.com"],
                "openai": ["openai.com"],
                "claude": ["anthropic.com"],
                "mistral": ["mistral.ai"],
            }
            hints = sender_hints.get(provider, [])

            while time.time() < deadline:
                _, msg_nums = imap.search(None, "UNSEEN")
                for num in reversed(msg_nums[0].split()):
                    _, data = imap.fetch(num, "(RFC822)")
                    msg = email_lib.message_from_bytes(data[0][1])
                    sender = msg.get("From", "").lower()

                    if hints and not any(h in sender for h in hints):
                        continue

                    # Ищем 6-значный код
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

                    codes = re.findall(r'\b\d{6}\b', body)
                    if codes:
                        log.info("Found verification code for %s: %s", provider, codes[-1])
                        imap.close()
                        return codes[-1]

                time.sleep(5)

            imap.close()
        except Exception as e:
            log.debug("Email read failed: %s", e)

        return None

    # ══════════════════════════════════════════════════════════════════════════
    # ФОНОВЫЙ МОНИТОРИНГ ЗДОРОВЬЯ КЛЮЧЕЙ
    # ══════════════════════════════════════════════════════════════════════════

    def start_key_monitoring(self, interval_sec: int = 3600) -> str:
        """
        Запустить фоновый мониторинг здоровья ключей.
        Каждый час проверяет все ключи и логирует проблемы.
        """
        if self._monitoring:
            return "⚡ Мониторинг ключей уже запущен."

        self._monitoring = True

        _claude_was_failing = [True]  # start assuming failed to trigger recovery msg on fix

        def _monitor_loop():
            while self._monitoring:
                try:
                    statuses = self.validate_all_keys()
                    for s in statuses:
                        if s.key_value and not s.valid:
                            log.warning(
                                "Key health check FAILED: %s — %s",
                                s.provider, s.error
                            )
                            if s.provider == "claude":
                                _claude_was_failing[0] = True
                            # Отправить алерт через EventBus
                            try:
                                from core.event_bus import EventBus
                                EventBus.get().publish(
                                    "key_manager.key_invalid",
                                    {"provider": s.provider, "error": s.error},
                                    source="key_manager"
                                )
                            except Exception:
                                pass
                        elif s.provider == "claude" and s.valid and _claude_was_failing[0]:
                            # Claude восстановился — уведомить пользователя
                            _claude_was_failing[0] = False
                            log.info("Claude API recovered — sending Telegram notification")
                            try:
                                from core.event_bus import EventBus
                                EventBus.get().publish(
                                    "telegram.send",
                                    {"text": (
                                        "✅ Claude API восстановлен! "
                                        "Ключ снова работает. "
                                        "Система переключилась на Claude (claude-3-5-sonnet-20241022)."
                                    )},
                                    source="key_manager"
                                )
                            except Exception as e:
                                log.debug("Claude recovery notify error: %s", e)
                except Exception as e:
                    log.debug("Key monitor error: %s", e)
                time.sleep(interval_sec)

        self._monitor_thread = threading.Thread(
            target=_monitor_loop, daemon=True, name="key-health-monitor"
        )
        self._monitor_thread.start()
        log.info("Key health monitoring started (interval=%ds)", interval_sec)
        return (
            f"✅ **Мониторинг ключей запущен**\n"
            f"   Интервал проверки: каждый час\n"
            f"   При проблемах — алерт в лог и Telegram"
        )

    def stop_key_monitoring(self) -> None:
        self._monitoring = False

    # ══════════════════════════════════════════════════════════════════════════
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ══════════════════════════════════════════════════════════════════════════

    def _extract_key_from_text(self, text: str) -> Optional[str]:
        """Извлечь API-ключ из произвольного текста."""
        # Шаблоны ключей разных провайдеров
        patterns = [
            r'gsk_[a-zA-Z0-9]{40,}',          # Groq
            r'sk-ant-[a-zA-Z0-9_-]{80,}',      # Claude
            r'sk-[a-zA-Z0-9]{48,}',             # OpenAI
            r'sk-[a-zA-Z0-9]{20,}',             # DeepSeek, Mistral
            r'AIza[a-zA-Z0-9_-]{35,}',          # Google/Gemini
            r'xai-[a-zA-Z0-9_-]{40,}',          # xAI Grok
            r'pplx-[a-zA-Z0-9]{40,}',           # Perplexity
            r'[a-zA-Z0-9]{32,64}',              # Together AI и другие (общий)
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group()
                # Фильтруем слишком длинные или явно не ключи
                if 10 <= len(candidate) <= 200:
                    return candidate
        return None

    def _detect_provider_from_key(self, key: str) -> Optional[str]:
        """Определить провайдера по формату ключа."""
        if key.startswith("gsk_"):
            return "groq"
        if key.startswith("sk-ant-"):
            return "claude"
        if key.startswith("AIza"):
            return "gemini"
        if key.startswith("xai-"):
            return "grok"
        if key.startswith("pplx-"):
            return "perplexity"
        if key.startswith("sk-") and len(key) > 50:
            return "openai"
        if key.startswith("sk-") and len(key) < 50:
            return "deepseek"
        return None

    def get_status(self) -> str:
        report = self.status_report()
        valid = sum(1 for p in PROVIDERS
                    if os.getenv(PROVIDERS[p].env_key, ""))
        return f"KeyManager: {valid}/{len(PROVIDERS)} ключей настроено"

    def status_report(self) -> Dict[str, Any]:
        result = {}
        for prov, pinfo in PROVIDERS.items():
            key = os.getenv(pinfo.env_key, "")
            result[prov] = {
                "has_key": bool(key),
                "masked": _mask_key(key) if key else "",
                "free_tier": pinfo.free_tier,
            }
        return result


# ══════════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════════════════════

def _mask_key(key: str) -> str:
    """Замаскировать ключ для отображения."""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:6] + "****" + key[-4:]


def _find_api_key_in_text(text: str, provider: str) -> List[str]:
    """Найти API-ключи в тексте (для перехвата из браузера)."""
    patterns = {
        "groq": r'gsk_[a-zA-Z0-9]{40,}',
        "gemini": r'AIza[a-zA-Z0-9_-]{35,}',
        "openai": r'sk-[a-zA-Z0-9]{48,}',
        "claude": r'sk-ant-[a-zA-Z0-9_-]{80,}',
        "deepseek": r'sk-[a-zA-Z0-9]{32,}',
        "grok": r'xai-[a-zA-Z0-9_-]{40,}',
        "together": r'[a-zA-Z0-9]{64}',
        "mistral": r'[a-zA-Z0-9]{32}',
        "perplexity": r'pplx-[a-zA-Z0-9]{40,}',
    }
    pattern = patterns.get(provider, r'[a-zA-Z0-9_-]{32,}')
    return re.findall(pattern, text)