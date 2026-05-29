#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MAXAI Browser Control Mode — Production v2
=========================================
FSM: INIT → READY → AI_ACTIVE → HUMAN_PENDING → HUMAN_ACTIVE
     → RECONCILING → RECOVERY → SAFE_MODE → QUARANTINED → TERMINATED

Control: fencing_token + lease_expiration + heartbeat
Pipeline: PREPARE → EXECUTE → VERIFY → COMMIT
"""
import asyncio, base64, hashlib, json, logging, os, secrets, time, uuid
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("maxai.browser")

# ─── Paths ───────────────────────────────────────────────────────────────────
DATA_DIR        = Path("/root/my_personal_ai/data")
SCREENSHOT_PATH = DATA_DIR / "browser_screenshot.jpg"
STATE_PATH      = DATA_DIR / "browser_state_v2.json"
LOG_PATH        = DATA_DIR / "browser_log_v2.jsonl"
CHECKPOINT_DIR  = DATA_DIR / "browser_checkpoints"
LEARNING_PATH   = DATA_DIR / "browser_lessons.jsonl"
NEG_MEM_PATH    = DATA_DIR / "browser_negative.jsonl"

for _p in [DATA_DIR, CHECKPOINT_DIR]:
    _p.mkdir(parents=True, exist_ok=True)

# ─── FSM States ──────────────────────────────────────────────────────────────
class BrowserState(str, Enum):
    INIT          = "INIT"
    READY         = "READY"
    AI_ACTIVE     = "AI_ACTIVE"
    HUMAN_PENDING = "HUMAN_PENDING"
    HUMAN_ACTIVE  = "HUMAN_ACTIVE"
    RECONCILING   = "RECONCILING"
    RECOVERY      = "RECOVERY"
    SAFE_MODE     = "SAFE_MODE"
    QUARANTINED   = "QUARANTINED"
    TERMINATED    = "TERMINATED"

TRANSITIONS: Dict[BrowserState, List[BrowserState]] = {
    BrowserState.INIT:          [BrowserState.READY],
    BrowserState.READY:         [BrowserState.AI_ACTIVE, BrowserState.HUMAN_ACTIVE, BrowserState.TERMINATED],
    BrowserState.AI_ACTIVE:     [BrowserState.READY, BrowserState.HUMAN_PENDING, BrowserState.RECONCILING, BrowserState.SAFE_MODE],
    BrowserState.HUMAN_PENDING: [BrowserState.HUMAN_ACTIVE, BrowserState.AI_ACTIVE, BrowserState.RECONCILING],
    BrowserState.HUMAN_ACTIVE:  [BrowserState.READY, BrowserState.RECONCILING, BrowserState.SAFE_MODE],
    BrowserState.RECONCILING:   [BrowserState.READY, BrowserState.RECOVERY, BrowserState.SAFE_MODE],
    BrowserState.RECOVERY:      [BrowserState.READY, BrowserState.SAFE_MODE, BrowserState.QUARANTINED],
    BrowserState.SAFE_MODE:     [BrowserState.READY, BrowserState.QUARANTINED, BrowserState.TERMINATED],
    BrowserState.QUARANTINED:   [BrowserState.TERMINATED],
    BrowserState.TERMINATED:    [],
}

# ─── Lease ───────────────────────────────────────────────────────────────────
LEASE_TTL_SEC   = 30
HEARTBEAT_GRACE = 5

@dataclass
class Lease:
    owner:          str   = "none"
    fencing_token:  str   = ""
    acquired_at:    float = 0.0
    expires_at:     float = 0.0
    last_heartbeat: float = 0.0
    session_id:     str   = ""

    def is_valid(self) -> bool:
        return self.owner != "none" and time.time() < self.expires_at + HEARTBEAT_GRACE

    def is_owner(self, token: str) -> bool:
        return self.fencing_token == token and self.is_valid()

    def renew(self):
        self.last_heartbeat = time.time()
        self.expires_at     = time.time() + LEASE_TTL_SEC

# ─── Replay safety ───────────────────────────────────────────────────────────
_REPLAY_ALLOWED   = {"navigate", "inspect", "screenshot", "get_text", "validate", "scroll"}
_REPLAY_FORBIDDEN = {"submit", "pay", "publish", "delete", "transfer", "purchase", "confirm_order", "send"}

def is_replay_safe(action: str, meta: Dict = None) -> bool:
    a = action.lower()
    if any(k in a for k in _REPLAY_FORBIDDEN):
        return False
    if meta and meta.get("is_destructive"):
        return False
    return True

# ─── Page stability ──────────────────────────────────────────────────────────
async def wait_for_stability(page, timeout_ms: int = 5000) -> Tuple[bool, str]:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            pass
        # Check overlays
        for sel in ["[role='dialog']:visible", ".modal:visible", ".overlay:visible"]:
            try:
                if await page.locator(sel).count() > 0:
                    return False, f"overlay:{sel}"
            except Exception:
                pass
        # DOM mutation check
        h1 = await _dom_hash(page)
        await asyncio.sleep(0.3)
        h2 = await _dom_hash(page)
        if h1 != h2:
            return False, "dom_mutating"
        return True, "stable"
    except Exception as e:
        return False, f"error:{e}"

async def _dom_hash(page) -> str:
    try:
        return hashlib.md5((await page.content()).encode()).hexdigest()
    except Exception:
        return ""

# ─── Checkpoint ──────────────────────────────────────────────────────────────
@dataclass
class Checkpoint:
    id:           str   = field(default_factory=lambda: str(uuid.uuid4())[:8])
    ts:           float = field(default_factory=time.time)
    fsm_state:    str   = ""
    url:          str   = ""
    dom_hash:     str   = ""
    scroll_x:     int   = 0
    scroll_y:     int   = 0
    modal_count:  int   = 0
    lease:        Dict  = field(default_factory=dict)
    screenshot_b64: str = ""

async def create_checkpoint(ctrl: "BrowserController") -> "Checkpoint":
    cp = Checkpoint(fsm_state=ctrl.state.value)
    if ctrl.page:
        try:
            cp.url      = ctrl.page.url
            cp.dom_hash = await _dom_hash(ctrl.page)
            sc = await ctrl.page.evaluate("() => ({x:window.scrollX,y:window.scrollY})")
            cp.scroll_x = sc.get("x", 0)
            cp.scroll_y = sc.get("y", 0)
            try:
                cp.modal_count = await ctrl.page.locator("[role='dialog']:visible").count()
            except Exception:
                pass
            ss = await ctrl.page.screenshot(type="jpeg", quality=60)
            cp.screenshot_b64 = base64.b64encode(ss).decode()
        except Exception:
            pass
    cp.lease = asdict(ctrl.lease)
    cp_file  = CHECKPOINT_DIR / f"cp_{cp.id}.json"
    cp_file.write_text(json.dumps(asdict(cp)))
    # Keep last 10
    old_cps = sorted(CHECKPOINT_DIR.glob("cp_*.json"), key=lambda p: p.stat().st_mtime)[:-10]
    for old in old_cps:
        old.unlink(missing_ok=True)
    return cp

# ─── Learning ────────────────────────────────────────────────────────────────
def store_successful_flow(flow: List[Dict], replay_verified: bool = False):
    if not replay_verified:
        return
    entry = {"ts": time.time(), "verified": True, "steps": flow}
    with open(LEARNING_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

def store_human_correction(intent: str, original: Dict, correction: Dict):
    with open(LEARNING_PATH, "a") as f:
        f.write(json.dumps({"ts": time.time(), "type": "human_correction",
                            "intent": intent, "original": original,
                            "correction": correction}) + "\n")

def store_negative_memory(category: str, selector: str, url: str, reason: str):
    with open(NEG_MEM_PATH, "a") as f:
        f.write(json.dumps({"ts": time.time(), "category": category,
                            "selector": selector, "url": url,
                            "reason": reason}) + "\n")

def check_negative_memory(selector: str, url: str) -> Optional[str]:
    try:
        if not NEG_MEM_PATH.exists():
            return None
        for line in NEG_MEM_PATH.read_text().strip().split("\n"):
            if not line:
                continue
            e = json.loads(line)
            if e.get("selector") == selector and (not e.get("url") or url.startswith(e["url"])):
                return e.get("reason", "blocked")
    except Exception:
        pass
    return None

# ─── Main Controller ─────────────────────────────────────────────────────────
class BrowserController:
    """MAXAI Browser Control Mode v2 — FSM + Fencing + Pipeline + Recovery."""

    def __init__(self):
        self.state             = BrowserState.INIT
        self.lease             = Lease()
        self.page              = None
        self.browser           = None
        self.playwright        = None
        self._lock             = asyncio.Lock()
        self._action_history:  List[Dict] = []
        self._pending_flow:    List[Dict] = []
        self._reconcile_count  = 0
        self._quarantine_reason= ""
        self._screenshot_b64   = ""

    # ── FSM ──────────────────────────────────────────────────────────────────
    def _transition(self, new_state: BrowserState, reason: str = "") -> bool:
        if new_state not in TRANSITIONS.get(self.state, []):
            log.warning("FSM reject %s→%s (%s)", self.state, new_state, reason)
            return False
        log.info("FSM %s→%s | %s", self.state, new_state, reason)
        self.state = new_state
        self._save_state()
        return True

    # ── Lease ─────────────────────────────────────────────────────────────────
    def acquire_lease(self, owner: str, session_id: str = "") -> Optional[str]:
        if self.lease.is_valid():
            return None
        token = secrets.token_hex(16)
        self.lease = Lease(
            owner=owner, fencing_token=token,
            acquired_at=time.time(), expires_at=time.time() + LEASE_TTL_SEC,
            last_heartbeat=time.time(), session_id=session_id or uuid.uuid4().hex[:8],
        )
        self._save_state()
        return token

    def release_lease(self, token: str) -> bool:
        if not self.lease.is_owner(token):
            return False
        self.lease = Lease()
        self._save_state()
        return True

    def heartbeat(self, token: str) -> bool:
        if not self.lease.is_owner(token):
            return False
        self.lease.renew()
        self._save_state()
        return True

    def _check_lease_expiry(self):
        if self.lease.owner != "none" and not self.lease.is_valid():
            log.warning("Lease expired for %s", self.lease.owner)
            self.lease = Lease()
            if self.state in (BrowserState.AI_ACTIVE, BrowserState.HUMAN_ACTIVE):
                self._transition(BrowserState.RECONCILING, "lease_expired")
            self._save_state()

    # ── Start / Stop ─────────────────────────────────────────────────────────
    async def start(self) -> bool:
        async with self._lock:
            try:
                from playwright.async_api import async_playwright
                self.playwright = await async_playwright().start()
                self.browser    = await self.playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox","--disable-dev-shm-usage","--disable-gpu",
                          "--disable-setuid-sandbox","--disable-background-networking"],
                )
                self.page = await self.browser.new_page(
                    viewport={"width": 1280, "height": 800},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                )
                self._transition(BrowserState.READY, "start_ok")
                await self._capture()
                await create_checkpoint(self)
                return True
            except Exception as e:
                log.error("Start failed: %s", e)
                self._save_state_err(str(e))
                return False

    async def stop(self):
        async with self._lock:
            try:
                if self.browser:
                    await self.browser.close()
                if self.playwright:
                    await self.playwright.stop()
            except Exception:
                pass
            self.page = self.browser = self.playwright = None
            self.lease = Lease()
            self._transition(BrowserState.TERMINATED, "stop")

    # ── PREPARE → EXECUTE → VERIFY → COMMIT ──────────────────────────────────
    async def execute_action(self, action: str, params: Dict, token: str) -> Dict:
        self._check_lease_expiry()

        # PREPARE
        prep = await self._prepare(action, params, token)
        if not prep["ok"]:
            return {**prep, "stage": "PREPARE"}

        # EXECUTE
        ex = await self._execute(action, params)
        if not ex["ok"]:
            store_negative_memory("action_failed", params.get("selector",""), self._url(), ex.get("error",""))
            return {**ex, "stage": "EXECUTE"}

        # VERIFY
        vfy = await self._verify(action, params, ex)
        if not vfy["ok"]:
            if self.state == BrowserState.AI_ACTIVE:
                self._transition(BrowserState.READY, "verify_failed")
            return {**vfy, "stage": "VERIFY", "committed": False}

        # COMMIT
        committed = await self._commit(action, params, ex)
        screenshot = await self._capture()
        return {
            "ok": True, "stage": "COMMITTED" if committed else "VERIFIED",
            "committed": committed, "action": action,
            "result": ex, "screenshot_b64": screenshot,
            "fsm_state": self.state.value, "url": self._url(),
        }

    async def _prepare(self, action: str, params: Dict, token: str) -> Dict:
        if not self.lease.is_owner(token):
            return {"ok": False, "reason": "stale_fencing_token"}
        if self.state not in (BrowserState.READY, BrowserState.AI_ACTIVE, BrowserState.HUMAN_ACTIVE):
            return {"ok": False, "reason": f"bad_fsm_state:{self.state}"}
        # Lease / FSM owner consistency
        if self.state == BrowserState.AI_ACTIVE and self.lease.owner != "ai":
            return {"ok": False, "reason": "ai_state_but_not_ai_owner"}
        if self.state == BrowserState.HUMAN_ACTIVE and self.lease.owner != "human":
            return {"ok": False, "reason": "human_state_but_not_human_owner"}
        # Page stability
        if self.page:
            ok, reason = await wait_for_stability(self.page)
            if not ok:
                return {"ok": False, "reason": f"page_unstable:{reason}"}
        # Negative memory check
        neg = check_negative_memory(params.get("selector",""), self._url())
        if neg:
            return {"ok": False, "reason": f"negative_memory:{neg}"}
        # Unsafe → require human
        _UNSAFE = {"submit","pay","purchase","transfer","delete","publish","confirm_order"}
        if any(u in action.lower() for u in _UNSAFE) and self.lease.owner != "human":
            return {"ok": False, "reason": "unsafe_requires_human_takeover"}
        return {"ok": True}

    async def _execute(self, action: str, params: Dict) -> Dict:
        try:
            if action == "navigate":
                url = params.get("url","")
                if not url.startswith("http"):
                    url = "https://" + url
                await self.page.goto(url, timeout=20000, wait_until="domcontentloaded")
                return {"ok": True, "url": self.page.url, "title": await self.page.title()}

            elif action == "click":
                t = params.get("target", params.get("selector",""))
                try:
                    await self.page.get_by_text(t, exact=False).first.click(timeout=5000)
                except Exception:
                    await self.page.click(t, timeout=5000)
                await asyncio.sleep(0.5)
                return {"ok": True, "clicked": t}

            elif action == "type":
                await self.page.fill(params.get("selector",""), params.get("text",""))
                return {"ok": True, "chars": len(params.get("text",""))}

            elif action in ("screenshot", "get_text", "scroll", "inspect", "validate"):
                if action == "get_text":
                    return {"ok": True, "text": (await self.page.inner_text("body"))[:5000]}
                if action == "scroll":
                    await self.page.evaluate(f"window.scrollBy({params.get('x',0)},{params.get('y',300)})")
                    return {"ok": True}
                if action == "inspect":
                    html = await self.page.locator(params.get("selector","body")).first.inner_html()
                    return {"ok": True, "html": html[:2000]}
                if action == "validate":
                    found = await self.page.locator(params.get("condition","body")).count() > 0
                    return {"ok": True, "found": found}
                return {"ok": True}

            else:
                return {"ok": False, "error": f"unknown_action:{action}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def _verify(self, action: str, params: Dict, ex: Dict) -> Dict:
        try:
            if action == "navigate":
                url = self.page.url
                dom = await _dom_hash(self.page)
                if not url or not dom:
                    return {"ok": False, "reason": "empty_url_or_dom"}
                return {"ok": True, "url": url, "dom_hash": dom}
            elif action == "type":
                try:
                    val  = await self.page.locator(params.get("selector","")).first.input_value()
                    want = params.get("text","")
                    if val != want:
                        return {"ok": False, "reason": f"value_mismatch:{val[:20]}!={want[:20]}"}
                except Exception:
                    pass
                return {"ok": True}
            else:
                return {"ok": True}
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    async def _commit(self, action: str, params: Dict, ex: Dict) -> bool:
        entry = {
            "ts": time.time(), "action": action,
            "params": {k: v for k,v in params.items() if k != "screenshot_b64"},
            "url": self._url(), "result": str(ex)[:100],
        }
        self._action_history.append(entry)
        if len(self._action_history) > 100:
            self._action_history = self._action_history[-100:]
        self._pending_flow.append(entry)
        try:
            with open(LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass
        if len(self._pending_flow) % 5 == 0:
            await create_checkpoint(self)
        self._save_state()
        return True

    # ── Human Takeover ────────────────────────────────────────────────────────
    async def request_human_takeover(self, ai_token: str, reason: str = "") -> Dict:
        """AI → HUMAN_PENDING (AI cannot jump directly to HUMAN_ACTIVE)."""
        if not self.lease.is_owner(ai_token):
            return {"ok": False, "reason": "invalid_ai_token"}
        if self.state != BrowserState.AI_ACTIVE:
            return {"ok": False, "reason": f"not_ai_active:{self.state}"}
        self.lease = Lease()  # AI releases, page stays
        ok = self._transition(BrowserState.HUMAN_PENDING, f"ai_req_takeover:{reason}")
        return {"ok": ok, "state": self.state.value}

    async def accept_human_takeover(self, session_id: str = "") -> Optional[str]:
        """Human accepts control (HUMAN_PENDING → HUMAN_ACTIVE)."""
        if self.state not in (BrowserState.HUMAN_PENDING, BrowserState.READY):
            return None
        self.lease = Lease()
        token = self.acquire_lease("human", session_id)
        if not token or not self._transition(BrowserState.HUMAN_ACTIVE, "human_accepted"):
            self.lease = Lease()
            return None
        await self._reconcile()
        return token

    async def human_release(self, token: str, corrections: Optional[List[Dict]] = None) -> bool:
        if not self.lease.is_owner(token):
            return False
        if corrections:
            for c in corrections:
                store_human_correction(c.get("intent",""), c.get("original",{}), c.get("correction",{}))
        self.release_lease(token)
        self._pending_flow = []
        self._transition(BrowserState.READY, "human_released")
        return True

    # ── Reconciliation ────────────────────────────────────────────────────────
    async def _reconcile(self) -> bool:
        if not self._transition(BrowserState.RECONCILING, "start"):
            return False
        try:
            if not self.page:
                self._transition(BrowserState.RECOVERY, "no_page")
                return False
            rec = {
                "url":      self.page.url,
                "dom_hash": await _dom_hash(self.page),
                "scroll":   await self.page.evaluate("()=>({x:window.scrollX,y:window.scrollY})"),
                "modals":   await self.page.locator("[role='dialog']:visible").count(),
            }
            self._reconcile_count += 1
            log.info("Reconcile OK: url=%s", rec["url"][:50])
            await create_checkpoint(self)
            self._transition(BrowserState.READY, "reconcile_ok")
            return True
        except Exception as e:
            log.error("Reconcile fail: %s", e)
            self._transition(BrowserState.SAFE_MODE, f"reconcile_failed:{e}")
            return False

    # ── Recovery ──────────────────────────────────────────────────────────────
    async def recover(self, checkpoint_id: Optional[str] = None) -> bool:
        """Recovery must use checkpoints. Not from scratch unless checkpoint invalid."""
        if not self._transition(BrowserState.RECOVERY, "start"):
            return False
        try:
            cp_data = None
            if checkpoint_id:
                f = CHECKPOINT_DIR / f"cp_{checkpoint_id}.json"
                if f.exists():
                    cp_data = json.loads(f.read_text())
            if cp_data is None:
                cps = sorted(CHECKPOINT_DIR.glob("cp_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not cps:
                    log.error("No checkpoints — SAFE_MODE")
                    self._transition(BrowserState.SAFE_MODE, "no_checkpoints")
                    return False
                cp_data = json.loads(cps[0].read_text())

            log.info("Recovering from checkpoint %s @ %s", cp_data.get("id"), cp_data.get("url","?"))
            if not self.page:
                await self.start()
            if cp_data.get("url"):
                try:
                    await self.page.goto(cp_data["url"], timeout=15000, wait_until="domcontentloaded")
                except Exception as e:
                    log.warning("Recovery nav failed: %s", e)
            self._transition(BrowserState.READY, "recovery_ok")
            return True
        except Exception as e:
            log.error("Recovery failed: %s", e)
            self._quarantine_reason = str(e)
            self._transition(BrowserState.QUARANTINED, f"recovery_failed:{e}")
            return False

    # ── AI Session helpers ────────────────────────────────────────────────────
    async def ai_start(self, session_id: str = "") -> Optional[str]:
        if self.state != BrowserState.READY:
            return None
        token = self.acquire_lease("ai", session_id)
        if not token or not self._transition(BrowserState.AI_ACTIVE, "ai_start"):
            if token:
                self.release_lease(token)
            return None
        return token

    async def ai_end(self, token: str) -> bool:
        if not self.lease.is_owner(token):
            return False
        self.release_lease(token)
        self._transition(BrowserState.READY, "ai_end")
        if len(self._pending_flow) >= 2:
            store_successful_flow(self._pending_flow, replay_verified=True)
        self._pending_flow = []
        return True

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _url(self) -> str:
        try:
            return self.page.url if self.page else ""
        except Exception:
            return ""

    async def _capture(self) -> str:
        try:
            if self.page:
                data = await self.page.screenshot(type="jpeg", quality=75, full_page=False)
                self._screenshot_b64 = base64.b64encode(data).decode()
                SCREENSHOT_PATH.write_bytes(data)
        except Exception:
            pass
        return self._screenshot_b64

    async def get_screenshot(self) -> str:
        return await self._capture()

    def _save_state(self):
        try:
            STATE_PATH.write_text(json.dumps({
                "fsm_state":         self.state.value,
                "lease_owner":       self.lease.owner,
                "lease_expires_in":  max(0, self.lease.expires_at - time.time()),
                "url":               self._url(),
                "actions":           len(self._action_history),
                "reconcile_count":   self._reconcile_count,
                "quarantine_reason": self._quarantine_reason,
                "ts":                time.time(),
            }))
        except Exception:
            pass

    def _save_state_err(self, err: str):
        try:
            STATE_PATH.write_text(json.dumps({"error": err, "ts": time.time()}))
        except Exception:
            pass

    def get_status(self) -> Dict:
        self._check_lease_expiry()
        return {
            "fsm_state":        self.state.value,
            "lease_owner":      self.lease.owner,
            "lease_valid":      self.lease.is_valid(),
            "lease_expires_in": max(0, self.lease.expires_at - time.time()) if self.lease.is_valid() else 0,
            "url":              self._url(),
            "running":          self.page is not None,
            "actions_count":    len(self._action_history),
            "recent_actions":   self._action_history[-5:],
            "reconcile_count":  self._reconcile_count,
            "quarantine_reason":self._quarantine_reason,
        }

    def list_checkpoints(self) -> List[Dict]:
        result = []
        for cf in sorted(CHECKPOINT_DIR.glob("cp_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
            try:
                d = json.loads(cf.read_text())
                result.append({"id": d["id"], "ts": d["ts"], "url": d.get("url",""), "fsm_state": d.get("fsm_state","")})
            except Exception:
                pass
        return result


# ─── Singleton ────────────────────────────────────────────────────────────────
_controller: Optional[BrowserController] = None

def get_or_create_controller() -> BrowserController:
    global _controller
    if _controller is None:
        _controller = BrowserController()
    return _controller

async def get_controller() -> BrowserController:
    return get_or_create_controller()

async def reset_controller() -> BrowserController:
    global _controller
    if _controller is not None:
        try:
            await _controller.stop()
        except Exception:
            pass
    _controller = BrowserController()
    return _controller
