# -*- coding: utf-8 -*-
"""
agents/search_agent.py — Веб-поиск и поиск информации.

Инструменты:
  • DuckDuckGo Search (бесплатно, без ключа)
  • Чтение веб-страниц через httpx + BeautifulSoup
  • Поиск по Wikipedia
  • Поиск по Arxiv (научные статьи)

Паттерны триггера:
  «найди», «поищи», «что такое X», «загуглить», «последние новости»,
  «search», «find», «look up», «wikipedia», «arxiv»
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMRequest

log = logging.getLogger("agents.search")

# Количество результатов поиска по умолчанию
DEFAULT_RESULTS = 5


class SearchAgent(BaseAgent):
    """
    Агент веб-поиска. Ищет информацию в интернете и возвращает
    структурированный ответ с синтезом найденных данных.
    """

    def __init__(self) -> None:
        super().__init__("search")
        self._ddgs = None
        self._http = None

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="search",
            description="Ищет информацию в интернете: DuckDuckGo, Wikipedia, Arxiv, чтение страниц.",
            capabilities=[
                "web_search", "read_url", "wikipedia_search",
                "arxiv_search", "news_search", "image_search",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(найди|поищи|загуглить|погуглить|ищи|найти|поиск|ответь)",
            r"(search|find|look up|google|bing|what is|who is)",
            r"(wikipedia|вики|arxiv|статья)",
            r"(последние новости|что нового|актуальн)",
            r"(прочитай страницу|открой сайт|зайди на)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            # Определить тип поиска
            if re.search(r"(wikipedia|вики)", text, re.IGNORECASE):
                return self._wikipedia_search(text)
            if re.search(r"(arxiv|научн|статья|paper|research)", text, re.IGNORECASE):
                return self._arxiv_search(text)
            if re.search(r"(прочитай|открой|зайди на|read url|open url|https?://)", text, re.IGNORECASE):
                return self._read_url(text)
            return self._web_search(text)
        except Exception as e:
            self._log_failure("search", str(e))
            return f"❌ Ошибка поиска: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── DuckDuckGo ────────────────────────────────────────────────────────────

    def _web_search(self, text: str) -> str:
        """Поиск через DuckDuckGo с синтезом результатов."""
        query = self._extract_query(text)
        log.info("Web search: %r", query)

        results = self._ddg_search(query, max_results=DEFAULT_RESULTS)
        if not results:
            return f"🔍 По запросу «{query}» ничего не найдено."

        # Форматируем результаты
        snippets = []
        for i, r in enumerate(results[:DEFAULT_RESULTS], 1):
            title = r.get("title", "Без заголовка")
            body = r.get("body", "")[:300]
            url = r.get("href", "")
            snippets.append(f"**{i}. {title}**\n{body}\n🔗 {url}")

        raw_text = "\n\n".join(snippets)

        # Синтез через LLM
        synthesis_prompt = (
            f"На основе результатов поиска ответь на вопрос: «{query}»\n\n"
            f"РЕЗУЛЬТАТЫ ПОИСКА:\n{raw_text}\n\n"
            f"Дай краткий структурированный ответ с ключевыми фактами. "
            f"Укажи источники."
        )
        synthesis = self._ask_llm(synthesis_prompt, task_type="analysis")

        return (
            f"🔍 **Поиск: «{query}»**\n\n"
            f"{synthesis}\n\n"
            f"---\n📋 **Источники:**\n" +
            "\n".join(f"• {r.get('title', '?')}: {r.get('href', '')}"
                      for r in results[:3])
        )

    def _ddg_search(self, query: str, max_results: int = 5) -> List[Dict]:
        """DuckDuckGo поиск."""
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            log.warning("DDG search failed: %s", e)
            return self._httpx_search_fallback(query, max_results)

    def _httpx_search_fallback(self, query: str, max_results: int) -> List[Dict]:
        """Fallback через DuckDuckGo HTML API."""
        try:
            http = self._get_http()
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            r = http.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code != 200:
                return []
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            results = []
            for div in soup.select(".result__body")[:max_results]:
                title_el = div.select_one(".result__title")
                body_el = div.select_one(".result__snippet")
                link_el = div.select_one(".result__url")
                results.append({
                    "title": title_el.get_text(strip=True) if title_el else "",
                    "body":  body_el.get_text(strip=True) if body_el else "",
                    "href":  link_el.get_text(strip=True) if link_el else "",
                })
            return results
        except Exception as e:
            log.warning("Fallback search failed: %s", e)
            return []

    # ── Wikipedia ─────────────────────────────────────────────────────────────

    def _wikipedia_search(self, text: str) -> str:
        """Поиск по Wikipedia через API."""
        query = self._extract_query(text)
        try:
            http = self._get_http()
            # Поиск страниц
            search_url = (
                f"https://ru.wikipedia.org/w/api.php"
                f"?action=query&format=json&list=search"
                f"&srsearch={quote_plus(query)}&srlimit=3"
            )
            r = http.get(search_url, timeout=15)
            data = r.json()
            pages = data.get("query", {}).get("search", [])

            if not pages:
                # Пробуем английскую Wikipedia
                search_url = (
                    f"https://en.wikipedia.org/w/api.php"
                    f"?action=query&format=json&list=search"
                    f"&srsearch={quote_plus(query)}&srlimit=3"
                )
                r = http.get(search_url, timeout=15)
                data = r.json()
                pages = data.get("query", {}).get("search", [])

            if not pages:
                return f"📖 Wikipedia: статья по «{query}» не найдена."

            # Загружаем контент первой страницы
            page_id = pages[0]["pageid"]
            lang = "ru" if "ru.wikipedia" in search_url else "en"
            content_url = (
                f"https://{lang}.wikipedia.org/w/api.php"
                f"?action=query&format=json&prop=extracts&exintro=true"
                f"&explaintext=true&pageids={page_id}"
            )
            r = http.get(content_url, timeout=15)
            extract = r.json()["query"]["pages"][str(page_id)].get("extract", "")
            extract = extract[:2000]

            return (
                f"📖 **Wikipedia: {pages[0]['title']}**\n\n"
                f"{extract}\n\n"
                f"🔗 https://{lang}.wikipedia.org/?curid={page_id}"
            )
        except Exception as e:
            return f"❌ Ошибка Wikipedia: {e}"

    # ── Arxiv ─────────────────────────────────────────────────────────────────

    def _arxiv_search(self, text: str) -> str:
        """Поиск научных статей на Arxiv."""
        query = self._extract_query(text)
        try:
            http = self._get_http()
            url = (
                f"https://export.arxiv.org/api/query"
                f"?search_query=all:{quote_plus(query)}"
                f"&start=0&max_results=3&sortBy=relevance"
            )
            r = http.get(url, timeout=20)
            import xml.etree.ElementTree as ET
            root = ET.fromstring(r.text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            entries = root.findall("atom:entry", ns)

            if not entries:
                return f"📄 Arxiv: статьи по «{query}» не найдены."

            results = []
            for entry in entries[:3]:
                title = entry.find("atom:title", ns)
                summary = entry.find("atom:summary", ns)
                link = entry.find("atom:id", ns)
                results.append(
                    f"📄 **{title.text.strip() if title is not None else '?'}**\n"
                    f"{(summary.text or '')[:300].strip()}...\n"
                    f"🔗 {link.text.strip() if link is not None else ''}"
                )

            return f"🔬 **Arxiv: «{query}»**\n\n" + "\n\n".join(results)
        except Exception as e:
            return f"❌ Ошибка Arxiv: {e}"

    # ── Чтение URL ────────────────────────────────────────────────────────────

    def _read_url(self, text: str) -> str:
        """Прочитать содержимое URL и резюмировать."""
        url_match = re.search(r"https?://[^\s]+", text)
        if not url_match:
            return "❌ URL не найден в запросе."
        url = url_match.group()
        try:
            http = self._get_http()
            r = http.get(url, headers={"User-Agent": "Mozilla/5.0"},
                         timeout=20, follow_redirects=True)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            # Удаляем скрипты/стили
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            content = soup.get_text(separator="\n", strip=True)
            content = "\n".join(l for l in content.splitlines() if len(l) > 20)[:3000]

            summary_prompt = (
                f"Резюмируй содержимое страницы {url}:\n\n{content}\n\n"
                f"Дай краткое структурированное резюме: о чём страница, "
                f"ключевые факты, важные детали."
            )
            return f"🌐 **{url}**\n\n" + self._ask_llm(summary_prompt, task_type="analysis")
        except Exception as e:
            return f"❌ Не удалось прочитать {url}: {e}"

    # ── Вспомогательные ──────────────────────────────────────────────────────

    def _extract_query(self, text: str) -> str:
        """Извлечь поисковый запрос из текста."""
        # Убираем служебные слова
        cleaned = re.sub(
            r"^(найди|поищи|загуглить|поиск|найти|search|find|look up|"
            r"что такое|кто такой|что нового о|wikipedia|arxiv|"
            r"прочитай страницу|открой сайт)\s*",
            "", text, flags=re.IGNORECASE
        ).strip()
        return cleaned or text

    def _get_http(self):
        """Получить или создать httpx клиент."""
        if self._http is None:
            try:
                import httpx
                import warnings
                warnings.filterwarnings("ignore")
                self._http = httpx.Client(timeout=30.0, verify=False,
                                          follow_redirects=True)
            except Exception:
                import requests
                self._http = requests.Session()
                self._http.verify = False
        return self._http
