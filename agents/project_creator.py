# -*- coding: utf-8 -*-
"""
agents/project_creator.py — Агент создания новых проектов.

Умеет:
  • Придумать идею нового проекта
  • Создать структуру папок и базовые файлы
  • Сгенерировать main.py, config.py, requirements.txt, README.md
  • Зарегистрировать проект в системной памяти
  • Запустить проект
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMRequest
from core.config import cfg
from memory.memory_store import MemoryStore

log = logging.getLogger("agents.project_creator")


# Шаблоны для разных типов проектов
PROJECT_TEMPLATES: Dict[str, Dict] = {
    "trading_bot": {
        "description": "Алготрейдинг бот для биржи",
        "dirs": ["core", "strategies", "data", "logs", "tests"],
        "deps": ["pybit", "pandas", "numpy", "python-dotenv", "httpx"],
    },
    "telegram_bot": {
        "description": "Telegram-бот",
        "dirs": ["handlers", "middlewares", "data", "logs"],
        "deps": ["python-telegram-bot", "python-dotenv", "httpx"],
    },
    "web_dashboard": {
        "description": "Веб-дашборд",
        "dirs": ["static", "templates", "api", "data"],
        "deps": ["fastapi", "uvicorn", "jinja2", "python-dotenv"],
    },
    "news_analyzer": {
        "description": "Анализатор новостей",
        "dirs": ["parsers", "analyzers", "data", "logs"],
        "deps": ["httpx", "beautifulsoup4", "feedparser", "python-dotenv"],
    },
    "backtester": {
        "description": "Бэктестер торговых стратегий",
        "dirs": ["strategies", "data", "results", "tests"],
        "deps": ["pandas", "numpy", "matplotlib", "python-dotenv"],
    },
    "ml_predictor": {
        "description": "ML-предиктор",
        "dirs": ["models", "data", "features", "results"],
        "deps": ["scikit-learn", "pandas", "numpy", "joblib"],
    },
    "generic": {
        "description": "Общий проект",
        "dirs": ["core", "data", "scripts", "tests"],
        "deps": ["python-dotenv", "httpx"],
    },
}


class ProjectCreatorAgent(BaseAgent):
    """Агент создания и управления проектами."""

    def __init__(self) -> None:
        super().__init__("project_creator")
        self._projects_dir = cfg.PROJECTS_DIR
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="project_creator",
            description="Создаёт новые проекты с полной структурой файлов и зависимостями.",
            capabilities=[
                "create_project", "list_projects", "suggest_projects",
                "generate_structure", "create_readme",
            ]
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(создай|сделай|запусти|начни|новый|новое)\s+.*(проект|бот|приложен|систем|анализатор|дашборд)",
            r"(create|make|start|new)\s+.*(project|bot|app|application|system|dashboard|analyzer)",
            r"(придумай|предложи|suggest)\s+.*(проект|project|идею|idea)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        """Обработать запрос создания проекта."""
        self._set_status(AgentStatus.RUNNING)

        try:
            # Определить: создание конкретного проекта или предложение идей
            if re.search(r"(придумай|предложи|suggest|идею|idea)", text, re.IGNORECASE):
                return self._suggest_projects()

            if re.search(r"(список|list|покажи|show).*(проект)", text, re.IGNORECASE):
                return self._list_projects()

            # Создать проект
            spec = self._parse_project_spec(text)
            if not spec:
                return "⚠️ Не удалось определить название и тип проекта. Уточни запрос."

            return self._create_project(spec)

        except Exception as e:
            self._log_failure("process", str(e))
            return f"❌ Ошибка создания проекта: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── Парсинг запроса ───────────────────────────────────────────────────────

    def _parse_project_spec(self, text: str) -> Optional[Dict]:
        """Извлечь спецификацию проекта из текста через LLM."""
        existing = [p.name for p in self._projects_dir.iterdir() if p.is_dir()]
        templates = list(PROJECT_TEMPLATES.keys())

        prompt = f"""Извлеки спецификацию проекта из запроса.

ЗАПРОС: {text}

ДОСТУПНЫЕ ШАБЛОНЫ: {', '.join(templates)}
СУЩЕСТВУЮЩИЕ ПРОЕКТЫ: {', '.join(existing) or 'нет'}

Верни JSON:
{{
  "name": "snake_case_название",
  "type": "один из шаблонов или generic",
  "description": "краткое описание",
  "extra_features": ["фича1", "фича2"]
}}

Только JSON."""

        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="general",
            max_tokens=300,
            temperature=0.2,
        ))

        try:
            match = re.search(r'\{.*\}', resp.content, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception:
            pass

        # Простой fallback — извлечь имя из текста
        name_match = re.search(r'["\']([a-zA-Z_][a-zA-Z0-9_]*)["\']', text)
        if name_match:
            return {"name": name_match.group(1), "type": "generic",
                    "description": text[:100], "extra_features": []}
        return None

    # ── Создание проекта ──────────────────────────────────────────────────────

    def _create_project(self, spec: Dict) -> str:
        """Создать проект с полной структурой."""
        name = spec["name"].lower().replace(" ", "_").replace("-", "_")
        proj_type = spec.get("type", "generic")
        description = spec.get("description", "")
        extra = spec.get("extra_features", [])

        project_dir = self._projects_dir / name
        if project_dir.exists():
            return f"⚠️ Проект `{name}` уже существует в `{project_dir}`"

        template = PROJECT_TEMPLATES.get(proj_type, PROJECT_TEMPLATES["generic"])
        progress = [f"🚀 Создаю проект **{name}** (тип: {proj_type})"]

        # 1. Создать директории
        project_dir.mkdir(parents=True)
        for subdir in template["dirs"] + ["scripts"]:
            (project_dir / subdir).mkdir(exist_ok=True)
        progress.append(f"  📁 Папки: {', '.join(template['dirs'])}")

        # 2. Создать __init__.py в каждой папке
        for subdir in template["dirs"]:
            (project_dir / subdir / "__init__.py").write_text(
                f'"""Package: {name}.{subdir}"""\n', encoding="utf-8"
            )

        # 3. requirements.txt
        deps = template["deps"].copy()
        if extra:
            # Дополнительные зависимости на основе фич
            for feat in extra:
                if "telegram" in feat.lower():
                    deps.append("python-telegram-bot")
                if "ml" in feat.lower() or "ai" in feat.lower():
                    deps.extend(["scikit-learn", "numpy"])
                if "web" in feat.lower() or "api" in feat.lower():
                    deps.extend(["fastapi", "uvicorn"])
        deps = list(dict.fromkeys(deps))  # дедупликация

        req_content = "# Requirements for " + name + "\n" + "\n".join(deps) + "\n"
        (project_dir / "requirements.txt").write_text(req_content, encoding="utf-8")
        progress.append(f"  📦 requirements.txt ({len(deps)} пакетов)")

        # 4. .env.example
        env_example = self._generate_env_example(proj_type, name)
        (project_dir / ".env.example").write_text(env_example, encoding="utf-8")

        # 5. config.py
        config_code = self._generate_config(name, proj_type)
        (project_dir / "config.py").write_text(config_code, encoding="utf-8")
        progress.append("  ⚙️ config.py")

        # 6. main.py — с авто-исправлением синтаксических ошибок
        main_code = self._generate_main_with_fix(name, proj_type, description, extra)
        (project_dir / "main.py").write_text(main_code, encoding="utf-8")
        progress.append("  🐍 main.py")

        # 7. README.md
        readme = self._generate_readme(name, proj_type, description, deps, extra)
        (project_dir / "README.md").write_text(readme, encoding="utf-8")
        progress.append("  📄 README.md")

        # 8. Валидация — проверяем синтаксис всех .py файлов
        errors = self._validate_project(project_dir)
        if errors:
            fixed = self._autofix_errors(project_dir, errors)
            if fixed:
                progress.append(f"  🔧 Авто-исправлено ошибок: {len(fixed)}")
            else:
                progress.append(f"  ⚠️ Найдены ошибки: {'; '.join(errors[:2])}")

        # 9. Зарегистрировать в памяти
        self._memory.save_project(
            name=name,
            description=description or template["description"],
            path=str(project_dir),
            metadata={"type": proj_type, "extra_features": extra}
        )
        progress.append(f"  💾 Зарегистрирован в памяти")

        self._log_success("create_project", f"name={name}, type={proj_type}")

        return (
            "\n".join(progress) + "\n\n"
            f"✅ Проект создан: `{project_dir}`\n\n"
            f"Следующие шаги:\n"
            f"```bash\n"
            f"cd {project_dir}\n"
            f"python -m venv venv\n"
            f"pip install -r requirements.txt\n"
            f"cp .env.example .env\n"
            f"python main.py\n"
            f"```"
        )

    # ── Валидация и авто-исправление ─────────────────────────────────────────

    def _generate_main_with_fix(self, name: str, proj_type: str,
                                description: str, extra: List[str],
                                max_attempts: int = 3) -> str:
        """Генерирует main.py и авто-исправляет синтаксические ошибки (до 3 попыток)."""
        code = self._generate_main(name, proj_type, description, extra)

        for attempt in range(max_attempts):
            try:
                import ast
                ast.parse(code)
                return code  # синтаксис OK
            except SyntaxError as e:
                log.warning("main.py syntax error (attempt %d): %s", attempt + 1, e)
                if attempt < max_attempts - 1:
                    fix_prompt = (
                        f"Исправь синтаксическую ошибку в Python-коде.\n"
                        f"Ошибка: {e.msg} на строке {e.lineno}\n\n"
                        f"КОД:\n```python\n{code}\n```\n\n"
                        f"Верни ТОЛЬКО исправленный код Python, без объяснений."
                    )
                    resp = self._llm.ask(LLMRequest(
                        messages=[{"role": "user", "content": fix_prompt}],
                        task_type="code", max_tokens=2000, temperature=0.1,
                    ))
                    if resp.success:
                        new_code = re.sub(r'```(?:python)?\s*', '', resp.content)
                        code = new_code.replace('```', '').strip()

        return code  # возвращаем как есть после всех попыток

    def _validate_project(self, project_dir: Path) -> List[str]:
        """Проверить синтаксис всех .py файлов проекта."""
        import ast
        errors = []
        for py_file in project_dir.rglob("*.py"):
            try:
                ast.parse(py_file.read_text(encoding="utf-8"))
            except SyntaxError as e:
                errors.append(f"{py_file.name}:{e.lineno}: {e.msg}")
            except Exception as e:
                errors.append(f"{py_file.name}: {e}")
        return errors

    def _autofix_errors(self, project_dir: Path, errors: List[str]) -> List[str]:
        """Авто-исправить найденные ошибки через LLM."""
        import ast
        fixed = []
        for error_desc in errors:
            # Парсим имя файла
            fname = error_desc.split(":")[0]
            py_file = next(project_dir.rglob(fname), None)
            if not py_file or not py_file.exists():
                continue
            try:
                original = py_file.read_text(encoding="utf-8")
                fix_prompt = (
                    f"Исправь ошибку в Python-файле.\n"
                    f"Ошибка: {error_desc}\n\n"
                    f"```python\n{original[:3000]}\n```\n\n"
                    f"Верни ТОЛЬКО исправленный Python-код."
                )
                resp = self._llm.ask(LLMRequest(
                    messages=[{"role": "user", "content": fix_prompt}],
                    task_type="code", max_tokens=2000, temperature=0.1,
                ))
                if resp.success:
                    new_code = re.sub(r'```(?:python)?\s*', '', resp.content)
                    new_code = new_code.replace('```', '').strip()
                    # Проверяем что исправление валидно
                    ast.parse(new_code)
                    py_file.write_text(new_code, encoding="utf-8")
                    fixed.append(fname)
                    log.info("Auto-fixed: %s", fname)
            except Exception as ex:
                log.warning("Autofix failed for %s: %s", fname, ex)
        return fixed

    # ── Генераторы файлов ─────────────────────────────────────────────────────

    def _generate_main(self, name: str, proj_type: str,
                       description: str, extra: List[str]) -> str:
        """Сгенерировать main.py через LLM."""
        prompt = f"""Создай main.py для Python-проекта.

Название: {name}
Тип: {proj_type}
Описание: {description}
Дополнительно: {', '.join(extra) if extra else 'нет'}

Требования:
- Python 3.11+, type hints, docstrings
- Загрузка конфига из .env через python-dotenv
- Базовое логирование через logging
- Структурированный main() и if __name__ == '__main__': main()
- Заглушки для основной логики с TODO-комментариями
- Обработка KeyboardInterrupt

Только код Python, без объяснений."""

        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code",
            max_tokens=2000,
            temperature=0.3,
        ))

        if resp.success:
            code = re.sub(r'```(?:python)?\s*', '', resp.content)
            return code.replace('```', '').strip()

        # Fallback шаблон
        return f'''# -*- coding: utf-8 -*-
"""
{name} — {description or "Main entry point"}
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    log.info("Starting {name}...")
    # TODO: implement main logic
    log.info("{name} stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
'''

    def _generate_config(self, name: str, proj_type: str) -> str:
        return f'''# -*- coding: utf-8 -*-
"""config.py — Конфигурация {name}."""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# ── Основные настройки ────────────────────────────────────────────────────────
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ── API ключи ─────────────────────────────────────────────────────────────────
# Добавь свои ключи в .env
API_KEY = os.getenv("API_KEY", "")
API_SECRET = os.getenv("API_SECRET", "")
'''

    def _generate_readme(self, name: str, proj_type: str,
                         description: str, deps: List[str], extra: List[str]) -> str:
        return f"""# {name}

{description or f'Автоматически создан системой my_personal_ai ({proj_type})'}

## Установка

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```

## Конфигурация

Заполни `.env` на основе `.env.example`.

## Запуск

```bash
python main.py
```

## Зависимости

{chr(10).join(f'- {d}' for d in deps)}

## Создан

Проект создан автоматически агентом `ProjectCreatorAgent` системы `my_personal_ai`.
"""

    def _generate_env_example(self, proj_type: str, name: str) -> str:
        base = f"# .env.example для {name}\n\nDEBUG=false\nLOG_LEVEL=INFO\n"
        if proj_type == "trading_bot":
            base += "\nBYBIT_API_KEY=\nBYBIT_API_SECRET=\nBYBIT_TESTNET=true\n"
        elif proj_type == "telegram_bot":
            base += "\nTELEGRAM_BOT_TOKEN=\nTELEGRAM_CHAT_ID=\n"
        elif proj_type in ("web_dashboard",):
            base += "\nHOST=0.0.0.0\nPORT=8080\n"
        return base

    # ── Список и идеи ─────────────────────────────────────────────────────────

    def _list_projects(self) -> str:
        projects = self._memory.get_projects()
        if not projects:
            dirs = [p.name for p in self._projects_dir.iterdir() if p.is_dir()]
            if dirs:
                return "📁 Проекты в папке:\n" + "\n".join(f"  • {d}" for d in dirs)
            return "📭 Проектов пока нет."

        lines = ["📁 **Зарегистрированные проекты:**\n"]
        for p in projects:
            lines.append(f"  • **{p['name']}** — {p.get('description', '')}")
        return "\n".join(lines)

    def _suggest_projects(self) -> str:
        """Предложить идеи новых проектов на основе контекста системы."""
        existing = [p.name for p in self._projects_dir.iterdir() if p.is_dir()]

        prompt = f"""Предложи 5 новых проектов для системы my_personal_ai (торговый бот + AI-ассистент).

Уже существуют: {', '.join(existing) or 'нет'}

Требования к каждой идее:
- Полезна для трейдинга, автоматизации или разработки
- Реалистична в реализации на Python
- Дополняет существующие компоненты

Формат:
1. **Название** — описание (тип шаблона)
2. ...

Только список, без лишних объяснений."""

        return self._ask_llm(prompt)
