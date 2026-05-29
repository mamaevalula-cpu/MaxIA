# -*- coding: utf-8 -*-
"""
core/agent_harness.py — ReAct (Reason + Act) agentic loop.

Превращает одну задачу в серию LLM-вызовов + инструментов.
Эквивалент Claude Code: получает задачу → думает → выбирает инструмент →
исполняет → наблюдает результат → повторяет до завершения.

Архитектура:
    AgentHarness.run(task) → HarnessResult
        ├── LLM: "что делать?" → ToolCall | FinalAnswer
        ├── ToolRouter: dispatch → FileTools | GitTools | ShellTool
        ├── Observation: передать результат обратно в LLM
        └── Сохранить урок в memory/lessons.json

Использование:
    from core.agent_harness import AgentHarness
    harness = AgentHarness()
    result = await harness.run("Найди все TODO в проекте и создай отчёт todo_report.md")
    print(result.answer)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("core.agent_harness")

BASE_DIR = Path(__file__).parent.parent
LESSONS_FILE = BASE_DIR / "memory" / "lessons.json"

# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """LLM requested a tool execution."""
    name: str
    params: Dict[str, Any]
    reasoning: str = ""


@dataclass
class StepResult:
    """One ReAct iteration."""
    step: int
    tool_call: Optional[ToolCall]
    observation: str
    is_final: bool = False
    final_answer: str = ""
    elapsed_ms: float = 0.0


@dataclass
class HarnessResult:
    """Final result of a full agentic run."""
    ok: bool
    answer: str
    steps: List[StepResult] = field(default_factory=list)
    total_ms: float = 0.0
    error: str = ""
    task: str = ""

    def summary(self) -> str:
        lines = [f"Task: {self.task[:80]}", f"Steps: {len(self.steps)}", f"Time: {self.total_ms:.0f}ms"]
        if not self.ok:
            lines.append(f"Error: {self.error}")
        lines.append(f"Answer: {self.answer[:300]}")
        return "\n".join(lines)


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an autonomous coding agent. You have access to tools to read, write, \
edit, search files, run git commands, and execute shell commands.

Think step by step. For each step:
1. Reason about what to do next (THOUGHT)
2. Choose a tool (ACTION) or declare you are done (FINAL)

ALWAYS respond with VALID JSON in one of these two formats:

If you need to use a tool:
{
  "thought": "I need to...",
  "action": "tool_name",
  "params": {"param1": "value1", "param2": "value2"}
}

If you have completed the task:
{
  "thought": "I have finished because...",
  "action": "FINAL",
  "answer": "Complete answer to the task..."
}

Available tools:
{tools_manifest}

Rules:
- Always read a file before editing it
- Never guess file contents — read first
- If a tool returns an error, try to fix the problem before giving up
- Be concise in thoughts but thorough in actions
- For FINAL answer, summarize what you did and the result
"""

# ── Tool router ───────────────────────────────────────────────────────────────


class ToolRouter:
    """Dispatches tool calls to the correct implementation."""

    def __init__(self) -> None:
        self._registry: Dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        from core.file_tools import FileTools
        ft = FileTools.get()

        self.register("read_file",   lambda p: ft.read(p["path"], p.get("offset", 0), p.get("limit", 200)))
        self.register("write_file",  lambda p: ft.write(p["path"], p["content"]))
        self.register("edit_file",   lambda p: ft.edit(p["path"], p["old_string"], p["new_string"], p.get("replace_all", False)))
        self.register("glob_files",  lambda p: ft.glob(p["pattern"], p.get("base", "")))
        self.register("grep_files",  lambda p: ft.grep(p["pattern"], p.get("path", ""), p.get("file_type", "")))
        self.register("list_dir",    lambda p: ft.ls(p.get("path", "")))
        self.register("backup_file", lambda p: ft.backup(p["path"]))

        try:
            from core.git_tools import GitTools
            gt = GitTools.get()
            self.register("git_status",   lambda p: gt.status())
            self.register("git_diff",     lambda p: gt.diff(p.get("path", ""), p.get("staged", False)))
            self.register("git_log",      lambda p: gt.log(p.get("n", 10), p.get("oneline", True)))
            self.register("git_add",      lambda p: gt.add(p.get("paths", [])))
            self.register("git_commit",   lambda p: gt.commit(p["message"]))
            self.register("git_branch",   lambda p: gt.branch())
        except ImportError:
            log.debug("git_tools not available yet")

        # -- Shell tool: run arbitrary shell commands -------------------------
        import subprocess as _sp
        def _shell(p: dict) -> str:
            cmd = p.get("cmd") or p.get("command") or ""
            if not cmd:
                return "ERROR: cmd param required"
            timeout_s = int(p.get("timeout", 30))
            try:
                r = _sp.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout_s)
                out = (r.stdout or "").strip()
                err = (r.stderr or "").strip()
                combined = out
                if err:
                    combined += (chr(10) + "[stderr] " + err) if out else ("[stderr] " + err)
                return combined[:3000] or "(no output)"
            except _sp.TimeoutExpired:
                return "ERROR: command timed out after {}s".format(timeout_s)
            except Exception as e:
                return "ERROR: {}".format(e)
        self.register("shell", _shell)
        self.register("run_command", _shell)

    def register(self, name: str, fn: Callable) -> None:
        self._registry[name] = fn

    def dispatch(self, call: ToolCall) -> str:
        fn = self._registry.get(call.name)
        if fn is None:
            return f"ERROR: Unknown tool '{call.name}'. Available: {list(self._registry.keys())}"
        try:
            result = fn(call.params)
            if hasattr(result, "ok"):
                if result.ok:
                    return result.output or "OK (no output)"
                else:
                    return f"ERROR: {result.error}"
            return str(result)
        except Exception as e:
            log.error("Tool dispatch error [%s]: %s", call.name, e)
            return f"ERROR: {e}\n{traceback.format_exc(limit=3)}"

    def manifest(self) -> str:
        from core.file_tools import FileTools
        tools = FileTools.tools_manifest()
        try:
            from core.git_tools import GitTools
            tools += GitTools.tools_manifest()
        except ImportError:
            pass
        return json.dumps(tools, ensure_ascii=False, indent=2)


# ── Lesson memory ─────────────────────────────────────────────────────────────


class LessonMemory:
    """Persists learned lessons to disk for future runs."""

    def __init__(self, path: Path = LESSONS_FILE) -> None:
        self._path = path
        self._lessons: List[dict] = self._load()

    def _load(self) -> List[dict]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text("utf-8"))
            except Exception:
                return []
        return []

    def save(self, task: str, result: HarnessResult) -> None:
        if not result.ok:
            return
        lesson = {
            "ts": time.time(),
            "task": task[:200],
            "steps": len(result.steps),
            "answer_summary": result.answer[:300],
            "tools_used": [s.tool_call.name for s in result.steps if s.tool_call and not s.is_final],
        }
        self._lessons.append(lesson)
        self._lessons = self._lessons[-100:]  # keep last 100
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._lessons, ensure_ascii=False, indent=2), "utf-8")

    def recent(self, n: int = 5) -> List[dict]:
        return self._lessons[-n:]


# ── LLM response parser ───────────────────────────────────────────────────────


def _parse_llm_response(text: str) -> Optional[dict]:
    """Extract JSON from LLM response, handling markdown code fences."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    return None


# ── AgentHarness ──────────────────────────────────────────────────────────────


class AgentHarness:
    """
    ReAct loop: task → think → act → observe → repeat → answer.

    Usage:
        harness = AgentHarness()
        result = await harness.run("Find all .py files with TODO and list them")
        print(result.answer)
    """

    def __init__(
        self,
        max_steps: int = 20,
        step_timeout: float = 60.0,
        on_step: Optional[Callable[[StepResult], None]] = None,
    ) -> None:
        self.max_steps = max_steps
        self.step_timeout = step_timeout
        self.on_step = on_step  # callback for UI / Telegram progress updates
        self._router = ToolRouter()
        self._memory = LessonMemory()

    def register_tool(self, name: str, fn: Callable) -> None:
        """Register additional tool at runtime."""
        self._router.register(name, fn)

    # ── Main entry ────────────────────────────────────────────────────────────

    async def run(
        self,
        task: str,
        extra_context: str = "",
        model_override: Optional[str] = None,
    ) -> HarnessResult:
        """Execute a task using the ReAct loop."""
        t0 = time.monotonic()
        steps: List[StepResult] = []

        # Build conversation history
        system_prompt = _SYSTEM_PROMPT.replace("{tools_manifest}", self._router.manifest())
        messages = [{"role": "user", "content": self._build_user_prompt(task, extra_context)}]

        log.info("AgentHarness.run: %s", task[:80])

        for step_num in range(1, self.max_steps + 1):
            step_t0 = time.monotonic()

            # ── LLM call ──────────────────────────────────────────────────────
            try:
                llm_text = await asyncio.wait_for(
                    self._llm_call(system_prompt, messages, model_override),
                    timeout=self.step_timeout,
                )
            except asyncio.TimeoutError:
                err = f"LLM timeout at step {step_num}"
                log.error(err)
                return HarnessResult(ok=False, answer="", error=err, steps=steps,
                                     total_ms=(time.monotonic()-t0)*1000, task=task)
            except Exception as e:
                err = f"LLM error at step {step_num}: {e}"
                log.error(err)
                return HarnessResult(ok=False, answer="", error=err, steps=steps,
                                     total_ms=(time.monotonic()-t0)*1000, task=task)

            # ── Parse response ────────────────────────────────────────────────
            parsed = _parse_llm_response(llm_text)
            if parsed is None:
                observation = f"ERROR: Could not parse LLM response as JSON: {llm_text[:200]}"
                messages.append({"role": "assistant", "content": llm_text})
                messages.append({"role": "user", "content": f"Observation: {observation}\n\nPlease respond with valid JSON."})
                sr = StepResult(step=step_num, tool_call=None, observation=observation,
                                elapsed_ms=(time.monotonic()-step_t0)*1000)
                steps.append(sr)
                if self.on_step:
                    self.on_step(sr)
                continue

            action = parsed.get("action", "")
            thought = parsed.get("thought", "")

            # ── FINAL answer ──────────────────────────────────────────────────
            if action == "FINAL":
                answer = parsed.get("answer", thought)
                sr = StepResult(
                    step=step_num,
                    tool_call=None,
                    observation="Task completed.",
                    is_final=True,
                    final_answer=answer,
                    elapsed_ms=(time.monotonic()-step_t0)*1000,
                )
                steps.append(sr)
                if self.on_step:
                    self.on_step(sr)

                result = HarnessResult(
                    ok=True,
                    answer=answer,
                    steps=steps,
                    total_ms=(time.monotonic()-t0)*1000,
                    task=task,
                )
                self._memory.save(task, result)
                log.info("Task done in %d steps (%.0fms)", step_num, result.total_ms)
                return result

            # ── Tool call ─────────────────────────────────────────────────────
            tool_call = ToolCall(
                name=action,
                params=parsed.get("params", {}),
                reasoning=thought,
            )

            observation = self._router.dispatch(tool_call)
            observation = observation[:4000]  # truncate very long outputs

            elapsed = (time.monotonic()-step_t0)*1000
            sr = StepResult(
                step=step_num,
                tool_call=tool_call,
                observation=observation,
                elapsed_ms=elapsed,
            )
            steps.append(sr)
            if self.on_step:
                self.on_step(sr)

            log.debug("Step %d: %s → %s chars (%.0fms)",
                      step_num, action, len(observation), elapsed)

            # Add to conversation
            messages.append({"role": "assistant", "content": llm_text})
            messages.append({
                "role": "user",
                "content": f"Observation from {action}:\n{observation}"
            })

        # max_steps exceeded
        err = f"Reached max_steps={self.max_steps} without completing task"
        log.warning(err)
        return HarnessResult(ok=False, answer="", error=err, steps=steps,
                             total_ms=(time.monotonic()-t0)*1000, task=task)

    # ── LLM call ─────────────────────────────────────────────────────────────

    async def _llm_call(
        self,
        system: str,
        messages: List[dict],
        model_override: Optional[str],
    ) -> str:
        """Call the LLM via BrainOrchestrator's router (sync wrapped in thread)."""
        # Build flat prompt from conversation history
        history = "\n".join(
            f"[{m['role'].upper()}] {m['content']}" for m in messages
        )
        full_prompt = f"{system}\n\n{history}"

        # Run sync LLMRouter.ask_simple in a thread so we don't block the event loop
        loop = asyncio.get_event_loop()
        try:
            from brain.llm_router import LLMRouter, LLMRequest
            router = LLMRouter.get()

            preferred = None
            if model_override:
                from core.config import LLMProvider
                try:
                    preferred = LLMProvider(model_override)
                except ValueError:
                    pass

            req = LLMRequest(
                messages=messages,
                system=system,
                max_tokens=4096,
                temperature=0.3,
                task_type="agent",
                preferred_provider=preferred,
            )

            response = await loop.run_in_executor(None, router.ask, req)
            if response.success and response.content:
                return response.content
            if response.error:
                raise RuntimeError(response.error)
            raise RuntimeError("LLMRouter returned empty response")

        except ImportError:
            pass

        # Fallback: direct anthropic async call
        try:
            import anthropic
            import os
            client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
            msg = await client.messages.create(
                model=model_override or "claude-3-5-sonnet-20241022",
                max_tokens=4096,
                system=system,
                messages=messages,
            )
            return msg.content[0].text
        except Exception as e:
            raise RuntimeError(f"LLM unavailable: {e}") from e

    # ── Helper ────────────────────────────────────────────────────────────────

    def _build_user_prompt(self, task: str, extra_context: str) -> str:
        parts = [f"Task: {task}"]
        if extra_context:
            parts.append(f"\nAdditional context:\n{extra_context}")

        lessons = self._memory.recent(3)
        if lessons:
            parts.append("\nRecent successful patterns (for reference):")
            for l in lessons:
                parts.append(f"  - {l['task'][:80]} → {l['steps']} steps, tools: {l['tools_used']}")

        return "\n".join(parts)

    # ── Sync wrapper ──────────────────────────────────────────────────────────

    def run_sync(self, task: str, extra_context: str = "") -> HarnessResult:
        """Blocking wrapper for non-async callers."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(1) as pool:
                    future = pool.submit(asyncio.run, self.run(task, extra_context))
                    return future.result(timeout=self.step_timeout * self.max_steps)
            else:
                return loop.run_until_complete(self.run(task, extra_context))
        except Exception as e:
            return HarnessResult(ok=False, answer="", error=str(e), task=task)


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[AgentHarness] = None


def get_harness(on_step: Optional[Callable] = None) -> AgentHarness:
    global _instance
    if _instance is None:
        _instance = AgentHarness(on_step=on_step)
    elif on_step is not None:
        _instance.on_step = on_step
    return _instance
