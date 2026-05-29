# -*- coding: utf-8 -*-
"""
family/knowledge_broadcaster.py — Безопасное распространение знаний в семье.

Задача:
  Когда knowledge entry создан/обновлён — решить:
    1. Кому оно нужно?        → KnowledgeScope
    2. Безопасно ли делиться? → scope validator
    3. Как уведомить?         → FamilyBus.publish()
    4. Подтвердить доставку   → consumed check

Scope (область знания):
  PRIVATE    — только внутри компонента, который его создал
  AI_ONLY    — только для личного ИИ
  TRADING    — только для торгового бота
  TELEGRAM   — только для Telegram-интерфейса
  FAMILY     — для всех компонентов семьи

Правила безопасного распространения:
  • API-ключи, секреты → PRIVATE всегда
  • Торговые стратегии → TRADING | AI_ONLY (не в Telegram как публичное знание)
  • Предпочтения пользователя → AI_ONLY | TELEGRAM
  • Факты общего характера → FAMILY
  • Гипотезы → AI_ONLY (не применять в торговле до верификации)
  • error_fix → FAMILY (ошибки важны для всех)

Использование:
    bc = KnowledgeBroadcaster.get()
    bc.announce_save(entry, cycle=5)     # новое знание
    bc.announce_update(entry_id, title)  # обновление
    bc.announce_rollback(entry_id)       # откат
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Dict, List, Optional

from family.family_bus import EventKind, FamilyBus, FamilyEvent

log = logging.getLogger("family.broadcaster")


class KnowledgeScope(str, Enum):
    PRIVATE  = "private"    # только для создателя
    AI_ONLY  = "ai"         # только личный ИИ
    TRADING  = "trading"    # торговый бот
    TELEGRAM = "telegram"   # Telegram-интерфейс
    FAMILY   = "all"        # вся семья


# ── Ключевые слова для определения scope ─────────────────────────────────────

_TRADING_SIGNALS = [
    "ордер", "позиция", "стоп-лосс", "тейк-профит", "стратег.*торг",
    "bybit", "binance", "btc", "eth", "usdt", "futures", "spot",
    "drawdown", "sharpe", "pnl", "leverage", "margin", "liquidat",
    "api.*key", "secret.*key", "hmac", "webhook",
]
_TELEGRAM_SIGNALS = [
    "telegram", "уведомлени", "чат", "inline.*кнопк",
    "команда.*бот", "message.*tg",
]
_SENSITIVE_SIGNALS = [
    "password", "пароль", "api_key", "api_secret", "private_key",
    "token.*auth", "secret", "credential",
]
_HYPOTHESIS_SIGNALS = ["гипотез", "hypothesis", "возможно", "предположительно"]

_TRADING_RE  = re.compile("|".join(_TRADING_SIGNALS), re.IGNORECASE)
_TELEGRAM_RE = re.compile("|".join(_TELEGRAM_SIGNALS), re.IGNORECASE)
_SENSITIVE_RE = re.compile("|".join(_SENSITIVE_SIGNALS), re.IGNORECASE)
_HYPO_RE     = re.compile("|".join(_HYPOTHESIS_SIGNALS), re.IGNORECASE)


class KnowledgeBroadcaster:
    """
    Singleton — решает кому отправить знание и публикует events в FamilyBus.
    """

    _instance: Optional["KnowledgeBroadcaster"] = None

    @classmethod
    def get(cls) -> "KnowledgeBroadcaster":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _bus(self) -> FamilyBus:
        return FamilyBus.get()

    # ── Публичный API ─────────────────────────────────────────────────────────

    def announce_save(self, entry, cycle: int = 0) -> KnowledgeScope:
        """
        Объявить всей семье о новом знании.
        Возвращает определённый scope.
        """
        scope = self.determine_scope(entry)
        target = scope.value   # совпадает с target в FamilyBus

        payload = {
            "entry_id":      getattr(entry, "id", 0),
            "title":         getattr(entry, "title", "")[:80],
            "category":      getattr(entry, "category", ""),
            "knowledge_type": getattr(entry, "knowledge_type", "auto"),
            "confidence":    round(getattr(entry, "confidence", 0.5), 3),
            "importance":    round(getattr(entry, "importance", 0.5), 3),
            "scope":         scope.value,
            "cycle":         cycle,
            "source_agent":  getattr(entry, "source", ""),
        }

        self._bus().publish(FamilyEvent(
            kind=EventKind.KNOWLEDGE_SAVED,
            source="ai",
            target=target,
            payload=payload,
        ))

        log.debug("Broadcast KNOWLEDGE_SAVED id=%d scope=%s",
                  payload["entry_id"], scope.value)
        return scope

    def announce_update(self, entry_id: int, title: str,
                        scope: KnowledgeScope = KnowledgeScope.FAMILY,
                        delta: Dict = None) -> None:
        """Объявить об обновлении существующего знания."""
        self._bus().publish(FamilyEvent(
            kind=EventKind.KNOWLEDGE_UPDATED,
            source="ai",
            target=scope.value,
            payload={
                "entry_id": entry_id,
                "title":    title[:80],
                "scope":    scope.value,
                "delta":    delta or {},
            },
        ))

    def announce_rollback(self, entry_id: int, reason: str = "") -> None:
        """Объявить об откате знания — все компоненты должны его игнорировать."""
        self._bus().publish(FamilyEvent(
            kind=EventKind.KNOWLEDGE_ROLLED_BACK,
            source="ai",
            target="all",
            payload={"entry_id": entry_id, "reason": reason},
        ))
        log.info("Broadcast ROLLBACK for entry_id=%d", entry_id)

    def announce_conflict(self, entry_id_a: int, entry_id_b: int,
                          conflict_type: str, resolution: str = "") -> None:
        """Объявить о конфликте и его разрешении."""
        self._bus().publish(FamilyEvent(
            kind=EventKind.KNOWLEDGE_CONFLICT,
            source="ai",
            target="all",
            payload={
                "entry_a":      entry_id_a,
                "entry_b":      entry_id_b,
                "conflict_type": conflict_type,
                "resolution":   resolution,
            },
        ))

    def send_trade_signal(self, signal: Dict) -> None:
        """
        Отправить торговый сигнал от AI к торговому боту.
        signal = {"symbol": "BTCUSDT", "side": "buy", "confidence": 0.75, ...}
        """
        # Обязательная проверка — сигналы только с подтверждённой уверенностью
        confidence = signal.get("confidence", 0.0)
        if confidence < 0.65:
            log.warning("Trade signal rejected: confidence=%.2f < 0.65", confidence)
            return

        self._bus().publish(FamilyEvent(
            kind=EventKind.TRADE_SIGNAL,
            source="ai",
            target="trading",
            payload=signal,
            ttl=300.0,   # сигнал актуален 5 минут
        ))
        log.info("Trade signal sent: %s %s conf=%.2f",
                 signal.get("side", "?"), signal.get("symbol", "?"), confidence)

    def send_telegram_notification(self, text: str,
                                    priority: str = "normal") -> None:
        """Отправить уведомление в Telegram через FamilyBus."""
        self._bus().publish(FamilyEvent(
            kind=EventKind.TG_NOTIFICATION,
            source="ai",
            target="telegram",
            payload={"text": text[:4096], "priority": priority},
            ttl=3600.0,
        ))

    # ── Определение scope ─────────────────────────────────────────────────────

    def determine_scope(self, entry) -> KnowledgeScope:
        """
        Определить область применения знания.
        Порядок приоритетов: sensitive → явный scope → auto-detection.
        """
        text = f"{getattr(entry, 'title', '')} {getattr(entry, 'content', '')}".lower()
        category = (getattr(entry, "category", "") or "").lower()
        knowledge_type = (getattr(entry, "knowledge_type", "") or "").lower()
        tags = [t.lower() for t in (getattr(entry, "tags", None) or [])]

        # 1. Секреты — всегда приватные
        if _SENSITIVE_RE.search(text):
            return KnowledgeScope.PRIVATE

        # 2. Явные теги scope
        for tag in tags:
            if tag in ("private", "secret", "confidential"):
                return KnowledgeScope.PRIVATE
            if tag in ("trading_only", "trading-only"):
                return KnowledgeScope.TRADING
            if tag in ("ai_only", "ai-only"):
                return KnowledgeScope.AI_ONLY
            if tag in ("family", "shared"):
                return KnowledgeScope.FAMILY

        # 3. Гипотезы — только для AI (не применять в торговле без верификации)
        if knowledge_type == "hypothesis" or _HYPO_RE.search(text):
            return KnowledgeScope.AI_ONLY

        # 4. Предпочтения пользователя — AI и Telegram
        if knowledge_type == "preference" or category == "preference":
            return KnowledgeScope.AI_ONLY

        # 5. Торговые знания → TRADING
        if _TRADING_RE.search(text) or category in ("strategy", "trading", "signal"):
            return KnowledgeScope.TRADING

        # 6. Telegram-специфичные → TELEGRAM
        if _TELEGRAM_RE.search(text):
            return KnowledgeScope.TELEGRAM

        # 7. Ошибки и их решения — полезны всем
        if knowledge_type in ("error_fix",) or category in ("error", "solution"):
            return KnowledgeScope.FAMILY

        # 8. Факты и правила — семья
        if knowledge_type in ("fact", "rule"):
            return KnowledgeScope.FAMILY

        # 9. По умолчанию — AI_ONLY (безопаснее)
        return KnowledgeScope.AI_ONLY

    def determine_scope_bulk(self, entries: list) -> Dict[str, List]:
        """Категоризировать список записей по scope."""
        result: Dict[str, List] = {s.value: [] for s in KnowledgeScope}
        for entry in entries:
            scope = self.determine_scope(entry)
            result[scope.value].append(entry)
        return result
