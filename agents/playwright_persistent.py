#!/usr/bin/env python3
"""
Playwright Persistent Browser Agent — MaxAI OMEGA v21
Manages persistent browser profiles for authenticated sessions.
User logs in manually; agent saves session and continues from there.
"""
import asyncio, json, os, logging
from pathlib import Path

log = logging.getLogger("playwright_agent")
PROFILES_DIR = Path("/root/my_personal_ai/data/browser_profiles")
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

# ── Temporal checkpoint system (Phase 4) ────────────────────────────────────
CHECKPOINTS_DIR = Path("/root/my_personal_ai/data/checkpoints")
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

def save_checkpoint(agent_id: str, state: dict):
    """Save agent state for crash recovery."""
    import time
    cp = CHECKPOINTS_DIR / f"{agent_id}.json"
    state["_checkpoint_ts"] = time.time()
    cp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    log.info("Checkpoint saved: %s", agent_id)

def load_checkpoint(agent_id: str) -> dict:
    """Load agent state from last checkpoint."""
    cp = CHECKPOINTS_DIR / f"{agent_id}.json"
    if cp.exists():
        try:
            state = json.loads(cp.read_text())
            log.info("Checkpoint loaded: %s (age=%.0fs)", agent_id,
                    __import__("time").time() - state.get("_checkpoint_ts", 0))
            return state
        except Exception as e:
            log.warning("Checkpoint load failed: %s", e)
    return {}

def delete_checkpoint(agent_id: str):
    cp = CHECKPOINTS_DIR / f"{agent_id}.json"
    if cp.exists():
        cp.unlink()

# ── Browser session management ───────────────────────────────────────────────
async def launch_persistent_session(profile: str = "default", url: str = None,
                                     headless: bool = True) -> dict:
    """Launch browser with persistent profile (saves cookies/localStorage)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"ok": False, "error": "playwright not installed. Run: pip install playwright && playwright install chromium"}

    profile_dir = PROFILES_DIR / profile
    profile_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(profile_dir),
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="ru-RU",
        )

        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        result = {"ok": True, "profile": profile, "profile_dir": str(profile_dir)}

        if url:
            try:
                await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                result["title"] = await page.title()
                result["url"] = page.url
                # Save checkpoint
                save_checkpoint(f"browser_{profile}", {"url": page.url, "title": result.get("title","")})
            except Exception as e:
                result["navigate_error"] = str(e)

        # Get cookies count (session health indicator)
        cookies = await ctx.cookies()
        result["cookies"] = len(cookies)
        result["logged_in"] = len(cookies) > 5  # heuristic: many cookies = logged in

        await ctx.close()
        return result

async def get_profile_status(profile: str = "default") -> dict:
    """Check if profile has saved session."""
    profile_dir = PROFILES_DIR / profile
    if not profile_dir.exists():
        return {"exists": False, "profile": profile}

    # Check localStorage/cookies files
    cookies_file = profile_dir / "Default" / "Cookies"
    ls_file = profile_dir / "Default" / "Local Storage" / "leveldb"

    return {
        "exists": True,
        "profile": profile,
        "profile_dir": str(profile_dir),
        "has_cookies": cookies_file.exists(),
        "has_local_storage": ls_file.exists() if ls_file else False,
        "size_mb": round(sum(f.stat().st_size for f in profile_dir.rglob("*") if f.is_file()) / 1024**2, 2),
        "checkpoint": load_checkpoint(f"browser_{profile}"),
    }

async def list_profiles() -> list:
    """List all saved browser profiles."""
    if not PROFILES_DIR.exists():
        return []
    return [
        await get_profile_status(d.name)
        for d in PROFILES_DIR.iterdir()
        if d.is_dir()
    ]

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    profile = sys.argv[2] if len(sys.argv) > 2 else "default"

    if cmd == "status":
        r = asyncio.run(get_profile_status(profile))
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif cmd == "launch":
        url = sys.argv[3] if len(sys.argv) > 3 else None
        r = asyncio.run(launch_persistent_session(profile, url))
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif cmd == "list":
        r = asyncio.run(list_profiles())
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif cmd == "checkpoint":
        state = load_checkpoint(profile)
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        print(f"Commands: status [profile], launch [profile] [url], list, checkpoint [agent_id]")
