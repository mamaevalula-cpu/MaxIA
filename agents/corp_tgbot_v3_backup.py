#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MaxAI Corporation — Client Bot v3.0
=====================================
Professional client-facing Telegram bot.
Open to ALL users worldwide. No whitelist restrictions.

Features:
- Multi-language: RU / EN auto-detection
- Full agent catalog (15 agents)
- Task submission → NEXUS API → AI execution → result delivery
- Payment instructions (crypto)
- Real-time task status
- Referral system
- Lead capture for enterprise
"""

import asyncio, json, logging, os, sys, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError
import urllib.parse

from telegram import (
    Update, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
import redis as _redis
from dotenv import load_dotenv

load_dotenv('/root/my_personal_ai/.env')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [CLIENT_BOT] %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/root/my_personal_ai/logs/client_bot.log'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger("client_bot")

rdb = _redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)

TOKEN = os.getenv("CORP_BOT_TOKEN", "")
NEXUS_BASE = "http://127.0.0.1:5000"
OWNER_TG = os.getenv("TELEGRAM_OWNER_ID", "")
OWNER_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Conversation states
CHOOSING_AGENT, TYPING_TASK, AWAITING_PAYMENT = range(3)

# ── AGENTS CATALOG ────────────────────────────────────────────────────────────
AGENTS = [
    {"id": "coder",     "name": "💻 CodeMaster",         "name_ru": "💻 Разработчик",         "desc": "Python, FastAPI, React, Automation",        "price": 49,  "emoji": "💻"},
    {"id": "trader",    "name": "📊 TradeBot Pro",        "name_ru": "📊 Трейдинг-бот",        "desc": "Bybit/Binance signals & analysis",           "price": 79,  "emoji": "📊"},
    {"id": "hunter",    "name": "🎯 LeadHunter",          "name_ru": "🎯 Поиск клиентов",      "desc": "Proposals, leads, outreach",                 "price": 29,  "emoji": "🎯"},
    {"id": "analyst",   "name": "📈 InsightAI",           "name_ru": "📈 Аналитик",            "desc": "Reports, data analysis, market research",    "price": 59,  "emoji": "📈"},
    {"id": "marketer",  "name": "📣 ViralBot",            "name_ru": "📣 Маркетолог",          "desc": "Content, SMM, copywriting, SEO",             "price": 39,  "emoji": "📣"},
    {"id": "presenter", "name": "🎯 PresentationMaster",  "name_ru": "🎯 Презентации",         "desc": "Pro PPTX in 30 seconds, dark theme",         "price": 89,  "emoji": "🎨"},
    {"id": "researcher","name": "🔬 BrainSearch",         "name_ru": "🔬 Исследования",        "desc": "Deep research, fact-check, reports",         "price": 49,  "emoji": "🔬"},
    {"id": "automator", "name": "⚙️ FlowBuilder",         "name_ru": "⚙️ Автоматизация",       "desc": "Bots, workflows, integrations, webhooks",    "price": 59,  "emoji": "⚙️"},
    {"id": "onec",      "name": "🏢 1С-Интеграция",       "name_ru": "🏢 1С-Интеграция",       "desc": "1С:Предприятие, интеграция, код",            "price": 119, "emoji": "🏢"},
    {"id": "legal",     "name": "⚖️ LexAI",               "name_ru": "⚖️ Юридический ИИ",      "desc": "Contracts, NDA, GDPR, compliance",           "price": 149, "emoji": "⚖️"},
    {"id": "finance",   "name": "💰 FinanceAI",           "name_ru": "💰 Финансовый анализ",   "desc": "DCF models, cash flow, investment reports",  "price": 149, "emoji": "💰"},
    {"id": "designer",  "name": "🎨 PixelMind",           "name_ru": "🎨 Дизайнер",            "desc": "UI/UX, landing pages, branding",             "price": 69,  "emoji": "🎨"},
    {"id": "hr",        "name": "👥 HireBot",             "name_ru": "👥 HR-автоматизация",    "desc": "Job descriptions, hiring, HR policies",      "price": 79,  "emoji": "👥"},
    {"id": "parser",    "name": "🕷️ DataScraper",         "name_ru": "🕷️ Парсер данных",       "desc": "Web scraping, data extraction, APIs",        "price": 39,  "emoji": "🕷️"},
    {"id": "support",   "name": "💬 SupportGenie",        "name_ru": "💬 Поддержка клиентов",  "desc": "24/7 support bot, FAQ, ticket handling",     "price": 19,  "emoji": "💬"},
]

AGENT_BY_ID = {a["id"]: a for a in AGENTS}

# ── UTILITIES ─────────────────────────────────────────────────────────────────
def is_russian(text: str) -> bool:
    if not text:
        return False
    ru_chars = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
    return ru_chars > 2

def get_lang(context: ContextTypes.DEFAULT_TYPE) -> str:
    return context.user_data.get("lang", "ru")

def nexus_post(path: str, data: dict, api_key: str = "") -> dict:
    """POST to NEXUS API."""
    try:
        body = json.dumps(data).encode()
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["x-api-key"] = api_key
        req = Request(f"{NEXUS_BASE}{path}", data=body, headers=headers, method="POST")
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"NEXUS POST {path} failed: {e}")
        return {"error": str(e)}

def nexus_get(path: str, api_key: str = "") -> dict:
    """GET from NEXUS API."""
    try:
        headers = {}
        if api_key:
            headers["x-api-key"] = api_key
        req = Request(f"{NEXUS_BASE}{path}", headers=headers)
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        log.error(f"NEXUS GET {path} failed: {e}")
        return {"error": str(e)}

def get_or_register_client(user_id: int, name: str, username: str = "") -> dict:
    """Get existing client or register new one."""
    key = f"nexus:tg_client:{user_id}"
    existing = rdb.get(key)
    if existing:
        return json.loads(existing)

    # Register new client
    email = f"tg{user_id}@maxai.fyi"
    resp = nexus_post("/nexus/register", {
        "email": email,
        "name": name or f"TG User {user_id}",
        "plan": "starter",
        "telegram_id": str(user_id)
    })

    if "api_key" in resp:
        client = resp
        rdb.set(key, json.dumps(client), ex=86400 * 30)
        log.info(f"New client registered: {name} ({user_id})")
        return client

    return {"api_key": "", "id": str(user_id)}

def notify_owner(message: str):
    """Notify owner about new client/order."""
    if not OWNER_TG or not OWNER_TOKEN:
        return
    try:
        body = json.dumps({"chat_id": OWNER_TG, "text": f"🔔 {message}", "parse_mode": "HTML"}).encode()
        req = Request(
            f"https://api.telegram.org/bot{OWNER_TOKEN}/sendMessage",
            data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        urlopen(req, timeout=5)
    except:
        pass

# ── KEYBOARDS ─────────────────────────────────────────────────────────────────
def main_menu_kb(lang: str = "ru") -> InlineKeyboardMarkup:
    if lang == "en":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Hire Agent", callback_data="menu_hire"),
             InlineKeyboardButton("📋 My Tasks", callback_data="menu_tasks")],
            [InlineKeyboardButton("💳 Pricing", callback_data="menu_pricing"),
             InlineKeyboardButton("📊 My Profile", callback_data="menu_profile")],
            [InlineKeyboardButton("🌐 Open Portal", url="https://maxai.fyi"),
             InlineKeyboardButton("💬 Support", callback_data="menu_support")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Нанять агента", callback_data="menu_hire"),
         InlineKeyboardButton("📋 Мои задачи", callback_data="menu_tasks")],
        [InlineKeyboardButton("💳 Тарифы", callback_data="menu_pricing"),
         InlineKeyboardButton("📊 Мой профиль", callback_data="menu_profile")],
        [InlineKeyboardButton("🌐 Открыть портал", url="https://maxai.fyi"),
         InlineKeyboardButton("💬 Поддержка", callback_data="menu_support")],
    ])

def agents_kb(page: int = 0) -> InlineKeyboardMarkup:
    per_page = 6
    start = page * per_page
    agents_page = AGENTS[start:start + per_page]

    rows = []
    for i in range(0, len(agents_page), 2):
        row = []
        for agent in agents_page[i:i+2]:
            row.append(InlineKeyboardButton(
                f"{agent['emoji']} {agent['name_ru'].split(' ', 1)[1] if ' ' in agent['name_ru'] else agent['name_ru']}",
                callback_data=f"hire_{agent['id']}"
            ))
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"agents_page_{page-1}"))
    if start + per_page < len(AGENTS):
        nav.append(InlineKeyboardButton("▶️", callback_data=f"agents_page_{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("↩ Назад", callback_data="menu_back")])
    return InlineKeyboardMarkup(rows)

# ── COMMAND HANDLERS ──────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = "ru"  # Default Russian
    if user.language_code and user.language_code.startswith("en"):
        lang = "en"
    context.user_data["lang"] = lang

    # Register/get client
    client = get_or_register_client(
        user.id, user.full_name, user.username or ""
    )
    context.user_data["client"] = client

    name = user.first_name or "Дорогой клиент"

    if lang == "en":
        text = (
            f"👋 Hello, <b>{name}</b>!\n\n"
            f"Welcome to <b>MaxAI Corporation</b> — the world's first autonomous AI corporation.\n\n"
            f"<b>What we do:</b>\n"
            f"• 15 specialized AI agents working 24/7\n"
            f"• From code writing to legal documents\n"
            f"• Results in 30 seconds to 5 minutes\n"
            f"• Enterprise-grade quality\n\n"
            f"🌐 <b>Portal:</b> https://maxai.fyi\n\n"
            f"Choose what you need:"
        )
    else:
        text = (
            f"👋 Привет, <b>{name}</b>!\n\n"
            f"Добро пожаловать в <b>MaxAI Corporation</b> — первую в мире автономную AI-корпорацию.\n\n"
            f"<b>Что мы делаем:</b>\n"
            f"• 15 специализированных AI-агентов работают 24/7\n"
            f"• От написания кода до юридических документов\n"
            f"• Результат за 30 секунд — 5 минут\n"
            f"• Качество уровня Enterprise\n\n"
            f"🌐 <b>Портал:</b> https://maxai.fyi\n\n"
            f"Что вас интересует?"
        )

    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_kb(lang))

    # Notify owner of new user
    notify_owner(
        f"Новый пользователь: <b>{user.full_name}</b> (@{user.username})\n"
        f"ID: {user.id} | Lang: {lang}"
    )


async def cmd_hire(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    if lang == "en":
        text = "🤖 <b>Choose your AI Agent:</b>\n\nAll agents work 24/7 and deliver results in minutes."
    else:
        text = "🤖 <b>Выберите AI-агента:</b>\n\nВсе агенты работают 24/7 и дают результат за минуты."

    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=agents_kb())
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=agents_kb())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client = context.user_data.get("client") or get_or_register_client(
        update.effective_user.id, update.effective_user.full_name
    )
    api_key = client.get("api_key", "")

    if not api_key:
        await update.message.reply_text("❌ Сначала начните с /start")
        return

    jobs = nexus_get("/nexus/tasks", api_key)
    jobs_list = jobs.get("jobs", []) if isinstance(jobs, dict) else []

    if not jobs_list:
        await update.message.reply_text(
            "📋 У вас пока нет задач.\n\nНажмите /hire чтобы заказать работу агента.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🤖 Нанять агента", callback_data="menu_hire")
            ]])
        )
        return

    text = "📋 <b>Ваши задачи:</b>\n\n"
    for job in jobs_list[:5]:
        status_icons = {"queued": "⏳", "running": "🔄", "completed": "✅", "failed": "❌"}
        icon = status_icons.get(job.get("status", ""), "❓")
        text += f"{icon} <code>{job['id']}</code> — {job.get('agent_type','?').title()}\n"
        text += f"   Статус: {job.get('status','?')} | {job.get('created_at','')[:10]}\n\n"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Обновить", callback_data="menu_tasks"),
        InlineKeyboardButton("🤖 Новая задача", callback_data="menu_hire")
    ]])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def cmd_pricing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    if lang == "en":
        text = (
            "💳 <b>MaxAI Pricing Plans:</b>\n\n"
            "🥉 <b>Starter</b> — $19/mo\n"
            "   1 agent · 50 tasks/mo\n\n"
            "🥈 <b>Professional</b> — $49/mo\n"
            "   5 agents · 300 tasks/mo\n\n"
            "🥇 <b>Business</b> — $99/mo\n"
            "   15 agents · 1000 tasks/mo\n\n"
            "💎 <b>Enterprise</b> — $299/mo\n"
            "   Unlimited agents · Unlimited tasks\n\n"
            "🔥 <b>Enterprise+</b> — $999/mo\n"
            "   Dedicated agents · SLA 99.9% · Priority\n\n"
            "🏷️ <i>Or pay per task: from $2/task</i>\n\n"
            "Payment: USDT (TRC20), ETH, BTC, SOL\n"
            "Contact: @MaxAI_SaaS_Bot for invoice"
        )
    else:
        text = (
            "💳 <b>Тарифы MaxAI Corporation:</b>\n\n"
            "🥉 <b>Starter</b> — $19/мес (~1800₽)\n"
            "   1 агент · 50 задач/мес\n\n"
            "🥈 <b>Professional</b> — $49/мес (~4600₽)\n"
            "   5 агентов · 300 задач/мес\n\n"
            "🥇 <b>Business</b> — $99/мес (~9200₽)\n"
            "   15 агентов · 1000 задач/мес\n\n"
            "💎 <b>Enterprise</b> — $299/мес (~28000₽)\n"
            "   Неограничено агентов и задач\n\n"
            "🔥 <b>Enterprise+</b> — $999/мес\n"
            "   Выделенные агенты · SLA 99.9% · Приоритет\n\n"
            "🏷️ <i>Или разовые задачи: от $2/задача</i>\n\n"
            "Оплата: USDT (TRC20), ETH, BTC, SOL\n"
            "За счётом: @MaxAI_SaaS_Bot"
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 Попробовать бесплатно", callback_data="menu_hire")],
        [InlineKeyboardButton("💬 Связаться для оплаты", url="https://t.me/MaxAI_SaaS_Bot")],
    ])
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


# ── CALLBACK HANDLERS ─────────────────────────────────────────────────────────
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    lang = get_lang(context)

    if data == "menu_back" or data == "menu_main":
        text = "🏠 Главное меню" if lang == "ru" else "🏠 Main Menu"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu_kb(lang))

    elif data == "menu_hire":
        await cmd_hire(update, context)

    elif data == "menu_tasks":
        client = context.user_data.get("client") or get_or_register_client(
            update.effective_user.id, update.effective_user.full_name
        )
        api_key = client.get("api_key", "")
        jobs = nexus_get("/nexus/tasks", api_key)
        jobs_list = jobs.get("jobs", []) if isinstance(jobs, dict) else []

        if not jobs_list:
            text = "📋 У вас пока нет задач.\n\nИспользуйте кнопку ниже чтобы нанять агента." if lang == "ru" else "📋 No tasks yet.\n\nUse button below to hire an agent."
        else:
            text = "📋 <b>Ваши последние задачи:</b>\n\n" if lang == "ru" else "📋 <b>Your recent tasks:</b>\n\n"
            icons = {"queued": "⏳", "running": "🔄", "completed": "✅", "failed": "❌"}
            for job in jobs_list[:5]:
                icon = icons.get(job.get("status", ""), "❓")
                text += f"{icon} {job.get('agent_type','?').title()} — {job.get('status','?')}\n"
                text += f"   ID: <code>{job['id']}</code>\n\n"

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Новая задача", callback_data="menu_hire"),
             InlineKeyboardButton("🔄 Обновить", callback_data="menu_tasks")],
            [InlineKeyboardButton("↩ Назад", callback_data="menu_back")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

    elif data == "menu_pricing":
        await cmd_pricing(update, context)

    elif data == "menu_profile":
        client = context.user_data.get("client") or get_or_register_client(
            update.effective_user.id, update.effective_user.full_name
        )
        api_key = client.get("api_key", "")
        plan = client.get("plan", "starter")
        tasks_used = client.get("tasks_used", 0)

        text = (
            f"📊 <b>Ваш профиль:</b>\n\n"
            f"👤 {update.effective_user.full_name}\n"
            f"📦 Тариф: <b>{plan.title()}</b>\n"
            f"✅ Задач выполнено: <b>{tasks_used}</b>\n"
            f"🔑 API ключ: <code>{api_key[:12]}...</code>\n\n"
            f"📘 Документация: https://maxai.fyi/nexus/openapi"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 Улучшить тариф", callback_data="menu_pricing")],
            [InlineKeyboardButton("↩ Назад", callback_data="menu_back")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

    elif data == "menu_support":
        text = (
            "💬 <b>Поддержка MaxAI Corporation</b>\n\n"
            "• Для технических вопросов: @MaxAI_SaaS_Bot\n"
            "• Документация: https://maxai.fyi\n"
            "• Email: support@maxai.fyi\n\n"
            "Среднее время ответа: <b>5 минут</b> (AI) / <b>2 часа</b> (человек)\n\n"
            "Опишите вашу проблему прямо здесь, и AI-агент поможет немедленно."
        )
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("↩ Назад", callback_data="menu_back")]])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

    elif data.startswith("agents_page_"):
        page = int(data.split("_")[-1])
        text = "🤖 <b>Выберите AI-агента:</b>" if lang == "ru" else "🤖 <b>Choose AI Agent:</b>"
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=agents_kb(page))

    elif data.startswith("hire_"):
        agent_id = data[5:]
        agent = AGENT_BY_ID.get(agent_id)
        if not agent:
            await query.edit_message_text("❌ Агент не найден")
            return

        context.user_data["selected_agent"] = agent_id
        price = agent["price"]
        name = agent["name_ru"] if lang == "ru" else agent["name"]

        text = (
            f"<b>{agent['emoji']} {name}</b>\n\n"
            f"📋 {agent['desc']}\n"
            f"💰 Стоимость: от <b>${price}/мес</b> или <b>$5/задача</b>\n\n"
            f"✍️ <b>Опишите вашу задачу</b> — и агент сразу приступит к работе.\n\n"
            f"<i>Пример: «Напиши Python скрипт для парсинга цен с Amazon»</i>"
            if lang == "ru" else
            f"<b>{agent['emoji']} {name}</b>\n\n"
            f"📋 {agent['desc']}\n"
            f"💰 From <b>${price}/mo</b> or <b>$5/task</b>\n\n"
            f"✍️ <b>Describe your task</b> — the agent will start immediately.\n\n"
            f"<i>Example: 'Write a Python script to scrape Amazon prices'</i>"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("↩ Назад", callback_data="menu_hire")]
        ])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

        context.user_data["state"] = "awaiting_task"


# ── MESSAGE HANDLER ───────────────────────────────────────────────────────────
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""
    lang = get_lang(context)

    # Auto-detect language
    if is_russian(text):
        context.user_data["lang"] = "ru"
        lang = "ru"
    elif text and all(ord(c) < 128 for c in text):
        if len(text) > 10:
            context.user_data["lang"] = "en"
            lang = "en"

    # Check if waiting for task description
    state = context.user_data.get("state")
    selected_agent = context.user_data.get("selected_agent")

    if state == "awaiting_task" and selected_agent and len(text) > 10:
        context.user_data["state"] = None
        agent = AGENT_BY_ID.get(selected_agent)

        # Get/register client
        client = context.user_data.get("client") or get_or_register_client(
            user.id, user.full_name, user.username or ""
        )
        api_key = client.get("api_key", "")

        # Submit task
        msg = await update.message.reply_text(
            "⚡ <b>Агент принял задачу!</b>\n\nОбрабатываю..." if lang == "ru" else
            "⚡ <b>Agent accepted task!</b>\n\nProcessing...",
            parse_mode="HTML"
        )

        if api_key:
            result = nexus_post("/nexus/tasks", {
                "agent_type": selected_agent,
                "task": text,
                "priority": 7
            }, api_key)

            job_id = result.get("job_id", "PENDING")

            # Notify owner
            notify_owner(
                f"📨 Новая задача!\n"
                f"Клиент: {user.full_name} (@{user.username})\n"
                f"Агент: {agent['name_ru'] if agent else selected_agent}\n"
                f"Задача: {text[:100]}\n"
                f"Job ID: {job_id}"
            )

            # Wait for result (async poll)
            await msg.edit_text(
                f"✅ <b>Задача в очереди!</b>\n\n"
                f"🤖 Агент: {agent['emoji']} {agent['name_ru'] if agent else selected_agent}\n"
                f"🆔 ID: <code>{job_id}</code>\n"
                f"⏱️ Ожидаемое время: 30-60 сек\n\n"
                f"Результат придёт прямо сюда!\n"
                f"Проверить статус: /status"
                if lang == "ru" else
                f"✅ <b>Task queued!</b>\n\n"
                f"🤖 Agent: {agent['emoji']} {agent['name'] if agent else selected_agent}\n"
                f"🆔 ID: <code>{job_id}</code>\n"
                f"⏱️ Expected time: 30-60 sec\n\n"
                f"Result will be sent here!\n"
                f"Check status: /status",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Мои задачи", callback_data="menu_tasks"),
                     InlineKeyboardButton("🤖 Ещё задача", callback_data="menu_hire")]
                ])
            )

            # Poll for result in background
            asyncio.create_task(poll_for_result(update, context, job_id, api_key, lang))

        else:
            await msg.edit_text(
                "❌ Ошибка регистрации. Попробуйте /start" if lang == "ru" else
                "❌ Registration error. Try /start"
            )

    elif len(text) > 5 and not text.startswith("/"):
        # Natural language task detection
        task_keywords = ["сделай", "напиши", "создай", "помоги", "нужно", "хочу",
                        "write", "create", "help", "make", "build", "analyze", "find"]
        if any(kw in text.lower() for kw in task_keywords):
            # Suggest agents
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 Выбрать агента", callback_data="menu_hire")],
                [InlineKeyboardButton("🔬 BrainSearch (исследование)", callback_data="hire_researcher")],
                [InlineKeyboardButton("💻 CodeMaster (разработка)", callback_data="hire_coder")],
            ])
            await update.message.reply_text(
                f"🤖 Понял! Выберите агента для этой задачи:" if lang == "ru" else
                f"🤖 Got it! Choose an agent for this task:",
                parse_mode="HTML", reply_markup=kb
            )
        else:
            # General inquiry — route to AI support
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 Главное меню", callback_data="menu_back")],
                [InlineKeyboardButton("💬 Написать менеджеру", url="https://t.me/MaxAI_SaaS_Bot")]
            ])
            await update.message.reply_text(
                "Я MaxAI Corporation Bot. Используйте /start для начала работы\nили кнопки ниже." if lang == "ru" else
                "I'm MaxAI Corporation Bot. Use /start to get started\nor the buttons below.",
                reply_markup=kb
            )


async def poll_for_result(
    update: Update, context: ContextTypes.DEFAULT_TYPE,
    job_id: str, api_key: str, lang: str
):
    """Poll for task result and send when ready."""
    max_attempts = 30  # 60 seconds max
    for attempt in range(max_attempts):
        await asyncio.sleep(2)
        try:
            result = nexus_get(f"/nexus/tasks/{job_id}", api_key)
            status = result.get("status", "queued")

            if status == "completed":
                result_text = result.get("result", "")
                if not result_text:
                    return

                preview = result_text[:2000]
                if len(result_text) > 2000:
                    preview += f"\n\n<i>... (показано 2000 из {len(result_text)} символов)</i>"

                msg = (
                    f"✅ <b>Задача выполнена!</b>\n"
                    f"⏱️ Время: {result.get('execution_ms', 0)//1000}с\n\n"
                    f"{preview}"
                    if lang == "ru" else
                    f"✅ <b>Task completed!</b>\n"
                    f"⏱️ Time: {result.get('execution_ms', 0)//1000}s\n\n"
                    f"{preview}"
                )

                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🤖 Ещё задача", callback_data="menu_hire"),
                     InlineKeyboardButton("⭐ Оценить", callback_data=f"rate_{job_id}")],
                ])
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=kb)
                return

            elif status == "failed":
                await update.message.reply_text(
                    f"❌ Задача не выполнена. Попробуйте ещё раз или обратитесь в поддержку.\nID: {job_id}"
                    if lang == "ru" else
                    f"❌ Task failed. Please try again or contact support.\nID: {job_id}"
                )
                return

        except Exception as e:
            log.warning(f"Poll error for {job_id}: {e}")

    # Timeout — notify to check later
    await update.message.reply_text(
        f"⏳ Задача всё ещё выполняется.\nПроверьте через минуту: /status\nID: <code>{job_id}</code>"
        if lang == "ru" else
        f"⏳ Task still processing.\nCheck in a minute: /status\nID: <code>{job_id}</code>",
        parse_mode="HTML"
    )


# ── PAYMENT COMMAND ───────────────────────────────────────────────────────────
async def cmd_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = (
        "💳 <b>Оплата MaxAI Corporation</b>\n\n"
        "Мы принимаем криптовалюту:\n\n"
        "🔷 <b>USDT TRC20</b> (рекомендуется, минимальная комиссия):\n"
        "<code>TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2</code>\n\n"
        "🔷 <b>ETH (ERC20)</b>:\n"
        "<code>0x7b72d6072f973a79d13abb11769927890832cc12</code>\n\n"
        "🟡 <b>BTC</b>:\n"
        "<code>158AEebXosZfxHY1ZVQNfTT6BHcuHqGFr4</code>\n\n"
        "🟣 <b>SOL</b>:\n"
        "<code>4v5rZQDfgHwE5135fQcVaQcaczYsb86gXbPgxWw4XDzK</code>\n\n"
        "После оплаты отправьте скриншот @MaxAI_SaaS_Bot с ID транзакции.\n"
        "Активация: <b>до 30 минут</b>."
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Уже оплатил", url="https://t.me/MaxAI_SaaS_Bot")],
        [InlineKeyboardButton("↩ Назад", callback_data="menu_back")]
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = (
        "<b>MaxAI Corporation Bot — Команды:</b>\n\n"
        "/start — Начать работу\n"
        "/hire — Нанять AI-агента\n"
        "/status — Проверить статус задач\n"
        "/pricing — Тарифы и цены\n"
        "/pay — Инструкции по оплате\n"
        "/help — Эта справка\n\n"
        "💡 <b>Совет:</b> Просто напишите что вам нужно, и бот сам предложит агента!"
        if lang == "ru" else
        "<b>MaxAI Corporation Bot — Commands:</b>\n\n"
        "/start — Get started\n"
        "/hire — Hire an AI agent\n"
        "/status — Check task status\n"
        "/pricing — Pricing plans\n"
        "/pay — Payment instructions\n"
        "/help — This help\n\n"
        "💡 <b>Tip:</b> Just describe what you need, and the bot will suggest an agent!"
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu_kb(lang))


# ── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        log.error("CORP_BOT_TOKEN not set!")
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("hire", cmd_hire))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pricing", cmd_pricing))
    app.add_handler(CommandHandler("pay", cmd_pay))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    log.info("MaxAI Client Bot v3.0 starting...")
    log.info(f"Token: ...{TOKEN[-8:]}")
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
