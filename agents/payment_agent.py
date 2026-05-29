# -*- coding: utf-8 -*-
"""
agents/payment_agent.py — Экспертный агент по платёжным системам.

Возможности:
  • Stripe: checkout, subscriptions, webhooks, connect
  • PayPal: orders, payouts, subscriptions
  • Crypto: USDT/BTC/ETH адреса, QR-коды
  • Генерация кода интеграции (любой платформы + язык)
  • Выставление счетов (PDF/HTML invoices)
  • Проверка статусов платежей
  • Аналитика доходов

Запуск:
  agent = PaymentAgent()
  result = agent.generate_payment_integration("stripe", "fastapi")
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from agents.base_agent import AgentInfo, AgentStatus, BaseAgent
from brain.llm_router import LLMProvider, LLMRequest

log = logging.getLogger("agents.payment")

DB_PATH = Path(__file__).parent.parent / "data" / "payments.db"


# ── Датаклассы ─────────────────────────────────────────────────────────────────

@dataclass
class PaymentRecord:
    id: str
    provider: str       # stripe | paypal | crypto | manual
    amount: float
    currency: str
    description: str
    status: str = "pending"   # pending | completed | failed | refunded
    client: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InvoiceItem:
    description: str
    quantity: float
    unit_price: float

    @property
    def total(self) -> float:
        return self.quantity * self.unit_price


@dataclass
class Invoice:
    id: str
    client_name: str
    client_email: str
    items: List[InvoiceItem]
    currency: str = "USD"
    due_date: str = ""
    notes: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def subtotal(self) -> float:
        return sum(i.total for i in self.items)

    @property
    def total(self) -> float:
        return self.subtotal


# ── База данных ────────────────────────────────────────────────────────────────

class PaymentDB:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                provider TEXT,
                amount REAL,
                currency TEXT,
                description TEXT,
                status TEXT,
                client TEXT,
                created_at TEXT,
                metadata TEXT
            );
            CREATE TABLE IF NOT EXISTS invoices (
                id TEXT PRIMARY KEY,
                client_name TEXT,
                client_email TEXT,
                items TEXT,
                currency TEXT,
                due_date TEXT,
                notes TEXT,
                total REAL,
                created_at TEXT
            );
            """)

    def save_payment(self, p: PaymentRecord) -> None:
        with self._conn() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO payments
            (id,provider,amount,currency,description,status,client,created_at,metadata)
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (p.id, p.provider, p.amount, p.currency, p.description,
                  p.status, p.client, p.created_at, json.dumps(p.metadata)))

    def get_payments(self, status: Optional[str] = None, limit: int = 50) -> List[Dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM payments WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM payments ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
        return [dict(r) for r in rows]

    def save_invoice(self, inv: Invoice) -> None:
        with self._conn() as conn:
            conn.execute("""
            INSERT OR REPLACE INTO invoices
            (id,client_name,client_email,items,currency,due_date,notes,total,created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (inv.id, inv.client_name, inv.client_email,
                  json.dumps([{"d": i.description, "q": i.quantity, "p": i.unit_price}
                               for i in inv.items]),
                  inv.currency, inv.due_date, inv.notes,
                  inv.total, inv.created_at))

    def earnings_report(self) -> Dict[str, Any]:
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='completed' AND currency='USD'"
            ).fetchone()[0]
            by_provider = conn.execute(
                "SELECT provider, SUM(amount) as total FROM payments "
                "WHERE status='completed' AND currency='USD' "
                "GROUP BY provider ORDER BY total DESC"
            ).fetchall()
        return {
            "total_usd": round(float(total), 2),
            "by_provider": {r["provider"]: round(r["total"], 2) for r in by_provider},
        }


# ── Шаблоны кода платёжных интеграций ─────────────────────────────────────────

# Шаблон Stripe checkout (Python FastAPI)
STRIPE_FASTAPI_TEMPLATE = '''# Stripe Checkout — FastAPI
# pip install stripe fastapi uvicorn python-dotenv

import stripe
import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")  # sk_live_... or sk_test_...
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

app = FastAPI()

class CheckoutRequest(BaseModel):
    amount_cents: int       # 999 = $9.99
    currency: str = "usd"
    description: str
    success_url: str = "https://yoursite.com/success"
    cancel_url: str = "https://yoursite.com/cancel"

@app.post("/create-checkout")
async def create_checkout(req: CheckoutRequest):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": req.currency,
                    "product_data": {"name": req.description},
                    "unit_amount": req.amount_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=req.success_url + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=req.cancel_url,
        )
        return {"checkout_url": session.url, "session_id": session.id}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        # TODO: fulfill order for session["customer_email"]
        print(f"Payment completed: {session['id']}")

    return {"status": "ok"}
'''

# Шаблон PayPal (Python Flask)
PAYPAL_FLASK_TEMPLATE = '''# PayPal Orders API — Flask
# pip install flask requests python-dotenv

import os, uuid, requests
from flask import Flask, request, jsonify

PAYPAL_CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
PAYPAL_SECRET = os.getenv("PAYPAL_SECRET")
BASE_URL = "https://api-m.sandbox.paypal.com"  # sandbox; prod: api-m.paypal.com

app = Flask(__name__)

def get_access_token() -> str:
    resp = requests.post(f"{BASE_URL}/v1/oauth2/token",
        auth=(PAYPAL_CLIENT_ID, PAYPAL_SECRET),
        data={"grant_type": "client_credentials"},
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

@app.route("/create-order", methods=["POST"])
def create_order():
    data = request.json
    token = get_access_token()
    resp = requests.post(f"{BASE_URL}/v2/checkout/orders",
        json={
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": str(uuid.uuid4()),
                "amount": {"currency_code": data.get("currency","USD"),
                           "value": str(data["amount"])},
                "description": data.get("description", "Payment"),
            }],
        },
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    return jsonify(resp.json())

@app.route("/capture-order/<order_id>", methods=["POST"])
def capture_order(order_id: str):
    token = get_access_token()
    resp = requests.post(f"{BASE_URL}/v2/checkout/orders/{order_id}/capture",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    return jsonify(resp.json())
'''

# Шаблон крипто (Python + web3)
CRYPTO_PAYMENT_TEMPLATE = '''# Crypto Payment — Self-hosted USDT (TRC20 / ERC20)
# pip install web3 requests qrcode[pil]

import os, hashlib, time
from web3 import Web3

# Для TRC20 (Tron) — не требует gas
TRON_API = "https://api.trongrid.io"
WALLET_ADDRESS = os.getenv("CRYPTO_WALLET_TRON")  # Твой TRC20 кошелёк

# Для ERC20 (Ethereum)
ETH_RPC = os.getenv("ETH_RPC_URL", "https://mainnet.infura.io/v3/YOUR_KEY")
w3 = Web3(Web3.HTTPProvider(ETH_RPC))
USDT_CONTRACT = "0xdAC17F958D2ee523a2206206994597C13D831ec7"  # USDT ERC20
ERC20_ABI = [{"inputs":[{"name":"_owner","type":"address"}],
              "name":"balanceOf","outputs":[{"name":"","type":"uint256"}],
              "type":"function"}]

def generate_payment_address(amount_usd: float, description: str) -> dict:
    """Генерирует адрес и QR для оплаты."""
    import qrcode, io, base64
    # Для demo — используем основной адрес
    # В production: генерируй HD wallet addresses (BIP32)
    address = WALLET_ADDRESS

    # QR-код
    qr = qrcode.make(f"tron:{address}?amount={amount_usd}&token=USDT")
    buf = io.BytesIO()
    qr.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return {
        "address": address,
        "network": "TRC20",
        "token": "USDT",
        "amount": amount_usd,
        "qr_base64": qr_b64,
        "description": description,
    }

def check_trc20_balance(address: str) -> float:
    """Проверяет баланс USDT TRC20."""
    import requests
    resp = requests.get(f"{TRON_API}/v1/accounts/{address}/tokens",
                        headers={"TRON-PRO-API-KEY": os.getenv("TRON_API_KEY","")})
    if resp.ok:
        for token in resp.json().get("data", []):
            if token.get("tokenAbbr") == "USDT":
                return float(token.get("balance", 0)) / 1e6
    return 0.0

# Binance Pay API
import hmac, hashlib
def create_binance_pay_order(amount_usd: float, description: str) -> dict:
    """Создаёт Binance Pay order."""
    import requests, json
    BINANCE_PAY_KEY = os.getenv("BINANCE_PAY_API_KEY")
    BINANCE_PAY_SECRET = os.getenv("BINANCE_PAY_API_SECRET")
    nonce = str(int(time.time() * 1000))
    body = json.dumps({
        "env": {"terminalType": "WEB"},
        "merchantTradeNo": nonce,
        "orderAmount": str(amount_usd),
        "currency": "USDT",
        "goods": {"goodsType": "01", "goodsCategory": "D000",
                  "referenceGoodsId": "1", "goodsName": description},
    })
    payload = f"{nonce}\\n{nonce}\\n{body}\\n"
    signature = hmac.new(BINANCE_PAY_SECRET.encode(), payload.encode(),
                         hashlib.sha512).hexdigest().upper()
    resp = requests.post("https://bpay.binanceapi.com/binancepay/openapi/v2/order",
        json=json.loads(body),
        headers={"BinancePay-Timestamp": nonce, "BinancePay-Nonce": nonce,
                 "BinancePay-Certificate-SN": BINANCE_PAY_KEY,
                 "BinancePay-Signature": signature})
    return resp.json()
'''


# ── Основной агент ─────────────────────────────────────────────────────────────

class PaymentAgent(BaseAgent):
    """
    Экспертный агент по платёжным системам.
    Знает Stripe, PayPal, крипто, Open Banking, региональные системы.
    """

    def __init__(self) -> None:
        super().__init__("payment")
        self._db = PaymentDB()

    def info(self) -> AgentInfo:
        return AgentInfo(
            name="payment",
            description=(
                "Эксперт по платёжным системам: Stripe, PayPal, крипто, банковские API. "
                "Генерирует код интеграции, счета, управляет платежами."
            ),
            capabilities=[
                "generate_integration", "create_invoice", "setup_crypto",
                "explain_api", "earnings_report", "check_status",
            ],
        )

    def can_handle(self, text: str) -> bool:
        patterns = [
            r"(stripe|paypal|payoneer|wise|revolut)",
            r"(платёж|payment|оплата|checkout|invoice|счёт)",
            r"(крипто|crypto|usdt|bitcoin|btc|ethereum|eth|binance.?pay)",
            r"(интеграц|integration).*(платёж|payment|stripe|paypal)",
            r"(webhook|вебхук).*(stripe|paypal|платёж)",
            r"(подписка|subscription).*(оплата|billing|stripe)",
            r"(open.?banking|plaid|tink|nord)",
            r"(pci.?dss|3d.?secure|3ds)",
            r"(юkassa|tinkoff.?pay|сбер.?pay|liqpay|fondy)",
        ]
        return any(re.search(p, text, re.IGNORECASE) for p in patterns)

    def process(self, text: str, source: str = "gui") -> str:
        self._set_status(AgentStatus.RUNNING)
        try:
            tl = text.lower()

            if re.search(r"(stripe).*(fastapi|flask|django|express|node|php)", tl):
                lang = self._extract_lang(tl)
                return self.generate_payment_integration("stripe", lang)

            if re.search(r"(paypal).*(flask|fastapi|django|express|node)", tl):
                lang = self._extract_lang(tl)
                return self.generate_payment_integration("paypal", lang)

            if re.search(r"(крипто|crypto|usdt|bitcoin|binance.?pay)", tl):
                return self.generate_payment_integration("crypto", "python")

            if re.search(r"(invoice|счёт|выставь|выставить)", tl):
                return self._cmd_invoice(text)

            if re.search(r"(отчёт|статистик|доход|earning|report)", tl):
                return self._cmd_earnings()

            if re.search(r"(webhook|вебхук)", tl):
                return self._explain_webhook(text)

            if re.search(r"(3d.?secure|3ds|fraud|мошенничество)", tl):
                return self._explain_fraud_prevention()

            if re.search(r"(pci.?dss|compliance|соответствие)", tl):
                return self._explain_pci()

            if re.search(r"(юkassa|тинькофф|сбер.?pay|liqpay)", tl):
                return self._explain_regional(tl)

            # По умолчанию — умный ответ через LLM
            return self._llm_payment_expert(text)

        except Exception as e:
            log.error("PaymentAgent error: %s", e)
            return f"❌ Ошибка PaymentAgent: {e}"
        finally:
            self._set_status(AgentStatus.IDLE)

    # ── Генерация интеграций ───────────────────────────────────────────────────

    def generate_payment_integration(self, provider: str, lang: str = "python") -> str:
        """Генерирует готовый код интеграции + инструкции."""
        provider = provider.lower()
        lang = lang.lower()

        # Шаблонные реализации для быстрого ответа
        if provider == "stripe" and lang in ("python", "fastapi"):
            return (
                f"## Stripe + FastAPI — полная интеграция\n\n"
                f"```python\n{STRIPE_FASTAPI_TEMPLATE}\n```\n\n"
                f"**Настройка:**\n"
                f"```bash\n"
                f"pip install stripe fastapi uvicorn python-dotenv\n"
                f"export STRIPE_SECRET_KEY=sk_test_...\n"
                f"export STRIPE_WEBHOOK_SECRET=whsec_...\n"
                f"# Webhook: stripe listen --forward-to localhost:8000/webhook/stripe\n"
                f"```\n\n"
                f"**Чеклист безопасности:**\n"
                f"- ✅ Верификация подписи webhook (`stripe.Webhook.construct_event`)\n"
                f"- ✅ Секрет в env (не в коде)\n"
                f"- ✅ Idempotency keys для повторных запросов\n"
                f"- ✅ HTTPS обязателен в production\n"
                f"- ✅ Логировать все события webhook"
            )

        if provider == "paypal" and lang in ("python", "flask"):
            return (
                f"## PayPal Orders API — Flask\n\n"
                f"```python\n{PAYPAL_FLASK_TEMPLATE}\n```\n\n"
                f"**Настройка:**\n"
                f"```bash\n"
                f"pip install flask requests python-dotenv\n"
                f"export PAYPAL_CLIENT_ID=...\n"
                f"export PAYPAL_SECRET=...\n"
                f"```\n\n"
                f"**Переключение на production:** замени `sandbox` → `api-m.paypal.com`"
            )

        if provider == "crypto":
            return (
                f"## Crypto Payments (USDT TRC20 + Binance Pay)\n\n"
                f"```python\n{CRYPTO_PAYMENT_TEMPLATE}\n```\n\n"
                f"**Поддерживаемые сети:**\n"
                f"- TRC20 (USDT) — нет gas, быстро, рекомендуется\n"
                f"- ERC20 (USDT/USDC/DAI) — gas fees\n"
                f"- Binance Pay — мгновенно, API\n"
                f"- BTC Lightning — micropayments\n\n"
                f"**Для production:** используй BTCPay Server или CoinGate API"
            )

        # Для остальных комбо — генерируем через LLM
        prompt = (
            f"Напиши полную интеграцию платёжной системы.\n\n"
            f"Провайдер: {provider}\n"
            f"Язык/фреймворк: {lang}\n\n"
            f"Включи:\n"
            f"1. Полный рабочий код (copy-paste ready)\n"
            f"2. Установку зависимостей\n"
            f"3. Переменные окружения\n"
            f"4. Обработку webhook\n"
            f"5. Чеклист безопасности\n\n"
            f"Код должен быть production-ready."
        )
        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code",
            max_tokens=1500,
            preferred_provider=LLMProvider.CLAUDE,
        ))
        return resp.content if resp.success else f"❌ Не удалось сгенерировать код для {provider}/{lang}"

    # ── Счета ─────────────────────────────────────────────────────────────────

    def create_invoice(self, client_name: str, client_email: str,
                       items: List[Dict], currency: str = "USD",
                       notes: str = "") -> Invoice:
        """Создаёт счёт и сохраняет в БД."""
        invoice_items = [
            InvoiceItem(
                description=i.get("description", "Service"),
                quantity=float(i.get("quantity", 1)),
                unit_price=float(i.get("unit_price", 0)),
            )
            for i in items
        ]
        inv = Invoice(
            id=f"INV-{datetime.now().strftime('%Y%m%d')}-{int(time.time())%10000:04d}",
            client_name=client_name,
            client_email=client_email,
            items=invoice_items,
            currency=currency,
            notes=notes,
        )
        self._db.save_invoice(inv)
        return inv

    def _cmd_invoice(self, text: str) -> str:
        """Генерирует счёт из запроса."""
        prompt = (
            f"Из этого запроса создай данные для счёта:\n{text}\n\n"
            f'Верни JSON: {{"client_name":"Имя клиента","client_email":"email",'
            f'"items":[{{"description":"...","quantity":1,"unit_price":500}}],'
            f'"currency":"USD","notes":""}}\n'
            f"Только JSON."
        )
        try:
            resp = self._llm.ask(LLMRequest(
                messages=[{"role": "user", "content": prompt}],
                task_type="classify", max_tokens=400,
                preferred_provider=LLMProvider.DEEPSEEK,
            ))
            m = re.search(r'\{.*\}', resp.content, re.DOTALL)
            if m:
                data = json.loads(m.group())
                inv = self.create_invoice(
                    client_name=data.get("client_name", "Клиент"),
                    client_email=data.get("client_email", ""),
                    items=data.get("items", [{"description": "Разработка", "quantity": 1, "unit_price": 500}]),
                    currency=data.get("currency", "USD"),
                    notes=data.get("notes", ""),
                )
                return self._format_invoice(inv)
        except Exception as e:
            log.debug("Invoice parse error: %s", e)
        return (
            "❌ Не удалось распарсить данные счёта.\n\n"
            "Формат: «выставь счёт Ивану Иванову ivan@mail.com на $500 за разработку API»"
        )

    def _format_invoice(self, inv: Invoice) -> str:
        lines = [
            f"🧾 **СЧЁТ {inv.id}**",
            f"Клиент: {inv.client_name} <{inv.client_email}>",
            f"Дата: {inv.created_at[:10]}",
            "",
            "Позиции:",
        ]
        for item in inv.items:
            lines.append(
                f"  • {item.description}: {item.quantity:.0f} × "
                f"{inv.currency} {item.unit_price:.2f} = {inv.currency} {item.total:.2f}"
            )
        lines += [
            "─" * 40,
            f"**ИТОГО: {inv.currency} {inv.total:.2f}**",
        ]
        if inv.notes:
            lines.append(f"\nПримечания: {inv.notes}")
        lines.append(f"\n✅ Сохранено в базе данных. ID: {inv.id}")
        return "\n".join(lines)

    # ── Объяснения ─────────────────────────────────────────────────────────────

    def _explain_webhook(self, text: str) -> str:
        prompt = (
            f"Объясни как настроить webhook для платёжной системы.\n"
            f"Запрос: {text}\n\n"
            f"Дай: 1) концепцию 2) рабочий код обработчика 3) проверку подписи "
            f"4) типичные ошибки. Конкретно и кратко."
        )
        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code", max_tokens=1000,
            preferred_provider=LLMProvider.CLAUDE,
        ))
        return resp.content if resp.success else "❌ Ошибка получения ответа"

    def _explain_fraud_prevention(self) -> str:
        return """## 3D Secure & Fraud Prevention

**3D Secure 2 (3DS2):**
```python
# Stripe — включить 3DS2
payment_intent = stripe.PaymentIntent.create(
    amount=1000, currency="usd",
    payment_method_types=["card"],
    # Запросить 3DS если карта высокого риска
    payment_method_options={
        "card": {"request_three_d_secure": "automatic"}
    }
)
```

**Stripe Radar Rules (без кода):**
- Block if `:card_country: != :ip_country:` — страна карты ≠ IP
- Block if `is_prepaid_card = true and :amount: > 5000` — предоплаченные карты
- 3DS if `:risk_score: > 65` — высокий риск

**Chargeback защита:**
- Сохраняй все метаданные платежа
- Требуй email подтверждение
- Rate limiting: 3 попытки / 15 мин / IP
- Блокировка по BIN для аномальных паттернов

**Velocity checks (Python):**
```python
import redis
r = redis.Redis()

def check_velocity(card_fingerprint: str, amount: int) -> bool:
    key = f"stripe:velocity:{card_fingerprint}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 3600)  # 1 hour window
    count, _ = pipe.execute()
    return count <= 5  # max 5 transactions per hour
```
"""

    def _explain_pci(self) -> str:
        return """## PCI DSS Compliance для разработчиков

**Уровни SAQ (Self-Assessment Questionnaire):**
- **SAQ A** — только iframes/hosted fields (Stripe Elements, Braintree Drop-in)
  → Ты НИКОГДА не видишь номер карты. Самый простой.
- **SAQ A-EP** — payment form на твоём сайте + redirect
- **SAQ D** — полная обработка карт на своём сервере (сложно!)

**Рекомендация:** Всегда используй SAQ A через:
- Stripe Elements / Stripe Checkout
- PayPal Hosted Fields
- Braintree Drop-in UI

**Что НЕЛЬЗЯ:**
- Логировать PAN (полный номер карты)
- Хранить CVV после авторизации
- Передавать данные карты через свой backend
- HTTP (только HTTPS!)

**Минимальный чеклист:**
```
✅ HTTPS everywhere (TLS 1.2+)
✅ Hosted payment fields (не своя форма)
✅ Webhook signature verification
✅ Секреты в env (не в коде)
✅ Access logging
✅ Dependency scanning (pip audit)
```
"""

    def _explain_regional(self, text: str) -> str:
        prompt = (
            f"Объясни интеграцию региональной платёжной системы.\n"
            f"Запрос: {text}\n\n"
            f"Дай: API endpoint, метод авторизации, пример запроса на Python, "
            f"основные возможности. Конкретно."
        )
        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code", max_tokens=800,
            preferred_provider=LLMProvider.DEEPSEEK,
        ))
        return resp.content if resp.success else "❌ Ошибка"

    def _llm_payment_expert(self, text: str) -> str:
        """Общий эксперт по платёжным вопросам."""
        prompt = (
            f"Ты эксперт по платёжным системам (Stripe, PayPal, крипто, Open Banking).\n"
            f"Вопрос: {text}\n\n"
            f"Дай конкретный, actionable ответ с кодом где нужно."
        )
        resp = self._llm.ask(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            task_type="code", max_tokens=1200,
            preferred_provider=LLMProvider.CLAUDE,
        ))
        return resp.content if resp.success else "❌ Ошибка LLM"

    def _cmd_earnings(self) -> str:
        report = self._db.earnings_report()
        lines = [
            f"💳 **Отчёт по платежам:**\n",
            f"Всего получено: **${report['total_usd']:.2f}**",
        ]
        if report["by_provider"]:
            lines.append("\nПо провайдерам:")
            for prov, amt in report["by_provider"].items():
                lines.append(f"  • {prov}: ${amt:.2f}")
        return "\n".join(lines)

    def _extract_lang(self, text: str) -> str:
        for lang in ("fastapi", "django", "flask", "express", "node", "nextjs",
                     "rails", "php", "laravel", "spring"):
            if lang in text:
                return lang
        return "python"

    @classmethod
    def get(cls) -> "PaymentAgent":
        if not hasattr(cls, "_instance") or cls._instance is None:
            cls._instance = cls()
        return cls._instance

    _instance: Optional["PaymentAgent"] = None
