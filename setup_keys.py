# -*- coding: utf-8 -*-
"""
setup_keys.py — Автоматическое получение API-ключей через браузер.

Запуск:
    python setup_keys.py              # все провайдеры
    python setup_keys.py --provider groq gemini together
    python setup_keys.py --check      # только проверить существующие ключи

Как работает:
  1. Открывает твой Chrome (с твоими сессиями — Google, GitHub, etc.)
  2. Заходит на страницу ключей каждого провайдера
  3. Кликает «Create key», дожидается генерации
  4. Автоматически перехватывает ключ из DOM / буфера обмена
  5. Сохраняет в .env и активирует в текущем процессе
  6. Переходит к следующему

Полностью автоматически (без участия):
  ✅ Groq        — если залогинен в Google/GitHub в Chrome
  ✅ Google Gemini — если залогинен в Google в Chrome
  ✅ Together AI  — если залогинен в GitHub в Chrome
  ✅ Mistral AI   — регистрация через GitHub
  ⚡ Grok (xAI)  — нужен X.com аккаунт
  ⚡ DeepSeek    — нужна регистрация
  ⚡ OpenAI      — нужна карта
  ⚡ Claude      — нужна карта
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import threading
from pathlib import Path

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── Инициализация .env ────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

ENV_PATH = BASE_DIR / ".env"


def _p(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode(), flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# КОНФИГ ПРОВАЙДЕРОВ
# ══════════════════════════════════════════════════════════════════════════════

PROVIDERS_CONFIG = {
    "groq": {
        "name": "Groq",
        "env_key": "GROQ_API_KEY",
        "keys_url": "https://console.groq.com/keys",
        "login_url": "https://console.groq.com/login",
        "free": True,
        "key_pattern": r'gsk_[a-zA-Z0-9]{40,80}',
        "create_button": ["Create API Key", "New API Key", "+ Create"],
        "key_selectors": [
            "input[readonly]",
            "input[type='text'][value*='gsk_']",
            "code",
            ".api-key",
            "[data-testid='api-key']",
        ],
    },
    "gemini": {
        "name": "Google Gemini",
        "env_key": "GOOGLE_API_KEY",
        "keys_url": "https://aistudio.google.com/app/apikey",
        "login_url": "https://aistudio.google.com/",
        "free": True,
        "key_pattern": r'AIza[a-zA-Z0-9_-]{35,45}',
        "create_button": ["Create API key", "Get API key", "Create API key in new project"],
        "key_selectors": [
            "input[readonly]",
            "[aria-label*='API key']",
            ".api-key-value",
            "code",
        ],
    },
    "together": {
        "name": "Together AI",
        "env_key": "TOGETHER_API_KEY",
        "keys_url": "https://api.together.xyz/settings/api-keys",
        "login_url": "https://api.together.xyz/signin",
        "free": True,
        "key_pattern": r'[a-zA-Z0-9]{64,}',
        "create_button": ["New API Key", "Create key", "Generate"],
        "key_selectors": [
            "input[readonly]",
            "input[type='text']",
            ".token-display",
            "code",
        ],
    },
    "mistral": {
        "name": "Mistral AI",
        "env_key": "MISTRAL_API_KEY",
        "keys_url": "https://console.mistral.ai/api-keys",
        "login_url": "https://console.mistral.ai/",
        "free": True,
        "key_pattern": r'[a-zA-Z0-9]{32,}',
        "create_button": ["Generate new key", "Create key", "New API key"],
        "key_selectors": [
            "input[readonly]",
            ".api-key",
            "[data-key]",
            "code",
        ],
    },
    "grok": {
        "name": "xAI Grok",
        "env_key": "XAI_API_KEY",
        "keys_url": "https://console.x.ai/",
        "login_url": "https://console.x.ai/",
        "free": True,
        "key_pattern": r'xai-[a-zA-Z0-9_-]{40,}',
        "create_button": ["Create API Key", "New Key", "Generate"],
        "key_selectors": [
            "input[readonly]",
            "input[type='password']",
            ".key-display",
            "code",
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "env_key": "DEEPSEEK_API_KEY",
        "keys_url": "https://platform.deepseek.com/api_keys",
        "login_url": "https://platform.deepseek.com/sign_in",
        "free": True,
        "key_pattern": r'sk-[a-zA-Z0-9]{32,}',
        "create_button": ["Create new API key", "New key", "Create"],
        "key_selectors": [
            "input[readonly]",
            ".api-key",
            "code",
            "[class*='key']",
        ],
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# ЗАПИСЬ В .ENV
# ══════════════════════════════════════════════════════════════════════════════

def write_env_key(env_key: str, value: str) -> bool:
    """Записать или обновить ключ в .env."""
    try:
        content = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
        lines = content.splitlines()
        updated = False
        for i, line in enumerate(lines):
            stripped = line.strip().lstrip("#").strip()
            if stripped.startswith(f"{env_key}="):
                lines[i] = f"{env_key}={value}"
                updated = True
                break
        if not updated:
            lines.append(f"{env_key}={value}")
        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ[env_key] = value
        return True
    except Exception as e:
        _p(f"  ⚠️ Не удалось записать {env_key}: {e}")
        return False


def mask(key: str) -> str:
    return key[:6] + "****" + key[-4:] if len(key) > 12 else "****"


# ══════════════════════════════════════════════════════════════════════════════
# ВАЛИДАЦИЯ КЛЮЧЕЙ (реальный API-вызов)
# ══════════════════════════════════════════════════════════════════════════════

def validate_key(provider: str, key: str) -> bool:
    """Проверить ключ реальным минимальным вызовом."""
    import httpx
    try:
        client = httpx.Client(timeout=10.0, verify=False)
        tests = {
            "groq": lambda k: client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {k}"}
            ).status_code in (200, 429),
            "gemini": lambda k: client.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={k}"
            ).status_code in (200, 429),
            "together": lambda k: client.get(
                "https://api.together.xyz/v1/models",
                headers={"Authorization": f"Bearer {k}"}
            ).status_code in (200, 429),
            "mistral": lambda k: client.get(
                "https://api.mistral.ai/v1/models",
                headers={"Authorization": f"Bearer {k}"}
            ).status_code in (200, 429),
            "grok": lambda k: client.get(
                "https://api.x.ai/v1/models",
                headers={"Authorization": f"Bearer {k}"}
            ).status_code in (200, 429),
            "deepseek": lambda k: client.post(
                "https://api.deepseek.com/chat/completions",
                headers={"Authorization": f"Bearer {k}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "1"}], "max_tokens": 1}
            ).status_code in (200, 429),
        }
        fn = tests.get(provider)
        return fn(key) if fn else True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════════════
# PLAYWRIGHT АВТОМАТИЗАЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

def get_chrome_user_data_dir() -> str:
    """Найти папку профиля Chrome на Windows/Mac/Linux."""
    import platform
    system = platform.system()
    home = Path.home()
    candidates = []
    if system == "Windows":
        candidates = [
            home / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
            home / "AppData" / "Local" / "Google" / "Chrome Beta" / "User Data",
            home / "AppData" / "Local" / "BraveSoftware" / "Brave-Browser" / "User Data",
        ]
    elif system == "Darwin":
        candidates = [
            home / "Library" / "Application Support" / "Google" / "Chrome",
        ]
    else:
        candidates = [
            home / ".config" / "google-chrome",
            home / ".config" / "chromium",
        ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def setup_provider_playwright(provider: str, config: dict, headless: bool = False) -> str:
    """
    Автоматически получить ключ провайдера через Playwright.
    Использует существующий Chrome-профиль пользователя.
    Возвращает ключ или пустую строку.
    """
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        return ""

    user_data_dir = get_chrome_user_data_dir()
    key_pattern = config["key_pattern"]
    captured_key = [None]

    def _find_key_in_text(text: str) -> str:
        matches = re.findall(key_pattern, text)
        return matches[-1] if matches else ""

    _p(f"  🌐 Playwright: открываю {config['name']} ({config['keys_url']})")

    try:
        with sync_playwright() as pw:
            # Запускаем с профилем пользователя
            if user_data_dir:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    args=["--no-first-run", "--no-default-browser-check"],
                    ignore_default_args=["--enable-automation"],
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            else:
                browser = pw.chromium.launch(headless=headless)
                ctx = browser.new_context()
                page = ctx.new_page()

            # Перехватчик ответов API — ищем ключи в JSON
            def on_response(response):
                try:
                    if response.status == 200:
                        body = response.text()
                        k = _find_key_in_text(body)
                        if k and len(k) > 20:
                            captured_key[0] = k
                except Exception:
                    pass

            page.on("response", on_response)

            # Переходим на страницу ключей
            page.goto(config["keys_url"], timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            # Ищем ключ в существующем DOM (может уже есть)
            for selector in config.get("key_selectors", []):
                try:
                    elements = page.query_selector_all(selector)
                    for el in elements:
                        text = el.get_attribute("value") or el.inner_text() or ""
                        k = _find_key_in_text(text)
                        if k and len(k) > 20:
                            captured_key[0] = k
                            break
                except Exception:
                    pass
                if captured_key[0]:
                    break

            # Если ключа нет — нажимаем кнопку создания
            if not captured_key[0]:
                for btn_text in config.get("create_button", []):
                    try:
                        # Пробуем разные стратегии поиска кнопки
                        selectors = [
                            f"button:has-text('{btn_text}')",
                            f"[role='button']:has-text('{btn_text}')",
                            f"a:has-text('{btn_text}')",
                            f"*:has-text('{btn_text}')",
                        ]
                        for sel in selectors:
                            try:
                                btn = page.wait_for_selector(sel, timeout=3000)
                                if btn:
                                    btn.click()
                                    _p(f"  🖱️  Нажал '{btn_text}'")
                                    page.wait_for_timeout(2000)
                                    break
                            except PWTimeout:
                                continue
                        if captured_key[0]:
                            break
                    except Exception:
                        continue

                # Ищем ключ после клика
                page.wait_for_timeout(2000)
                for selector in config.get("key_selectors", []):
                    try:
                        elements = page.query_selector_all(selector)
                        for el in elements:
                            text = el.get_attribute("value") or el.inner_text() or ""
                            k = _find_key_in_text(text)
                            if k and len(k) > 20:
                                captured_key[0] = k
                                break
                    except Exception:
                        pass
                    if captured_key[0]:
                        break

            # Ждём ключ (до 30 секунд)
            if not captured_key[0]:
                _p(f"  ⏳ Жду появления ключа...")
                for _ in range(30):
                    if captured_key[0]:
                        break
                    # Сканируем весь DOM
                    try:
                        page_text = page.evaluate("() => document.body.innerText")
                        k = _find_key_in_text(page_text)
                        if k and len(k) > 20:
                            captured_key[0] = k
                            break
                    except Exception:
                        pass
                    page.wait_for_timeout(1000)

            ctx.close()

    except Exception as e:
        _p(f"  ⚠️ Playwright ошибка для {provider}: {e}")

    return captured_key[0] or ""


# ══════════════════════════════════════════════════════════════════════════════
# ПРОВЕРКА СУЩЕСТВУЮЩИХ КЛЮЧЕЙ
# ══════════════════════════════════════════════════════════════════════════════

def check_all_keys() -> dict:
    """Проверить все существующие ключи параллельно."""
    import concurrent.futures
    results = {}

    def _check(provider, cfg):
        key = os.getenv(cfg["env_key"], "").strip()
        if not key:
            return provider, {"has_key": False, "valid": False}
        valid = validate_key(provider, key)
        return provider, {"has_key": True, "valid": valid, "masked": mask(key)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(_check, p, c) for p, c in PROVIDERS_CONFIG.items()]
        for fut in concurrent.futures.as_completed(futures):
            provider, result = fut.result()
            results[provider] = result

    return results


# ══════════════════════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ЦИКЛ НАСТРОЙКИ
# ══════════════════════════════════════════════════════════════════════════════

def setup_provider(provider: str, headless: bool = False) -> bool:
    """Настроить одного провайдера. Возвращает True если ключ получен."""
    config = PROVIDERS_CONFIG.get(provider)
    if not config:
        _p(f"❌ Неизвестный провайдер: {provider}")
        return False

    env_key = config["env_key"]
    existing = os.getenv(env_key, "").strip()

    # Проверяем существующий ключ
    if existing:
        _p(f"\n🔍 {config['name']}: проверяю существующий ключ {mask(existing)}...")
        if validate_key(provider, existing):
            _p(f"  ✅ Ключ валиден — пропускаю")
            return True
        else:
            _p(f"  ⚠️ Ключ невалиден — буду получать новый")

    _p(f"\n🔑 {config['name']}: получаю ключ автоматически...")

    # Пробуем через Playwright
    key = setup_provider_playwright(provider, config, headless=headless)

    if key:
        _p(f"  🎉 Ключ перехвачен: {mask(key)}")
        _p(f"  🔍 Валидирую...")
        if validate_key(provider, key):
            write_env_key(env_key, key)
            _p(f"  ✅ {config['name']}: ключ сохранён → {env_key}={mask(key)}")
            return True
        else:
            _p(f"  ❌ Ключ невалиден, пропускаю")
            return False
    else:
        # Playwright не смог — открываем браузер вручную
        _p(f"  ℹ️ Playwright не смог автоматически — открываю страницу")
        _p(f"  🔗 {config['keys_url']}")
        try:
            import webbrowser
            webbrowser.open(config["keys_url"])
        except Exception:
            pass

        # Ждём ввода ключа от пользователя
        _p(f"  Когда получишь ключ, вставь его здесь:")
        _p(f"  (или нажми Enter чтобы пропустить)")
        try:
            inp = input(f"  {config['name']} API key: ").strip()
        except (EOFError, KeyboardInterrupt):
            inp = ""

        if inp and len(inp) > 15:
            if validate_key(provider, inp):
                write_env_key(env_key, inp)
                _p(f"  ✅ {config['name']}: сохранён → {mask(inp)}")
                return True
            else:
                _p(f"  ❌ Ключ невалиден")
        return False


def run_setup(providers_to_setup: list, headless: bool = False) -> None:
    """Запустить настройку для списка провайдеров."""
    _p("\n" + "═" * 62)
    _p("  🔑 Автоматическая настройка API-ключей")
    _p("  Использует твой браузер (Chrome) с существующими сессиями")
    _p("═" * 62)

    # Проверяем Playwright
    try:
        from playwright.sync_api import sync_playwright
        has_playwright = True
        _p("\n  ✅ Playwright установлен — полная автоматизация активна")
    except ImportError:
        has_playwright = False
        _p("\n  ⚠️ Playwright не установлен — буду открывать браузер вручную")
        _p("  Для полной автоматизации: pip install playwright && playwright install chromium")

    chrome_dir = get_chrome_user_data_dir()
    if chrome_dir:
        _p(f"  ✅ Chrome профиль найден: {chrome_dir[:60]}...")
    else:
        _p("  ⚠️ Chrome профиль не найден — браузер запустится без сессий")

    _p(f"\n  Провайдеры к настройке: {', '.join(providers_to_setup)}\n")

    success = []
    failed = []
    skipped = []

    for provider in providers_to_setup:
        config = PROVIDERS_CONFIG.get(provider)
        if not config:
            _p(f"⚠️ Пропускаю неизвестный провайдер: {provider}")
            continue

        env_key = config["env_key"]
        existing = os.getenv(env_key, "").strip()
        if existing and validate_key(provider, existing):
            _p(f"  ✅ {config['name']}: уже настроен ({mask(existing)})")
            skipped.append(provider)
            continue

        ok = setup_provider(provider, headless=headless)
        if ok:
            success.append(provider)
        else:
            failed.append(provider)

    # Итоговый отчёт
    _p("\n" + "═" * 62)
    _p("  📊 ИТОГ")
    _p("═" * 62)
    if skipped:
        _p(f"  ✅ Уже были активны:  {', '.join(skipped)}")
    if success:
        _p(f"  🎉 Успешно добавлены: {', '.join(success)}")
    if failed:
        _p(f"  ❌ Не удалось:        {', '.join(failed)}")
        _p(f"     Добавь вручную через: python main.py")
        _p(f"     → напиши: 'сохрани ключ <провайдер>: <ключ>'")

    total_active = len(skipped) + len(success)
    _p(f"\n  Активных провайдеров: {total_active}/{len(providers_to_setup)}")

    # Перезагружаем .env
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH, override=True)
    except Exception:
        pass

    if total_active > 0:
        # Сбрасываем статус в LLMRouter
        try:
            from brain.llm_router import LLMRouter, LLMProvider
            router = LLMRouter.get()
            for p in success:
                try:
                    router.reset_provider(LLMProvider(p))
                except Exception:
                    pass
            _p(f"\n  ✅ LLMRouter обновлён — новые провайдеры активны")
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Автоматическая настройка API-ключей для my_personal_ai"
    )
    parser.add_argument(
        "--provider", nargs="+",
        choices=list(PROVIDERS_CONFIG.keys()),
        help="Конкретные провайдеры (по умолчанию — все)"
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Только проверить существующие ключи, не создавать новые"
    )
    parser.add_argument(
        "--headless", action="store_true",
        help="Запустить браузер без видимого окна"
    )
    parser.add_argument(
        "--free-only", action="store_true", default=True,
        help="Только бесплатные провайдеры (по умолчанию)"
    )
    args = parser.parse_args()

    if args.check:
        _p("\n🔍 Проверка всех ключей...\n")
        results = check_all_keys()
        for provider, result in results.items():
            cfg = PROVIDERS_CONFIG.get(provider, {})
            name = cfg.get("name", provider)
            free = "🆓" if cfg.get("free") else "💳"
            if not result["has_key"]:
                _p(f"  ❌ {name} {free}: нет ключа")
            elif result["valid"]:
                _p(f"  ✅ {name} {free}: {result.get('masked', '****')} — OK")
            else:
                _p(f"  ⚠️ {name} {free}: {result.get('masked', '****')} — НЕВАЛИДЕН")
        return

    # Определяем провайдеров
    if args.provider:
        providers = args.provider
    else:
        # По умолчанию все (или только бесплатные если --free-only)
        if args.free_only:
            providers = [p for p, c in PROVIDERS_CONFIG.items() if c.get("free")]
        else:
            providers = list(PROVIDERS_CONFIG.keys())

    run_setup(providers, headless=args.headless)


if __name__ == "__main__":
    main()
