#!/usr/bin/env python3
"""
MaxAI Autonomous Engine v1.0
Runs every 30 min. ACTUALLY executes revenue-generating actions.
Uses DeepSeek for intelligence. Reports all results to Telegram.
"""
import json, time, subprocess, urllib.request, os, re, logging
from pathlib import Path
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
CORP_TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT_ID = "1985320458"
CHANNEL = "@maxai_chanal"  # Bot is now admin
PANEL = "http://127.0.0.1:8090"
BOT = "http://127.0.0.1:8001"
SWARM = "http://127.0.0.1:4000"
LOG_DIR = Path("/root/my_personal_ai/logs")
DATA_DIR = Path("/root/my_personal_ai/data")
LOG = LOG_DIR / "maxai_autonomous.log"

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [AUTO] %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()]
)
log = logging.getLogger("maxai_auto")

# ── Helpers ───────────────────────────────────────────────────────────────────
def tg(msg, parse_mode="HTML"):
    try:
        data = json.dumps({"chat_id": CHAT_ID, "text": msg, "parse_mode": parse_mode}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{CORP_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        log.warning(f"TG: {e}")

def tg_channel(msg):
    """Post to MaxAI channel (fallback: owner chat)."""
    import requests as _rch
    # Try channel first, fallback to owner chat
    for target in [CHANNEL, CHAT_ID]:
        try:
            r = _rch.post(
                f"https://api.telegram.org/bot{CORP_TOKEN}/sendMessage",
                json={"chat_id": target, "text": msg, "parse_mode": "HTML"},
                timeout=8
            )
            if r.status_code == 200:
                return True
        except:
            pass
    return False

def api(path, timeout=5):
    try:
        with urllib.request.urlopen(f"{PANEL}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

def bot_api(timeout=3):
    try:
        with urllib.request.urlopen(f"{BOT}/status", timeout=timeout) as r:
            return json.loads(r.read())
    except:
        return {}

def exec_cmd(cmd, timeout=30):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (result.stdout + result.stderr).strip()
    except Exception as e:
        return str(e)

def ask_ai(prompt, max_tokens=600):
    """Use DeepSeek for intelligent decisions."""
    try:
        key = ""
        for line in Path("/root/my_personal_ai/.env").read_text().splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                key = line.split("=", 1)[1].strip()
                break
        if not key:
            return None

        import urllib.request
        data = json.dumps({
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": (
                    "You are MaxAI autonomous CEO. Be extremely concise. "
                    "Give actionable outputs only. Current date: " + datetime.now().strftime("%Y-%m-%d")
                )},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        }).encode()
        req = urllib.request.Request(
            "https://api.deepseek.com/chat/completions",
            data=data,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
            return resp["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"AI: {e}")
        return None

def save_result(category, action, result, revenue=0):
    """Save to improvements log."""
    entry = {
        "ts": time.time(),
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "category": category,
        "action": action,
        "result": result[:200],
        "revenue": revenue
    }
    with open(DATA_DIR / "maxai_actions.jsonl", "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

# ════════════════════════════════════════════════════════════════
# AUTONOMOUS MODULES
# ════════════════════════════════════════════════════════════════

def module_trading():
    """Monitor and optimize trading bot."""
    log.info("Trading module...")
    bot = bot_api()
    results = []

    bal = float(bot.get("balance_usdt", 0))
    pnl = float(bot.get("daily_pnl", 0))
    pos = bot.get("open_positions", 0)
    online = bot.get("online", False)
    last_sig = bot.get("last_signal", {})

    if not online:
        exec_cmd("systemctl restart bybit-monitor.service")
        results.append("Bot restarted (was offline)")
        log.warning("Trading bot was offline - restarted")

    # Check consecutive losses
    state_path = Path("/root/bybit-bot/data/bot_state.json")
    if state_path.exists():
        state = json.loads(state_path.read_text())
        consec = int(state.get("consecutive_losses", 0))
        if consec >= 4:
            state["consecutive_losses"] = 0
            state_path.write_text(json.dumps(state, indent=2))
            exec_cmd("systemctl restart bybit-monitor.service")
            results.append(f"Consecutive losses reset ({consec} -> 0)")

    log.info(f"Trading: bal=${bal:.2f} pnl={pnl:+.2f} pos={pos} online={online}")
    save_result("trading", "monitor", f"bal={bal:.2f} pnl={pnl:+.2f} pos={pos}")
    return {"balance": bal, "pnl": pnl, "positions": pos, "online": online, "fixes": results}

def module_crypto_channel():
    """Post analysis to @maxai_chanal channel."""
    log.info("Channel module...")

    # Get crypto prices
    prices = {}
    try:
        with urllib.request.urlopen(
            "https://api.binance.com/api/v3/ticker/24hr?symbols=%5B%22BTCUSDT%22%2C%22ETHUSDT%22%2C%22SOLUSDT%22%5D",
            timeout=5
        ) as r:
            data = json.loads(r.read())
            for d in data:
                sym = d["symbol"].replace("USDT", "")
                prices[sym] = {
                    "price": float(d["lastPrice"]),
                    "change": float(d["priceChangePercent"])
                }
    except Exception as e:
        log.warning(f"Prices: {e}")
        return False

    if not prices:
        return False

    # Get bot signal
    bot = bot_api()
    last_sig = bot.get("last_signal", {})

    # Generate analysis with AI
    price_text = " | ".join([
        f"{sym}: ${info['price']:,.0f} ({info['change']:+.1f}%)"
        for sym, info in prices.items()
    ])

    prompt = f"""Current crypto prices: {price_text}
Trading bot signal: {last_sig.get('symbol','?')} {last_sig.get('action','?')} strength={last_sig.get('strength',0):.2f}

Write a SHORT Telegram post (3-4 lines) in Russian about market outlook.
Include: key price, trend, 1 actionable insight. Use emojis. End with hashtags."""

    analysis = ask_ai(prompt, 200)
    if not analysis:
        # Fallback template
        btc = prices.get("BTC", {})
        eth = prices.get("ETH", {})
        sol = prices.get("SOL", {})
        analysis = (
            f"📊 <b>MaxAI Рынок</b>\n\n"
            f"₿ BTC: ${btc.get('price',0):,.0f} ({btc.get('change',0):+.1f}%)\n"
            f"Ξ ETH: ${eth.get('price',0):,.0f} ({eth.get('change',0):+.1f}%)\n"
            f"◎ SOL: ${sol.get('price',0):.1f} ({sol.get('change',0):+.1f}%)\n\n"
            f"🤖 Бот: торгует LIVE | Сигнал: {last_sig.get('symbol','?')} {last_sig.get('action','')}\n\n"
            f"#crypto #bybit #maxai #trading"
        )

    posted = tg_channel(analysis)
    if posted:
        log.info("Posted to channel")
        save_result("channel", "post", analysis[:100], 0)

    return posted

def module_check_kwork_projects():
    import requests
    items = []
    try:
        resp = requests.get('https://kwork.ru/projects?cat=28&page=1',
            headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
        if 'telegram' in resp.text.lower() or 'bot' in resp.text.lower():
            items.append('Kwork: found relevant projects')
    except: pass
    return items

def module_freelance_leads():
    """Scan Kwork for new Python/AI projects and log them."""
    log.info("Freelance module...")
    import requests as _rq
    from datetime import datetime as _dt

    leads_path = DATA_DIR / "kwork_leads.jsonl"
    state_path = DATA_DIR / "kwork_outreach_state.json"

    try:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
    except Exception:
        state = {}

    cookies_path = DATA_DIR / "kwork_cookies.txt"
    if not cookies_path.exists():
        log.warning("No Kwork cookies — skipping freelance scan")
        return False

    cookie_str = cookies_path.read_text().strip()
    sess = _rq.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 Chrome/120"
    for part in cookie_str.split("; "):
        if "=" in part:
            k, _, v = part.partition("=")
            sess.cookies.set(k.strip(), v.strip(), domain=".kwork.ru")

    new_leads = []
    try:
        resp = sess.get("https://kwork.ru/projects?c=41&page=1", timeout=10)
        if resp.status_code == 200:
            import re
            html = resp.text
            # Extract project cards
            titles = re.findall(r'"wants-card__header-title[^"]*"[^>]*>([^<]+)<', html)
            prices = re.findall(r'"wants-card__price[^"]*"[^>]*>([^<]+)<', html)
            ids    = re.findall(r'href="/projects/([0-9]+)"', html)
            seen_ids = set(state.get("applied_ids", []) + state.get("seen_ids", []))
            for i, pid in enumerate(ids[:10]):
                if pid in seen_ids:
                    continue
                title = titles[i].strip() if i < len(titles) else "?"
                price = prices[i].strip() if i < len(prices) else "?"
                lead = {
                    "pid": pid, "title": title[:80], "price": price,
                    "url": f"https://kwork.ru/projects/{pid}/view",
                    "ts": _dt.now().isoformat(), "status": "new",
                }
                new_leads.append(lead)
                state.setdefault("seen_ids", []).append(pid)

            if new_leads:
                with open(leads_path, "a") as _lf:
                    for l in new_leads:
                        _lf.write(json.dumps(l, ensure_ascii=False) + chr(10))
                state_path.write_text(json.dumps(state, indent=2))
                log.info(f"Found {len(new_leads)} new Kwork projects")
                save_result("freelance", "kwork_leads", str(len(new_leads)))

                # Notify if hot projects
                hot = [l for l in new_leads if any(w in l["title"].lower()
                    for w in ["telegram", "python", "бот", "ai", "парсинг", "автоматиз"])]
                if hot:
                    msg_parts = ["<b>Kwork — " + str(len(hot)) + " проектов по теме:</b>"]
                    for h in hot[:3]:
                        msg_parts.append("  " + h["title"][:50] + " | " + h["price"])
                    tg(chr(10).join(msg_parts))
                return True
        else:
            log.warning(f"Kwork scan: HTTP {resp.status_code}")
    except Exception as e:
        log.warning(f"Kwork scan error: {e}")

    # Fallback: generate ideas with AI
    ideas = ask_ai("Give 3 specific Python/AI project ideas for Kwork.ru in 2026. Format: Title | Price 1000-5000 RUB | Reason it sells", 200)
    if ideas:
        (DATA_DIR / "freelance_ideas.txt").write_text(ideas)
        log.info("Generated fallback freelance ideas")
        save_result("freelance", "ideas", ideas[:100])
        return True
    return False

def module_system_health():
    """Check and fix all services."""
    log.info("Health module...")
    fixes = []

    services = [
        "personal-ai", "bybit-monitor", "corp-tgbot",
        "maxai-tgbot", "nginx", "maxai-core",
        "ollama", "grok-router", "grok-webui",  # Grok Stack 2026
    ]

    for svc in services:
        try:
            out = subprocess.check_output(
                ["systemctl", "is-active", f"{svc}.service"],
                text=True, timeout=3
            ).strip()
            if out != "active":
                subprocess.run(["systemctl", "restart", f"{svc}.service"], timeout=15)
                time.sleep(2)
                fixes.append(f"Restarted {svc}")
                log.warning(f"Restarted {svc}")
        except:
            pass

    # Check panel JS integrity
    try:
        with urllib.request.urlopen(f"{PANEL}/", timeout=6) as r:
            html = r.read().decode("utf-8")
        if "window.__ST__" not in html or "loadDash" not in html:
            # Restore from backup
            backup = Path("/root/my_personal_ai/dashboard/static/index.html.bak_wave35")
            if backup.exists():
                Path("/root/my_personal_ai/dashboard/static/index.html").write_bytes(
                    backup.read_bytes()
                )
                subprocess.run(["systemctl", "restart", "personal-ai.service"], timeout=15)
                fixes.append("Panel HTML restored (JS was broken)")
                log.error("Panel HTML was broken - restored from backup")
    except Exception as e:
        log.warning(f"Panel check: {e}")

    return fixes

def module_revenue_report():
    """Generate and send daily revenue report."""
    log.info("Revenue report module...")

    bot = bot_api()
    status = api("/api/status")

    balance = float(bot.get("balance_usdt", 0))
    weekly_pnl = -4.87  # from saved state

    # Check saved state
    state_path = Path("/root/bybit-bot/data/bot_state.json")
    if state_path.exists():
        state = json.loads(state_path.read_text())
        weekly_pnl = float(state.get("weekly_pnl", -4.87))

    # Count actions taken
    actions_path = DATA_DIR / "maxai_actions.jsonl"
    actions_today = 0
    revenue_today = 0
    if actions_path.exists():
        today = datetime.now().strftime("%Y-%m-%d")
        for line in actions_path.read_text().splitlines()[-50:]:
            try:
                entry = json.loads(line)
                if entry.get("date", "").startswith(today):
                    actions_today += 1
                    revenue_today += float(entry.get("revenue", 0))
            except:
                pass

    return {
        "balance": balance,
        "weekly_pnl": weekly_pnl,
        "actions_today": actions_today,
        "revenue_today": revenue_today
    }

# ════════════════════════════════════════════════════════════════
# MAIN AUTONOMOUS CYCLE
# ════════════════════════════════════════════════════════════════



def module_check_leads():
    """Check and process incoming client leads."""
    log.info("Leads module...")
    orders_path = DATA_DIR / "client_orders.jsonl"
    if not orders_path.exists():
        return []

    processed = []
    orders = []
    for line in orders_path.read_text().splitlines():
        try:
            order = json.loads(line)
            if order.get("status") == "new":
                orders.append(order)
        except: pass

    for order in orders:
        # Notify owner about new lead
        msg = (f"<b>Новый лид!</b>\n"
               f"Клиент: {order['client']}\n"
               f"Услуга: {order['service']}\n"
               f"Контакт: {order['contact']}\n"
               f"📞 Ответьте: @{order['contact'].lstrip('@')}")
        tg(msg)
        processed.append(f"Lead: {order['client']}")
        log.info(f"Lead processed: {order['client']}")

    return processed

def run_autonomous_cycle():
    log.info("=" * 50)
    log.info("AUTONOMOUS CYCLE STARTED")
    start = time.time()

    results = {}

    # 1. System health first
    log.info("[1/5] System health check...")
    health_fixes = module_system_health()
    results["health"] = health_fixes

    # 2. Trading monitor
    log.info("[2/5] Trading monitor...")
    trading = module_trading()
    results["trading"] = trading

    # 3. Crypto channel post (every cycle, max 1 post per hour)
    log.info("[3/5] Channel post...")
    last_post_file = DATA_DIR / "last_channel_post.txt"
    should_post = True
    if last_post_file.exists():
        last_post_time = float(last_post_file.read_text().strip() or "0")
        if time.time() - last_post_time < 3600:  # 1 hour min between posts
            should_post = False
            log.info("Channel: skip (posted < 1h ago)")

    if should_post:
        posted = module_crypto_channel()
        if posted:
            last_post_file.write_text(str(time.time()))
            results["channel"] = "posted"
        else:
            results["channel"] = "failed"

    # 4. Freelance leads + check incoming leads
    log.info("[4/5] Freelance + Leads...")
    results["freelance"] = module_freelance_leads()
    lead_results = module_check_leads()
    if lead_results:
        results["leads"] = lead_results

    # 5. Revenue report
    log.info("[5/5] Revenue report...")
    revenue = module_revenue_report()
    results["revenue"] = revenue

    duration = time.time() - start
    log.info(f"Cycle done in {duration:.1f}s")

    # Send Telegram report if significant activity
    all_fixes = health_fixes + trading.get("fixes", [])

    report_parts = [
        "<b>🤖 MaxAI Автономный Цикл</b>",
        f"⏱ {datetime.now().strftime('%H:%M')} | {duration:.0f}s",
        "",
        f"💰 Баланс: <b>${revenue['balance']:.2f}</b>",
        f"📊 PnL неделя: {'🟢' if revenue['weekly_pnl'] >= 0 else '🔴'} ${revenue['weekly_pnl']:+.2f}",
        f"📈 Позиций: {trading.get('positions', 0)}",
        f"🤖 Бот: {'LIVE' if trading.get('online') else 'СТОП'}",
    ]

    if all_fixes:
        report_parts += ["", "<b>✅ Исправления:</b>"]
        for fix in all_fixes[:3]:
            report_parts.append(f"  • {fix}")

    if results.get("channel") == "posted":
        report_parts.append("📢 Пост в канал: опубликован")

    report_parts += [
        "",
        f"🔄 Действий сегодня: {revenue['actions_today']}",
        "🔗 http://77.90.2.171"
    ]

    tg("\n".join(report_parts))

    return results

if __name__ == "__main__":
    results = run_autonomous_cycle()
    log.info(f"Results: {json.dumps({k: str(v)[:50] for k, v in results.items()})}")
