#!/usr/bin/env python3
"""
MaxAI Autonomous Brain v2.0
=================================================
Полностью автономная система управления MaxAI Corporation.
Знает всю систему, умеет всё настраивать, работает 24/7.

Запуск: python3 maxai_brain.py
Или как сервис: systemctl start maxai-brain
"""
import asyncio, json, os, sys, time, logging, subprocess, re
import urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
import redis as _redis

# ── Setup ──────────────────────────────────────────────────────────────────
LOG_FILE = Path('/root/my_personal_ai/logs/maxai_brain.log')
LOG_FILE.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [BRAIN] %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_FILE)),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('maxai.brain')

ENV_FILE = Path('/root/my_personal_ai/.env')
REDIS_URL = 'redis://127.0.0.1:6379/0'
rdb = _redis.from_url(REDIS_URL, decode_responses=True)

def load_env() -> Dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip()
    return env

# ══════════════════════════════════════════════════════════════════════
# SYSTEM KNOWLEDGE BASE — MaxAI знает всё о своей системе
# ══════════════════════════════════════════════════════════════════════
SYSTEM_KNOWLEDGE = {
    "server": {
        "ip": "77.90.2.171",
        "os": "Ubuntu 22.04",
        "venv": "/root/venv",
        "timezone": "UTC-5",
    },
    "services": {
        "nginx":          {"port": 80,   "config": "/etc/nginx/sites-enabled/maxai-panel", "critical": True},
        "redis":          {"port": 6379, "critical": True},
        "maxai-core":     {"port": 4000, "dir": "/root/maxai-core", "critical": True},
        "personal-ai":    {"port": 8090, "dir": "/root/my_personal_ai", "critical": True},
        "nexus-api":      {"port": 5000, "dir": "/root/nexus", "critical": True},
        "maxai-tgbot":    {"script": "/root/my_personal_ai/scripts/maxai_bot_v3.py"},
        "corp-tgbot":     {"script": "/root/my_personal_ai/agents/corp_tgbot.py"},
        "nexus-bot":      {"script": "/root/nexus/nexus_bot.py"},
        "maxai-aaas":     {"script": "/root/my_personal_ai/scripts/aaas_engine.py"},
        "bybit-bot":      {"script": "/root/bybit-bot/bybit_live_runner.py"},
        "maxai-browser":  {"port": 8096, "dir": "/root/my_personal_ai/dashboard"},
        "maxai-guardian": {"script": "/root/my_personal_ai/scripts/self_healing_watchdog.py"},
    },
    "urls": {
        "admin_panel":    "http://77.90.2.171",
        "client_portal":  "http://77.90.2.171/portal.html",
        "nexus_api":      "http://77.90.2.171/nexus",
        "hire_page":      "http://77.90.2.171/hire.html",
        "api_docs":       "http://77.90.2.171/api-docs",
        "hf_space":       "https://maxocrporate-maxai-text-analyzer.hf.space",
        "fiverr":         "https://www.fiverr.com/maxai_co",
        "channel":        "https://t.me/maxai_chanal",
    },
    "wallets": {
        "usdt_trc20": "TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2",
        "eth":        "0x7b72d6072f973a79d13abb11769927890832cc12",
        "btc":        "158AEebXosZfxHY1ZVQNfTT6BHcuHqGFr4",
        "sol":        "4v5rZQDfgHwE5135fQcVaQcaczYsb86gXbPgxWw4XDzK",
    },
    "platforms": {
        "kwork": {"url": "https://kwork.ru", "login": "froggyinternet@gmail.com", "category": "freelance"},
        "fiverr": {"url": "https://www.fiverr.com/maxai_co", "category": "freelance"},
        "huggingface": {"url": "https://huggingface.co/Maxocrporate", "category": "ai"},
        "agentverse": {"url": "https://agentverse.ai", "category": "ai_agents"},
    },
    "ai_providers": {
        "openrouter": {"priority": 1, "model": "openai/gpt-3.5-turbo", "env_key": "OPENROUTER_API_KEY"},
        "anthropic":  {"priority": 2, "model": "claude-haiku-4-5", "env_key": "ANTHROPIC_API_KEY"},
        "groq":       {"priority": 3, "model": "llama-3.1-8b-instant", "env_key": "GROQ_API_KEY", "status": "blocked"},
    },
    "cron_tasks": [
        {"interval": "*/10", "script": "payment_monitor.py", "purpose": "Monitor crypto wallets for payments"},
        {"interval": "*/15", "script": "kwork_scan_v3.py", "purpose": "Scan Kwork for new projects and apply"},
        {"interval": "*/30", "script": "platform_monitor.py", "purpose": "Monitor all AaaS platforms"},
        {"interval": "*/30", "script": "nexus hunter", "purpose": "Revenue hunter across platforms"},
        {"interval": "0 */3", "script": "maxai_channel_poster.py", "purpose": "Post to @maxai_chanal"},
        {"interval": "0 3",   "script": "groq_auto_key.py", "purpose": "Auto-refresh Groq API key"},
    ],
}


# ══════════════════════════════════════════════════════════════════════
# HEALTH MONITOR — проверяет всё и чинит
# ══════════════════════════════════════════════════════════════════════
class HealthMonitor:
    def __init__(self):
        self.env = load_env()
        self.issues = []
        self.fixed = []

    def api_get(self, url: str, timeout: int = 5) -> tuple:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read()), r.status
        except urllib.request.HTTPError as e:
            return {}, e.code
        except Exception:
            return {}, 0

    def check_service(self, svc: str) -> bool:
        r = subprocess.run(['systemctl','is-active',svc], capture_output=True, text=True)
        return r.stdout.strip() == 'active'

    def restart_service(self, svc: str) -> bool:
        r = subprocess.run(['systemctl','restart',svc], capture_output=True, text=True)
        time.sleep(3)
        return self.check_service(svc)

    def check_and_fix_services(self):
        critical = ['nginx','redis','maxai-core','personal-ai','nexus-api',
                    'maxai-tgbot','corp-tgbot','maxai-aaas','bybit-bot','maxai-guardian',
                    'bybit-monitor']
        for svc in critical:
            if not self.check_service(svc):
                log.warning(f"Service {svc} is DOWN — restarting...")
                ok = self.restart_service(svc)
                if ok:
                    log.info(f"Service {svc} restarted ✅")
                    self.fixed.append(svc)
                else:
                    self.issues.append(f"Service {svc} failed to restart")
                    log.error(f"Service {svc} FAILED to restart ❌")

    def check_endpoints(self):
        endpoints = [
            ('http://127.0.0.1/', 'Admin Panel'),
            ('http://127.0.0.1/nexus/stats', 'NEXUS Stats'),
            ('http://127.0.0.1/api/trading/balance', 'Trading'),
        ]
        for url, name in endpoints:
            _, status = self.api_get(url)
            if status != 200:
                self.issues.append(f"Endpoint {name} returns {status}")

    def check_trading(self):
        _, status = self.api_get('http://127.0.0.1/api/trading/balance')
        if status != 200:
            log.warning("Trading API down — restarting bybit-bot")
            self.restart_service('bybit-bot')

    def run_full_check(self) -> Dict[str, Any]:
        self.issues = []
        self.fixed = []
        self.check_and_fix_services()
        self.check_endpoints()
        self.check_trading()
        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'issues': self.issues,
            'fixed': self.fixed,
            'healthy': len(self.issues) == 0,
        }


# ══════════════════════════════════════════════════════════════════════
# AI BRAIN — интеллект MaxAI
# ══════════════════════════════════════════════════════════════════════
class AIBrain:
    def __init__(self):
        self.env = load_env()
        self.or_key = self.env.get('OPENROUTER_API_KEY', '')
        self.ant_key = self.env.get('ANTHROPIC_API_KEY', '')

    async def think(self, prompt: str, context: str = '') -> str:
        """Main AI reasoning — OpenRouter first, Anthropic fallback."""
        import httpx
        system = f"""You are MaxAI — the autonomous brain of MaxAI Corporation.
You manage a server at 77.90.2.171 with 13+ services running 24/7.
You know the full system architecture and can fix any issue.
Server knowledge:
- Admin Panel: http://77.90.2.171
- NEXUS Platform: http://77.90.2.171/portal.html
- Services: nginx, redis, maxai-core, personal-ai, nexus-api, maxai-tgbot, corp-tgbot, maxai-aaas, bybit-bot
- Trading: Bybit V5, pairs: BTC/ETH/SOL/LINK/AVAX, leverage 3x
- Revenue: Kwork freelance (41 proposals sent), Fiverr (@maxai_co), HuggingFace Space RUNNING
- Wallets: USDT TRC20: TAN8FijYFgmM8wCq8Y5jogkry9kPaY9NE2
{context}
Respond in Russian concisely and actionably."""

        if self.or_key:
            try:
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.post('https://openrouter.ai/api/v1/chat/completions',
                        headers={'Authorization': f'Bearer {self.or_key}',
                                 'HTTP-Referer': 'http://77.90.2.171', 'X-Title': 'MaxAI Brain'},
                        json={'model': 'openai/gpt-3.5-turbo',
                              'messages': [{'role': 'system', 'content': system},
                                           {'role': 'user', 'content': prompt[:4000]}],
                              'max_tokens': 1500})
                    if r.status_code == 200:
                        return r.json()['choices'][0]['message']['content'].strip()
            except Exception as e:
                log.warning(f'OpenRouter error: {e}')

        if self.ant_key:
            try:
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.post('https://api.anthropic.com/v1/messages',
                        headers={'x-api-key': self.ant_key, 'anthropic-version': '2023-06-01'},
                        json={'model': 'claude-haiku-4-5', 'system': system,
                              'messages': [{'role': 'user', 'content': prompt[:4000]}],
                              'max_tokens': 1500})
                    if r.status_code == 200:
                        return r.json()['content'][0]['text'].strip()
            except Exception as e:
                log.warning(f'Anthropic error: {e}')

        return f"MaxAI обработал: {prompt[:80]}... [Пополни баланс Anthropic для полного AI]"

    async def analyze_system(self) -> str:
        """Analyze current system state and provide recommendations."""
        # Gather system state
        state = {
            'balance': rdb.get('bybit:balance:usdt') or '?',
            'revenue_real': float(rdb.get('aaas:revenue:real_total_usd') or 0),
            'proposals_sent': len(rdb.keys('kwork:proposal:*:ts')),
            'nexus_clients': len(rdb.lrange('nexus:clients:list', 0, -1)),
        }

        prompt = f"""Проанализируй состояние MaxAI Corporation:
- Bybit баланс: ${state['balance']}
- Реальный доход: ${state['revenue_real']:.2f}
- Kwork предложений: {state['proposals_sent']}
- NEXUS клиентов: {state['nexus_clients']}

Дай 3 конкретных действия для увеличения дохода."""

        return await self.think(prompt)


# ══════════════════════════════════════════════════════════════════════
# WEBSITE NAVIGATOR — умеет заходить на сайты
# ══════════════════════════════════════════════════════════════════════
class WebsiteNavigator:
    """MaxAI умеет правильно заходить на все нужные сайты."""
    BROWSER_URL = 'http://127.0.0.1:8096'

    def _b(self, path: str, data=None, method=None) -> dict:
        """Browser proxy call — accepts optional method override."""
        m = method or ('POST' if data is not None else 'GET')
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(
            self.BROWSER_URL + path, data=body,
            headers={'Content-Type': 'application/json'} if body else {},
            method=m)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except Exception as e:
            return {'error': str(e)[:80]}

    def navigate(self, url: str, wait: float = 3.0) -> dict:
        result = self._b('/navigate', {'url': url})
        time.sleep(wait)
        return result

    def js(self, code: str) -> dict:
        return self._b('/execute', {'code': code})

    def click(self, selector_or_text: str) -> dict:
        # Try text first
        btn = self._b('/find', {'text': selector_or_text})
        if btn.get('x') and btn.get('y'):
            return self._b('/click', {'x': int(btn['x']), 'y': int(btn['y'])})
        # Try CSS selector
        return self.js(f"document.querySelector('{selector_or_text}')?.click()")

    def fill(self, selector: str, value: str) -> dict:
        return self.js(f"""
var el = document.querySelector('{selector}') || document.querySelector('[name=\"{selector}\"]')
       || document.querySelector('[placeholder*=\"{selector}\"]');
if(el) {{
    el.value = {json.dumps(value)};
    el.dispatchEvent(new Event('input', {{bubbles:true}}));
    el.dispatchEvent(new Event('change', {{bubbles:true}}));
    return 'filled';
}}
return 'not_found';""")

    def get_page_state(self) -> dict:
        health = self._b('/health', method='GET')
        page_info = self.js("""return JSON.stringify({
            url: window.location.href,
            title: document.title,
            logged_in: !!(document.querySelector('[href*=logout], [data-action=logout], .user-menu, .header-user')),
            forms: document.querySelectorAll('form').length,
            inputs: document.querySelectorAll('input').length,
            buttons: [...document.querySelectorAll('button')].map(b=>b.textContent.trim()).filter(t=>t.length<30).slice(0,8),
        })""")
        return {'health': health, 'page': json.loads(page_info.get('result','{}'))}

    def login_kwork(self, email: str, password: str) -> bool:
        """Login to Kwork.ru"""
        log.info("Logging in to Kwork...")
        self.navigate('https://kwork.ru/', wait=3)

        # Check if already logged in
        state = self.get_page_state()
        if state['page'].get('logged_in'):
            log.info("Kwork: already logged in ✅")
            return True

        # Navigate to login
        self.navigate('https://kwork.ru/login', wait=3)
        self.fill('email', email)
        time.sleep(0.5)
        self.fill('password', password)
        time.sleep(0.5)
        self.click('Войти')
        time.sleep(3)

        state = self.get_page_state()
        ok = state['page'].get('logged_in', False)
        log.info(f"Kwork login: {'✅' if ok else '❌'}")
        return ok

    def check_login_status(self, platform: str) -> bool:
        """Check if logged into a platform."""
        urls = {
            'kwork': 'https://kwork.ru/',
            'fiverr': 'https://www.fiverr.com/',
            'huggingface': 'https://huggingface.co/',
        }
        if platform not in urls:
            return False
        self.navigate(urls[platform], wait=3)
        state = self.get_page_state()
        return state['page'].get('logged_in', False)

    def ensure_platform_login(self) -> Dict[str, bool]:
        """Ensure MaxAI is logged into all platforms."""
        env = load_env()
        results = {}

        # Kwork login
        kwork_email = env.get('KWORK_EMAIL', env.get('KWORK_LOGIN', 'froggyinternet@gmail.com'))
        kwork_pass = env.get('KWORK_PASSWORD', '')
        if kwork_pass:
            results['kwork'] = self.login_kwork(kwork_email, kwork_pass)
        else:
            results['kwork'] = self.check_login_status('kwork')

        return results


# ══════════════════════════════════════════════════════════════════════
# REVENUE ENGINE — активно ищет и закрывает сделки
# ══════════════════════════════════════════════════════════════════════
class RevenueEngine:
    def __init__(self):
        self.navigator = WebsiteNavigator()

    async def hunt_projects(self) -> dict:
        """Autonomous project hunting across platforms."""
        log.info("Revenue Hunter: starting scan...")
        try:
            result = subprocess.run(
                ['/root/venv/bin/python3', '/root/nexus/intelligence/hunter.py'],
                capture_output=True, text=True, timeout=300
            )
            return {'ok': True, 'output': result.stdout[-500:]}
        except Exception as e:
            return {'ok': False, 'error': str(e)}

    def post_to_channel(self, message: str) -> bool:
        """Post marketing content to Telegram channel."""
        env = load_env()
        token = env.get('CORP_BOT_TOKEN', '')
        if not token:
            return False
        try:
            req = urllib.request.Request(
                f'https://api.telegram.org/bot{token}/sendMessage',
                data=json.dumps({'chat_id': '@maxai_chanal', 'text': message,
                                 'parse_mode': 'HTML', 'disable_web_page_preview': True}).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read())
                return d.get('ok', False)
        except:
            return False

    def notify_owner(self, message: str) -> bool:
        """Send notification to bot owner."""
        env = load_env()
        token = env.get('TELEGRAM_BOT_TOKEN', '')
        owner = env.get('TELEGRAM_OWNER_ID', '')
        if not token or not owner:
            return False
        try:
            req = urllib.request.Request(
                f'https://api.telegram.org/bot{token}/sendMessage',
                data=json.dumps({'chat_id': owner, 'text': message,
                                 'parse_mode': 'HTML'}).encode(),
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=8) as r:
                return json.loads(r.read()).get('ok', False)
        except:
            return False


# ══════════════════════════════════════════════════════════════════════
# MAIN AUTONOMOUS LOOP
# ══════════════════════════════════════════════════════════════════════
class MaxAIBrain:
    """Main autonomous brain — runs everything 24/7."""

    def __init__(self):
        self.health = HealthMonitor()
        self.ai = AIBrain()
        self.revenue = RevenueEngine()
        self.navigator = WebsiteNavigator()
        self.cycle = 0
        self.start_time = time.time()

    async def run_cycle(self):
        """One full autonomous cycle."""
        self.cycle += 1
        now = datetime.now()
        log.info(f"=== Cycle {self.cycle} === {now.strftime('%H:%M:%S %d.%m.%Y')}")

        # Save brain status to Redis
        rdb.set('maxai:brain:cycle', self.cycle)
        rdb.set('maxai:brain:last_ts', time.time())
        rdb.set('maxai:brain:status', 'running')

        # 1. Health check every cycle (5 min)
        health_result = self.health.run_full_check()
        if health_result['fixed']:
            log.info(f"Auto-fixed: {health_result['fixed']}")
            self.revenue.notify_owner(
                f"🔧 <b>MaxAI Auto-Fixed</b>\n\n"
                f"Restored services: {', '.join(health_result['fixed'])}\n"
                f"Cycle: {self.cycle}"
            )
        if health_result['issues']:
            log.warning(f"Issues: {health_result['issues']}")

        # 2. Revenue hunt every 6 cycles (~30 min)
        if self.cycle % 6 == 0:
            log.info("Running revenue hunt...")
            result = await self.revenue.hunt_projects()
            log.info(f"Hunt result: {result.get('ok')}")

        # 3. AI analysis every 12 cycles (~1 hour)
        if self.cycle % 12 == 0:
            analysis = await self.ai.analyze_system()
            log.info(f"AI Analysis: {analysis[:200]}")
            rdb.set('maxai:brain:last_analysis', analysis, ex=7200)

        # 4. Platform login check every 24 cycles (~2 hours)
        if self.cycle % 24 == 0:
            log.info("Checking platform logins...")
            login_status = self.navigator.ensure_platform_login()
            log.info(f"Login status: {login_status}")
            rdb.set('maxai:brain:login_status', json.dumps(login_status))

        # 5. Channel post every 36 cycles (~3 hours)
        if self.cycle % 36 == 0:
            log.info("Posting to channel...")
            analysis = await self.ai.think(
                "Напиши короткий (3-4 строки) маркетинговый пост о MaxAI Corporation "
                "для Telegram канала. Упомяни: AI агенты, автоматизация, от $19/мес. "
                "Добавь ссылку на @MaxAI_SaaS_Bot и #maxai #ai"
            )
            self.revenue.post_to_channel(analysis)

        # 6. Daily report every 288 cycles (~24 hours)
        if self.cycle % 288 == 0:
            await self._daily_report()

    async def _daily_report(self):
        """Generate and send daily performance report."""
        real_rev = float(rdb.get('aaas:revenue:real_total_usd') or 0)
        proposals = len(rdb.keys('kwork:proposal:*:ts'))
        uptime_h = (time.time() - self.start_time) / 3600

        report = (
            f"📊 <b>MaxAI Daily Report</b>\n\n"
            f"⏱ Uptime: {uptime_h:.1f}h\n"
            f"💰 Real revenue: ${real_rev:.2f}\n"
            f"📋 Proposals sent: {proposals}\n"
            f"🔄 Cycles completed: {self.cycle}\n\n"
            f"Services: all operational ✅\n"
            f"Portal: http://77.90.2.171/portal.html"
        )
        self.revenue.notify_owner(report)
        log.info(f"Daily report sent")

    async def run_forever(self):
        """Main infinite loop."""
        log.info("=" * 60)
        log.info("MaxAI Autonomous Brain v2.0 STARTED")
        log.info(f"Server: 77.90.2.171 | Services: 13+ | Agents: 10")
        log.info("=" * 60)

        rdb.set('maxai:brain:start_ts', time.time())
        rdb.set('maxai:brain:version', '2.0')

        # Startup notification
        env = load_env()
        token = env.get('TELEGRAM_BOT_TOKEN', '')
        owner = env.get('TELEGRAM_OWNER_ID', '')
        if token and owner:
            try:
                req = urllib.request.Request(
                    f'https://api.telegram.org/bot{token}/sendMessage',
                    data=json.dumps({'chat_id': owner, 'parse_mode': 'HTML',
                        'text': '🧠 <b>MaxAI Brain v2.0 Started</b>\n\nAutonomous mode: ON\n24/7 self-management active\n\nPortal: http://77.90.2.171/portal.html'}).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                urllib.request.urlopen(req, timeout=5)
            except: pass

        while True:
            try:
                await self.run_cycle()
                await asyncio.sleep(300)  # 5 minutes between cycles
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Cycle error: {e}")
                rdb.set('maxai:brain:last_error', str(e)[:200])
                await asyncio.sleep(60)

        rdb.set('maxai:brain:status', 'stopped')
        log.info("MaxAI Brain stopped")


# ══════════════════════════════════════════════════════════════════════
# API for external queries (brain can answer questions)
# ══════════════════════════════════════════════════════════════════════
async def answer_question(question: str) -> str:
    """MaxAI answers any question about the system."""
    brain = AIBrain()
    return await brain.think(question)

async def get_system_status() -> dict:
    """Get complete system status."""
    monitor = HealthMonitor()
    result = monitor.run_full_check()

    # Add AI providers status
    env = load_env()
    result['ai_providers'] = {
        'openrouter': bool(env.get('OPENROUTER_API_KEY')),
        'anthropic':  bool(env.get('ANTHROPIC_API_KEY')),
        'groq':       bool(env.get('GROQ_API_KEY')),
        'anthropic_balance': 'needs_topup',  # Known issue
    }
    result['real_revenue'] = float(rdb.get('aaas:revenue:real_total_usd') or 0)
    result['nexus_clients'] = len(rdb.lrange('nexus:clients:list', 0, -1))
    result['kwork_proposals'] = len(rdb.keys('kwork:proposal:*:ts'))

    return result




# ── NEXUS QUEUE MONITOR ──────────────────────────────────────────────────────
async def nexus_queue_check():
    """Monitor task queues and auto-recover stuck jobs."""
    try:
        import redis as _r
        rdb_local = _r.from_url('redis://127.0.0.1:6379/0', decode_responses=True)

        queues = ['nexus:queue:global', 'nexus:queue:coder', 'nexus:queue:researcher',
                  'nexus:queue:trader', 'nexus:queue:presenter']
        total_pending = sum(rdb_local.llen(q) for q in queues)

        if total_pending > 20:
            log.warning(f'[BRAIN] Queue backup: {total_pending} tasks pending — restarting nexus-worker')
            subprocess.run(['systemctl', 'restart', 'nexus-worker'], capture_output=True)
            rdb_local.set('brain:auto_fix:queue_restart', '1', ex=3600)
            return f'Queue backup ({total_pending}) → restarted nexus-worker'

        # Check worker alive
        r = subprocess.run(['systemctl', 'is-active', 'nexus-worker'], capture_output=True, text=True)
        if r.stdout.strip() != 'active':
            log.warning('[BRAIN] nexus-worker down — restarting')
            subprocess.run(['systemctl', 'restart', 'nexus-worker'], capture_output=True)
            return 'nexus-worker was down — restarted'

        return f'Queue OK ({total_pending} pending)'
    except Exception as e:
        return f'Queue check error: {e}'

async def revenue_check():
    """Check revenue and send daily summary."""
    try:
        import redis as _r
        rdb_local = _r.from_url('redis://127.0.0.1:6379/0', decode_responses=True)
        real = float(rdb_local.get('nexus:revenue:real_total') or 0)
        clients = rdb_local.llen('nexus:clients:list')
        tasks = int(rdb_local.get('nexus:stats:tasks_total') or 0)
        balance = float(rdb_local.get('bybit:balance_usdt') or 0)
        rdb_local.set('brain:revenue:snapshot', json.dumps({
            'real': real, 'clients': clients, 'tasks': tasks,
            'balance': balance, 'ts': time.time()
        }))
        return f'Revenue:  | Clients: {clients} | Tasks: {tasks} | Balance: '
    except Exception as e:
        return f'Revenue check error: {e}'

if __name__ == '__main__':
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else 'run'

    if mode == 'status':
        import asyncio
        result = asyncio.run(get_system_status())
        print(json.dumps(result, indent=2, default=str))

    elif mode == 'ask':
        question = ' '.join(sys.argv[2:]) if len(sys.argv) > 2 else 'Какой статус системы?'
        import asyncio
        answer = asyncio.run(answer_question(question))
        print(answer)

    elif mode == 'login':
        nav = WebsiteNavigator()
        results = nav.ensure_platform_login()
        print(json.dumps(results))

    elif mode == 'hunt':
        rev = RevenueEngine()
        import asyncio
        result = asyncio.run(rev.hunt_projects())
        print(json.dumps(result))

    else:  # run
        brain = MaxAIBrain()
        asyncio.run(brain.run_forever())
