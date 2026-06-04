#!/usr/bin/env python3
"""kwork_create_gigs.py - Creates new Kwork gigs in less competitive niches"""
import json, re, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"
COOKIE_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")
STATE_FILE  = Path("/root/my_personal_ai/data/kwork_gigs_created.json")

def tg(msg):
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            data=data, headers={"Content-Type":"application/json"}), timeout=8)
    except Exception: pass

NEW_GIGS = [
    {
        "title": "Напишу Python скрипт для автоматизации любой задачи",
        "desc": ("Напишу Python-скрипт под вашу задачу.\n"
                 "Что делаю:\n- Автоматизация повторяющихся задач\n"
                 "- Работа с Excel/Google Sheets\n- Парсинг данных\n"
                 "- Работа с API\n- Email рассылки\n"
                 "Вы получите рабочий скрипт + инструкцию + поддержку 3 дня.\n"
                 "Срок: 1-3 дня."),
        "price": "500",
    },
    {
        "title": "Автоматизирую Google Таблицы через Python или Apps Script",
        "desc": ("Автоматизирую ваши Google Таблицы.\n"
                 "Что умею:\n- Apps Script макросы\n- Python + gspread\n"
                 "- Автоматические отчёты\n- Синхронизация таблиц\n"
                 "- Связка с внешними API\nСрок: 1-2 дня."),
        "price": "600",
    },
    {
        "title": "Создам простого Telegram-бота для вашего бизнеса",
        "desc": ("Создам Telegram-бота без AI для бизнеса.\n"
                 "Функции: приём заявок, автоответы, кнопочное меню,\n"
                 "уведомления, интеграция с Google Sheets.\n"
                 "Идеально для магазинов и сервисов.\n"
                 "Срок: 1-2 дня. Поддержка неделю."),
        "price": "800",
    },
]

def try_fill_gig(page, gig):
    print("Creating:", gig["title"][:50])
    try:
        page.goto("https://kwork.ru/new", timeout=20000, wait_until="networkidle")
        time.sleep(6)

        # Try to set language to RU
        try:
            page.locator("input[value='ru']").first.check()
            time.sleep(0.5)
        except Exception: pass

        # Fill title
        title_inp = page.locator("input[name='title'], textarea[name='title']").first
        title_inp.wait_for(timeout=5000, state="visible")
        title_inp.fill(gig["title"])
        time.sleep(0.5)

        # Category: find and select IT/Development
        try:
            cat_sel = page.locator("select[name='parentCategories']").first
            cat_sel.wait_for(timeout=5000, state="visible")
            cats = cat_sel.locator("option").all()
            for cat in cats:
                txt = cat.inner_text().strip()
                if "Разработка" in txt or "IT" in txt:
                    val = cat.get_attribute("value") or ""
                    if val:
                        cat_sel.select_option(value=val)
                        time.sleep(1)
                        print("  Cat:", txt[:40])
                        break
        except Exception as e: print("  cat err:", e)

        # Subcategory: automation/scripts
        try:
            subcat = page.locator("select[name='categories']").first
            subcat.wait_for(timeout=3000, state="visible")
            sub_opts = subcat.locator("option").all()
            for s in sub_opts:
                stxt = s.inner_text().strip()
                if any(w in stxt for w in ["Скрипт", "Автомат", "Бот", "Python"]):
                    sv = s.get_attribute("value") or ""
                    if sv:
                        subcat.select_option(value=sv)
                        time.sleep(0.5)
                        print("  Subcat:", stxt[:40])
                        break
        except Exception: pass

        # Description
        try:
            desc_area = page.locator("textarea[name='description']").first
            desc_area.wait_for(timeout=4000, state="visible")
            desc_area.fill(gig["desc"])
            time.sleep(0.5)
        except Exception as e: print("  desc err:", e)

        # Set work time (delivery days)
        try:
            wt = page.locator("select[name='work_time']").first
            wt.wait_for(timeout=3000)
            wt.select_option(value="2")
        except Exception: pass

        # Submit
        for btn_txt in ["Сохранить и опубликовать", "Опубликовать", "Создать кворк", "Сохранить"]:
            try:
                btn = page.get_by_text(btn_txt, exact=False).first
                btn.wait_for(timeout=3000, state="visible")
                btn.click()
                time.sleep(5)
                print("  Clicked:", btn_txt)
                cur = page.url
                print("  URL after:", cur[:70])
                if "manage" in cur or "offer" in cur:
                    return True
                break
            except Exception: pass

        # Check for success indicators
        body = page.inner_text("body")[:200]
        if "успешно" in body.lower() or "опубликован" in body.lower():
            return True
        return False

    except Exception as e:
        print("  Error:", e)
        return False

def main():
    state = {}
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    except Exception: pass

    if not COOKIE_FILE.exists():
        print("No Kwork cookies"); return

    cookie_str = COOKIE_FILE.read_text().strip()
    cookies_list = [{"name":k.strip(),"value":v.strip(),"domain":".kwork.ru","path":"/"}
                    for p in cookie_str.split("; ") if "=" in p for k,_,v in [p.partition("=")]]

    created_titles = state.get("created_titles", [])
    success = 0

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox","--disable-gpu"])
        ctx = b.new_context(user_agent="Mozilla/5.0 Chrome/120", viewport={"width":1280,"height":900})
        ctx.add_cookies(cookies_list)
        page = ctx.new_page()

        # Verify session
        page.goto("https://kwork.ru/seller", timeout=15000, wait_until="domcontentloaded")
        time.sleep(3)
        print("Session URL:", page.url[:60])

        for gig in NEW_GIGS:
            if gig["title"] in created_titles:
                print("Skip (exists):", gig["title"][:40])
                continue
            ok = try_fill_gig(page, gig)
            if ok:
                success += 1
                created_titles.append(gig["title"])
                state["created_titles"] = created_titles
                STATE_FILE.write_text(json.dumps(state, indent=2))
                tg("Kwork gig created: " + gig["title"][:60])
                print("SUCCESS:", gig["title"][:50])
            else:
                print("FAIL:", gig["title"][:50])
            time.sleep(2)

        ctx.close(); b.close()

    print(f"Done: {success}/{len(NEW_GIGS)} gigs created")
    if success > 0:
        tg(f"Kwork: {success} new gigs created!")

if __name__ == "__main__":
    main()
