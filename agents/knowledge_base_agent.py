from __future__ import annotations
import logging, sqlite3, time
log = logging.getLogger("agents.knowledge_base")
DB = "/root/my_personal_ai/data/knowledge_base.db"

class KnowledgeBaseAgent:
    name = "knowledge_base"
    def __init__(self):
        conn = sqlite3.connect(DB)
        conn.execute("CREATE TABLE IF NOT EXISTS kb(id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, tags TEXT, ts REAL)")
        conn.commit(); conn.close()
        log.info("KnowledgeBaseAgent OK")
    def save(self, title: str, content: str, tags: str = "") -> str:
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO kb(title,content,tags,ts) VALUES(?,?,?,?)", (title,content,tags,time.time()))
        conn.commit(); conn.close()
        return f"Saved: {title}"
    def search(self, query: str) -> str:
        q = f"%{query}%"; conn = sqlite3.connect(DB)
        rows = conn.execute("SELECT title,content FROM kb WHERE title LIKE ? OR content LIKE ? LIMIT 5",(q,q)).fetchall()
        conn.close()
        return chr(10).join(f"{r[0]}: {r[1][:200]}" for r in rows) if rows else f"Not found: {query}"
    def list_topics(self) -> str:
        conn = sqlite3.connect(DB)
        rows = conn.execute("SELECT title FROM kb ORDER BY ts DESC LIMIT 20").fetchall()
        conn.close()
        return chr(10).join(f"  - {r[0]}" for r in rows) if rows else "Empty"
    def process(self, text: str) -> str:
        if "найди" in text.lower() or "search" in text.lower():
            return self.search(text.split(None,1)[-1])
        return "KnowledgeBase:" + chr(10) + self.list_topics()
