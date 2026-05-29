# -*- coding: utf-8 -*-
"""
agents/bonus_hunter_agent.py
Automatically finds free API trials, bonuses, and discounts for AI services.
Registers for free tiers and integrates new API keys into the system.
"""
from __future__ import annotations
import asyncio, httpx, json, logging, os, re, time
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv, set_key

log = logging.getLogger('agents.bonus_hunter')
ENV_FILE = Path('/root/my_personal_ai/.env')

# Known free/cheap API services to check
FREE_SERVICES = {
    'together_ai': {
        'name': 'Together.ai',
        'signup_url': 'https://api.together.xyz/signup',
        'api_check': 'https://api.together.xyz/v1/models',
        'key_pattern': r'[a-zA-Z0-9]{64}',
        'env_key': 'TOGETHER_API_KEY',
        'free_credits': '$5',
        'models': ['meta-llama/Llama-3.2-3B-Instruct-Turbo', 'Qwen/Qwen2.5-7B-Instruct-Turbo'],
    },
    'groq': {
        'name': 'Groq',
        'api_check': 'https://api.groq.com/openai/v1/models',
        'env_key': 'GROQ_API_KEY',
        'free_credits': 'Free tier',
        'daily_limit': '14400 req/day',
    },
    'openrouter': {
        'name': 'OpenRouter',
        'signup_url': 'https://openrouter.ai/sign-up',
        'api_check': 'https://openrouter.ai/api/v1/models',
        'env_key': 'OPENROUTER_API_KEY',
        'free_credits': '29 free models',
        'note': 'Requires manual signup - CAPTCHA blocks VPS',
    },
    'cerebras': {
        'name': 'Cerebras',
        'signup_url': 'https://cloud.cerebras.ai/',
        'env_key': 'CEREBRAS_API_KEY',
        'free_credits': 'Free tier (500 tok/s)',
        'note': 'Requires manual signup - CAPTCHA blocks VPS',
    },
    'mistral': {
        'name': 'Mistral AI',
        'api_check': 'https://api.mistral.ai/v1/models',
        'env_key': 'MISTRAL_API_KEY',
        'free_models': ['open-mistral-7b', 'open-mixtral-8x7b'],
    },
    'deepseek': {
        'name': 'DeepSeek',
        'api_check': 'https://api.deepseek.com/models',
        'env_key': 'DEEPSEEK_API_KEY',
        'price': '$0.14/M input tokens',
    },
    'huggingface': {
        'name': 'HuggingFace (free inference)',
        'api_check': 'https://api-inference.huggingface.co/status',
        'env_key': 'HF_API_KEY',
        'free_credits': 'Free for public models',
    },
    'google_ai': {
        'name': 'Google AI / Gemini',
        'api_check': 'https://generativelanguage.googleapis.com/v1beta/models',
        'env_key': 'GOOGLE_API_KEY',
        'free_tier': 'Yes - 1M tokens/day for Flash',
    },
}

class BonusHunterAgent:
    """Scans for free API services and manages bonus programs"""

    def __init__(self):
        load_dotenv(ENV_FILE)
        self.env = {k: os.getenv(k, '') for k in [
            'GROQ_API_KEY', 'DEEPSEEK_API_KEY', 'MISTRAL_API_KEY',
            'OPENROUTER_API_KEY', 'CEREBRAS_API_KEY', 'TOGETHER_API_KEY',
            'GOOGLE_API_KEY', 'HF_API_KEY', 'PERPLEXITY_API_KEY'
        ]}
        self.report = []

    def check_key_status(self) -> dict:
        """Check which API keys are set and which are empty"""
        status = {}
        for k, v in self.env.items():
            status[k] = 'SET' if v else 'EMPTY'
        return status

    async def test_provider(self, name: str, endpoint: str, key: str) -> dict:
        """Test if a provider API key works"""
        if not key:
            return {'status': 'no_key', 'name': name}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(endpoint, headers={'Authorization': 'Bearer ' + key})
                if r.status_code == 200:
                    return {'status': 'ok', 'name': name, 'code': r.status_code}
                elif r.status_code == 429:
                    return {'status': 'rate_limited', 'name': name}
                else:
                    return {'status': 'error', 'name': name, 'code': r.status_code}
        except Exception as e:
            return {'status': 'error', 'name': name, 'error': str(e)[:50]}

    async def check_openrouter_free(self) -> list:
        """Get list of free models on OpenRouter (no auth needed)"""
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get('https://openrouter.ai/api/v1/models')
                if r.status_code == 200:
                    models = r.json().get('data', [])
                    free = [m['id'] for m in models if m.get('pricing', {}).get('prompt') == '0']
                    return free
        except Exception as e:
            log.warning('OR free models check failed: %s', e)
        return []

    async def check_groq_quota(self) -> dict:
        """Check Groq rate limit headers"""
        key = self.env.get('GROQ_API_KEY', '')
        if not key:
            return {'error': 'no key'}
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    'https://api.groq.com/openai/v1/chat/completions',
                    headers={'Authorization': 'Bearer ' + key},
                    json={'model': 'llama-3.3-70b-versatile', 'messages': [{'role':'user','content':'1'}], 'max_tokens': 1}
                )
                remaining = r.headers.get('x-ratelimit-remaining-requests', '?')
                reset = r.headers.get('x-ratelimit-reset-requests', '?')
                return {'status': r.status_code, 'remaining': remaining, 'reset': reset}
        except Exception as e:
            return {'error': str(e)[:60]}

    def generate_report(self) -> str:
        """Generate a status report of all providers"""
        lines = ['=== AI PROVIDER STATUS ===']
        status = self.check_key_status()
        for k, v in status.items():
            lines.append(f'  {k}: {v}')
        return chr(10).join(lines)

    async def run_scan(self) -> str:
        """Run full bonus/free tier scan"""
        log.info('BonusHunter: starting scan')
        results = []

        # 1. Check OpenRouter free models
        free_or = await self.check_openrouter_free()
        results.append(f'OpenRouter free models: {len(free_or)} available')
        if free_or:
            results.append('  Top free: ' + ', '.join(free_or[:5]))

        # 2. Check Groq quota
        groq_status = await self.check_groq_quota()
        results.append(f'Groq quota: {groq_status}')

        # 3. Key status
        key_status = self.check_key_status()
        empty_keys = [k for k, v in key_status.items() if v == 'EMPTY']
        if empty_keys:
            results.append(f'Missing keys (need manual signup): {empty_keys}')

        # 4. Providers needing manual signup (CAPTCHA blocks VPS)
        manual_needed = []
        if not self.env.get('OPENROUTER_API_KEY'):
            manual_needed.append('OpenRouter: https://openrouter.ai/sign-up (free, 29 models)')
        if not self.env.get('CEREBRAS_API_KEY'):
            manual_needed.append('Cerebras: https://cloud.cerebras.ai/ (free, 500 tok/s)')
        if not self.env.get('TOGETHER_API_KEY'):
            manual_needed.append('Together.ai: https://api.together.xyz/ ($5 free credit)')
        if manual_needed:
            results.append('MANUAL SIGNUP NEEDED (CAPTCHA blocks VPS):')
            for m in manual_needed:
                results.append('  - ' + m)

        report = chr(10).join(results)
        log.info('BonusHunter scan complete: %d items', len(results))
        return report


async def main():
    hunter = BonusHunterAgent()
    report = await hunter.run_scan()
    print(report)


    def process(self, text: str = "", source: str = "internal", **kwargs) -> str:
        """Orchestrator bridge — auto-added."""
        for m in ["run","execute","work","handle","daily_cycle","check","scan","analyze","report","daily_report"]:
            fn = getattr(self, m, None)
            if fn and callable(fn):
                try:
                    r = fn()
                    return str(r)[:400] if r else self.__class__.__name__ + ": ok"
                except Exception as e:
                    return self.__class__.__name__ + f" error: {e}"
        return self.__class__.__name__ + ": ready"

if __name__ == '__main__':
    asyncio.run(main())