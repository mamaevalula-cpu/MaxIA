# -*- coding: utf-8 -*-
"""
agents/monitor_agent.py — Агент мониторинга + Семантический Файрвол (v2026.4).

Функции:
  • Мониторинг цен криптовалют (через Bybit API / CoinGecko)
  • Мониторинг веб-сайтов (доступность, изменение контента)
  • Алерты при пересечении порогов
  • Системный мониторинг (CPU, RAM, диск)
  • Уведомления через Telegram
  
  ★ НОВОЕ: Семантический Файрвол для защиты от Prompt Injection
    - Фильтрация команд из внешних источников (веб, новости, поиск)
    - Блокировка императивных инструкций перед передачей в EXECUTION_SECURE контур
    - Логирование всех попыток инъекций

Триггеры:
  «следи за», «мониторинг», «уведоми когда», «alert», «watch»
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMRequest

log = logging.getLogger("agents.monitor")

# Файрвол логи
FIREWALL_LOG = Path(__file__).parent.parent / "agent_logs" / "semantic_firewall.log"

MONITORS_FILE = Path(__file__).parent.parent / "data" / "monitors.json"


@dataclass
class MonitorTask:
    id: str
    type: str            # "price" | "website" | "system" | "custom"
    target: str          # symbol, URL, metric name
    condition: str       # "above", "below", "changed", "unavailable"
    threshold: float = 0.0
    interval_sec: int = 60
    active: bool = True
    last_value: Optional[float] = None
    last_check: float = 0.0
    alert_count: int = 0
    created_at: float = field(default_factory=time.time)


class MonitorAgent(BaseAgent):
    """
    Агент мониторинга — следит за условиями и уведомляет при срабатывании.
    """

    def __init__(self) -> None:
        super().__init__("monitor")
        self._tasks: Dict[str, MonitorTask] = {}
        self._alert_callbacks: List[Callable] = []
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._load_tasks()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="monitor",
            description="Мониторинг цен, сайтов, системы. Алерты в Telegram при срабатывании условий.",
            capabilities=[
                "watch_price", "watch_website", "watch_system",
                "add_alert", "list_monitors", "remove_monitor",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(следи за|мониторинг|уведоми|алерт|watch|monitor|alert|notify)",
            r"(когда цена|price alert|price above|price below)",
            r"(список мониторов|покажи мониторы|list monitors)",
            r"(системный статус|cpu|ram|память|диск)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            text_lower = text.lower()

            # Список мониторов
            if re.search(r"(список|list|покажи мониторы|show)", text_lower):
                return self._list_monitors()

            # Системный статус
            if re.search(r"(cpu|ram|память|диск|system|процессор)", text_lower):
                return self._system_status()

            # Цена криптовалюты
            if re.search(r"(цена|price|btc|eth|usdt|крипт)", text_lower):
                return self._handle_price_monitor(text)

            # Сайт
            if re.search(r"(сайт|сервер|url|website|http)", text_lower):
                return self._handle_website_monitor(text)

            # Разбираем команду через LLM
            return self._parse_and_add(text)

        except Exception as e:
            self._log_failure("monitor", str(e))
            return f"❌ Ошибка мониторинга: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    def add_alert_callback(self, cb: Callable) -> None:
        """Зарегистрировать callback для алертов (напр. → Telegram)."""
        self._alert_callbacks.append(cb)

    def start_monitoring(self) -> None:
        """Запустить фоновый мониторинг."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="monitor-agent"
        )
        self._thread.start()
        log.info("MonitorAgent started (%d tasks)", len(self._tasks))

    def stop_monitoring(self) -> None:
        self._stop_event.set()

    # ── Обработчики команд ────────────────────────────────────────────────────

    def _handle_price_monitor(self, text: str) -> str:
        """Парсим и регистрируем ценовой алерт."""
        # Ищем символ
        sym_match = re.search(r"\b(BTC|ETH|SOL|BNB|XRP|USDT|[A-Z]{2,6}USDT)\b",
                               text, re.IGNORECASE)
        symbol = sym_match.group().upper() if sym_match else "BTCUSDT"
        if not symbol.endswith("USDT"):
            symbol += "USDT"

        # Ищем порог
        num_match = re.search(r"(\d+[\d,.]*)", text)
        threshold = float(num_match.group().replace(",", ".")) if num_match else 0.0

        # Определяем условие
        condition = "below" if re.search(r"(ниже|below|под|упадёт)", text, re.IGNORECASE) else "above"

        # Текущая цена
        price = self._get_crypto_price(symbol)
        price_str = f"${price:,.2f}" if price else "N/A"

        if threshold:
            task_id = self._add_task(MonitorTask(
                id=f"price_{symbol}_{int(time.time())}",
                type="price",
                target=symbol,
                condition=condition,
                threshold=threshold,
                interval_sec=30,
            ))
            cond_str = "выше" if condition == "above" else "ниже"
            return (
                f"✅ **Алерт добавлен!**\n\n"
                f"📊 {symbol}: текущая цена {price_str}\n"
                f"🔔 Уведомлю когда цена {cond_str} ${threshold:,.2f}\n"
                f"🆔 Monitor ID: `{task_id}`\n\n"
                f"💡 Мониторинг каждые 30 сек. Telegram-уведомление при срабатывании."
            )
        else:
            # Просто показываем текущую цену
            return f"💰 **{symbol}**: {price_str}"

    def _handle_website_monitor(self, text: str) -> str:
        """Регистрируем мониторинг сайта."""
        url_match = re.search(r"https?://[^\s]+", text)
        if not url_match:
            return "❌ URL не найден в запросе. Укажи URL сайта."
        url = url_match.group()
        task_id = self._add_task(MonitorTask(
            id=f"web_{int(time.time())}",
            type="website",
            target=url,
            condition="unavailable",
            interval_sec=120,
        ))
        return (
            f"✅ **Мониторинг сайта добавлен!**\n\n"
            f"🌐 URL: {url}\n"
            f"🔔 Уведомлю если сайт станет недоступным\n"
            f"🆔 Monitor ID: `{task_id}`"
        )

    def _parse_and_add(self, text: str) -> str:
        """Парсим команду мониторинга через LLM."""
        prompt = (
            f"Распарси команду мониторинга и верни JSON:\n\n"
            f"КОМАНДА: {text}\n\n"
            f"JSON: {{\"type\": \"price|website|system\", \"target\": \"...\", "
            f"\"condition\": \"above|below|changed|unavailable\", "
            f"\"threshold\": 0.0, \"interval_sec\": 60}}\n"
            f"Только JSON."
        )
        resp = self._llm.ask_fast(prompt, task_type="classify")
        try:
            match = re.search(r'\{.*?\}', resp, re.DOTALL)
            if match:
                data = json.loads(match.group())
                task = MonitorTask(
                    id=f"custom_{int(time.time())}",
                    type=data.get("type", "custom"),
                    target=data.get("target", text[:50]),
                    condition=data.get("condition", "changed"),
                    threshold=float(data.get("threshold", 0)),
                    interval_sec=int(data.get("interval_sec", 60)),
                )
                task_id = self._add_task(task)
                return f"✅ Мониторинг добавлен (ID: `{task_id}`)\n{json.dumps(data, ensure_ascii=False, indent=2)}"
        except Exception as e:
            log.debug("Monitor parse error: %s", e)
        return "❌ Не удалось распарсить команду мониторинга. Укажи детали явно."

    # ── Системный статус ──────────────────────────────────────────────────────

    def _system_status(self) -> str:
        """Состояние системы: CPU, RAM, диск."""
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=1)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            # Определяем статус
            cpu_status = "🔴" if cpu > 80 else ("🟡" if cpu > 50 else "🟢")
            mem_pct = mem.percent
            mem_status = "🔴" if mem_pct > 85 else ("🟡" if mem_pct > 65 else "🟢")
            disk_pct = disk.percent
            disk_status = "🔴" if disk_pct > 90 else ("🟡" if disk_pct > 75 else "🟢")

            return (
                f"💻 **Системный статус**\n\n"
                f"{cpu_status} CPU: {cpu:.1f}%\n"
                f"{mem_status} RAM: {mem.used // 1024**2}MB / {mem.total // 1024**2}MB ({mem_pct:.1f}%)\n"
                f"{disk_status} Диск: {disk.used // 1024**3}GB / {disk.total // 1024**3}GB ({disk_pct:.1f}%)\n\n"
                f"🌡 Статус: {'⚠️ Нагрузка высокая!' if cpu > 80 or mem_pct > 85 else '✅ Норма'}"
            )
        except ImportError:
            return "❌ psutil не установлен. `pip install psutil`"

    # ── Цены криптовалют ─────────────────────────────────────────────────────

    def _get_crypto_price(self, symbol: str) -> Optional[float]:
        """Получить текущую цену через Bybit или CoinGecko."""
        try:
            import httpx
            # Bybit API (бесплатно, без ключа)
            sym = symbol.replace("USDT", "")
            r = httpx.get(
                f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={symbol}",
                timeout=5, verify=False
            )
            data = r.json()
            price_str = data.get("result", {}).get("list", [{}])[0].get("lastPrice", "")
            if price_str:
                return float(price_str)
        except Exception:
            pass

        try:
            # CoinGecko fallback
            coin_id = {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum",
                       "SOLUSDT": "solana"}.get(symbol, symbol.replace("USDT", "").lower())
            import httpx
            r = httpx.get(
                f"https://api.coingecko.com/api/v3/simple/price"
                f"?ids={coin_id}&vs_currencies=usd",
                timeout=5, verify=False
            )
            return r.json().get(coin_id, {}).get("usd")
        except Exception:
            return None

    # ── Список мониторов ──────────────────────────────────────────────────────

    def _list_monitors(self) -> str:
        if not self._tasks:
            return "📭 Нет активных мониторов.\n\nПримеры:\n• «следи за BTC выше 70000»\n• «мониторинг сайта https://example.com»"

        lines = [f"📊 **Активные мониторы ({len(self._tasks)}):**\n"]
        for task_id, task in self._tasks.items():
            status = "✅" if task.active else "⏸"
            cond = f"{'выше' if task.condition=='above' else 'ниже'} ${task.threshold:,.0f}" \
                   if task.threshold else task.condition
            lines.append(
                f"{status} `{task_id[:20]}` | {task.type} | {task.target[:30]} | {cond} "
                f"| алертов: {task.alert_count}"
            )
        return "\n".join(lines)

    # ── Фоновый мониторинг ────────────────────────────────────────────────────

    def _monitor_loop(self) -> None:
        log.info("Monitor loop started")
        while not self._stop_event.is_set():
            now = time.time()
            for task_id, task in list(self._tasks.items()):
                if not task.active:
                    continue
                if now - task.last_check < task.interval_sec:
                    continue
                try:
                    self._check_task(task)
                    task.last_check = now
                except Exception as e:
                    log.debug("Monitor check %s error: %s", task_id, e)
            self._stop_event.wait(timeout=10)

    def _check_task(self, task: MonitorTask) -> None:
        """Проверить условие задачи и отправить алерт если нужно."""
        alert_msg = None

        if task.type == "price":
            price = self._get_crypto_price(task.target)
            if price is not None:
                task.last_value = price
                if task.condition == "above" and price > task.threshold:
                    alert_msg = f"📈 {task.target}: ${price:,.2f} — ВЫШЕ ${task.threshold:,.0f}!"
                elif task.condition == "below" and price < task.threshold:
                    alert_msg = f"📉 {task.target}: ${price:,.2f} — НИЖЕ ${task.threshold:,.0f}!"

        elif task.type == "website":
            ok = self._check_website(task.target)
            if not ok and task.condition == "unavailable":
                alert_msg = f"🔴 Сайт недоступен: {task.target}"

        elif task.type == "system":
            try:
                import psutil
                if task.target == "cpu" and psutil.cpu_percent() > task.threshold:
                    alert_msg = f"🔥 CPU > {task.threshold:.0f}%!"
                elif task.target == "ram" and psutil.virtual_memory().percent > task.threshold:
                    alert_msg = f"🔥 RAM > {task.threshold:.0f}%!"
            except ImportError:
                pass

        if alert_msg:
            task.alert_count += 1
            log.info("ALERT: %s", alert_msg)
            for cb in self._alert_callbacks:
                try:
                    cb(alert_msg)
                except Exception:
                    pass
            # Пауза после алерта чтобы не спамить
            task.last_check = time.time() + task.interval_sec * 5
            self._save_tasks()

    def _check_website(self, url: str) -> bool:
        try:
            import httpx
            r = httpx.head(url, timeout=10, verify=False, follow_redirects=True)
            return r.status_code < 500
        except Exception:
            return False

    # ── Управление задачами ───────────────────────────────────────────────────

    def _add_task(self, task: MonitorTask) -> str:
        self._tasks[task.id] = task
        self._save_tasks()
        return task.id

    def _load_tasks(self) -> None:
        try:
            if MONITORS_FILE.exists():
                data = json.loads(MONITORS_FILE.read_text(encoding="utf-8"))
                for item in data:
                    task = MonitorTask(**item)
                    self._tasks[task.id] = task
        except Exception:
            pass

    def _save_tasks(self) -> None:
        try:
            MONITORS_FILE.parent.mkdir(exist_ok=True)
            data = [vars(t) for t in self._tasks.values()]
            MONITORS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass

    # ══════════════════════════════════════════════════════════════════════════
    # СЕМАНТИЧЕСКИЙ ФАЙРВОЛ (ANTI-INJECTION) — v2026.4
    # ══════════════════════════════════════════════════════════════════════════

    def semantic_firewall(self, text: str, source_agent: str = "unknown") -> Tuple[str, bool]:
        """
        Семантический Изолятор: Фильтрует императивные команды и инъекции из внешних данных.
        
        Возвращает:
            (cleaned_text, is_safe)
            - cleaned_text: очищенный текст
            - is_safe: True если безопасен, False если обнаружена инъекция
        """
        FIREWALL_LOG.parent.mkdir(exist_ok=True)
        
        # Белый список доверенных источников (НЕ фильтруем команды от пользователя)
        TRUSTED_SOURCES = ["gui", "telegram", "user", "cli", "dashboard", "direct"]
        if source_agent.lower() in TRUSTED_SOURCES:
            return text, True  # Пропускаем без фильтрации
        
        # Паттерны опасных команд (prompt injection patterns)
        dangerous_patterns = [
            # Команды переопределения контекста
            r"(ignore|забудь|игнорируй|disregard).{0,20}(previous|предыдущ|инструк|instruction|prompt)",
            r"(system|системный).{0,15}(prompt|инструкция|режим|mode)",
            r"(new|новый|change|смени).{0,15}(instruction|инструкция|rule|правило|role|роль)",
            
            # Команды выполнения
            r"(execute|выполни|run|запусти).{0,20}(script|скрипт|code|код|command|команду)",
            r"(transfer|переведи|send|отправь).{0,20}(balance|баланс|money|деньги|crypto|крипто)",
            r"(delete|удали|remove|убери).{0,20}(file|файл|data|данные|database|базу)",
            
            # Попытки доступа к системе
            r"(show|покажи|reveal|раскрой).{0,20}(api.{0,5}key|ключ|password|пароль|secret|секрет)",
            r"(access|доступ).{0,20}(admin|администратор|root|система|system)",
            r"sudo|rm\s+-rf|eval\(|exec\(|__import__|os\.system",
            
            # Императивные переходы
            r"(теперь ты|now you|from now|с этого момента|начиная с|starting from).{0,30}(must|должен|are|ты)",
            r"(act as|веди себя как|pretend|притворись|imagine|представь).{0,20}(admin|hacker|root)",
            
            # Скрытые инструкции в HTML/Markdown
            r"<!--.*?(ignore|system|execute|delete|password).*?-->",
            r"\[hidden\]|\[system\]|\[admin\]",
            
            # Переполнение буфера / DoS
            r"(.)\1{100,}",  # Повторяющиеся символы
        ]
        
        detected_threats = []
        for pattern in dangerous_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.DOTALL)
            for match in matches:
                detected_threats.append({
                    "pattern": pattern[:50],
                    "match": match.group(0)[:100],
                    "position": match.start()
                })
        
        # Если обнаружены угрозы
        if detected_threats:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            log_entry = {
                "timestamp": timestamp,
                "source_agent": source_agent,
                "threats_detected": len(detected_threats),
                "threats": detected_threats,
                "original_text_preview": text[:500]
            }
            
            # Логирование
            try:
                with open(FIREWALL_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            except Exception as e:
                log.error("Failed to write firewall log: %s", e)
            
            log.warning("[INJECTION DETECTED] Source: %s | Threats: %d", 
                       source_agent, len(detected_threats))
            
            # Очистка: удаляем все опасные фрагменты
            cleaned = text
            for threat in detected_threats:
                match_text = threat["match"]
                cleaned = cleaned.replace(match_text, "[FILTERED]")
            
            return cleaned, False
        
        # Текст безопасен
        return text, True

    def filter_external_data(self, data: str, source: str = "unknown") -> Dict[str, Any]:
        """
        Публичный интерфейс для фильтрации внешних данных перед передачей в EXECUTION контур.
        
        Args:
            data: Данные для проверки (текст, HTML, JSON)
            source: Источник данных (search, browser, news, etc.)
        
        Returns:
            {
                "original": исходные данные,
                "cleaned": очищенные данные,
                "is_safe": bool,
                "threats_found": int,
                "status": "PASS" | "FILTERED" | "BLOCKED"
            }
        """
        cleaned, is_safe = self.semantic_firewall(data, source)
        
        return {
            "original": data,
            "cleaned": cleaned,
            "is_safe": is_safe,
            "threats_found": 0 if is_safe else data.count("[FILTERED]"),
            "status": "PASS" if is_safe else "FILTERED"
        }
