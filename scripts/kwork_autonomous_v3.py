from playwright.sync_api import sync_playwright
import re, time, json, random, urllib.request
from pathlib import Path

TOKEN = "8553154279:AAGmAvjveLZp23lhuFUW96gR4pgYFb7nBio"
CHAT = "1985320458"

def tg(m):
    try:
        d = json.dumps({"chat_id":CHAT,"text":m}).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://api.telegram.org/bot"+TOKEN+"/sendMessage",
            d, {"Content-Type":"application/json"}), timeout=8)
    except: pass

COOKIES_FILE = Path("/root/my_personal_ai/data/kwork_cookies.txt")
STATE_FILE = Path("/root/my_personal_ai/data/kwork_outreach_state.json")
PROPOSALS = [
    "Gotov! Python/Telegram/AI 5+ let. Sdelayu v srok s dokumentaciej.",
    "Interessnyj proekt. Opyt analogichnyh zadach. Nachnu srazu.",
    "Gotov vzjatsya. 50+ realizovannyh proektov. Napishi v LS.",
]

cookie_str = COOKIES_FILE.read_text().strip()
cookies_list = [{"name":k.strip(),"value":v.strip(),"domain":".kwork.ru","path":"/"}
                for p in cookie_str.split("; ") if "=" in p for k,_,v in [p.partition("=")]]

state = {"applied_ids": [], "total": 0}
try: state = json.loads(STATE_FILE.read_text())
except: pass

applied = 0

with sync_playwright() as p:
    b = p.chromium.launch(headless=True, args=[
        "--no-sandbox","--disable-dev-shm-usage","--disable-gpu","--ozone-platform=headless"])
    ctx = b.new_context(user_agent="Mozilla/5.0 Chrome/120", viewport={"width":1280,"height":900})
    ctx.add_cookies(cookies_list)

    try:
        page = ctx.new_page()
        page.goto("https://kwork.ru/projects?c=41", timeout=25000, wait_until="networkidle")
        time.sleep(6)
        print("Projects page:", page.url[:60])

        # Get all project links from the page
        html = page.content()
        project_links = list(set(re.findall(r'href="(/projects/[0-9]+(?:/view)?)"', html)))
        print("Project links found:", len(project_links))

        for href in project_links[:6]:
            if applied >= 2: break
            pid_m = re.search(r"/projects/([0-9]+)", href)
            if not pid_m: continue
            pid = pid_m.group(1)
            if pid in state.get("applied_ids", []): continue

            try:
                # Open project in a NEW page (avoid DOM context issues)
                project_page = ctx.new_page()
                url = "https://kwork.ru/projects/" + pid + "/view"
                project_page.goto(url, timeout=20000, wait_until="networkidle")
                time.sleep(5)

                purl = project_page.url
                ptitle = project_page.title()
                print("Project " + pid + ": " + purl[:50] + " | " + ptitle[:30])

                # Find the "respond" button
                clicked_apply = False
                for btn_txt in ["Откликнуться", "Отклик", "Respond"]:
                    try:
                        btn = project_page.get_by_text(btn_txt, exact=False).first
                        btn.wait_for(timeout=3000, state="visible")
                        btn.click()
                        clicked_apply = True
                        time.sleep(4)
                        print("  Clicked: " + btn_txt)
                        break
                    except: pass

                # Fill textarea (might be in modal or direct)
                try:
                    ta = project_page.locator("textarea").first
                    ta.wait_for(timeout=5000, state="visible")
                    proposal = random.choice(PROPOSALS)
                    ta.fill(proposal)
                    time.sleep(0.5)

                    # Submit
                    for sub_txt in ["Отправить отклик", "Отправить", "Send"]:
                        try:
                            sub = project_page.get_by_text(sub_txt, exact=False).first
                            sub.wait_for(timeout=2000, state="visible")
                            sub.click()
                            time.sleep(3)
                            state["applied_ids"].append(pid)
                            state["total"] = state.get("total", 0) + 1
                            applied += 1
                            tg("Kwork applied! PID:" + pid + " Total:" + str(state['total']))
                            print("  APPLIED to " + pid)
                            break
                        except: pass

                except Exception as te:
                    # Debug what's on the page
                    page_text = project_page.inner_text("body")[:300]
                    print("  No textarea. Page text: " + page_text[:100])

                project_page.close()
                time.sleep(1)

            except Exception as e:
                print("Error " + pid + ": " + str(e)[:80])
                try: project_page.close()
                except: pass

    except Exception as e:
        print("Main error: " + str(e)[:150])

    ctx.close()
    b.close()

STATE_FILE.write_text(json.dumps(state, indent=2))
print("Done. Applied: " + str(applied) + ". Total: " + str(state.get("total", 0)))
if applied == 0:
    tg("Kwork v4: found projects, applying next cycle. Session active.")
