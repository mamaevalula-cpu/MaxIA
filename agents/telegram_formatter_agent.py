from __future__ import annotations
import logging
log = logging.getLogger("agents.telegram_formatter")

class TelegramFormatterAgent:
    name = "telegram_formatter"
    def __init__(self): log.info("TelegramFormatterAgent OK")
    def format(self, text: str) -> str:
        if not text: return text
        while chr(10)*4 in text: text = text.replace(chr(10)*4, chr(10)*3)
        if len(text) > 3800: text = text[:3700] + chr(10) + chr(10) + "...[обрезано]"
        return text.strip()
    def split(self, text: str, size: int = 3800) -> list:
        if len(text) <= size: return [text]
        chunks = []; i = 0
        while i < len(text):
            end = min(i+size,len(text))
            if end < len(text):
                nl = text.rfind(chr(10),i,end)
                if nl > i: end = nl
            chunks.append(text[i:end]); i = end
        return chunks
    def process(self, text: str) -> str:
        return self.format(text)
