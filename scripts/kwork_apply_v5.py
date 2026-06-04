#!/usr/bin/env python3
"""Fixed Kwork Playwright Apply — uses JS click + modal wait."""
from playwright.sync_api import sync_playwright
from pathlib import Path
import time, re, json, random, urllib.request, os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT  = os.getenv("TELEGRAM_CHAT_ID", "1985320458")

def tg(msg):
    if not TOKEN: return
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}), timeout=5)
    except: pass

COOKIE_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")
STATE_FILE  = Path("/root/my_personal_ai/data/kwork_outreach_state.json")

def load_state():
    try: return json.loads(STATE_FILE.read_text())
    except: return {"applied_ids": [], "total": 0}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2))

PROPOSALS = [
    "MaxAI Corporation готова выполнить ваш проект! Специализируемся именно на таких задачах. Готовы приступить сегодня. Напишите в ЛС!",
    "Команда MaxAI — эксперты AI-разработки. Python, FastAPI, Telegram боты. Гарантия качества. Срок от 1 дня!",
    "MaxAI Corp: 50+ успешных проектов. Ваша задача — наша специализация. Срок от 1 дня. Пишите!",
    "Здравствуйте! MaxAI готова взяться за ваш проект. Python/AI/Telegram — наш профиль. Начнём сегодня!",
    "Отличный проект! MaxAI Corporation специализируется именно на таких задачах. Напишите в ЛС.",
]

# Try Redis proposals
try:
    import redis, json as _j
    r = redis.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    saved = r.get("maxai:kwork:proposals")
    if saved:
        loaded = _j.loads(saved)
        if loaded: PROPOSALS = loaded
except: pass

cookie_str = COOKIE_FILE.read_text().strip()
cookies_list = [{"name": k.strip(), "value": v.strip(), "domain": ".kwork.ru", "path": "/"}
                for part in cookie_str.split("; ") if "=" in part
                for k, _, v in [part.partition("=")]]

state = load_state()
applied_count = 0

print("Starting MaxAI Kwork Apply v2...")
tg("🔄 Kwork Apply v2 запущен...")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
        locale="ru-RU"
    )
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    # Navigate to projects list
    page.goto("https://kwork.ru/projects?c=41&page=1", timeout=25000, wait_until="networkidle")
    time.sleep(4)

    # Get project links via JS
    all_links = page.evaluate("""
        () => {
            const links = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                const m = a.href.match(/kwork\\.ru\\/projects\\/(\\d+)/);
                if (m) links.add(m[1]);
            });
            return Array.from(links);
        }
    """)

    print(f"Found {len(all_links)} project IDs")

    # Also scan category 67 (AI/Data)
    page.goto("https://kwork.ru/projects?c=67&page=1", timeout=20000, wait_until="networkidle")
    time.sleep(3)
    links2 = page.evaluate("""
        () => {
            const links = new Set();
            document.querySelectorAll('a[href]').forEach(a => {
                const m = a.href.match(/kwork\\.ru\\/projects\\/(\\d+)/);
                if (m) links.add(m[1]);
            });
            return Array.from(links);
        }
    """)
    all_links = list(set(all_links + links2))
    print(f"Total project IDs: {len(all_links)}")

    for pid in all_links[:10]:  # Try up to 10 projects
        if pid in state.get("applied_ids", []):
            continue

        try:
            page.goto(f"https://kwork.ru/projects/{pid}/view", timeout=15000, wait_until="networkidle")
            time.sleep(4)

            # Check if apply button exists using JS
            btn_info = page.evaluate("""
                () => {
                    const texts = ['Откликнуться', 'Предложить услугу', 'Написать предложение'];
                    for (const text of texts) {
                        const el = Array.from(document.querySelectorAll('button, a, div[role="button"]'))
                            .find(e => e.textContent.trim().includes(text));
                        if (el) return {found: true, text: el.textContent.trim(), tag: el.tagName};
                    }
                    return {found: false};
                }
            """)

            if not btn_info.get("found"):
                print(f"  {pid}: no apply button, skipping")
                continue

            title = page.title()[:60]
            print(f"  {pid}: APPLY BUTTON FOUND! Title: {title}")

            # Click via JS to avoid timeout
            clicked = page.evaluate("""
                () => {
                    const texts = ['Откликнуться', 'Предложить услугу', 'Написать предложение'];
                    for (const text of texts) {
                        const el = Array.from(document.querySelectorAll('button, a, div[role="button"]'))
                            .find(e => e.textContent.trim().includes(text));
                        if (el) { el.click(); return true; }
                    }
                    return false;
                }
            """)

            if not clicked:
                print(f"  {pid}: click failed")
                continue

            time.sleep(3)  # Wait for modal to open

            # Find textarea in modal
            try:
                textarea = page.locator("textarea").first
                textarea.wait_for(timeout=8000, state="visible")
                proposal_text = random.choice(PROPOSALS)
                textarea.fill(proposal_text)
                time.sleep(1)

                # Submit the form
                submit_btn = page.evaluate("""
                    () => {
                        const btns = Array.from(document.querySelectorAll('button[type="submit"], button.btn-red:not(.cancel)'));
                        const b = btns.find(b => b.textContent.trim().match(/отправ|submit|предлож/i));
                        if (b) { b.click(); return b.textContent.trim(); }
                        return null;
                    }
                """)

                time.sleep(2)

                if submit_btn:
                    applied_count += 1
                    state["applied_ids"].append(pid)
                    state["total"] = state.get("total", 0) + 1
                    save_state(state)
                    print(f"  ✅ APPLIED to {pid}: {title[:40]}")
                    tg(f"✅ Kwork отклик отправлен!\n{title[:60]}\nПредложение: {proposal_text[:100]}")
                else:
                    print(f"  {pid}: submit button not found after modal")

            except Exception as e:
                print(f"  {pid}: modal error: {str(e)[:80]}")

        except Exception as e:
            print(f"  {pid}: error: {str(e)[:60]}")

        if applied_count >= 3:  # Max 3 per run
            break

    browser.close()

print(f"\nDone. Applied: {applied_count} this run | Total: {state.get('total', 0)}")
if applied_count > 0:
    tg(f"✅ Kwork: {applied_count} откликов отправлено!")
else:
    tg(f"⚠️ Kwork: 0 откликов (все проекты уже обработаны или кнопка не найдена)")
