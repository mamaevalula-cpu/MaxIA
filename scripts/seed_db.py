import psycopg2, json
conn = psycopg2.connect('postgresql://postgres:hyperion_v12_pass@127.0.0.1/hyperion_v12')
cur = conn.cursor()

# Add missing departments
for d in [('maxai-trading','MaxAI Trading','USD'),('maxai-marketing','MaxAI Marketing','USD'),('maxai-analytics','MaxAI Analytics','USD')]:
    cur.execute("INSERT INTO departments(department_id,name,base_currency,is_active) VALUES(%s,%s,%s,true) ON CONFLICT(department_id) DO NOTHING", d)

# Add missing markets (correct schema: market_id, language_code, local_currency, compliance_ruleset)
new_markets = [
    ('EN','en','USD','{"gdpr":false,"data_retention_days":365}'),
    ('GLOBAL','en','USD','{"gdpr":false,"data_retention_days":365}'),
    ('KZ','ru','KZT','{"gdpr":false,"data_retention_days":365}'),
]
for m in new_markets:
    cur.execute("INSERT INTO markets(market_id,language_code,local_currency,compliance_ruleset) VALUES(%s,%s,%s,%s::jsonb) ON CONFLICT(market_id) DO NOTHING", m)

conn.commit()
print("Departments+Markets OK")

# Use only existing market_ids: RU, US, EU, EN, GLOBAL
caps = [
    ('telegram-bot-dev-v1','maxai-dev','RU','Telegram Bot Dev','Build Telegram bots commands keyboards payments AI responses aiogram'),
    ('trading-bot-dev-v1','maxai-trading','RU','Trading Bot Dev','Grid DCA Momentum bots Bybit Binance 24/7 automation'),
    ('parser-scraper-v1','maxai-dev','RU','Web Parser Scraper','Selenium Playwright BeautifulSoup API scraping automation'),
    ('fastapi-backend-v1','maxai-dev','RU','FastAPI Backend','REST APIs auth JWT PostgreSQL Docker VPS deployment'),
    ('llm-chatbot-v1','maxai-dev','RU','LLM Chatbot','GPT Claude Groq RAG embeddings knowledge base chatbot integration'),
    ('seo-content-v1','maxai-marketing','RU','SEO Content Writing','Articles blog posts keyword optimization copywriting SEO'),
    ('smm-posting-v1','maxai-marketing','RU','Social Media SMM','Telegram VK Instagram content creation scheduled posting SMM'),
    ('email-outreach-v1','maxai-sales','RU','Email Outreach B2B','Cold email lead generation follow-up sequences CRM B2B'),
    ('freelance-bidding-v1','maxai-sales','RU','Freelance Bidding','kwork fl.ru habr.freelance automated proposals bidding'),
    ('data-analytics-v1','maxai-analytics','RU','Business Analytics','Data analysis dashboards sales reports forecasting pandas'),
    ('yandex-ads-v1','maxai-marketing','RU','Yandex Direct VK Ads','Ad creation targeting optimization A/B conversion tracking'),
    ('support-bot-v1','maxai-dev','RU','AI Support Bot','24/7 customer support Telegram chat FAQ automation bot'),
    ('crypto-monitor-v1','maxai-trading','GLOBAL','Crypto Monitor','Price alerts portfolio tracking signals Bybit Binance Telegram'),
    ('fiverr-upwork-v1','maxai-sales','EN','Intl Freelance','Fiverr Upwork PeoplePerHour automated English market proposals'),
    ('fullstack-webapp-v1','maxai-dev','EN','Full Stack WebApp','React FastAPI PostgreSQL Docker Nginx VPS full deployment webapp'),
]

sql = ("INSERT INTO capabilities(capability_id,department_id,market_id,version,status,"
       "input_schema,output_schema,execution_graph,tool_permissions,"
       "latency_budget_ms,cost_budget,success_threshold,retirement_threshold) "
       "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
       "ON CONFLICT(capability_id) DO UPDATE SET "
       "department_id=EXCLUDED.department_id,status=EXCLUDED.status,updated_at=NOW()")

for c in caps:
    cur.execute(sql, (c[0],c[1],c[2],'1.0','STABLE',
                json.dumps({'desc':c[4],'name':c[3]}),'{}','{}','[]',
                10000,1.0,0.90,0.70))
conn.commit()
print("Capabilities inserted")

pats = [
    ('telegram_bot_quick','maxai-dev','RU','telegram-bot-dev-v1','{"t":"bot"}','{"h":4,"steps":4}',0.95),
    ('trading_grid_bybit','maxai-trading','RU','trading-bot-dev-v1','{"t":"grid"}','{"profit_pct":0.5}',0.90),
    ('parser_selenium','maxai-dev','RU','parser-scraper-v1','{"t":"parse"}','{"h":3}',0.92),
    ('fastapi_crud','maxai-dev','RU','fastapi-backend-v1','{"t":"api"}','{"h":8}',0.88),
    ('llm_rag_chatbot','maxai-dev','RU','llm-chatbot-v1','{"t":"rag"}','{"h":6}',0.91),
    ('kwork_bid_win','maxai-sales','RU','freelance-bidding-v1','{"p":"kwork"}','{"win_rate":0.15}',0.85),
    ('email_b2b_cold','maxai-sales','RU','email-outreach-v1','{"t":"smb"}','{"open_rate":0.22}',0.80),
]

sql2 = ("INSERT INTO pattern_memory(pattern_id,department_id,market_id,capability_id,"
        "input_signature,output_template,quality_score,usage_count,last_used_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,0,NOW()) "
        "ON CONFLICT(pattern_id) DO UPDATE SET quality_score=EXCLUDED.quality_score")

for p in pats:
    cur.execute(sql2, p)
conn.commit()

cur.execute('SELECT count(*) FROM capabilities')
print('Total capabilities:', cur.fetchone()[0])
cur.execute('SELECT count(*) FROM pattern_memory')
print('Total patterns:', cur.fetchone()[0])
cur.execute('SELECT capability_id, department_id FROM capabilities ORDER BY created_at')
for row in cur.fetchall():
    print(f'  {row[0]} [{row[1]}]')
conn.close()
print('SEED DONE')
