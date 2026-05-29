# -*- coding: utf-8 -*-
"""
core/knowledge_seeder.py — Загрузчик начальных знаний в систему.

При первом запуске заполняет MemoryStore и VectorStore базой знаний:
  • Архитектура текущего торгового бота (bybit-bot)
  • Ошибки и решения из прошлых сессий
  • Стратегии и конфигурации
  • Промпты и инструкции

Также умеет импортировать контекст из:
  • Файлов JSON (data/prior_context.json)
  • Директории с .txt/.md файлами
  • Напрямую переданного текста
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("core.seeder")

BASE_DIR = Path(__file__).parent.parent
SEEDED_FLAG = BASE_DIR / "data" / ".knowledge_seeded"

# ── Встроенные знания о проекте ───────────────────────────────────────────────

BUILTIN_KNOWLEDGE = [
    {
        "category": "architecture",
        "title": "Структура bybit-bot",
        "content": """Торговый бот Bybit расположен в bybit-bot/.
Ключевые файлы:
- main_gui.py     → GUI-запуск: BotCore + DeepSeekHandler + AITrader + AgentCore
- bot_core.py     → управление процессом бота, API Bybit, статус
- gui_manager.py  → CustomTkinter GUI, CommandParser, чат-интерфейс
- agent_core.py   → AI-агент: classify → generate patch → test → apply
- code_engine.py  → безопасное изменение кода (backup + test + rollback)
- deepseek_handler.py → DeepSeek V3/R1 + Groq fallback
- ai_trader.py    → сканер рынка: EMA/RSI/MACD/BB + adaptive learning
- message_bridge.py → file-based IPC между GUI и Telegram
- monitoring/telegram_controller.py → Telegram-бот с командами""",
        "importance": 0.9,
        "tags": ["bybit", "bot", "architecture"],
    },
    {
        "category": "solution",
        "title": "Исправление CommandParser — порядок правил",
        "content": """Критический баг: правило close_all должно идти ПЕРЕД positions в списке _RULES.
Иначе 'закрой все позиции' матчится как positions вместо close_all.
Правило: более специфичные команды всегда размещать перед общими.""",
        "importance": 0.8,
        "tags": ["gui", "parser", "bug"],
    },
    {
        "category": "solution",
        "title": "Исправление UnicodeEncodeError в Windows консоли",
        "content": """При запуске скриптов с эмодзи на Windows cp1252 возникает UnicodeEncodeError.
Решение: добавить в начало скрипта:
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')""",
        "importance": 0.7,
        "tags": ["windows", "encoding", "bug"],
    },
    {
        "category": "solution",
        "title": "Async/sync bridge для Telegram+AgentCore",
        "content": """TelegramController async, AgentCore sync.
Решение: ThreadPoolExecutor + loop.run_in_executor() для вызова sync-кода из async.
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor() as pool:
    future = pool.submit(agent.process, text)
    result = await asyncio.get_event_loop().run_in_executor(None, future.result)""",
        "importance": 0.8,
        "tags": ["async", "telegram", "agent"],
    },
    {
        "category": "strategy",
        "title": "LLM Приоритет: экономия токенов",
        "content": """Порядок использования LLM (по убыванию приоритета):
1. Ollama (локально, бесплатно) — для рутинных задач
2. DeepSeek V3 — основной для кода
3. Claude Sonnet — проверка и финальный аудит
4. Groq llama — бесплатный резерв
5. Perplexity — для поиска в интернете

При исчерпании токенов: автоматически переключаться вниз.
Сложные задачи ставить в очередь и выполнять при восстановлении токенов.""",
        "importance": 0.9,
        "tags": ["llm", "tokens", "cost"],
    },
    {
        "category": "strategy",
        "title": "Безопасное изменение кода",
        "content": """Цикл безопасного изменения кода:
1. create_backup(file)     — создать .bak копию
2. generate_patch(task)    — попросить LLM сгенерировать патч (JSON)
3. test_syntax(new_code)   — ast.parse проверка
4. apply_patch()           — записать изменения
5. test_compile(file)      — py_compile в subprocess
6. rollback() если тест не прошёл

Разрешённые файлы: только из ALLOWED_PATHS списка.""",
        "importance": 0.9,
        "tags": ["code", "safety", "backup"],
    },
    {
        "category": "context",
        "title": "Настройки рисков торговли",
        "content": """Правила управления рисками:
- Риск на сделку: ≤ 1% от депозита
- Максимальная экспозиция: ≤ 15%
- Daily loss limit: 3-5%
- Обязательный Stop-Loss на каждой позиции
- По умолчанию: торговля на TESTNET (BYBIT_TESTNET=true)
- Для mainnet: TRADING_LIVE_CONFIRMED=true в .env""",
        "importance": 0.95,
        "tags": ["trading", "risk", "safety"],
    },
    {
        "category": "context",
        "title": "Структура my_personal_ai",
        "content": """my_personal_ai/ — персональная AI-система.
Компоненты:
- brain/orchestrator.py  → главный оркестратор всех запросов
- brain/llm_router.py    → умный маршрутизатор LLM
- agents/                → модульные агенты
- memory/                → SQLite + RAG
- vector_stores/         → VectorStoreManager
- auth/                  → зашифрованные секреты + браузер-авторизация
- gui/                   → CustomTkinter GUI
- projects/              → создаваемые проекты""",
        "importance": 1.0,
        "tags": ["architecture", "personal_ai"],
    },
    {
        "category": "fact",
        "title": "Технические требования системы",
        "content": """Python 3.11+
Обязательно: httpx, python-dotenv
Опционально: customtkinter, cryptography, chromadb, python-telegram-bot
Тестирование через pytest (pytest.ini в корне)
Логи в my_personal_ai/logs/""",
        "importance": 0.7,
        "tags": ["requirements", "setup"],
    },
]


class KnowledgeSeeder:
    """Загружает начальные знания при первом запуске."""

    def __init__(self) -> None:
        from memory.memory_store import MemoryStore
        from memory.rag_engine import RAGEngine
        self._memory = MemoryStore.get()
        self._rag = RAGEngine.get()

    def seed_if_needed(self) -> bool:
        """
        Загрузить знания если ещё не загружались.
        Возвращает True если был выполнен сидинг.
        """
        if SEEDED_FLAG.exists():
            log.debug("Knowledge already seeded, skipping")
            return False

        log.info("First run — seeding knowledge base...")
        self.seed_all()

        # Отметить что сидинг выполнен
        SEEDED_FLAG.parent.mkdir(parents=True, exist_ok=True)
        SEEDED_FLAG.write_text(
            f"seeded={time.time()}\n"
            f"entries={len(BUILTIN_KNOWLEDGE)}\n",
            encoding="utf-8"
        )
        return True

    def seed_all(self) -> int:
        """Загрузить все встроенные знания. Возвращает количество записей."""
        count = 0

        # 1. Встроенные знания
        for item in BUILTIN_KNOWLEDGE:
            try:
                self._rag.save_knowledge(
                    category=item["category"],
                    title=item["title"],
                    content=item["content"],
                    tags=item.get("tags", []),
                    importance=item.get("importance", 0.5),
                    source="builtin"
                )
                count += 1
            except Exception as e:
                log.debug("Seed error: %s", e)

        # 2. Файл prior_context.json (если есть)
        prior = BASE_DIR / "data" / "prior_context.json"
        if prior.exists():
            count += self._seed_from_json(prior)

        # 3. Контекст из bybit-bot (README, CLAUDE.md)
        count += self._seed_from_docs()

        log.info("Knowledge seeded: %d entries", count)
        return count

    def _seed_from_json(self, path: Path) -> int:
        """Загрузить контекст из JSON-файла."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            count = 0
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        self._rag.save_knowledge(
                            category=item.get("category", "context"),
                            title=item.get("title", "Импортированный контекст"),
                            content=item.get("content", str(item)),
                            source="prior_context.json"
                        )
                        count += 1
            return count
        except Exception as e:
            log.debug("JSON seed failed: %s", e)
            return 0

    def _seed_from_docs(self) -> int:
        """Загрузить контекст из файлов документации."""
        count = 0
        doc_files = [
            BASE_DIR.parent / "bybit-bot" / "README.md",
            BASE_DIR.parent / "CLAUDE.md",
            BASE_DIR / "README.md",
        ]
        for doc_path in doc_files:
            if doc_path.exists():
                try:
                    content = doc_path.read_text(encoding="utf-8")[:5000]
                    self._rag.save_knowledge(
                        category="context",
                        title=f"Документация: {doc_path.name}",
                        content=content,
                        source=str(doc_path.name),
                        importance=0.6
                    )
                    count += 1
                except Exception as e:
                    log.debug("Doc seed %s failed: %s", doc_path, e)
        return count

    def add_context(self, text: str, category: str = "context",
                    title: str = "", importance: float = 0.7) -> int:
        """
        Добавить произвольный контекст в базу знаний.
        Используй для ручного пополнения из GUI или CLI.
        """
        return self._rag.save_knowledge(
            category=category,
            title=title or text[:60],
            content=text,
            source="manual",
            importance=importance
        )

    def import_chat_history(self, history: List[Dict]) -> int:
        """
        Импортировать историю чата (список {role, content}).
        Для загрузки прошлых диалогов.
        """
        from memory.memory_store import Message
        count = 0
        for msg in history:
            try:
                self._memory.add_message(Message(
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    source="imported",
                    session_id="imported"
                ))
                count += 1
            except Exception:
                pass
        log.info("Imported %d chat messages", count)
        return count

    def reset_seed_flag(self) -> None:
        """Сбросить флаг сидинга (для повторной загрузки)."""
        if SEEDED_FLAG.exists():
            SEEDED_FLAG.unlink()
            log.info("Seed flag reset — will re-seed on next launch")
