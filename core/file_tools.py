# -*- coding: utf-8 -*-
"""
core/file_tools.py — Прямые файловые операции для агента.

Эквивалент инструментов Claude Code: Read, Write, Edit, Glob, Grep.
Доступны через ToolRegistry и AgentHarness как atomic tools.

Все операции:
  • Логируют действия
  • Проверяют безопасность (не выходим за пределы BASE_DIR)
  • Возвращают структурированный ToolResult
  • Можно использовать из любого агента, Telegram и UI

Использование:
    from core.file_tools import FileTools
    ft = FileTools()
    result = ft.read("brain/orchestrator.py", offset=0, limit=50)
    result = ft.write("test.py", "print('hello')")
    result = ft.edit("test.py", old="hello", new="world")
    result = ft.glob("**/*.py")
    result = ft.grep("def process", path="agents/", file_type="py")
"""

from __future__ import annotations

import fnmatch
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

log = logging.getLogger("core.file_tools")

BASE_DIR = Path(__file__).parent.parent


@dataclass
class FileResult:
    """Результат файловой операции."""
    ok:      bool
    output:  str        # основной вывод
    error:   str = ""
    path:    str = ""
    lines_affected: int = 0

    def __bool__(self) -> bool:
        return self.ok

    def short(self, max_chars: int = 500) -> str:
        return self.output[:max_chars] + ("…" if len(self.output) > max_chars else "")


class FileTools:
    """
    Набор прямых файловых операций.
    Singleton через .get(), или создавай экземпляр напрямую.
    """

    _instance: Optional["FileTools"] = None

    def __init__(self, base_dir: Path = BASE_DIR) -> None:
        self._base = base_dir.resolve()

    @classmethod
    def get(cls) -> "FileTools":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Safety ───────────────────────────────────────────────────────────────

    def _resolve(self, rel_path: str) -> Optional[Path]:
        """Resolve path, ensuring it stays within BASE_DIR."""
        try:
            p = (self._base / rel_path).resolve()
            if not str(p).startswith(str(self._base)):
                log.warning("Path escape attempt: %s", rel_path)
                return None
            return p
        except Exception as e:
            log.error("Path resolve error: %s", e)
            return None

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self._base))
        except ValueError:
            return str(p)

    # ── READ ──────────────────────────────────────────────────────────────────

    def read(
        self,
        path: str,
        offset: int = 0,
        limit: int = 2000,
        encoding: str = "utf-8",
    ) -> FileResult:
        """
        Читать файл с поддержкой offset/limit (номера строк, с 1).
        Аналог инструмента Read в Claude Code.
        """
        p = self._resolve(path)
        if p is None:
            return FileResult(ok=False, error=f"Path not allowed: {path}", path=path)
        if not p.exists():
            return FileResult(ok=False, error=f"File not found: {path}", path=path)
        if not p.is_file():
            return FileResult(ok=False, error=f"Not a file: {path}", path=path)

        try:
            raw = p.read_text(encoding=encoding, errors="replace")
            lines = raw.splitlines(keepends=True)
            total = len(lines)
            start = max(0, offset)
            end   = min(total, start + limit) if limit > 0 else total
            chunk = lines[start:end]
            numbered = "".join(
                f"{start + i + 1}\t{line}" for i, line in enumerate(chunk)
            )
            meta = f"[Lines {start+1}-{end} of {total} | {self._rel(p)}]"
            return FileResult(
                ok=True,
                output=f"{meta}\n{numbered}",
                path=self._rel(p),
                lines_affected=len(chunk),
            )
        except Exception as e:
            return FileResult(ok=False, error=str(e), path=path)

    def read_raw(self, path: str, encoding: str = "utf-8") -> str:
        """Вернуть сырое содержимое файла (для внутреннего использования)."""
        p = self._resolve(path)
        if p is None or not p.is_file():
            return ""
        return p.read_text(encoding=encoding, errors="replace")

    # ── WRITE ─────────────────────────────────────────────────────────────────

    def write(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        create_dirs: bool = True,
    ) -> FileResult:
        """
        Записать файл полностью (перезапись).
        Аналог инструмента Write в Claude Code.
        """
        p = self._resolve(path)
        if p is None:
            return FileResult(ok=False, error=f"Path not allowed: {path}", path=path)
        try:
            if create_dirs:
                p.parent.mkdir(parents=True, exist_ok=True)
            lines = content.count("\n") + 1
            p.write_text(content, encoding=encoding)
            log.info("write → %s (%d lines)", self._rel(p), lines)
            return FileResult(
                ok=True,
                output=f"✅ Written: {self._rel(p)} ({lines} lines)",
                path=self._rel(p),
                lines_affected=lines,
            )
        except Exception as e:
            return FileResult(ok=False, error=str(e), path=path)

    # ── EDIT (exact string replacement) ──────────────────────────────────────

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
        encoding: str = "utf-8",
    ) -> FileResult:
        """
        Заменить exact строку в файле.
        Аналог инструмента Edit в Claude Code.
        old_string должен встречаться РОВНО ОДИН РАЗ (если replace_all=False).
        """
        p = self._resolve(path)
        if p is None:
            return FileResult(ok=False, error=f"Path not allowed: {path}", path=path)
        if not p.is_file():
            return FileResult(ok=False, error=f"File not found: {path}", path=path)

        try:
            content = p.read_text(encoding=encoding, errors="replace")
            count = content.count(old_string)

            if count == 0:
                return FileResult(
                    ok=False,
                    error=f"old_string not found in {self._rel(p)}",
                    path=self._rel(p),
                )
            if not replace_all and count > 1:
                return FileResult(
                    ok=False,
                    error=(
                        f"old_string found {count} times in {self._rel(p)}. "
                        "Use replace_all=True or provide more context."
                    ),
                    path=self._rel(p),
                )

            if replace_all:
                new_content = content.replace(old_string, new_string)
            else:
                new_content = content.replace(old_string, new_string, 1)

            p.write_text(new_content, encoding=encoding)
            reps = count if replace_all else 1
            log.info("edit → %s (%d replacement(s))", self._rel(p), reps)
            return FileResult(
                ok=True,
                output=f"✅ Edited: {self._rel(p)} ({reps} replacement(s))",
                path=self._rel(p),
                lines_affected=reps,
            )
        except Exception as e:
            return FileResult(ok=False, error=str(e), path=path)

    # ── GLOB (file pattern search) ────────────────────────────────────────────

    def glob(
        self,
        pattern: str,
        base: str = "",
        max_results: int = 200,
        exclude_pycache: bool = True,
    ) -> FileResult:
        """
        Найти файлы по glob-паттерну.
        Аналог инструмента Glob в Claude Code.
        """
        search_base = self._resolve(base) if base else self._base
        if search_base is None:
            return FileResult(ok=False, error=f"Base path not allowed: {base}")

        try:
            matches = sorted(
                search_base.rglob(pattern),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if exclude_pycache:
                matches = [m for m in matches if "__pycache__" not in str(m)]
            matches = matches[:max_results]
            paths   = [self._rel(m) for m in matches]
            output  = "\n".join(paths) if paths else "(no matches)"
            return FileResult(
                ok=True,
                output=output,
                lines_affected=len(paths),
            )
        except Exception as e:
            return FileResult(ok=False, error=str(e))

    # ── GREP (content search) ─────────────────────────────────────────────────

    def grep(
        self,
        pattern: str,
        path: str = "",
        file_type: str = "",
        case_insensitive: bool = False,
        context_lines: int = 0,
        max_results: int = 250,
    ) -> FileResult:
        """
        Искать паттерн в файлах.
        Аналог инструмента Grep в Claude Code.
        """
        search_path = self._resolve(path) if path else self._base
        if search_path is None:
            return FileResult(ok=False, error=f"Path not allowed: {path}")

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return FileResult(ok=False, error=f"Invalid regex: {e}")

        results = []
        glob_pat = f"*.{file_type}" if file_type else "*"

        try:
            if search_path.is_file():
                files = [search_path]
            else:
                files = [
                    f for f in search_path.rglob(glob_pat)
                    if f.is_file() and "__pycache__" not in str(f)
                ]

            for f in files:
                try:
                    lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
                    for i, line in enumerate(lines):
                        if compiled.search(line):
                            rel = self._rel(f)
                            entry = f"{rel}:{i+1}: {line.rstrip()}"
                            if context_lines > 0:
                                ctx_before = lines[max(0, i-context_lines):i]
                                ctx_after  = lines[i+1:min(len(lines), i+1+context_lines)]
                                entry += "\n" + "\n".join(
                                    f"  {j+max(0,i-context_lines)+1}  {l}"
                                    for j, l in enumerate(ctx_before)
                                )
                                entry += "\n" + "\n".join(
                                    f"  {i+1+j+1}  {l}"
                                    for j, l in enumerate(ctx_after)
                                )
                            results.append(entry)
                            if len(results) >= max_results:
                                break
                except Exception:
                    continue
                if len(results) >= max_results:
                    break

            output = "\n".join(results) if results else "(no matches)"
            return FileResult(ok=True, output=output, lines_affected=len(results))
        except Exception as e:
            return FileResult(ok=False, error=str(e))

    # ── LIST DIR ──────────────────────────────────────────────────────────────

    def ls(self, path: str = "", max_entries: int = 100) -> FileResult:
        """Список файлов и папок в директории."""
        p = self._resolve(path) if path else self._base
        if p is None:
            return FileResult(ok=False, error=f"Path not allowed: {path}")
        if not p.is_dir():
            return FileResult(ok=False, error=f"Not a directory: {path}")

        try:
            entries = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            lines = []
            for e in entries[:max_entries]:
                icon = "📁" if e.is_dir() else "📄"
                size = "" if e.is_dir() else f"  ({e.stat().st_size:,}b)"
                lines.append(f"{icon} {e.name}{size}")
            output = "\n".join(lines) or "(empty)"
            return FileResult(ok=True, output=output, path=self._rel(p),
                              lines_affected=len(lines))
        except Exception as e:
            return FileResult(ok=False, error=str(e))

    # ── DELETE ────────────────────────────────────────────────────────────────

    def delete(self, path: str, confirm: bool = False) -> FileResult:
        """Удалить файл (требует confirm=True)."""
        if not confirm:
            return FileResult(
                ok=False,
                error="Pass confirm=True to delete files",
                path=path,
            )
        p = self._resolve(path)
        if p is None:
            return FileResult(ok=False, error=f"Path not allowed: {path}", path=path)
        if not p.exists():
            return FileResult(ok=False, error=f"Not found: {path}", path=path)
        try:
            p.unlink() if p.is_file() else None
            log.warning("deleted: %s", self._rel(p))
            return FileResult(ok=True, output=f"🗑️ Deleted: {self._rel(p)}", path=self._rel(p))
        except Exception as e:
            return FileResult(ok=False, error=str(e), path=path)

    # ── BACKUP / RESTORE ─────────────────────────────────────────────────────

    def backup(self, path: str) -> FileResult:
        """Создать резервную копию файла перед изменением."""
        import time as _time
        p = self._resolve(path)
        if p is None or not p.is_file():
            return FileResult(ok=False, error=f"File not found: {path}", path=path)
        ts = int(_time.time())
        backup_path = p.with_suffix(f".bak.{ts}{p.suffix}")
        try:
            import shutil
            shutil.copy2(p, backup_path)
            return FileResult(
                ok=True,
                output=f"💾 Backup: {self._rel(backup_path)}",
                path=self._rel(backup_path),
            )
        except Exception as e:
            return FileResult(ok=False, error=str(e), path=path)

    # ── TOOLS MANIFEST (for AgentHarness) ────────────────────────────────────

    @staticmethod
    def tools_manifest() -> List[dict]:
        """Описание всех инструментов для LLM (используется в AgentHarness)."""
        return [
            {
                "name": "read_file",
                "description": "Read a file. Returns numbered lines. Use offset/limit for large files.",
                "params": {"path": "str", "offset": "int=0", "limit": "int=200"},
            },
            {
                "name": "write_file",
                "description": "Write (overwrite) a file completely.",
                "params": {"path": "str", "content": "str"},
            },
            {
                "name": "edit_file",
                "description": "Replace exact text in a file. old_string must be unique.",
                "params": {"path": "str", "old_string": "str", "new_string": "str"},
            },
            {
                "name": "glob_files",
                "description": "Find files matching a glob pattern (e.g. '**/*.py').",
                "params": {"pattern": "str", "base": "str=''"},
            },
            {
                "name": "grep_files",
                "description": "Search for regex pattern in files.",
                "params": {"pattern": "str", "path": "str=''", "file_type": "str=''"},
            },
            {
                "name": "list_dir",
                "description": "List files and folders in a directory.",
                "params": {"path": "str=''"},
            },
        ]
