#!/usr/bin/env python3
"""
Kwork Auto-Outreach Bot
Finds relevant Python/Telegram/AI projects and auto-applies
Uses existing session cookies
"""
import requests, json, re, time, urllib.request
from pathlib import Path
from datetime import datetime

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"
COOKIES_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")
STATE_FILE = Path("/root/my_personal_ai/data/kwork_outreach_state.json")
LOG_FILE = Path("/root/my_personal_ai/logs/kwork_outreach.log")

SEARCH_QUERIES = ["telegram bot", "python bot", "ai chatgpt", "автоматизация python", "парсер python"]
MAX_APPLY_PER_RUN = 3
MIN_BUDGET = 1000  # Min project budget in RUB

PROPOSAL_TEMPLATES = [
    "Привет! Готов взяться за задачу. Python/Telegram/AI — моя специализация. Выполню качественно, в срок, с документацией. Уточни детали в ЛС.",
    "Интересный проект! Имею опыт с похожими задачами. Сделаю быстро и качественно. Начну сразу после обсуждения деталей.",
    "Готов выполнить. Опыт: 50+ аналогичных проектов. Python, Telegram API, ChatGPT интеграции. Напишите в ЛС для уточнения.",
]

import logging
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [KWORK] %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger("kwork_outreach")

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"}), timeout=8)
    except: pass

def load_state():
    try: return json.loads(STATE_FILE.read_text())
    except: return {"applied": [], "total_applied": 0, "last_run": None}

def save_state(s): STATE_FILE.write_text(json.dumps(s, indent=2))

def make_session():
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"
    cookie_str = COOKIES_FILE.read_text().strip()
    for part in cookie_str.split("; "):
        if "=" in part:
            k, _, v = part.partition("=")
            session.cookies.set(k.strip(), v.strip(), domain=".kwork.ru")
    return session

def find_projects(session, query, page=1):
    """Find relevant projects on Kwork."""
    try:
        # Try projects/marketplace section
        url = f"https://kwork.ru/projects?c=41&q={requests.utils.quote(query)}&page={page}"
        resp = session.get(url, timeout=10)
        if resp.status_code != 200:
            return []

        html = resp.text
        # Extract project data
        projects = []

        # Find project cards
        titles = re.findall(r'"wants-card__header-title[^"]*"[^>]*>([^<]+)<', html)
        prices = re.findall(r'"wants-card__price[^"]*"[^>]*>([^<]+)<', html)
        links = re.findall(r'href="(/projects/[0-9]+[^"]*)"', html)

        for i, title in enumerate(titles[:10]):
            title = title.strip()
            if len(title) < 10:
                continue
            project = {
                "title": title,
                "price": prices[i].strip() if i < len(prices) else "?",
                "link": links[i] if i < len(links) else "",
                "query": query,
                "id": re.search(r'/projects/(\d+)', links[i]).group(1) if i < len(links) and links[i] else ""
            }
            projects.append(project)

        log.info("Found %d projects for query '%s'", len(projects), query)
        return projects

    except Exception as e:
        log.warning("Find projects error: %s", e)
        return []

def apply_to_project(session, project, proposal, state):
    """Apply to a Kwork project."""
    proj_id = project.get("id", "")
    if not proj_id or proj_id in state.get("applied", []):
        return False

    try:
        csrf = session.cookies.get("csrf_user_token", "")
        resp = session.post(
            f"https://kwork.ru/api/projects/{proj_id}/apply",
            json={"offer_text": proposal},
            headers={
                "X-Csrf-Token": csrf,
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"https://kwork.ru/projects/{proj_id}"
            },
            timeout=10
        )
        log.info("Apply to %s: status=%d response=%s", proj_id, resp.status_code, resp.text[:100])

        if resp.status_code in [200, 201]:
            state["applied"].append(proj_id)
            return True
        return False
    except Exception as e:
        log.warning("Apply error for %s: %s", proj_id, e)
        return False

def main():
    log.info("=== KWORK OUTREACH RUN ===")

    if not COOKIES_FILE.exists():
        log.error("No cookies file. Cannot run.")
        tg("Kwork outreach: no cookies. Run kwork_session_v4.py first.")
        return

    state = load_state()
    session = make_session()

    # Verify session
    resp = session.get("https://kwork.ru/seller", timeout=8)
    if "seller" not in resp.url:
        log.error("Session expired!")
        tg("Kwork session expired. New cookies needed.")
        return

    log.info("Session valid. Searching projects...")
    applied_this_run = 0
    found_projects = []

    # Search across all queries
    for query in SEARCH_QUERIES:
        if applied_this_run >= MAX_APPLY_PER_RUN:
            break
        projects = find_projects(session, query)
        found_projects.extend(projects)
        time.sleep(1)

    # Deduplicate
    seen_ids = set()
    unique_projects = []
    for p in found_projects:
        if p["id"] and p["id"] not in seen_ids and p["id"] not in state.get("applied", []):
            seen_ids.add(p["id"])
            unique_projects.append(p)

    log.info("Unique new projects: %d", len(unique_projects))

    # Apply to best ones
    import random
    for project in unique_projects[:MAX_APPLY_PER_RUN]:
        if applied_this_run >= MAX_APPLY_PER_RUN:
            break

        proposal = random.choice(PROPOSAL_TEMPLATES)
        success = apply_to_project(session, project, proposal, state)

        if success:
            applied_this_run += 1
            state["total_applied"] = state.get("total_applied", 0) + 1
            log.info("Applied to: %s | total=%d", project["title"][:50], state["total_applied"])
            tg(f"Applied to Kwork project:\n{project['title'][:60]}\n\nTotal applied: {state['total_applied']}")
            time.sleep(2)

    state["last_run"] = datetime.now().isoformat()
    state["projects_found_last"] = len(unique_projects)
    save_state(state)

    log.info("Run complete. Applied: %d this run, %d total", applied_this_run, state.get("total_applied", 0))

    if applied_this_run == 0 and len(unique_projects) == 0:
        log.info("No new projects found this run.")
    elif applied_this_run == 0:
        log.info("Found %d projects but none new to apply to.", len(unique_projects))

if __name__ == "__main__":
    main()
