from __future__ import annotations
import logging, time, threading, os
log = logging.getLogger("agents.auto_responder")

class AutoResponderAgent:
    name = "auto_responder"
    def __init__(self):
        self._sent: set = set()
        threading.Thread(target=self._run, daemon=True, name="auto_responder").start()
        log.info("AutoResponderAgent OK")
    def send_digest(self, period: str = "now") -> str:
        try:
            import httpx; from dotenv import load_dotenv
            load_dotenv("/root/my_personal_ai/.env")
            tok = os.getenv("TELEGRAM_BOT_TOKEN",""); cid = os.getenv("TELEGRAM_CHAT_ID","")
            greet = {"morning":"Доброе утро!","evening":"Добрый вечер!","now":"Статус:"}
            msg = "[АПЕКСМИНД] " + greet.get(period,"") + chr(10) + "Система активна." + chr(10) + time.strftime("%H:%M")
            if tok and cid:
                httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id":cid,"text":msg}, timeout=8)
            return msg
        except Exception as e:
            return f"AutoResponder error: {e}"
    def _run(self):
        while True:
            try:
                now = time.localtime(); day = now.tm_yday
                if now.tm_hour == 8 and f"m{day}" not in self._sent:
                    self.send_digest("morning"); self._sent.add(f"m{day}")
                elif now.tm_hour == 20 and f"e{day}" not in self._sent:
                    self.send_digest("evening"); self._sent.add(f"e{day}")
            except Exception as e:
                log.error("AutoResponder: %s", e)
            time.sleep(60)
    def process(self, text: str) -> str:
        return self.send_digest("now")
