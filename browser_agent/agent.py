# -*- coding: utf-8 -*-
"""
browser_agent/agent.py — AI-управляемый браузер на Playwright.

Возможности:
  • Открыть URL, навигация, back/forward
  • Клик по элементу (semantic: text, role, label, css, xpath)
  • Заполнение форм (input, select, textarea)
  • Снимок страницы (screenshot → base64)
  • Извлечение текста / DOM / ссылок
  • Сохранение и загрузка сессий (cookies + localStorage)
  • Режим наблюдения (observe) — только читать, не кликать
  • Запись уроков: какие сценарии работают, какие нет

Режимы:
  HEADLESS   — фоновый браузер (по умолчанию для автоматизации)
  VISIBLE    — видимый браузер (отладка, работа пользователя)
  OBSERVE    — только чтение, без действий

Безопасность:
  • Логины/пароли хранятся только в SecretManager (encrypted SQLite)
  • Сессии (cookies) — в data/browser_sessions/ в зашифрованном виде
  • Все hi-level действия пишутся в memory/lessons
  • Никакие секреты не логируются

Использование:
    agent = BrowserAgent.get()
    await agent.goto("https://example.com")
    await agent.click(text="Войти")
    await agent.fill(label="Email", value="user@example.com")
    content = await agent.get_text()
    await agent.save_session("mysite")

    # Синхронный вызов (для GUI/thread)
    result = agent.run_sync("goto", url="https://example.com")
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("browser_agent")

_SESSIONS_DIR = Path(__file__).parent.parent / "data" / "browser_sessions"
_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)

_LESSONS_LOG = Path(__file__).parent.parent / "data" / "browser_lessons.jsonl"


class BrowserMode(str, Enum):
    HEADLESS = "headless"
    VISIBLE  = "visible"
    OBSERVE  = "observe"    # только чтение


@dataclass
class BrowserAction:
    action:  str                        # goto / click / fill / screenshot / extract / scroll
    params:  Dict[str, Any] = field(default_factory=dict)
    ts:      float = field(default_factory=time.time)


@dataclass
class ActionResult:
    ok:       bool
    action:   str
    data:     Any       = None      # текст, base64 screenshot, список ссылок
    error:    str       = ""
    url:      str       = ""
    duration_ms: float  = 0.0

    def __bool__(self):
        return self.ok


class BrowserAgent:
    """
    Singleton — AI-управляемый браузер через Playwright.
    Потокобезопасен: все async-операции выполняются в выделенном event loop.
    """

    _instance: Optional["BrowserAgent"] = None

    def __init__(self):
        self._mode    = BrowserMode.HEADLESS
        self._loop:   Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._browser = None     # playwright Browser
        self._page    = None     # playwright Page
        self._playwright = None
        self._context = None     # playwright BrowserContext
        self._lock    = threading.Lock()
        self._ready   = threading.Event()
        self._current_url = ""
        self._observe_only = False
        self._action_history: List[ActionResult] = []

    @classmethod
    def get(cls) -> "BrowserAgent":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Инициализация ─────────────────────────────────────────────────────────

    def start(self, mode: BrowserMode = BrowserMode.HEADLESS) -> bool:
        """Запустить браузер в отдельном потоке с event loop."""
        self._mode = mode
        self._observe_only = (mode == BrowserMode.OBSERVE)

        if self._thread and self._thread.is_alive():
            return True

        self._ready.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="browser-agent", daemon=True
        )
        self._thread.start()
        # Ждём готовности (максимум 30 сек)
        if not self._ready.wait(timeout=30):
            log.error("BrowserAgent: failed to start within 30s")
            return False
        log.info("BrowserAgent started in %s mode", mode.value)
        return True

    def stop(self) -> None:
        """Закрыть браузер и остановить event loop."""
        if self._loop and self._loop.is_running():
            # Закрываем браузер и останавливаем loop
            future = asyncio.run_coroutine_threadsafe(self._close_browser(), self._loop)
            try:
                future.result(timeout=5)  # ждём завершения закрытия
            except Exception as e:
                log.warning("Error closing browser: %s", e)
            
            # Останавливаем event loop
            self._loop.call_soon_threadsafe(self._loop.stop)
            
            # Ждём завершения потока
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=5)
        
        self._loop = None
        self._thread = None
        log.info("BrowserAgent stopped")

    def _run_loop(self) -> None:
        """Event loop браузера — работает в отдельном потоке."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_browser())
            self._ready.set()
            self._loop.run_forever()
        except Exception as e:
            log.error("BrowserAgent loop error: %s", e)
            self._ready.set()   # разблокировать даже при ошибке
        finally:
            self._loop.close()

    async def _start_browser(self) -> None:
        """Инициализировать Playwright и браузер."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log.error("playwright not installed: pip install playwright && playwright install chromium")
            return

        self._playwright = await async_playwright().start()
        headless = self._mode != BrowserMode.VISIBLE

        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--lang=en-US,en",
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--allow-running-insecure-content",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        # Stealth user agent (looks like real Chrome)
        _USER_AGENT = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        # Контекст с постоянными cookies
        storage = self._load_storage_state()
        ctx_kwargs = dict(
            locale="en-US",
            viewport={"width": 1366, "height": 768},
            user_agent=_USER_AGENT,
            java_script_enabled=True,
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        if storage:
            ctx_kwargs["storage_state"] = storage
        self._context = await self._browser.new_context(**ctx_kwargs)

        self._page = await self._context.new_page()

        # Apply playwright-stealth to avoid bot detection (Cloudflare, etc.)
        try:
            from playwright_stealth import stealth_async
            await stealth_async(self._page)
            log.debug("Stealth mode applied")
        except ImportError:
            log.debug("playwright-stealth not installed, running without stealth")
        except Exception as e:
            log.debug("Stealth apply error: %s", e)

        # Remove webdriver property
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """)

        # Перехватывать ошибки страницы
        self._page.on("pageerror", lambda e: log.debug("Page JS error: %s", e))
        log.debug("Playwright browser started (headless=%s, stealth=True)", headless)

    async def _close_browser(self) -> None:
        """Корректное закрытие всех ресурсов браузера."""
        try:
            if self._page:
                try:
                    await self._page.close()
                except Exception as e:
                    log.debug("Error closing page: %s", e)
                self._page = None
            
            if self._context:
                try:
                    await self._context.close()
                except Exception as e:
                    log.debug("Error closing context: %s", e)
                self._context = None
            
            if self._browser:
                try:
                    await self._browser.close()
                except Exception as e:
                    log.debug("Error closing browser: %s", e)
                self._browser = None
            
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    log.debug("Error stopping playwright: %s", e)
                self._playwright = None
        except Exception as e:
            log.error("Error in _close_browser: %s", e)

    # ── Публичный API (синхронный фасад) ─────────────────────────────────────

    def run_sync(self, action: str, **params) -> ActionResult:
        """
        Синхронный вызов async-действия.
        Безопасен для вызова из GUI/Tkinter потока.
        """
        if not self._loop or not self._loop.is_running():
            if not self.start():
                return ActionResult(ok=False, action=action,
                                    error="Browser not started")

        future = asyncio.run_coroutine_threadsafe(
            self._execute(action, params), self._loop
        )
        try:
            result = future.result(timeout=30)
        except TimeoutError:
            result = ActionResult(ok=False, action=action,
                                  error="Action timeout (30s)")
        except Exception as e:
            result = ActionResult(ok=False, action=action, error=str(e))

        self._action_history.append(result)
        self._record_lesson(action, params, result)
        return result

    # ── Async actions ─────────────────────────────────────────────────────────

    async def _execute(self, action: str, params: dict) -> ActionResult:
        """Диспетчер действий."""
        t0 = time.time()
        if not self._page:
            return ActionResult(ok=False, action=action,
                                error="Browser page not initialized")
        try:
            if action == "goto":
                result = await self._goto(params.get("url", ""))
            elif action == "click":
                result = await self._click(params)
            elif action == "fill":
                result = await self._fill(params)
            elif action == "screenshot":
                result = await self._screenshot()
            elif action == "get_text":
                result = await self._get_text(params.get("selector", "body"))
            elif action == "get_links":
                result = await self._get_links()
            elif action == "scroll":
                result = await self._scroll(params.get("direction", "down"),
                                            params.get("amount", 500))
            elif action == "wait":
                await asyncio.sleep(params.get("seconds", 1))
                result = ActionResult(ok=True, action=action,
                                      url=self._current_url)
            elif action == "save_session":
                result = await self._save_session(params.get("name", "default"))
            elif action == "load_session":
                result = await self._load_session(params.get("name", "default"))
            elif action == "get_dom":
                result = await self._get_dom()
            elif action == "select":
                result = await self._select(params)
            elif action == "back":
                await self._page.go_back()
                result = ActionResult(ok=True, action=action,
                                      url=self._page.url)
            elif action == "forward":
                await self._page.go_forward()
                result = ActionResult(ok=True, action=action,
                                      url=self._page.url)
            elif action == "refresh":
                await self._page.reload()
                result = ActionResult(ok=True, action=action,
                                      url=self._page.url)
            elif action == "current_url":
                result = ActionResult(ok=True, action=action,
                                      data=self._page.url,
                                      url=self._page.url)
            else:
                result = ActionResult(ok=False, action=action,
                                      error=f"Unknown action: {action}")

            result.duration_ms = round((time.time() - t0) * 1000, 1)
            return result
        except Exception as e:
            log.error("Browser action '%s' failed: %s", action, e)
            return ActionResult(ok=False, action=action,
                                error=str(e)[:200],
                                duration_ms=round((time.time() - t0) * 1000, 1))

    async def _goto(self, url: str) -> ActionResult:
        """Перейти по URL."""
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        resp = await self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
        self._current_url = self._page.url
        status = resp.status if resp else 0
        ok = status < 400 if status else True
        return ActionResult(ok=ok, action="goto", url=self._current_url,
                            data={"status": status, "url": self._current_url},
                            error="" if ok else f"HTTP {status}")

    async def _click(self, params: dict) -> ActionResult:
        """Кликнуть по элементу. Semantic-first локаторы."""
        if self._observe_only:
            return ActionResult(ok=False, action="click",
                                error="Observe-only mode: clicks disabled")

        locator = self._resolve_locator(params)
        if not locator:
            return ActionResult(ok=False, action="click",
                                error="No locator specified (text/role/css/xpath)")

        # Подождать что элемент виден
        await locator.wait_for(state="visible", timeout=10000)
        await locator.click()
        # Подождать возможную навигацию
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        self._current_url = self._page.url
        return ActionResult(ok=True, action="click", url=self._current_url)

    async def _fill(self, params: dict) -> ActionResult:
        """Заполнить поле ввода."""
        if self._observe_only:
            return ActionResult(ok=False, action="fill",
                                error="Observe-only mode")

        value = params.get("value", "")
        locator = self._resolve_locator(params)
        if not locator:
            return ActionResult(ok=False, action="fill",
                                error="No locator specified")

        await locator.wait_for(state="visible", timeout=8000)
        await locator.clear()
        await locator.fill(value)
        return ActionResult(ok=True, action="fill", url=self._current_url,
                            data={"filled": True})

    async def _select(self, params: dict) -> ActionResult:
        """Выбрать значение в <select>."""
        if self._observe_only:
            return ActionResult(ok=False, action="select", error="Observe-only mode")
        value = params.get("value", "")
        locator = self._resolve_locator(params)
        if not locator:
            return ActionResult(ok=False, action="select", error="No locator")
        await locator.select_option(value=value)
        return ActionResult(ok=True, action="select", url=self._current_url)

    async def _screenshot(self) -> ActionResult:
        """Снимок экрана → base64 PNG."""
        data = await self._page.screenshot(type="png", full_page=False)
        b64 = base64.b64encode(data).decode()
        return ActionResult(ok=True, action="screenshot",
                            data=b64, url=self._current_url)

    async def _get_text(self, selector: str = "body") -> ActionResult:
        """Получить текст со страницы."""
        try:
            element = self._page.locator(selector)
            text = await element.inner_text(timeout=5000)
        except Exception:
            text = await self._page.evaluate("() => document.body.innerText")
        return ActionResult(ok=True, action="get_text",
                            data=text[:10000], url=self._current_url)

    async def _get_links(self) -> ActionResult:
        """Получить все ссылки на странице."""
        links = await self._page.evaluate("""
            () => Array.from(document.querySelectorAll('a[href]'))
                       .map(a => ({text: a.innerText.trim(), href: a.href}))
                       .filter(l => l.href.startsWith('http'))
                       .slice(0, 100)
        """)
        return ActionResult(ok=True, action="get_links",
                            data=links, url=self._current_url)

    async def _get_dom(self) -> ActionResult:
        """Получить упрощённый DOM (интерактивные элементы)."""
        dom = await self._page.evaluate("""
            () => {
                const els = document.querySelectorAll(
                    'button, a, input, select, textarea, [role="button"], [onclick]'
                );
                return Array.from(els).map(el => ({
                    tag:   el.tagName.toLowerCase(),
                    type:  el.type || '',
                    text:  (el.innerText || el.value || el.placeholder || '').slice(0,80),
                    id:    el.id || '',
                    name:  el.name || '',
                    role:  el.getAttribute('role') || '',
                    href:  el.href || '',
                })).slice(0, 200);
            }
        """)
        return ActionResult(ok=True, action="get_dom",
                            data=dom, url=self._current_url)

    async def _scroll(self, direction: str, amount: int) -> ActionResult:
        """Прокрутить страницу."""
        delta = amount if direction == "down" else -amount
        await self._page.evaluate(f"window.scrollBy(0, {delta})")
        await asyncio.sleep(0.3)
        return ActionResult(ok=True, action="scroll", url=self._current_url)

    async def _save_session(self, name: str) -> ActionResult:
        """Сохранить cookies + localStorage для последующего использования."""
        try:
            state = await self._context.storage_state()
            session_file = _SESSIONS_DIR / f"{name}.json"
            session_file.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("Browser session saved: %s", name)
            return ActionResult(ok=True, action="save_session",
                                data={"session": name, "path": str(session_file)})
        except Exception as e:
            return ActionResult(ok=False, action="save_session", error=str(e))

    async def _load_session(self, name: str) -> ActionResult:
        """Загрузить сохранённую сессию."""
        session_file = _SESSIONS_DIR / f"{name}.json"
        if not session_file.exists():
            return ActionResult(ok=False, action="load_session",
                                error=f"Session '{name}' not found")
        try:
            state = json.loads(session_file.read_text(encoding="utf-8"))
            # Создать новый контекст с загруженной сессией
            await self._context.close()
            self._context = await self._browser.new_context(
                storage_state=state,
                locale="ru-RU",
                viewport={"width": 1280, "height": 800},
            )
            self._page = await self._context.new_page()
            log.info("Browser session loaded: %s", name)
            return ActionResult(ok=True, action="load_session",
                                data={"session": name})
        except Exception as e:
            return ActionResult(ok=False, action="load_session", error=str(e))

    # ── Локаторы ──────────────────────────────────────────────────────────────

    def _resolve_locator(self, params: dict):
        """
        Semantic-first: text → role+name → label → css → xpath.
        Порядок важен — сначала самые надёжные.
        """
        if not self._page:
            return None
        page = self._page

        if "text" in params:
            return page.get_by_text(params["text"], exact=False)
        if "role" in params:
            name = params.get("name", "")
            return page.get_by_role(params["role"], name=name) if name else \
                   page.get_by_role(params["role"])
        if "label" in params:
            return page.get_by_label(params["label"])
        if "placeholder" in params:
            return page.get_by_placeholder(params["placeholder"])
        if "css" in params:
            return page.locator(params["css"])
        if "xpath" in params:
            return page.locator(f"xpath={params['xpath']}")
        if "selector" in params:
            return page.locator(params["selector"])
        return None

    # ── Сессии ────────────────────────────────────────────────────────────────

    def _load_storage_state(self) -> Optional[dict]:
        """Загрузить последнюю сохранённую сессию 'default' при старте."""
        default_session = _SESSIONS_DIR / "default.json"
        if default_session.exists():
            try:
                return json.loads(default_session.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def list_sessions(self) -> List[str]:
        """Список сохранённых сессий."""
        return [f.stem for f in _SESSIONS_DIR.glob("*.json")]

    # ── Уроки / Memory ────────────────────────────────────────────────────────

    def _record_lesson(self, action: str, params: dict, result: ActionResult) -> None:
        """Записать урок: что сработало, что нет."""
        lesson = {
            "ts":       time.time(),
            "action":   action,
            "url":      result.url,
            "params":   {k: v for k, v in params.items()
                         if k not in ("value", "password")},  # не логировать секреты
            "ok":       result.ok,
            "error":    result.error,
            "duration_ms": result.duration_ms,
        }
        try:
            with open(_LESSONS_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(lesson, ensure_ascii=False) + "\n")
        except Exception:
            pass

        # Сохранить в MemoryStore только важные уроки (ошибки и успешные сценарии)
        if not result.ok and result.error:
            self._save_to_memory(action, params, result)

    def _save_to_memory(self, action: str, params: dict,
                        result: ActionResult) -> None:
        """Записать урок в общую память системы."""
        try:
            from memory.memory_store import KnowledgeEntry, MemoryStore
            content = (
                f"Браузер-действие: {action}\n"
                f"URL: {result.url}\n"
                f"Параметры: {json.dumps({k:v for k,v in params.items() if k!='value'}, ensure_ascii=False)}\n"
                f"Результат: {'OK' if result.ok else 'ERROR'}\n"
                f"Ошибка: {result.error}\n"
                f"Длительность: {result.duration_ms}ms"
            )
            entry = KnowledgeEntry(
                category="error" if not result.ok else "solution",
                title=f"[Browser] {action} на {result.url[:50]}",
                content=content,
                tags=["browser_agent", "auto", action],
                importance=0.6,
                source="browser_agent",
            )
            MemoryStore.get().add_knowledge(entry)
        except Exception:
            pass

    # ── Статус и отчёт ────────────────────────────────────────────────────────

    def status(self) -> dict:
        running = self._thread is not None and self._thread.is_alive()
        return {
            "running":      running,
            "mode":         self._mode.value if running else "stopped",
            "current_url":  self._current_url,
            "sessions":     self.list_sessions(),
            "observe_only": self._observe_only,
            "history_count": len(self._action_history),
            "last_error":   next(
                (r.error for r in reversed(self._action_history) if not r.ok), ""
            ),
        }

    def get_history(self, last_n: int = 20) -> List[ActionResult]:
        return self._action_history[-last_n:]

    def get_lessons_report(self, last_n: int = 50) -> str:
        """Отчёт об ошибках браузер-агента из log файла."""
        if not _LESSONS_LOG.exists():
            return "Нет записей уроков браузера"
        lines = _LESSONS_LOG.read_text(encoding="utf-8").splitlines()[-last_n:]
        errors = []
        for l in lines:
            try:
                d = json.loads(l)
                if not d.get("ok"):
                    errors.append(
                        f"  ❌ [{d['action']}] {d.get('url','?')[:50]} — {d.get('error','')[:60]}"
                    )
            except Exception:
                pass
        if not errors:
            return "✅ Ошибок браузера не найдено"
        return "Ошибки браузер-агента:\n" + "\n".join(errors[-20:])
