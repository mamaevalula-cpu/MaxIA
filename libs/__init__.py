# -*- coding: utf-8 -*-
"""
libs/ — типовые переиспользуемые библиотеки для работы с LLM, памятью и агентами.

Организация:
  llm_client.py       — универсальный клиент для всех LLM (OpenAI, Groq, DeepSeek, xAI)
  memory_manager.py   — работа с долгосрочной памятью (vectordb, episodic, working)
  agent_utils.py      — утилиты для агентов (retry, logging, state management)
  web_scraper.py      — парсинг и скрейпинг веб-сайтов
  search_engine.py    — поиск в интернете (DuckDuckGo, Google)
  data_processor.py   — обработка структурированных данных (CSV, JSON, Excel)
  message_queue.py    — очередь задач и обработка потоков
  cache_layer.py      — кэширование результатов LLM и поисков
  config_manager.py   — управление конфигурацией из .env
  health_monitor.py   — мониторинг здоровья системы
"""

__all__ = [
    'llm_client',
    'memory_manager',
    'agent_utils',
    'web_scraper',
    'search_engine',
    'data_processor',
    'message_queue',
    'cache_layer',
    'config_manager',
    'health_monitor',
]
