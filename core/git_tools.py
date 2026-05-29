# -*- coding: utf-8 -*-
"""
core/git_tools.py — Git operations for the agent harness.

Предоставляет git diff/status/log/add/commit/branch как инструменты
для AgentHarness. Аналог git-команд в Claude Code.

Использование:
    from core.git_tools import GitTools
    gt = GitTools.get()
    result = gt.status()
    result = gt.diff("agents/telegram_agent.py")
    result = gt.commit("fix: correct message queue logic")
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("core.git_tools")

BASE_DIR = Path(__file__).parent.parent


@dataclass
class GitResult:
    ok: bool
    output: str
    error: str = ""

    def __bool__(self) -> bool:
        return self.ok

    def short(self, n: int = 500) -> str:
        return self.output[:n] + ("…" if len(self.output) > n else "")


def _run(args: List[str], cwd: Path = BASE_DIR) -> GitResult:
    """Execute a git command, return GitResult."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0:
            return GitResult(ok=True, output=proc.stdout.strip())
        else:
            return GitResult(ok=False, output=proc.stdout.strip(), error=proc.stderr.strip())
    except FileNotFoundError:
        return GitResult(ok=False, output="", error="git not found in PATH")
    except subprocess.TimeoutExpired:
        return GitResult(ok=False, output="", error="git command timed out")
    except Exception as e:
        return GitResult(ok=False, output="", error=str(e))


class GitTools:
    """
    Git operations as structured tool calls.
    Singleton via .get().
    """

    _instance: Optional["GitTools"] = None

    def __init__(self, repo_dir: Path = BASE_DIR) -> None:
        self._dir = repo_dir

    @classmethod
    def get(cls) -> "GitTools":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> GitResult:
        """Show working tree status (short format)."""
        return _run(["status", "--short"], self._dir)

    def status_full(self) -> GitResult:
        """Show full git status."""
        return _run(["status"], self._dir)

    # ── Diff ──────────────────────────────────────────────────────────────────

    def diff(self, path: str = "", staged: bool = False) -> GitResult:
        """Show diff of unstaged (or staged) changes."""
        args = ["diff"]
        if staged:
            args.append("--cached")
        args += ["--stat", "--patch"]
        if path:
            args += ["--", path]
        r = _run(args, self._dir)
        if r.ok and not r.output:
            r.output = "(no changes)"
        return r

    def diff_stat(self) -> GitResult:
        """Show only diffstat (files changed, insertions, deletions)."""
        return _run(["diff", "--stat"], self._dir)

    # ── Log ───────────────────────────────────────────────────────────────────

    def log(self, n: int = 10, oneline: bool = True) -> GitResult:
        """Show recent commit log."""
        fmt = "--oneline" if oneline else "--pretty=format:%h %ad %s (%an)"
        args = ["log", fmt, f"-{n}"]
        if not oneline:
            args += ["--date=short"]
        return _run(args, self._dir)

    def log_file(self, path: str, n: int = 5) -> GitResult:
        """Show commits that touched a specific file."""
        return _run(["log", "--oneline", f"-{n}", "--", path], self._dir)

    # ── Branch ───────────────────────────────────────────────────────────────

    def branch(self) -> GitResult:
        """List all branches (current marked with *)."""
        return _run(["branch", "-a"], self._dir)

    def current_branch(self) -> GitResult:
        """Get current branch name."""
        return _run(["rev-parse", "--abbrev-ref", "HEAD"], self._dir)

    def checkout(self, branch_name: str, create: bool = False) -> GitResult:
        """Checkout existing branch, or create new one."""
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(branch_name)
        return _run(args, self._dir)

    # ── Stage + Commit ────────────────────────────────────────────────────────

    def add(self, paths: Optional[List[str]] = None) -> GitResult:
        """Stage files. If paths is empty, stage all changes."""
        if not paths:
            return _run(["add", "-A"], self._dir)
        return _run(["add"] + paths, self._dir)

    def commit(self, message: str) -> GitResult:
        """Create a commit with the given message."""
        if not message.strip():
            return GitResult(ok=False, output="", error="Commit message cannot be empty")
        return _run(["commit", "-m", message], self._dir)

    def add_and_commit(self, message: str, paths: Optional[List[str]] = None) -> GitResult:
        """Stage files and commit in one step."""
        add_result = self.add(paths)
        if not add_result.ok:
            return add_result
        return self.commit(message)

    # ── Stash ─────────────────────────────────────────────────────────────────

    def stash(self, message: str = "") -> GitResult:
        args = ["stash", "push"]
        if message:
            args += ["-m", message]
        return _run(args, self._dir)

    def stash_pop(self) -> GitResult:
        return _run(["stash", "pop"], self._dir)

    def stash_list(self) -> GitResult:
        return _run(["stash", "list"], self._dir)

    # ── Remote ────────────────────────────────────────────────────────────────

    def remote_url(self) -> GitResult:
        return _run(["remote", "get-url", "origin"], self._dir)

    def fetch(self) -> GitResult:
        return _run(["fetch", "--all", "--prune"], self._dir)

    # ── Init ─────────────────────────────────────────────────────────────────

    def init(self) -> GitResult:
        """Initialize a git repo in BASE_DIR if not already one."""
        return _run(["init"], self._dir)

    def is_repo(self) -> bool:
        r = _run(["rev-parse", "--git-dir"], self._dir)
        return r.ok

    # ── Tools manifest (for AgentHarness) ────────────────────────────────────

    @staticmethod
    def tools_manifest() -> List[dict]:
        return [
            {
                "name": "git_status",
                "description": "Show git working tree status (short format). No params needed.",
                "params": {},
            },
            {
                "name": "git_diff",
                "description": "Show diff of unstaged changes. Optionally filter by file path.",
                "params": {"path": "str=''", "staged": "bool=false"},
            },
            {
                "name": "git_log",
                "description": "Show recent git commit log.",
                "params": {"n": "int=10", "oneline": "bool=true"},
            },
            {
                "name": "git_add",
                "description": "Stage files for commit. Pass paths=[] to stage all.",
                "params": {"paths": "list[str]=[]"},
            },
            {
                "name": "git_commit",
                "description": "Create a git commit. message is required.",
                "params": {"message": "str"},
            },
            {
                "name": "git_branch",
                "description": "List all git branches.",
                "params": {},
            },
        ]
