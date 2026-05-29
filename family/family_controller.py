# -*- coding: utf-8 -*-
"""
family/family_controller.py — Главный координатор всей семьи AI.

Это единая точка входа для управления всеми тремя системами.
Запускается вместе с my_personal_ai и координирует:

  1. Синхронизацию знаний      → распространяет verified entries через bus
  2. Фоновый мониторинг        → следит за состоянием всех компонентов
  3. Обработку торговых сигналов → фильтрует и пересылает в bybit-bot
  4. Обработку команд Telegram  → маршрутизирует в правильный компонент
  5. Систему самопочинки        → обнаруживает и исправляет ошибки
  6. Синхронизацию после обучения → после каждого цикла рассылает обновления

Принципы безопасности:
  • Торговые сигналы проходят pre/post validation
  • Knowledge broadcast только для verified entries (confidence ≥ 0.6)
  • Все изменения логируются в training_log + family_events
  • Откат = сигнал KNOWLEDGE_ROLLED_BACK → все компоненты игнорируют entry

Использование:
    fc = FamilyController.get()
    fc.start()          # запустить фоновые процессы

    # После цикла обучения
    fc.on_training_cycle_done(cycle=5, saved=3, rejected=1)

    # Получить полный статус
    print(fc.family_status())
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("family.controller")

# Интервалы фоновых задач
_SYNC_INTERVAL    = 300    # 5 мин — синхронизация знаний с шиной
_HEALTH_INTERVAL  = 60     # 1 мин — проверка здоровья
_CONSUME_INTERVAL = 30     # 30 сек — обработка входящих events
_PING_INTERVAL    = 120    # 2 мин — keepalive ping в FamilyBus

# Порог confidence для broadcast
_BROADCAST_CONFIDENCE = 0.60
_BROADCAST_IMPORTANCE = 0.50


@dataclass
class FamilySyncStats:
    """Статистика синхронизации за текущую сессию."""
    broadcasts_sent:     int = 0
    trade_signals_sent:  int = 0
    tg_notifications:    int = 0
    events_consumed:     int = 0
    errors_handled:      int = 0
    rollbacks_triggered: int = 0
    started_at:          float = field(default_factory=time.time)

    @property
    def uptime_str(self) -> str:
        age = time.time() - self.started_at
        if age < 3600:
            return f"{age/60:.0f} мин"
        return f"{age/3600:.1f} ч"


class FamilyController:
    """
    Singleton — главный координатор всей AI-семьи.
    """

    _instance: Optional["FamilyController"] = None

    def __init__(self):
        self._stats = FamilySyncStats()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self._started = False
        self._event_handlers: Dict[str, List[Callable]] = {}

    @classmethod
    def get(cls) -> "FamilyController":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Зависимости ───────────────────────────────────────────────────────────

    def _bus(self):
        from family.family_bus import FamilyBus
        return FamilyBus.get()

    def _broadcaster(self):
        from family.knowledge_broadcaster import KnowledgeBroadcaster
        return KnowledgeBroadcaster.get()

    def _health(self):
        from family.health_monitor import FamilyHealthMonitor
        return FamilyHealthMonitor.get()

    def _mem(self):
        from memory.memory_store import MemoryStore
        return MemoryStore.get()

    # ── Запуск / остановка ────────────────────────────────────────────────────

    def start(self) -> None:
        """Запустить все фоновые процессы координации."""
        if self._started:
            return

        self._stop.clear()
        self._started = True

        # 1. Keepalive ping
        self._spawn("family-ping",    self._ping_loop)
        # 2. Обработка входящих событий
        self._spawn("family-consume", self._consume_loop)
        # 3. Мониторинг здоровья
        self._spawn("family-health",  self._health_loop)
        # 4. Периодическая синхронизация знаний
        self._spawn("family-sync",    self._sync_loop)

        log.info("FamilyController started (4 background threads)")

        # Сообщить всем что personal_ai онлайн
        self._bus().publish(
            __import__("family.family_bus", fromlist=["FamilyEvent", "EventKind"])
            .__dict__["FamilyEvent"](
                kind=__import__("family.family_bus", fromlist=["EventKind"])
                     .__dict__["EventKind"].COMPONENT_ONLINE,
                source="ai",
                target="all",
                payload={"component": "personal_ai", "ts": time.time()},
            )
        )

    def stop(self) -> None:
        """Остановить все фоновые процессы."""
        self._stop.set()
        for t in self._threads:
            t.join(timeout=5)
        self._started = False
        log.info("FamilyController stopped")

    def _spawn(self, name: str, target: Callable) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    # ── Хуки от SelfTrainingAgent ─────────────────────────────────────────────

    def on_training_cycle_done(self, cycle: int, saved: int,
                                rejected: int, updated: int = 0) -> None:
        """
        Вызывается после каждого цикла обучения.
        Рассылает обновлённые знания нужным компонентам.
        """
        from family.family_bus import EventKind
        self._bus().broadcast(
            EventKind.TRAINING_CYCLE_DONE, source="ai",
            payload={
                "cycle": cycle, "saved": saved,
                "rejected": rejected, "updated": updated,
            },
        )

        # Синхронизировать новые знания с семьёй
        self._sync_new_knowledge(since_cycle=cycle)
        self._stats.broadcasts_sent += saved

        log.info("FamilyController: training cycle #%d done → %d broadcast",
                 cycle, saved)

    def on_knowledge_rollback(self, entry_id: int, reason: str) -> None:
        """Вызывается при откате знания — уведомляем всю семью."""
        self._broadcaster().announce_rollback(entry_id, reason)
        self._stats.rollbacks_triggered += 1

    def on_error_detected(self, component: str, error: str,
                           severity: str = "warning") -> None:
        """Зафиксировать ошибку в шине и уведомить Telegram."""
        from family.family_bus import EventKind
        self._bus().broadcast(
            EventKind.ERROR_DETECTED, source=component,
            payload={"error": error[:200], "severity": severity},
        )
        if severity == "critical":
            self._broadcaster().send_telegram_notification(
                f"🔴 CRITICAL ERROR [{component}]\n{error[:300]}", priority="high"
            )
        self._stats.errors_handled += 1

    # ── Синхронизация знаний ──────────────────────────────────────────────────

    def _sync_new_knowledge(self, since_cycle: int = 0) -> int:
        """
        Найти знания, которые ещё не были разосланы, и разослать их.
        Возвращает количество разосланных.
        """
        try:
            mem = self._mem()
            bc  = self._broadcaster()

            # Получить записи с высоким confidence и importance
            entries = mem.get_knowledge(limit=500)
            to_broadcast = [
                e for e in entries
                if (getattr(e, "confidence", 0) >= _BROADCAST_CONFIDENCE
                    and e.importance >= _BROADCAST_IMPORTANCE
                    and getattr(e, "verified", False))
            ]

            count = 0
            for entry in to_broadcast[:30]:   # не более 30 за раз
                try:
                    bc.announce_save(entry, cycle=since_cycle)
                    count += 1
                except Exception as ex:
                    log.debug("Broadcast error for entry %d: %s", entry.id, ex)

            return count
        except Exception as e:
            log.error("sync_new_knowledge error: %s", e)
            return 0

    # ── Обработка входящих событий ───────────────────────────────────────────

    def _handle_incoming_events(self) -> int:
        """Обработать входящие события для компонента 'ai'."""
        from family.family_bus import EventKind
        events = self._bus().consume(target="ai", limit=20)
        if not events:
            return 0

        for event in events:
            try:
                self._dispatch_event(event)
            except Exception as e:
                log.error("Event dispatch error: %s (%s)", e, event.kind)

        self._stats.events_consumed += len(events)
        return len(events)

    def _dispatch_event(self, event) -> None:
        """Маршрутизация входящего события."""
        from family.family_bus import EventKind

        if event.kind == EventKind.TRADE_EXECUTED:
            self._on_trade_executed(event.payload)

        elif event.kind == EventKind.TRADE_FAILED:
            self._on_trade_failed(event.payload)

        elif event.kind == EventKind.TG_COMMAND:
            self._on_tg_command(event.payload)

        elif event.kind == EventKind.RISK_ALERT:
            self._on_risk_alert(event.payload)

        elif event.kind == EventKind.COMPONENT_OFFLINE:
            comp = event.payload.get("component", "?")
            log.warning("Family: component %s went OFFLINE", comp)
            self._broadcaster().send_telegram_notification(
                f"⚠️ Компонент {comp} недоступен", priority="high"
            )

        elif event.kind == EventKind.HEALTH_PING:
            pass   # просто обновляет last_seen

        # Пользовательские обработчики
        handlers = self._event_handlers.get(event.kind.value, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                log.debug("Custom handler error: %s", e)

    def _on_trade_executed(self, payload: Dict) -> None:
        """Сделка выполнена → сохранить как знание."""
        symbol   = payload.get("symbol", "?")
        side     = payload.get("side", "?")
        pnl      = payload.get("pnl", 0.0)
        strategy = payload.get("strategy", "?")

        if pnl == 0:
            return

        from memory.memory_store import KnowledgeEntry, MemoryStore
        entry = KnowledgeEntry(
            category="solution" if pnl > 0 else "error",
            title=f"[Trade] {strategy} {symbol} {side} pnl={pnl:+.2f}",
            content=(
                f"Стратегия: {strategy}\nПара: {symbol}\nСторона: {side}\n"
                f"PnL: {pnl:+.4f}\nВремя: {time.strftime('%d.%m.%Y %H:%M')}\n"
                f"Детали: {str(payload)[:400]}"
            ),
            tags=["trade_result", "auto", symbol.lower()],
            importance=0.70 if pnl > 0 else 0.85,
            source="trading_bot",
        )
        try:
            from training.learning_loop import LearningLoop
            LearningLoop.get().process(entry, cycle=0)
            log.info("Trade result saved: %s %s pnl=%+.2f", symbol, side, pnl)
        except Exception as e:
            log.debug("Failed to save trade result: %s", e)

    def _on_trade_failed(self, payload: Dict) -> None:
        """Сделка провалена → запомнить причину."""
        error = payload.get("error", "unknown")
        symbol = payload.get("symbol", "?")
        log.warning("Trade failed: %s — %s", symbol, error)

        self._broadcaster().send_telegram_notification(
            f"❌ Сделка {symbol} провалена: {error[:100]}", priority="normal"
        )

    def _on_tg_command(self, payload: Dict) -> None:
        """Команда пришла из Telegram → маршрутизировать в brain."""
        command = payload.get("command", "")
        user_id = payload.get("user_id", "?")
        text    = payload.get("text", "")

        log.info("TG command from %s: %s", user_id, command)
        # Передаём в orchestrator (если запущен)
        try:
            from brain.orchestrator import Orchestrator
            # Async-команды обрабатываются в polling loop TelegramAgent
            # Здесь логируем для истории
        except Exception:
            pass

    def _on_risk_alert(self, payload: Dict) -> None:
        """Риск-предупреждение от торгового бота."""
        msg = payload.get("message", "Риск-предупреждение")
        level = payload.get("level", "warning")
        icon = "🔴" if level == "critical" else "⚠️"
        self._broadcaster().send_telegram_notification(
            f"{icon} РИСК: {msg[:200]}", priority=level,
        )

    # ── Регистрация обработчиков ──────────────────────────────────────────────

    def register_handler(self, event_kind: str,
                          handler: Callable) -> None:
        """Зарегистрировать кастомный обработчик для типа события."""
        if event_kind not in self._event_handlers:
            self._event_handlers[event_kind] = []
        self._event_handlers[event_kind].append(handler)

    # ── Статус и отчёт ────────────────────────────────────────────────────────

    def family_status(self) -> str:
        """Полный статус всей семьи."""
        health = self._health().check_all()
        bus_stats = self._bus().stats()
        health_report = self._health().format_report(health)

        lines = [
            health_report,
            "",
            "═══════════════════════════════════════",
            "  СТАТИСТИКА КООРДИНАЦИИ",
            "═══════════════════════════════════════",
            f"  Uptime:           {self._stats.uptime_str}",
            f"  Broadcasts sent:  {self._stats.broadcasts_sent}",
            f"  Trade signals:    {self._stats.trade_signals_sent}",
            f"  TG notifications: {self._stats.tg_notifications}",
            f"  Events consumed:  {self._stats.events_consumed}",
            f"  Errors handled:   {self._stats.errors_handled}",
            f"  Rollbacks:        {self._stats.rollbacks_triggered}",
            "",
            f"  Bus pending:      {bus_stats['pending']}",
            f"  Bus total:        {bus_stats['total']}",
        ]
        return "\n".join(lines)

    # ── Фоновые loop'ы ────────────────────────────────────────────────────────

    def _ping_loop(self) -> None:
        """Keepalive ping в FamilyBus."""
        from family.family_bus import EventKind
        while not self._stop.is_set():
            try:
                self._bus().ping("personal_ai", status="online")
            except Exception:
                pass
            self._stop.wait(timeout=_PING_INTERVAL)

    def _consume_loop(self) -> None:
        """Обработка входящих событий."""
        while not self._stop.is_set():
            try:
                self._handle_incoming_events()
            except Exception as e:
                log.error("Consume loop error: %s", e)
            self._stop.wait(timeout=_CONSUME_INTERVAL)

    def _health_loop(self) -> None:
        """Проверка здоровья всех компонентов."""
        # Первая проверка через 10 секунд
        self._stop.wait(timeout=10)
        while not self._stop.is_set():
            try:
                self._health().check_all()
            except Exception as e:
                log.error("Health loop error: %s", e)
            self._stop.wait(timeout=_HEALTH_INTERVAL)

    def _sync_loop(self) -> None:
        """Периодическая синхронизация знаний с шиной."""
        # Первая синхронизация через 60 секунд после старта
        self._stop.wait(timeout=60)
        while not self._stop.is_set():
            try:
                count = self._sync_new_knowledge()
                if count:
                    log.debug("FamilySync: broadcasted %d knowledge entries", count)
                # Очистка старых событий
                deleted = self._bus().cleanup(days=3)
                if deleted:
                    log.debug("FamilyBus cleanup: deleted %d old events", deleted)
            except Exception as e:
                log.error("Sync loop error: %s", e)
            self._stop.wait(timeout=_SYNC_INTERVAL)
