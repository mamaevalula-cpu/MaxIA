# -*- coding: utf-8 -*-
"""
agents/freelance_agent.py — Автономный агент поиска работы и заработка.

Возможности:
  • Поиск вакансий на фриланс-платформах (Upwork, Freelancer, Fiverr, Remote.co)
  • Генерация персонализированных proposal через LLM
  • Оценка стоимости и сроков проекта
  • Трекинг заявок и статусов
  • Управление портфолио
  • Статистика заработка

Запуск:
  agent = FreelanceAgent()
  jobs = agent.search_jobs(["python", "fastapi", "stripe"])
  proposal = agent.generate_proposal(jobs[0])
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMProvider, LLMRequest

log = logging.getLogger("agents.freelance")

DB_PATH = Path(__file__).parent.parent / "data" / "freelance.db"


# ── Датаклассы ─────────────────────────────────────────────────────────────────

@dataclass
class FreelanceJob:
    """Вакансия с фриланс-платформы."""
    id: str
    platform: str           # upwork | freelancer | fiverr | remote | manual
    title: str
    description: str
    budget_min: float = 0.0
    budget_max: float = 0.0
    budget_type: str = "fixed"   # fixed | hourly
    skills: List[str] = field(default_factory=list)
    client_rating: float = 0.0
    client_reviews: int = 0
    posted_at: str = ""
    url: str = ""
    match_score: float = 0.0    # 0-1 насколько подходит


@dataclass
class Proposal:
    """Поданная заявка."""
    id: str
    job_id: str
    job_title: str
    platform: str
    text: str
    bid_amount: float
    bid_type: str       # fixed | hourly
    estimated_hours: float
    status: str = "draft"   # draft | submitted | viewed | shortlisted | rejected | won
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    notes: str = ""


@dataclass
class PortfolioItem:
    """Элемент портфолио."""
    id: str
    title: str
    description: str
    tech_stack: List[str] = field(default_factory=list)
    demo_url: str = ""
    github_url: str = ""
    client: str = ""
    earned: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ProjectEstimate:
    """Оценка проекта."""
    description: str
    hours_min: float
    hours_max: float
    rate_usd: float
    price_min: float
    price_max: float
    breakdown: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    delivery_days: int = 7


# ── База данных ────────────────────────────────────────────────────────────────

class FreelanceDB:
    """SQLite хранилище для фриланс-данных."""

    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                platform TEXT,
                title TEXT,
                description TEXT,
                budget_min REAL,
                budget_max REAL,
                budget_type TEXT,
                skills TEXT,
                client_rating REAL,
                posted_at TEXT,
                url TEXT,
                match_score REAL,
                fetched_at REAL
            );
            CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY,
                job_id TEXT,
                job_title TEXT,
                platform TEXT,
                text TEXT,
                bid_amount REAL,
                bid_type TEXT,
                estimated_hours REAL,
                status TEXT,
                created_at TEXT,
                notes TEXT
            );
            CREATE TABLE IF NOT EXISTS portfolio (
                id TEXT PRIMARY KEY,
                title TEXT,
                description TEXT,
                tech_stack TEXT,
                demo_url TEXT,
                github_url TEXT,
                client TEXT,
                earned REAL,
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL,
                currency TEXT,
                platform TEXT,
                description TEXT,
                date TEXT
            );
            """)

    def save_job(self, job: FreelanceJob) -> None:
        with self._conn() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO jobs
            (id,platform,title,description,budget_min,budget_max,budget_type,
             skills,client_rating,posted_at,url,match_score,fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (job.id, job.platform, job.title, job.description,
                  job.budget_min, job.budget_max, job.budget_type,
                  json.dumps(job.skills), job.client_rating,
                  job.posted_at, job.url, job.match_score, time.time()))

    def get_jobs(self, limit: int = 20) -> List[FreelanceJob]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY match_score DESC, fetched_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        result = []
        for r in rows:
            j = FreelanceJob(
                id=r["id"], platform=r["platform"], title=r["title"],
                description=r["description"], budget_min=r["budget_min"],
                budget_max=r["budget_max"], budget_type=r["budget_type"],
                skills=json.loads(r["skills"] or "[]"),
                client_rating=r["client_rating"], posted_at=r["posted_at"],
                url=r["url"], match_score=r["match_score"],
            )
            result.append(j)
        return result

    def save_proposal(self, p: Proposal) -> None:
        with self._conn() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO proposals
            (id,job_id,job_title,platform,text,bid_amount,bid_type,
             estimated_hours,status,created_at,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (p.id, p.job_id, p.job_title, p.platform, p.text,
                  p.bid_amount, p.bid_type, p.estimated_hours,
                  p.status, p.created_at, p.notes))

    def update_proposal_status(self, proposal_id: str, status: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE proposals SET status=? WHERE id=?",
                         (status, proposal_id))

    def get_proposals(self, status: Optional[str] = None) -> List[Proposal]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM proposals WHERE status=? ORDER BY created_at DESC",
                    (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM proposals ORDER BY created_at DESC"
                ).fetchall()
        return [Proposal(
            id=r["id"], job_id=r["job_id"], job_title=r["job_title"],
            platform=r["platform"], text=r["text"], bid_amount=r["bid_amount"],
            bid_type=r["bid_type"], estimated_hours=r["estimated_hours"],
            status=r["status"], created_at=r["created_at"], notes=r["notes"],
        ) for r in rows]

    def add_portfolio_item(self, item: PortfolioItem) -> None:
        with self._conn() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO portfolio
            (id,title,description,tech_stack,demo_url,github_url,client,earned,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (item.id, item.title, item.description,
                  json.dumps(item.tech_stack), item.demo_url, item.github_url,
                  item.client, item.earned, item.created_at))

    def get_portfolio(self) -> List[PortfolioItem]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM portfolio ORDER BY created_at DESC").fetchall()
        return [PortfolioItem(
            id=r["id"], title=r["title"], description=r["description"],
            tech_stack=json.loads(r["tech_stack"] or "[]"),
            demo_url=r["demo_url"], github_url=r["github_url"],
            client=r["client"], earned=r["earned"], created_at=r["created_at"],
        ) for r in rows]

    def record_earning(self, amount: float, currency: str, platform: str,
                       description: str) -> None:
        with self._conn() as conn:
            conn.execute("""
            INSERT INTO earnings (amount,currency,platform,description,date)
            VALUES (?,?,?,?,?)
            """, (amount, currency, platform, description,
                  datetime.now().strftime("%Y-%m-%d")))

    def earnings_summary(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM earnings WHERE currency='USD'"
            ).fetchone()[0]
            by_platform = conn.execute(
                "SELECT platform, SUM(amount) as total FROM earnings "
                "WHERE currency='USD' GROUP BY platform ORDER BY total DESC"
            ).fetchall()
            monthly = conn.execute(
                "SELECT substr(date,1,7) as month, SUM(amount) as total "
                "FROM earnings WHERE currency='USD' "
                "GROUP BY month ORDER BY month DESC LIMIT 12"
            ).fetchall()
        return {
            "total_usd": round(total, 2),
            "by_platform": {r["platform"]: round(r["total"], 2) for r in by_platform},
            "monthly": {r["month"]: round(r["total"], 2) for r in monthly},
        }


# ── Основной агент ─────────────────────────────────────────────────────────────

# Мои ключевые навыки для матчинга вакансий
MY_SKILLS = [
    "python", "fastapi", "django", "flask", "asyncio",
    "javascript", "typescript", "react", "next.js", "node.js",
    "telegram bot", "discord bot", "api integration",
    "stripe", "paypal", "crypto", "payment",
    "postgresql", "sqlite", "redis", "mongodb",
    "docker", "kubernetes", "aws", "gcp",
    "machine learning", "data science", "pandas", "numpy",
    "web scraping", "playwright", "selenium", "scrapy",
    "trading bot", "bybit", "binance", "algorithmic trading",
    "solidity", "smart contract", "web3", "ethereum",
    "rust", "go", "java",
]

# Базовая почасовая ставка по типу задачи
RATE_BY_TYPE: Dict[str, float] = {
    "api": 60.0,
    "bot": 50.0,
    "payment": 80.0,
    "scraping": 45.0,
    "trading": 100.0,
    "ml": 90.0,
    "blockchain": 120.0,
    "mobile": 70.0,
    "fullstack": 75.0,
    "default": 55.0,
}


class FreelanceAgent(BaseAgent):
    """
    Автономный агент поиска работы и управления фрилансом.
    Умеет искать вакансии, писать proposals и отслеживать доход.
    """

    def __init__(self) -> None:
        super().__init__("freelance")
        self._db = FreelanceDB()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="freelance",
            description=(
                "Автономный фриланс: поиск вакансий, написание proposals, "
                "оценка стоимости, трекинг заработка."
            ),
            capabilities=[
                "search_jobs", "generate_proposal", "estimate_project",
                "list_proposals", "track_earnings", "add_portfolio",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(найди|поищи|search).*(работ|job|вакансий|фриланс)",
            r"(фриланс|freelance|upwork|freelancer|fiverr)",
            r"(proposal|заявк|предложени).*(написать|создать|сгенерируй)",
            r"(оцени|estimate|сколько стоит|цена|бюджет).*(проект|задач|разработ)",
            r"(заработ|earning|доход|income).*(статистик|отчёт|сколько)",
            r"(портфолио|portfolio).*(добав|показ)",
            r"(заявк|proposal).*(список|активн|статус)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            tl = text.lower()

            if re.search(r"(найди|поищи|search).*(работ|job|вакансий)", tl):
                return self._cmd_search_jobs(text)

            if re.search(r"(оцени|estimate|сколько стоит|цена|бюджет)", tl):
                return self._cmd_estimate(text)

            if re.search(r"(proposal|заявк).*(написать|создать|сгенерируй)", tl):
                return self._cmd_generate_proposal(text)

            if re.search(r"(заработ|earning|доход|income)", tl):
                return self._cmd_earnings()

            if re.search(r"(портфолио|portfolio).*(добав)", tl):
                return self._cmd_add_portfolio(text)

            if re.search(r"(заявк|proposal).*(список|активн|статус)", tl):
                return self._cmd_list_proposals()

            # По умолчанию — поиск вакансий
            return self._cmd_search_jobs(text)

        except Exception as e:
            log.error("FreelanceAgent error: %s", e)
            return f"❌ Ошибка FreelanceAgent: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── Поиск вакансий ─────────────────────────────────────────────────────────

    def search_jobs(self, skills: Optional[List[str]] = None,
                    budget_min: float = 50.0,
                    platform: str = "all") -> List[FreelanceJob]:
        """Поиск вакансий по навыкам через SearchAgent + LLM парсинг."""
        search_skills = skills or MY_SKILLS[:8]
        jobs: List[FreelanceJob] = []

        # Поиск через DuckDuckGo (доступен без ключа)
        queries = [
            f"site:upwork.com jobs {' '.join(search_skills[:4])} python remote",
            f"freelance jobs {' '.join(search_skills[:3])} remote 2025",
            f"site:freelancer.com projects python api bot",
        ]

        for query in queries[:2]:
            try:
                from agents.search_agent import SearchAgent
                searcher = SearchAgent.get() if hasattr(SearchAgent, 'get') else SearchAgent()
                results = searcher.search(query, max_results=5)
                parsed = self._parse_search_results(results, search_skills)
                jobs.extend(parsed)
            except Exception as e:
                log.debug("Job search error for query '%s': %s", query, e)

        # Сохраняем в БД
        for job in jobs:
            self._db.save_job(job)

        # Также возвращаем ранее сохранённые
        saved = self._db.get_jobs(limit=20)
        all_jobs = {j.id: j for j in saved}
        for j in jobs:
            all_jobs[j.id] = j

        result = sorted(all_jobs.values(), key=lambda x: x.match_score, reverse=True)
        return result[:15]

    def _parse_search_results(self, results: Any, skills: List[str]) -> List[FreelanceJob]:
        """Парсим результаты поиска в структурированные вакансии."""
        if not results:
            return []

        # Преобразуем результаты в текст для LLM
        if isinstance(results, list):
            text = "\n".join(str(r) for r in results[:5])
        else:
            text = str(results)[:3000]

        prompt = (
            f"Из этих результатов поиска извлеки вакансии для фриланс-разработчика.\n\n"
            f"{text}\n\n"
            f"Верни JSON массив (максимум 5 вакансий):\n"
            f'[{{"id":"u1","platform":"upwork","title":"...","description":"...",'
            f'"budget_min":0,"budget_max":500,"budget_type":"fixed",'
            f'"skills":["python","api"],"url":"https://..."}}]\n'
            f"Если нет реальных вакансий — верни [].\n"
            f"Только JSON."
        )
        try:
            resp = self._llm.ask(LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                task_type="classify",
                max_tokens=800,
                preferred_provider=LLMProvider.DEEPSEEK,
            ))
            match = re.search(r'\[.*?\]', resp.content, re.DOTALL)
            if match:
                raw_jobs = json.loads(match.group())
                jobs = []
                for rj in raw_jobs[:5]:
                    job = FreelanceJob(
                        id=str(rj.get("id", f"j{int(time.time())}")),
                        platform=rj.get("platform", "web"),
                        title=rj.get("title", ""),
                        description=rj.get("description", ""),
                        budget_min=float(rj.get("budget_min", 0)),
                        budget_max=float(rj.get("budget_max", 500)),
                        budget_type=rj.get("budget_type", "fixed"),
                        skills=rj.get("skills", []),
                        url=rj.get("url", ""),
                    )
                    job.match_score = self._calc_match(job, skills)
                    if job.title:
                        jobs.append(job)
                return jobs
        except Exception as e:
            log.debug("Parse jobs error: %s", e)
        return []

    def _calc_match(self, job: FreelanceJob, my_skills: List[str]) -> float:
        """Считаем match score 0-1."""
        text = (job.title + " " + job.description + " " + " ".join(job.skills)).lower()
        matched = sum(1 for s in my_skills if s.lower() in text)
        return min(1.0, matched / max(len(my_skills), 1) * 3)

    # ── Генерация proposal ─────────────────────────────────────────────────────

    def generate_proposal(self, job: FreelanceJob) -> Proposal:
        """Генерирует персонализированный proposal через LLM."""
        estimate = self.estimate_project(job.description)

        portfolio = self._db.get_portfolio()
        portfolio_text = ""
        if portfolio:
            items = portfolio[:3]
            portfolio_text = "Релевантные работы из портфолио:\n" + "\n".join(
                f"• {p.title} ({', '.join(p.tech_stack[:3])})" for p in items
            )

        prompt = (
            f"Напиши профессиональный proposal для фриланс-вакансии.\n\n"
            f"ВАКАНСИЯ: {job.title}\n"
            f"ОПИСАНИЕ: {job.description[:600]}\n"
            f"БЮДЖЕТ: ${job.budget_min}-${job.budget_max} ({job.budget_type})\n"
            f"НАВЫКИ: {', '.join(job.skills[:8])}\n\n"
            f"МОЯ ОЦЕНКА: {estimate.hours_min}-{estimate.hours_max} часов, "
            f"${estimate.price_min}-${estimate.price_max}\n"
            f"{portfolio_text}\n\n"
            f"ТРЕБОВАНИЯ к proposal:\n"
            f"1. Крючок (1 предложение): покажи что понял задачу\n"
            f"2. Подход (3-4 предложения): как именно сделаешь\n"
            f"3. Опыт: 1-2 релевантных примера\n"
            f"4. Сроки: реалистичные + небольшой буфер\n"
            f"5. Призыв к действию: конкретный вопрос клиенту\n\n"
            f"Язык: английский (для international платформ).\n"
            f"Длина: 200-300 слов. Без шаблонных фраз типа 'I am a skilled developer'."
        )

        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code",
            max_tokens=600,
            preferred_provider=LLMProvider.CLAUDE,
        ))

        proposal_text = resp.content if resp.success else "❌ Не удалось сгенерировать proposal"

        bid = estimate.price_min if job.budget_type == "fixed" else estimate.rate_usd
        proposal = Proposal(
            id=f"p{int(time.time())}",
            job_id=job.id,
            job_title=job.title,
            platform=job.platform,
            text=proposal_text,
            bid_amount=bid,
            bid_type=job.budget_type,
            estimated_hours=estimate.hours_min,
        )
        self._db.save_proposal(proposal)
        return proposal

    # ── Оценка стоимости ───────────────────────────────────────────────────────

    def estimate_project(self, description: str) -> ProjectEstimate:
        """Оценивает стоимость проекта через LLM."""
        # Определяем тип задачи для ставки
        desc_lower = description.lower()
        rate = RATE_BY_TYPE["default"]
        for kw, r in [("stripe", "payment"), ("paypal", "payment"),
                      ("trading", "trading"), ("bot", "bot"),
                      ("scraping", "scraping"), ("ml", "ml"),
                      ("smart contract", "blockchain"), ("solidity", "blockchain"),
                      ("api", "api"), ("mobile", "mobile")]:
            if kw in desc_lower:
                rate = RATE_BY_TYPE.get(r, rate)
                break

        prompt = (
            f"Оцени трудозатраты на фриланс-проект (ты senior Python developer).\n\n"
            f"ОПИСАНИЕ: {description[:500]}\n\n"
            f"Верни JSON:\n"
            f'{{"hours_min":8,"hours_max":16,'
            f'"breakdown":["Design: 2h","Backend API: 6h","Testing: 2h"],'
            f'"risks":["Unclear requirements","Third-party API instability"],'
            f'"delivery_days":5}}\n'
            f"Только JSON."
        )

        hours_min, hours_max = 8.0, 16.0
        breakdown = ["Development", "Testing", "Documentation"]
        risks = ["Scope creep", "API limitations"]
        delivery = 5

        try:
            resp = self._llm.ask(LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                task_type="analysis",
                max_tokens=400,
                preferred_provider=LLMProvider.DEEPSEEK,
            ))
            if resp.success:
                match = re.search(r'\{.*?\}', resp.content, re.DOTALL)
                if match:
                    data = json.loads(match.group())
                    hours_min = float(data.get("hours_min", 8))
                    hours_max = float(data.get("hours_max", 16))
                    breakdown = data.get("breakdown", breakdown)
                    risks = data.get("risks", risks)
                    delivery = int(data.get("delivery_days", 5))
        except Exception as e:
            log.debug("Estimate LLM error: %s", e)

        return ProjectEstimate(
            description=description[:100],
            hours_min=hours_min,
            hours_max=hours_max,
            rate_usd=rate,
            price_min=round(hours_min * rate, 0),
            price_max=round(hours_max * rate, 0),
            breakdown=breakdown,
            risks=risks,
            delivery_days=delivery,
        )

    # ── Портфолио ─────────────────────────────────────────────────────────────

    def add_portfolio_item(self, title: str, description: str,
                           tech_stack: List[str], demo_url: str = "",
                           github_url: str = "", earned: float = 0.0) -> PortfolioItem:
        item = PortfolioItem(
            id=f"port{int(time.time())}",
            title=title,
            description=description,
            tech_stack=tech_stack,
            demo_url=demo_url,
            github_url=github_url,
            earned=earned,
        )
        self._db.add_portfolio_item(item)
        log.info("Portfolio item added: %s", title)
        return item

    # ── Статистика заработка ───────────────────────────────────────────────────

    def track_earnings(self) -> Dict[str, Any]:
        return self._db.earnings_summary()

    def record_earning(self, amount: float, platform: str,
                       description: str, currency: str = "USD") -> None:
        self._db.record_earning(amount, currency, platform, description)

    # ── Команды из текста ──────────────────────────────────────────────────────

    def _cmd_search_jobs(self, text: str) -> str:
        # Извлечь навыки из запроса
        skill_keywords = re.findall(
            r'\b(python|javascript|typescript|react|fastapi|django|flask|'
            r'telegram|discord|bot|api|stripe|paypal|crypto|docker|'
            r'trading|ml|scraping|rust|go|solidity)\b',
            text, re.IGNORECASE
        )
        skills = list(set(s.lower() for s in skill_keywords)) if skill_keywords else None

        jobs = self.search_jobs(skills=skills)

        if not jobs:
            return (
                "🔍 Вакансии не найдены в реальном времени.\n\n"
                "Сохранённые вакансии из базы:\n"
                + self._format_jobs(self._db.get_jobs(limit=10))
            )

        return f"🔍 Найдено {len(jobs)} вакансий:\n\n" + self._format_jobs(jobs[:8])

    def _cmd_estimate(self, text: str) -> str:
        # Извлечь описание задачи
        desc = re.sub(r'^(оцени|estimate|сколько стоит|цена)\s*', '', text, flags=re.IGNORECASE)
        estimate = self.estimate_project(desc or text)
        return self._format_estimate(estimate)

    def _cmd_generate_proposal(self, text: str) -> str:
        jobs = self._db.get_jobs(limit=1)
        if not jobs:
            return (
                "⚠️ Нет сохранённых вакансий. Сначала выполни поиск:\n"
                "«найди мне работу по Python»"
            )
        job = jobs[0]
        proposal = self.generate_proposal(job)
        return self._format_proposal(proposal)

    def _cmd_list_proposals(self) -> str:
        proposals = self._db.get_proposals()
        if not proposals:
            return "📋 Нет поданных заявок."
        lines = ["📋 **Заявки:**\n"]
        for p in proposals[:10]:
            icon = {"draft": "✏️", "submitted": "📤", "viewed": "👁",
                    "shortlisted": "⭐", "won": "✅", "rejected": "❌"}.get(p.status, "•")
            lines.append(
                f"{icon} **{p.job_title[:50]}** ({p.platform})\n"
                f"   ${p.bid_amount} {p.bid_type} | {p.status} | {p.created_at[:10]}"
            )
        return "\n".join(lines)

    def _cmd_earnings(self) -> str:
        summary = self.track_earnings()
        proposals = self._db.get_proposals(status="won")
        lines = [
            f"💰 **Статистика заработка:**\n",
            f"Всего заработано: **${summary['total_usd']:.2f}**",
        ]
        if summary["by_platform"]:
            lines.append("\nПо платформам:")
            for plat, amt in summary["by_platform"].items():
                lines.append(f"  • {plat}: ${amt:.2f}")
        if summary["monthly"]:
            lines.append("\nПо месяцам:")
            for month, amt in list(summary["monthly"].items())[:6]:
                lines.append(f"  • {month}: ${amt:.2f}")
        lines.append(f"\n✅ Выигранных заявок: {len(proposals)}")
        return "\n".join(lines)

    def _cmd_add_portfolio(self, text: str) -> str:
        prompt = (
            f"Из этого запроса извлеки данные для портфолио:\n{text}\n\n"
            f'Верни JSON: {{"title":"...","description":"...",'
            f'"tech_stack":["python","fastapi"],"demo_url":"","github_url":"","earned":0}}'
        )
        try:
            resp = self._llm.ask(LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                task_type="classify", max_tokens=300,
                preferred_provider=LLMProvider.DEEPSEEK,
            ))
            m = re.search(r'\{.*?\}', resp.content, re.DOTALL)
            if m:
                data = json.loads(m.group())
                item = self.add_portfolio_item(
                    title=data.get("title", "Проект"),
                    description=data.get("description", ""),
                    tech_stack=data.get("tech_stack", []),
                    demo_url=data.get("demo_url", ""),
                    github_url=data.get("github_url", ""),
                    earned=float(data.get("earned", 0)),
                )
                return f"✅ Добавлено в портфолио: **{item.title}**\nТех. стек: {', '.join(item.tech_stack)}"
        except Exception as e:
            log.debug("Add portfolio error: %s", e)
        return "❌ Не удалось распарсить данные портфолио. Укажи: название, описание, технологии."

    # ── Форматирование ─────────────────────────────────────────────────────────

    def _format_jobs(self, jobs: List[FreelanceJob]) -> str:
        if not jobs:
            return "Нет доступных вакансий."
        lines = []
        for i, j in enumerate(jobs, 1):
            budget = f"${j.budget_min:.0f}-${j.budget_max:.0f} {j.budget_type}" \
                     if j.budget_max > 0 else "бюджет не указан"
            match = f"match: {j.match_score:.0%}" if j.match_score > 0 else ""
            skills_str = ", ".join(j.skills[:4]) if j.skills else ""
            lines.append(
                f"{i}. **{j.title}** [{j.platform}]\n"
                f"   {budget} | {match}\n"
                f"   {skills_str}\n"
                + (f"   {j.url}\n" if j.url else "")
            )
        return "\n".join(lines)

    def _format_estimate(self, est: ProjectEstimate) -> str:
        lines = [
            f"📊 **Оценка проекта:**\n",
            f"⏱ Трудозатраты: **{est.hours_min:.0f}–{est.hours_max:.0f} часов**",
            f"💵 Стоимость: **${est.price_min:.0f}–${est.price_max:.0f}**",
            f"📅 Срок: {est.delivery_days} дней",
            f"💱 Ставка: ${est.rate_usd:.0f}/час",
        ]
        if est.breakdown:
            lines.append("\n📋 Разбивка работ:")
            lines.extend(f"  • {b}" for b in est.breakdown)
        if est.risks:
            lines.append("\n⚠️ Риски:")
            lines.extend(f"  • {r}" for r in est.risks[:3])
        return "\n".join(lines)

    def _format_proposal(self, p: Proposal) -> str:
        return (
            f"📝 **Proposal для: {p.job_title}**\n"
            f"Платформа: {p.platform} | Ставка: ${p.bid_amount} ({p.bid_type})\n"
            f"ID: {p.id}\n\n"
            f"---\n{p.text}\n---\n\n"
            f"✅ Сохранено в базе. Статус: {p.status}\n"
            f"Команда: «обнови статус заявки {p.id} на submitted» когда подашь."
        )

    @classmethod
    def get(cls) -> "FreelanceAgent":
        if not hasattr(cls, "_instance") or cls._instance is None:
            cls._instance = cls()
        return cls._instance

    _instance: Optional["FreelanceAgent"] = None
