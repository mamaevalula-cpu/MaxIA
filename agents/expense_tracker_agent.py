from __future__ import annotations
import logging
import sqlite3
import time
from typing import Optional

log = logging.getLogger("agents.expense_tracker")

DB = "/root/my_personal_ai/data/expenses.db"


class ExpenseTrackerAgent:
    name = "expense_tracker"

    def __init__(self) -> None:
        """Инициализация таблицы expenses и таблиц для трекинга ежедневной выручки и онбординга агентов."""
        conn = sqlite3.connect(DB)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exp (
                provider TEXT,
                tokens INT,
                cost REAL,
                ts REAL,
                model TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revenue_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                revenue REAL NOT NULL DEFAULT 0,
                target REAL NOT NULL DEFAULT 1000.0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_onboarding_daily (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                agents_onboarded INT NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()
        log.info("ExpenseTrackerAgent initialized with revenue and agent onboarding tracking")

    def record(self, provider: str, tokens: int, cost: float, model: str = "") -> None:
        """
        Запись затрат.

        Args:
            provider: Провайдер (например, "openai").
            tokens: Количество использованных токенов.
            cost: Стоимость в долларах.
            model: Название модели (опционально).
        """
        conn = sqlite3.connect(DB)
        conn.execute(
            "INSERT INTO exp (provider, tokens, cost, ts, model) VALUES (?,?,?,?,?)",
            (provider, tokens, cost, time.time(), model),
        )
        conn.commit()
        conn.close()

    def record_revenue(self, revenue: float, target: float = 1000.0) -> None:
        """
        Запись ежедневной выручки и цели.

        Args:
            revenue: Сумма выручки за сегодня.
            target: Цель выручки на день (по умолчанию 1000 USD).
        """
        conn = sqlite3.connect(DB)
        conn.execute(
            "INSERT INTO revenue_daily (ts, revenue, target) VALUES (?,?,?)",
            (time.time(), revenue, target),
        )
        conn.commit()
        conn.close()
        log.info(f"Recorded revenue: ${revenue:.2f}, target: ${target:.2f}")

    def record_onboarding(self, agents_onboarded: int) -> None:
        """
        Запись количества агентов, онбордированных за день.

        Args:
            agents_onboarded: Количество агентов, добавленных сегодня.
        """
        conn = sqlite3.connect(DB)
        conn.execute(
            "INSERT INTO agent_onboarding_daily (ts, agents_onboarded) VALUES (?,?)",
            (time.time(), agents_onboarded),
        )
        conn.commit()
        conn.close()
        log.info(f"Recorded agents onboarded: {agents_onboarded}")

    def summary(self) -> str:
        """
        Возвращает сводку по затратам за последние 24 часа, статус достижения цели по выручке
        и метрики онбординга агентов.

        Returns:
            Строка с информацией о дневных затратах, выручке и онбординге.
        """
        conn = sqlite3.connect(DB)
        # Затраты за последние 24 часа
        rows = conn.execute(
            """
            SELECT provider, SUM(tokens), SUM(cost)
            FROM exp
            WHERE ts > ?
            GROUP BY provider
            ORDER BY cost DESC
            """,
            (time.time() - 86400,),
        ).fetchall()

        # Последняя запись выручки
        revenue_row = conn.execute(
            """
            SELECT revenue, target
            FROM revenue_daily
            ORDER BY ts DESC
            LIMIT 1
            """
        ).fetchone()

        # Суммарное количество агентов за последние 24 часа
        onboarding_row = conn.execute(
            """
            SELECT SUM(agents_onboarded)
            FROM agent_onboarding_daily
            WHERE ts > ?
            """,
            (time.time() - 86400,),
        ).fetchone()
        conn.close()

        # Формирование отчета
        lines = []
        lines.append("=== Daily Summary (last 24h) ===")
        lines.append("Costs by provider:")
        total_cost = 0.0
        for provider, tokens, cost in rows:
            lines.append(f"  {provider}: {tokens} tokens, ${cost:.4f}")
            total_cost += cost
        lines.append(f"Total cost: ${total_cost:.4f}")

        if revenue_row:
            revenue, target = revenue_row
            progress = (revenue / target * 100) if target > 0 else 0.0
            lines.append(f"Revenue: ${revenue:.2f} / ${target:.2f} ({progress:.1f}%)")
            if revenue >= target:
                lines.append("Goal status: ACHIEVED")
            else:
                lines.append("Goal status: NOT ACHIEVED")
        else:
            lines.append("Revenue: No data recorded")

        if onboarding_row and onboarding_row[0] is not None:
            agents_count = onboarding_row[0]
            lines.append(f"Agents onboarded: {agents_count}")
            if agents_count >= 10000:
                lines.append("Agent target: ACHIEVED")
            else:
                progress_agents = (agents_count / 10000) * 100
                lines.append(f"Agent target: {agents_count}/10000 ({progress_agents:.1f}%)")
        else:
            lines.append("Agents onboarded: No data")

        return "\n".join(lines)

    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        """Orchestrator bridge — auto-added."""
        for m in ["run","execute","work","handle","daily_cycle","check","scan","analyze","report","daily_report"]:
            fn = getattr(self, m, None)
            if fn and callable(fn):
                try:
                    r = fn()
                    return str(r)[:400] if r else self.__class__.__name__ + ": ok"
                except Exception as e:
                    return self.__class__.__name__ + f" error: {e}"
        return self.__class__.__name__ + ": ready"
