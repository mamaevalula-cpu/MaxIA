# -*- coding: utf-8 -*-
"""
core/tool_registry.py — Единый реестр инструментов системы.

Решает проблему: агенты не знают о возможностях друг друга.

Возможности:
  • Регистрация инструментов с метаданными (описание, теги, capabilities)
  • Поиск по задаче/тегу/capability — автоматический выбор нужного инструмента
  • Цепочки инструментов (tool chaining)
  • Кэширование результатов
  • Метрики использования

Использование:
    reg = ToolRegistry.get()
    reg.register(ToolSpec(name="search", ...))

    # Найти инструмент для задачи
    tool = reg.find_for_task("найди информацию о BTC")
    result = tool.run("найди информацию о BTC")

    # Автоматическая цепочка
    results = reg.execute_chain(["search", "summarizer"], query)
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

log = logging.getLogger("core.tool_registry")

# ── Конфигурация ──────────────────────────────────────────────────────────────

CACHE_TTL_DEFAULT  = 300   # секунд по умолчанию для кэша результатов
TOOL_TIMEOUT       = 30    # таймаут выполнения инструмента (сек)
MAX_CHAIN_LENGTH   = 5     # максимальная длина цепочки инструментов


class ToolCategory(Enum):
    SEARCH      = "search"
    CODE        = "code"
    ANALYSIS    = "analysis"
    TRADING     = "trading"
    MEMORY      = "memory"
    MATH        = "math"
    MEDIA       = "media"
    MONITORING  = "monitoring"
    NOTIFICATION = "notification"
    UTILITY     = "utility"


@dataclass
class ToolSpec:
    """Спецификация инструмента."""
    name:         str
    description:  str
    category:     ToolCategory = ToolCategory.UTILITY
    tags:         List[str]    = field(default_factory=list)
    capabilities: List[str]    = field(default_factory=list)
    # Функция запуска: callable(query: str, **kwargs) → str
    run_fn:       Optional[Callable] = field(default=None, repr=False)
    # Метаданные
    enabled:      bool  = True
    timeout_sec:  int   = TOOL_TIMEOUT
    cache_ttl:    int   = 0      # 0 = не кэшировать
    priority:     int   = 5      # 1-10, выше = приоритетнее
    # Паттерны запросов, которые роутятся к этому инструменту
    route_patterns: List[str] = field(default_factory=list)
    _compiled_patterns: List[re.Pattern] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE)
            for p in self.route_patterns
        ]

    def matches(self, query: str) -> float:
        """
        Проверить насколько инструмент подходит для запроса.
        Returns: score 0..1 (0 = не подходит)
        """
        if not self.enabled:
            return 0.0

        score = 0.0

        # Проверка паттернов роутинга
        for pattern in self._compiled_patterns:
            if pattern.search(query):
                score = max(score, 0.8)
                break

        # Keyword matching с тегами и capabilities
        query_words = set(re.findall(r'\w+', query.lower()))
        tool_words  = set(
            w.lower()
            for term in (self.tags + self.capabilities + [self.name, self.description])
            for w in re.findall(r'\w+', term)
        )
        if query_words and tool_words:
            overlap = len(query_words & tool_words) / len(query_words)
            score = max(score, overlap * 0.6)

        return min(1.0, score)


@dataclass
class ToolResult:
    """Результат выполнения инструмента."""
    tool_name:   str
    query:       str
    output:      str
    success:     bool  = True
    from_cache:  bool  = False
    latency_ms:  float = 0.0
    error:       str   = ""


class ToolRegistry:
    """
    Singleton. Централизованный реестр инструментов.

    Автоматически регистрирует все агенты системы.
    """

    _instance: Optional["ToolRegistry"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}
        self._cache: Dict[str, Tuple[str, float]] = {}  # key → (result, expires_at)
        self._stats: Dict[str, Dict] = {}
        self._rlock = threading.RLock()
        log.info("ToolRegistry initialized")

    @classmethod
    def get(cls) -> "ToolRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Регистрация ───────────────────────────────────────────────────────────

    def register(self, spec: ToolSpec) -> None:
        """Зарегистрировать инструмент."""
        with self._rlock:
            self._tools[spec.name] = spec
            if spec.name not in self._stats:
                self._stats[spec.name] = {
                    "calls": 0, "successes": 0, "cache_hits": 0, "total_ms": 0.0
                }
        log.debug("Tool registered: %s [%s]", spec.name, spec.category.value)

    def register_agent(
        self,
        name:        str,
        agent:       Any,
        description: str,
        category:    ToolCategory = ToolCategory.UTILITY,
        tags:        List[str] = None,
        capabilities: List[str] = None,
        route_patterns: List[str] = None,
        cache_ttl:   int = 0,
        priority:    int = 5,
    ) -> None:
        """Зарегистрировать агента как инструмент."""
        def _run(query: str, **kwargs) -> str:
            try:
                if hasattr(agent, "process"):
                    result = agent.process(query, **kwargs)
                    return str(result) if result else ""
                elif callable(agent):
                    return str(agent(query, **kwargs))
                return ""
            except Exception as e:
                log.warning("Tool %s failed: %s", name, e)
                return f"⚠️ Ошибка инструмента {name}: {e}"

        spec = ToolSpec(
            name=name,
            description=description,
            category=category,
            tags=tags or [],
            capabilities=capabilities or [],
            run_fn=_run,
            cache_ttl=cache_ttl,
            priority=priority,
            route_patterns=route_patterns or [],
        )
        self.register(spec)

    def unregister(self, name: str) -> None:
        """Удалить инструмент из реестра."""
        with self._rlock:
            self._tools.pop(name, None)

    def enable(self, name: str) -> None:
        with self._rlock:
            if name in self._tools:
                self._tools[name].enabled = True

    def disable(self, name: str) -> None:
        with self._rlock:
            if name in self._tools:
                self._tools[name].enabled = False

    # ── Поиск инструментов ────────────────────────────────────────────────────

    def find_for_task(self, query: str, category: Optional[ToolCategory] = None) -> Optional[ToolSpec]:
        """Найти лучший инструмент для задачи."""
        candidates = self.rank_for_task(query, category)
        return candidates[0] if candidates else None

    def rank_for_task(
        self,
        query:    str,
        category: Optional[ToolCategory] = None,
        top_k:   int = 5,
    ) -> List[ToolSpec]:
        """Ранжировать инструменты по релевантности задаче."""
        with self._rlock:
            tools = list(self._tools.values())

        scored: List[Tuple[float, ToolSpec]] = []
        for tool in tools:
            if not tool.enabled:
                continue
            if category and tool.category != category:
                continue
            score = tool.matches(query)
            if score > 0.1:
                # Учитываем приоритет
                score = score * 0.8 + (tool.priority / 10) * 0.2
                scored.append((score, tool))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored[:top_k]]

    def find_by_name(self, name: str) -> Optional[ToolSpec]:
        """Найти инструмент по имени."""
        with self._rlock:
            return self._tools.get(name)

    def find_by_category(self, category: ToolCategory) -> List[ToolSpec]:
        """Найти все инструменты категории."""
        with self._rlock:
            return [t for t in self._tools.values()
                    if t.category == category and t.enabled]

    def find_by_tags(self, tags: List[str]) -> List[ToolSpec]:
        """Найти инструменты по тегам."""
        tag_set = set(t.lower() for t in tags)
        with self._rlock:
            return [
                tool for tool in self._tools.values()
                if tool.enabled and tag_set & {t.lower() for t in tool.tags}
            ]

    # ── Выполнение ────────────────────────────────────────────────────────────

    def execute(
        self,
        tool_name: str,
        query:     str,
        use_cache: bool = True,
        **kwargs,
    ) -> ToolResult:
        """
        Выполнить инструмент по имени.

        Args:
            tool_name: имя инструмента
            query:     запрос/задание
            use_cache: использовать кэш результатов
            **kwargs:  дополнительные параметры инструмента

        Returns: ToolResult
        """
        t0 = time.time()
        tool = self.find_by_name(tool_name)

        if not tool:
            return ToolResult(
                tool_name=tool_name, query=query,
                output=f"⚠️ Инструмент '{tool_name}' не найден",
                success=False,
            )

        if not tool.enabled:
            return ToolResult(
                tool_name=tool_name, query=query,
                output=f"⚠️ Инструмент '{tool_name}' отключён",
                success=False,
            )

        # Проверить кэш
        if use_cache and tool.cache_ttl > 0:
            cache_key = f"{tool_name}:{hash(query)}"
            cached = self._get_cache(cache_key)
            if cached is not None:
                self._record_stat(tool_name, success=True, cache_hit=True, ms=0)
                return ToolResult(
                    tool_name=tool_name, query=query,
                    output=cached, success=True, from_cache=True,
                    latency_ms=0.0,
                )

        # Выполнить
        if not tool.run_fn:
            return ToolResult(
                tool_name=tool_name, query=query,
                output=f"⚠️ Инструмент '{tool_name}' не имеет run_fn",
                success=False,
            )

        try:
            output = tool.run_fn(query, **kwargs)
            success = True
            error = ""
        except Exception as e:
            log.warning("Tool %s execution error: %s", tool_name, e)
            output = f"⚠️ Ошибка: {e}"
            success = False
            error = str(e)

        latency_ms = (time.time() - t0) * 1000
        self._record_stat(tool_name, success=success, cache_hit=False, ms=latency_ms)

        # Кэшировать если успешно
        if success and tool.cache_ttl > 0 and output:
            cache_key = f"{tool_name}:{hash(query)}"
            self._set_cache(cache_key, output, tool.cache_ttl)

        return ToolResult(
            tool_name=tool_name,
            query=query,
            output=output or "",
            success=success,
            latency_ms=latency_ms,
            error=error,
        )

    def auto_execute(self, query: str, category: Optional[ToolCategory] = None) -> ToolResult:
        """
        Автоматически выбрать и выполнить лучший инструмент для задачи.
        """
        tool = self.find_for_task(query, category)
        if not tool:
            return ToolResult(
                tool_name="none", query=query,
                output="⚠️ Подходящий инструмент не найден",
                success=False,
            )
        return self.execute(tool.name, query)

    def execute_chain(
        self,
        tool_names: List[str],
        initial_query: str,
        pass_output: bool = True,
    ) -> List[ToolResult]:
        """
        Выполнить цепочку инструментов.

        Args:
            tool_names:    список имён инструментов
            initial_query: начальный запрос
            pass_output:   передавать вывод предыдущего как вход следующему

        Returns: список результатов каждого инструмента
        """
        if len(tool_names) > MAX_CHAIN_LENGTH:
            tool_names = tool_names[:MAX_CHAIN_LENGTH]

        results: List[ToolResult] = []
        current_query = initial_query

        for name in tool_names:
            result = self.execute(name, current_query)
            results.append(result)
            if not result.success:
                break  # останавливаем цепочку при ошибке
            if pass_output and result.output:
                # Следующий инструмент получает вывод предыдущего + исходный запрос
                current_query = (
                    f"Исходный запрос: {initial_query}\n\n"
                    f"Результат предыдущего шага ({name}):\n{result.output}"
                )

        return results

    # ── Кэш ──────────────────────────────────────────────────────────────────

    def _get_cache(self, key: str) -> Optional[str]:
        with self._rlock:
            entry = self._cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            with self._rlock:
                self._cache.pop(key, None)
            return None
        return value

    def _set_cache(self, key: str, value: str, ttl: int) -> None:
        with self._rlock:
            self._cache[key] = (value, time.time() + ttl)

    def cleanup_cache(self) -> int:
        """Удалить устаревшие записи кэша. Returns: кол-во удалённых."""
        now = time.time()
        with self._rlock:
            expired = [k for k, (_, exp) in self._cache.items() if now > exp]
            for k in expired:
                del self._cache[k]
        return len(expired)

    # ── Статистика ────────────────────────────────────────────────────────────

    def _record_stat(self, name: str, success: bool, cache_hit: bool, ms: float) -> None:
        with self._rlock:
            if name not in self._stats:
                self._stats[name] = {"calls": 0, "successes": 0, "cache_hits": 0, "total_ms": 0.0}
            s = self._stats[name]
            s["calls"] += 1
            if success:
                s["successes"] += 1
            if cache_hit:
                s["cache_hits"] += 1
            s["total_ms"] += ms

    def get_stats(self) -> Dict:
        with self._rlock:
            tools_count = len(self._tools)
            enabled     = sum(1 for t in self._tools.values() if t.enabled)
            cache_size  = len(self._cache)
            stats_copy  = dict(self._stats)

        total_calls = sum(s["calls"] for s in stats_copy.values())
        return {
            "tools_registered": tools_count,
            "tools_enabled":    enabled,
            "cache_entries":    cache_size,
            "total_calls":      total_calls,
            "tool_stats":       stats_copy,
        }

    def list_tools(self) -> List[Dict]:
        """Список всех инструментов с описанием."""
        with self._rlock:
            return [
                {
                    "name": t.name,
                    "description": t.description[:80],
                    "category": t.category.value,
                    "tags": t.tags[:5],
                    "enabled": t.enabled,
                    "priority": t.priority,
                }
                for t in sorted(self._tools.values(), key=lambda x: x.priority, reverse=True)
            ]

    def get_report(self) -> str:
        s = self.get_stats()
        lines = [
            f"🔧 **Tool Registry**",
            f"  Инструментов: {s['tools_registered']} ({s['tools_enabled']} включено)",
            f"  Кэш: {s['cache_entries']} записей",
            f"  Вызовов всего: {s['total_calls']}",
        ]
        # Топ-5 по вызовам
        top = sorted(s["tool_stats"].items(), key=lambda x: x[1]["calls"], reverse=True)[:5]
        if top:
            lines.append("  Топ инструменты:")
            for name, ts in top:
                rate = round(ts["successes"] / max(ts["calls"], 1) * 100)
                lines.append(f"    • {name}: {ts['calls']} вызовов, {rate}% успех")
        return "\n".join(lines)


# ── Авторегистрация стандартных инструментов ──────────────────────────────────

def register_default_tools(registry: ToolRegistry, agents: Dict[str, Any]) -> None:
    """
    Зарегистрировать все агенты системы как инструменты.
    Вызывается из main.py после создания всех агентов.
    """

    _agent_specs = [
        dict(
            name="search",
            description="Поиск информации в интернете, Wikipedia, веб-страницы",
            category=ToolCategory.SEARCH,
            tags=["поиск", "интернет", "wikipedia", "веб", "search", "web"],
            capabilities=["search_web", "fetch_url", "wikipedia"],
            route_patterns=[
                r"найди|поищи|погуглить|загуглить|search|find online|look up",
                r"wikipedia|wiki|что такое|кто такой",
            ],
            cache_ttl=120,
            priority=7,
        ),
        dict(
            name="code_runner",
            description="Выполнение Python кода в изолированной среде",
            category=ToolCategory.CODE,
            tags=["код", "python", "выполнить", "запустить", "run", "execute"],
            capabilities=["run_python", "execute_code", "test_code"],
            route_patterns=[r"выполни код|запусти код|run code|execute|что вернёт"],
            cache_ttl=0,
            priority=8,
        ),
        dict(
            name="coder",
            description="Написание, изменение и рефакторинг кода",
            category=ToolCategory.CODE,
            tags=["код", "программирование", "функция", "класс", "refactor"],
            capabilities=["write_code", "modify_code", "debug", "review_code"],
            route_patterns=[r"напиши|измени|добавь|исправь|перепиши .*(код|функц|класс)"],
            cache_ttl=0,
            priority=9,
        ),
        dict(
            name="math",
            description="Математические и финансовые вычисления",
            category=ToolCategory.MATH,
            tags=["математика", "вычисление", "формула", "финансы", "math"],
            capabilities=["calculate", "solve_equation", "financial_math", "statistics"],
            route_patterns=[r"вычисли|посчитай|реши уравнени|интеграл|производная|NPV|IRR"],
            cache_ttl=3600,
            priority=8,
        ),
        dict(
            name="analyzer",
            description="Глубокий анализ данных, текста и ситуаций",
            category=ToolCategory.ANALYSIS,
            tags=["анализ", "исследование", "оценка", "analysis", "research"],
            capabilities=["analyze", "compare", "evaluate", "explain"],
            route_patterns=[r"анализ|исследуй|объясни|сравни|оцени|почему|как работает"],
            cache_ttl=300,
            priority=7,
        ),
        dict(
            name="trading",
            description="Торговля на Bybit: ордера, позиции, баланс",
            category=ToolCategory.TRADING,
            tags=["торговля", "bybit", "ордер", "позиция", "крипто", "trading"],
            capabilities=["place_order", "get_balance", "get_positions", "get_price"],
            route_patterns=[r"купи|продай|ордер|позиция|баланс|btc|eth|usdt|bybit"],
            cache_ttl=0,
            priority=10,
        ),
        dict(
            name="news",
            description="Последние новости: крипто, технологии, AI",
            category=ToolCategory.SEARCH,
            tags=["новости", "дайджест", "тренды", "news", "headlines"],
            capabilities=["get_news", "crypto_news", "tech_news", "ai_news"],
            route_patterns=[r"новости|дайджест|тренды|headlines|what's new"],
            cache_ttl=600,
            priority=6,
        ),
        dict(
            name="summarizer",
            description="Суммаризация текстов, документов и URL",
            category=ToolCategory.ANALYSIS,
            tags=["суммаризация", "краткое", "резюме", "tldr", "summary"],
            capabilities=["summarize_text", "summarize_url", "extract_key_points"],
            route_patterns=[r"суммаризируй|кратко|резюме|tldr|tl;dr|summarize"],
            cache_ttl=300,
            priority=6,
        ),
        dict(
            name="monitor",
            description="Мониторинг цен, сайтов и системных ресурсов",
            category=ToolCategory.MONITORING,
            tags=["мониторинг", "алерт", "цена", "следи", "monitor"],
            capabilities=["price_alert", "website_monitor", "system_metrics"],
            route_patterns=[r"следи|мониторинг|алерт|уведоми когда|monitor"],
            cache_ttl=0,
            priority=7,
        ),
        dict(
            name="image",
            description="Анализ изображений и OCR",
            category=ToolCategory.MEDIA,
            tags=["изображение", "фото", "ocr", "image", "vision"],
            capabilities=["analyze_image", "ocr", "describe_image"],
            route_patterns=[r"изображение|фото|картинк|ocr|image|vision"],
            cache_ttl=0,
            priority=6,
        ),
        dict(
            name="telegram",
            description="Отправка уведомлений в Telegram",
            category=ToolCategory.NOTIFICATION,
            tags=["telegram", "уведомление", "сообщение", "notification"],
            capabilities=["send_message", "send_notification"],
            route_patterns=[r"отправь в telegram|уведоми в telegram|telegram alert"],
            cache_ttl=0,
            priority=5,
        ),
        dict(
            name="key_manager",
            description="Управление API ключами провайдеров",
            category=ToolCategory.UTILITY,
            tags=["ключи", "api", "провайдер", "keys", "credentials"],
            capabilities=["check_keys", "add_key", "validate_key"],
            route_patterns=[r"ключи|api.?key|провайдер|credentials|check keys"],
            cache_ttl=0,
            priority=5,
        ),
        dict(
            name="planner",
            description="Планирование и выполнение сложных многошаговых задач",
            category=ToolCategory.UTILITY,
            tags=["план", "задача", "автономно", "plan", "complex", "multi-step"],
            capabilities=["create_plan", "execute_plan", "decompose_task"],
            route_patterns=[r"создай план|выполни по шагам|сложная задача|автономно"],
            cache_ttl=0,
            priority=8,
        ),
    ]

    for spec_kwargs in _agent_specs:
        agent_name = spec_kwargs["name"]
        agent = agents.get(agent_name)
        if agent:
            registry.register_agent(agent=agent, **spec_kwargs)
        else:
            # Инструмент без агента (placeholder)
            spec = ToolSpec(**{k: v for k, v in spec_kwargs.items()
                               if k in ToolSpec.__dataclass_fields__})
            registry.register(spec)


    # ── Analysis + Monitoring tools ─────────────────────────────────────────
    import sys as _sys
    _sys.path.insert(0, "/root/my_personal_ai")

    try:
        from tools.analysis import MarketAnalyzer
        from tools.server_monitor import ServerMonitor
        import os as _os, re as _re

        _mkt_analyzer = MarketAnalyzer()
        _srv_monitor  = ServerMonitor.get()

        def _run_market_analysis(query: str, **kw) -> str:
            m = _re.search(r"([A-Z]{2,10}USDT)", query.upper())
            symbol = m.group(1) if m else "BTCUSDT"
            try:
                _sys.path.insert(0, "/root/bybit-bot")
                from core.exchange import BybitExchange
                ex = BybitExchange(
                    _os.getenv("BYBIT_API_KEY",""),
                    _os.getenv("BYBIT_API_SECRET",""),
                    _os.getenv("BYBIT_TESTNET","true").lower()=="true"
                )
                candles = ex.get_klines(symbol, "15", 200)
                return _mkt_analyzer.analyze(symbol, candles)
            except Exception as e:
                from tools.analysis import analyze_market
                # Return demo analysis without live data
                return f"⚠️ Bybit API недоступен ({e}). Для анализа нужны API ключи в .env"

        registry.register(ToolSpec(
            name="market_analysis",
            description="Технический анализ: RSI, MACD, BB, EMA, ATR, сигналы BUY/SELL",
            category=ToolCategory.ANALYSIS,
            tags=["trading","crypto","rsi","macd","ema","bollinger","analysis","bybit","market","chart"],
            capabilities=["technical_analysis","indicator_calculation","signal_generation","regime_detection"],
            run_fn=_run_market_analysis,
            priority=8,
            route_patterns=[
                r"(анализ|проанализ|график|чарт|индикатор|rsi|macd|ema)",
                r"(technical.analysis|chart.analysis|indicator)",
                r"([A-Z]{2,10}USDT).*(анализ|signal|сигнал|цена|price)",
            ],
        ))

        registry.register(ToolSpec(
            name="server_resources",
            description="Ресурсы сервера: CPU, RAM, диск, нагрузка",
            category=ToolCategory.MONITORING,
            tags=["server","cpu","ram","memory","disk","resources","performance","psutil"],
            capabilities=["resource_monitoring","performance_check","health_check"],
            run_fn=lambda q, **kw: _srv_monitor.get_summary(),
            priority=7,
            route_patterns=[
                r"(ресурс|нагрузк|cpu|оперативн|сервер.*статус|server.*status|ram|память сервер)",
                r"(resource|load.average|memory.*usage|disk.*space)",
            ],
        ))
        log.info("Analysis + monitoring tools registered")
    except Exception as _tool_e:
        log.debug("Optional tools skipped: %s", _tool_e)


    log.info("Default tools registered: %d", len(_agent_specs))