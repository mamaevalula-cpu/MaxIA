# -*- coding: utf-8 -*-
"""
agents/trading_agent.py — Агент-интеграция с торговым ботом Bybit.

Управляет trading_bot как подпроцессом или через прямой импорт.
Показывает статус, баланс, позиции.
Передаёт команды в торговый бот.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from core.config import cfg
from core.trading_bridge import TradingBridge, get_trading_status_text

log = logging.getLogger("agents.trading")

# Путь к торговому боту (если он существует как отдельный проект)
BYBIT_BOT_DIR = Path(__file__).parent.parent.parent / "bybit-bot"

# BYBIT ALPHA Elite Trading AI Agent v2.6 system prompt
BYBIT_ALPHA_SYSTEM_PROMPT = (
    "You are BYBIT ALPHA — Elite Trading AI Agent v2.6. "
    "Your mission: maximize risk-adjusted returns on Bybit futures/spot. "
    "Core principles: "
    "- Risk management FIRST: never risk >1% per trade; "
    "- Use multi-timeframe analysis (1m, 5m, 15m, 1h, 4h); "
    "- Ensemble signals: combine momentum + mean-reversion + volume; "
    "- Paper mode: simulate trades with full position sizing logic; "
    "- Always explain your reasoning with: signal strength, confidence %, entry/exit levels; "
    "- Report PnL in real-time via Telegram."
)
TRADING_BOT_PROJECT = cfg.PROJECTS_DIR / "trading_bot"


# ── HTTP proxy to bybit_monitor ──────────────────────────────────────────────

BOT_HTTP_URL = os.environ.get("BYBIT_BOT_HTTP_URL", "http://127.0.0.1:8001")


class _BotCoreHTTP:
    """
    Drop-in replacement for BotCore that uses HTTP calls to bybit_monitor.
    All methods that previously required direct module access now go via REST.
    """

    def _get(self, path: str) -> dict:
        from urllib.request import urlopen
        import json as _j
        try:
            with urlopen(f"{BOT_HTTP_URL}{path}", timeout=10) as r:
                return _j.loads(r.read())
        except Exception as e:
            return {"error": str(e), "ok": False}

    def _post(self, path: str, body: dict = None) -> dict:
        from urllib.request import urlopen, Request
        import json as _j
        try:
            data = _j.dumps(body or {}).encode()
            req  = Request(f"{BOT_HTTP_URL}{path}", data=data,
                           headers={"Content-Type": "application/json"}, method="POST")
            with urlopen(req, timeout=10) as r:
                return _j.loads(r.read())
        except Exception as e:
            return {"error": str(e), "ok": False}

    def get_status(self) -> dict:
        return self._get("/status")

    def get_balance(self) -> dict:
        return self._get("/balance")

    def get_positions(self) -> dict:
        return self._get("/positions")

    def get_orders(self) -> dict:
        return self._get("/orders")

    def get_pnl(self) -> dict:
        return self._get("/pnl")

    def get_signals(self) -> dict:
        return self._get("/signals")

    def get_strategies(self) -> dict:
        return self._get("/strategies")

    def start(self) -> dict:
        return self._post("/trading/resume")

    def stop(self) -> dict:
        return self._post("/trading/pause")

    def place_order(self, symbol: str, side: str, qty: float,
                    order_type: str = "market", price: float = 0.0) -> dict:
        return self._post("/place_order", {
            "symbol": symbol, "side": side, "qty": qty,
            "order_type": order_type, "price": price,
        })

    def close_position(self, symbol: str) -> dict:
        return self._post("/close_position", {"symbol": symbol})

    def close_all_positions(self) -> dict:
        return self._post("/close_all_positions")

    def set_risk(self, pct: float) -> dict:
        return self._post("/set_risk", {"risk_pct": pct})

    def toggle_strategy(self, name: str) -> dict:
        return self._post(f"/strategy/{name}/toggle")

    @property
    def is_running(self) -> bool:
        s = self.get_status()
        return s.get("online", False) and not s.get("paused", False)

    @property
    def mode(self) -> str:
        s = self.get_status()
        return "paper" if s.get("paper", True) else "live"



class TradingAgent(BaseAgent):
    """
    Агент управления торговым ботом.
    Читает данные через TradingBridge (SQLite + HTTP).
    Выполняет операции через прямой Bybit API V5.
    """

    def __init__(self) -> None:
        super().__init__("trading")
        self._bot_dir = BYBIT_BOT_DIR if BYBIT_BOT_DIR.exists() else TRADING_BOT_PROJECT
        self._bot_core = None   # lazy-load (write operations only)
        self._status_cache: Optional[str] = None
        self._bridge: TradingBridge = TradingBridge.get()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="trading",
            description="Автономный торговый агент Bybit. Размещает ордера, управляет позициями и ботом.",
            capabilities=[
                "get_status", "get_positions", "get_balance", "get_pairs",
                "start_bot", "stop_bot",
                "place_order",       # купить/продать
                "close_position",    # закрыть позицию
                "close_all_positions",
                "get_market_price",  # текущая цена
                "set_risk",          # установить риск
                "trading_analysis",  # анализ рынка
            ]
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(торговл|трейд|позици|ордер|баланс|bybit|биржа|сделк)",
            r"(trade|trading|position|order|balance|exchange|deal|pnl|profit)",
            r"(старт|стоп|запусти|останови).*(бот|торговл)",
            r"(start|stop).*(bot|trading)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        """Обработать команду для торгового бота."""
        self._set_status(AgentStatus.RUNNING)
        try:
            t = text.lower()

            # ── Статус и данные ───────────────────────────────────────────────
            if any(w in t for w in ["статус", "status", "как дела", "что сейчас",
                                     "как там", "как торгует", "торгует наш", "как бот"]):
                return self.get_status()

            if any(w in t for w in ["позици", "position", "сделки открыт"]):
                return self.get_positions()

            if any(w in t for w in ["баланс", "balance", "счёт", "сколько денег"]):
                return self.get_balance()

            if any(w in t for w in ["пары", "pairs", "монеты", "coins", "торгуемые"]):
                return self.get_pairs()

            # ── Управление ботом ──────────────────────────────────────────────
            if any(w in t for w in ["запусти бот", "старт бот", "start bot",
                                     "включи бот", "запусти торговл"]):
                return self.start_bot()

            if any(w in t for w in ["останови бот", "стоп бот", "stop bot",
                                     "выключи бот", "останови торговл"]):
                return self.stop_bot()

            # ── Закрытие позиций ──────────────────────────────────────────────
            if any(w in t for w in ["закрой все", "close all", "закрыть все позиции"]):
                return self.close_all_positions()

            # Закрыть конкретную позицию: "закрой BTCUSDT"
            import re as _re
            close_match = _re.search(r"закро[йи]\s+([A-Z]{2,10}USDT?)", text, _re.IGNORECASE)
            if close_match:
                return self.close_position(close_match.group(1).upper())

            # ── Ордера: "купи 0.01 BTCUSDT", "продай 10 SOLUSDT" ─────────────
            buy_match = _re.search(
                r"(купи|buy|long|открой long)\s+([\d.]+)\s*([A-Z]{2,10}USDT?)",
                text, _re.IGNORECASE
            )
            if buy_match:
                qty    = float(buy_match.group(2))
                symbol = buy_match.group(3).upper()
                return self.place_order(symbol, "Buy", qty)

            sell_match = _re.search(
                r"(продай|sell|short|открой short)\s+([\d.]+)\s*([A-Z]{2,10}USDT?)",
                text, _re.IGNORECASE
            )
            if sell_match:
                qty    = float(sell_match.group(2))
                symbol = sell_match.group(3).upper()
                return self.place_order(symbol, "Sell", qty)

            # Цена: "цена BTCUSDT", "курс ETH"
            price_match = _re.search(r"(цена|курс|price|ticker)\s+([A-Z]{2,10})", text, _re.IGNORECASE)
            if price_match:
                sym = price_match.group(2).upper()
                if not sym.endswith("USDT"):
                    sym += "USDT"
                return self.get_market_price(sym)

            # Риск: "установи риск 0.5"
            risk_match = _re.search(r"(риск|risk)\s+([\d.]+)", text, _re.IGNORECASE)
            if risk_match:
                return self.set_risk(float(risk_match.group(2)))

            # ── Анализ + статус через LLM ─────────────────────────────────────
            return self._trading_analysis(text)

        except Exception as e:
            self._log_failure("process", str(e))
            return f"❌ Ошибка торгового агента: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── Команды бота ─────────────────────────────────────────────────────────


    def get_analysis(self, symbol: str = "BTCUSDT") -> str:
        """Full technical analysis for a symbol using pandas + ta."""
        try:
            from tools.bybit_loader import get_exchange
            from tools.analysis import MarketAnalyzer
            ex      = get_exchange()
            candles = ex.get_klines(symbol, "15", 200)
            return MarketAnalyzer().analyze(symbol, candles)
        except Exception as e:
            log.error("get_analysis error: %s", e)
            return f"❌ Анализ недоступен: {e}"

    def get_server_status(self) -> str:
        """Get server resource status."""
        try:
            from tools.server_monitor import ServerMonitor
            return ServerMonitor.get().get_summary()
        except Exception as e:
            return f"❌ Ошибка мониторинга: {e}"

    def get_status(self) -> str:
        """Получить статус торгового бота через TradingBridge."""
        try:
            bot = self._bridge.get_status()
            lines = [
                f"📊 **Статус торгового бота**",
                f"  {bot.status_emoji} {bot.mode_label}",
            ]
            if bot.online:
                lines += [
                    f"  💰 Баланс: {bot.balance_usdt:.2f} USDT",
                    f"  📈 Daily PnL: {bot.daily_pnl:+.2f} USDT ({bot.daily_pnl_pct:+.2f}%)",
                    f"  📂 Открыто позиций: {bot.open_positions}",
                    f"  🔁 Сделок сегодня: {bot.trades_today} "
                    f"(Win: {bot.winning_trades} / Loss: {bot.losing_trades})",
                    f"  📊 Win rate: {bot.win_rate*100:.1f}%",
                ]
                if bot.active_pairs:
                    lines.append(f"  🎯 Пары: {', '.join(bot.active_pairs[:6])}")
                if bot.active_strategies:
                    lines.append(f"  🧠 Стратегии: {', '.join(bot.active_strategies)}")
                if bot.recent_trades:
                    lines.append("\n**Последние сделки:**")
                    for t in bot.recent_trades[:5]:
                        side_e = "🟢" if t.side.lower() == "buy" else "🔴"
                        lat = f" {t.latency_ms:.0f}ms" if t.latency_ms else ""
                        lines.append(f"  {side_e} {t.symbol} {t.side} "
                                     f"qty={t.qty} [{t.status}]{lat} @ {t.submitted_dt}")
            else:
                core = self._get_bot_core()
                if core:
                    return self._status_from_core(core)
                lines.append("  ⚠️  Бот оффлайн или не запущен")
                lines.append(f"  📁 DB: {self._bridge._db_path}")
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ Не удалось получить статус: {e}\n{self._mock_status()}"

    def _status_from_core(self, core) -> str:
        """Fallback: получить статус из BotCore (legacy)."""
        try:
            st = core.get_status()
            # Handle both dict and object returns
            if isinstance(st, dict):
                _running = st.get('running', False)
                _balance = st.get('balance_usd', st.get('balance_usdt', 0.0))
                _positions = st.get('positions', [])
                _pairs = st.get('pairs', [])
            else:
                _running = getattr(st, 'running', False)
                _balance = getattr(st, 'balance_usd', getattr(st, 'balance_usdt', 0.0))
                _positions = getattr(st, 'positions', [])
                _pairs = getattr(st, 'pairs', [])
            lines = [
                "📊 **Статус торгового бота** (BotCore)",
                f"  {'🟢 Работает' if _running else '🔴 Остановлен'}",
                f"  💰 Баланс: ${float(_balance):.2f} USDT",
                f"  📈 Позиций: {len(_positions)}",
                f"  🎯 Пары: {', '.join((_pairs[:5] if isinstance(_pairs, list) else [])) or '—'}",
            ]
            return "\n".join(lines)
        except Exception as e:
            return f"⚠️ BotCore error: {e}"

    def get_positions(self) -> str:
        """Получить открытые позиции."""
        bot = self._bridge.get_status()
        if not bot.online:
            core = self._get_bot_core()
            if core:
                try:
                    st = core.get_status()
                    if not st.positions:
                        return "📭 Открытых позиций нет."
                    lines = ["📈 **Открытые позиции:**\n"]
                    for p in st.positions:
                        sign = "+" if p.unrealised_pnl >= 0 else ""
                        lines.append(
                            f"  **{p.symbol}** {p.side}\n"
                            f"    Размер: {p.size} | Вход: {p.entry_price:.4f}\n"
                            f"    PnL: {sign}{p.unrealised_pnl:.3f} USDT\n"
                        )
                    return "\n".join(lines)
                except Exception as e:
                    return f"⚠️ {e}"
            return "📭 Торговый бот не подключён. Позиции недоступны."
        if bot.open_positions == 0:
            return "📭 Открытых позиций нет."
        return (f"📂 **Открыто позиций: {bot.open_positions}**\n"
                f"_(Детали доступны через Bybit API напрямую)_")

    def get_balance(self) -> str:
        """Получить баланс счёта."""
        bot = self._bridge.get_status()
        if bot.online and bot.balance_usdt > 0:
            return (f"💰 **Баланс:** {bot.balance_usdt:.2f} USDT\n"
                    f"  Daily PnL: {bot.daily_pnl:+.2f} USDT ({bot.daily_pnl_pct:+.2f}%)")
        # Fallback
        core = self._get_bot_core()
        if core:
            try:
                st = core.get_status()
                return f"💰 **Баланс:** ${st.balance_usd:.2f} USDT"
            except Exception as e:
                return f"⚠️ {e}"
        return "📭 Баланс недоступен (бот оффлайн)."

    def get_pairs(self) -> str:
        """Получить список торгуемых пар."""
        bot = self._bridge.get_status()
        if bot.online and bot.active_pairs:
            return f"🎯 **Торгуемые пары:** {', '.join(bot.active_pairs)}"
        core = self._get_bot_core()
        if core:
            try:
                pairs = core.get_pairs()
                return f"🎯 **Торгуемые пары:** {', '.join(pairs) or '—'}"
            except Exception as e:
                return f"⚠️ {e}"
        return "📭 Торговый бот не подключён."

    def start_bot(self) -> str:
        core = self._get_bot_core()
        if core is None:
            return "📭 Торговый бот не подключён. Запуск невозможен."
        try:
            ok, msg = core.start()
            return f"🟢 Торговый бот запущен. {msg}" if ok else f"⚠️ {msg}"
        except Exception as e:
            return f"❌ Ошибка запуска: {e}"

    def stop_bot(self) -> str:
        core = self._get_bot_core()
        if core is None:
            return "📭 Торговый бот не подключён."
        try:
            ok, msg = core.stop()
            return f"🔴 Торговый бот остановлен. {msg}" if ok else f"⚠️ {msg}"
        except Exception as e:
            return f"❌ Ошибка остановки: {e}"

    def place_order(self, symbol: str, side: str, qty: float,
                    order_type: str = "Market",
                    stop_loss: float = 0.0,
                    take_profit: float = 0.0) -> str:
        """
        Разместить ордер напрямую через Bybit API.
        AI вызывает этот метод для автономной торговли.
        side: "Buy" (long) | "Sell" (short)
        """
        core = self._get_bot_core()
        if core is None:
            return self._place_order_direct(symbol, side, qty, order_type, stop_loss, take_profit)
        try:
            # Проверяем баланс и риск
            balance, equity = core.get_balance()
            risk_pct = core.get_risk()
            max_qty = (equity * risk_pct / 100) / max(qty, 1)
            if qty > max_qty * 10:
                return f"⛔ Превышен риск. Макс объём при риске {risk_pct}%: {max_qty:.4f}"
            result = self._place_order_direct(symbol, side, qty, order_type, stop_loss, take_profit)
            log.info("Order placed: %s %s %s qty=%s → %s", order_type, side, symbol, qty, result)
            return result
        except Exception as e:
            return f"❌ Ошибка ордера: {e}"

    def close_position(self, symbol: str) -> str:
        """Закрыть открытую позицию по символу."""
        core = self._get_bot_core()
        if core is None:
            return "📭 BotCore не подключён."
        try:
            results = core.close_all_positions()
            # Фильтруем только нужный символ если задан
            target = [r for r in results if symbol.upper() in r.upper()]
            if target:
                return f"✅ Позиция {symbol} закрыта: {target[0]}"
            return f"📭 Открытая позиция {symbol} не найдена."
        except Exception as e:
            return f"❌ Ошибка закрытия: {e}"

    def close_all_positions(self) -> str:
        """Закрыть ВСЕ открытые позиции."""
        core = self._get_bot_core()
        if core is None:
            return "📭 BotCore не подключён."
        try:
            results = core.close_all_positions()
            if results:
                return "✅ Все позиции закрыты:\n" + "\n".join(f"  • {r}" for r in results)
            return "📭 Нет открытых позиций."
        except Exception as e:
            return f"❌ Ошибка: {e}"

    def get_market_price(self, symbol: str) -> str:
        """Получить текущую цену символа."""
        core = self._get_bot_core()
        if core:
            try:
                ticker = core.get_ticker(symbol)
                return (f"📊 **{symbol}**  "
                        f"Last: ${ticker.get('last', 0):.4f}  "
                        f"Bid: ${ticker.get('bid', 0):.4f}  "
                        f"Ask: ${ticker.get('ask', 0):.4f}")
            except Exception as e:
                return f"⚠️ {e}"
        return self._place_order_direct.__doc__ or "BotCore не подключён"

    def set_risk(self, pct: float) -> str:
        """Установить риск на сделку (%)."""
        if pct <= 0 or pct > 5:
            return "⛔ Риск должен быть от 0.1% до 5%"
        core = self._get_bot_core()
        if core:
            try:
                msg = core.set_risk(pct)
                return f"✅ Риск установлен: {pct}%  {msg}"
            except Exception as e:
                return f"❌ {e}"
        return "BotCore не подключён."

    def _place_order_direct(self, symbol: str, side: str, qty: float,
                             order_type: str = "Market",
                             stop_loss: float = 0.0,
                             take_profit: float = 0.0) -> str:
        """Прямой вызов Bybit API V5 для размещения ордера (без BotCore)."""
        # ── SECURITY: Symbol whitelist + HITL approval (2026-05-17) ─────────────
        # Empty ALLOWED_SYMBOLS = ALL direct orders BLOCKED until manually re-enabled
        ALLOWED_SYMBOLS: list = []  # Add symbols only after explicit authorization
        HITL_LOG = '/root/my_personal_ai/logs/trade_attempts.log'
        PENDING   = '/root/my_personal_ai/data/pending_approvals.jsonl'

        import logging as _log_sec, time as _tsec, json as _jsec, uuid as _uuid
        _log_sec.basicConfig(filename=HITL_LOG, level=_log_sec.INFO,
                             format='%(asctime)s %(levelname)s %(message)s')
        _logger_sec = _log_sec.getLogger('trade_guard')

        symbol_up = str(symbol).upper()
        if symbol_up not in ALLOWED_SYMBOLS:
            _logger_sec.warning(
                "BLOCKED direct order: %s %s %s - not in whitelist (ALLOWED_SYMBOLS=%r)",
                side, qty, symbol_up, ALLOWED_SYMBOLS
            )
            import os as _os
            _os.makedirs(_os.path.dirname(PENDING), exist_ok=True)
            nonce = _uuid.uuid4().hex[:8]
            entry = _jsec.dumps({
                'nonce': nonce, 'symbol': symbol_up, 'side': side,
                'qty': qty, 'price': 0, 'ts': _tsec.time(),
                'status': 'blocked', 'reason': 'symbol_not_whitelisted'
            })
            try:
                with open(PENDING, 'a') as _pf:
                    _pf.write(entry + '\n')
            except Exception as _pe:
                _logger_sec.error("Could not write pending_approvals: %s", _pe)
            return (
                f"BLOCKED: Direct order {side} {qty} {symbol_up} was NOT placed.\n"
                f"Reason: Symbol not in whitelist (ALLOWED_SYMBOLS is empty).\n"
                f"Nonce: {nonce}\n"
                f"To enable: add '{symbol_up}' to ALLOWED_SYMBOLS in _place_order_direct()."
            )
        # ── END SECURITY GUARD ────────────────────────────────────────────────
        import hashlib, hmac, time as _time
        api_key    = cfg.bybit_api_key
        api_secret = cfg.bybit_api_secret
        if not api_key or not api_secret:
            return "⚠️ BYBIT_API_KEY / BYBIT_API_SECRET не заданы в .env"

        testnet = cfg.bybit_testnet
        base_url = "https://api-testnet.bybit.com" if testnet else "https://api.bybit.com"

        ts   = str(int(_time.time() * 1000))
        body: dict = {
            "category":  "linear",
            "symbol":    symbol.upper(),
            "side":      side,            # "Buy" | "Sell"
            "orderType": order_type,      # "Market" | "Limit"
            "qty":       str(qty),
            "timeInForce": "GTC",
        }
        if stop_loss  > 0: body["stopLoss"]   = str(stop_loss)
        if take_profit > 0: body["takeProfit"] = str(take_profit)

        body_str = json.dumps(body, separators=(",", ":"))
        sign_str = ts + api_key + "5000" + body_str
        sig = hmac.new(api_secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()

        try:
            import httpx as _httpx
            r = _httpx.post(
                f"{base_url}/v5/order/create",
                headers={
                    "X-BAPI-API-KEY":        api_key,
                    "X-BAPI-SIGN":           sig,
                    "X-BAPI-TIMESTAMP":      ts,
                    "X-BAPI-RECV-WINDOW":    "5000",
                    "Content-Type":          "application/json",
                },
                content=body_str,
                timeout=10,
                verify=False,
            )
            data = r.json()
            ret_code = data.get("retCode", -1)
            if ret_code == 0:
                order_id = data.get("result", {}).get("orderId", "?")
                mode = "TESTNET" if testnet else "LIVE"
                return (f"✅ Ордер размещён [{mode}]\n"
                        f"  {order_type} {side} {symbol} qty={qty}\n"
                        f"  OrderID: {order_id}")
            else:
                return f"❌ Bybit API: {data.get('retMsg', 'unknown error')} (code {ret_code})"
        except Exception as e:
            return f"❌ Ошибка HTTP: {e}"

    # ── Анализ ────────────────────────────────────────────────────────────────

    def _trading_analysis(self, text: str) -> str:
        """Анализ торговых вопросов через LLM + реальные данные."""
        # Добавляем текущий статус бота в контекст
        bot_context = ""
        try:
            bot = self._bridge.get_status()
            if bot.online:
                bot_context = (
                    f"\n\nТекущий статус торгового бота:\n"
                    f"  Режим: {bot.mode_label}\n"
                    f"  Баланс: {bot.balance_usdt:.2f} USDT\n"
                    f"  Daily PnL: {bot.daily_pnl:+.2f} USDT ({bot.daily_pnl_pct:+.2f}%)\n"
                    f"  Открыто позиций: {bot.open_positions}\n"
                    f"  Сделок сегодня: {bot.trades_today} "
                    f"(Win: {bot.winning_trades}, Loss: {bot.losing_trades})\n"
                    f"  Пары: {', '.join(bot.active_pairs[:5])}\n"
                    f"  Стратегии: {', '.join(bot.active_strategies)}\n"
                )
                if bot.recent_trades:
                    bot_context += "  Последние сделки:\n"
                    for t in bot.recent_trades[:3]:
                        bot_context += f"    {t.symbol} {t.side} qty={t.qty} [{t.status}]\n"
            else:
                # Fallback to BotCore
                core = self._get_bot_core()
                if core:
                    try:
                        st = core.get_status()
                        bot_context = (
                            f"\n\nТекущий статус бота (BotCore):\n"
                            f"  Баланс: ${st.balance_usd:.2f} USDT\n"
                            f"  Позиций: {len(st.positions)}\n"
                        )
                    except Exception:
                        pass
        except Exception:
            pass

        return self._ask_llm(
            text + bot_context,
            system=(
                "You are BYBIT ALPHA — Elite Trading AI Agent v2.6. "
                "Your mission: maximize risk-adjusted returns on Bybit futures/spot. "
                "Core principles: "
                "- Risk management FIRST: never risk >1% per trade; "
                "- Use multi-timeframe analysis (1m, 5m, 15m, 1h, 4h); "
                "- Ensemble signals: combine momentum + mean-reversion + volume; "
                "- Paper mode: simulate trades with full position sizing logic; "
                "- Always explain your reasoning with: signal strength, confidence %, entry/exit levels; "
                "- Report PnL in real-time via Telegram. "
                "You have direct access to the Bybit trading bot. "
                "You CAN place orders, change settings and manage positions. "
                "Risk per trade <= 1%. This is not financial advice."
            ),
            task_type="trading",
            require_quality=False
        )

    # ── Lazy-load BotCore ─────────────────────────────────────────────────────

    def _get_bot_core(self):
        """HTTP-proxy to bybit_monitor running on port 8001."""
        if self._bot_core is not None:
            return self._bot_core
        self._bot_core = _BotCoreHTTP()
        return self._bot_core


    def _mock_status(self) -> str:
        mode = "TESTNET" if cfg.bybit_testnet else "MAINNET"
        return (
            f"📊 **Торговый бот** [{mode}]\n"
            f"  ⚠️  BotCore не подключён (bybit-bot не найден)\n"
            f"  Путь поиска: `{BYBIT_BOT_DIR}`\n\n"
            f"Чтобы подключить бот:\n"
            f"  1. Убедись что папка `bybit-bot/` существует\n"
            f"  2. Установи зависимости: `pip install -r bybit-bot/requirements.txt`\n"
            f"  3. Заполни `.env` файл"
        )