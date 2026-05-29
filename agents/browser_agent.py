#!/usr/bin/env python3
"""
BrowserAgent - Autonomous web browser via Tor for MaxAI.
Uses Tor SOCKS5 (127.0.0.1:9050) for anonymous secure browsing.
Falls back to direct requests if Tor unavailable.
"""
import logging, time, re
from typing import Optional, List, Dict, Any
from agents.base_agent import BaseAgent, AgentInfo

log = logging.getLogger("agents.browser")


class BrowserAgent(BaseAgent):
    """Autonomous web browser via Tor - secure and anonymous."""

    name = "browser"
    description = "Anonymous browser via Tor. Can: open pages, search web, parse text, check links, get crypto prices."

    def __init__(self):
        super().__init__("browser")
        self._session = None
        self._tor_ok = False
        self._page_history: List[Dict] = []
        self._setup_session()

    # ── Abstract method implementations ──────────────────────────────────────

    def can_handle(self, text: str) -> bool:
        """Returns True if this agent can handle the given text."""
        text_lower = text.lower()
        keywords = [
            "найди", "поиск", "search", "найти", "ищи",
            "браузер", "browser", "открой", "открыть",
            "цена", "price", "курс", "стоимость",
            "новости", "news", "история", "history",
            "http://", "https://", "tor", "www.",
            "btc", "eth", "bitcoin", "ethereum",
        ]
        return any(kw in text_lower for kw in keywords)

    def info(self) -> AgentInfo:
        """Return agent metadata."""
        return AgentInfo(
            name="browser",
            description="Anonymous web browser via Tor. Searches, browses pages, gets crypto prices.",
            capabilities=[
                "web_search", "page_browse", "crypto_price",
                "news_fetch", "tor_anonymity", "link_extraction",
            ],
            version="2.0.0",
        )

    # ── Session setup ─────────────────────────────────────────────────────────

    def _setup_session(self):
        """Configure requests session via Tor or direct."""
        try:
            import requests
            sess = requests.Session()
            sess.proxies = {
                "http":  "socks5h://127.0.0.1:9050",
                "https": "socks5h://127.0.0.1:9050",
                "no": "127.0.0.1,localhost,::1",
            }
            sess.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/115.0",
                "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
            })
            try:
                resp = sess.get("https://check.torproject.org/api/ip", timeout=10)
                data = resp.json()
                if data.get("IsTor"):
                    self._tor_ok = True
                    log.info("BrowserAgent: Tor OK - IP=%s", data.get("IP", "?"))
                else:
                    log.warning("BrowserAgent: Tor not confirmed, using direct connection")
                    sess.proxies = {}
            except Exception as te:
                log.warning("BrowserAgent: Tor test failed (%s), using direct", te)
                sess.proxies = {}
            self._session = sess
            log.info("BrowserAgent initialized (tor=%s)", self._tor_ok)
        except ImportError:
            log.error("BrowserAgent: requests not installed - run: pip install requests[socks]")
        except Exception as e:
            log.error("BrowserAgent: session setup failed: %s", e)

    # ── Core methods ──────────────────────────────────────────────────────────

    def browse(self, url: str, extract_links: bool = False) -> Dict[str, Any]:
        """Open a page and return text + metadata."""
        if not self._session:
            self._setup_session()
        if not self._session:
            return {"error": "No HTTP session available", "url": url}
        try:
            t0 = time.time()
            resp = self._session.get(url, timeout=20)
            latency = round((time.time() - t0) * 1000)
            text = self._extract_text(resp.text)
            title = self._extract_title(resp.text)
            links = self._extract_links(resp.text, url) if extract_links else []
            result = {
                "url": url,
                "title": title,
                "status": resp.status_code,
                "text": text[:5000],
                "links": links[:20],
                "latency_ms": latency,
                "via_tor": self._tor_ok,
                "ts": time.time(),
            }
            self._page_history.append({"url": url, "title": title, "ts": time.time()})
            if len(self._page_history) > 50:
                self._page_history = self._page_history[-50:]
            log.info("BrowserAgent: %s -> %d chars, %dms, tor=%s",
                     url[:60], len(text), latency, self._tor_ok)
            return result
        except Exception as e:
            log.error("BrowserAgent.browse error for %s: %s", url[:60], e)
            return {"error": str(e), "url": url}

    def search(self, query: str) -> List[Dict]:
        """Search the web via DuckDuckGo (no tracking)."""
        try:
            from urllib.parse import quote
            search_url = f"https://html.duckduckgo.com/html/?q={quote(query)}&kl=ru-ru"
            result = self.browse(search_url)
            if result.get("error"):
                return [{"error": result["error"], "query": query}]
            text = result.get("text", "")
            parts = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 40]
            snippets = [{"text": p[:300], "query": query} for p in parts[:8]]
            log.info("BrowserAgent: search '%s' -> %d results", query[:40], len(snippets))
            return snippets if snippets else [{"text": text[:2000], "query": query}]
        except Exception as e:
            return [{"error": str(e), "query": query}]

    def get_price(self, symbol: str) -> Optional[float]:
        """Get crypto price from Bybit API."""
        try:
            if not self._session:
                self._setup_session()
            clean = symbol.upper().replace("USDT", "")
            resp = self._session.get(
                f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={clean}USDT",
                timeout=8
            )
            data = resp.json()
            price = data.get("result", {}).get("list", [{}])[0].get("lastPrice")
            if price:
                log.info("BrowserAgent: %sUSDT = %s", clean, price)
                return float(price)
            return None
        except Exception as e:
            log.error("get_price error for %s: %s", symbol, e)
            return None

    def get_news(self, topic: str = "crypto bitcoin") -> List[Dict]:
        """Get news on topic via DuckDuckGo."""
        return self.search(topic + " news site:coindesk.com OR site:cointelegraph.com OR site:reuters.com")

    def history(self) -> List[Dict]:
        """Return browsing history."""
        return list(reversed(self._page_history))

    def new_identity(self) -> bool:
        """Get a new Tor exit node (new IP)."""
        try:
            from stem import Signal
            from stem.control import Controller
            with Controller.from_port(port=9051) as ctrl:
                ctrl.authenticate()
                ctrl.signal(Signal.NEWNYM)
                time.sleep(5)
                self._setup_session()
                log.info("BrowserAgent: new Tor identity obtained")
                return True
        except Exception as e:
            log.warning("BrowserAgent.new_identity failed: %s", e)
            return False

    def status(self) -> str:
        """Return status string."""
        tor = "Tor active" if self._tor_ok else "Direct (no Tor)"
        hist = len(self._page_history)
        return f"BrowserAgent: {tor} | History: {hist} pages"

    # ── HTML parsing helpers ──────────────────────────────────────────────────

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML."""
        html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.I)
        html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.I)
        html = re.sub(r'<[^>]+>', ' ', html)
        for entity, char in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'),
                               ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'")]:
            html = html.replace(entity, char)
        html = re.sub(r'\s{3,}', '\n\n', html)
        return html.strip()[:8000]

    def _extract_title(self, html: str) -> str:
        m = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.DOTALL)
        return m.group(1).strip()[:100] if m else "Untitled"

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        return list(set(re.findall(r'href=["\']*(https?://[^"\'\s>]+)', html)))[:20]

    # ── Main process dispatcher ───────────────────────────────────────────────

    def process(self, text: str, source: str = "user", **kwargs) -> str:
        """Process browser command."""
        text_lower = text.lower().strip()

        if any(w in text_lower for w in ["новый ip", "сменить ip", "new identity", "new ip", "смени ip"]):
            ok = self.new_identity()
            return "Новый Tor IP получен" if ok else "Tor control port недоступен (порт 9051)"

        if any(w in text_lower for w in ["история", "history", "посещённые", "посещенные"]):
            h = self.history()
            if not h:
                return "История посещений пуста"
            lines_out = ["Браузер (последние 10):"]
            for item in h[:10]:
                ts = time.strftime("%H:%M", time.localtime(item["ts"]))
                lines_out.append(f"  [{ts}] {item['title'][:50]} - {item['url'][:70]}")
            return "\n".join(lines_out)

        if any(w in text_lower for w in ["статус", "status", "tor"]):
            return self.status()

        search_words = ["найди", "поиск", "search", "найти", "ищи", "найди информацию", "поищи"]
        if any(w in text_lower for w in search_words):
            query = text_lower
            for p in search_words + ["в интернете", "в сети", "онлайн"]:
                query = query.replace(p, "").strip()
            if not query:
                return "Укажи запрос: найди [запрос]"
            results = self.search(query)
            if not results:
                return "Ничего не найдено"
            lines_out = [f"Результаты поиска: {query[:50]}"]
            for r in results[:5]:
                t = r.get('text', r.get('error', ''))
                lines_out.append(f"  {t[:200]}")
            return "\n".join(lines_out)

        if any(w in text_lower for w in ["цена", "price", "курс", "стоимость"]):
            syms = re.findall(r'\b(BTC|ETH|SOL|BNB|XRP|ADA|LINK|DOGE|AVAX|DOT|MATIC|ARB|OP)\b', text.upper())
            if not syms:
                syms = ["BTC", "ETH"]
            prices = []
            for sym in syms[:5]:
                p = self.get_price(sym)
                prices.append(f"{sym}: ${p:,.2f}" if p else f"{sym}: N/A")
            via = "Tor" if self._tor_ok else "Direct"
            return f"[{via}] " + " | ".join(prices)

        if any(w in text_lower for w in ["новости", "news", "крипто новости"]):
            topic = text_lower
            for p in ["новости", "news", "крипто", "crypto"]:
                topic = topic.replace(p, "").strip()
            topic = topic or "crypto bitcoin market"
            results = self.get_news(topic)
            if not results:
                return "Нет новостей"
            text_out = results[0].get('text', 'Нет данных')[:1500]
            return f"Новости: {topic[:30]}\n\n{text_out}"

        urls = re.findall(r'https?://[\w./%-]+', text)
        if urls:
            url = urls[0]
            result = self.browse(url, extract_links=True)
            if result.get("error"):
                return f"Ошибка открытия {url}: {result['error']}"
            via = "Tor" if result["via_tor"] else "Direct"
            links_text = "\n".join(result.get("links", [])[:5])
            return (
                f"[{via}] {result['title']}\n"
                f"URL: {url}\n"
                f"Статус: {result['status']} | {result['latency_ms']}ms\n\n"
                f"{result['text'][:800]}\n\n"
                f"Ссылки:\n{links_text}"
            )

        return (
            f"BrowserAgent [{self.status()}]\n\n"
            f"Команды:\n"
            f"  найди [запрос] - поиск в интернете\n"
            f"  [url] - открыть страницу\n"
            f"  цена BTC/ETH - курс криптовалют\n"
            f"  новости [тема] - последние новости\n"
            f"  история - история посещений\n"
            f"  новый ip - сменить Tor exit node"
        )
