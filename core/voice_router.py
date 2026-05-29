# -*- coding: utf-8 -*-
"""
core/voice_router.py — Голосовой маршрутизатор команд.

Архитектура подготовлена к голосовому вводу:
  • Принимает транскрипт речи (строку) из любого STT-движка
  • Нормализует: ошибки транскрипции, фонетические замены, слитные слова
  • Классифицирует намерение (intent) через fuzzy-matching + паттерны
  • Извлекает параметры команды (тикер, сумму, выражение и т.д.)
  • Маршрутизирует в BrainOrchestrator через стандартный OrchestratorRequest

Интеграция STT (примеры):
    # Whisper (OpenAI)
    import openai
    transcript = openai.audio.transcriptions.create(
        model="whisper-1", file=audio_file
    ).text
    VoiceRouter.get().route(transcript, source="voice_whisper")

    # Vosk (offline)
    transcript = vosk_model.recognize(audio_data)
    VoiceRouter.get().route(transcript, source="voice_vosk")

    # Google STT
    transcript = google_speech_client.recognize(audio)
    VoiceRouter.get().route(transcript, source="voice_google")
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("core.voice_router")


# ── Таблица фонетических замен ────────────────────────────────────────────────
# Частые ошибки русского STT при транскрипции команд

_PHONETIC_FIXES: List[Tuple[str, str]] = [
    # Числа / математика
    (r"\bплюс\b",      "+"),
    (r"\bминус\b",     "-"),
    (r"\bумножить\s*на\b", "*"),
    (r"\bразделить\s*на\b", "/"),
    (r"\bравно\b",     "="),
    (r"\bстепень\b",   "**"),
    (r"\bквадрат\b",   "**2"),
    (r"\bкорень\b",    "sqrt"),
    (r"\bпроцент\b",   "%"),
    # Тикеры
    (r"\bбиткоин\b",   "BTC"),
    (r"\bбитком\b",    "BTC"),    # частая ошибка
    (r"\bэфир\b",      "ETH"),
    (r"\bэфириум\b",   "ETH"),
    (r"\bсолана\b",    "SOL"),
    (r"\bдогикоин\b",  "DOGE"),
    (r"\bдоге\b",      "DOGE"),
    (r"\bюсдт\b",      "USDT"),
    (r"\bтезер\b",     "USDT"),
    # Команды
    (r"\bпроверь\s+систему\b", "статус системы"),
    (r"\bдиагностика\b",        "проверь здоровье системы"),
    (r"\bсамодиагностика\b",    "watchdog проверка"),
    (r"\bпосчитай\b",           "вычисли"),
    (r"\bзапусти\s+обучение\b", "начни самообучение"),
    # Технические термины
    (r"\bдипсик\b",    "deepseek"),
    (r"\bклод\b",      "claude"),
    (r"\bджемини\b",   "gemini"),
]

# ── Паттерны голосовых команд → intent ───────────────────────────────────────

_VOICE_PATTERNS: List[Tuple[str, str, Dict]] = [
    # (regex, intent, extra_flags)
    # Статус
    (r"\b(статус|состояние|как дела|что с системой|проверь)\b", "status", {}),
    (r"\b(здоровь|диагностик|watchdog|сторожев)\b",              "health",  {}),

    # Торговля
    (r"\b(купи|покупай|buy|лонг|long)\b.{0,30}\b([A-Z]{2,6})\b",         "trade_buy", {"extract_ticker": True}),
    (r"\b(продай|продавай|sell|шорт|short)\b.{0,30}\b([A-Z]{2,6})\b",    "trade_sell", {"extract_ticker": True}),
    (r"\b(цена|курс|стоимость|сколько стоит)\b.{0,20}\b([A-Z]{2,6})\b",  "price", {"extract_ticker": True}),
    (r"\b(баланс|balance|сколько денег|сколько на счету)\b",               "balance", {}),
    (r"\b(позиции|открытые сделки|positions)\b",                           "positions", {}),

    # Математика
    (r"\b(посчитай|вычисли|сколько будет|calculate|реши)\b",               "math", {}),
    (r"\b(интеграл|производная|корень|степень|факториал)\b",                "math", {}),

    # Новости / поиск
    (r"\b(новости|news|что случилось|что нового)\b",                        "news", {}),
    (r"\b(найди|поищи|search|загугли|погугли)\b",                          "search", {}),

    # Агенты
    (r"\b(напиши\s+код|создай\s+скрипт|код\s+для)\b",                     "code", {}),
    (r"\b(создай\s+проект|новый\s+проект)\b",                              "project", {}),
    (r"\b(обучись|самообучение|начни\s+учиться|тренируйся)\b",             "learn", {}),
    (r"\b(запусти\s+код|выполни\s+код|run|запусти\s+скрипт)\b",           "run_code", {}),
    (r"\b(суммируй|кратко|резюмируй|summarize)\b",                         "summarize", {}),

    # Ключи
    (r"\b(ключи|api\s+ключи|keys|проверь\s+ключи)\b",                     "keys", {}),

    # Управление
    (r"\b(стоп|останови|stop|выключи|shutdown)\b",                         "stop", {}),
    (r"\b(помощь|help|что умеешь|команды)\b",                              "help", {}),
]

# ── Извлечение параметров ─────────────────────────────────────────────────────

_AMOUNT_RE  = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(usdt|btc|eth|sol|usd|доллар|рублей)?\b", re.IGNORECASE)
_TICKER_RE  = re.compile(r"\b([A-Z]{2,6})\b")
_MATH_RE    = re.compile(r"[\d\+\-\*\/\(\)\.\^\s]+")


@dataclass
class VoiceIntent:
    """Результат распознавания голосовой команды."""
    raw_text: str            # Оригинальный транскрипт
    normalized_text: str     # После фонетической нормализации
    intent: str              # Определённое намерение
    confidence: float        # 0.0 – 1.0
    params: Dict[str, Any] = field(default_factory=dict)
    # params может содержать: ticker, amount, math_expr, query и т.д.


class VoiceRouter:
    """
    Маршрутизатор голосовых команд.
    Singleton.

    Использование:
        router = VoiceRouter.get()
        router.set_brain_callback(brain.process)
        intent = router.route("Купи биткоин на сто долларов")
    """

    _instance: Optional["VoiceRouter"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._brain_callback: Optional[Callable] = None
        self._handlers: Dict[str, Callable[[VoiceIntent], str]] = {}
        self._register_default_handlers()
        log.info("VoiceRouter initialized")

    @classmethod
    def get(cls) -> "VoiceRouter":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_brain_callback(self, cb: Callable) -> None:
        """Подключить BrainOrchestrator для обработки команд."""
        self._brain_callback = cb

    def register_handler(self, intent: str, handler: Callable[[VoiceIntent], str]) -> None:
        """Зарегистрировать кастомный обработчик для конкретного интента."""
        self._handlers[intent] = handler

    # ── Основной API ──────────────────────────────────────────────────────────

    def route(self, transcript: str, source: str = "voice",
              session_id: str = "voice") -> str:
        """
        Распознать команду из текста и выполнить её.

        Args:
            transcript: Текст речи (из STT или ввод пользователя)
            source: Источник ("voice_whisper", "voice_vosk", "voice_google", ...)
            session_id: ID сессии для контекста памяти

        Returns:
            Текстовый ответ системы
        """
        if not transcript or not transcript.strip():
            return "Пустой ввод."

        intent = self.recognize(transcript)
        log.info(
            "Voice: '%s' → intent=%s (%.0f%%) params=%s",
            transcript[:60], intent.intent, intent.confidence * 100, intent.params
        )

        # Попробовать кастомный обработчик
        if intent.intent in self._handlers:
            try:
                return self._handlers[intent.intent](intent)
            except Exception as e:
                log.error("Voice handler error [%s]: %s", intent.intent, e)

        # Маршрутизация через Brain
        if self._brain_callback:
            try:
                from brain.orchestrator import OrchestratorRequest
                req = OrchestratorRequest(
                    text=intent.normalized_text,
                    source=source,
                    session_id=session_id,
                    metadata={"voice_intent": intent.intent,
                               "voice_params": intent.params,
                               "voice_confidence": intent.confidence},
                )
                resp = self._brain_callback(req)
                return resp.text if resp else "Нет ответа"
            except Exception as e:
                log.error("Brain callback error from voice: %s", e)
                return f"Ошибка обработки: {e}"
        else:
            return f"Распознана команда: {intent.intent} | {intent.normalized_text}"

    def recognize(self, text: str) -> VoiceIntent:
        """
        Распознать намерение без выполнения.
        Полезно для тестирования и предварительного анализа.
        """
        normalized = self._normalize(text)
        intent, confidence, params = self._classify(normalized)
        return VoiceIntent(
            raw_text=text,
            normalized_text=normalized,
            intent=intent,
            confidence=confidence,
            params=params,
        )

    # ── Нормализация ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(text: str) -> str:
        """
        Нормализовать текст голосовой команды:
          1. Lowercase
          2. Фонетические замены (биткоин → BTC, плюс → +)
          3. Удаление лишних пробелов
          4. Стандартизация пунктуации
        """
        result = text.strip()

        for pattern, replacement in _PHONETIC_FIXES:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        # Убрать лишние пробелы
        result = re.sub(r"\s{2,}", " ", result).strip()
        return result

    # ── Классификация ─────────────────────────────────────────────────────────

    @staticmethod
    def _classify(normalized: str) -> Tuple[str, float, Dict[str, Any]]:
        """
        Классифицировать намерение по нормализованному тексту.
        Возвращает (intent, confidence, params).
        """
        params: Dict[str, Any] = {}

        for pattern, intent, flags in _VOICE_PATTERNS:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                confidence = 0.85

                # Извлечение тикера
                if flags.get("extract_ticker"):
                    ticker_m = _TICKER_RE.search(normalized)
                    if ticker_m:
                        params["ticker"] = ticker_m.group(1).upper()
                        confidence = 0.92

                # Извлечение суммы
                amount_m = _AMOUNT_RE.search(normalized)
                if amount_m:
                    try:
                        params["amount"] = float(
                            amount_m.group(1).replace(",", ".")
                        )
                        if amount_m.group(2):
                            params["amount_currency"] = amount_m.group(2).upper()
                    except ValueError:
                        pass

                # Математическое выражение
                if intent == "math":
                    math_m = _MATH_RE.search(normalized)
                    if math_m:
                        params["expression"] = math_m.group(0).strip()

                return intent, confidence, params

        # Fallback — передать как обычный текст
        return "general", 0.5, {}

    # ── Дефолтные обработчики ─────────────────────────────────────────────────

    def _register_default_handlers(self) -> None:
        """Зарегистрировать базовые обработчики для системных команд."""

        def _handle_help(intent: VoiceIntent) -> str:
            return (
                "Голосовые команды:\n"
                "• 'статус' — состояние системы\n"
                "• 'диагностика' — самодиагностика\n"
                "• 'новости' — последние новости\n"
                "• 'посчитай <выражение>' — математика\n"
                "• 'баланс' — баланс биржи\n"
                "• 'купи/продай <тикер>' — торговый ордер\n"
                "• 'найди <запрос>' — поиск\n"
                "• 'напиши код для <задача>' — генерация кода\n"
                "• 'обучись' — запуск самообучения\n"
            )

        self.register_handler("help", _handle_help)

    # ── Утилиты ───────────────────────────────────────────────────────────────

    @staticmethod
    def is_voice_input(text: str) -> bool:
        """
        Эвристика: похоже ли на голосовой ввод?
        (нет знаков препинания в конце, много союзов, разговорный стиль)
        """
        text = text.strip()
        if not text:
            return False
        # Нет знаков препинания в конце
        no_punct = not text[-1] in ".?!,;"
        # Много союзов/предлогов (разговорный стиль)
        spoken_words = {"пожалуйста", "скажи", "покажи", "слушай", "эй"}
        has_spoken = any(w in text.lower() for w in spoken_words)
        return no_punct or has_spoken

    def get_supported_intents(self) -> List[str]:
        """Список поддерживаемых интентов."""
        return list({intent for _, intent, _ in _VOICE_PATTERNS}) + ["general"]
