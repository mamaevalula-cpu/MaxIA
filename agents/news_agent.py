# -*- coding: utf-8 -*-
"""
agents/news_agent.py — Агент новостей и трендов.

Источники:
  • RSS-ленты (feedparser): технологии, крипто, бизнес, наука
  • DuckDuckGo News
  • Фильтрация по теме через LLM
  • Дайджест с краткими саммари

Триггеры: «последние новости», «что нового», «тренды», «дайджест»
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMRequest

log = logging.getLogger("agents.news")

# RSS-ленты по категориям
RSS_FEEDS = {
    "tech": [
        "https://feeds.feedburner.com/TechCrunch",
        "https://www.theverge.com/rss/index.xml",
        "https://hnrss.org/frontpage",       # Hacker News
        "https://www.wired.com/feed/rss",
    ],
    "crypto": [
        "https://cointelegraph.com/rss",
        "https://coindesk.com/arc/outboundfeeds/rss/",
        "https://cryptonews.com/news/feed/",
        "https://decrypt.co/feed",
    ],
    "ai": [
        "https://openai.com/blog/rss.xml",
        "https://bair.berkeley.edu/blog/feed.xml",
        "https://huggingface.co/blog/feed.xml",
    ],
    "finance": [
        "https://feeds.bloomberg.com/technology/news.rss",
        "https://seekingalpha.com/feed.xml",
    ],
    "russia": [
        "https://lenta.ru/rss/articles",
        "https://tass.ru/rss/v2.xml",
        "https://habr.com/ru/rss/articles/",
    ],
}

# Кеш новостей
CACHE_FILE = Path(__file__).parent.parent / "data" / "news_cache.json"
CACHE_TTL = 1800  # 30 минут


class NewsAgent(BaseAgent):
    """
    Агент новостей — следит за трендами и доставляет дайджест.
    """

    def __init__(self) -> None:
        super().__init__("news")
        self._cache: Dict[str, Dict] = {}
        self._load_cache()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="news",
            description="Собирает и суммаризирует новости: технологии, крипто, AI, финансы.",
            capabilities=[
                "get_news", "tech_news", "crypto_news",
                "ai_news", "news_digest", "trending_topics",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(последние новости|что нового|новости|дайджест|тренды)",
            r"(news|digest|trending|latest|what's new|headlines)",
            r"(новости крипто|новости технологий|новости ии|tech news|crypto news)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            category = self._detect_category(text)
            return self._get_digest(text, category)
        except Exception as e:
            self._log_failure("news", str(e))
            return f"❌ Ошибка получения новостей: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── Определение категории ─────────────────────────────────────────────────

    def _detect_category(self, text: str) -> str:
        if re.search(r"(крипто|bitcoin|btc|eth|crypto|bybit|binance)", text, re.IGNORECASE):
            return "crypto"
        if re.search(r"(ии|ai|artificial intelligence|нейросет|gpt|claude|deepseek)", text, re.IGNORECASE):
            return "ai"
        if re.search(r"(финанс|акции|рынок|биржа|finance|stocks|market)", text, re.IGNORECASE):
            return "finance"
        if re.search(r"(россия|рф|russia|habr|хабр)", text, re.IGNORECASE):
            return "russia"
        return "tech"  # default

    # ── Получение и обработка новостей ───────────────────────────────────────

    def _get_digest(self, query: str, category: str) -> str:
        """Получить дайджест новостей по категории."""
        # Проверяем кеш
        cache_key = category
        cached = self._cache.get(cache_key)
        if cached and time.time() - cached.get("ts", 0) < CACHE_TTL:
            articles = cached["articles"]
            from_cache = True
        else:
            articles = self._fetch_rss(category)
            if not articles:
                # Fallback: DuckDuckGo news
                articles = self._ddg_news(query)
            self._cache[cache_key] = {"ts": time.time(), "articles": articles}
            self._save_cache()
            from_cache = False

        if not articles:
            return f"📰 Новости по теме «{category}» недоступны в данный момент."

        # Фильтрация по запросу пользователя (если есть конкретный топик)
        topic_filter = self._extract_topic(query)
        if topic_filter and len(topic_filter) > 3:
            filtered = [a for a in articles
                        if topic_filter.lower() in (a.get("title","") + a.get("summary","")).lower()]
            if filtered:
                articles = filtered[:8]

        # Суммаризация через LLM
        articles_text = "\n\n".join([
            f"**{a['title']}**\n{a.get('summary','')[:300]}\n{a.get('link','')}"
            for a in articles[:8]
        ])

        prompt = (
            f"Сделай краткий дайджест этих новостей по теме «{category}».\n"
            f"Запрос пользователя: «{query}»\n\n"
            f"НОВОСТИ:\n{articles_text}\n\n"
            f"Формат:\n"
            f"1. Топ-3 самых важных новости с кратким объяснением\n"
            f"2. Общий тренд (1 предложение)\n"
            f"3. На что обратить внимание\n"
            f"Будь конкретным, без лишних слов."
        )
        digest = self._ask_llm(prompt, task_type="analysis")

        cache_note = " _(из кеша)_" if from_cache else ""
        return (
            f"📰 **Дайджест [{category.upper()}]{cache_note}**\n"
            f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"{digest}\n\n"
            f"---\n"
            f"📌 Всего найдено статей: {len(articles)}"
        )

    def _fetch_rss(self, category: str) -> List[Dict]:
        """Загрузить RSS-ленты по категории."""
        try:
            import feedparser
        except ImportError:
            return []

        feeds = RSS_FEEDS.get(category, RSS_FEEDS["tech"])
        articles = []

        for feed_url in feeds[:3]:  # Макс 3 ленты
            try:
                # feedparser может использовать кеш
                cache_key = hashlib.md5(feed_url.encode()).hexdigest()
                feed_cache = self._cache.get(f"rss_{cache_key}")

                if feed_cache and time.time() - feed_cache.get("ts", 0) < CACHE_TTL:
                    articles.extend(feed_cache["items"])
                    continue

                feed = feedparser.parse(feed_url)
                items = []
                for entry in feed.entries[:5]:
                    items.append({
                        "title": entry.get("title", ""),
                        "summary": re.sub(r'<[^>]+>', '', entry.get("summary", ""))[:500],
                        "link": entry.get("link", ""),
                        "published": entry.get("published", ""),
                    })
                self._cache[f"rss_{cache_key}"] = {"ts": time.time(), "items": items}
                articles.extend(items)
            except Exception as e:
                log.debug("RSS %s failed: %s", feed_url, e)

        return articles[:15]

    def _ddg_news(self, query: str) -> List[Dict]:
        """Новости через DuckDuckGo как fallback."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.news(query, max_results=8))
            return [{"title": r.get("title",""), "summary": r.get("body",""),
                     "link": r.get("url","")} for r in results]
        except Exception as e:
            log.debug("DDG news failed: %s", e)
            return []

    def _extract_topic(self, text: str) -> str:
        cleaned = re.sub(
            r"(последние новости о?|что нового о?|новости о?|тренды|дайджест|"
            r"news about|latest|trending)",
            "", text, flags=re.IGNORECASE
        ).strip()
        return cleaned

    # ── Кеш ──────────────────────────────────────────────────────────────────

    def _load_cache(self) -> None:
        try:
            if CACHE_FILE.exists():
                self._cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            self._cache = {}

    def _save_cache(self) -> None:
        try:
            CACHE_FILE.parent.mkdir(exist_ok=True)
            # Сохраняем только легковесные данные (без binary)
            light = {k: v for k, v in self._cache.items()
                     if isinstance(v, dict) and "articles" in v}
            CACHE_FILE.write_text(
                json.dumps(light, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass
