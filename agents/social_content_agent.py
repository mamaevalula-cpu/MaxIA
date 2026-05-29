#!/usr/bin/env python3
"""
social_content_agent.py — Autonomous social content scheduler for MaxAI.

Posts 3 times/day at 09:00, 14:00, 19:00 UTC+3 (Moscow).
Uses Claude/Groq to generate premium Russian business content.
SIMHash-based deduplication prevents repeating posts within 7 days.
Posts to Telegram channel or chat (CHANNEL_ID from env).
"""
import os
import re
import math
import time
import json
import random
import hashlib
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

import httpx

logger = logging.getLogger("social_content")

# ─────────────────────── Config ────────────────────────────────────────────

BOT_TOKEN    = os.environ.get("CORP_BOT_TOKEN", "")
CHANNEL_ID   = os.environ.get("CHANNEL_ID", "")          # -100xxxxxx or @channame
OWNER_CHAT   = int(os.environ.get("OWNER_CHAT_ID", "1985320458"))
GROQ_KEY     = os.environ.get("GROQ_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DB_PATH      = os.environ.get("CONTENT_DB", "/root/my_personal_ai/data/social_content.db")
POST_HOURS   = [9, 14, 19]          # Moscow time (UTC+3)
DEDUP_DAYS   = 7                    # no repeat within N days
SIMHASH_BITS = 64
SIMHASH_THRESHOLD = 10              # hamming distance for "similar"

TZ_MOSCOW    = timezone(timedelta(hours=3))

# ─────────────────────── Content topics ────────────────────────────────────

CONTENT_THEMES = [
    "Как AI автоматизация увеличивает прибыль бизнеса на 40% за 3 месяца",
    "5 задач в вашем бизнесе, которые уже сегодня можно отдать ИИ",
    "Кейс: как наш клиент сэкономил 200 часов/месяц с AI-ботом",
    "Telegram-боты для бизнеса: что умеет современный AI-ассистент",
    "Почему компании выбирают MaxAI вместо штатного SMM-специалиста",
    "Автоматизация лидогенерации: от заявки до сделки без участия человека",
    "AI vs human: кто быстрее обрабатывает входящие заявки?",
    "Интеграция CRM + AI: как не терять клиентов в 2026",
    "Масштабирование бизнеса с AI: реальные цифры наших клиентов",
    "Ошибки при внедрении AI в бизнес (и как их избежать)",
    "ROI от AI-автоматизации: считаем вместе",
    "Чат-бот для отдела продаж: 10 функций, которые вы не знали",
    "Автоматический контент-маркетинг: как мы делаем это за вас",
    "AI-агент для фриланса: как зарабатывать больше с меньшими усилиями",
    "Новый уровень клиентского сервиса: ИИ отвечает 24/7",
]

SYSTEM_PROMPT = """Ты — копирайтер премиум-класса для MaxAI Corporation.
Пишешь посты для Telegram-канала о AI-автоматизации бизнеса.

Стиль: профессиональный, уверенный, без воды. Короткие абзацы.
Тон: деловой, но живой. Говоришь с предпринимателями как равный.

Структура поста:
1. Цепляющий заголовок (1-2 строки, эмодзи)
2. Проблема или инсайт (2-3 предложения)
3. Решение/польза от MaxAI (2-3 предложения)
4. Конкретные цифры или факт (1-2 предложения)
5. CTA: "Подключить AI: @Corporation_MaxAI_bot | от 3000 руб/$33"

Ограничения:
- Длина поста: 150-250 слов
- Без кликбейта и пустых обещаний
- Только конкретика и польза
- Обязательный CTA в конце
"""

# ─────────────────────── SIMHash ───────────────────────────────────────────

def simhash(text: str, bits: int = SIMHASH_BITS) -> int:
    """Compute SIMHash of text for near-duplicate detection."""
    if not text:
        return 0
    tokens = re.findall(r'\w+', text.lower())
    if not tokens:
        return 0
    v = [0] * bits
    for token in tokens:
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        for i in range(bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    return sum(1 << i for i in range(bits) if v[i] > 0)


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


def is_duplicate(text: str, existing_hashes: List[int]) -> bool:
    h = simhash(text)
    # Normalize to unsigned for comparison
    if h >= 2**63:
        h -= 2**64
    for eh in existing_hashes:
        if eh is None:
            continue
        if hamming_distance(h, eh) <= SIMHASH_THRESHOLD:
            return True
    return False


# ─────────────────────── Database ──────────────────────────────────────────

class ContentDB:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._init()

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS posts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    theme      TEXT,
                    content    TEXT,
                    simhash    INTEGER,
                    channel_id TEXT,
                    message_id INTEGER,
                    posted_at  TEXT DEFAULT (CURRENT_TIMESTAMP),
                    status     TEXT DEFAULT 'posted'
                );
                CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts(posted_at DESC);
                CREATE INDEX IF NOT EXISTS idx_posts_simhash   ON posts(simhash);
            """)

    def recent_hashes(self, days: int = DEDUP_DAYS) -> List[int]:
        cutoff = (datetime.now(TZ_MOSCOW) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT simhash FROM posts WHERE posted_at > ? AND status='posted'",
                (cutoff,)
            ).fetchall()
        return [r["simhash"] for r in rows if r["simhash"]]

    def save(self, theme: str, content: str, channel_id: str,
             message_id: Optional[int] = None) -> int:
        h = simhash(content)
        # Convert to signed 64-bit so SQLite INTEGER doesn't overflow
        if h >= 2**63:
            h -= 2**64
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO posts (theme,content,simhash,channel_id,message_id) VALUES (?,?,?,?,?)",
                (theme, content, h, channel_id, message_id)
            )
            return cur.lastrowid

    def recent(self, limit: int = 10) -> List[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id,theme,posted_at,status,message_id FROM posts ORDER BY posted_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status='posted' THEN 1 END) as posted,
                    SUM(CASE WHEN status='failed' THEN 1 END) as failed,
                    MAX(posted_at) as last_posted
                FROM posts
            """).fetchone()
        return dict(row) if row else {}


# ─────────────────────── Content generator ─────────────────────────────────

class ContentGenerator:
    """Generates posts via Groq (primary) or Claude (fallback)."""

    async def generate(self, theme: str) -> str:
        # Try Groq first (faster, cheaper)
        if GROQ_KEY:
            result = await self._groq(theme)
            if result:
                return result
        # Fallback: Claude
        if ANTHROPIC_KEY:
            result = await self._claude(theme)
            if result:
                return result
        # Static fallback
        return self._static(theme)

    async def _groq(self, theme: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=20) as client:
            try:
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {GROQ_KEY}"},
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user",   "content": f"Напиши пост на тему: {theme}"}
                        ],
                        "max_tokens": 600,
                        "temperature": 0.85,
                    }
                )
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"].strip()
                logger.warning("Groq status %d", r.status_code)
            except Exception as e:
                logger.error("Groq error: %s", e)
        return None

    async def _claude(self, theme: str) -> Optional[str]:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                r = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": ANTHROPIC_KEY,
                        "anthropic-version": "2023-06-01",
                    },
                    json={
                        "model": "claude-haiku-4-5",
                        "max_tokens": 600,
                        "system": SYSTEM_PROMPT,
                        "messages": [
                            {"role": "user", "content": f"Напиши пост на тему: {theme}"}
                        ]
                    }
                )
                if r.status_code == 200:
                    return r.json()["content"][0]["text"].strip()
                logger.warning("Claude status %d", r.status_code)
            except Exception as e:
                logger.error("Claude error: %s", e)
        return None

    def _static(self, theme: str) -> str:
        """Emergency fallback — pre-written template."""
        return (
            f"🤖 *MaxAI Corporation*\n\n"
            f"**{theme}**\n\n"
            f"Мы автоматизируем рутину, чтобы вы занимались стратегией.\n\n"
            f"✅ Ответы клиентам 24/7\n"
            f"✅ Автоматическая обработка заявок\n"
            f"✅ Интеграция с вашей CRM\n\n"
            f"💰 Окупаемость: 2-4 недели\n\n"
            f"Подключить AI: @Corporation_MaxAI_bot | от 3000 руб/$33"
        )


# ─────────────────────── Telegram poster ───────────────────────────────────

class TelegramPoster:
    BASE = "https://api.telegram.org"

    def __init__(self):
        self.token = BOT_TOKEN
        self.channel = CHANNEL_ID or str(OWNER_CHAT)  # fallback to owner DM

    def _url(self, method: str) -> str:
        return f"{self.BASE}/bot{self.token}/{method}"

    async def post(self, text: str) -> Optional[int]:
        """Post text to channel. Returns message_id or None."""
        if not self.token:
            logger.error("CORP_BOT_TOKEN not set")
            return None
        async with httpx.AsyncClient(timeout=15) as client:
            try:
                r = await client.post(self._url("sendMessage"), json={
                    "chat_id": self.channel,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                })
                data = r.json()
                if r.status_code == 200 and data.get("ok"):
                    mid = data["result"]["message_id"]
                    logger.info("Posted to %s, message_id=%d", self.channel, mid)
                    return mid
                else:
                    logger.error("Telegram post failed: %s", data)
                    # Retry without parse_mode if markdown error
                    if "parse" in str(data).lower() or "can't parse" in str(data).lower():
                        r2 = await client.post(self._url("sendMessage"), json={
                            "chat_id": self.channel,
                            "text": text,
                        })
                        if r2.status_code == 200 and r2.json().get("ok"):
                            return r2.json()["result"]["message_id"]
            except Exception as e:
                logger.error("Telegram post exception: %s", e)
        return None

    async def notify_owner(self, msg: str):
        """Send notification to owner."""
        if not self.token:
            return
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                await client.post(self._url("sendMessage"), json={
                    "chat_id": OWNER_CHAT,
                    "text": msg,
                })
            except Exception:
                pass


# ─────────────────────── Scheduler ─────────────────────────────────────────

class ContentScheduler:
    """Main scheduler: checks time, generates, deduplicates, posts."""

    def __init__(self):
        self.db        = ContentDB()
        self.generator = ContentGenerator()
        self.poster    = TelegramPoster()
        self._posted_hours: set = set()   # track which hours posted this day

    def _next_post_time(self) -> Optional[datetime]:
        """Return next scheduled post time (Moscow TZ)."""
        now = datetime.now(TZ_MOSCOW)
        today = now.date()
        for h in POST_HOURS:
            t = datetime.combine(today, __import__('datetime').time(h, 0), tzinfo=TZ_MOSCOW)
            if t > now:
                return t
        # Next day 09:00
        tomorrow = today + timedelta(days=1)
        return datetime.combine(tomorrow, __import__('datetime').time(POST_HOURS[0], 0), tzinfo=TZ_MOSCOW)

    def _should_post_now(self) -> bool:
        """True if current time matches a scheduled hour (within 5 min window)."""
        now = datetime.now(TZ_MOSCOW)
        hour_key = f"{now.date()}-{now.hour}"
        if hour_key in self._posted_hours:
            return False
        return now.hour in POST_HOURS and now.minute < 5

    def _pick_theme(self) -> str:
        """Pick a theme not recently used."""
        recent = self.db.recent(len(CONTENT_THEMES))
        used_themes = {r["theme"] for r in recent}
        available = [t for t in CONTENT_THEMES if t not in used_themes]
        if not available:
            available = CONTENT_THEMES
        return random.choice(available)

    async def run_once(self) -> Optional[Dict[str, Any]]:
        """Generate and post one piece of content."""
        theme = self._pick_theme()
        recent_hashes = self.db.recent_hashes()

        # Try up to 3 times to get non-duplicate content
        for attempt in range(3):
            content = await self.generator.generate(theme)
            if not is_duplicate(content, recent_hashes):
                break
            logger.info("Duplicate content on attempt %d, retrying with new theme", attempt + 1)
            theme = self._pick_theme()
        else:
            logger.warning("Could not generate non-duplicate content after 3 attempts")

        message_id = await self.poster.post(content)

        post_id = self.db.save(
            theme=theme,
            content=content,
            channel_id=self.poster.channel,
            message_id=message_id,
        )

        result = {
            "post_id": post_id,
            "theme": theme,
            "channel": self.poster.channel,
            "message_id": message_id,
            "success": message_id is not None,
        }
        logger.info("Content posted: %s", result)
        return result

    async def run_loop(self):
        """Continuous scheduler loop."""
        logger.info("Content scheduler started. Post hours (MSK): %s", POST_HOURS)
        while True:
            try:
                if self._should_post_now():
                    now = datetime.now(TZ_MOSCOW)
                    hour_key = f"{now.date()}-{now.hour}"
                    logger.info("Posting at %s MSK", now.strftime("%H:%M"))
                    result = await self.run_once()
                    self._posted_hours.add(hour_key)
                    if not result.get("success"):
                        await self.poster.notify_owner(
                            f"⚠️ Content scheduler: failed to post at {now.strftime('%H:%M')} MSK"
                        )
            except Exception as e:
                logger.error("Scheduler loop error: %s", e)
            await asyncio.sleep(60)  # check every minute


# ─────────────────────── Module singleton ──────────────────────────────────

_scheduler: Optional[ContentScheduler] = None

def get_scheduler() -> ContentScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ContentScheduler()
    return _scheduler


async def start_scheduler():
    """Start the background scheduler loop (call from app startup)."""
    scheduler = get_scheduler()
    asyncio.create_task(scheduler.run_loop())
    logger.info("Social content scheduler background task started")


# ─────────────────────── CLI ───────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    parser = argparse.ArgumentParser(description="Social Content Scheduler")
    parser.add_argument("--post-now", action="store_true", help="Post immediately")
    parser.add_argument("--stats",    action="store_true", help="Show stats")
    parser.add_argument("--recent",   type=int, default=0, help="Show N recent posts")
    parser.add_argument("--daemon",   action="store_true", help="Run scheduler loop")
    args = parser.parse_args()

    sched = ContentScheduler()

    if args.stats:
        import json as _json
        print(_json.dumps(sched.db.stats(), ensure_ascii=False, indent=2))

    elif args.recent:
        import json as _json
        posts = sched.db.recent(args.recent)
        for p in posts:
            print(f"[{p['posted_at']}] #{p['id']} {p['theme'][:60]} (msg_id={p['message_id']})")

    elif args.post_now:
        async def _post():
            result = await sched.run_once()
            print("Result:", result)
        asyncio.run(_post())

    elif args.daemon:
        asyncio.run(sched.run_loop())

    else:
        parser.print_help()
