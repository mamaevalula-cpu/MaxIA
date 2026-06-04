from playwright.sync_api import sync_playwright
import json, time, re, random, urllib.request
from pathlib import Path

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"
COOKIES_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")
STATE_FILE = Path("/root/my_personal_ai/data/kwork_outreach_state.json")

# Professional Russian proposals (loaded from Redis if available)
PROPOSALS = [
    "MaxAI Corporation - готова выполнить ваш проект! Специализируемся именно на таких задачах. Готовы приступить сегодня.",
    "Команда MaxAI — эксперты AI-разработки. Python, FastAPI, Telegram боты. Гарантия качества. Срок от 1 дня!",
    "MaxAI Corp: 50+ успешных проектов. Ваша задача — наша специализация. Пишите в ЛС!",
    "Здравствуйте! MaxAI готова взяться за ваш проект. Python/AI/Telegram — наш профиль. Начнем сегодня!",
    "Отличный проект! MaxAI Corporation специализируется именно на таких задачах. Напишите в ЛС.",
]
try:
    import redis as _rp, json as _jr
    _rdb = _rp.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    _saved = _rdb.get("maxai:kwork:proposals")
    if _saved:
        _loaded = _jr.loads(_saved)
        if _loaded: PROPOSALS = _loaded
except: pass

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data, headers={"Content-Type":"application/json"}), timeout=8)
    except: pass

def load_state():
    try: return json.loads(STATE_FILE.read_text())
    except: return {"applied_ids": [], "total": 0}

def save_state(s): STATE_FILE.write_text(json.dumps(s, indent=2))

state = load_state()
cookie_str = COOKIES_FILE.read_text().strip()
cookies_list = [{"name":k.strip(),"value":v.strip(),"domain":".kwork.ru","path":"/"}
                for part in cookie_str.split("; ") if "=" in part
                for k,_,v in [part.partition("=")]]

print("Starting Kwork outreach via Playwright...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--ozone-platform=headless"])
    ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/120", viewport={"width":1280,"height":900})
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    try:
        page.goto("https://kwork.ru/projects?c=41&page=1", timeout=25000, wait_until="networkidle")
        time.sleep(6)
        print("URL:", page.url[:60])
        print("Title:", page.title()[:50])

        html = page.content()
        project_links = list(set(re.findall(r'href="(/projects/[0-9]+)"', html)))
        print("Project links found:", len(project_links))

        if not project_links:
            # Get page text
            body = page.inner_text("body")
            lines = [l.strip() for l in body.split("\n") if len(l.strip()) > 20]
            print("Page lines sample:", lines[:10])

        applied = 0
        for link in project_links[:5]:
            pid_m = re.search(r"/projects/(\d+)", link)
            if not pid_m: continue
            pid = pid_m.group(1)
            if pid in state.get("applied_ids", []): continue

            try:
                page.goto("https://kwork.ru" + link, timeout=15000, wait_until="domcontentloaded")
                time.sleep(4)

                # Try multiple selectors for the apply button
                apply_btn = None
                selectors = [
                    "button:has-text('Откликнуться')",
                    "button:has-text('Отклик')",
                    "button:has-text('Предложить услугу')",
                    ".want-btn",
                    "[data-name='offer']",
                    "a:has-text('Откликнуться')",
                ]
                for sel in selectors:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible(timeout=2000):
                            apply_btn = btn
                            break
                    except: pass
                if not apply_btn:
                    apply_btn = page.locator("button:has-text('Откликнуться')").first
                try:
                    apply_btn.wait_for(timeout=5000, state="visible")
                    apply_btn.click()
                    time.sleep(2)

                    textarea = page.locator("textarea").first
                    textarea.wait_for(timeout=8000, state="visible")
                    textarea.fill(random.choice(PROPOSALS))
                    time.sleep(0.5)

                    submit = page.locator("button[type='submit']").first
                    submit.click()
                    time.sleep(3)

                    state["applied_ids"].append(pid)
                    state["total"] = state.get("total", 0) + 1
                    applied += 1
                    print(f"Applied to {pid}! Total: {state['total']}")
                    tg(f"Kwork applied!\nProject: {pid}\nTotal: {state['total']}")
                    time.sleep(2)
                except Exception as e2:
                    print(f"  Apply error {pid}: {e2}")

            except Exception as e:
                print(f"  Error {pid}: {e}")

        if applied == 0:
            print("No new projects applied. Saving state.")
            tg("Kwork: session ok, 0 new projects applied this run")

    except Exception as e:
        print("Error:", str(e)[:200])
        tg("Kwork error: " + str(e)[:100])

    ctx.close()
    browser.close()

save_state(state)
print("Done. Total applied:", state.get("total", 0))
