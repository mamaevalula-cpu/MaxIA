#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/web_automation_agent.py v2.0 -- Self-Correction Loop.
Handles: DOM changes, Cloudflare, CAPTCHA, 2FA/OTP, browser crashes.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
import traceback
from collections import deque
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from agents.base_agent import AgentInfo, BaseAgent

log = logging.getLogger("agents.web_automation")

MAX_RETRIES     = 3
RETRY_BACKOFF   = [2, 5, 15]
STEP_TIMEOUT_MS = 30_000
NAV_TIMEOUT_MS  = 45_000
SCREENSHOT_DIR  = Path("/tmp/webshots")
ERROR_LOG_PATH  = Path("/root/my_personal_ai/logs/web_errors.jsonl")

CF_MARKERS  = ["just a moment", "checking your browser", "cf-browser-verification",
               "cloudflare", "ray id:"]
CAP_MARKERS = ["recaptcha", "hcaptcha", "are you human", "captcha", "verify you are human"]


class SelfCorrectionError(Exception):
    """All retries exhausted for an automation step."""


class WebAutomationAgent(BaseAgent):
    """
    Autonomous Playwright agent with Self-Correction Loop.

    On every action:
    1. Try primary selector / action.
    2. Fail -> screenshot -> ask LLM for semantic alternative -> retry.
    3. After MAX_RETRIES fails -> JSON error log -> clear cookies -> raise.
    """

    name = "web_automation"
    description = "Playwright: autonomous navigation, login, extraction, self-healing."

    def __init__(self) -> None:
        super().__init__("web_automation")
        self._ready = False
        self._browser = None
        self._context = None
        self._page    = None
        self._playwright = None
        self._results: List[Dict] = []
        self._task_queue: deque = deque()
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Lazy init: don't start browser at __init__ time - start on first use
        # This prevents hanging during service startup
        log.info("WebAutomationAgent: lazy init (browser starts on first use)")

    # -- abstract ---------------------------------------------------------

    def can_handle(self, text: str) -> bool:
        kw = ["playwright", "web agent", "browser", "собери ip",
              "зарегистрируй", "открой сайт", "web automation", "браузер", "kwork"]
        return any(k in text.lower() for k in kw)

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="web_automation",
            description="Playwright agent with self-correction loop v2.0.",
            capabilities=["navigate", "login", "extract_data", "collect_ips",
                          "self_correction", "otp_extraction", "cloudflare_wait"],
            version="2.0.0",
        )

    # -- browser lifecycle ------------------------------------------------

    def _init_browser(self) -> bool:
        try:
            from playwright.sync_api import sync_playwright
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                      "--disable-blink-features=AutomationControlled",
                      "--window-size=1280,720"],
            )
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                java_script_enabled=True,
            )
            self._page = self._context.new_page()
            self._page.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            self._ready = True
            log.info("WebAutomationAgent v2.0: Playwright ready")
            return True
        except Exception as e:
            self._ready = False
            log.warning("WebAutomationAgent unavailable: %s", e)
            return False

    def _ensure_browser(self) -> bool:
        """Health-ping and auto-recover crashed browser."""
        if not self._ready:
            return self._init_browser()
        try:
            self._page.evaluate("1+1")
            return True
        except Exception:
            log.warning("Browser crash detected -- reinitialising")
            return self._init_browser()

    # -- navigation -------------------------------------------------------

    def navigate(self, url: str, wait: str = "domcontentloaded") -> Dict[str, Any]:
        """Navigate with 2 retries on network failure."""
        if not self._ensure_browser():
            return {"error": "Browser unavailable"}
        for attempt in range(2):
            try:
                self._page.goto(url, wait_until=wait, timeout=NAV_TIMEOUT_MS)
                self._page.wait_for_timeout(1500)
                return {"ok": True, "url": self._page.url, "title": self._page.title()}
            except Exception as e:
                if attempt == 0:
                    time.sleep(RETRY_BACKOFF[0])
                    self._ensure_browser()
                else:
                    return {"error": str(e), "url": url}
        return {"error": "navigation failed"}

    def page_content(self, max_chars: int = 6000) -> str:
        try:
            return self._page.inner_text("body", timeout=5000)[:max_chars]
        except Exception:
            return ""

    def screenshot(self, name: str = "shot") -> str:
        path = str(SCREENSHOT_DIR / f"{name}_{int(time.time())}.png")
        try:
            self._page.screenshot(path=path, full_page=False)
            return path
        except Exception as e:
            return f"error:{e}"

    # -- LLM selector fallback -------------------------------------------

    def _ask_llm_for_selector(self, description: str, html: str) -> Optional[str]:
        """Ask LLM for a CSS selector when primary selector fails."""
        try:
            from brain.llm_router import LLMRouter
            llm = LLMRouter.get()
            prompt = (
                "HTML:\n```\n" + html[:2500] + "\n```\n"
                "Find a CSS selector for: '" + description + "'\n"
                "Return ONLY the selector, no explanation."
            )
            result = llm.ask_sync(
                prompt,
                system="Expert CSS selector finder. Return selector only.",
                max_tokens=60,
                task_type="code",
            )
            if result and result.strip():
                return result.strip().split("\n")[0].strip()
        except Exception as e:
            log.debug("LLM selector query failed: %s", e)
        return None

    # -- smart interactions -----------------------------------------------

    def _smart_click(self, selector: str, description: str) -> bool:
        """Click with self-correction: primary -> LLM alt -> text search."""
        for attempt in range(MAX_RETRIES):
            try:
                el = self._page.locator(selector).first
                el.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
                el.click(timeout=STEP_TIMEOUT_MS)
                return True
            except Exception as e:
                log.debug("click attempt %d (%s): %s", attempt + 1, selector, e)
                if attempt >= MAX_RETRIES - 1:
                    break
                html = self._page.content()[:4000]
                llm_sel = self._ask_llm_for_selector(description, html)
                if llm_sel and llm_sel != selector:
                    selector = llm_sel
                    continue
                # text fallback
                for try_fb in [
                    lambda: self._page.get_by_text(description, exact=False).first.click(timeout=5000),
                    lambda: self._page.get_by_role("button", name=re.compile(description, re.I)).first.click(timeout=5000),
                ]:
                    try:
                        try_fb()
                        return True
                    except Exception:
                        pass
                time.sleep(RETRY_BACKOFF[min(attempt, 2)])
        return False

    def _smart_fill(self, selector: str, value: str, description: str) -> bool:
        """Fill input with self-correction fallbacks."""
        for attempt in range(MAX_RETRIES):
            try:
                self._page.locator(selector).first.fill(value, timeout=STEP_TIMEOUT_MS)
                return True
            except Exception as e:
                log.debug("fill attempt %d (%s): %s", attempt + 1, selector, e)
                if attempt >= MAX_RETRIES - 1:
                    break
                html = self._page.content()[:4000]
                llm_sel = self._ask_llm_for_selector(description + " input", html)
                if llm_sel:
                    selector = llm_sel
                    continue
                for try_fb in [
                    lambda: self._page.get_by_label(re.compile(description, re.I)).first.fill(value),
                    lambda: self._page.get_by_placeholder(re.compile(description, re.I)).first.fill(value),
                ]:
                    try:
                        try_fb()
                        return True
                    except Exception:
                        pass
                time.sleep(RETRY_BACKOFF[min(attempt, 2)])
        return False

    # -- cloudflare / captcha ---------------------------------------------

    def _detect_cloudflare(self) -> bool:
        try:
            ct = self._page.inner_text("body", timeout=3000).lower()
            return any(m in ct for m in CF_MARKERS)
        except Exception:
            return False

    def _detect_captcha(self) -> bool:
        try:
            ct = self._page.inner_text("body", timeout=3000).lower()
            return any(m in ct for m in CAP_MARKERS)
        except Exception:
            return False

    def _handle_cloudflare(self, max_wait: int = 25) -> bool:
        """Wait for Cloudflare JS challenge to auto-resolve."""
        log.info("Cloudflare detected -- waiting up to %ds", max_wait)
        for _ in range(max_wait):
            time.sleep(1)
            if not self._detect_cloudflare():
                log.info("Cloudflare passed")
                return True
        self.screenshot("cloudflare_fail")
        return False

    def _handle_captcha(self) -> bool:
        """Try auto-clicking hCaptcha / reCAPTCHA checkbox."""
        log.info("CAPTCHA detected -- attempting auto-click")
        time.sleep(3)
        pairs = [
            ("iframe[src*='hcaptcha']", ".checkbox"),
            ("iframe[title*='reCAPTCHA']", ".recaptcha-checkbox-border"),
        ]
        for iframe_sel, cb_sel in pairs:
            try:
                frame = self._page.frame_locator(iframe_sel).first
                frame.locator(cb_sel).click(timeout=5000)
                time.sleep(3)
                if not self._detect_captcha():
                    return True
            except Exception:
                pass
        self.screenshot("captcha_unsolved")
        return False

    # -- OTP extraction ---------------------------------------------------

    def _extract_otp_from_email(self, timeout: int = 90) -> Optional[str]:
        """Poll email agent for a fresh OTP code (6-8 digits or alphanumeric)."""
        log.info("Polling email for OTP (timeout: %ds)", timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                from agents.email_agent import EmailAgent
                msgs = EmailAgent().get_recent_messages(limit=5)
                for msg in msgs:
                    body = msg.get("body", "") + " " + msg.get("subject", "")
                    m = re.search(r"\b(\d{6,8})\b", body)
                    if m:
                        log.info("OTP found: %s", m.group(1))
                        return m.group(1)
                    c = re.search(r"(?:code|token|key)[:\s]+([A-Za-z0-9]{6,20})", body, re.I)
                    if c:
                        log.info("Code found: %s", c.group(1))
                        return c.group(1)
            except Exception as e:
                log.debug("Email poll: %s", e)
            time.sleep(5)
        return None

    def _fill_otp(self, code: str) -> bool:
        selectors = [
            "input[name*='otp']", "input[name*='code']", "input[name*='token']",
            "input[autocomplete='one-time-code']", "input[type='number']",
            "input[placeholder*='code']", "input[placeholder*='OTP']",
        ]
        for sel in selectors:
            try:
                if self._page.locator(sel).count() > 0:
                    self._page.locator(sel).first.fill(code, timeout=5000)
                    self._page.keyboard.press("Enter")
                    log.info("OTP filled via: %s", sel)
                    return True
            except Exception:
                continue
        return False

    # -- step executor (CORE self-correction loop) -------------------------

    def execute_step(self, step_fn: Callable, description: str,
                     session_id: str = "default") -> Any:
        """
        Run step_fn up to MAX_RETRIES times.
        On each failure: screenshot, check OTP/CF/CAPTCHA, exponential backoff.
        If all retries fail: write JSON error log, clear cookies, raise.
        """
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                if self._detect_cloudflare():
                    self._handle_cloudflare()
                if self._detect_captcha():
                    self._handle_captcha()
                result = step_fn()
                if result is not None and result is not False:
                    return result
                raise RuntimeError(f"step returned {result!r}")
            except SelfCorrectionError:
                raise
            except Exception as e:
                last_error = e
                log.warning("Step [%s] attempt %d/%d: %s",
                            description, attempt + 1, MAX_RETRIES, e)
                self.screenshot(f"err_{session_id}_{attempt}")
                # OTP check
                content_lc = self.page_content(500).lower()
                if any(kw in content_lc for kw in
                       ["verification code", "enter code", "otp", "2fa", "two-factor"]):
                    otp = self._extract_otp_from_email(timeout=90)
                    if otp and self._fill_otp(otp):
                        self._page.wait_for_timeout(2000)
                        continue
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                    time.sleep(delay)
                    self._ensure_browser()

        # Exhausted -- save JSON error entry
        entry = {
            "ts": time.time(),
            "session_id": session_id,
            "step": description,
            "error": str(last_error),
            "url": self._page.url if self._page else "unknown",
            "traceback": traceback.format_exc()[-2000:],
        }
        try:
            with open(ERROR_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # Clean session state
        try:
            self._context.clear_cookies()
            self._page.goto("about:blank")
        except Exception:
            pass
        log.error("Step [%s] EXHAUSTED after %d attempts", description, MAX_RETRIES)
        raise SelfCorrectionError(f"'{description}': {last_error}")

    # -- high-level tasks -------------------------------------------------

    def login(self, url: str, email_sel: str, pass_sel: str,
              email: str, password: str, submit_sel: str = "") -> Dict[str, Any]:
        """Full login flow: navigate -> fill -> submit -> OTP if needed."""
        sid = f"login_{int(time.time())}"
        try:
            self.execute_step(
                lambda: self.navigate(url)["ok"], "navigate to login", session_id=sid)
            self.execute_step(
                lambda: self._smart_fill(email_sel, email, "email username"),
                "fill email", session_id=sid)
            self.execute_step(
                lambda: self._smart_fill(pass_sel, password, "password"),
                "fill password", session_id=sid)
            if submit_sel:
                self.execute_step(
                    lambda: self._smart_click(submit_sel, "login submit button"),
                    "submit login", session_id=sid)
            else:
                self._page.keyboard.press("Enter")
            self._page.wait_for_timeout(3000)
            # OTP check after submit
            ct = self.page_content(500).lower()
            if any(kw in ct for kw in ["verification", "otp", "2fa", "code"]):
                otp = self._extract_otp_from_email(timeout=90)
                if otp:
                    self._fill_otp(otp)
                    self._page.wait_for_timeout(2000)
            return {"ok": True, "url": self._page.url, "title": self._page.title()}
        except SelfCorrectionError as e:
            return {"error": str(e), "session_id": sid}

    def scrape_page(self, url: str, selectors: Dict[str, str]) -> Dict[str, Any]:
        """Scrape fields; falls back to LLM selector on DOM mismatch."""
        nav = self.navigate(url)
        if nav.get("error"):
            return {"error": nav["error"]}
        data: Dict[str, Any] = {}
        for field, sel in selectors.items():
            try:
                el = self._page.locator(sel).first
                el.wait_for(state="visible", timeout=5000)
                data[field] = el.inner_text(timeout=3000).strip()
            except Exception:
                html = self._page.content()[:4000]
                llm_sel = self._ask_llm_for_selector(field, html)
                if llm_sel:
                    try:
                        data[field] = (
                            self._page.locator(llm_sel).first.inner_text(timeout=3000).strip()
                        )
                        continue
                    except Exception:
                        pass
                data[field] = None
        return {"url": self._page.url, "data": data}

    # -- service IPs / gmail ----------------------------------------------

    def get_service_ips(self) -> str:
        p = Path("/root/my_personal_ai/config/service_ips.json")
        if not p.exists():
            return "IPs not collected. POST /api/web/collect-ips"
        try:
            data = json.loads(p.read_text())
            parts = ["Service IPs (cached):"]
            for name, info in data.items():
                ip   = info.get("primary_ip", "?")
                host = info.get("host", "")
                parts.append("  " + name + ": " + ip + "  (" + host + ")")
            return "\n".join(parts)
        except Exception as e:
            return "Error reading IPs: " + str(e)

    def get_gmail_app_password(self, email: str, password: str) -> Optional[str]:
        r = self.login(
            "https://accounts.google.com/signin/v2/identifier",
            "input[type=email]", "input[type=password]", email, password)
        if r.get("error"):
            return None
        nav = self.navigate("https://myaccount.google.com/apppasswords")
        if nav.get("error"):
            return None
        content = self.page_content()
        codes = re.findall(r"[a-z]{4}\s[a-z]{4}\s[a-z]{4}\s[a-z]{4}", content)
        return codes[0].replace(" ", "") if codes else None

    # -- status / dispatcher ----------------------------------------------

    def status(self) -> str:
        ok = self._ready and self._page is not None
        return (
            "WebAutomationAgent v2.0\n"
            "  Browser: " + ("ready" if ok else "unavailable") + "\n"
            "  Results: " + str(len(self._results)) + "\n"
            "  Queue:   " + str(len(self._task_queue)) + " pending\n"
            "  Errors:  " + str(ERROR_LOG_PATH)
        )

    def process(self, text: str, source: str = "user", **kwargs) -> str:
        tl = text.lower().strip()
        if "статус" in tl or "status" in tl:
            return self.status()
        if "ip" in tl and any(k in tl for k in ["собери", "collect", "service", "сервис"]):
            return self.get_service_ips()
        if "gmail" in tl or "app password" in tl:
            r = self.get_gmail_app_password(
                os.getenv("EMAIL_ADDRESS", ""), os.getenv("EMAIL_PASSWORD", ""))
            return ("App Password: " + r) if r else (
                "Needs manual generation: myaccount.google.com/apppasswords")
        url_m = re.search(r"https?://\S+", text)
        if url_m:
            nav = self.navigate(url_m.group(0))
            if nav.get("error"):
                return "Navigation error: " + nav["error"]
            return (
                "[" + nav["url"] + "]\n"
                "Title: " + nav["title"] + "\n\n"
                + self.page_content(2000)
            )
        return (
            "WebAutomationAgent v2.0 -- Self-Correction Loop\n"
            "  open https://...      navigate and extract\n"
            "  collect IPs           show cached service IPs\n"
            "  gmail app password    extract Gmail app password\n"
            "  status                agent health check"
        )
