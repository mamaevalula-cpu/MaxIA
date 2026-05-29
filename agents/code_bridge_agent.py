#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
agents/code_bridge_agent.py — Master Controller Code Bridge.

Bridges the AI panel to the server filesystem, terminal and codebase.
Replaces Claude Code CLI — all operations go through this agent.

Capabilities:
  • Read / write / create / delete files
  • Execute shell commands (bash/python)
  • Search codebase (grep, file index)
  • Git operations (status, diff, commit, log)
  • Project audit and context snapshots
  • Process management (start/stop/status services)
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.base_agent import AgentInfo, BaseAgent

log = logging.getLogger("agents.code_bridge")

# Safety: these prefixes are always allowed
SAFE_ROOTS = [
    "/root/my_personal_ai",
    "/root/bybit-bot",
    "/tmp",
    "/var/log",
    "/root",
]

# Commands that are always blocked
BLOCKED_CMDS = [
    "rm -rf /", "mkfs", "dd if=", ":(){:|:&};:", "chmod 777 /",
    "curl | sh", "wget | sh", "bash <(", "> /dev/sda",
]

# Max output length
MAX_OUTPUT = 8000


class CodeBridgeAgent(BaseAgent):
    """Master Controller — bridges AI panel to server filesystem and terminal."""

    name = "code_bridge"
    description = "File system, terminal, git, code search — full server control from AI panel."

    def __init__(self):
        super().__init__("code_bridge")
        self._history: List[Dict] = []   # command history
        self._cwd = "/root/my_personal_ai"

    # ── Abstract method implementations ──────────────────────────────────────

    def can_handle(self, text: str) -> bool:
        text_lower = text.lower()
        keywords = [
            "файл", "file", "читай", "read", "запиши", "write", "создай",
            "terminal", "терминал", "команда", "command", "bash", "python",
            "git", "код", "code", "проект", "project", "директория", "dir",
            "папка", "folder", "поиск в коде", "grep", "индекс", "deploy",
            "restart", "перезапусти", "запусти скрипт",
        ]
        return any(kw in text_lower for kw in keywords)

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="code_bridge",
            description="Master Controller: file system, terminal, git, code search.",
            capabilities=[
                "file_read", "file_write", "file_create", "file_delete",
                "terminal_exec", "bash_exec", "python_exec",
                "git_status", "git_diff", "git_commit", "git_log",
                "code_search", "file_index", "project_audit",
                "service_restart", "process_list",
            ],
            version="1.0.0",
        )

    # ── File Operations ───────────────────────────────────────────────────────

    def read_file(self, path: str) -> Dict[str, Any]:
        """Read file content."""
        p = Path(path).resolve()
        if not self._is_safe_path(str(p)):
            return {"error": f"Path not in allowed roots: {path}"}
        try:
            if not p.exists():
                return {"error": f"File not found: {path}"}
            if p.is_dir():
                return self.list_dir(str(p))
            size = p.stat().st_size
            if size > 500_000:
                return {"error": f"File too large: {size} bytes. Use search instead."}
            content = p.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            return {
                "path": str(p),
                "content": content[:MAX_OUTPUT],
                "lines": len(lines),
                "size": size,
                "truncated": len(content) > MAX_OUTPUT,
            }
        except Exception as e:
            return {"error": str(e)}

    def write_file(self, path: str, content: str, mode: str = "w") -> Dict[str, Any]:
        """Write/create file."""
        p = Path(path).resolve()
        if not self._is_safe_path(str(p)):
            return {"error": f"Path not in allowed roots: {path}"}
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            if mode == "a":
                p.open("a", encoding="utf-8").write(content)
            else:
                p.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(p), "size": p.stat().st_size}
        except Exception as e:
            return {"error": str(e)}

    def list_dir(self, path: str = None) -> Dict[str, Any]:
        """List directory contents."""
        p = Path(path or self._cwd).resolve()
        if not self._is_safe_path(str(p)):
            return {"error": f"Path not allowed: {path}"}
        try:
            if not p.exists():
                return {"error": f"Directory not found: {path}"}
            items = []
            for item in sorted(p.iterdir()):
                try:
                    stat = item.stat()
                    items.append({
                        "name": item.name,
                        "type": "dir" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else None,
                        "modified": stat.st_mtime,
                    })
                except Exception:
                    pass
            return {"path": str(p), "items": items, "count": len(items)}
        except Exception as e:
            return {"error": str(e)}

    def delete_file(self, path: str) -> Dict[str, Any]:
        """Delete file (not directories)."""
        p = Path(path).resolve()
        if not self._is_safe_path(str(p)):
            return {"error": f"Path not allowed: {path}"}
        try:
            if not p.exists():
                return {"error": "File not found"}
            if p.is_dir():
                return {"error": "Use specific dir removal — refusing to delete directory"}
            p.unlink()
            return {"ok": True, "deleted": str(p)}
        except Exception as e:
            return {"error": str(e)}

    # ── Terminal ──────────────────────────────────────────────────────────────

    def exec_command(self, cmd: str, cwd: str = None, timeout: int = 30) -> Dict[str, Any]:
        """Execute shell command safely."""
        # Safety check
        cmd_lower = cmd.lower().strip()
        for blocked in BLOCKED_CMDS:
            if blocked in cmd_lower:
                return {"error": f"Blocked command pattern: {blocked}"}

        work_dir = cwd or self._cwd
        if not self._is_safe_path(work_dir):
            work_dir = self._cwd

        t0 = time.time()
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True,
                cwd=work_dir, timeout=timeout,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
            elapsed = round((time.time() - t0) * 1000)
            out = result.stdout[:MAX_OUTPUT]
            err = result.stderr[:2000]
            entry = {
                "cmd": cmd, "cwd": work_dir,
                "exit_code": result.returncode,
                "stdout": out, "stderr": err,
                "duration_ms": elapsed,
                "ts": time.time(),
            }
            self._history.append(entry)
            if len(self._history) > 100:
                self._history = self._history[-100:]
            log.info("exec [%d] %s | %dms", result.returncode, cmd[:60], elapsed)
            return entry
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s", "cmd": cmd}
        except Exception as e:
            return {"error": str(e), "cmd": cmd}

    def exec_python(self, code: str, timeout: int = 30) -> Dict[str, Any]:
        """Execute Python code snippet."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False,
                                         encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
        try:
            return self.exec_command(
                f"/root/venv/bin/python3 {tmp}", timeout=timeout
            )
        finally:
            Path(tmp).unlink(missing_ok=True)

    # ── Git Operations ────────────────────────────────────────────────────────

    def git_status(self, repo: str = None) -> Dict[str, Any]:
        """Git status of a repository."""
        repo = repo or self._cwd
        r = self.exec_command("git status --short", cwd=repo, timeout=10)
        diff = self.exec_command("git diff --stat HEAD 2>/dev/null | tail -5", cwd=repo, timeout=10)
        branch = self.exec_command("git branch --show-current 2>/dev/null", cwd=repo, timeout=5)
        return {
            "repo": repo,
            "branch": branch.get("stdout", "").strip(),
            "status": r.get("stdout", ""),
            "diff_stat": diff.get("stdout", ""),
            "error": r.get("error"),
        }

    def git_log(self, repo: str = None, n: int = 10) -> Dict[str, Any]:
        """Recent git commits."""
        repo = repo or self._cwd
        r = self.exec_command(
            f"git log --oneline -n {n} 2>/dev/null", cwd=repo, timeout=10
        )
        return {"repo": repo, "log": r.get("stdout", ""), "error": r.get("error")}

    def git_diff(self, repo: str = None, file: str = "") -> Dict[str, Any]:
        """Git diff."""
        repo = repo or self._cwd
        cmd = f"git diff HEAD {file}".strip()
        r = self.exec_command(cmd, cwd=repo, timeout=15)
        return {"repo": repo, "diff": r.get("stdout", "")[:6000]}

    # ── Code Search ───────────────────────────────────────────────────────────

    def search_code(self, query: str, path: str = None, pattern: str = "*.py") -> Dict[str, Any]:
        """Search in codebase."""
        search_path = path or self._cwd
        if not self._is_safe_path(search_path):
            search_path = self._cwd
        # Use ripgrep if available, else grep
        rg = subprocess.run("which rg", shell=True, capture_output=True).returncode == 0
        if rg:
            cmd = f"rg -n --max-count=5 --glob '{pattern}' {shlex.quote(query)} {search_path} 2>/dev/null | head -50"
        else:
            cmd = f"grep -rn --include='{pattern}' {shlex.quote(query)} {search_path} 2>/dev/null | head -50"
        r = self.exec_command(cmd, timeout=15)
        lines = [l for l in r.get("stdout", "").split("\n") if l.strip()]
        return {
            "query": query,
            "path": search_path,
            "matches": lines,
            "count": len(lines),
        }

    def file_index(self, path: str = None, ext: str = ".py") -> Dict[str, Any]:
        """Index all files of given extension."""
        search_path = path or self._cwd
        cmd = f"find {search_path} -name '*{ext}' -not -path '*/.*' -not -path '*/venv/*' 2>/dev/null | sort | head -200"
        r = self.exec_command(cmd, timeout=10)
        files = [l for l in r.get("stdout", "").split("\n") if l.strip()]
        return {"path": search_path, "ext": ext, "files": files, "count": len(files)}

    # ── Project Audit ─────────────────────────────────────────────────────────

    def audit_project(self, project_path: str) -> Dict[str, Any]:
        """Create context snapshot for a project."""
        p = Path(project_path)
        if not p.exists():
            return {"error": f"Project not found: {project_path}"}

        snap: Dict[str, Any] = {
            "path": str(p),
            "name": p.name,
            "audited_at": time.time(),
        }

        # Tech stack detection
        stack = []
        if (p / "requirements.txt").exists():
            reqs = (p / "requirements.txt").read_text(errors="replace")[:500]
            stack.append(f"Python: {reqs[:200]}")
        if (p / "package.json").exists():
            pkg = json.loads((p / "package.json").read_text(errors="replace"))
            stack.append(f"Node: {pkg.get('name')} v{pkg.get('version')}")
        if (p / "go.mod").exists():
            stack.append("Go")
        if (p / "Cargo.toml").exists():
            stack.append("Rust")
        snap["stack"] = stack

        # File count by extension
        r = self.exec_command(
            f"find {str(p)} -not -path '*/.*' -not -path '*/venv/*' -not -path '*/node_modules/*' "
            f"-type f | sed 's/.*\\.//' | sort | uniq -c | sort -rn | head -10",
            timeout=10
        )
        snap["file_types"] = r.get("stdout", "").strip()

        # Recent changes
        git_log = self.git_log(str(p), n=5)
        snap["recent_commits"] = git_log.get("log", "No git history")

        # TODO/FIXME count
        r = self.exec_command(
            f"grep -rn 'TODO\\|FIXME\\|HACK\\|XXX' {str(p)} --include='*.py' 2>/dev/null | wc -l",
            timeout=10
        )
        snap["todo_count"] = r.get("stdout", "0").strip()

        # Main entry points
        entries = []
        for ep in ["main.py", "app.py", "server.py", "index.py", "manage.py"]:
            if (p / ep).exists():
                entries.append(ep)
        snap["entry_points"] = entries

        # Size
        r = self.exec_command(f"du -sh {str(p)} 2>/dev/null | cut -f1", timeout=5)
        snap["disk_size"] = r.get("stdout", "?").strip()

        return snap

    # ── Process Management ────────────────────────────────────────────────────

    def service_status(self, service: str) -> Dict[str, Any]:
        """Check systemd service status."""
        r = self.exec_command(f"systemctl is-active {service} && systemctl show {service} --property=MainPID,ActiveState,SubState", timeout=5)
        return {"service": service, "output": r.get("stdout", ""), "error": r.get("error")}

    def service_restart(self, service: str) -> Dict[str, Any]:
        """Restart systemd service."""
        r = self.exec_command(f"systemctl restart {service}", timeout=30)
        time.sleep(3)
        status = self.service_status(service)
        return {"restarted": True, "service": service, "status": status}

    def process_list(self) -> List[Dict]:
        """List running Python/Node processes."""
        r = self.exec_command("ps aux --no-headers | grep -E 'python|node|gunicorn' | grep -v grep | head -20", timeout=5)
        procs = []
        for line in r.get("stdout", "").split("\n"):
            if line.strip():
                parts = line.split()
                if len(parts) >= 11:
                    procs.append({
                        "pid": parts[1],
                        "cpu": parts[2],
                        "mem": parts[3],
                        "cmd": " ".join(parts[10:])[:80],
                    })
        return procs

    def get_history(self) -> List[Dict]:
        """Return command history."""
        return list(reversed(self._history[-20:]))

    # ── Main Dispatcher ───────────────────────────────────────────────────────

    def process(self, text: str, source: str = "user", **kwargs) -> str:
        """Process code bridge command."""
        text_lower = text.lower().strip()

        # Git operations
        if text_lower.startswith("git "):
            r = self.exec_command(text, cwd=self._cwd, timeout=30)
            out = r.get("stdout", "") + r.get("stderr", "")
            return out.strip() or f"Exit code: {r.get('exit_code', '?')}"

        # File read
        m = re.search(r'(?:читай|read|покажи|show|cat)\s+([/\w.\-]+)', text_lower)
        if m:
            r = self.read_file(m.group(1))
            if r.get("error"):
                return f"Ошибка: {r['error']}"
            return f"📄 {r['path']} ({r['lines']} строк):\n\n{r['content'][:3000]}"

        # List directory
        m = re.search(r'(?:ls|dir|список|list)\s*([/\w.\-]*)', text_lower)
        if m:
            r = self.list_dir(m.group(1) or self._cwd)
            if r.get("error"):
                return f"Ошибка: {r['error']}"
            items = r.get("items", [])
            lines = [f"📁 {r['path']}:"]
            for item in items[:50]:
                icon = "📁" if item["type"] == "dir" else "📄"
                size = f" ({item['size']} b)" if item.get("size") else ""
                lines.append(f"  {icon} {item['name']}{size}")
            return "\n".join(lines)

        # Search code
        m = re.search(r'(?:найди в коде|grep|search code|поиск в коде)\s+(.+)', text_lower)
        if m:
            r = self.search_code(m.group(1))
            matches = r.get("matches", [])
            if not matches:
                return f"Ничего не найдено по запросу: {m.group(1)}"
            return f"🔍 Найдено {r['count']} совпадений:\n" + "\n".join(matches[:20])

        # Execute command
        m = re.search(r'(?:запусти|execute|run|bash)\s+(.+)', text, re.IGNORECASE)
        if m:
            cmd = m.group(1)
            r = self.exec_command(cmd)
            if r.get("error"):
                return f"Ошибка: {r['error']}"
            out = (r.get("stdout") or "") + (r.get("stderr") or "")
            return f"$ {cmd}\n{out.strip()[:2000]}" if out else f"Выполнено (код {r.get('exit_code', 0)})"

        # Audit project
        if "аудит" in text_lower or "audit" in text_lower:
            snap = self.audit_project(self._cwd)
            return json.dumps(snap, ensure_ascii=False, indent=2)[:2000]

        # Status
        if "статус" in text_lower or "status" in text_lower:
            procs = self.process_list()
            hist = len(self._history)
            return (
                f"CodeBridge Agent\n"
                f"  CWD: {self._cwd}\n"
                f"  Processes: {len(procs)}\n"
                f"  History: {hist} commands\n"
                f"  Safe roots: {', '.join(SAFE_ROOTS[:3])}"
            )

        return (
            "CodeBridge — доступные команды:\n"
            "  читай /path/file.py — показать файл\n"
            "  ls /path — список файлов\n"
            "  запусти команда — выполнить в bash\n"
            "  grep запрос — поиск в коде\n"
            "  git status/log/diff — git операции\n"
            "  аудит — анализ текущего проекта"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_safe_path(path: str) -> bool:
        """Check if path is under allowed roots."""
        for root in SAFE_ROOTS:
            try:
                Path(path).relative_to(root)
                return True
            except ValueError:
                continue
        return False
