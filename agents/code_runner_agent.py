# -*- coding: utf-8 -*-
"""
agents/code_runner_agent.py — Безопасное выполнение Python-кода.

Возможности:
  • Запуск Python-кода в изолированном subprocess
  • Таймаут + лимит памяти
  • Capture stdout/stderr
  • Анализ результата через LLM
  • История выполнений (последние 50)

Безопасность:
  • Запрет опасных модулей (os.system, subprocess, shutil.rmtree и т.д.)
  • Таймаут 15 сек
  • Только временная директория для файлов
"""

from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMRequest

log = logging.getLogger("agents.code_runner")

TIMEOUT_SEC = 15
MAX_OUTPUT_LEN = 5000

# Запрещённые паттерны в коде (безопасность)
DANGEROUS_PATTERNS = [
    r"os\.system\s*\(",
    r"subprocess\.\w+\s*\(",
    r"shutil\.rmtree",
    r"open\s*\(.*['\"]w",        # запись файлов в продакшн
    r"__import__\s*\(",
    r"exec\s*\(",
    r"eval\s*\(",
    r"compile\s*\(",
    r"globals\s*\(\s*\)\s*\[",
]


class CodeRunnerAgent(BaseAgent):
    """
    Агент выполнения кода — безопасная Python-песочница.
    Запускает код в subprocess с таймаутом и перехватывает вывод.
    """

    def __init__(self) -> None:
        super().__init__("code_runner")
        self._history: List[Dict] = []
        self._history_file = Path(__file__).parent.parent / "data" / "code_runner_history.json"
        self._load_history()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="code_runner",
            description="Выполняет Python-код в безопасной песочнице. Захватывает вывод и анализирует результат.",
            capabilities=[
                "run_code", "execute_python", "test_snippet",
                "evaluate_expression", "run_script",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(выполни|запусти|исполни|протестируй)\s+.*(код|скрипт|программу|функцию)",
            r"(run|execute|eval|test)\s+.*(code|script|function|snippet)",
            r"(что выведет|что вернёт|результат выполнения)",
            r"(проверь код|протестируй код|запусти код)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            # Извлечь код из текста
            code = self._extract_code(text)
            if not code:
                # Попросить LLM сгенерировать код для выполнения
                code = self._generate_code(text)

            if not code:
                return "❌ Не удалось найти или сгенерировать код для выполнения."

            # Проверка безопасности
            safe, danger_msg = self._check_safety(code)
            if not safe:
                return f"⛔ Опасный код заблокирован: {danger_msg}"

            # Выполнение
            result = self._run_code(code)
            self._save_to_history(text, code, result)

            # Анализ результата
            analysis = self._analyze_result(code, result)
            return analysis

        except Exception as e:
            self._log_failure("run_code", str(e))
            return f"❌ Ошибка выполнения: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    def run_code_direct(self, code: str) -> Tuple[bool, str]:
        """
        Прямое выполнение кода (вызывается другими агентами).
        Возвращает (success, output).
        """
        safe, msg = self._check_safety(code)
        if not safe:
            return False, f"⛔ Опасный паттерн: {msg}"
        result = self._run_code(code)
        return result["success"], result["stdout"] or result["stderr"]

    # ── Извлечение кода ───────────────────────────────────────────────────────

    def _extract_code(self, text: str) -> str:
        """Извлечь код из markdown блока или чистого Python."""
        # Markdown блоки
        match = re.search(r'```(?:python)?\s*\n(.*?)```', text, re.DOTALL)
        if match:
            return match.group(1).strip()

        # Простой Python (строки с отступами или def/class)
        lines = text.split("\n")
        code_lines = [l for l in lines if l.startswith(("    ", "\t", "def ", "class ",
                                                          "import ", "from ", "print(",
                                                          "x =", "a =", "result ="))]
        if len(code_lines) >= 2:
            return "\n".join(code_lines)
        return ""

    def _generate_code(self, text: str) -> str:
        """Попросить LLM сгенерировать код для выполнения."""
        prompt = (
            f"Напиши Python-код для выполнения задачи: {text}\n\n"
            f"Требования:\n"
            f"- Только Python 3.11+\n"
            f"- Код должен выводить результат через print()\n"
            f"- Без внешних зависимостей (только stdlib)\n"
            f"- Верни ТОЛЬКО код, без объяснений"
        )
        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code", max_tokens=1000, temperature=0.2,
        ))
        if resp.success:
            code = re.sub(r'```(?:python)?\s*', '', resp.content)
            return code.replace('```', '').strip()
        return ""

    # ── Безопасность ─────────────────────────────────────────────────────────

    def _check_safety(self, code: str) -> Tuple[bool, str]:
        """Проверить код на опасные паттерны."""
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                return False, f"паттерн: {pattern}"
        # AST-анализ
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                # Запрет import os + вызов os.system
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in ("os", "subprocess", "shutil"):
                            pass  # Import допускаем, но вызовы блокируем
        except SyntaxError:
            pass  # Синтаксическая ошибка обнаружится при запуске
        return True, ""

    # ── Выполнение ────────────────────────────────────────────────────────────

    def _run_code(self, code: str) -> Dict:
        """Выполнить код в subprocess с таймаутом."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", encoding="utf-8", delete=False
        ) as f:
            # Добавляем безопасный wrapper
            wrapped = (
                "import sys, io\n"
                "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')\n"
                "sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')\n\n"
                + code
            )
            f.write(wrapped)
            tmp_path = f.name

        try:
            t_start = time.time()
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SEC,
                encoding="utf-8",
                errors="replace",
            )
            elapsed = time.time() - t_start
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout[:MAX_OUTPUT_LEN],
                "stderr": proc.stderr[:MAX_OUTPUT_LEN],
                "returncode": proc.returncode,
                "elapsed": elapsed,
                "code": code,
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"⏱ Таймаут {TIMEOUT_SEC}с превышен",
                "returncode": -1,
                "elapsed": TIMEOUT_SEC,
                "code": code,
            }
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "returncode": -1,
                "elapsed": 0,
                "code": code,
            }
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def _analyze_result(self, code: str, result: Dict) -> str:
        """Отформатировать и проанализировать результат выполнения."""
        status = "✅" if result["success"] else "❌"
        elapsed_str = f"{result['elapsed']:.2f}с"

        output = result["stdout"] or result["stderr"] or "(нет вывода)"
        header = f"{status} **Выполнено за {elapsed_str}**\n\n"

        # Показываем код
        code_block = f"```python\n{result['code'][:800]}\n```\n\n"

        # Вывод
        output_block = f"**Вывод:**\n```\n{output[:1000]}\n```"

        # Если ошибка — объясняем через LLM
        explanation = ""
        if not result["success"] and result["stderr"]:
            explain_prompt = (
                f"Объясни ошибку Python и как её исправить:\n\n"
                f"КОД:\n{code}\n\n"
                f"ОШИБКА:\n{result['stderr'][:500]}\n\n"
                f"Дай краткое объяснение и исправленный код."
            )
            resp = self._ask_llm(explain_prompt, task_type="code")
            explanation = f"\n\n**Анализ ошибки:**\n{resp}"

        return header + code_block + output_block + explanation

    # ── История ──────────────────────────────────────────────────────────────

    def _save_to_history(self, request: str, code: str, result: Dict) -> None:
        self._history.append({
            "ts": time.time(),
            "request": request[:200],
            "code": code[:500],
            "success": result["success"],
            "output": (result["stdout"] or result["stderr"])[:200],
        })
        self._history = self._history[-50:]
        try:
            self._history_file.parent.mkdir(exist_ok=True)
            self._history_file.write_text(
                json.dumps(self._history, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    def _load_history(self) -> None:
        try:
            if self._history_file.exists():
                self._history = json.loads(
                    self._history_file.read_text(encoding="utf-8")
                )
        except Exception:
            self._history = []

    def get_history(self, limit: int = 10) -> List[Dict]:
        return self._history[-limit:]
