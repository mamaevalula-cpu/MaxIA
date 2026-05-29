# -*- coding: utf-8 -*-
"""
main.py — Точка входа системы my_personal_ai.

Запуск:
    python main.py              # GUI + все агенты
    python main.py --no-gui     # только фоновые агенты
    python main.py --setup      # первичная настройка
    python main.py --status     # вывести статус и выйти

Порядок инициализации:
  1. Логирование
  2. Конфиг + проверка зависимостей
  3. Секреты (SecretManager)
  4. Память (MemoryStore + RAGEngine)
  5. Векторные базы (VectorStoreManager)
  6. LLM Router
  7. Агенты (Coder, ProjectCreator, Trading, Telegram, Analyzer)
  8. BrainOrchestrator (регистрирует агентов)
  9. GUI
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

# ── uvloop: replace default asyncio event loop with libuv (faster) ────────────
try:
    import uvloop
    uvloop.install()   # replaces asyncio default loop policy system-wide
    print("  ⚡ uvloop enabled (libuv async backend)")
except ImportError:
    pass  # graceful fallback to standard asyncio

log = logging.getLogger("main")

# Убедимся что корень проекта в sys.path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── Зависимости ───────────────────────────────────────────────────────────────

def check_dependencies() -> None:
    """Проверить обязательные зависимости."""
    required = {
        "httpx":     "pip install httpx",
        "dotenv":    "pip install python-dotenv",
    }
    optional = {
        "customtkinter": "pip install customtkinter  (рекомендуется для красивого GUI)",
        "cryptography":  "pip install cryptography   (для шифрования секретов)",
        "chromadb":      "pip install chromadb        (для векторного поиска)",
    }

    missing_req = []
    for pkg, cmd in required.items():
        try:
            __import__(pkg if pkg != "dotenv" else "dotenv")
        except ImportError:
            missing_req.append(cmd)

    if missing_req:
        print("=" * 60)
        print("❌ ОТСУТСТВУЮТ ОБЯЗАТЕЛЬНЫЕ ЗАВИСИМОСТИ:")
        for cmd in missing_req:
            print(f"   {cmd}")
        print("=" * 60)
        sys.exit(1)

    for pkg, hint in optional.items():
        try:
            __import__(pkg)
        except ImportError:
            print(f"⚠️  {hint}")


def load_env() -> None:
    """Загрузить переменные окружения. Приоритет: .env.local → .env → os.environ."""
    try:
        from dotenv import load_dotenv
        # .env.local — наивысший приоритет (локальные переопределения, не в git)
        env_local = BASE_DIR / ".env.local"
        if env_local.exists():
            load_dotenv(env_local, override=True)

        env_file = BASE_DIR / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)  # не перекрывает .env.local
        else:
            # Создать пустой .env из примера
            example = BASE_DIR / ".env.example"
            if example.exists():
                import shutil
                shutil.copy(example, env_file)
                print(f"✅ Создан .env из .env.example — заполни ключи!")
    except ImportError:
        pass


# ── Команда --setup ───────────────────────────────────────────────────────────

def run_setup() -> None:
    """Интерактивная первичная настройка."""
    print("\n" + "=" * 60)
    print("  🧠 Personal AI — Первичная настройка")
    print("=" * 60)

    env_path = BASE_DIR / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    def _set_env(key: str, prompt: str, required: bool = False) -> None:
        current = os.getenv(key, "")
        if current:
            print(f"  ✅ {key} — уже задан")
            return
        val = input(f"  {prompt}: ").strip()
        if not val and required:
            print(f"  ⚠️  {key} не задан (можно добавить позже)")
            return
        if val:
            found = False
            for i, line in enumerate(lines):
                if line.startswith(f"{key}="):
                    lines[i] = f"{key}={val}"
                    found = True
                    break
            if not found:
                lines.append(f"{key}={val}")

    print("\n[LLM Ключи — бесплатные провайдеры]")
    print("  (нажми Enter чтобы пропустить)")
    _set_env("GROQ_API_KEY",      "Groq API Key  — бесплатно: console.groq.com/keys")
    _set_env("GOOGLE_API_KEY",    "Gemini API Key — бесплатно: aistudio.google.com/app/apikey")
    _set_env("DEEPSEEK_API_KEY",  "DeepSeek API Key — дёшево: platform.deepseek.com/api_keys")
    _set_env("TOGETHER_API_KEY",  "Together AI Key — $1 бесплатно: api.together.xyz/settings/api-keys")
    _set_env("XAI_API_KEY",       "xAI Grok Key — $25 бесплатно: console.x.ai")
    _set_env("MISTRAL_API_KEY",   "Mistral AI Key — бесплатный план: console.mistral.ai/api-keys")
    print("\n[LLM Ключи — платные провайдеры]")
    _set_env("ANTHROPIC_API_KEY", "Claude API Key (anthropic.com)")
    _set_env("OPENAI_API_KEY",    "OpenAI API Key (platform.openai.com/api-keys)")
    _set_env("PERPLEXITY_API_KEY","Perplexity API Key (perplexity.ai/settings/api)")

    print("\n[Telegram]")
    _set_env("TELEGRAM_BOT_TOKEN", "Telegram Bot Token (@BotFather)")
    _set_env("TELEGRAM_CHAT_ID", "Telegram Chat ID")

    print("\n[Bybit]")
    _set_env("BYBIT_API_KEY", "Bybit API Key (testnet рекомендуется)")
    _set_env("BYBIT_API_SECRET", "Bybit API Secret")

    print("\n[Безопасность]")
    _set_env("MASTER_PASSWORD", "Мастер-пароль для шифрования секретов")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n✅ .env сохранён: {env_path}")
    print("   Запусти: python main.py")


# ── Команда --status ──────────────────────────────────────────────────────────

def print_status() -> None:
    from core.logger import setup_logging
    setup_logging("WARNING")
    from brain.llm_router import LLMRouter
    from memory.memory_store import MemoryStore

    print("\n📊 Статус системы my_personal_ai\n")

    # LLM
    router = LLMRouter.get()
    report = router.status_report()
    print("🧠 LLM Провайдеры:")
    for name, status in report.items():
        emoji = "✅" if status["available"] else "❌"
        print(f"  {emoji} {name:15s} {'(токены исчерпаны)' if status['tokens_exhausted'] else ''}")

    # Память
    mem = MemoryStore.get()
    stats = mem.stats()
    print(f"\n💾 Память:")
    for k, v in stats.items():
        print(f"  {k:20s}: {v}")

    # Проекты
    projects = mem.get_projects()
    if projects:
        print(f"\n📁 Проекты ({len(projects)}):")
        for p in projects:
            print(f"  • {p['name']}: {p.get('description', '')[:50]}")


# ── Главная инициализация ─────────────────────────────────────────────────────

def _p(text: str) -> None:
    """Печать с защитой от ошибок (UnicodeEncodeError, None stdout при pythonw)."""
    try:
        if sys.stdout is not None:
            print(text, flush=True)
    except (UnicodeEncodeError, AttributeError):
        try:
            print(text.encode("ascii", errors="replace").decode("ascii"), flush=True)
        except Exception:
            pass
    except Exception:
        pass


def main(no_gui: bool = False, no_telegram: bool = False,
         daemon: bool = False) -> None:
    _p("=" * 62)
    _p("  [*] Personal AI  --  Avtonomnyy II-Assistent")
    _p("=" * 62)

    # [1] Логирование + Конфиг + Секреты
    from core.logger import setup_logging
    from core.config import cfg
    setup_logging(cfg.log_level)
    _p(f"\n  [1/8] Logging... OK (level={cfg.log_level})")

    # Аудит секретов — предупреждения при отсутствии ключей
    try:
        from core.secrets import secrets
        warnings = secrets.audit()
        for w in warnings:
            log.warning(w)
            _p(f"  ⚠️  {w}")
    except Exception as e:
        log.debug("Secrets audit skipped: %s", e)

    # [2] Память
    from memory.memory_store import MemoryStore
    mem = MemoryStore.get()
    stats = mem.stats()
    _p(f"  [2/8] Memory... OK ({stats['messages']} msg, {stats['knowledge']} knowledge)")

    # [3] Векторные базы
    from vector_stores.manager import VectorStoreManager
    vsm = VectorStoreManager.get()
    _p(f"  [3/8] VectorStore... OK")

    # [4] RAG Engine + знания
    from memory.rag_engine import RAGEngine
    from core.knowledge_seeder import KnowledgeSeeder
    rag = RAGEngine.get()
    rag.set_vector_manager(vsm)
    seeder = KnowledgeSeeder()
    was_seeded = seeder.seed_if_needed()
    seed_msg = " (first run - knowledge loaded!)" if was_seeded else ""
    _p(f"  [4/8] RAGEngine + KnowledgeSeeder... OK{seed_msg}")

    # [5] LLM Router
    from brain.llm_router import LLMRouter
    router = LLMRouter.get()
    report = router.status_report()
    available = [k for k, v in report.items() if v["available"]]
    _p(f"  [5/8] LLMRouter... OK ({', '.join(available) or 'none available'})")

    # [6] Агенты
    _p(f"  [6/8] Agents...")
    from agents.coder_agent import CoderAgent
    from agents.project_creator import ProjectCreatorAgent
    from agents.trading_agent import TradingAgent
    from agents.telegram_agent import TelegramAgent
    from agents.analyzer_agent import AnalyzerAgent

    # ── Новые AI-инструменты ──────────────────────────────────────────────────
    from agents.search_agent import SearchAgent
    from agents.code_runner_agent import CodeRunnerAgent
    from agents.self_training_agent import SelfTrainingAgent
    from agents.news_agent import NewsAgent
    from agents.monitor_agent import MonitorAgent
    from agents.summarizer_agent import SummarizerAgent
    from agents.image_agent import ImageAgent
    from agents.key_manager_agent import KeyManagerAgent
    from agents.math_agent import MathAgent
    from agents.planner_agent import PlannerAgent
    from agents.freelance_agent import FreelanceAgent
    from agents.payment_agent import PaymentAgent
    from agents.browser_agent import BrowserAgent
    from agents.email_agent import EmailAgent
    from agents.code_bridge_agent import CodeBridgeAgent
    from agents.web_automation_agent import WebAutomationAgent
    # ── Новые агенты семьи (2026-05) ─────────────────────────────────────────
    from agents.bonus_hunter_agent import BonusHunterAgent
    from agents.server_agent import ServerAgent
    from agents.claude_dev_agent import ClaudeDevAgent
    from agents.order_agent import OrderAgent
    # 10 new agents 2026-05
    try:
        from agents.crypto_monitor_agent import CryptoMonitorAgent
        from agents.health_monitor_agent import HealthMonitorAgent
        from agents.scheduler_agent import SchedulerAgent
        from agents.auto_responder_agent import AutoResponderAgent
        from agents.knowledge_base_agent import KnowledgeBaseAgent
        from agents.market_scanner_agent import MarketScannerAgent
        from agents.expense_tracker_agent import ExpenseTrackerAgent
        from agents.code_reviewer_agent import CodeReviewerAgent
        from agents.telegram_formatter_agent import TelegramFormatterAgent
        from agents.business_intel_agent import BusinessIntelAgent
        _HAS_NEW10 = True
    except Exception as _ie:
        log.warning("New agents import: %s", _ie); _HAS_NEW10 = False

    # Phase 2: WB + Coffee profit workflow agents
    try:
        from agents.wildberries_agent import WildberriesAgent
        from agents.coffee_sourcing_agent import CoffeeSourcingAgent
        _HAS_WB = True
    except Exception as _we:
        log.warning("WB/Coffee agents import: %s", _we); _HAS_WB = False

    # Phase 3: Revenue stream agents (2026-05-24)
    try:
        from agents.bybit_earn_agent import BybitEarnAgent
        from agents.funding_arb_agent import FundingArbAgent
        from agents.channel_monetization_agent import ChannelMonetizationAgent
        from agents.saas_subscription_agent import SaasSubscriptionAgent
        from agents.crypto_rebalancer_agent import CryptoRebalancerAgent
        from agents.b2b_leads_agent import B2BLeadsAgent
        from agents.smart_trainer_agent import SmartTrainerAgent
        _HAS_REVENUE = True
    except Exception as _re:
        log.warning("Revenue agents import: %s", _re); _HAS_REVENUE = False

    # Phase 4: Elite World-Corporation Agents (2026-05-24)
    try:
        from agents.hyperion_ceo_agent import HyperionCEOAgent
        from agents.autodev_agent import AutoDevAgent
        from agents.quality_guardian_agent import QualityGuardianAgent
        from agents.world_expander_agent import WorldExpanderAgent
        from agents.agent_factory_agent import AgentFactoryAgent
        _HAS_ELITE = True
    except Exception as _ee:
        log.warning("Elite agents import: %s", _ee); _HAS_ELITE = False

    coder          = CoderAgent()
    creator        = ProjectCreatorAgent()
    trading        = TradingAgent()
    tg_agent       = TelegramAgent()
    analyzer       = AnalyzerAgent()
    searcher       = SearchAgent()
    code_runner    = CodeRunnerAgent()
    self_trainer   = SelfTrainingAgent()
    news           = NewsAgent()
    monitor        = MonitorAgent()
    summarizer     = SummarizerAgent()
    image_agent    = ImageAgent()
    key_manager    = KeyManagerAgent()
    math_agent     = MathAgent()
    planner        = PlannerAgent()
    freelance      = FreelanceAgent()
    payment        = PaymentAgent()
    browser = None
    try:
        browser        = BrowserAgent()
        _p("[DBG] browser init OK")
    except Exception as _be:
        log.warning("BrowserAgent init failed: %s", _be)
        browser        = None

    email_ag = None
    try:
        email_ag       = EmailAgent()
        _p("[DBG] email init OK")
    except Exception as _ee:
        log.warning("EmailAgent init failed: %s", _ee)
        email_ag       = None

    code_bridge = None
    try:
        code_bridge    = CodeBridgeAgent()
        _p("[DBG] codebridge OK")
    except Exception as _cbe:
        log.warning("CodeBridgeAgent init failed: %s", _cbe)
        code_bridge    = None

    web_auto = None
    try:
        web_auto = WebAutomationAgent()
        _p("[DBG] webAuto OK")
    except Exception as _wae:
        log.warning("WebAutomationAgent init failed: %s", _wae)
        web_auto = None

    bonus_hunter = None
    try:
        bonus_hunter = BonusHunterAgent()
        _p("[DBG] BonusHunter OK")
    except Exception as _bhe:
        log.warning("BonusHunterAgent init: %s", _bhe)

    server_ag = None
    try:
        server_ag = ServerAgent()
        _p("[DBG] ServerAgent OK")
    except Exception as _sae:
        log.warning("ServerAgent init: %s", _sae)

    claude_dev = None
    try:
        claude_dev = ClaudeDevAgent()
        _p("[DBG] ClaudeDevAgent OK")
    except Exception as _cde:
        log.warning("ClaudeDevAgent init: %s", _cde)

    order_ag = None
    try:
        order_ag = OrderAgent()
        _p("[DBG] OrderAgent OK")
    except Exception as _oae:
        log.warning("OrderAgent init: %s", _oae)

    # Revenue stream agents
    bybit_earn_ag = funding_arb_ag = channel_ag = saas_ag = rebalancer_ag = b2b_ag = smart_trainer_ag = None
    if _HAS_REVENUE if "_HAS_REVENUE" in dir() else False:
        try: bybit_earn_ag = BybitEarnAgent(); _p("[DBG] BybitEarnAgent OK")
        except Exception as _e: log.warning("BybitEarnAgent: %s", _e)
        try: funding_arb_ag = FundingArbAgent(); _p("[DBG] FundingArbAgent OK")
        except Exception as _e: log.warning("FundingArbAgent: %s", _e)
        try: channel_ag = ChannelMonetizationAgent(); _p("[DBG] ChannelAgent OK")
        except Exception as _e: log.warning("ChannelAgent: %s", _e)
        try: saas_ag = SaasSubscriptionAgent(); _p("[DBG] SaasAgent OK")
        except Exception as _e: log.warning("SaasAgent: %s", _e)
        try: rebalancer_ag = CryptoRebalancerAgent(); _p("[DBG] RebalancerAgent OK")
        except Exception as _e: log.warning("RebalancerAgent: %s", _e)
        try: b2b_ag = B2BLeadsAgent(); _p("[DBG] B2BLeadsAgent OK")
        except Exception as _e: log.warning("B2BLeadsAgent: %s", _e)
        try: smart_trainer_ag = SmartTrainerAgent(); _p("[DBG] SmartTrainerAgent OK")
        except Exception as _e: log.warning("SmartTrainerAgent: %s", _e)

    ceo_ag = autodev_ag = quality_ag = world_ag = factory_ag = None
    if "_HAS_ELITE" in dir() and _HAS_ELITE:
        try: ceo_ag = HyperionCEOAgent(); _p("[DBG] CEO OK")
        except Exception as _e: log.warning("CEO: %s", _e)
        try: autodev_ag = AutoDevAgent(); _p("[DBG] AutoDev OK")
        except Exception as _e: log.warning("AutoDev: %s", _e)
        try: quality_ag = QualityGuardianAgent(); _p("[DBG] Quality OK")
        except Exception as _e: log.warning("Quality: %s", _e)
        try: world_ag = WorldExpanderAgent(); _p("[DBG] WorldExpander OK")
        except Exception as _e: log.warning("WorldExpander: %s", _e)
        try: factory_ag = AgentFactoryAgent(); _p("[DBG] Factory OK")
        except Exception as _e: log.warning("Factory: %s", _e)


    # init 10 new agents
    _new10_agents = {}
    if _HAS_NEW10:
        for _n,_cls in [("crypto_monitor",CryptoMonitorAgent),("health_monitor",HealthMonitorAgent),
            ("scheduler",SchedulerAgent),("auto_responder",AutoResponderAgent),
            ("knowledge_base",KnowledgeBaseAgent),("market_scanner",MarketScannerAgent),
            ("expense_tracker",ExpenseTrackerAgent),("code_reviewer",CodeReviewerAgent),
            ("telegram_formatter",TelegramFormatterAgent),("business_intel",BusinessIntelAgent)]:
            try: _new10_agents[_n] = _cls(); _p(f"[DBG] {_n} OK")
            except Exception as _e: log.warning("%s: %s",_n,_e)

    agents = {
        # Оригинальные 5 агентов
        "coder":           coder,
        "project_creator": creator,
        "trading":         trading,
        "telegram":        tg_agent,
        "analyzer":        analyzer,
        # AI-инструменты
        "search":          searcher,
        "code_runner":     code_runner,
        "self_training":   self_trainer,
        "news":            news,
        "monitor":         monitor,
        "summarizer":      summarizer,
        "image":           image_agent,
        # Менеджер ключей
        "key_manager":     key_manager,
        # Математика и финансы
        "math":            math_agent,
        # Планировщик (автономное выполнение)
        "planner":         planner,
        # Фриланс и платежи (Elite AI)
        "freelance":       freelance,
        "payment":         payment,
        **({"browser": browser} if browser else {}),  # Optional - Tor browser agent
        **({"email": email_ag} if email_ag else {}),  # Email agent
        **({"code_bridge": code_bridge} if code_bridge else {}),  # Master Controller
        **({"web_automation": web_auto} if web_auto else {}),  # Web Automation
        # ── Новые агенты (2026-05) ────────────────────────────────────
        **({"bonus_hunter": bonus_hunter} if bonus_hunter else {}),
        **({"server": server_ag} if server_ag else {}),
        **({"claude_dev": claude_dev} if claude_dev else {}),
        **({"order": order_ag} if order_ag else {}),
        **_new10_agents,
        # Revenue agents (2026-05-24)
        **({'bybit_earn': bybit_earn_ag} if bybit_earn_ag else {}),
        **({'funding_arb': funding_arb_ag} if funding_arb_ag else {}),
        **({'channel': channel_ag} if channel_ag else {}),
        **({'saas': saas_ag} if saas_ag else {}),
        **({'rebalancer': rebalancer_ag} if rebalancer_ag else {}),
        **({'b2b_leads': b2b_ag} if b2b_ag else {}),
        **({'smart_trainer': smart_trainer_ag} if smart_trainer_ag else {}),
        # Elite agents — World Corporation Level
        **({'hyperion_ceo': ceo_ag} if ceo_ag else {}),
        **({'autodev': autodev_ag} if autodev_ag else {}),
        **({'quality_guardian': quality_ag} if quality_ag else {}),
        **({'world_expander': world_ag} if world_ag else {}),
        **({'agent_factory': factory_ag} if factory_ag else {}),
    }
    _p(f"       Registered: {len(agents)} agents")

    # [7] Brain Orchestrator
    from brain.orchestrator import BrainOrchestrator
    brain = BrainOrchestrator.get()
    for name, agent in agents.items():
        brain.register_agent(name, agent)

    # Подключить PlannerAgent к агентам и brain callback
    planner.register_agents(agents)
    planner.set_brain_callback(brain.process)

    # [7.0] Tool Registry — единый реестр инструментов
    try:
        from core.tool_registry import ToolRegistry, register_default_tools
        tool_reg = ToolRegistry.get()
        register_default_tools(tool_reg, agents)
        # Подключить к TaskQueue
        try:
            from core.task_queue import TaskQueue
            TaskQueue.get().set_tool_registry(tool_reg)
        except Exception:
            pass
        _p(f"  [7/8] ToolRegistry... OK ({len(tool_reg.list_tools())} tools)")
    except Exception as e:
        _p(f"  [7/8] ToolRegistry... skipped ({e})")

    _p(f"  [7/8] BrainOrchestrator... OK (+ planner + CoT + episodic + tool_registry)")

    # [7.1] Фоновые сервисы агентов
    # MonitorAgent — алерты по ценам/сайтам
    monitor.start_monitoring()

    # Единый callback для Telegram-алертов (используется monitor + watchdog)
    def _send_monitor_alert(msg: str) -> None:
        try:
            tg_agent.send_notification(f"🔔 ALERT: {msg}")
        except Exception:
            pass

    if cfg.telegram_token:
        monitor.add_alert_callback(_send_monitor_alert)

    # SelfTrainingAgent — фоновое обучение каждый час
    self_trainer.start_background_training()

    # KeyManagerAgent — проверка ключей при старте + фоновый мониторинг
    def _startup_key_check():
        """Проверить ключи через 3с после старта (не блокируем GUI)."""
        time.sleep(3)
        try:
            statuses = key_manager.validate_all_keys()
            valid = sum(1 for s in statuses if s.valid)
            no_key = sum(1 for s in statuses if not s.key_value)
            invalid = sum(1 for s in statuses if s.key_value and not s.valid)
            log.info("Key check at startup: %d valid, %d missing, %d invalid",
                     valid, no_key, invalid)
            if invalid:
                invalid_names = [s.provider for s in statuses
                                 if s.key_value and not s.valid]
                log.warning("Invalid API keys: %s", invalid_names)
        except Exception as e:
            log.debug("Startup key check failed: %s", e)

    threading.Thread(target=_startup_key_check, daemon=True).start()
    key_manager.start_key_monitoring(interval_sec=3600)

    # ── Self-Healing Engine ───────────────────────────────────────────────────
    try:
        from monitoring.self_healing import SelfHealingEngine
        healer = SelfHealingEngine.get()
        # Wire Telegram alert callback
        try:
            tg = brain._agents.get("telegram")
            if tg and hasattr(tg, "send_notification"):
                healer.set_alert_callback(tg.send_notification)
        except Exception:
            pass
        healer.start()
        _p("  [7.1c] Self-Healing Engine... OK (5min checks)")
    except Exception as _she:
        _p(f"  [7.1c] Self-Healing Engine... SKIP ({_she})")

    # ── Project Registry ─────────────────────────────────────────────────────
    try:
        from core.project_registry import ProjectRegistry
        ProjectRegistry.get()   # initialize + recover
        _p("  [7.1d] Project Registry... OK")
    except Exception as _pre:
        _p(f"  [7.1d] Project Registry... SKIP ({_pre})")

    # ── Internal REST API (Trading Bot ↔ AI System) ───────────────────────────
    try:
        from core.api_server import start_api_server
        start_api_server(host="127.0.0.1", port=8000)
        _p(f"  [7.1a] Internal API... OK (http://127.0.0.1:8000)")
    except Exception as _api_err:
        _p(f"  [7.1a] Internal API... SKIP ({_api_err})")
    try:
        from dashboard.server import start_dashboard
        start_dashboard(host="0.0.0.0", port=8090)
        _p(f"  [7.1b] Web Dashboard... OK (http://0.0.0.0:8080)")
    except Exception as _dash_err:
        _p(f"  [7.1b] Web Dashboard... SKIP ({_dash_err})")
    _p(f"  [7.1] Background services... OK (monitor + self-training + key-health)")

    # [7.2] SystemWatchdog + Metrics + HealthCheck + Compliance + Validation + Polishing
    from core.watchdog import SystemWatchdog
    from monitoring.metrics import MetricsCollector
    from monitoring.healthcheck import health_checker
    from compliance.compliance_checker import compliance_checker
    from validation.user_perspective import user_validator
    from polishing.polisher import system_polisher

    watchdog = SystemWatchdog.get()
    watchdog.register_agents(agents)
    if cfg.telegram_token:
        watchdog.add_alert_callback(_send_monitor_alert)
    watchdog.start()

    # Регистрация компонентов для health check
    health_checker.register_memory(mem)
    for name, agent in agents.items():
        health_checker.register_agent(name, agent)

    # Настройка user perspective validator
    user_validator.set_brain_callback(brain.process)
    user_validator.set_telegram_agent(tg_agent)

    _metrics = MetricsCollector.get()  # инициализируем для начала сбора
    _p(f"  [7.2] SystemWatchdog + Metrics + HealthCheck + Compliance + Validation + Polishing... OK (self-healing, observability, compliance, user-validation, auto-improvement)")

    # [7.3] FamilyController — unified AI family bus (Personal AI + Telegram + Trading)
    try:
        from family.family_controller import FamilyController
        family = FamilyController.get()
        family.start()

        # Подключить колбэк: торговый агент → family bus
        try:
            from core.trading_bridge import TradingBridge
            def _on_trade_event(payload: dict):
                family._on_trade_executed(payload)
            TradingBridge.get().add_event_callback(_on_trade_event)
        except Exception:
            pass

        _p(f"  [7.3] FamilyController... OK (bus + health-monitor + knowledge-sync)")
    except Exception as e:
        log.warning("FamilyController init failed (non-critical): %s", e)
        _p(f"  [7.3] FamilyController... skipped ({e})")

    # [7.4] AgentHarness + FileTools + GitTools — "Claude Code" внутри системы
    try:
        from core.file_tools import FileTools
        from core.git_tools import GitTools
        from core.agent_harness import get_harness
        from agents.task_executor_agent import TaskExecutorAgent
        FileTools.get()
        GitTools.get()
        get_harness()
        TaskExecutorAgent.get()
        _p(f"  [7.4] AgentHarness + FileTools + GitTools... OK (autonomous task execution ready)")
    except Exception as e:
        log.warning("AgentHarness init failed (non-critical): %s", e)
        _p(f"  [7.4] AgentHarness... skipped ({e})")

    # [8] Telegram агент запуск
    # Пропускаем если --no-telegram (бот уже запущен на сервере)
    _no_tg = no_telegram or "--no-telegram" in sys.argv
    if cfg.telegram_token and not _no_tg:
        tg_agent.set_brain_callback(brain.process)
        tg_agent.set_watchdog(watchdog)   # передаём watchdog для /health
        tg_agent.start()
        _p(f"  [8/8] Telegram bot... OK")
    elif _no_tg:
        _p(f"  [8/8] Telegram bot... skipped (running on server)")
    else:
        _p(f"  [8/8] Telegram bot... skipped (no token)")

    # ── GUI или headless ──────────────────────────────────────────────────────

    if daemon:
        _run_daemon(brain, agents)
    elif no_gui:
        _p("\n  Headless mode. Ctrl+C to exit.")
        _run_headless(brain, agents)
    else:
        _p("\n  Starting GUI...")
        _run_gui(brain, agents)


def _run_gui(brain, agents: dict) -> None:
    """Запустить GUI-версию."""
    from gui.main_window import PersonalAIGUI
    gui = PersonalAIGUI()

    # Подключить мозг
    gui.set_brain(brain)

    # Зарегистрировать агентов в GUI
    for name, agent in agents.items():
        gui.register_agent(name, agent)

    # Callback: результаты мозга → чат GUI
    def _on_brain_result(response, source):
        if source != "gui":  # Избегаем двойного вывода для GUI-запросов
            gui.post({"action": "chat", "tag": "bot", "text": response.text})

    brain.add_response_callback(_on_brain_result)

    _p("  Ready! Opening window...\n")
    gui.run()


def _run_headless(brain, agents: dict) -> None:
    """Запустить в headless режиме (без GUI)."""
    try:
        import readline  # улучшенный ввод (Linux/Mac)
    except ImportError:
        pass  # Windows — работает без readline

    _p("\nInput query (or 'exit' to quit):\n")

    while True:
        try:
            text = input("Ты: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if text.lower() in ("exit", "quit", "q"):
            break
        if not text:
            continue

        from brain.orchestrator import OrchestratorRequest
        req = OrchestratorRequest(text=text, source="cli", session_id="cli")
        resp = brain.process(req)
        _p(f"\nAI: {resp.text}\n")

    _p("\n  Shutdown.")


def _run_daemon(brain, agents: dict) -> None:
    """
    24/7 Daemon mode — запустить в фоне без GUI и без интерактивного ввода.

    Режим для серверов и автономной работы:
    - пишет PID в data/daemon.pid
    - запускает ежедневный автобэкап (3:00 по местному времени)
    - логирует heartbeat каждые 5 минут
    - завершается по SIGTERM / SIGINT
    - поддерживает graceful shutdown
    """
    import signal
    import time

    # ── Записать PID ──────────────────────────────────────────────────────────
    pid_file = BASE_DIR / "data" / "daemon.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    _p(f"\n  [DAEMON] PID {os.getpid()} → {pid_file}")
    _p("  [DAEMON] 24/7 mode active. SIGINT/SIGTERM to stop.\n")

    _stop_event = threading.Event()

    def _handle_signal(sig, frame):
        sig_name = signal.Signals(sig).name if hasattr(signal, 'Signals') else str(sig)
        _p(f"\n  [DAEMON] Signal {sig_name} ({sig}) — initiating graceful shutdown...")
        log.warning("[DAEMON] Received signal %s (%d) — graceful shutdown", sig_name, sig)
        _stop_event.set()

    # Handle all common termination signals
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGHUP,  _handle_signal)  # terminal hangup
    signal.signal(signal.SIGUSR1, _handle_signal)  # user-defined signal 1
    signal.signal(signal.SIGUSR2, _handle_signal)  # user-defined signal 2

    # ── Ежедневный автобэкап (03:00) ──────────────────────────────────────────
    def _backup_loop():
        import datetime
        while not _stop_event.is_set():
            now = datetime.datetime.now()
            target = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target + datetime.timedelta(days=1)
            wait_sec = (target - now).total_seconds()
            _stop_event.wait(timeout=min(wait_sec, 3600))  # проверяем каждый час
            if _stop_event.is_set():
                break
            now2 = datetime.datetime.now()
            if now2.hour == 3 and now2.minute < 5:
                try:
                    from scripts.backup import create_backup
                    arch = create_backup()
                    log.info("[DAEMON] Auto-backup created: %s (%.1f MB)",
                             arch.name, arch.stat().st_size / 1_048_576)
                    _p(f"  [DAEMON] Backup: {arch.name}")
                except Exception as e:
                    log.error("[DAEMON] Auto-backup failed: %s", e)

    threading.Thread(target=_backup_loop, daemon=True, name="daemon-backup").start()

    # ── Heartbeat каждые 5 минут ──────────────────────────────────────────────
    def _heartbeat_loop():
        while not _stop_event.is_set():
            _stop_event.wait(timeout=300)
            if not _stop_event.is_set():
                try:
                    from brain.llm_router import LLMRouter
                    report = LLMRouter.get().status_report()
                    avail = [k for k, v in report.items() if v["available"]]
                    log.info("[DAEMON] heartbeat | agents=%d | llm=%s",
                             len(agents), ",".join(avail) or "none")
                except Exception:
                    log.info("[DAEMON] heartbeat | agents=%d", len(agents))

    threading.Thread(target=_heartbeat_loop, daemon=True, name="daemon-heartbeat").start()

    _p("  [DAEMON] All services running. Waiting for stop signal...\n")

    # ── Главный цикл ───────────────────────────────────────────────────────────
    _stop_event.wait()  # ждёт SIGTERM или SIGINT

    _p("  [DAEMON] Shutting down gracefully...")
    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass
    _p("  [DAEMON] Stopped.")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Personal AI — Автономный ИИ-Ассистент"
    )
    parser.add_argument("--no-gui", action="store_true",
                        help="Запустить без GUI (headless — интерактивный REPL)")
    parser.add_argument("--daemon", action="store_true",
                        help="24/7 daemon: фоновые агенты + Telegram + автобэкап, без ввода")
    parser.add_argument("--no-telegram", action="store_true",
                        help="Не запускать Telegram бот (уже запущен на сервере)")
    parser.add_argument("--setup", action="store_true",
                        help="Первичная настройка")
    parser.add_argument("--status", action="store_true",
                        help="Показать статус и выйти")
    args = parser.parse_args()

    load_env()
    check_dependencies()

    if args.setup:
        run_setup()
    elif args.status:
        print_status()
    else:
        # --daemon автоматически подразумевает --no-gui
        main(
            no_gui=args.no_gui or args.daemon,
            no_telegram=args.no_telegram,
            daemon=args.daemon,
        )