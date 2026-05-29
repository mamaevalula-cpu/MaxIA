# -*- coding: utf-8 -*-
"""
run_headless.py — Запуск Personal AI без GUI (для сервера / VPS)

Запускает:
  • Brain Orchestrator
  • Все агенты (TelegramAgent, TradingAgent, и т.д.)
  • Мониторинг системы

Без GUI — только Telegram-бот как интерфейс.

Использование:
  python run_headless.py
  python run_headless.py --debug
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
import threading
from pathlib import Path

# Настройка UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

# ── Аргументы ─────────────────────────────────────────────────────────────────

parser = argparse.ArgumentParser(description="Personal AI Headless Server")
parser.add_argument("--debug", action="store_true", help="Debug logging")
parser.add_argument("--no-trading", action="store_true", help="Disable trading agent")
parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram bot")
args, _ = parser.parse_known_args()

# ── Логирование ───────────────────────────────────────────────────────────────

log_level = logging.DEBUG if args.debug else logging.INFO
log_dir   = BASE_DIR / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / "headless.log", encoding="utf-8"),
    ]
)
log = logging.getLogger("headless")

# ── Конфиг ────────────────────────────────────────────────────────────────────

from core.config import cfg
cfg.ensure_dirs()

log.info("=" * 60)
log.info("  Personal AI — Headless Server Mode")
log.info("=" * 60)
log.info("Base dir : %s", BASE_DIR)
log.info("Log level: %s", "DEBUG" if args.debug else "INFO")

# ── Загрузка компонентов ──────────────────────────────────────────────────────

_agents    = {}
_brain     = None
_tg_agent  = None
_shutdown  = threading.Event()


def _p(msg: str) -> None:
    log.info(msg)
    print(msg, flush=True)


def _init_brain():
    global _brain
    _p("[1/6] Инициализация Brain Orchestrator...")
    from brain.orchestrator import BrainOrchestrator
    _brain = BrainOrchestrator.get()
    _p(f"  Brain OK: {len(_brain._agents)} агентов")
    return _brain


def _init_agents():
    global _agents
    _p("[2/6] Инициализация агентов...")

    agent_classes = [
        ("coder",           "agents.coder_agent",        "CoderAgent"),
        ("analyzer",        "agents.analyzer_agent",     "AnalyzerAgent"),
        ("search",          "agents.search_agent",       "SearchAgent"),
        ("math",            "agents.math_agent",         "MathAgent"),
        ("news",            "agents.news_agent",         "NewsAgent"),
        ("summarizer",      "agents.summarizer_agent",   "SummarizerAgent"),
        ("planner",         "agents.planner_agent",      "PlannerAgent"),
        ("monitor",         "agents.monitor_agent",      "MonitorAgent"),
        ("key_manager",     "agents.key_manager_agent",  "KeyManagerAgent"),
    ]

    if not args.no_trading:
        agent_classes.append(("trading", "agents.trading_agent", "TradingAgent"))

    for name, module_path, class_name in agent_classes:
        try:
            mod = __import__(module_path, fromlist=[class_name])
            cls = getattr(mod, class_name)
            agent = cls()
            _agents[name] = agent
            _brain.register_agent(name, agent)
            _p(f"  {name}: OK")
        except Exception as e:
            _p(f"  {name}: SKIP ({e})")

    _p(f"  Загружено агентов: {len(_agents)}")


def _init_evolution():
    _p("[3/6] NEXT-STAGE компоненты...")
    try:
        from brain.chain_of_thought import ChainOfThoughtEngine
        cot = ChainOfThoughtEngine.get()
        _p(f"  CoT Engine: OK")
    except Exception as e:
        _p(f"  CoT: SKIP ({e})")

    try:
        from memory.episodic_memory import EpisodicMemory
        EpisodicMemory.get()
        _p(f"  Episodic Memory: OK")
    except Exception as e:
        _p(f"  EpisodicMemory: SKIP ({e})")

    try:
        from core.tool_registry import ToolRegistry, register_default_tools
        reg = ToolRegistry.get()
        register_default_tools(reg, _agents)
        _p(f"  ToolRegistry: OK ({len(reg.list_tools())} tools)")
    except Exception as e:
        _p(f"  ToolRegistry: SKIP ({e})")

    try:
        from core.task_queue import TaskQueue
        from core.tool_registry import ToolRegistry
        tq = TaskQueue.get()
        tq.set_tool_registry(ToolRegistry.get())
        tq.set_brain_callback(_brain.process)
        tq.start()
        _p(f"  TaskQueue: OK (workers started)")
    except Exception as e:
        _p(f"  TaskQueue: SKIP ({e})")


def _init_telegram():
    global _tg_agent
    if args.no_telegram:
        _p("[4/6] Telegram: отключён (--no-telegram)")
        return

    _p("[4/6] Telegram Bot...")
    if not cfg.telegram_token:
        _p("  SKIP: TELEGRAM_BOT_TOKEN не задан в .env")
        return

    try:
        from agents.telegram_agent import TelegramAgent
        _tg_agent = TelegramAgent()
        _tg_agent.set_brain_callback(_brain.process)
        _agents["telegram"] = _tg_agent
        _brain.register_agent("telegram", _tg_agent)
        _tg_agent.start()
        _p(f"  Telegram bot @{cfg.telegram_token.split(':')[0]}: запущен")
    except Exception as e:
        _p(f"  Telegram: FAIL ({e})")
        import traceback
        traceback.print_exc()


def _init_trading_bridge():
    _p("[5/6] Trading Bridge...")
    try:
        from core.trading_bridge import TradingBridge
        bridge = TradingBridge.get()
        status = bridge.get_status()
        _p(f"  Bridge: {'online' if status.online else 'bot offline (OK)'}")
    except Exception as e:
        _p(f"  Bridge: SKIP ({e})")


def _start_watchdog():
    _p("[6/6] Watchdog...")

    def _watchdog_loop():
        while not _shutdown.is_set():
            try:
                # Проверить telegram агент
                if _tg_agent and hasattr(_tg_agent, "_status"):
                    from agents.base_agent import AgentStatus
                    if _tg_agent._status == AgentStatus.ERROR:
                        log.warning("TelegramAgent в ERROR — перезапуск...")
                        _tg_agent.stop()
                        time.sleep(5)
                        _tg_agent.start()

                # Записать heartbeat
                hb_file = BASE_DIR / "data" / "heartbeat.txt"
                hb_file.write_text(
                    f"{time.strftime('%Y-%m-%d %H:%M:%S')} running\n"
                    f"agents={len(_agents)}\n"
                    f"telegram={'ok' if _tg_agent else 'disabled'}\n"
                )
            except Exception as e:
                log.debug("Watchdog error: %s", e)
            _shutdown.wait(60)  # проверка каждые 60 сек

    t = threading.Thread(target=_watchdog_loop, name="watchdog", daemon=True)
    t.start()
    _p("  Watchdog: OK (60s interval)")


# ── Graceful shutdown ─────────────────────────────────────────────────────────

def _on_signal(signum, frame):
    log.info("Signal %s received — shutting down gracefully...", signum)
    _shutdown.set()


signal.signal(signal.SIGINT,  _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _p("")
    _p("Запуск Personal AI Headless...")
    _p("")

    _init_brain()
    _init_agents()
    _init_evolution()
    _init_telegram()
    _init_trading_bridge()
    _start_watchdog()

    _p("")
    _p("=" * 60)
    _p("  Personal AI запущен!")
    _p(f"  Агентов: {len(_agents)}")
    _p(f"  Telegram: {'активен' if _tg_agent else 'отключён'}")
    _p(f"  Управление через: /status /help /trading")
    _p("  Для остановки: Ctrl+C или systemctl stop ai-assistant")
    _p("=" * 60)
    _p("")

    # Основной цикл
    try:
        while not _shutdown.is_set():
            _shutdown.wait(5)
    except KeyboardInterrupt:
        pass

    # Завершение
    _p("Останавливаю агентов...")
    if _tg_agent:
        try:
            _tg_agent.stop()
            _p("  Telegram: остановлен")
        except Exception:
            pass

    try:
        from core.task_queue import TaskQueue
        TaskQueue.get().stop()
        _p("  TaskQueue: остановлена")
    except Exception:
        pass

    _p("Personal AI остановлен. До свидания!")


if __name__ == "__main__":
    main()
