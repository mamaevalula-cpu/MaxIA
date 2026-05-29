# Корпорация MaxAI — Официальный Бэклог
Дата создания: 2026-05-25 | Цель: $1000/день через 7 дней

## СТАТУС СИСТЕМЫ
- Panel chat: OK (model=fallback, responses work)
- Telegram bot: OK
- Bybit bot: $221.12 LIVE (trading paused, resets Monday 00:01 UTC)
- Earn: BLOCKED (нет API-права Earn → нужно включить вручную)
- LLM: DEGRADED (Groq 403, Anthropic no credits, нужен Gemini ключ)
- Revenue: $0.00 earned to date (non-trading)
- Agents: 89 файлов, ~5 реально работающих

## НУЖНО ОТ ПОЛЬЗОВАТЕЛЯ (блокирует доход)
1. [ ] bybit.com → API → O8NZsb1QOlQET3c3kH → Edit → включить Earn (+$0.04/день)
2. [ ] aistudio.google.com → Get API Key → прислать (GEMINI_KEY=AIzaSy...)
3. [ ] Kwork: проверить работает ли froggyinternet@gmail.com / Internetinternet!2

## БЭКЛОГ (приоритет по ROI)

### P0 — ИСПОЛНЯЕТСЯ СЕЙЧАС
- [x] Trading config оптимизирован (1% risk/trade, +BTC/ETH)
- [x] Monday 00:01 UTC cron restart bybit-monitor
- [x] smart_chat upgraded (live data, no LLM needed)
- [x] Telegram → panel AI routing
- [x] Revenue executor auto-Earn logic
- [ ] Kwork agent полный цикл (login → profile → offers → apply)
- [ ] Avito agent (Russian market AI services ads)

### P1 — ЭТА НЕДЕЛЯ ($0→$100/день)
- [ ] Kwork: 3-5 активных услуг (Python bot, AI automation, парсер)
- [ ] Avito: 5 объявлений/день (3000-15000 руб/заказ)
- [ ] MaxAI API endpoint (/api/v1/) — монетизация через RapidAPI
- [ ] Gemini LLM активировать (нужен ключ от пользователя)
- [ ] Bybit Earn активировать (нужно разрешение API)
- [ ] Trading Monday restart → цель +$1.5/день

### P2 — НЕДЕЛЯ 2 ($100→$500/день)
- [ ] Upwork profile (English market, $50-200/project)
- [ ] Fiverr gigs (AI services $20-100)
- [ ] Telegram канал с платными подписками (сигналы, AI инструменты)
- [ ] Agent rental API — $29/месяц за доступ к агенту
- [ ] MCP server публикация (Claude marketplace)
- [ ] 100+ агентов активно работают

### P3 — НЕДЕЛЯ 3-4 ($500→$1000/день)
- [ ] Массовый Kwork/Upwork (10 аккаунтов автоматизированы)
- [ ] B2B продажи (автоматизация для бизнеса $500-5000/контракт)
- [ ] Agent marketplace (покупка/аренда агентов)
- [ ] Copy trading публичный (привлечение инвесторов)
- [ ] API subscriptions (100 клиентов × $30/мес = $3000/мес)

## МЕТРИКИ (обновлять ежедневно)
| Метрика | Цель | Факт |
|---------|------|------|
| Revenue today | $1+ | $0 |
| Active earning agents | 10 | 0 |
| Kwork orders | 1 | 0 |
| Avito leads | 3 | 0 |
| Bybit PnL (weekly) | +$10 | -$19.46 |
| Earn APR income | $0.04/day | $0 |
| Total balance | $230+ | $221.12 |

## ЗАМОРОЖЕННЫЕ ПРОЕКТЫ (не трогать)
- hyperion_engine_v11_monorepo/ — заморожен
- hyperion_engine_v12/ — заморожен
- hyperion_command_center/ — заморожен
- hyperion_corporation_structure/ — заморожен
- Все projects/* кроме активно используемых

## ИНЦИДЕНТ-ЛОГ
- 2026-05-24: Weekly trading limit hit (-$19.46). Restart Monday.
- 2026-05-24: Groq API 403 from VPS IP (blocked). Workaround: smart_chat.
- 2026-05-24: Bybit login browser-blocked (2FA/anti-bot). Need manual Earn enable.
- 2026-05-24: Google AI Studio OAuth-only. Need manual Gemini key.
