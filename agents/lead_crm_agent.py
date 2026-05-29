#!/usr/bin/env python3
"""
lead_crm_agent.py — Lead CRM with intent scoring, segmentation and Telegram alerts.
Stores every incoming lead from /api/v1/webhook into SQLite.
Sends instant Telegram alert for hot leads (score > 0.7).
"""
import os
import re
import math
import sqlite3
import asyncio
import logging
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("lead_crm")

# ─────────────────────── Config ────────────────────────────────────────────

DB_PATH    = os.environ.get("LEADS_DB", "/root/my_personal_ai/data/leads.db")
BOT_TOKEN  = os.environ.get("CORP_BOT_TOKEN", "")
OWNER_CHAT = int(os.environ.get("OWNER_CHAT_ID", "1985320458"))
HOT_THRESHOLD  = 0.7
WARM_THRESHOLD = 0.4

# ─────────────────────── Intent keywords ───────────────────────────────────

_INTENT_WEIGHTS: Dict[str, float] = {
    # Budget / payment signals  → very strong
    "бюджет": 0.25, "budget": 0.25, "заплатить": 0.22, "оплатить": 0.22,
    "стоимость": 0.20, "цена": 0.20, "прайс": 0.18, "price": 0.20,
    "сколько стоит": 0.25, "how much": 0.25, "тариф": 0.18,
    # Urgency / timeline
    "срочно": 0.18, "urgent": 0.18, "сегодня": 0.15, "today": 0.15,
    "asap": 0.18, "как можно скорее": 0.18, "deadline": 0.15,
    # Purchase intent
    "хочу купить": 0.25, "want to buy": 0.25, "заказать": 0.22,
    "order": 0.20, "purchase": 0.22, "договор": 0.22, "контракт": 0.22,
    "подключить": 0.20, "подписаться": 0.18,
    # Qualification signals
    "компания": 0.10, "company": 0.10, "бизнес": 0.10, "business": 0.10,
    "проект": 0.10, "project": 0.10, "интеграция": 0.12, "integration": 0.12,
    "автоматизация": 0.12, "automation": 0.12, "api": 0.12, "бот": 0.10,
    # Contact / meeting
    "позвони": 0.15, "call me": 0.15, "встреча": 0.15, "meeting": 0.15,
    "обсудить": 0.12, "discuss": 0.12, "демо": 0.15, "demo": 0.15,
    # Soft interest
    "интересно": 0.06, "interested": 0.06, "расскажите": 0.05,
    "tell me more": 0.06, "подробнее": 0.05, "information": 0.05,
}

_BUDGET_RE = re.compile(r"[\$€₽]\s*\d+|\d[\d\s]*(?:usd|usdt|руб|тыс|k\b)", re.I)
_EMAIL_RE  = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE  = re.compile(r"(?:\+7|8|\+1|\+\d{1,3})[\s\-()]?\d[\d\s\-()]{6,14}\d")


# ─────────────────────── Data model ────────────────────────────────────────

@dataclass
class Lead:
    name:         str   = ""
    contact:      str   = ""
    service:      str   = ""
    budget:       str   = ""
    intent_score: float = 0.0
    segment:      str   = "cold"
    source:       str   = "webhook"
    status:       str   = "new"
    notes:        str   = ""
    message_hash: str   = ""
    raw_text:     str   = ""
    created_at:   str   = field(default_factory=lambda: datetime.utcnow().isoformat())


# ─────────────────────── Database ──────────────────────────────────────────

class LeadDB:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS leads (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    name         TEXT    DEFAULT "",
                    contact      TEXT    DEFAULT "",
                    service      TEXT    DEFAULT "",
                    budget       TEXT    DEFAULT "",
                    intent_score REAL    DEFAULT 0.0,
                    segment      TEXT    DEFAULT "cold",
                    source       TEXT    DEFAULT "webhook",
                    status       TEXT    DEFAULT "new",
                    notes        TEXT    DEFAULT "",
                    message_hash TEXT    UNIQUE,
                    raw_text     TEXT    DEFAULT "",
                    created_at   TEXT    DEFAULT (CURRENT_TIMESTAMP)
                );

                CREATE INDEX IF NOT EXISTS idx_leads_segment
                    ON leads(segment);
                CREATE INDEX IF NOT EXISTS idx_leads_score
                    ON leads(intent_score DESC);
                CREATE INDEX IF NOT EXISTS idx_leads_created
                    ON leads(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_leads_status
                    ON leads(status);
            """)

    def upsert(self, lead: Lead) -> Optional[int]:
        """Insert lead; skip if duplicate hash. Returns row id or None."""
        with self._conn() as conn:
            try:
                cur = conn.execute("""
                    INSERT INTO leads
                        (name,contact,service,budget,intent_score,segment,
                         source,status,notes,message_hash,raw_text,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """, (lead.name, lead.contact, lead.service, lead.budget,
                      lead.intent_score, lead.segment, lead.source,
                      lead.status, lead.notes, lead.message_hash,
                      lead.raw_text, lead.created_at))
                return cur.lastrowid
            except sqlite3.IntegrityError:
                logger.debug("Duplicate lead hash=%s — skipped", lead.message_hash)
                return None

    def recent(self, limit: int = 20) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*)                                  as total,
                    SUM(CASE WHEN segment='hot'  THEN 1 END) as hot,
                    SUM(CASE WHEN segment='warm' THEN 1 END) as warm,
                    SUM(CASE WHEN segment='cold' THEN 1 END) as cold,
                    ROUND(AVG(intent_score),3)                as avg_score,
                    SUM(CASE WHEN status='converted' THEN 1 END) as converted
                FROM leads
            """).fetchone()
            return dict(row) if row else {}


# ─────────────────────── Scoring engine ────────────────────────────────────

class IntentScorer:
    """Keyword + structural NLP scorer — no external model required."""

    @staticmethod
    def score(text: str) -> float:
        if not text:
            return 0.0
        t = text.lower()
        raw = 0.0

        # Keyword accumulation
        matched = set()
        for kw, w in _INTENT_WEIGHTS.items():
            if kw in t and kw not in matched:
                raw += w
                matched.add(kw)

        # Structural bonuses
        if _BUDGET_RE.search(text):
            raw += 0.20
        if _EMAIL_RE.search(text):
            raw += 0.12
        if _PHONE_RE.search(text):
            raw += 0.15

        # Message length bonus
        words = len(t.split())
        if words >= 30:
            raw += 0.08
        elif words >= 15:
            raw += 0.04

        # Question mark = info-seeking, slight negative
        if "?" in text and words < 10:
            raw -= 0.05

        # Sigmoid compression → [0, 1]
        score = 1 / (1 + math.exp(-4.0 * (raw - 0.35)))
        return round(min(max(score, 0.0), 1.0), 4)

    @staticmethod
    def segment(score: float) -> str:
        if score >= HOT_THRESHOLD:
            return "hot"
        if score >= WARM_THRESHOLD:
            return "warm"
        return "cold"


# ─────────────────────── Lead parser ───────────────────────────────────────

class LeadParser:
    """Extract structured fields from free-form webhook payload."""

    @staticmethod
    def parse(payload: Dict[str, Any]) -> Lead:
        lead = Lead()

        # Raw text: concatenate all meaningful string fields
        parts = []
        for key in ("message", "text", "body", "content", "question", "comment"):
            v = payload.get(key, "")
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        lead.raw_text = " | ".join(parts) if parts else str(payload)

        # Name
        for key in ("name", "full_name", "username", "user_name", "first_name"):
            if payload.get(key):
                lead.name = str(payload[key]).strip()
                break
        if not lead.name:
            try:
                msg = payload.get("message", {})
                if isinstance(msg, dict):
                    frm = msg.get("from", {})
                    if isinstance(frm, dict):
                        lead.name = frm.get("first_name", "")
            except Exception:
                pass

        # Contact: email / phone from payload or extracted from text
        for key in ("email", "phone", "contact", "telegram", "username"):
            if payload.get(key):
                lead.contact = str(payload[key]).strip()
                break
        if not lead.contact:
            m = _EMAIL_RE.search(lead.raw_text)
            if m:
                lead.contact = m.group()
            else:
                m = _PHONE_RE.search(lead.raw_text)
                if m:
                    lead.contact = m.group()

        # Service / topic
        for key in ("service", "topic", "subject", "product", "request"):
            if payload.get(key):
                lead.service = str(payload[key]).strip()[:200]
                break

        # Budget
        m = _BUDGET_RE.search(lead.raw_text)
        if m:
            lead.budget = m.group().strip()
        elif payload.get("budget"):
            lead.budget = str(payload["budget"])[:100]

        # Source
        lead.source = str(payload.get("source", "webhook"))[:50]

        # Notes: extra metadata
        extra = {k: v for k, v in payload.items()
                 if k not in ("message","text","body","content","name","email",
                               "phone","contact","service","topic","budget","source")
                 and isinstance(v, (str, int, float)) and str(v).strip()}
        if extra:
            lead.notes = str(extra)[:500]

        # Score + segment
        lead.intent_score = IntentScorer.score(lead.raw_text)
        lead.segment      = IntentScorer.segment(lead.intent_score)

        # Dedup hash
        lead.message_hash = hashlib.sha256(
            lead.raw_text[:500].encode("utf-8", errors="replace")
        ).hexdigest()[:32]

        return lead


# ─────────────────────── Telegram alerts ───────────────────────────────────

class TelegramAlert:
    BASE = "https://api.telegram.org"

    def __init__(self):
        self.token = BOT_TOKEN
        self.chat  = OWNER_CHAT

    def _url(self, method: str) -> str:
        return f"{self.BASE}/bot{self.token}/{method}"

    async def send_hot_alert(self, lead: Lead, lead_id: int):
        if not self.token:
            logger.warning("CORP_BOT_TOKEN not set — skipping Telegram alert")
            return
        seg_emoji = {"hot": "🔥", "warm": "🌡", "cold": "❄️"}.get(lead.segment, "📝")
        score_bar = "█" * int(lead.intent_score * 10) + "░" * (10 - int(lead.intent_score * 10))
        lines = [
            f"{seg_emoji} *Горячий лид #{lead_id}*",
            "━━━━━━━━━━━━━━━━━━━━",
            f"👤 *Имя:* {lead.name or 'Не указано'}",
            f"📞 *Контакт:* {lead.contact or 'Не указан'}",
            f"🎯 *Услуга:* {lead.service or 'Не указана'}",
            f"💰 *Бюджет:* {lead.budget or 'Не указан'}",
            f"📊 *Intent:* `{score_bar}` {lead.intent_score:.2f}",
            f"🏷 *Сегмент:* {lead.segment.upper()}",
            f"📝 *Текст:* _{lead.raw_text[:300]}_",
        ]
        text = chr(10).join(lines)
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                r = await client.post(self._url("sendMessage"), json={
                    "chat_id": self.chat,
                    "text": text,
                    "parse_mode": "Markdown",
                })
                if r.status_code != 200:
                    logger.error("Telegram alert failed: %s", r.text[:200])
                else:
                    logger.info("Hot lead alert sent for lead_id=%d", lead_id)
            except Exception as e:
                logger.error("Telegram alert exception: %s", e)


# ─────────────────────── Main LeadCRM class ────────────────────────────────

class LeadCRM:
    """Public API used by webhook handler."""

    def __init__(self):
        self.db      = LeadDB()
        self.scorer  = IntentScorer()
        self.parser  = LeadParser()
        self.alert   = TelegramAlert()
        logger.info("LeadCRM initialized, db=%s", DB_PATH)

    async def capture(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse payload, score, save to DB. Send Telegram alert if hot.
        Returns lead dict or None if duplicate.
        """
        lead = self.parser.parse(payload)
        lead_id = self.db.upsert(lead)

        if lead_id is None:
            return None  # duplicate

        logger.info(
            "Lead #%d captured: segment=%s score=%.2f name=%r contact=%r",
            lead_id, lead.segment, lead.intent_score, lead.name, lead.contact
        )

        if lead.segment == "hot":
            asyncio.create_task(self.alert.send_hot_alert(lead, lead_id))

        return {
            "lead_id":      lead_id,
            "segment":      lead.segment,
            "intent_score": lead.intent_score,
            "name":         lead.name,
            "contact":      lead.contact,
        }

    def get_stats(self) -> Dict[str, Any]:
        return self.db.stats()

    def get_recent(self, limit: int = 20) -> list:
        return self.db.recent(limit)


# ─────────────────────── Module-level singleton ─────────────────────────────

_crm_instance: Optional[LeadCRM] = None

def get_crm() -> LeadCRM:
    global _crm_instance
    if _crm_instance is None:
        _crm_instance = LeadCRM()
    return _crm_instance


# ─────────────────────── CLI self-test ─────────────────────────────────────

if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.DEBUG)

    crm = LeadCRM()

    test_cases = [
        {
            "name": "Алексей Петров",
            "email": "alex@corp.ru",
            "service": "AI автоматизация",
            "message": "Срочно нужна интеграция бота для автоматизации продаж. Бюджет 50000 руб. Хочу заказать, готов оплатить сегодня.",
            "source": "landing"
        },
        {
            "name": "Мария",
            "message": "Расскажите подробнее о ваших услугах",
            "source": "telegram"
        },
        {
            "name": "ООО Технология",
            "phone": "+7-999-123-45-67",
            "service": "CRM система",
            "message": "Хочу купить CRM для отдела продаж. Бюджет $2000. Срочно нужна демо.",
            "source": "form"
        },
    ]

    async def run_tests():
        for i, payload in enumerate(test_cases):
            result = await crm.capture(payload)
            print(f"Test {i+1}: {json.dumps(result, ensure_ascii=False, indent=2)}")
        print("\nStats:", json.dumps(crm.get_stats(), ensure_ascii=False, indent=2))
        print("\nRecent:", json.dumps(crm.get_recent(5), ensure_ascii=False, indent=2))

    asyncio.run(run_tests())
