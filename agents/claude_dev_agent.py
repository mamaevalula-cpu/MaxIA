# -*- coding: utf-8 -*-
"""
agents/claude_dev_agent.py — Dev-агент на базе Claude API с tool use.
Экономия токенов: Haiku для анализа, Sonnet для правок, edit_file вместо write_file.
"""
from __future__ import annotations
import json, logging, os, re, subprocess, time
from pathlib import Path
from typing import Any, Dict, Optional
from agents.base_agent import AgentInfo, BaseAgent

log = logging.getLogger("agents.claude_dev")

WORKDIR         = Path("/root/my_personal_ai")
MAX_ITER        = 25
MAX_FILE_LINES  = 300
MAX_TASK_TOKENS    = 150000
CHECKPOINT_F    = WORKDIR / "data" / "dev_checkpoint.json"
MODEL_HAIKU     = "claude-haiku-4-5"
MODEL_SONNET    = "claude-sonnet-4-5"

SYSTEM_PROMPT = (
    """Ты — автономный Python/DevOps инженер. Полные права на сервере.
Сервер: 77.90.2.171 | root | Ubuntu 22.04
Проект: /root/my_personal_ai (персональный ИИ, Python 3.11, FastAPI, asyncio).
brain/ — LLM/оркестратор, agents/ — агенты, core/ — утилиты, data/ — БД SQLite.
Сервис: personal-ai.service (systemctl restart/status personal-ai).
Права: работай с любыми файлами /root/, /etc/. Ставь пакеты pip/apt.
AUTO_APPROVE_ORDERS=true — ордера автоматически без подтверждения.
Делай задачу до конца автономно.

Правила:
1. read_file с lines=100-150 (не весь файл)
2. edit_file для точечных правок (не write_file для больших файлов)
3. run_shell: python3 -m py_compile <файл> после изменений
4. Краткий итог в конце — только что сделано"""
)

SHELL_BLOCKED = [
    r"rm\s+-rf\s+/[^/]", r"rm\s+-rf\s+/\s*$", r"mkfs",
    r":\(\)\{:\|:&\};:", r"dd\s+if=.*of=/dev/",
]

TOOLS_DEF = [
    {
        "name": "read_file",
        "description": "Read file. Use lines=60-100 to save tokens. Always read before editing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "lines": {"type": "integer", "description": "Max lines (default 150)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Surgical edit: replace old_text with new_text. TOKEN-EFFICIENT — prefer over write_file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "write_file",
        "description": "Write complete file. Only for NEW files or small complete rewrites (<80 lines).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_shell",
        "description": "Run shell command: grep, py_compile, systemctl, git, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "list_dir",
        "description": "List directory contents.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        "cache_control": {"type": "ephemeral"},
    },
    {
        "name": "browser_goto",
        "description": "Open URL in headless browser. Use for signup, getting API keys, reading web pages.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]
        }
    },
    {
        "name": "browser_get_text",
        "description": "Get text from current browser page. Use after browser_goto. selector='body' for full page.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": []
        }
    },
    {
        "name": "browser_click",
        "description": "Click element on browser page by CSS selector or text content",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"}
            },
            "required": []
        }
    },
    {
        "name": "browser_fill",
        "description": "Type text into input field in browser",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"}
            },
            "required": ["selector", "value"]
        }
    },
    {
        "name": "browser_get_links",
        "description": "Get all links from current browser page",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "browser_current_url",
        "description": "Get current URL of browser page",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]


def _blocked(cmd: str) -> bool:
    return any(re.search(p, cmd, re.IGNORECASE) for p in SHELL_BLOCKED)


class ClaudeDevAgent(BaseAgent):

    def __init__(self):
        super().__init__("claude_dev")
        self._client = None
        log.info("ClaudeDevAgent initialized")

    def can_handle(self, text: str) -> bool:
        tl = text.lower()
        return any(kw in tl for kw in (
            "исправь", "починить", "почини", "добавь", "настрой",
            "измени код", "обнови код", "задеплой", "деплой",
            "реализуй", "сделай чтобы", "продолжай", "продолжи",
            "напиши агент", "создай агент", "оптимизируй", "рефакторинг",
        ))

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="claude_dev",
            description="Development tasks via Claude API with tool use",
            capabilities=["code_edit", "file_read", "shell_exec", "deploy", "checkpoint"],
        )

    # ── Tools ─────────────────────────────────────────────────────────────

    def _read_file(self, path: str, lines=150) -> str:
        try:
            p = Path(path) if Path(path).is_absolute() else WORKDIR / path
            if p.is_dir():
                return self._list_dir(str(p))
            # Handle string range like '1-80'
            if isinstance(lines, str) and "-" in str(lines):
                parts = str(lines).split("-")
                start, end = int(parts[0]) - 1, int(parts[1])
                txt = p.read_text(encoding="utf-8", errors="replace").splitlines()
                return "\n".join(txt[max(0,start):end])
            lines = int(lines) if lines else 150
            txt = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if len(txt) > lines:
                h = lines // 2
                txt = txt[:h] + [f"... [{len(txt) - lines} lines omitted] ..."] + txt[-h:]
            return "\n".join(txt)
        except Exception as e:
            return f"[read_file error: {e}]"

    def _edit_file(self, path: str, old_text: str, new_text: str) -> str:
        try:
            p = Path(path) if Path(path).is_absolute() else WORKDIR / path
            content = p.read_text(encoding="utf-8", errors="replace")
            if old_text not in content:
                return f"[edit_file: old_text not found in {p.name}]"
            p.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
            return f"OK: edited {p.name}"
        except Exception as e:
            return f"[edit_file error: {e}]"

    def _write_file(self, path: str, content: str) -> str:
        try:
            p = Path(path) if Path(path).is_absolute() else WORKDIR / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"OK: wrote {p.name} ({len(content)} chars)"
        except Exception as e:
            return f"[write_file error: {e}]"

    def _run_shell(self, cmd: str, timeout: int = 30) -> str:
        if _blocked(cmd):
            return "BLOCKED: dangerous command"
        try:
            r = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=str(WORKDIR),
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            out = ((r.stdout or "").strip() + "\n" + (r.stderr or "").strip()).strip()
            return (out or "(no output)")[:2000] + f"\nexit={r.returncode}"
        except subprocess.TimeoutExpired:
            return f"TIMEOUT {timeout}s"
        except Exception as e:
            return f"[shell error: {e}]"


    # ══════════════════════════════════════════════════════
    # BROWSER TOOLS — uses BrowserAgent (Playwright headless)
    # ══════════════════════════════════════════════════════

    def _get_browser(self):
        """Get or start browser agent singleton."""
        try:
            import sys, os
            sys.path.insert(0, "/root/my_personal_ai")
            from browser_agent.agent import BrowserAgent, BrowserMode
            ba = BrowserAgent.get()
            if not ba._running:
                ba.start(BrowserMode.HEADLESS)
            return ba
        except Exception as e:
            return None

    def _browser_action(self, action: str, **params) -> str:
        ba = self._get_browser()
        if not ba:
            return "ERROR: browser not available"
        try:
            res = ba.run_sync(action, **params)
            # ActionResult may have .ok/.success/.data/.error
            ok = getattr(res, "ok", None) or getattr(res, "success", None)
            data = getattr(res, "data", None) or getattr(res, "result", None) or str(res)
            err  = getattr(res, "error", None)
            if err:
                return f"ERROR: {err}"
            return str(data)[:2000] if data else "OK"
        except Exception as e:
            return f"ERROR: {e}"

    def _browser_goto(self, url: str) -> str:
        if not url.startswith("http"):
            url = "https://" + url
        result = self._browser_action("goto", url=url)
        # After navigation, also return page title
        try:
            ba = self._get_browser()
            if ba:
                title_res = ba.run_sync("get_text", selector="title")
                title = getattr(title_res, "data", "") or ""
                url_res = ba.run_sync("current_url")
                cur_url = getattr(url_res, "data", url) or url
                return f"Navigated to: {cur_url}\nPage: {title[:100]}"
        except Exception:
            pass
        return result

    def _browser_get_text(self, selector: str = "body") -> str:
        return self._browser_action("get_text", selector=selector)

    def _browser_click(self, params: dict) -> str:
        return self._browser_action("click", **params)

    def _browser_fill(self, selector: str, value: str) -> str:
        return self._browser_action("fill", selector=selector, value=value)

    def _browser_get_links(self) -> str:
        return self._browser_action("get_links")

    def _browser_screenshot(self) -> str:
        """Take screenshot, save to /tmp/screenshot.png, return path."""
        try:
            ba = self._get_browser()
            if not ba:
                return "ERROR: browser not available"
            res = ba.run_sync("screenshot")
            data = getattr(res, "data", None)
            if data:
                import base64, os
                path = "/tmp/ai_screenshot.png"
                if isinstance(data, str) and data.startswith("/"):
                    return f"Screenshot: {data}"
                # try save base64
                with open(path, "wb") as f:
                    f.write(base64.b64decode(data) if isinstance(data, str) else data)
                return f"Screenshot saved: {path}"
            return "Screenshot taken"
        except Exception as e:
            return f"ERROR: {e}"

    def _browser_current_url(self) -> str:
        return self._browser_action("current_url")


    def _list_dir(self, path: str) -> str:
        try:
            p = Path(path) if Path(path).is_absolute() else WORKDIR / path
            items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            return "\n".join(
                f"{'  ' if e.is_file() else 'd '}{e.name}"
                + (f" ({e.stat().st_size}b)" if e.is_file() else "/")
                for e in items[:60]
            )
        except Exception as e:
            return f"[list_dir error: {e}]"

    def _dispatch(self, name: str, inp: Dict[str, Any]) -> str:
        if name == "read_file":  return self._read_file(inp["path"], inp.get("lines", 150))
        if name == "edit_file":  return self._edit_file(inp["path"], inp["old_text"], inp["new_text"])
        if name == "write_file": return self._write_file(inp["path"], inp["content"])
        if name == "run_shell":  return self._run_shell(inp["cmd"], inp.get("timeout", 30))
        if name == "list_dir":   return self._list_dir(inp["path"])
        if name == "browser_goto":       return self._browser_goto(inp.get("url", ""))
        if name == "browser_get_text":   return self._browser_get_text(inp.get("selector", "body"))
        if name == "browser_click":      return self._browser_click(inp)
        if name == "browser_fill":       return self._browser_fill(inp["selector"], inp["value"])
        if name == "browser_get_links":  return self._browser_get_links()
        if name == "browser_screenshot": return self._browser_screenshot()
        if name == "browser_current_url":return self._browser_current_url()
        return f"Unknown tool: {name}"

    # ── Checkpoint ────────────────────────────────────────────────────────

    def save_checkpoint(self, task: str, summary: str, done: bool = False):
        try:
            CHECKPOINT_F.parent.mkdir(parents=True, exist_ok=True)
            CHECKPOINT_F.write_text(
                json.dumps({"task": task, "summary": summary, "done": done, "ts": time.time()},
                           ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass

    def load_checkpoint(self) -> Optional[Dict]:
        try:
            if CHECKPOINT_F.exists():
                d = json.loads(CHECKPOINT_F.read_text(encoding="utf-8"))
                if time.time() - d.get("ts", 0) < 86400:
                    return d
        except Exception:
            pass
        return None

    def _load_context(self) -> str:
        """Load session context file for продолжай."""
        for candidate in [
            Path("/root/my_personal_ai/data/session_context.md"),
            Path(__file__).parent.parent / "data" / "session_context.md",
            WORKDIR / "data" / "session_context.md",
        ]:
            try:
                if candidate.exists():
                    return candidate.read_text(encoding="utf-8", errors="replace")[:1500]
            except Exception:
                pass
        return ""

    # ── Client ────────────────────────────────────────────────────────────

    def _get_client(self):
        if self._client is None:
            import anthropic
            key = os.getenv("ANTHROPIC_API_KEY", "")
            if not key:
                env_f = WORKDIR / ".env"
                for line in env_f.read_text(errors="replace").splitlines():
                    if line.startswith("ANTHROPIC_API_KEY="):
                        key = line.split("=", 1)[1].strip()
                        break
            self._client = anthropic.Anthropic(api_key=key)
        return self._client

    def _pick_model(self, task: str) -> str:
        change_kw = (
            "исправь", "добавь", "измени", "удали", "создай", "напиши",
            "настрой", "задеплой", "обнови", "fix", "add", "create",
            "write", "implement",
        )
        return MODEL_SONNET if any(kw in task.lower() for kw in change_kw) else MODEL_HAIKU

    # ── Process ───────────────────────────────────────────────────────────

    def process(self, text: str, source: str = "") -> str:
        t0 = time.time()
        log.info("ClaudeDevAgent task: %r", text[:80])

        # "продолжай" — load checkpoint
        if re.search(r"продолжай|продолжи\b|\bcontinue\b", text.lower()):
            cp = self.load_checkpoint()
            if cp and not cp.get("done"):
                task = f"Продолжи задачу: {cp['task']}\nПрогресс: {cp['summary']}"
            elif cp:
                ctx = self._load_context()
                ctx_block = f"\n\nКОНТЕКСТ ПРОЕКТА:\n{ctx}" if ctx else ""
                # Strip accumulated nesting prefixes from previous runs
                prev_task = cp['task']
                prev_task = re.sub(
                    r"^(Предыдущая задача[^:]*:\s*|Продолжи задачу:\s*)+",
                    "", prev_task, flags=re.MULTILINE
                ).strip()[:80]
                task = (
                    f"Предыдущая задача (завершена): {prev_task}\n"
                    f"Итог: {cp['summary'][:150]}{ctx_block}\n\n"
                    "На основе контекста: кратко сообщи что было сделано "
                    "и предложи следующий шаг из TODO (приоритет 1 первым)."
                )
            else:
                ctx = self._load_context()
                if ctx:
                    task = (
                        "Прочитай контекст проекта и предложи следующий шаг из TODO"
                        " (начни с приоритета 1).\n\nКОНТЕКСТ:\n" + ctx[:1500]
                    )
                else:
                    return (
                    "Ещё не было задач. Напиши что нужно, например:\n"
                    "- исправь баг в cache_router\n"
                    "- добавь rate limiting в nginx\n"
                    "- покажи структуру проекта"
                )
        else:
            task = text

        # Governance budget check
        try:
            from core.governance import GovernanceLayer
            ok, reason = GovernanceLayer.get().check_token_budget(task_id="dev", tokens_needed=500)
            if not ok:
                return f"Токен-бюджет исчерпан: {reason}"
        except Exception:
            pass

        client   = self._get_client()
        # For status/summary tasks ("продолжай"), force haiku — no code changes
        _is_status = bool(re.search(r"продолжай|продолжи|continue|кратко сообщи|предложи следующий", text.lower()))
        model    = MODEL_HAIKU if _is_status else self._pick_model(task)
        messages = [{"role": "user", "content": task}]
        total_tokens = 0
        result = ""
        _tools_used = []  # track tool calls for result summary

        try:
            for _iteration in range(MAX_ITER):
                resp = client.messages.create(
                    model=model,
                    max_tokens=4096,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"}
                        }
                    ],
                    tools=TOOLS_DEF,
                    messages=messages,
                )
                _cache_read = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
                _cache_created = getattr(resp.usage, "cache_creation_input_tokens", 0) or 0
                total_tokens += resp.usage.input_tokens + resp.usage.output_tokens
                log.info("Iter %d: stop=%s in=%d out=%d total=%d cache_read=%d cache_new=%d",
                         _iteration, resp.stop_reason,
                         resp.usage.input_tokens, resp.usage.output_tokens, total_tokens,
                         _cache_read, _cache_created)

                if resp.stop_reason == "end_turn":
                    for blk in resp.content:
                        if hasattr(blk, "text") and blk.text:
                            result = blk.text
                    # Fallback: if Claude returned no text, build summary from tools
                    if not result and _tools_used:
                        result = "✅ Выполнено. Инструменты: " + ", ".join(_tools_used[-8:])
                    elif not result:
                        result = "✅ Задача выполнена."
                    break

                if resp.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": resp.content})
                    tool_results = []
                    for blk in resp.content:
                        if blk.type == "tool_use":
                            _tool_label = f"{blk.name}({str(blk.input.get('path', blk.input.get('cmd', '')))[:30]})"
                            _tools_used.append(_tool_label)
                            log.info("Tool %s: %s", blk.name, str(blk.input)[:80])
                            out = self._dispatch(blk.name, blk.input)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": blk.id,
                                "content": out[:3000],
                            })
                    messages.append({"role": "user", "content": tool_results})
                    if total_tokens > MAX_TASK_TOKENS:
                        result = result or ("Выполнено (бюджет исчерпан). Сделано: " + ", ".join(_tools_used[-5:]))
                        break
                elif resp.stop_reason in ("max_tokens", "stop_sequence"):
                    # Claude hit output limit — collect any partial text
                    for blk in resp.content:
                        if hasattr(blk, "text") and blk.text:
                            result = (result or "") + blk.text
                    if not result:
                        result = ("⚠️ Ответ обрезан. Инструменты: " + ", ".join(_tools_used[-5:])) if _tools_used else "⚠️ Ответ обрезан."
                    break
                else:
                    # Unknown stop_reason — log and break
                    result = result or ("✅ Готово. Использованы: " + ", ".join(_tools_used)) if _tools_used else (result or "✅ Готово.")
                    break

            # Loop exhausted all iterations — build result from tool history
            if not result:
                if _tools_used:
                    result = "⚠️ Достигнут лимит итераций. Выполнено: " + ", ".join(_tools_used[-8:])
                else:
                    result = "⚠️ Задача не завершена за " + str(MAX_ITER) + " итераций."

        except Exception as e:
            log.error("ClaudeDevAgent error: %s", e)
            result = result or f"Ошибка Claude API: {e}"

        elapsed = round((time.time() - t0) * 1000)
        model_s = "haiku" if "haiku" in model else "sonnet"

        # Report to governance
        try:
            from core.governance import GovernanceLayer
            GovernanceLayer.get().record_token_usage(
                session_id="dev_agent", task_id="dev",
                tokens=total_tokens, provider="claude",
            )
        except Exception:
            pass

        # Save clean task to avoid checkpoint nesting on next "продолжай"
        _ckpt_task = text if re.search(r"продолжай|продолжи|continue", text.lower()) else task
        self.save_checkpoint(_ckpt_task, result or "completed", done=True)
        # Absolute safety net — result can never be empty
        if not result:
            result = (
                "✅ Сделано: " + ", ".join(_tools_used[-8:])
            ) if _tools_used else "✅ Задача обработана."
        return f"{result}\n\n_Claude {model_s} · {total_tokens} токенов · {elapsed}ms_"