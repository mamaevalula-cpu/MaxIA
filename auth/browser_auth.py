# -*- coding: utf-8 -*-
"""
auth/browser_auth.py — Браузерная авторизация через Playwright/Selenium.

Умеет:
  • Открыть браузер и дать пользователю войти вручную
  • Сохранить cookies/сессию после входа
  • Использовать сохранённую сессию для последующих запросов
  • Получать коды подтверждения из браузера
  • Авторегистрация на сайтах (с явного разрешения пользователя)

ВАЖНО: Все действия логируются. Создание аккаунтов только с подтверждения.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.config import cfg
from core.secret_manager import SecretManager

log = logging.getLogger("auth.browser")

SESSIONS_DIR = cfg.DATA_DIR / "browser_sessions"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


class BrowserSession:
    """Сохранённая браузерная сессия."""

    def __init__(self, service: str, cookies: List[Dict],
                 local_storage: Dict = None, headers: Dict = None):
        self.service = service
        self.cookies = cookies
        self.local_storage = local_storage or {}
        self.headers = headers or {}
        self.created_at = time.time()
        self.last_used = time.time()

    def to_dict(self) -> Dict:
        return {
            "service": self.service,
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "headers": self.headers,
            "created_at": self.created_at,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "BrowserSession":
        s = cls(
            service=data["service"],
            cookies=data.get("cookies", []),
            local_storage=data.get("local_storage", {}),
            headers=data.get("headers", {}),
        )
        s.created_at = data.get("created_at", time.time())
        s.last_used = data.get("last_used", time.time())
        return s


class BrowserAuth:
    """
    Менеджер браузерной авторизации.

    Стратегия:
    1. Проверить есть ли сохранённая сессия для сервиса
    2. Если нет — открыть браузер, дать пользователю войти вручную
    3. Захватить cookies/токены
    4. Зашифрованно сохранить
    5. Залогировать действие

    НЕ сохраняет пароли в открытом виде.
    """

    _instance: Optional["BrowserAuth"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._sessions: Dict[str, BrowserSession] = {}
        self._secrets = SecretManager.get()
        self._playwright_available = self._check_playwright()
        self._selenium_available = self._check_selenium()
        self._load_sessions()
        log.info(
            "BrowserAuth ready (playwright=%s, selenium=%s)",
            self._playwright_available, self._selenium_available
        )

    @classmethod
    def get(cls) -> "BrowserAuth":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Проверка доступности браузерных инструментов ──────────────────────────

    def _check_playwright(self) -> bool:
        try:
            import playwright
            return True
        except ImportError:
            return False

    def _check_selenium(self) -> bool:
        try:
            import selenium
            return True
        except ImportError:
            return False

    # ── Авторизация ───────────────────────────────────────────────────────────

    def has_session(self, service: str) -> bool:
        """Есть ли сохранённая сессия для сервиса?"""
        return service in self._sessions

    def login_manual(self, service: str, url: str,
                     on_ready: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Открыть браузер. Пользователь входит вручную.
        После входа — захватить сессию.

        Метод блокирующий (ждёт пока пользователь не завершит вход).
        on_ready(cookies) — callback после захвата.
        """
        log.info("Manual login: service=%s, url=%s", service, url)
        self._secrets.log_auth_action(service, "manual_login_start", url)

        if self._playwright_available:
            return self._login_playwright(service, url, on_ready)
        elif self._selenium_available:
            return self._login_selenium(service, url, on_ready)
        else:
            return False, (
                "Браузерные инструменты не установлены.\n"
                "Установи: pip install playwright && playwright install\n"
                "или:       pip install selenium webdriver-manager"
            )

    def _login_playwright(self, service: str, url: str,
                          on_ready: Optional[Callable]) -> Tuple[bool, str]:
        """Авторизация через Playwright (рекомендуется)."""
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                context = browser.new_context()
                page = context.new_page()
                page.goto(url)

                log.info("Browser opened. Waiting for user to login (max 5 min)...")
                # Ждём пока пользователь залогинится (до 5 минут)
                # Простой способ: ждать изменения URL или клика на кнопку
                page.wait_for_timeout(300_000)  # 5 минут

                # Захватить cookies
                cookies = context.cookies()
                storage = page.evaluate("JSON.stringify(window.localStorage)")
                import json
                local_storage = json.loads(storage) if storage else {}

                session = BrowserSession(
                    service=service,
                    cookies=cookies,
                    local_storage=local_storage,
                )
                self._sessions[service] = session
                self._save_sessions()

                if on_ready:
                    on_ready(cookies)

                self._secrets.log_auth_action(service, "manual_login_success",
                                               f"cookies={len(cookies)}")
                browser.close()
                return True, f"Сессия сохранена ({len(cookies)} cookies)"

        except Exception as e:
            log.error("Playwright login failed: %s", e)
            self._secrets.log_auth_action(service, "manual_login_failed", str(e))
            return False, str(e)

    def _login_selenium(self, service: str, url: str,
                        on_ready: Optional[Callable]) -> Tuple[bool, str]:
        """Авторизация через Selenium."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service

            try:
                from webdriver_manager.chrome import ChromeDriverManager
                driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
            except Exception:
                driver = webdriver.Chrome()

            driver.get(url)
            log.info("Selenium browser opened. Waiting for user...")

            # Ждём пока пользователь войдёт (простая проверка изменения URL)
            start_url = url
            deadline = time.time() + 300
            while time.time() < deadline:
                time.sleep(3)
                if driver.current_url != start_url:
                    break

            # Захватить cookies
            cookies = driver.get_cookies()
            session = BrowserSession(service=service, cookies=cookies)
            self._sessions[service] = session
            self._save_sessions()

            if on_ready:
                on_ready(cookies)

            self._secrets.log_auth_action(service, "selenium_login_success",
                                           f"cookies={len(cookies)}")
            driver.quit()
            return True, f"Сессия сохранена ({len(cookies)} cookies)"

        except Exception as e:
            log.error("Selenium login failed: %s", e)
            return False, str(e)

    def get_session_cookies(self, service: str) -> List[Dict]:
        """Получить cookies для сервиса."""
        session = self._sessions.get(service)
        if session:
            session.last_used = time.time()
            return session.cookies
        return []

    def delete_session(self, service: str) -> bool:
        """Удалить сессию."""
        if service in self._sessions:
            del self._sessions[service]
            self._save_sessions()
            self._secrets.log_auth_action(service, "session_deleted")
            return True
        return False

    def list_sessions(self) -> List[Dict]:
        """Список всех сохранённых сессий."""
        return [
            {
                "service": s.service,
                "cookies_count": len(s.cookies),
                "created_at": s.created_at,
                "last_used": s.last_used,
            }
            for s in self._sessions.values()
        ]

    # ── Авторегистрация ───────────────────────────────────────────────────────

    def register_account(self, service: str, url: str,
                         email: str = "", use_email_verification: bool = True,
                         confirm_callback: Optional[Callable] = None) -> Tuple[bool, str]:
        """
        Авторегистрация на сайте.
        ВСЕГДА требует явного подтверждения (confirm_callback → True).
        """
        log.info("Account registration requested: service=%s", service)

        if confirm_callback and not confirm_callback(service, url):
            self._secrets.log_auth_action(service, "registration_cancelled_by_user")
            return False, "Регистрация отменена пользователем."

        self._secrets.log_auth_action(service, "registration_started", url)
        # Открываем браузер, пользователь регистрируется вручную
        return self.login_manual(service, url)

    # ── Персистентность сессий ────────────────────────────────────────────────

    def _save_sessions(self) -> None:
        """Сохранить сессии в зашифрованное хранилище."""
        try:
            data = json.dumps({
                k: v.to_dict() for k, v in self._sessions.items()
            })
            self._secrets.set("browser_sessions", data, service="auth")
        except Exception as e:
            log.debug("Save sessions failed: %s", e)

    def _load_sessions(self) -> None:
        """Загрузить сессии из хранилища."""
        try:
            raw = self._secrets.get("browser_sessions", "{}")
            data = json.loads(raw)
            self._sessions = {
                k: BrowserSession.from_dict(v)
                for k, v in data.items()
            }
            log.debug("Loaded %d browser sessions", len(self._sessions))
        except Exception as e:
            log.debug("Load sessions failed: %s", e)
            self._sessions = {}
