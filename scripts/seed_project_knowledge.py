# -*- coding: utf-8 -*-
"""
scripts/seed_project_knowledge.py
Загружает в базу знаний AI-ассистента полную историю разработки:
- Архитектуру системы
- Все исправления и ПОЧЕМУ они сделаны именно так
- Логику принятых решений
- Как работает каждый компонент
- Типичные ошибки и их решения

Запуск: python scripts/seed_project_knowledge.py
"""

from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.memory_store import MemoryStore, KnowledgeEntry

mem = MemoryStore.get()

ENTRIES = [

# ═══════════════════════════════════════════════════════════════
# 1. АРХИТЕКТУРА СИСТЕМЫ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="architecture",
    title="Полная архитектура my_personal_ai — структура файлов и компонентов",
    importance=1.0,
    tags=["architecture", "files", "components", "overview"],
    source="claude_session",
    content="""
Система my_personal_ai — автономный персональный AI-ассистент.
Точка входа: launch.py → main.py → GUI + агенты.

СТРУКТУРА ФАЙЛОВ:
  main.py               — инициализация всех компонентов (8 шагов)
  launch.py             — точка запуска для pythonw.exe (без консоли)
  core/config.py        — конфигурация через .env, LLMProvider enum
  core/system_prompt.py — системный промт AI (BASE_SYSTEM_PROMPT + TASK_ADDONS)
  core/logger.py        — настройка логирования
  brain/orchestrator.py — главный мозг: классифицирует запросы, маршрутизирует к агентам
  brain/llm_router.py   — умный роутер LLM (DeepSeek→Groq→Claude→Ollama)
  memory/memory_store.py — SQLite БД: messages + knowledge + projects + tasks
  memory/rag_engine.py   — RAG: контекст из памяти + история диалога
  vector_stores/         — векторный поиск (SQLite backend по умолчанию)
  agents/base_agent.py   — базовый класс агентов
  agents/coder_agent.py  — пишет/изменяет Python-файлы, авто-исправление синтаксиса
  agents/trading_agent.py — управление Bybit, автономная торговля
  agents/telegram_agent.py — Telegram бот (bidirectional)
  agents/project_creator.py — создание новых проектов с авто-фиксом ошибок
  agents/analyzer_agent.py  — анализ кода и данных
  gui/main_window.py    — GUI на CustomTkinter: чат, дашборд, агенты, проекты
  bybit-bot/bot_core.py — ядро торгового бота (отдельный проект)

ПОРЯДОК ИНИЦИАЛИЗАЦИИ (main.py):
  1. Логирование
  2. MemoryStore (SQLite)
  3. VectorStoreManager
  4. RAGEngine + KnowledgeSeeder
  5. LLMRouter
  6. Агенты (coder, project_creator, trading, telegram, analyzer)
  7. BrainOrchestrator (регистрирует агентов)
  8. TelegramAgent.start() — фоновый поток

SINGLETON-паттерн: BrainOrchestrator.get(), LLMRouter.get(), MemoryStore.get()
"""),

# ═══════════════════════════════════════════════════════════════
# 2. КАК РАБОТАЕТ ОРКЕСТРАТОР
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="architecture",
    title="BrainOrchestrator — логика маршрутизации запросов и intent patterns",
    importance=1.0,
    tags=["orchestrator", "intent", "routing", "brain"],
    source="claude_session",
    content="""
BrainOrchestrator.process(request) — главный цикл обработки:

  1. _classify_intent(text) — regex-паттерны определяют намерение
  2. RAGEngine.get_context() — релевантный контекст из памяти
  3. _route(request, intent, rag_context, _step) — выбор агента/LLM
  4. _verify() — проверка для code_change и trading
  5. rag.learn_from_interaction() — сохранение в память
  6. _notify() — callbacks (например, в GUI)

INTENT_PATTERNS (порядок важен — dict проверяется по очереди):
  project_create  — "создай проект", "новое приложение", "создай telegram-бот"
  code_change     — "измени код", "напиши функцию", "исправь ошибку"
  trading         — "торгует", "баланс", "позиции", "купи", "bybit", "как там бот"
  analysis        — "анализ", "объясни", "почему", "сравни"
  memory          — "запомни", "сохрани", "что ты знаешь"
  rollback        — "откат", "отмени", "восстанови"
  status          — "статус", "состояние", "как дела"
  (fallback)      — LLM-чат

ВАЖНО: project_create ДОЛЖЕН стоять ДО code_change в словаре.
Иначе "создай telegram-бот" → code_change вместо project_create.
Причина: "создай" есть в обоих паттернах, но project_create специфичнее.

PROGRESS CALLBACK:
OrchestratorRequest.progress_callback(msg: str) → GUI обновляет "thinking bubble"
в реальном времени, показывая шаги: "Классифицирую...", "Запускаю CoderAgent..." и т.д.
"""),

# ═══════════════════════════════════════════════════════════════
# 3. LLM РОУТЕР — ПРИОРИТЕТЫ И ПОЧЕМУ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="architecture",
    title="LLMRouter — приоритеты провайдеров и логика выбора",
    importance=0.95,
    tags=["llm", "router", "deepseek", "groq", "ollama", "performance"],
    source="claude_session",
    content="""
ПРИОРИТЕТ ПРОВАЙДЕРОВ (важен для производительности):
  chat:    DeepSeek → Groq → Claude → Perplexity → Ollama
  code:    DeepSeek → Claude → Groq → Ollama
  trading: DeepSeek → Groq → Claude → Ollama
  analysis:DeepSeek → Claude → Groq → Perplexity → Ollama

ПОЧЕМУ OLLAMA В КОНЦЕ — не в начале:
  Ollama (локальный сервер) обычно НЕ запущен. При проверке timeout=2 сек.
  Если Ollama первый в цепочке — каждый запрос ждёт 2 секунды перед DeepSeek.
  Было: Ollama первый → каждый запрос +2-3 секунды задержки.
  Стало: DeepSeek первый → ответы за 4-6 сек вместо 7-14.

OLLAMA КЕШИРОВАНИЕ:
  Доступность Ollama кешируется на 300 секунд (5 минут).
  Если недоступен — 5 минут не проверяется, нет лишних timeout-ов.

ПОЧЕМУ НЕ ТОЛЬКО DEEPSEEK:
  DeepSeek может иметь перерывы, rate limits, или исчерпание баланса.
  Groq — бесплатный, очень быстрый (llama-3.3-70b), хороший fallback.
  Claude — высокое качество для сложных задач, аудита кода.

SSL verify=False:
  На Windows антивирус/прокси перехватывают TLS.
  certifi.where() не работает (чужой корневой сертификат).
  Решение: verify=False для всех исходящих запросов.
  Это безопасно для личного инструмента — все endpoint'ы захардкожены.

ИСТОРИЯ ДИАЛОГА — ОГРАНИЧЕНИЕ:
  Лимит: последние 6 сообщений, каждое обрезается до 800 символов.
  Почему: без ограничения токены растут с каждым ответом (5k→7k→9k→...)
  → ответы замедляются, стоимость растёт.
"""),

# ═══════════════════════════════════════════════════════════════
# 4. GUI — КАК РАБОТАЕТ ЧАТ И ИСПРАВЛЕННЫЕ БАГИ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="bugfix",
    title="GUI gui/main_window.py — все исправления и почему они сделаны",
    importance=0.95,
    tags=["gui", "chat", "send_button", "copy_paste", "history", "bugfix"],
    source="claude_session",
    content="""
КРИТИЧЕСКИЙ БАГ — кнопка Send зависала навсегда:
  Причина: после отправки код делал self._ph = True (флаг "показан placeholder")
           НО не вставлял текст placeholder'а в поле.
           Поле — пустое. Пользователь печатает → FocusIn не срабатывает
           (фокус уже на поле) → _ph остаётся True.
           Нажимает Send → "if self._ph: return" → ЗАБЛОКИРОВАНО НАВСЕГДА.
  Исправление: после отправки _ph = False (поле чистое, готово к вводу).
               Placeholder возвращается только при потере фокуса (_inp_focus_out).

ДОПОЛНИТЕЛЬНАЯ ЗАЩИТА от зависания:
  _process() обёрнут в try/finally → _thinking = False ВСЕГДА сбрасывается.
  Watchdog timer 90 сек → если ответ завис, кнопка разблокируется автоматически.

ПОЛЕ ВВОДА — CTkTextbox заменён на нативный tk.Text:
  Причина: CTkTextbox не поддерживал Ctrl+V корректно на Windows.
  tk.Text имеет нативный clipboard на уровне ОС.
  Привязки: Ctrl+V (вставить, очистить placeholder), Ctrl+A, Ctrl+Z (undo),
            Ctrl+C, ПКМ (контекстное меню).

КОПИРОВАНИЕ ИЗ ПУЗЫРЬКОВ СООБЩЕНИЙ:
  tk.Text в state="disabled" НЕ получает keyboard focus автоматически.
  Поэтому Ctrl+C не работал даже при визуальном выделении.
  Исправление: bind("<Button-1>", w.focus_set()) + явный bind("<Control-c>")
  Кнопка "⎘ Копировать" + правый клик → контекстное меню.

ИСТОРИЯ ПЕРЕПИСКИ — сохранение и восстановление:
  Сохранение: сообщения пользователя → MemoryStore сразу при _chat_add().
              Ответы AI → оркестратор через learn_from_interaction().
  Загрузка: на старте _load_chat_history() читает последние 60 сообщений
            из БД (source="gui") и показывает компактным стилем.
  Формат ts: хранится как Unix timestamp (float), конвертируется через
             datetime.fromtimestamp(ts).strftime("%H:%M").

ШАГИ АГЕНТОВ В ЧАТ (живое обновление):
  OrchestratorRequest.progress_callback → _q.put({"action": "step_update"})
  → _update_step() обновляет thinking bubble в реальном времени.
  Показывает: "Классифицирую...", "Запускаю CoderAgent...", "Получен ответ от deepseek..."
"""),

# ═══════════════════════════════════════════════════════════════
# 5. ТОРГОВЫЙ АГЕНТ — АВТОНОМНАЯ ТОРГОВЛЯ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="trading",
    title="TradingAgent — автономная торговля, методы, Bybit API, разрешения",
    importance=1.0,
    tags=["trading", "bybit", "autonomous", "order", "position", "api"],
    source="claude_session",
    content="""
РАЗРЕШЕНИЯ:
  TRADING_LIVE_CONFIRMED=true установлен в .env.
  AI имеет право торговать автономно без подтверждения каждой сделки.
  Ограничение риска: ≤ 1% депозита на сделку (жёстко в коде).

МЕТОДЫ TradingAgent:
  process(text)          — обрабатывает текстовые команды
  get_status()           — статус бота: баланс, позиции, режим
  get_balance()          — баланс USDT
  get_positions()        — открытые позиции с PnL
  get_pairs()            — торгуемые пары
  start_bot()            — запустить bybit-bot subprocess
  stop_bot()             — остановить бот
  place_order(symbol, side, qty, order_type, stop_loss, take_profit)
                         — разместить ордер через Bybit API V5
  close_position(symbol) — закрыть конкретную позицию
  close_all_positions()  — закрыть все позиции
  get_market_price(sym)  — текущая цена
  set_risk(pct)          — установить риск %

КОМАНДЫ (распознаются в process()):
  "как там торгует наш бот" → get_status()
  "купи 0.001 BTCUSDT"     → place_order("BTCUSDT", "Buy", 0.001)
  "продай 0.5 ETHUSDT"     → place_order("ETHUSDT", "Sell", 0.5)
  "закрой BTCUSDT"          → close_position("BTCUSDT")
  "закрой все позиции"      → close_all_positions()
  "цена BTCUSDT"            → get_market_price("BTCUSDT")
  "установи риск 0.5"       → set_risk(0.5)

ПРЯМОЙ API (без BotCore):
  _place_order_direct() вызывает Bybit V5 API напрямую через httpx.
  Подписывает запрос HMAC-SHA256: timestamp + api_key + recv_window + body.
  TESTNET: api-testnet.bybit.com | LIVE: api.bybit.com.
  BYBIT_TESTNET=true в .env → testnet по умолчанию.

СВЯЗЬ С BYBIT-BOT:
  TradingAgent → BotCore (bybit-bot/bot_core.py) через lazy-import.
  BotCore управляет subprocess главного торгового бота.
  Методы BotCore: start(), stop(), get_status(), get_balance(),
                  get_positions(), close_all_positions(), get_ticker().

LLM-АНАЛИЗ ТОРГОВЛИ:
  _trading_analysis() вставляет реальный статус бота в контекст LLM.
  Промт: "У тебя есть прямой доступ к боту. Ты МОЖЕШЬ размещать ордера."
"""),

# ═══════════════════════════════════════════════════════════════
# 6. TELEGRAM АГЕНТ — ДВУСТОРОННЯЯ СВЯЗЬ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="architecture",
    title="TelegramAgent — двусторонняя связь, SSL fix, команды",
    importance=0.9,
    tags=["telegram", "ssl", "bot", "bidirectional"],
    source="claude_session",
    content="""
ДВУСТОРОННЯЯ РАБОТА:
  Входящие сообщения в Telegram → _on_message → brain_callback (OrchestratorRequest)
  → BrainOrchestrator.process() → ответ → reply_text → update.message.reply_text()
  Ответ также сохраняется в MemoryStore (source="telegram").

КОМАНДЫ БОТА:
  /start, /help — приветствие
  /status       — статус системы (через оркестратор)
  /balance      — баланс Bybit
  /positions    — открытые позиции

УВЕДОМЛЕНИЕ О СТАРТЕ:
  При запуске отправляет в cfg.telegram_chat_id сообщение о готовности.

SSL FIX (Windows TLS interception):
  python-telegram-bot использует свой httpx-клиент и игнорирует наш ssl_ctx.
  Решение: ssl._create_default_https_context = ssl._create_unverified_context
           применяется глобально ДО создания Application.
  Сначала тест: httpx.get("https://api.telegram.org", verify=certifi.where())
  Если падает — применяем bypass.

FALLBACK ДЛЯ MARKDOWN:
  Если reply с parse_mode="Markdown" падает (спецсимволы) →
  повторяет без parse_mode. Не зависает.

CONFLICT ERROR:
  "Conflict: terminated by other getUpdates request" —
  возникает при перезапуске, если старый polling не успел завершиться.
  Безопасно — через несколько секунд новый polling захватит управление.

ПРЯМАЯ ОТПРАВКА (без Application):
  _send_direct() → httpx.post к api.telegram.org, verify=False.
  Используется когда бот не запущен (нет self._application).
"""),

# ═══════════════════════════════════════════════════════════════
# 7. CODER AGENT — КАК ПИШЕТ И ИСПРАВЛЯЕТ КОД
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="architecture",
    title="CoderAgent + ProjectCreatorAgent — написание кода и авто-исправление",
    importance=0.9,
    tags=["coder", "project", "ast", "autofix", "syntax"],
    source="claude_session",
    content="""
CoderAgent — agents/coder_agent.py:
  Пишет/изменяет Python-файлы.
  Перед изменением: делает backup (filename.bak).
  После записи: проверяет синтаксис через ast.parse().
  rollback() — восстанавливает из .bak файла.

ProjectCreatorAgent — agents/project_creator.py:
  Создаёт полную структуру нового проекта.
  _generate_main_with_fix() — генерирует main.py, при SyntaxError → LLM исправляет,
                              до 3 попыток.
  _validate_project() — ast.parse() для всех .py файлов.
  _autofix_errors() — передаёт ошибки в LLM, LLM возвращает исправленный код,
                      проверяет ast.parse(), только потом записывает.
  Проекты создаются в: my_personal_ai/projects/

АВТО-ИСПРАВЛЕНИЕ ЦИКЛ:
  generate → ast.parse → если SyntaxError → LLM fix → ast.parse → если OK → write
  Максимум 3 итерации. Если не исправил — сообщает об ошибке.

BACKUP СТРАТЕГИЯ:
  filename.bak создаётся всегда перед изменением.
  rollback: восстанавливает .bak → переименовывает в оригинальный файл.
"""),

# ═══════════════════════════════════════════════════════════════
# 8. WINDOWS-СПЕЦИФИЧНЫЕ ПРОБЛЕМЫ И РЕШЕНИЯ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="solution",
    title="Windows-специфичные баги и их решения в my_personal_ai",
    importance=0.95,
    tags=["windows", "ssl", "encoding", "pythonw", "cp1252", "fix"],
    source="claude_session",
    content="""
1. SSL CERTIFICATE_VERIFY_FAILED:
   Причина: антивирус/прокси перехватывает TLS, подменяет сертификат.
            certifi не знает о корпоративном CA → верификация падает.
   Решение: verify=False везде (httpx, requests, telegram).
            В llm_router.py: _make_http_client() сначала пробует certifi,
            при ошибке переключается на verify=False.
            В telegram_agent.py: ssl._create_default_https_context = ssl._create_unverified_context

2. UnicodeEncodeError в print() (CP1252 vs UTF-8):
   Причина: Windows консоль использует CP1252, emoji не кодируются.
   Решение: PYTHONIOENCODING=utf-8 в bat/env + _p() wrapper в main.py
            _p() перехватывает UnicodeEncodeError и выводит ASCII.

3. pythonw.exe (запуск без консоли):
   Причина: pythonw.exe устанавливает sys.stdout = None → print() падает.
   Решение: launch.py перенаправляет stdout/stderr в logs/launch.log
            при sys.stdout is None.
   Shortcut ведёт на pythonw.exe + launch.py (не main.py напрямую).

4. readline ImportError:
   Причина: модуль readline есть только на Linux/Mac.
   Решение: try: import readline except ImportError: pass

5. Telegram Conflict (два бота одновременно):
   При перезапуске старый polling может ещё не завершиться.
   drop_pending_updates=True помогает, но конфликт на несколько секунд неизбежен.
   Безопасно — разрешается автоматически.

6. BrainOrchestrator множественная инициализация:
   В логах видно несколько "BrainOrchestrator ready" — это рестарты приложения,
   не баг. Singleton корректен внутри одного процесса.
"""),

# ═══════════════════════════════════════════════════════════════
# 9. СИСТЕМНЫЙ ПРОМТ AI
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="context",
    title="Системный промт AI — структура, принципы, торговые права",
    importance=1.0,
    tags=["system_prompt", "persona", "principles", "trading_rights"],
    source="claude_session",
    content="""
Файл: core/system_prompt.py
Функция: build_system_prompt(task_type, rag_context, projects, agent_statuses)

BASE_SYSTEM_PROMPT содержит 4 ключевых принципа:

1. НЕМЕДЛЕННОЕ ДЕЙСТВИЕ:
   AI — исполнитель, не консультант. Делает сразу, не просит разрешения.
   "Создаю Telegram-бота. Вот структура..." → показывает код → "Что добавить?"

2. САМОИСПРАВЛЕНИЕ ОШИБОК:
   При ошибке: анализирует traceback построчно, исправляет, говорит что изменил.
   Формат: "Причина: ...\nФайл: ...:строка\nИсправление: ..."

3. ОДНА СЕССИЯ — ОДИН КОНТЕКСТ:
   Помнит весь разговор. Не начинает с нуля. "Продолжи" — знает о чём речь.

4. САМОДОРАБОТКА:
   На "доработай себя" → анализирует слабые места → предлагает изменения в:
   а) core/system_prompt.py (промт)
   б) agents/*.py (код агентов)
   в) brain/orchestrator.py (роутинг)
   Реализует через CoderAgent.

ТОРГОВЫЕ ПРАВА (ключевой раздел):
   TRADING_LIVE_CONFIRMED=true — пользователь дал карт-бланш.
   AI МОЖЕТ: place_order(), close_position(), set_risk(), start_bot().
   AI НЕ ГОВОРИТ "у меня нет доступа" — у него ЕСТЬ доступ через TradingAgent.

TASK_ADDONS — дополнения по типу задачи:
   "code"     — рабочий Python, только изменённые участки с ±3 строк контекста
   "analysis" — Факты → Анализ → Вывод → Риски
   "trading"  — пара, таймфрейм, SL/TP, риск ≤ 1%
   "chat"     — по делу, без воды
"""),

# ═══════════════════════════════════════════════════════════════
# 10. КАК ВНОСИТЬ ИЗМЕНЕНИЯ В СИСТЕМУ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="context",
    title="Как правильно изменять и дорабатывать my_personal_ai",
    importance=0.95,
    tags=["development", "workflow", "changes", "test", "syntax"],
    source="claude_session",
    content="""
РАБОЧИЙ ПРОЦЕСС ИЗМЕНЕНИЙ:

1. Читаем файл перед изменением (Read tool)
2. Вносим изменения (Edit tool — не пишем файл целиком, только diff)
3. Проверяем синтаксис: python -c "import ast; ast.parse(open('file.py').read())"
4. Проверяем логику: python -c "from module import Class; ..."
5. Запускаем систему, смотрим логи в logs/

КЛЮЧЕВЫЕ ПАТТЕРНЫ:
  Новый агент: наследовать BaseAgent, реализовать info(), can_handle(), process()
  Новый intent: добавить в INTENT_PATTERNS (порядок важен!)
  Новая LLM: добавить в LLMProvider enum + _call_X() + _build_priority_chain()

ФАЙЛЫ КОТОРЫЕ НЕЛЬЗЯ ТРОГАТЬ БЕЗ ОСТОРОЖНОСТИ:
  core/config.py   — изменение сломает всю систему (LLMProvider enum)
  memory/memory_store.py — изменение схемы БД требует миграции
  brain/orchestrator.py  — intent_patterns порядок критичен

ЛОГИ:
  logs/brain.log   — все запросы к оркестратору + intent + LLM время
  logs/agents.log  — старт/стоп агентов, ошибки
  logs/errors.log  — все исключения с traceback
  logs/trading.log — торговые операции

БЫСТРАЯ ДИАГНОСТИКА:
  "Кнопка Send не работает" → _ph флаг завис или _thinking=True
  "AI не отвечает"          → смотреть logs/brain.log, errors.log
  "Telegram не работает"   → SSL, или конфликт двух инстанций бота
  "Ответы медленные"       → Ollama в цепочке провайдеров первый
  "Торговля не работает"   → TRADING_LIVE_CONFIRMED, BYBIT_API_KEY в .env

ТЕСТИРОВАНИЕ INTENT ROUTING:
  python -c "
  from brain.orchestrator import INTENT_PATTERNS
  text = 'твой запрос'
  for intent, pat in INTENT_PATTERNS.items():
      if pat.search(text): print(intent); break
  "
"""),

# ═══════════════════════════════════════════════════════════════
# 11. ИСТОРИЯ РАЗРАБОТКИ — ХРОНОЛОГИЯ ИЗМЕНЕНИЙ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="context",
    title="Хронология разработки — что когда делалось и в каком порядке",
    importance=0.9,
    tags=["history", "chronology", "changes", "fixes"],
    source="claude_session",
    content="""
ПОРЯДОК РАЗРАБОТКИ И КЛЮЧЕВЫЕ РЕШЕНИЯ:

1. ЗАПУСК (launch.py + pythonw.exe):
   Проблема: "Ошибка запуска" при двойном клике.
   Причина: python.exe через .bat файл + emoji в print() → UnicodeEncodeError.
   Решение: launch.py перенаправляет stdout при sys.stdout is None,
            переход на pythonw.exe напрямую, _p() wrapper.

2. SSL FIX (llm_router.py):
   Проблема: "AI недоступен: SSL CERTIFICATE_VERIFY_FAILED" в чате.
   Причина: Windows антивирус перехватывает TLS.
   Решение: _make_http_client() — certifi fallback → verify=False.

3. СИСТЕМНЫЙ ПРОМТ (core/system_prompt.py — новый файл):
   Проблема: AI говорил "у меня нет доступа к боту".
   Решение: Создан BUILD_SYSTEM_PROMPT с 4 принципами + явным указанием
            что у AI ЕСТЬ агенты как инструменты.

4. INTENT ROUTING (orchestrator.py):
   Проблема: "создай проект news_bot" → code_change (из-за "бот").
   Решение: project_create перед code_change в INTENT_PATTERNS.

5. ПРОЕКТ АВТО-ФИКС (project_creator.py):
   Добавлены: _generate_main_with_fix(), _validate_project(), _autofix_errors()
   3 попытки LLM-исправления синтаксических ошибок.

6. TELEGRAM SSL + КОМАНДЫ (telegram_agent.py):
   Добавлены /status, /balance, /positions команды.
   SSL fix через ssl._create_default_https_context.
   Startup notification при запуске.

7. COPY/PASTE GUI (main_window.py):
   Заменён CTkTextbox → нативный tk.Text.
   Добавлены все keyboard bindings (Ctrl+V, Ctrl+C, Ctrl+A, Ctrl+Z, ПКМ).
   Fix: Ctrl+C в disabled tk.Text требует явного bind + focus_set.

8. ШАГИ АГЕНТОВ В ЧАТ:
   OrchestratorRequest.progress_callback + step_update в очереди.
   Пользователь видит в реальном времени что происходит.

9. ПРОИЗВОДИТЕЛЬНОСТЬ (llm_router.py + orchestrator.py):
   Ollama → конец цепочки (не первый), кеш 300 сек.
   История: 10→6 сообщений, обрезка до 800 символов.
   Было: 7-14 сек. Стало: 4-6 сек.

10. ТОРГОВЫЕ ПРАВА (trading_agent.py + .env):
    Добавлены: place_order(), close_position(), get_market_price(), set_risk().
    TRADING_LIVE_CONFIRMED=true.
    Intent pattern расширен: "торгует", "купи", "продай", "как там бот".

11. HISTORY PERSISTENCE (main_window.py):
    _load_chat_history() на старте → последние 60 сообщений из БД.
    _save_message() → сохранение сразу при _chat_add().
    Формат ts: Unix float → datetime.fromtimestamp().

12. SEND BUTTON BUG FIX (main_window.py):
    Причина: _ph=True без placeholder текста → блокировало Send.
    Решение: после отправки _ph=False, try/finally в _process(), watchdog 90s.
"""),

# ═══════════════════════════════════════════════════════════════
# 12. КОНФИГУРАЦИЯ — КЛЮЧЕВЫЕ ПАРАМЕТРЫ
# ═══════════════════════════════════════════════════════════════
KnowledgeEntry(
    category="context",
    title="Ключевые параметры .env и core/config.py",
    importance=0.9,
    tags=["config", "env", "keys", "settings"],
    source="claude_session",
    content="""
ФАЙЛ: my_personal_ai/.env

LLM ПРОВАЙДЕРЫ:
  DEEPSEEK_API_KEY=...     — основной (deepseek.com)
  ANTHROPIC_API_KEY=...    — Claude (anthropic.com)
  GROQ_API_KEY=...         — бесплатный быстрый fallback
  OLLAMA_URL=http://localhost:11434  — локальный (обычно не запущен)

TELEGRAM:
  TELEGRAM_BOT_TOKEN=...   — от @BotFather
  TELEGRAM_CHAT_ID=...     — твой Telegram user ID

BYBIT:
  BYBIT_API_KEY=...
  BYBIT_API_SECRET=...
  BYBIT_TESTNET=true       — testnet по умолчанию (безопасно)
  TRADING_LIVE_CONFIRMED=true  — ← нужно для автономной торговли

СИСТЕМА:
  LOG_LEVEL=INFO
  VECTOR_BACKEND=sqlite    — sqlite | chroma | faiss

ТЕКУЩИЕ ЗНАЧЕНИЯ (из рабочей конфигурации):
  DeepSeek, Groq, Claude — настроены и работают
  Telegram бот — работает, SSL bypass активен
  Bybit — testnet режим, ключи заданы
  TRADING_LIVE_CONFIRMED=true — AI может торговать автономно

core/config.py:
  LLMProvider(Enum): OLLAMA, DEEPSEEK, CLAUDE, GROQ, PERPLEXITY
  cfg.llm_priority — список провайдеров по умолчанию
  cfg.bybit_testnet — bool из BYBIT_TESTNET
  cfg.trading_live_confirmed — bool из TRADING_LIVE_CONFIRMED
  cfg.PROJECTS_DIR — папка для проектов
"""),

]  # end ENTRIES


def main():
    import sys, io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    print(f"Загрузка знаний в базу... ({len(ENTRIES)} записей)")
    for i, entry in enumerate(ENTRIES, 1):
        try:
            entry_id = mem.add_knowledge(entry)
            print(f"  [{i:2d}/{len(ENTRIES)}] OK  [{entry.category}] {entry.title[:60]}")
        except Exception as e:
            print(f"  [{i:2d}/{len(ENTRIES)}] ERR [{entry.category}] {entry.title[:40]}: {e}")

    # Проверка
    total = mem.stats()
    print(f"\nГотово. Всего записей в knowledge: {total.get('knowledge', '?')}")
    print("Теперь AI знает всю историю разработки и логику принятых решений.")


if __name__ == "__main__":
    main()
