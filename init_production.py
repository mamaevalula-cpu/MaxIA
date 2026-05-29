#!/usr/bin/env python3
"""
init_production.py — Инициализация для production environment.

Выполняет:
- Проверку конфигурации
- Инициализацию базы данных
- Загрузку базовых знаний
- Health check
- User perspective validation
- System polishing
"""

import asyncio
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)


async def main():
    """Главная функция инициализации."""
    log.info("=" * 60)
    log.info("Production Initialization")
    log.info("=" * 60)

    try:
        # 1. Проверка конфигурации
        log.info("\n[1/5] Checking configuration...")
        from core.config import cfg
        from core.logger import setup_logging

        setup_logging(cfg.log_level)
        log.info("✓ Configuration loaded")

        # 2. Инициализация компонентов
        log.info("\n[2/5] Initializing components...")

        from memory.memory_store import MemoryStore
        mem = MemoryStore.get()
        log.info("✓ Memory store initialized")

        from vector_stores.manager import VectorStoreManager
        vsm = VectorStoreManager.get()
        log.info("✓ Vector store initialized")

        from memory.rag_engine import RAGEngine
        rag = RAGEngine.get()
        rag.set_vector_manager(vsm)
        log.info("✓ RAG engine initialized")

        # 3. Загрузка базовых знаний
        log.info("\n[3/5] Loading base knowledge...")
        from core.knowledge_seeder import KnowledgeSeeder

        seeder = KnowledgeSeeder()
        was_seeded = await asyncio.to_thread(seeder.seed_if_needed)
        if was_seeded:
            log.info("✓ Base knowledge loaded")
        else:
            log.info("✓ Knowledge already loaded")

        # 4. Health check
        log.info("\n[4/5] Running health checks...")
        from monitoring.healthcheck import health_checker

        results = await health_checker.check_all()
        summary = health_checker.get_summary(results)

        log.info("  Total components: %d", summary["total_components"])
        log.info("  ✓ Healthy: %d", summary["healthy"])
        log.info("  ⚠ Degraded: %d", summary["degraded"])
        log.info("  ✗ Unhealthy: %d", summary["unhealthy"])

        if summary["unhealthy"] > 0:
            log.error("Critical issues detected!")
            for result in results:
                if result.is_critical:
                    log.error("  - %s: %s", result.component, result.message)
            return 1

        # 5. System polishing (опционально)
        log.info("\n[5/5] Running system polishing...")
        from polishing.polisher import system_polisher

        polish_result = await system_polisher.run_polishing_loop()
        log.info("  Issues found: %d", len(polish_result.issues_found))
        log.info("  Issues fixed: %d", polish_result.issues_fixed)

        if polish_result.issues_found:
            for issue in polish_result.issues_found[:5]:  # Первые 5
                log.warning("  - [%s] %s: %s", issue.severity, issue.component, issue.description)

        log.info("\n" + "=" * 60)
        log.info("✅ Production initialization completed successfully!")
        log.info("=" * 60)
        return 0

    except Exception as e:
        log.error("Initialization failed: %s", e, exc_info=True)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)