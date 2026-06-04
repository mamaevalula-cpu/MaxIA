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
    "MaxAI Corporation готова выполнить ваш проект! Специализируемся именно на таких задачах. Готовы приступить сегодня. Напишите в ЛС!",
    "Команда MaxAI — эксперты в разработке AI-решений. Python, FastAPI, Telegram боты, парсеры. Быстрая реализация (1-3 дня). Гарантия качества.",
    "MaxAI Corporation: 50+ успешных проектов, команда AI-специалистов. Ваша задача — наша специализация. Срок от 1 дня. Пишите!",
]

# Load from Redis if available
try:
    import redis as _rp, json as _jp
    _rdb = _rp.from_url("redis://127.0.0.1:6379/0", decode_responses=True)
    _saved = _rdb.get("maxai:kwork:proposals")
    if _saved:
        PROPOSALS = _jp.loads(_saved)
        print(f"Loaded {len(PROPOSALS)} proposals from Redis")
except Exception as _ep:
    pass
