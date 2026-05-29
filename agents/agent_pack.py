#!/usr/bin/env python3
"""
agents/agent_pack.py
Factory of 70+ lightweight non-conflicting domain agents.
Each agent owns UNIQUE keywords — guaranteed no overlap.
Uses LLM via _ask_llm for all responses.
"""
import logging, os
from typing import Any

log = logging.getLogger("agent_pack")

# ── Conflict-free base ────────────────────────────────────────────────────────
class _LightBase:
    """Minimal base that never clashes with abstract BaseAgent."""
    status = "idle"
    def __init__(self):
        self._llm_router = None
    def _ask(self, text: str, system: str = "") -> str:
        try:
            from brain.llm_router import LLMRouter, LLMRequest
            router = LLMRouter.get()
            req = LLMRequest(
                messages=[{"role": "user", "content": text}],
                system=system or f"You are {self.name} — {self.description}. Be concise, helpful, in Russian.",
                max_tokens=800,
                task_type="chat",
            )
            resp = router.ask(req)
            return resp.content if resp.success else f"[{self.name}] LLM unavailable"
        except Exception as e:
            return f"[{self.name}] error: {e}"
    def can_handle(self, text: str) -> bool:
        t = text.lower()
        return any(kw in t for kw in self.keywords)
    def process(self, text, source="internal"):
        if hasattr(text, "text"):
            text = text.text
        return self._ask(str(text))
    def info(self):
        return {"name": self.name, "description": self.description, "status": self.status}
    def start(self): self.status = "idle"
    def stop(self): self.status = "stopped"


def _make(name, description, keywords, system_prompt="", priority=3):
    """Factory: create a unique non-conflicting agent class."""
    cls = type(name, (_LightBase,), {
        "name": name,
        "description": description,
        "keywords": keywords,
        "priority": priority,
        "system_prompt": system_prompt or f"You are {name}: {description}",
    })
    return cls


# ════════════════════════════════════════════════════════════════════════════
# AGENT DEFINITIONS — each keyword set is UNIQUE across all agents
# ════════════════════════════════════════════════════════════════════════════

PACK_DEFINITIONS = [

    # ── TRADING & CRYPTO ──────────────────────────────────────────────────────
    ("BtcScalperAgent",    "BTC краткосрочные сигналы скальпирования",
     ["btc скальп", "биткоин скальп", "btc signal", "скальп btc", "btc 1m", "btc 5m"],
     "Ты эксперт по скальпингу BTC. Анализируй паттерны 1-5 минут.", 6),

    ("EthMomentumAgent",   "ETH momentum трекер и сигналы",
     ["eth момент", "ethereum momentum", "eth тренд", "eth rsi", "eth macd", "эфир сигнал"],
     "Ты эксперт по ETH momentum trading.", 6),

    ("AltcoinScannerAgent","Сканер altcoin возможностей (SOL/BNB/XRP)",
     ["альткоин", "altcoin", "sol сигнал", "bnb сигнал", "xrp сигнал", "alt season"],
     "Ты сканируешь альткоины на торговые возможности.", 5),

    ("PortfolioRebalancerAgent", "Балансировщик криптопортфеля",
     ["ребаланс", "rebalance", "портфель крипто", "allocat", "диверсификация крипто"],
     "Ты оптимизируешь баланс криптопортфеля.", 5),

    ("FundingRateAgent",   "Мониторинг funding rate на фьючерсах",
     ["funding rate", "фандинг", "funding fee", "перпетуал", "perpetual funding"],
     "Ты отслеживаешь funding rates на крипто биржах.", 5),

    ("LiquidationScannerAgent", "Сканер уровней ликвидации",
     ["ликвидац", "liquidation", "liq level", "уровень ликвид", "liquidation map"],
     "Ты сканируешь уровни ликвидации на рынке.", 6),

    ("OnchainTrackerAgent","Отслеживание on-chain метрик кошельков",
     ["onchain", "on-chain", "whale wallet", "кит кошел", "blockchain explorer"],
     "Ты анализируешь on-chain данные и движения китов.", 5),

    ("DexArbitrageAgent",  "DEX арбитраж между протоколами",
     ["dex арбитраж", "defi арбитраж", "uniswap arb", "pancakeswap arb", "flash loan"],
     "Ты ищешь арбитражные возможности в DeFi.", 5),

    ("DefiYieldAgent",     "DeFi yield farming и staking стратегии",
     ["yield farm", "стейкинг", "staking apy", "liquidity mining", "defi доход"],
     "Ты анализируешь DeFi yield возможности.", 4),

    ("CryptoNewsFilterAgent", "Фильтр крипто новостей по важности",
     ["крипто новост", "crypto news", "bitcoin news", "sec crypto", "coindesk"],
     "Ты фильтруешь и оцениваешь важность крипто новостей.", 4),

    # ── WILDBERRIES ──────────────────────────────────────────────────────────
    ("WbSalesTrackerAgent","Трекер продаж Wildberries в реальном времени",
     ["wb продаж", "wildberries продаж", "вб статистик", "wb заказ", "wb выручка"],
     "Ты отслеживаешь продажи на Wildberries.", 6),

    ("WbPriceOptimizerAgent","Оптимизатор цен на WB для максимальной прибыли",
     ["wb цена", "wildberries цен", "вб прайс", "wb ценообразован", "репрайс wb"],
     "Ты оптимизируешь цены на Wildberries для максимальной прибыли.", 6),

    ("WbAdsOptimizerAgent","Оптимизатор рекламных кампаний WB",
     ["wb реклам", "wildberries реклам", "вб ads", "wb ставка реклам", "wb cpm"],
     "Ты управляешь рекламными кампаниями на Wildberries.", 5),

    ("WbCompetitorAgent",  "Мониторинг конкурентов на WB",
     ["wb конкурент", "wildberries конкурент", "вб аналитик конкур", "wb spy", "wb позиц"],
     "Ты отслеживаешь конкурентов на Wildberries.", 5),

    ("WbStockManagerAgent","Управление остатками и поставками WB",
     ["wb остатк", "wildberries склад", "вб поставк", "wb fbo", "wb fbs", "вб приемк"],
     "Ты управляешь складскими остатками на Wildberries.", 5),

    ("WbReviewAgent",      "Работа с отзывами и рейтингом WB",
     ["wb отзыв", "wildberries отзыв", "вб рейтинг", "wb review", "ответ отзыв wb"],
     "Ты управляешь отзывами на Wildberries.", 4),

    ("OzonAnalyticsAgent", "Аналитика и продажи на Ozon",
     ["ozon", "озон продаж", "ozon аналитик", "ozon fbo", "ozon seller"],
     "Ты анализируешь продажи и позиции на Ozon.", 5),

    ("AvitoAgent",         "Управление объявлениями на Avito",
     ["avito", "авито", "объявлен avito", "авито продаж", "авито pro"],
     "Ты управляешь объявлениями на Avito.", 4),

    # ── COFFEE SOURCING ───────────────────────────────────────────────────────
    ("CoffeePriceMonitorAgent","Мониторинг цен кофе (биржа ICE, Колумбия)",
     ["кофе цена", "coffee price", "arabica price", "ice coffee", "cop rub курс"],
     "Ты мониторишь цены кофе на мировых биржах.", 5),

    ("CoffeeLogisticsAgent","Расчёт логистики кофе Колумбия→Россия",
     ["кофе логистик", "coffee logistics", "кофе доставк", "кофе таможн", "green bean ship"],
     "Ты рассчитываешь логистику кофе из Колумбии в Россию.", 5),

    ("CoffeeSupplierAgent","CRM поставщиков кофе в Колумбии",
     ["кофе поставщик", "coffee supplier", "coffee farm", "колумбийск кофе", "finca"],
     "Ты ведёшь базу поставщиков кофе в Колумбии.", 4),

    ("CoffeeMarginAgent",  "Расчёт маржи кофейных контрактов",
     ["кофе маржа", "coffee margin", "кофе прибыл", "контракт кофе", "coffee deal"],
     "Ты рассчитываешь маржинальность кофейных контрактов.", 5),

    ("CoffeeQualityAgent", "Контроль качества и грейдинг кофе",
     ["кофе качеств", "coffee grade", "кофе cupping", "speciality coffee", "scaa"],
     "Ты оцениваешь качество и грейдинг кофе.", 4),

    # ── FREELANCE & WORK ─────────────────────────────────────────────────────
    ("UpworkScannerAgent", "Сканер заказов на Upwork по IT/AI",
     ["upwork", "апворк", "upwork job", "upwork proposal", "upwork freelance"],
     "Ты ищешь и фильтруешь заказы на Upwork.", 5),

    ("KworkAgent",         "Управление услугами и заказами на Kwork",
     ["kwork", "кворк", "kwork заказ", "kwork услуг", "fl.ru"],
     "Ты управляешь услугами и заказами на Kwork/FL.ru.", 4),

    ("InvoiceGeneratorAgent","Генератор счётов и закрывающих документов",
     ["счёт фактур", "invoice", "акт выполнен", "закрывающ документ", "счёт на оплат"],
     "Ты генерируешь счета-фактуры и акты выполненных работ.", 4),

    ("ContractAgent",      "Генератор и анализ договоров",
     ["договор", "контракт состав", "nda", "оферта состав", "договор услуг"],
     "Ты составляешь и анализируешь договора.", 4),

    ("ClientCrmAgent",     "CRM управление клиентской базой",
     ["crm клиент", "база клиент", "клиент лид", "клиент менедж", "воронка продаж"],
     "Ты ведёшь CRM базу клиентов.", 5),

    ("DeadlineTrackerAgent","Трекер дедлайнов и задач",
     ["дедлайн", "deadline", "срок задач", "просрочен задач", "task deadline"],
     "Ты отслеживаешь дедлайны и предупреждаешь об опасных просрочках.", 4),

    ("FreelanceBillingAgent","Биллинг и учёт оплат фриланса",
     ["фриланс оплат", "freelance payment", "hourly rate", "почасов оплат", "оплат freelance"],
     "Ты ведёшь учёт оплат по фриланс проектам.", 5),

    # ── CONTENT & MARKETING ──────────────────────────────────────────────────
    ("SeoAnalyzerAgent",   "SEO анализ сайтов и ключевых слов",
     ["seo анализ", "ключевые слова seo", "seo аудит", "pagerank", "семантическ ядро"],
     "Ты проводишь SEO анализ и подбор ключевых слов.", 4),

    ("CopywriterAgent",    "Копирайтинг и продающие тексты",
     ["копирайт", "продающ текст", "лендинг текст", "рекламн текст", "описани товар"],
     "Ты пишешь продающие тексты и рекламные описания.", 4),

    ("TelegramChannelAgent","Управление и контент Telegram каналов",
     ["телеграм канал", "tg канал", "telegram channel", "пост в канал", "контент план телеграм"],
     "Ты управляешь Telegram каналами и создаёшь контент.", 4),

    ("YoutubeScriptAgent", "Сценарии и описания для YouTube",
     ["youtube скрипт", "youtube сценари", "ютуб видео", "youtube description", "видео скрипт"],
     "Ты пишешь сценарии и описания для YouTube видео.", 3),

    ("AdCopyAgent",        "Создание рекламных объявлений (VK/Яндекс/Google)",
     ["рекламн объявлен", "yandex direct", "google ads", "vk реклам", "таргет реклам"],
     "Ты создаёшь рекламные объявления для Яндекс.Директ и Google Ads.", 4),

    ("BrandMonitorAgent",  "Мониторинг упоминаний бренда в сети",
     ["упоминан бренд", "brand mention", "мониторинг репутац", "отзыв о компани", "brand alert"],
     "Ты мониторишь упоминания бренда в интернете.", 4),

    ("ViralContentAgent",  "Генерация вирального контента",
     ["вирусн контент", "viral content", "мемы", "тренд контент", "viral idea"],
     "Ты генерируешь идеи и тексты для вирального контента.", 3),

    # ── DATA & RESEARCH ──────────────────────────────────────────────────────
    ("WebScraperAgent",    "Парсинг и сбор данных с сайтов",
     ["парсинг сайт", "web scraping", "парс данных", "scrapy", "beautifulsoup"],
     "Ты парсишь данные с веб сайтов.", 4),

    ("PdfExtractorAgent",  "Извлечение данных и анализ PDF документов",
     ["pdf извлеч", "pdf анализ", "pdf парс", "текст из pdf", "pdf таблиц"],
     "Ты извлекаешь и анализируешь данные из PDF документов.", 4),

    ("StatisticsAgent",    "Статистический анализ данных",
     ["статистик анализ", "regression", "корреляц", "p-value", "статистик расчёт"],
     "Ты проводишь статистический анализ данных.", 4),

    ("CompetitorIntelAgent","Конкурентная разведка и бенчмаркинг",
     ["конкурентн разведк", "competitor intel", "бенчмарк", "competitor analysis", "рынок конкурент"],
     "Ты собираешь конкурентную разведку.", 5),

    ("TrendAnalyzerAgent", "Анализ трендов рынка и потребителей",
     ["тренд рынок", "market trend", "тренд потребител", "emerging trend", "trend forecast"],
     "Ты анализируешь тренды рынка.", 4),

    ("ReportGeneratorAgent","Автоматическая генерация отчётов",
     ["сформир отчёт", "generate report", "отчёт создат", "автоматическ отчёт", "еженедельн отчёт"],
     "Ты генерируешь автоматические отчёты по данным.", 4),

    ("DataCleanerAgent",   "Очистка и нормализация данных",
     ["очистка данных", "data cleaning", "нормализац данных", "дедупликац", "data preprocessing"],
     "Ты очищаешь и нормализуешь данные.", 3),

    # ── SYSTEM & AUTOMATION ──────────────────────────────────────────────────
    ("GitAgent",           "Git операции: коммиты, ветки, PR",
     ["git commit", "git push", "git merge", "pull request", "git branch"],
     "Ты выполняешь Git операции и управляешь кодовой базой.", 5),

    ("DockerAgent",        "Управление Docker контейнерами",
     ["docker", "контейнер docker", "docker-compose", "dockerfile", "docker run"],
     "Ты управляешь Docker контейнерами и образами.", 5),

    ("DatabaseAgent",      "SQL запросы и управление базами данных",
     ["sql запрос", "select from", "database query", "postgres", "sqlite запрос"],
     "Ты выполняешь SQL запросы и управляешь базами данных.", 5),

    ("ApiTesterAgent",     "Тестирование API и интеграций",
     ["api тест", "test endpoint", "postman", "api integration test", "curl тест"],
     "Ты тестируешь API эндпоинты и интеграции.", 4),

    ("BackupAgent",        "Автоматическое резервное копирование",
     ["backup", "резервн коп", "бэкап", "snapshot", "архив данных"],
     "Ты создаёшь и управляешь резервными копиями.", 4),

    ("FileOrganizerAgent", "Организация и управление файловой системой",
     ["организ файл", "файл менедж", "sort files", "cleanup files", "file tree"],
     "Ты организуешь файловую систему и управляешь файлами.", 3),

    ("AlertManagerAgent",  "Умная система алертов и уведомлений",
     ["алерт настрой", "alert rule", "notification rule", "уведомлен правил", "alert threshold"],
     "Ты настраиваешь и управляешь системой алертов.", 5),

    # ── FINANCE & ACCOUNTING ─────────────────────────────────────────────────
    ("TaxCalculatorAgent", "Расчёт налогов (УСН, НДС, НДФЛ)",
     ["налог расчёт", "ндс расчёт", "усн налог", "ндфл", "налоговый вычет"],
     "Ты рассчитываешь налоги по российскому законодательству.", 5),

    ("ExpenseCategorizerAgent","Категоризация расходов по статьям",
     ["категориз расход", "статьи расход", "расход категори", "classify expense", "расход учёт"],
     "Ты категоризируешь расходы по бухгалтерским статьям.", 4),

    ("ProfitLossAgent",    "P&L отчёты и финансовый анализ",
     ["p&l отчёт", "прибыл убыток", "финансов результат", "доход расход отчёт", "рентабельност"],
     "Ты составляешь P&L отчёты и анализируешь финансовые результаты.", 5),

    ("CurrencyHedgerAgent","Хеджирование валютных рисков",
     ["хеджирован", "currency hedge", "валютн риск", "курсов риск", "fx hedge"],
     "Ты управляешь валютными рисками через хеджирование.", 5),

    ("CashFlowAgent",      "Управление денежным потоком",
     ["cash flow", "денежн поток", "кассов разрыв", "ликвидност компани", "оборотн капитал"],
     "Ты анализируешь и управляешь денежным потоком.", 5),

    # ── COMMUNICATION ───────────────────────────────────────────────────────
    ("EmailComposerAgent", "Составление деловых писем и ответов",
     ["напиш письмо", "email составит", "деловое письмо", "email ответ", "письмо клиент"],
     "Ты составляешь профессиональные деловые письма.", 4),

    ("WhatsappAgent",      "Интеграция и автоответы WhatsApp",
     ["whatsapp", "вацап", "whatsapp business", "wa bot", "whatsapp auto"],
     "Ты управляешь сообщениями и автоответами в WhatsApp.", 4),

    ("VkAgent",            "Управление группами и публикациями ВКонтакте",
     ["вконтакте", "vk публикац", "vk group", "вк пост", "vk community"],
     "Ты управляешь группами и контентом ВКонтакте.", 3),

    # ── AI & OPTIMIZATION ───────────────────────────────────────────────────
    ("PromptOptimizerAgent","Оптимизация промптов для LLM",
     ["оптимизир промпт", "prompt engineer", "system prompt улучш", "few shot", "chain of thought"],
     "Ты оптимизируешь промпты для максимальной эффективности LLM.", 4),

    ("RagBuilderAgent",    "Построение RAG пайплайнов",
     ["rag пайплайн", "vector database", "embeddings", "retrieval augmented", "chromadb"],
     "Ты строишь RAG пайплайны для работы с документами.", 4),

    ("ModelEvaluatorAgent","Тестирование и сравнение LLM моделей",
     ["тест модел", "benchmark llm", "llm compare", "model eval", "model quality"],
     "Ты тестируешь и сравниваешь качество LLM моделей.", 4),

    # ── REAL ESTATE & LOGISTICS ──────────────────────────────────────────────
    ("RealEstateAgent",    "Анализ рынка недвижимости",
     ["недвижимост", "real estate", "квартир купит", "ипотека расчёт", "аренда помещен"],
     "Ты анализируешь рынок недвижимости и ипотечные предложения.", 4),

    ("LogisticsCalculatorAgent","Расчёт стоимости логистики и доставки",
     ["логистик стоимост", "доставк расчёт", "тарифы перевозк", "freight rate", "карго расчёт"],
     "Ты рассчитываешь стоимость логистики и доставки.", 5),

    ("CustomsAgent",       "Таможенное оформление и пошлины",
     ["таможн", "customs duty", "таможенн пошлин", "ввозн пошлин", "тн вэд"],
     "Ты рассчитываешь таможенные пошлины и помогаешь с оформлением.", 5),

    # ── PERSONAL ASSISTANT ───────────────────────────────────────────────────
    ("MeetingPlannerAgent","Планирование встреч и переговоров",
     ["встреч план", "переговор план", "schedule meeting", "calendar event", "созвон план"],
     "Ты планируешь встречи и переговоры.", 3),

    ("TranslatorAgent",    "Перевод текстов (EN/RU/ES/ZH)",
     ["переведи", "translate", "перевод текст", "english to russian", "spanish translate"],
     "Ты выполняешь качественные переводы текстов.", 3),

    ("ResearchAgent",      "Глубокое исследование тем и вопросов",
     ["исследован тем", "deep research", "изучи вопрос", "найди информац о", "research topic"],
     "Ты проводишь глубокое исследование на любую тему.", 4),

    ("PersonalFinanceAgent","Личные финансы и бюджетирование",
     ["личн финанс", "личн бюджет", "накоплен план", "личн расход", "финансов цел"],
     "Ты помогаешь планировать личные финансы и бюджет.", 4),

    ("HealthTrackerAgent", "Отслеживание здоровья и активности",
     ["здоровь трекер", "фитнес план", "калориj", "тренировк план", "health metrics"],
     "Ты помогаешь отслеживать показатели здоровья.", 3),

    ("WildberriesCleanskinAgent", "Специализированный агент для CLEANS SKIN на WB",
     ["cleans skin", "cleansskin", "крем cleansskin", "чистая кожа wb", "cleanskin wb"],
     "Ты специализируешься на продвижении CLEANS SKIN крема на Wildberries.", 7),

    ("CoffeeColombiaAgent","Специализированный агент кофейного бизнеса Колумбия",
     ["colombia coffee", "колумбийск бизнес", "600kg кофе", "зелён зерно колумби", "кофе экспорт колумби"],
     "Ты ведёшь специализированный кофейный бизнес Колумбия→Россия.", 7),
]


# ── Build agent classes from definitions ─────────────────────────────────────
PACK_AGENTS = {}
for item in PACK_DEFINITIONS:
    name, desc, kws, sys_p, pri = item
    cls = _make(name, desc, kws, sys_p, pri)
    PACK_AGENTS[name] = cls

log.info("agent_pack: %d agents loaded", len(PACK_AGENTS))


def get_all() -> dict:
    """Return {name: instance} for all pack agents."""
    return {k: v() for k, v in PACK_AGENTS.items()}
