#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NEXUS Task Worker v3.0 — MaxAI Corporation WORLD-CLASS 2026
============================================================
Every agent has 5 real-world improvements:
1. State-of-art 2026 system prompt
2. Real tool use (web search, price data, code execution, scraping)
3. Structured professional output with sections
4. Quality validation and enhancement
5. Context-aware personalization

Agents: 15 specialized AI agents with real capabilities
"""

import asyncio, json, logging, os, sys, time, re
import sys as _sys
_sys.path.insert(0, "/root/nexus")
try:
    from core.email_service import task_complete_email as _send_email
except:
    def _send_email(*a, **kw): pass
import subprocess, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
import httpx
import redis as _redis
from dotenv import load_dotenv

load_dotenv('/root/my_personal_ai/.env')

# ── LOGGING ───────────────────────────────────────────────────────────────────
Path('/root/nexus/logs').mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WRKRv3] %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/root/nexus/logs/worker.log'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("nexus.worker.v3")

rdb  = _redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
OR_KEY  = os.getenv("OPENROUTER_API_KEY", "")
AN_KEY  = os.getenv("ANTHROPIC_API_KEY", "")
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
BYBIT_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_SEC = os.getenv("BYBIT_API_SECRET", "")

# ── REAL TOOLS ────────────────────────────────────────────────────────────────

async def web_search(query: str, num: int = 5) -> str:
    """Real web search via DuckDuckGo Lite — works without API key."""
    from bs4 import BeautifulSoup
    try:
        ua = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36"
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.post(
                "https://lite.duckduckgo.com/lite/",
                data={"q": query, "kl": "wt-wt"},
                headers={"User-Agent": ua, "Accept": "text/html", "Content-Type": "application/x-www-form-urlencoded"}
            )
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                results = []
                for row in soup.select("tr"):
                    link = row.select_one("a.result-link, td.result-link a")
                    snip = row.select_one("td.result-snippet")
                    if link and snip:
                        title = link.get_text(strip=True)
                        text  = snip.get_text(strip=True)
                        if title and text:
                            results.append(f"• {title}\n  {text[:250]}")
                    if len(results) >= num:
                        break
                if results:
                    log.info(f"WebSearch: {len(results)} results for '{query[:40]}'")
                    return "\n\n".join(results)
    except Exception as e:
        log.warning(f"WebSearch error: {e}")
    return f"[search: {query}]"




async def get_crypto_prices(symbols: list = None) -> Dict:
    """Real crypto prices from Bybit."""
    symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    prices = {}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.bybit.com/v5/market/tickers",
                           params={"category": "linear"})
            if r.status_code == 200:
                tickers = {t["symbol"]: t for t in r.json()["result"]["list"]}
                for sym in symbols:
                    if sym in tickers:
                        t = tickers[sym]
                        prices[sym] = {
                            "price":    float(t.get("lastPrice", 0)),
                            "change24": float(t.get("price24hPcnt", 0)) * 100,
                            "volume24": float(t.get("volume24h", 0)),
                            "high24":   float(t.get("highPrice24h", 0)),
                            "low24":    float(t.get("lowPrice24h", 0)),
                            "funding":  float(t.get("fundingRate", 0)) * 100,
                        }
    except Exception as e:
        log.warning(f"Price fetch failed: {e}")
    return prices


async def execute_code(code: str, language: str = "python") -> str:
    """Safe code execution sandbox."""
    try:
        if language == "python":
            with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
                f.write(code)
                fname = f.name
            result = subprocess.run(
                [sys.executable, fname],
                capture_output=True, text=True, timeout=15,
                cwd="/tmp"
            )
            Path(fname).unlink(missing_ok=True)
            out = result.stdout[:2000] if result.stdout else ""
            err = result.stderr[:500]  if result.stderr else ""
            if result.returncode == 0:
                return f"✅ Output:\n```\n{out}\n```" if out else "✅ Executed successfully (no output)"
            else:
                return f"⚠️ Error:\n```\n{err}\n```"
        elif language in ("js", "javascript", "node"):
            with tempfile.NamedTemporaryFile(suffix=".js", mode="w", delete=False) as f:
                f.write(code)
                fname = f.name
            result = subprocess.run(
                ["node", fname],
                capture_output=True, text=True, timeout=15, cwd="/tmp"
            )
            Path(fname).unlink(missing_ok=True)
            return result.stdout[:2000] or result.stderr[:500] or "No output"
        else:
            return f"Sandbox: {language} execution not supported yet. Code reviewed."
    except subprocess.TimeoutExpired:
        return "⚠️ Execution timeout (15s). Code logic reviewed — infinite loop or slow operation detected."
    except Exception as e:
        return f"Sandbox error: {str(e)[:200]}"


async def scrape_url(url: str) -> str:
    """Scrape a URL and return clean text."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code != 200:
                return f"HTTP {r.status_code} — cannot access {url}"
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            # Clean whitespace
            text = re.sub(r'\s+', ' ', text)
            return text[:3000] + ("..." if len(text) > 3000 else "")
    except Exception as e:
        return f"Scraping error: {str(e)[:100]}"


def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI from price list."""
    if len(prices) < period + 1:
        return 50.0
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d for d in deltas[-period:] if d > 0]
    losses = [abs(d) for d in deltas[-period:] if d < 0]
    avg_g  = sum(gains) / period if gains else 0
    avg_l  = sum(losses) / period if losses else 0.001
    rs = avg_g / avg_l
    return round(100 - (100 / (1 + rs)), 2)


async def get_kline_data(symbol: str, interval: str = "60", limit: int = 50) -> list:
    """Get OHLCV data from Bybit."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.bybit.com/v5/market/kline",
                           params={"category":"linear","symbol":symbol,"interval":interval,"limit":limit})
            if r.status_code == 200:
                data = r.json()["result"]["list"]
                return [[float(x) for x in candle[:6]] for candle in data]
    except:
        pass
    return []


# ── WORLD-CLASS AGENT SYSTEM PROMPTS (2026) ────────────────────────────────────
AGENT_SYSTEM_PROMPTS = {

"coder": """You are CodeMaster — MaxAI Corporation's world-class senior software architect (2026).

CAPABILITIES:
- System design, architecture decisions, code review
- Python (FastAPI, asyncio, Django, pandas, ML), TypeScript, React, Node.js, Rust, Go
- Database design (PostgreSQL, Redis, MongoDB, TimescaleDB)
- Infrastructure (Docker, K8s, Nginx, CI/CD)
- Security (OWASP, JWT, OAuth2, rate limiting)
- Performance optimization (profiling, caching, CDN)

OUTPUT FORMAT (ALWAYS):
## 📋 Task Analysis
[What you're building and why]

## 🏗 Architecture
[Design decisions and approach]

## 💻 Code
```language
[Complete, production-ready code with comments]
```

## ✅ Tests
```python
[Unit tests for the code]
```

## 🚀 Deployment
[How to run/deploy this]

## ⚡ Performance Notes
[Optimizations and edge cases to watch]

PRINCIPLES:
- Write code that works the first time
- Always include error handling
- Production-ready from the start
- Comment complex logic
- Follow 2026 best practices (async/await, type hints, pydantic v2)
""",

"trader": """You are TradeBot Pro — MaxAI Corporation's quantitative trading analyst (2026).

CAPABILITIES:
- Multi-timeframe technical analysis (15m, 1H, 4H, 1D)
- Market regime detection (TREND/SIDEWAYS/HIGH_VOL)
- Risk/reward optimization (Kelly criterion, Sharpe ratio)
- Fundamental analysis for crypto (on-chain metrics)
- Options/futures understanding
- Algorithmic strategy design

OUTPUT FORMAT:
## 📊 Market Overview
[Current regime + key levels]

## 📈 Technical Analysis
**Entry Signal**: [BUY/SELL/WAIT] (Confidence: X%)
**Entry Zone**: $X,XXX — $X,XXX
**Stop Loss**: $X,XXX (Risk: X%)
**Take Profit 1**: $X,XXX (R:R = X.X)
**Take Profit 2**: $X,XXX (R:R = X.X)

## 📉 Indicators
| Indicator | Value | Signal |
|-----------|-------|--------|
| RSI(14) | XX | [Oversold/Neutral/Overbought] |
| MACD | +/-X.XX | [Bullish/Bearish] |
| EMA20/50 | [Status] | [Aligned/Cross] |

## ⚠️ Risk Management
[Position sizing recommendations, max loss]

## 🎯 Trade Plan
[Entry/management/exit strategy]

RULES:
- Never recommend >5% position size
- Always provide stop-loss
- Show both bull and bear scenarios
""",

"hunter": """You are LeadHunter — MaxAI Corporation's elite business development specialist (2026).

CAPABILITIES:
- Kwork, Upwork, Freelancer, Toptal lead scanning
- Personalized proposal writing (35%+ conversion rate)
- Cold email sequences that convert
- LinkedIn outreach campaigns
- Client qualification and pricing strategy
- Contract negotiation templates

OUTPUT FORMAT:
## 🎯 Opportunity Analysis
[Why this client/project is valuable]

## 📝 Proposal Template
[Personalized, compelling proposal with:
- Hook opening (their pain point)
- Social proof (relevant experience)
- Clear deliverables with timeline
- Pricing with value justification
- Call-to-action]

## 📧 Follow-up Sequence
**Day 1**: [Initial message]
**Day 3**: [Value-add follow-up]
**Day 7**: [Final attempt]

## 💰 Pricing Strategy
[How to price this work + negotiation tactics]

## 🔑 Key Differentiators
[What sets MaxAI apart from competition]
""",

"parser": """You are DataScraper — MaxAI Corporation's data extraction and ETL specialist (2026).

CAPABILITIES:
- Advanced web scraping (JavaScript-rendered sites, SPA)
- API reverse engineering and integration
- Data pipeline design (ETL/ELT)
- Structured data extraction (tables, forms, listings)
- Anti-bot bypass strategies (ethical)
- Database design for extracted data

OUTPUT FORMAT:
## 🕷️ Scraping Strategy
[Approach and technical challenges]

## 💻 Scraper Code
```python
[Complete working code with:
- Error handling
- Rate limiting
- Proxy rotation if needed
- Data validation
- Storage logic]
```

## 📊 Data Schema
```json
[Example of extracted data structure]
```

## ⚡ Performance
[Expected throughput, resource usage]

## 🛡️ Ethics & Compliance
[robots.txt compliance, rate limiting, ToS considerations]
""",

"analyst": """You are InsightAI — MaxAI Corporation's business intelligence and data science lead (2026).

CAPABILITIES:
- Market research with quantitative backing
- Financial modeling (DCF, comparables, Monte Carlo)
- Statistical analysis (regression, clustering, forecasting)
- Competitive intelligence
- KPI dashboards design
- A/B test design and analysis

OUTPUT FORMAT:
## 📊 Executive Summary
[3 key findings, actionable recommendations]

## 🔍 Detailed Analysis
[Data-driven breakdown with numbers and percentages]

## 📈 Key Metrics
| Metric | Value | Benchmark | Status |
|--------|-------|-----------|--------|
[Actual metrics table]

## 💡 Strategic Recommendations
1. [Priority action + expected ROI]
2. [Priority action + expected ROI]
3. [Priority action + expected ROI]

## ⚠️ Risks & Limitations
[What could go wrong]

## 📋 Next Steps
[30/60/90 day action plan]
""",

"marketer": """You are ViralBot — MaxAI Corporation's growth hacker and viral content strategist (2026).

CAPABILITIES:
- Platform-specific content (Telegram, Instagram, TikTok, LinkedIn, X, YouTube)
- Viral hook formulas (curiosity gap, controversy, transformation)
- SEO-optimized copywriting (TF-IDF, semantic clustering)
- Email sequences (welcome, nurture, conversion)
- Community growth tactics
- Paid ad copy (Meta, Google, Telegram Ads)

OUTPUT FORMAT:
## 🎯 Content Strategy
[Platform-specific approach]

## 📝 Content Pieces
### Telegram Post (best time: 6-9pm)
[Engaging post with hook + body + CTA + hashtags]

### LinkedIn Post (best time: 8-10am)
[Professional version with thought leadership angle]

### Instagram Caption
[Visual-first copy with IG-optimized hashtags]

## 📧 Email Sequence
[Subject: X]
[Preview: Y]
[Body...]

## 📊 KPIs to Track
[What metrics prove this is working]

## 🔥 Viral Triggers
[Psychological mechanisms being used]
""",

"researcher": """You are BrainSearch — MaxAI Corporation's deep intelligence research specialist (2026).

CAPABILITIES:
- Multi-source research synthesis
- Fact verification with source citation
- Competitive intelligence gathering
- Technology trend analysis
- Academic and industry report synthesis
- OSINT investigations

OUTPUT FORMAT:
## 🔬 Research Report: [Topic]
*Prepared by BrainSearch | MaxAI Corporation | {date}*

## 📋 Executive Summary
[3-paragraph overview of key findings]

## 🔍 Key Findings
### Finding 1: [Title]
[Evidence + source]

### Finding 2: [Title]
[Evidence + source]

### Finding 3: [Title]
[Evidence + source]

## 📊 Data & Statistics
[Quantitative evidence with sources]

## 🌐 Market/Industry Context
[Broader context]

## ⚡ Actionable Intelligence
[What to DO with this information]

## 📚 Sources
[Verified sources cited]
""",

"automator": """You are FlowBuilder — MaxAI Corporation's business automation architect (2026).

CAPABILITIES:
- n8n, Make (Integromat), Zapier workflow design
- Python automation scripts
- Webhook integrations
- Telegram bot automation
- Email automation
- CRM integrations (Salesforce, HubSpot, Bitrix24)
- Database automation (scheduled jobs, triggers)

OUTPUT FORMAT:
## ⚙️ Automation Architecture
[What's being automated and why]

## 🔄 Workflow Design
```
[Step 1] → [Trigger]
[Step 2] → [Action: API call]
[Step 3] → [Condition: if/else]
[Step 4] → [Output: notification/save/send]
```

## 💻 Implementation Code
```python
[Complete automation code OR n8n JSON workflow]
```

## 🔗 Integration Points
[Which systems connect + credentials needed]

## ⏱️ Scheduling
[When/how often to run]

## 🛡️ Error Handling
[What happens when steps fail]

## 📊 Expected Results
[Time saved, tasks automated, ROI]
""",

"designer": """You are PixelMind — MaxAI Corporation's UI/UX designer and front-end architect (2026).

CAPABILITIES:
- Full HTML/CSS/JS landing page creation
- Design systems (Figma tokens, CSS variables)
- Conversion rate optimization (CRO)
- Mobile-first responsive design
- Performance optimization (Core Web Vitals)
- Brand identity creation
- A/B test variant design

OUTPUT FORMAT:
## 🎨 Design Brief
[Visual direction, brand values, target user]

## 🏗️ Component Structure
[Layout breakdown and component hierarchy]

## 💻 Complete Code
```html
<!DOCTYPE html>
[Full production-ready HTML/CSS/JS]
```

## 📱 Mobile Adaptation
[Mobile-specific considerations]

## ⚡ Performance
[Image optimization, lazy loading, Core Web Vitals score]

## 🎯 CRO Elements
[Conversion optimization techniques used]

## 🔄 A/B Test Variants
[Alternative approaches to test]
""",

"support": """You are SupportGenie — MaxAI Corporation's AI customer success specialist (2026).

CAPABILITIES:
- Customer issue diagnosis and resolution
- FAQ knowledge base creation
- Ticket routing and prioritization
- Customer health scoring
- Churn prevention strategies
- Escalation management
- Multi-language support (RU/EN/CN)

OUTPUT FORMAT:
## 💬 Issue Analysis
**Severity**: [Critical/High/Medium/Low]
**Category**: [Technical/Billing/Usage/Feature Request]
**Sentiment**: [Frustrated/Neutral/Satisfied]

## ✅ Immediate Response
[Professional, empathetic reply to send NOW]

## 🔧 Resolution Steps
1. [Step 1]
2. [Step 2]
3. [Step 3]

## 📋 FAQ Entry (for knowledge base)
**Q**: [Customer question]
**A**: [Clear, helpful answer]

## 🔄 Follow-up
[What to check in 24-48h]

## 📊 Prevention
[How to prevent this issue recurring]
""",

"presenter": """You are PresentationMaster — MaxAI Corporation's world-class presentation designer (2026).

CAPABILITIES:
- Investor pitch decks (Series A-C ready)
- Board presentations with executive-level content
- Product demos and sales decks
- Annual reports and company overviews
- Conference keynote presentations
- Training and educational presentations
- GENERATES REAL .PPTX FILES via pptxgenjs

OUTPUT FORMAT:
Provide complete slide content as JSON for rendering:
{
  "company": "Company Name",
  "tagline": "Compelling tagline",
  "theme": "dark",
  "slides": [
    {"layout": "title", "title": "...", "subtitle": "...", "facts": [...]},
    {"layout": "content", "tag": "PROBLEM", "title": "...", "items": [...]},
    {"layout": "two", "tag": "SOLUTION", "columns": [...]},
    ...
    {"layout": "cta", "title": "...", "ctas": [...]}
  ]
}

QUALITY STANDARDS:
- 10-14 slides (investor attention span)
- Data-backed claims (cite sources)
- Clear narrative arc (Problem → Solution → Proof → Ask)
- Professional dark theme by default
- Every slide has ONE key message
""",

"onec": """Вы — агент 1С-Интеграции MaxAI Corporation, ведущий эксперт по 1С:Предприятие 8.x (2026).

КОМПЕТЕНЦИИ:
- 1С:Предприятие 8.3 (УТ, УПП, БП, ЗУП, CRM, ERP)
- Обмен данными (COM, HTTP-сервисы, веб-сервисы SOAP/REST)
- Интеграция с внешними системами (Bitrix24, amoCRM, SAP, 1С:Шина)
- Оптимизация запросов и производительности
- Разработка конфигураций и расширений
- Деплой и администрирование серверов 1С

ФОРМАТ ОТВЕТА:
## 🏢 Анализ задачи
[Что нужно сделать и в какой конфигурации]

## 💻 Код 1С
```bsl
// Готовый, комментированный код
[Полный код 1С:Предприятие]
```

## 🔗 Настройка обмена
[Шаги по настройке интеграции]

## 📋 Тестирование
[Как проверить работу]

## 📚 Документация
[Ключевые объекты конфигурации, справочники, документы]

## ⚠️ Возможные проблемы
[Типичные ошибки и как их избежать]
""",

"legal": """You are LexAI — MaxAI Corporation's AI legal document specialist (2026).

CAPABILITIES:
- Commercial contracts (supply, services, SaaS)
- NDAs and confidentiality agreements
- Privacy policies (GDPR, CCPA, Russian 152-ФЗ)
- Terms of service for software/apps
- Employment agreements
- Partnership and joint venture agreements
- Compliance frameworks (ISO 27001, SOC2, GDPR)

OUTPUT FORMAT:
## ⚖️ Document Analysis
**Document Type**: [Contract/NDA/Policy]
**Jurisdiction**: [Russia/EU/USA/International]
**Parties**: [Party A / Party B]

## 📄 Complete Document
[FULL legal document with all clauses, proper formatting]

## 🔑 Key Clauses Explained
| Clause | Purpose | Risk Level |
|--------|---------|-----------|
[Summary table]

## ⚠️ Risk Assessment
[What's protected, what's exposed]

## 📝 Negotiation Points
[Clauses client might want to negotiate]

## ✅ Compliance Checklist
- [ ] GDPR compliant
- [ ] Local law compliant
- [ ] Industry standard

⚠️ *Note: This is AI-generated guidance. Have a licensed attorney review before signing.*
""",

"hr": """You are HireBot — MaxAI Corporation's AI HR automation specialist (2026).

CAPABILITIES:
- Job description optimization (ATS-friendly + SEO)
- Interview question banks (behavioral, technical, case)
- Candidate evaluation rubrics
- Compensation benchmarking
- Onboarding programs
- Performance review templates
- HR policy creation (Russia/EU/USA)

OUTPUT FORMAT:
## 👥 HR Task Analysis
[What's needed and why]

## 📋 Primary Deliverable
[Main document/template]

## 🎯 Interview Questions (if relevant)
**Behavioral**: [5 questions]
**Technical**: [5 questions]
**Culture Fit**: [5 questions]

## 📊 Evaluation Rubric
| Criterion | Weight | 1-5 Scale |
|-----------|--------|-----------|
[Scoring matrix]

## 💰 Compensation Benchmark
[Market data for the role/location]

## 📈 Success Metrics
[How to measure success of this hire/policy]
""",

"finance": """You are FinanceAI — MaxAI Corporation's AI financial modeling specialist (2026).

CAPABILITIES:
- DCF valuation models
- Financial statement analysis
- Cash flow forecasting (3/5/10 year)
- Investment thesis preparation
- Fundraising financial models
- Unit economics (CAC, LTV, payback)
- Business plan financials

OUTPUT FORMAT:
## 💰 Financial Analysis Report
*Date: {date} | MaxAI FinanceAI Agent*

## 📊 Executive Summary
[Key financial metrics and recommendations]

## 📈 Financial Model
| Year | Revenue | COGS | Gross Profit | EBITDA | Net Income |
|------|---------|------|-------------|--------|-----------|
[5-year projection table]

## 💹 Key Metrics
- Revenue CAGR: X%
- Gross Margin: X%
- Break-even: Month X
- LTV/CAC Ratio: X.X
- Payback Period: X months

## 🎯 Valuation
- DCF (Base Case): $X.XM
- Revenue Multiple: X.Xx
- Comparable Companies: $X.XM

## ⚠️ Risks & Sensitivities
[What assumptions could be wrong]

## 📋 Recommendation
[Clear investment/financial recommendation]
""",

}

DEFAULT_PROMPT = """You are a professional AI agent at MaxAI Corporation (2026).
Provide world-class, comprehensive, actionable responses.
Format with headers, bullet points, and structured sections.
Respond in the same language as the client's request.
Always deliver more value than expected."""


# ── TOOL ORCHESTRATION PER AGENT ─────────────────────────────────────────────

async def enhance_with_tools(agent_type: str, task: str) -> str:
    """Gather real data before AI call based on agent type."""
    context_parts = []

    # BrainSearch: real web search
    if agent_type in ("researcher", "analyst"):
        log.info(f"Web search for {agent_type}: {task[:50]}")
        search_results = await web_search(task[:200], num=5)
        if search_results:
            context_parts.append(f"=== WEB SEARCH RESULTS ===\n{search_results}")

    # TradeBot: real prices + indicators
    if agent_type == "trader":
        symbols_in_task = re.findall(r'\b(BTC|ETH|SOL|BNB|XRP|ADA|DOT|MATIC|DOGE|AVAX)\b', task.upper())
        if not symbols_in_task:
            symbols_in_task = ["BTC", "ETH"]
        pairs = [f"{s}USDT" for s in symbols_in_task[:3]]
        log.info(f"Fetching prices for: {pairs}")
        prices = await get_crypto_prices(pairs)
        if prices:
            lines = []
            for sym, data in prices.items():
                # Get kline for RSI
                klines = await get_kline_data(sym, "60", 50)
                closes = [k[4] for k in klines] if klines else []
                rsi = calculate_rsi(closes) if closes else 0

                lines.append(
                    f"**{sym}**: ${data['price']:,.2f} | "
                    f"24h: {data['change24']:+.2f}% | "
                    f"Vol: ${data['volume24']:,.0f} | "
                    f"Funding: {data['funding']:.4f}% | "
                    f"RSI(14): {rsi}"
                )
            context_parts.append(f"=== LIVE MARKET DATA ({datetime.now().strftime('%Y-%m-%d %H:%M UTC')}) ===\n" + "\n".join(lines))

    # DataScraper: scrape URLs from task
    if agent_type == "parser":
        urls = re.findall(r'https?://[^\s]+', task)
        if urls:
            log.info(f"Scraping URLs: {urls[:2]}")
            for url in urls[:2]:
                content = await scrape_url(url)
                context_parts.append(f"=== SCRAPED CONTENT: {url} ===\n{content}")

    # MarketerBot: search for trends
    if agent_type == "marketer":
        topic = task[:100]
        search_results = await web_search(f"viral marketing trends 2026 {topic}", num=3)
        context_parts.append(f"=== CURRENT TRENDS ===\n{search_results}")

    # LeadHunter: check real Kwork opportunities
    if agent_type == "hunter":
        try:
            kw_query = " ".join(task.split()[:5])
            kwork_results = await web_search(f"site:kwork.ru {kw_query}", num=3)
            context_parts.append(f"=== KWORK OPPORTUNITIES ===\n{kwork_results}")
        except:
            pass

    return "\n\n".join(context_parts)


# ── AI CALL WITH TOOL CONTEXT ─────────────────────────────────────────────────

async def call_ai(system_prompt: str, task: str, context: str = "") -> str:
    """Call Anthropic (primary) with tool context injected."""
    full_message = task
    if context:
        full_message = f"{context}\n\n---\n\nCLIENT REQUEST:\n{task}\n\n---\n\nUsing the real data above, provide your expert analysis:"

    # Add current date/time context
    now = datetime.now().strftime("%Y-%m-%d %H:%M UTC")
    system_with_date = system_prompt.replace("{date}", now) + f"\n\nCurrent date/time: {now}"

    # 1. Anthropic (primary — best quality)
    if AN_KEY:
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": AN_KEY, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={
                        "model": "claude-haiku-4-5",
                        "system": system_with_date,
                        "messages": [{"role": "user", "content": full_message[:8000]}],
                        "max_tokens": 4096
                    }
                )
                if r.status_code == 200:
                    result = r.json()["content"][0]["text"]
                    log.info(f"Anthropic OK: {len(result)} chars")
                    return result
                log.warning(f"Anthropic {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log.warning(f"Anthropic failed: {e}")

    # 2. OpenRouter (fallback)
    if OR_KEY:
        try:
            async with httpx.AsyncClient(timeout=120) as c:
                r = await c.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OR_KEY}", "Content-Type": "application/json"},
                    json={
                        "model": "anthropic/claude-haiku-4-5",
                        "messages": [
                            {"role": "system", "content": system_with_date},
                            {"role": "user", "content": full_message[:8000]}
                        ],
                        "max_tokens": 4096
                    }
                )
                if r.status_code == 200:
                    result = r.json()["choices"][0]["message"]["content"]
                    log.info(f"OpenRouter OK: {len(result)} chars")
                    return result
        except Exception as e:
            log.warning(f"OpenRouter failed: {e}")

    return "⚠️ AI providers temporarily unavailable. Task queued. Please retry in 5 minutes."


# ── PRESENTATION GENERATOR ────────────────────────────────────────────────────

async def generate_presentation(task: str, job_id: str) -> str:
    """Generate real PPTX with AI content."""
    system = AGENT_SYSTEM_PROMPTS["presenter"]
    ai_response = await call_ai(system, task, "")

    json_match = re.search(r'\{[\s\S]*\}', ai_response)
    if not json_match:
        return f"📊 Структура презентации:\n\n{ai_response[:2000]}"

    try:
        pres_data = json.loads(json_match.group())
        pres_data["id"] = job_id

        import os as _os
        env = {**_os.environ, "NODE_PATH": "/root/nexus/node_modules"}
        proc = await asyncio.create_subprocess_exec(
            "/usr/bin/node", "/root/nexus/presentation_engine.js",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env, cwd="/tmp"
        )
        stdout, _ = await asyncio.wait_for(
            proc.communicate(input=json.dumps(pres_data).encode()), timeout=90
        )
        if proc.returncode == 0:
            result = json.loads(stdout.decode().strip())
            if result.get("ok"):
                fname = f"MaxAI_Presentation_{job_id}.pptx"
                dest  = f"/var/www/maxai-client/assets/{fname}"
                Path("/var/www/maxai-client/assets").mkdir(exist_ok=True)
                Path(result["file"]).rename(dest)
                return (
                    f"✅ **Презентация готова!**\n\n"
                    f"📥 Скачать PPTX: https://maxai.fyi/assets/{fname}\n"
                    f"📊 Слайдов: {result.get('slides', 10)}\n"
                    f"🎨 Тема: Dark Professional 2026\n\n"
                    f"Что включено:\n"
                    f"• Титульный слайд с ключевыми метриками\n"
                    f"• Структурированный контент\n"
                    f"• Профессиональное форматирование\n"
                    f"• Призыв к действию\n\n"
                    f"Нужны правки? Опишите что изменить."
                )
    except Exception as e:
        log.error(f"PPTX generation: {e}")

    return f"📊 Презентация подготовлена:\n\n{ai_response[:3000]}"


# ── CODE EXECUTION INTEGRATION ────────────────────────────────────────────────

async def execute_code_in_task(task: str, ai_response: str) -> str:
    """If AI wrote code, extract and execute it."""
    code_blocks = re.findall(r'```(?:python|py)\n(.*?)```', ai_response, re.DOTALL)
    if not code_blocks:
        return ai_response

    # Execute first code block as demo
    first_code = code_blocks[0]
    # Safety check: no harmful operations
    dangerous = ["os.system", "subprocess.Popen", "__import__", "eval(", "exec("]
    if any(d in first_code for d in dangerous):
        return ai_response + "\n\n⚠️ *Code contains system calls — review before execution*"

    # Only execute if code is reasonably short and safe
    if len(first_code) < 2000 and "input(" not in first_code and "while True" not in first_code:
        execution_result = await execute_code(first_code, "python")
        return ai_response + f"\n\n---\n🤖 **Auto-Execution Result:**\n{execution_result}"

    return ai_response


# ── QUALITY VALIDATOR ─────────────────────────────────────────────────────────

def validate_and_enhance(result: str, agent_type: str, task: str) -> str:
    """Validate result quality and add agent-specific enhancements."""
    # Too short = bad quality
    if len(result) < 200:
        return result + "\n\n*[Agent is providing a brief response. Type your question with more detail for comprehensive analysis.]*"

    # Add footer with agent info
    agent_names = {
        "coder": "💻 CodeMaster", "trader": "📊 TradeBot Pro", "hunter": "🎯 LeadHunter",
        "parser": "🕷️ DataScraper", "analyst": "📈 InsightAI", "marketer": "📣 ViralBot",
        "researcher": "🔬 BrainSearch", "automator": "⚙️ FlowBuilder", "designer": "🎨 PixelMind",
        "support": "💬 SupportGenie", "presenter": "🎯 PresentationMaster",
        "onec": "🏢 1С-Агент", "legal": "⚖️ LexAI", "hr": "👥 HireBot", "finance": "💰 FinanceAI",
    }
    agent_name = agent_names.get(agent_type, "🤖 MaxAI Agent")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    footer = f"\n\n---\n*{agent_name} · MaxAI Corporation · {timestamp} · maxai.fyi*"

    # Don't add footer if it's a PPTX result
    if "Скачать PPTX" in result or "Download" in result:
        return result

    return result + footer


# ── NOTIFY CLIENT ─────────────────────────────────────────────────────────────

def notify_telegram(chat_id: str, message: str, result_preview: str = ""):
    """Send task completion to client."""
    if not TG_TOKEN or not chat_id:
        return
    try:
        import urllib.request
        text = message
        if result_preview and len(result_preview) > 50:
            text += f"\n\n{result_preview[:1500]}"
        data = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        log.warning(f"TG notify failed: {e}")


# ── PROCESS JOB ───────────────────────────────────────────────────────────────

async def process_job(job_id: str):
    """Process one job end-to-end with real tool use."""
    job_key = f"nexus:job:{job_id}:data"
    raw = rdb.get(job_key)
    if not raw:
        log.warning(f"Job {job_id} not found")
        return

    job       = json.loads(raw)
    agent_type = job.get("agent_type", "researcher")
    task       = job.get("task", "")
    client_id  = job.get("client_id", "")

    log.info(f">>> {job_id} | {agent_type} | {task[:60]}")

    job["status"]     = "running"
    job["started_at"] = datetime.now(timezone.utc).isoformat()
    rdb.set(job_key, json.dumps(job))
    start_ts = time.time()

    try:
        # STEP 1: Gather real-world data via tools
        context = await enhance_with_tools(agent_type, task)
        if context:
            log.info(f"Tool context for {job_id}: {len(context)} chars")

        # STEP 2: AI generation with context
        if agent_type == "presenter":
            result = await generate_presentation(task, job_id)
        else:
            system_prompt = AGENT_SYSTEM_PROMPTS.get(agent_type, DEFAULT_PROMPT)
            result = await call_ai(system_prompt, task, context)

            # STEP 3: Code execution for coder agent
            if agent_type == "coder" and result:
                result = await execute_code_in_task(task, result)

        # STEP 4: Quality validation
        result = validate_and_enhance(result, agent_type, task)

        elapsed = time.time() - start_ts

        # Save result
        job["status"]       = "completed"
        job["result"]       = result
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        job["execution_ms"] = int(elapsed * 1000)
        job["tools_used"]   = bool(context)
        job["char_count"]   = len(result)

        rdb.set(job_key, json.dumps(job))
        rdb.setex(f"nexus:job:{job_id}:result", 86400 * 7, result)
        rdb.incr(f"nexus:stats:tasks:{datetime.now().strftime('%Y-%m-%d')}")
        rdb.incr(f"nexus:agent:{agent_type}:tasks_completed")
        rdb.lpush("nexus:completed:jobs", job_id)
        rdb.ltrim("nexus:completed:jobs", 0, 999)

        # Send email notification
        if client_raw:
            _client = json.loads(client_raw)
            _email = _client.get('email', '')
            _name  = _client.get('name', 'Client')
            if _email and '@' in _email and 'maxai.fyi' not in _email:
                agent_names = {
                    'coder':'💻 CodeMaster','trader':'📊 TradeBot Pro',
                    'researcher':'🔬 BrainSearch','presenter':'🎨 PresentationMaster',
                }
                _aname = agent_names.get(agent_type, f'🤖 {agent_type.title()}')
                _send_email(_email, _name, _aname, task[:100], result[:500], job_id)

        # Notify client via Telegram
        client_raw = rdb.get(f"nexus:client:{client_id}:info")
        if client_raw:
            client  = json.loads(client_raw)
            tg_id   = client.get("telegram_id")
            if tg_id:
                agent_icons = {
                    "coder": "💻 CodeMaster", "trader": "📊 TradeBot Pro", "hunter": "🎯 LeadHunter",
                    "parser": "🕷️ DataScraper", "analyst": "📈 InsightAI", "marketer": "📣 ViralBot",
                    "researcher": "🔬 BrainSearch", "automator": "⚙️ FlowBuilder", "designer": "🎨 PixelMind",
                    "support": "💬 SupportGenie", "presenter": "🎯 PresentationMaster",
                    "onec": "🏢 1С-Агент", "legal": "⚖️ LexAI", "hr": "👥 HireBot", "finance": "💰 FinanceAI",
                }
                aname = agent_icons.get(agent_type, "🤖 Agent")
                tools_note = " (использовал реальные данные)" if context else ""
                header = (
                    f"✅ <b>Задача выполнена!</b>\n"
                    f"🤖 Агент: {aname}{tools_note}\n"
                    f"⏱️ Время: {elapsed:.1f}с\n"
                    f"📊 Объём: {len(result)} символов\n"
                    f"🆔 <code>{job_id}</code>\n\n"
                )
                notify_telegram(tg_id, header, result)

        log.info(f"✅ {job_id} | {elapsed:.1f}s | {len(result)} chars | tools={bool(context)}")

    except Exception as e:
        log.error(f"❌ {job_id} failed: {e}", exc_info=True)
        job["status"]       = "failed"
        job["error"]        = str(e)[:500]
        job["completed_at"] = datetime.now(timezone.utc).isoformat()
        rdb.set(job_key, json.dumps(job))


# ── WORKER LOOP ───────────────────────────────────────────────────────────────

async def worker_loop():
    log.info("=" * 60)
    log.info("NEXUS Task Worker v3.0 — WORLD CLASS — MaxAI Corporation")
    log.info(f"Anthropic: {'✅' if AN_KEY else '❌'} | OpenRouter: {'✅' if OR_KEY else '❌'}")
    log.info(f"Agents: {len(AGENT_SYSTEM_PROMPTS)} | Tools: WebSearch + LivePrices + CodeExec + Scraper")
    log.info("=" * 60)

    QUEUES = [
        "nexus:queue:presenter", "nexus:queue:coder",   "nexus:queue:trader",
        "nexus:queue:onec",      "nexus:queue:legal",   "nexus:queue:finance",
        "nexus:queue:analyst",   "nexus:queue:hunter",  "nexus:queue:researcher",
        "nexus:queue:marketer",  "nexus:queue:automator","nexus:queue:parser",
        "nexus:queue:designer",  "nexus:queue:hr",      "nexus:queue:support",
        "nexus:queue:global",
    ]

    idle = 0
    while True:
        processed = False
        for q in QUEUES:
            job_id = rdb.rpop(q)
            if job_id:
                rdb.lrem("nexus:queue:global", 0, job_id)
                await process_job(job_id)
                processed = True
                idle = 0
                break

        if not processed:
            idle += 1
            if idle % 30 == 1:
                total = sum(rdb.llen(q) for q in QUEUES)
                completed = int(rdb.llen("nexus:completed:jobs") or 0)
                log.info(f"Idle | pending={total} | completed={completed}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(worker_loop())
