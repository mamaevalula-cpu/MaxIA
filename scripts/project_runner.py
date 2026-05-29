#!/usr/bin/env python3
"""
project_runner.py — runs every 30 min via cron.
Dispatches project tasks by hour to /api/chat.
Projects: trading, market, freelance, wb, reports, coffee, funding, signals, marketplace.
"""
import json, time, urllib.request, sqlite3, os, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = '/root/my_personal_ai'
API  = 'http://localhost:8000'


def chat(text, session='project_runner'):
    try:
        req = urllib.request.Request(
            API + '/api/chat',
            data=json.dumps({'text': text, 'session_id': session}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=90) as r:
            d = json.loads(r.read())
            return d.get('response', d.get('text', ''))[:400]
    except Exception as e:
        return f'ERROR: {e}'


def update_project_progress(name_like: str, delta: float, task_name: str,
                             task_status: str = 'completed'):
    """Update project progress in SQLite DB after each successful run."""
    try:
        db_path = os.path.join(BASE, 'data/projects.db')
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT progress, tasks, config FROM projects WHERE name LIKE ?",
            (f'%{name_like}%',)).fetchone()
        if not row:
            conn.close()
            return
        old_progress = float(row[0] or 0)
        new_progress  = min(100.0, old_progress + delta)

        # Update task status inside tasks JSON
        tasks = json.loads(row[1]) if row[1] else []
        for t in tasks:
            if t.get('name', '') == task_name or task_name in t.get('name', ''):
                t['status']   = task_status
                t['progress'] = 100 if task_status == 'completed' else 50
                t['updated_at'] = time.time()

        # Update last_check in config
        cfg = json.loads(row[2]) if row[2] else {}
        cfg['last_check'] = time.time()

        conn.execute(
            "UPDATE projects SET progress=?, tasks=?, config=?, updated_at=? "
            "WHERE name LIKE ?",
            (new_progress, json.dumps(tasks, ensure_ascii=False),
             json.dumps(cfg, ensure_ascii=False), time.time(), f'%{name_like}%'))
        conn.commit()
        conn.close()
        print(f'  DB updated: {name_like} progress={new_progress:.1f}%')
    except Exception as e:
        print(f'  DB update error: {e}')


# ─────────────────────────────────────────────────────────────────
hour = time.localtime().tm_hour

project_tasks = {
    # ── Trading / Finance ──────────────────────────────────────────
    0:  ('trading_runner',   'Bybit Earn: реинвестируй накопленные проценты USDT'),
    12: ('funding_runner',   'Funding Rate Arbitrage: проверь rates BTC/ETH/SOL, '
                             'открой позиции при rate>0.05%'),

    # ── Market analysis ───────────────────────────────────────────
    6:  ('market_runner',    'MARKET ANALYSIS (use search_agent): 1) Get current BTC price and 24h change. 2) Get ETH price and 24h change. 3) Get SOL price and change. 4) Give buy/sell/hold signal for each. Send 1 Telegram message with results. DO NOT ASK FOR MORE INFO, EXECUTE NOW with search_agent or code_runner. тренд, объёмы, ключевые уровни'),

    # ── Idle projects — periodic AI steps ─────────────────────────
    11: ('email_intelligence',
         'Email Intelligence: проверь и классифицируй непрочитанные важные письма. '
         'Составь сводку приоритетных писем. Сохрани в data/email_summary.json'),
    13: ('microsaas_dev',
         'AI Micro-SaaS Bot: придумай одну новую полезную функцию для бота. '
         'Опиши кратко техническую реализацию. Сохрани идею в data/microsaas_ideas.json'),
    15: ('apexmind_status',
         'MaxAI AI System: самодиагностика — что работает хорошо, '
         'что требует улучшения? Топ-3 приоритета. Кратко.'),

    16: ('signal_runner',    'BTC сейчас: один ответ BUY/SELL/HOLD и одна причина в 15 слов.'),

    # ── Freelance / Business ──────────────────────────────────────
    7:  ('freelance_runner',
         'ЗАДАЧА МОНЕТИЗАЦИИ: '
         '1) Проверь /root/my_personal_ai/data/kwork_gigs.json — там 3 готовых гига. '
         'Если они ещё не опубликованы на kwork.ru — опубликуй через browser_agent. '
         'Email для регистрации: jimmorrisoninlove@gmail.com. '
         '2) Найди 3 новых заказа на kwork.ru (python бот, парсер, telegram). '
         'Откликнись на каждый. '
         'Сохрани результат в data/monetization_log.json.'),
    10: ('maxai_image_gen',
         'MaxAI ЕЖЕДНЕВНЫЙ ПОСТ: '
         'СТРОГО ВЫПОЛНИ: python3 /root/my_personal_ai/projects/hyperion_engine_v11_monorepo/maxai/daily_post.py '
         'Это создаст профессиональное рекламное изображение через Pollinations.ai FLUX и отправит его в Telegram. '
         'НЕ ПЛАНИРУЙ, НЕ СОЗДАВАЙ НОВЫХ ЗАДАЧ — просто запусти скрипт. '
         'После успеха отчитайся: какой шаблон, размер файла, статус отправки.'),
    18: ('coffee_runner',    'Coffee Export: поиск B2B покупателей кофе Колумбия→Россия. '
                             'Сохрани в data/coffee_leads.json'),

    # ── Корпорация MaxAI — каждые 6ч: 8, 14, 20 ─────────────────
    8:  ('maxai_ops', 'EXECUTE NOW (no planning): Run these shell commands: 1) curl -s http://localhost:8005/health | head -1. 2) curl -s http://localhost:8006/health | head -1. 3) curl -s http://localhost:8000/health | head -1. 4) systemctl is-active personal-ai hyperion-engine hyperion-control-plane-v2. Output results to Telegram in one message. START EXECUTING: curl http://localhost:8005/health (restart if down). Check v12: curl http://localhost:8006/health. 2) Check all agents: curl http://localhost:8000/health. 3) Run agent pool: cd /root/my_personal_ai/projects/hyperion_engine_v11_monorepo && python3 -c "from maxai.core import get_pool; p=get_pool(); print(f\"Pool: {len(p._agents)} agents\")". 4) Save: echo ok > /root/my_personal_ai/data/maxai_ops_status.json. 2) Check agents: curl http://localhost:8005/agents. 3) Run: cd /root/my_personal_ai/projects/hyperion_engine_v11_monorepo && python3 maxai/core.py. 4) Save status to /root/my_personal_ai/data/maxai_ops_status.json. DO NOT create new plans. Just do these 4 steps.'),
    14: ('maxai_sales', 'MaxAI SALES (PRIORITY 1 - earn money): 1) Try kwork.ru via browser_agent: open kwork.ru, login jimmorrisoninlove@gmail.com/Fukcyoubithc48, bid on 5 projects (telegram bot, python bot, parser). 2) IF browser fails: use email_agent to send outreach to 3 leads from /root/my_personal_ai/data/leads.json. 3) Post promo to Telegram: send_message via telegram_agent to chat_id 1985320458 with daily promo from /root/my_personal_ai/data/agent_catalog.json. 4) Save results: write to /root/my_personal_ai/data/kwork_status.json. Login: jimmorrisoninlove@gmail.com / Fukcyoubithc48. 2) If gigs not published yet: publish from /root/my_personal_ai/data/kwork_gigs.json (3 gigs). 3) Find 5 orders: python bot, telegram bot, parser. 4) Submit bids: \'Ready in 24h. MaxAI - AI development.\' 5) Save to /root/my_personal_ai/data/kwork_status.json. ACT, don\'t plan.'),
    20: ('maxai_growth', 'MaxAI GROWTH AND REPORT: 1) Hire 20 new agents: cd /root/my_personal_ai/projects/hyperion_engine_v11_monorepo && python3 -c "from maxai.core import get_pool,HRDirector; p=get_pool(); h=HRDirector(p); print(h.daily_hr_cycle())". 2) Check revenue: python3 -c "from maxai.core import get_revenue; print(get_revenue().daily_report())". 3) Send Telegram report: agents hired today, revenue today, plan for tomorrow. 4) Save to /root/my_personal_ai/data/maxai_growth.json.'),

    # ── Корпорация MaxAI — v12 autonomous development ────────
    3:  ('hyperion_v12_dev',
         'HYPERION ENGINE MaxAI — АВТОНОМНАЯ РАЗРАБОТКА v12:\n'
         '1) Проверь статус: curl http://localhost:8006/health && curl http://localhost:8006/dashboard\n'
         '2) Если control-plane не отвечает: systemctl restart hyperion-control-plane-v2\n'
         '3) Проверь data-plane: systemctl status hyperion-data-plane-v2\n'
         '4) Отправь тестовую задачу: curl -s -X POST http://localhost:8006/tasks/submit '
         '-H "Content-Type: application/json" '
         '-d \'{"department_id":"maxai-dev","market_id":"RU","expected_revenue":15.0,"estimated_cost":0.5,"success_probability":0.9}\'\n'
         '5) Проверь результат через /dashboard — task должна появиться в состоянии PROMOTED\n'
         '6) Если всё работает — придумай и реализуй ОДНО улучшение для Hyperion v12 '
         '(например: новый endpoint, улучшение валидации, добавить метрику в dashboard)\n'
         '7) Сохрани отчёт: echo результаты > /root/my_personal_ai/data/hyperion_v12_dev_log.json\n'
         '8) Отправь краткий отчёт в Telegram через BOT_TOKEN=8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM CHAT_ID=1985320458\n'
         'ДЕЙСТВУЙ, не планируй. Отчитайся о каждом шаге.'),

    # ── Wildberries ───────────────────────────────────────────────
    # (hour 8 replaced by marketplace_prices which includes WB)

    # ── Hyperion v12 self-improvement — 2am ───────────────────────
    2:  ('hyperion_v12_improve',
         'HYPERION v12 САМООБУЧЕНИЕ:\n'
         '1) Читай /root/my_personal_ai/data/hyperion_v12_dev_log.json\n'
         '2) Анализируй паттерны из PostgreSQL: '
         'psql postgresql://postgres:hyperion_v12_pass@127.0.0.1/hyperion_v12 '
         '-c "SELECT layer, COUNT(*), AVG(financial_impact_delta) FROM pattern_memory GROUP BY layer;"\n'
         '3) Оцени: какие задачи проходят/не проходят валидацию? Почему?\n'
         '4) Реализуй улучшение в data_plane_v2.py или control_plane_v2.py — '
         'например улучши качество валидации или добавь новый паттерн в pattern_memory\n'
         '5) Перезапусти изменённый сервис если нужно\n'
         'Кратко отчитайся что изменил.'),

    # ── Reports ───────────────────────────────────────────────────
    17: ('email_outreach',
         'EMAIL МОНЕТИЗАЦИЯ: '
         'Используй email_agent с аккаунтом jimmorrisoninlove@gmail.com. '
         'Отправь деловое предложение 3 потенциальным клиентам из data/freelance_matches.json. '
         'Тема: "AI-разработка Telegram-бота под ключ — 1 день, 1000 руб". '
         'Сохрани отправленные письма в data/outreach_sent.json. '
         'Если data/freelance_matches.json пустой — найди потенциальных клиентов через поиск.'),
    9:  ('report_runner',    'Утренний отчёт в Telegram: балансы, '
                             'активные проекты (Корпорация MaxAI + Trading), план на день'),
    21: ('evening_report',   'Вечерний отчёт в Telegram: P&L за день, '
                             'баланс, статус Корпорация MaxAI + всех проектов'),
    23: ('health_runner',    'Диагностика всех агентов: проверь статусы, '
                             'перезапусти упавшие, отчёт в Telegram'),
    19:  ('agent_hire', 'HR DAILY CYCLE: Run: cd /root/my_personal_ai/projects/hyperion_engine_v11_monorepo && python3 -c "from maxai.core import get_pool,HRDirector; p=get_pool(); h=HRDirector(p); r=h.daily_hr_cycle(); print(r)". Report to Telegram: agents hired, pool size.'),
    22:  ('pattern_sync', 'PATTERN SYNC: Check Hyperion v12 dashboard via curl http://localhost:8006/dashboard. Update /root/my_personal_ai/data/hyperion_v12_dev_log.json with current stats. Send brief stats to Telegram.'),
    4:   ('intl_scan', 'INTERNATIONAL SCAN: Use search_agent to find top 3 AI automation gigs on fiverr.com and upwork.com. Save to /root/my_personal_ai/data/international_leads.json. Report via Telegram.'),
}

# ─────────────────────────────────────────────────────────────────
if hour in project_tasks:
    session_id, task = project_tasks[hour]
    print(f'[{time.strftime("%H:%M")}] Running: {session_id}')
    result = chat(task, session_id)
    print(f'Result: {result[:300]}')

    # Track Корпорация MaxAI progress
    if session_id.startswith('marketplace'):
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        task_label = {
            'marketplace_prices':   'Мониторинг цен конкурентов',
            'marketplace_seo':      'SEO-оптимизация карточек',
            'marketplace_analysis': 'Анализ рынка',
        }.get(session_id, session_id)
        update_project_progress(
            'MaxAI', delta=5.0 if ok else 0.5,
            task_name=task_label,
            task_status='completed' if ok else 'error')

    # Track Wildberries progress (it overlaps with marketplace)
    if session_id == 'wb_runner':
        ok = 'ERROR' not in result
        update_project_progress('CLEANS SKIN', delta=3.0 if ok else 0,
                                 task_name='Мониторинг цен', task_status='completed' if ok else 'running')

    # Track idle projects progress
    if session_id == 'email_intelligence':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('Email Intelligence', delta=4.0 if ok else 0,
                                 task_name='Анализ писем', task_status='completed' if ok else 'error')
    if session_id == 'microsaas_dev':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('AI Micro-SaaS', delta=3.0 if ok else 0,
                                 task_name='Разработка функций', task_status='completed' if ok else 'error')
    if session_id == 'apexmind_status':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('MaxAI', delta=2.0 if ok else 0,
                                 task_name='Самодиагностика', task_status='completed' if ok else 'error')
    if session_id == 'hyperion_status':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('Корпорация MaxAI', delta=3.0 if ok else 0,
                                 task_name='Hyperion status check', task_status='completed' if ok else 'error')
    if session_id == 'hyperion_build':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('Корпорация MaxAI', delta=5.0 if ok else 0,
                                 task_name='Hyperion build', task_status='completed' if ok else 'error')
    if session_id == 'hyperion_selfimprove':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('Корпорация MaxAI', delta=5.0 if ok else 0,
                                 task_name='Hyperion self-improve', task_status='completed' if ok else 'error')
    if session_id == 'hyperion_v12_dev':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('Корпорация MaxAI', delta=2.0 if ok else 0,
                                 task_name='Hyperion v12 development', task_status='completed' if ok else 'error')
    if session_id == 'hyperion_v12_improve':
        ok = 'ERROR' not in result and 'timed out' not in result.lower()
        update_project_progress('Корпорация MaxAI', delta=1.5 if ok else 0,
                                 task_name='Hyperion v12 self-improvement', task_status='completed' if ok else 'error')

else:
    # Every 30 min: health ping
    print(f'[{time.strftime("%H:%M")}] Health ping')
    result = chat('Статус системы: сколько агентов активно, есть ли ошибки? Одна строка.',
                  'health_ping')
    print(f'Status: {result[:150]}')
