#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_learn.py - Daily external knowledge fetcher.

Fetches:
  1. Top 5 AI papers from arXiv (cs.AI + cs.LG, last 24h)
  2. Top 5 trending GitHub AI repos

Adds each item to the knowledge base via POST http://localhost:8090/api/knowledge/add
Logs everything to /root/my_personal_ai/logs/daily_learn.log
"""

import json
import logging
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# -- Logging setup -------------------------------------------------------------
LOG_FILE = Path("/root/my_personal_ai/logs/daily_learn.log")
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("daily_learn")

# -- Constants -----------------------------------------------------------------
API_URL = "http://localhost:8090/api/knowledge/add"
TIMEOUT = 10
ARXIV_URL = (
    "http://export.arxiv.org/api/query"
    "?search_query=cat:cs.AI+OR+cat:cs.LG"
    "&sortBy=submittedDate&sortOrder=descending&max_results=5"
)
GITHUB_URL = (
    "https://api.github.com/search/repositories"
    "?q=artificial+intelligence+OR+machine+learning+OR+LLM"
    "&sort=stars&order=desc&per_page=5"
)
ARXIV_NS = "http://www.w3.org/2005/Atom"


# -- Helpers -------------------------------------------------------------------

def http_get(url, headers=None):
    """GET request with timeout; returns bytes or None on error."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.URLError as e:
        log.warning("GET %s failed: %s", url, e)
        return None
    except Exception as e:
        log.warning("GET %s unexpected error: %s", url, e)
        return None


def post_knowledge(title, content, category, tags, importance=0.8):
    """POST one knowledge entry to the local API. Returns True on success."""
    payload = json.dumps({
        "title": title,
        "content": content,
        "category": category,
        "tags": json.dumps(tags),
        "importance": importance,
    }).encode("utf-8")
    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                log.info("  Added id=%s: %s", result.get("id"), title[:80])
                return True
            else:
                log.warning("  API rejected: %s | %s", title[:60], result.get("error"))
                return False
    except Exception as e:
        log.warning("  API error (%s), falling back to SQLite for: %s", e, title[:60])
        return sqlite_insert(title, content, category, tags, importance)


def sqlite_insert(title, content, category, tags, importance):
    """Direct SQLite insert as fallback when API is unavailable."""
    try:
        import sqlite3
        db_path = "/root/my_personal_ai/data/memory.db"
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute(
            "INSERT OR IGNORE INTO knowledge (title, content, category, tags, importance, ts) "
            "VALUES (?,?,?,?,?,?)",
            (title, content, category, json.dumps(tags), importance, time.time()),
        )
        con.commit()
        new_id = cur.lastrowid
        con.close()
        log.info("  SQLite inserted id=%s: %s", new_id, title[:80])
        return True
    except Exception as e:
        log.error("  SQLite insert failed: %s", e)
        return False


# -- Fetchers ------------------------------------------------------------------

def fetch_arxiv_papers():
    """Fetch top 5 recent papers from arXiv cs.AI / cs.LG."""
    log.info("Fetching arXiv papers ...")
    raw = http_get(ARXIV_URL)
    if not raw:
        log.warning("arXiv fetch returned nothing.")
        return []

    papers = []
    try:
        root = ET.fromstring(raw)
        entries = root.findall("{%s}entry" % ARXIV_NS)
        for entry in entries[:5]:
            def txt(tag):
                el = entry.find("{%s}%s" % (ARXIV_NS, tag))
                return el.text.strip() if el is not None and el.text else ""

            arxiv_id_url = txt("id")
            title = txt("title").replace("\n", " ").replace("  ", " ")
            summary = txt("summary").replace("\n", " ").replace("  ", " ")
            published = txt("published")
            authors_els = entry.findall("{%s}author" % ARXIV_NS)
            authors = ", ".join(
                (a.find("{%s}name" % ARXIV_NS).text or "").strip()
                for a in authors_els[:3]
                if a.find("{%s}name" % ARXIV_NS) is not None
            )
            cat_el = entry.find("{http://arxiv.org/schemas/atom}primary_category")
            categories = [cat_el.get("term", "cs.AI")] if cat_el is not None else ["cs.AI"]

            papers.append({
                "title": "[arXiv] " + title,
                "content": (
                    "Source: " + arxiv_id_url + "\n"
                    "Authors: " + authors + "\n"
                    "Published: " + published + "\n\n"
                    "Abstract:\n" + summary
                ),
                "tags": ["arxiv", "ai-paper", "auto-fetched"] + categories[:2],
            })
    except ET.ParseError as e:
        log.error("arXiv XML parse error: %s", e)

    log.info("arXiv: fetched %d papers.", len(papers))
    return papers


def fetch_github_repos():
    """Fetch top 5 trending AI repos from GitHub search API."""
    log.info("Fetching GitHub trending AI repos ...")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "daily-learn-bot/1.0",
    }
    raw = http_get(GITHUB_URL, headers=headers)
    if not raw:
        log.warning("GitHub fetch returned nothing.")
        return []

    repos = []
    try:
        data = json.loads(raw)
        items = data.get("items", [])[:5]
        for item in items:
            name = item.get("full_name", "unknown")
            desc = item.get("description") or "No description."
            stars = item.get("stargazers_count", 0)
            language = item.get("language") or "N/A"
            url = item.get("html_url", "")
            topics = item.get("topics", [])[:5]
            pushed = item.get("pushed_at", "")

            repos.append({
                "title": "[GitHub] " + name,
                "content": (
                    "Repository: " + url + "\n"
                    "Stars: " + str(stars) + "\n"
                    "Language: " + language + "\n"
                    "Last pushed: " + pushed + "\n"
                    "Topics: " + (", ".join(topics) or "none") + "\n\n"
                    "Description:\n" + desc
                ),
                "tags": ["github", "trending", "ai", "auto-fetched"] + topics[:3],
            })
    except (json.JSONDecodeError, KeyError) as e:
        log.error("GitHub parse error: %s", e)

    log.info("GitHub: fetched %d repos.", len(repos))
    return repos


# -- Main ----------------------------------------------------------------------

def main():
    start = time.time()
    log.info("=" * 60)
    log.info("daily_learn.py started at %s", datetime.now(timezone.utc).isoformat())

    added = 0
    failed = 0

    # 1. arXiv papers
    papers = fetch_arxiv_papers()
    for paper in papers:
        ok = post_knowledge(
            title=paper["title"],
            content=paper["content"],
            category="ai-paper",
            tags=paper["tags"],
            importance=0.85,
        )
        if ok:
            added += 1
        else:
            failed += 1

    # 2. GitHub trending repos
    repos = fetch_github_repos()
    for repo in repos:
        ok = post_knowledge(
            title=repo["title"],
            content=repo["content"],
            category="github-trending",
            tags=repo["tags"],
            importance=0.75,
        )
        if ok:
            added += 1
        else:
            failed += 1

    elapsed = time.time() - start
    log.info(
        "daily_learn.py finished in %.1fs | added=%d | failed=%d",
        elapsed, added, failed,
    )
    log.info("=" * 60)
    return added


if __name__ == "__main__":
    main()
