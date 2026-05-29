# -*- coding: utf-8 -*-
"""
agents/coder_agent.py — Агент для написания и изменения кода.

Умеет:
  • Анализировать существующий код
  • Генерировать новый код
  • Безопасно применять изменения (тест → бэкап → применить → откат при ошибке)
  • Обучаться на ошибках (сохраняет паттерны)
  • Создавать задачи для Claude если задача слишком сложная
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMProvider, LLMRequest
from core.config import cfg
from memory.memory_store import KnowledgeEntry

log = logging.getLogger("agents.coder")

# Разрешённые для изменения пути (внутри my_personal_ai/)
ALLOWED_PATHS = [
    "agents/",
    "brain/",
    "memory/",
    "vector_stores/",
    "core/",
    "auth/",
    "gui/",
    "projects/",
]

BACKUP_DIR = cfg.DATA_DIR / "code_backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class CodePatch:
    patch_type: str       # "snippet_replace" | "full_replace" | "new_file"
    file_path: str
    original: str = ""
    new_code: str = ""
    description: str = ""


class CoderAgent(BaseAgent):
    """
    Агент-программист.
    Принимает текстовое задание → генерирует патч → тестирует → применяет.
    """

    def __init__(self) -> None:
        super().__init__("coder")
        self._knowledge_file = cfg.DATA_DIR / "coder_knowledge.json"
        self._knowledge = self._load_knowledge()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="coder",
            description="Пишет и изменяет Python-код. Тестирует перед применением.",
            capabilities=[
                "write_code", "modify_code", "fix_bugs",
                "create_file", "rollback", "test_syntax",
            ]
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(измени|добавь|удали|перепиши|исправь|напиши|создай)\s+.*код",
            r"(change|modify|add|remove|rewrite|fix|write|create)\s+.*code",
            r"(функци|класс|метод|файл|скрипт|модуль)",
            r"(function|class|method|file|script|module)",
        ]
        for p in patterns:
            if re.search(p, text, re.IGNORECASE):
                return True
        return False

    def process(self, text: str, source: str = "gui") -> str:
        """Обработать задание на изменение кода."""
        self._set_status(AgentStatus.RUNNING)
        self._memory.log_agent(self.name, "process_start", text[:200])

        try:
            # 1. Классификация задания
            intent = self._classify(text)

            if intent.get("type") == "read_file":
                return self._read_file_summary(intent.get("file", ""))

            if intent.get("type") == "rollback":
                return self.rollback(intent.get("file", ""))

            if intent.get("type") == "code_change":
                return self._apply_code_change(text, intent)

            # Fallback: объяснение
            return self._explain(text)

        except Exception as e:
            self._log_failure("process", str(e))
            self._set_status(AgentStatus.ERROR)
            return f"❌ Ошибка агента-программиста: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── Классификация ─────────────────────────────────────────────────────────

    def _classify(self, text: str) -> Dict:
        """Классифицировать задание через LLM."""
        file_list = self._list_project_files()[:60]

        prompt = f"""Ты анализируешь задание для изменения кода. Проект: my_personal_ai.

ЗАДАНИЕ: {text}

ФАЙЛЫ ПРОЕКТА:
{chr(10).join(file_list)}

Правила классификации:
- "code_change" — нужно изменить, добавить, исправить, написать, улучшить код (БОЛЬШИНСТВО задач)
- "read_file" — только прочитать/показать содержимое файла
- "rollback" — откатить изменения
- "explain" — ТОЛЬКО если задание требует объяснения без изменений кода

ВАЖНО: Если задание содержит "улучши", "добавь", "исправь", "измени", "напиши",
"доработай", "реализуй" — это ВСЕГДА "code_change", даже если файл не указан явно.
Для "code_change" выбери наиболее подходящий файл из списка.

Верни JSON:
{{
  "type": "code_change" | "read_file" | "rollback" | "explain",
  "file": "<относительный путь от my_personal_ai/>",
  "description": "<что именно нужно изменить>",
  "complexity": "simple" | "medium" | "complex"
}}

Только JSON, без объяснений."""

        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code",
            max_tokens=400,
            temperature=0.1,
        ))

        try:
            match = re.search(r'\{.*\}', resp.content, re.DOTALL)
            if match:
                result = json.loads(match.group())
                # Доп. проверка: если задание явно содержит глаголы изменения → всегда code_change
                change_verbs = r"(улучши|добавь|исправь|измени|напиши|доработай|реализуй|перепиши|обнови)"
                if re.search(change_verbs, text, re.IGNORECASE):
                    if result.get("type") == "explain":
                        result["type"] = "code_change"
                        log.debug("Override classify: explain→code_change (change verb detected)")
                return result
        except Exception as e:
            log.debug("Classify parse error: %s", e)

        # Fallback: если в тексте есть глаголы изменений → code_change
        change_verbs = r"(улучши|добавь|исправь|измени|напиши|доработай|реализуй)"
        if re.search(change_verbs, text, re.IGNORECASE):
            return {"type": "code_change", "file": "", "description": text, "complexity": "medium"}
        return {"type": "explain", "file": "", "description": text}

    # ── Применение изменений ──────────────────────────────────────────────────

    def _apply_code_change(self, task: str, intent: Dict) -> str:
        """Полный цикл: читаем файл → генерируем патч → тестируем → применяем."""
        rel_path = intent.get("file", "")

        # Если файл не указан — LLM выберет сам в _generate_patch
        # Проверка безопасности только если файл явно указан
        if rel_path and not self._is_allowed(rel_path):
            # Попробуем найти похожий разрешённый файл
            log.warning("File %s not in allowed paths, asking LLM to pick correct file", rel_path)
            rel_path = ""  # Сбрасываем — LLM выберет файл сам в generate_patch

        # Читаем файл если он существует
        full_path = cfg.BASE_DIR / rel_path if rel_path else None
        current_code = ""
        if full_path and full_path.exists():
            current_code = full_path.read_text(encoding="utf-8")

        # Генерируем патч
        patch = self._generate_patch(task, rel_path, current_code, intent)
        if not patch:
            return "⚠️ Не удалось сгенерировать патч. Попробуй переформулировать задание."

        # Проверяем синтаксис
        ok, msg = self._test_syntax(patch.new_code)
        if not ok:
            # Пытаемся исправить
            patch = self._fix_syntax(patch, msg)
            ok2, msg2 = self._test_syntax(patch.new_code)
            if not ok2:
                self._save_failure(task, f"SyntaxError: {msg2}")
                return (
                    f"❌ Синтаксическая ошибка после генерации и исправления:\n"
                    f"```\n{msg2}\n```\n\n"
                    f"📋 **Задача для Claude:**\n{self._create_claude_task(task, msg2)}"
                )

        # Создаём бэкап
        backup_path = ""
        if full_path and full_path.exists():
            ok_b, backup_path = self._create_backup(rel_path)
            if not ok_b:
                return f"⚠️ Не удалось создать бэкап: {backup_path}"

        # Применяем (используем file_path из патча — LLM мог выбрать другой файл)
        actual_path = patch.file_path or rel_path
        if actual_path and actual_path != rel_path:
            rel_path = actual_path
            full_path = cfg.BASE_DIR / rel_path if rel_path else None
            log.info("CoderAgent using patch file_path: %s", rel_path)

        try:
            if patch.patch_type == "full_replace":
                self._write_file(rel_path, patch.new_code)
            elif patch.patch_type == "snippet_replace":
                ok_s, msg_s = self._apply_snippet(rel_path, patch.original, patch.new_code)
                if not ok_s:
                    # Fallback к full_replace если snippet не нашёлся
                    log.warning("snippet_replace failed (%s), trying full_replace", msg_s)
                    self._write_file(rel_path, patch.new_code)
            elif patch.patch_type == "new_file":
                self._write_file(rel_path, patch.new_code)
        except Exception as e:
            if backup_path:
                self._restore_backup(rel_path, backup_path)
            return f"❌ Ошибка записи файла: {e}"

        # Тест компиляции
        if rel_path.endswith(".py"):
            ok_c, msg_c = self._test_compile(rel_path)
            if not ok_c:
                if backup_path:
                    self._restore_backup(rel_path, backup_path)
                self._save_failure(task, msg_c)
                return (
                    f"❌ Ошибка компиляции после применения. Откат выполнен.\n"
                    f"```\n{msg_c}\n```\n\n"
                    f"📋 **Задача для Claude:**\n{self._create_claude_task(task, msg_c)}"
                )

        # Успех!
        self._save_success(task, rel_path)
        self._log_success("code_change", f"file={rel_path}")

        return (
            f"✅ Изменения применены в `{rel_path}`\n\n"
            f"📝 {patch.description}\n\n"
            f"💾 Бэкап: `{Path(backup_path).name if backup_path else 'нет'}`\n\n"
            f"```python\n{patch.new_code[:800]}{'...' if len(patch.new_code) > 800 else ''}\n```"
        )

    # ── Генерация патча ───────────────────────────────────────────────────────

    def _generate_patch(self, task: str, rel_path: str,
                        current_code: str, intent: Dict) -> Optional[CodePatch]:
        """Генерировать патч через LLM."""
        # Контекст успешных решений
        similar = self._find_similar_solutions(task)
        similar_ctx = ""
        if similar:
            similar_ctx = "\n\nПОХОЖИЕ УСПЕШНЫЕ РЕШЕНИЯ:\n" + "\n".join(similar[:3])

        code_ctx = f"\nТЕКУЩИЙ КОД ({rel_path}):\n```python\n{current_code[:3000]}\n```" \
                   if current_code else ""

        # Список файлов для подсказки если rel_path не указан
        file_hint = rel_path or "выбери подходящий файл из проекта"
        file_list_ctx = ""
        if not rel_path:
            fl = self._list_project_files()[:30]
            file_list_ctx = f"\nФАЙЛЫ ПРОЕКТА (выбери подходящий):\n" + "\n".join(fl)

        prompt = f"""Ты опытный Python-разработчик. Выполни задание точно и безопасно.

ЗАДАНИЕ: {task}
{code_ctx}
{file_list_ctx}
{similar_ctx}

Верни JSON с патчем:
{{
  "patch_type": "snippet_replace" | "full_replace" | "new_file",
  "file_path": "{file_hint}",
  "original": "ТОЧНЫЙ существующий фрагмент кода для замены (если snippet_replace)",
  "new_code": "НОВЫЙ код (полный файл для full_replace/new_file, или новый фрагмент для snippet_replace)",
  "description": "Что именно изменено"
}}

Правила:
- ОБЯЗАТЕЛЬНО укажи реальный файл в file_path (не 'путь/к/файлу.py')
- Для snippet_replace: original должен ТОЧНО совпадать с текущим кодом
- Для full_replace: new_code — полный файл с shebang и импортами
- Код должен быть валидным Python 3.11+
- Добавляй type hints и docstrings
- Только JSON, без markdown блоков вокруг JSON"""

        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code",
            require_quality=True,
            max_tokens=4000,
            temperature=0.2,
        ))

        if not resp.success:
            return None

        try:
            # Убираем markdown блоки
            content = re.sub(r'```(?:json)?\s*', '', resp.content)
            content = content.replace('```', '').strip()
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return CodePatch(
                    patch_type=data.get("patch_type", "full_replace"),
                    file_path=data.get("file_path", rel_path),
                    original=data.get("original", ""),
                    new_code=data.get("new_code", ""),
                    description=data.get("description", ""),
                )
        except Exception as e:
            log.error("Patch parse error: %s\nContent: %s", e, resp.content[:200])

        return None

    def _fix_syntax(self, patch: CodePatch, error: str) -> CodePatch:
        """Попробовать исправить синтаксическую ошибку через LLM."""
        prompt = f"""Исправь синтаксическую ошибку в Python-коде.

ОШИБКА: {error}

КОД:
```python
{patch.new_code}
```

Верни ТОЛЬКО исправленный код, без объяснений."""

        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code",
            max_tokens=3000,
            temperature=0.1,
        ))

        if resp.success:
            code = re.sub(r'```(?:python)?\s*', '', resp.content)
            code = code.replace('```', '').strip()
            patch.new_code = code

        return patch

    # ── Тестирование ─────────────────────────────────────────────────────────

    def _test_syntax(self, code: str) -> Tuple[bool, str]:
        """Проверить синтаксис через ast.parse."""
        try:
            ast.parse(code)
            return True, "OK"
        except SyntaxError as e:
            return False, f"SyntaxError строка {e.lineno}: {e.msg}"

    def _test_compile(self, rel_path: str) -> Tuple[bool, str]:
        """Проверить компиляцию через py_compile в subprocess."""
        path = cfg.BASE_DIR / rel_path
        cmd = [sys.executable, "-c",
               f"import py_compile; py_compile.compile(r'{path}', doraise=True)"]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=15, cwd=str(cfg.BASE_DIR)
            )
            if result.returncode == 0:
                return True, "OK"
            return False, (result.stderr or result.stdout).strip()[:300]
        except subprocess.TimeoutExpired:
            return False, "Таймаут компиляции"
        except Exception as e:
            return False, str(e)

    # ── Файловые операции ─────────────────────────────────────────────────────

    def _write_file(self, rel_path: str, content: str) -> None:
        path = cfg.BASE_DIR / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log.info("Written: %s (%d bytes)", rel_path, len(content))

    def _apply_snippet(self, rel_path: str, original: str,
                       replacement: str) -> Tuple[bool, str]:
        path = cfg.BASE_DIR / rel_path
        if not path.exists():
            return False, f"Файл не найден: {rel_path}"
        content = path.read_text(encoding="utf-8")
        if original not in content:
            return False, f"Фрагмент не найден в {rel_path}"
        new_content = content.replace(original, replacement, 1)
        path.write_text(new_content, encoding="utf-8")
        return True, "OK"

    def _create_backup(self, rel_path: str) -> Tuple[bool, str]:
        src = cfg.BASE_DIR / rel_path
        if not src.exists():
            return True, ""
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = BACKUP_DIR / f"{src.name}.{ts}.bak"
        try:
            shutil.copy2(src, dst)
            return True, str(dst)
        except Exception as e:
            return False, str(e)

    def _restore_backup(self, rel_path: str, backup_path: str) -> None:
        try:
            shutil.copy2(backup_path, cfg.BASE_DIR / rel_path)
            log.info("Restored %s from %s", rel_path, backup_path)
        except Exception as e:
            log.error("Restore failed: %s", e)

    def rollback(self, file_hint: str = "") -> str:
        """Откатить последний бэкап файла."""
        if file_hint:
            stem = Path(file_hint).name
        else:
            # Берём самый свежий бэкап
            backups = sorted(BACKUP_DIR.glob("*.bak"))
            if not backups:
                return "📭 Нет доступных бэкапов."
            stem = backups[-1].stem.rsplit(".", 1)[0]

        backups = sorted(BACKUP_DIR.glob(f"{stem}.*.bak"))
        if not backups:
            return f"📭 Бэкап для `{stem}` не найден."

        latest = backups[-1]
        # Определить исходный путь
        original_name = stem
        target = self._find_file(original_name)
        if not target:
            return f"⚠️ Файл `{original_name}` не найден в проекте."
        try:
            shutil.copy2(latest, target)
            return f"✅ Откат выполнен: `{original_name}` восстановлен из `{latest.name}`"
        except Exception as e:
            return f"❌ Откат не удался: {e}"

    def _find_file(self, name: str) -> Optional[Path]:
        """Найти файл по имени в проекте."""
        for p in cfg.BASE_DIR.rglob(name):
            if "venv" not in str(p) and "__pycache__" not in str(p):
                return p
        return None

    # ── Вспомогательные ──────────────────────────────────────────────────────

    def _is_allowed(self, rel_path: str) -> bool:
        normalized = rel_path.replace("\\", "/")
        return any(normalized.startswith(a) for a in ALLOWED_PATHS)

    def _list_project_files(self) -> List[str]:
        result = []
        for p in cfg.BASE_DIR.rglob("*.py"):
            rel = str(p.relative_to(cfg.BASE_DIR)).replace("\\", "/")
            if "venv" not in rel and "__pycache__" not in rel and ".bak" not in rel:
                result.append(rel)
        return sorted(result)

    def _read_file_summary(self, rel_path: str) -> str:
        path = cfg.BASE_DIR / rel_path if rel_path else None
        if not path or not path.exists():
            return f"❌ Файл не найден: {rel_path}"
        content = path.read_text(encoding="utf-8")
        return (
            f"📄 **{rel_path}** ({len(content)} символов):\n\n"
            f"```python\n{content[:2000]}{'...' if len(content) > 2000 else ''}\n```"
        )

    def _explain(self, text: str) -> str:
        return self._ask_llm(
            text,
            system="Ты опытный Python-разработчик. Отвечай конкретно и с примерами кода.",
            task_type="code"
        )

    def _create_claude_task(self, task: str, error: str) -> str:
        return (
            f"Мой AI-агент не смог выполнить задачу. Помоги решить:\n\n"
            f"**Задача:** {task}\n\n"
            f"**Ошибка:** {error}\n\n"
            f"**Проект:** my_personal_ai (Python 3.11+)\n\n"
            f"Дай готовое решение с кодом."
        )

    # ── Обучение ─────────────────────────────────────────────────────────────

    def _save_success(self, task: str, file_path: str) -> None:
        self._knowledge.setdefault("successes", []).append({
            "task": task[:200], "file": file_path, "ts": time.time()
        })
        self._knowledge["successes"] = self._knowledge["successes"][-100:]
        self._save_knowledge()

    def _save_failure(self, task: str, error: str) -> None:
        self._knowledge.setdefault("failures", []).append({
            "task": task[:200], "error": error[:300], "ts": time.time()
        })
        self._knowledge["failures"] = self._knowledge["failures"][-50:]
        self._save_knowledge()

    def _find_similar_solutions(self, task: str) -> List[str]:
        words = set(task.lower().split())
        results = []
        for s in self._knowledge.get("successes", []):
            task_words = set(s["task"].lower().split())
            overlap = len(words & task_words) / max(len(words), 1)
            if overlap > 0.3:
                results.append(f"✅ [{s['file']}]: {s['task'][:100]}")
        return results[:3]

    def _load_knowledge(self) -> Dict:
        try:
            if self._knowledge_file.exists():
                return json.loads(self._knowledge_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {"successes": [], "failures": []}

    def _save_knowledge(self) -> None:
        try:
            self._knowledge_file.write_text(
                json.dumps(self._knowledge, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception as e:
            log.debug("Knowledge save failed: %s", e)
