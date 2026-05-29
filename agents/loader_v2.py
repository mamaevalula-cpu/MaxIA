#!/usr/bin/env python3
"""
agents/loader_v2.py — Non-conflicting agent loader.

Loads all 40+ file-based agents + 70 pack agents.
Conflict-resolution: first agent that can_handle() wins (by priority).
"""
import importlib
import logging
from typing import Any, Dict, List, Optional, Tuple, Type

try:
    from core.base_agent import BaseAgent
except ImportError:
    from agents.base_agent import BaseAgent
try:
    from core.orchestrator import AgentOrchestrator
except ImportError:
    AgentOrchestrator = None

log = logging.getLogger("loader_v2")

# Module path, class name, registration name
FILE_AGENTS: List[Tuple[str, str, str]] = [
    ("agents.master_control_agent", "MasterControlAgent", "master_control"),
    ("agents.coder_agent",          "CoderAgent",          "coder"),
    ("agents.project_creator",      "ProjectCreatorAgent", "project_creator"),
    ("agents.trading_agent",        "TradingAgent",        "trading"),
    ("agents.telegram_agent",       "TelegramAgent",       "telegram"),
    ("agents.analyzer_agent",       "AnalyzerAgent",       "analyzer"),
    ("agents.search_agent",         "SearchAgent",         "search"),
    ("agents.code_runner_agent",    "CodeRunnerAgent",     "code_runner"),
    ("agents.self_training_agent",  "SelfTrainingAgent",   "self_training"),
    ("agents.news_agent",           "NewsAgent",           "news"),
    ("agents.monitor_agent",        "MonitorAgent",        "monitor"),
    ("agents.summarizer_agent",     "SummarizerAgent",     "summarizer"),
    ("agents.image_agent",          "ImageAgent",          "image"),
    ("agents.key_manager_agent",    "KeyManagerAgent",     "key_manager"),
    ("agents.math_agent",           "MathAgent",           "math"),
    ("agents.planner_agent",        "PlannerAgent",        "planner"),
    ("agents.freelance_agent",      "FreelanceAgent",      "freelance"),
    ("agents.payment_agent",        "PaymentAgent",        "payment"),
    ("agents.browser_agent",        "BrowserAgent",        "browser"),
    ("agents.email_agent",          "EmailAgent",          "email"),
    ("agents.code_bridge_agent",    "CodeBridgeAgent",     "code_bridge"),
    ("agents.web_automation_agent", "WebAutomationAgent",  "web_automation"),
    ("agents.bonus_hunter_agent",   "BonusHunterAgent",    "bonus_hunter"),
    ("agents.server_agent",         "ServerAgent",         "server"),
    ("agents.claude_dev_agent",     "ClaudeDevAgent",      "claude_dev"),
    ("agents.order_agent",          "OrderAgent",          "order"),
    ("agents.crypto_monitor_agent", "CryptoMonitorAgent",  "crypto_monitor"),
    ("agents.health_monitor_agent", "HealthMonitorAgent",  "health_monitor"),
    ("agents.scheduler_agent",      "SchedulerAgent",      "scheduler"),
    ("agents.auto_responder_agent", "AutoResponderAgent",  "auto_responder"),
    ("agents.market_scanner_agent", "MarketScannerAgent",  "market_scanner"),
    ("agents.expense_tracker_agent","ExpenseTrackerAgent", "expense_tracker"),
    ("agents.code_reviewer_agent",  "CodeReviewerAgent",   "code_reviewer"),
    ("agents.telegram_formatter_agent","TelegramFormatterAgent","telegram_formatter"),
    ("agents.business_intel_agent", "BusinessIntelAgent",  "business_intel"),
]

def load_single_agent(module_path: str, class_name: str, 
                     orchestrator: AgentOrchestrator, 
                     **kwargs: Any) -> Optional[BaseAgent]:
    """
    Load and register a single agent from its module path.

    Args:
        module_path: Dot-separated Python module path (e.g. "agents.coder_agent").
        class_name: Name of the agent class to instantiate.
        orchestrator: The orchestrator instance to register with.
        **kwargs: Additional keyword arguments passed to the agent constructor.

    Returns:
        The instantiated agent, or None if loading failed.
    """
    try:
        module = importlib.import_module(module_path)
        agent_class: Type[BaseAgent] = getattr(module, class_name)
        agent = agent_class(**kwargs)
        orchestrator.register_agent(agent.name, agent)
        log.info("Loaded agent %s (%s)", agent.name, module_path)
        return agent
    except (ImportError, AttributeError) as exc:
        log.warning("Failed to load agent %s from %s: %s", class_name, module_path, exc)
        return None

def load_agents(orchestrator: AgentOrchestrator, 
                agent_list: Optional[List[Tuple[str, str, str]]] = None) -> Dict[str, BaseAgent]:
    """
    Load all file-based agents into the orchestrator.

    Iterates over FILE_AGENTS (or a custom list) and loads each agent
    using importlib. Agents that fail to import are skipped with a warning.

    Args:
        orchestrator: The orchestrator instance to populate.
        agent_list: Optional override of the default agent list.
                        Defaults to FILE_AGENTS.

    Returns:
        Dictionary mapping registration names to instantiated agents.
    """
    agents: Dict[str, BaseAgent] = {}
    if agent_list is None:
        agent_list = FILE_AGENTS

    for module_path, class_name, reg_name in agent_list:
        agent = load_single_agent(module_path, class_name, orchestrator)
        if agent is not None:
            agents[reg_name] = agent

    log.info("Loaded %d/%d file agents", len(agents), len(agent_list))
    return agents

__all__ = ["FILE_AGENTS", "load_single_agent", "load_agents"]
