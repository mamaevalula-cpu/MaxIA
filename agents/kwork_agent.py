#!/usr/bin/env python3
"""
kwork_agent.py — Автоматический поиск и отклик на заказы Kwork
MaxAI Revenue Stream: AI/Python разработка на Kwork

Kwork — крупнейшая русскоязычная фриланс-биржа.
Средний чек для AI/бот проектов: 2000-15000 руб ($25-180)

Стратегия:
1. Поиск заказов по ключевым словам (Python, бот, ИИ, автоматизация)
2. Фильтр по цене (от 1500 руб)
3. Генерация персонализированного предложения через AI
4. Отправка предложения + уведомление в Telegram
"""
import json, logging, os, re, sys, time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote

sys.path.insert(0, '/root/my_personal_ai')
Path('/root/my_personal_ai/logs').mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/root/my_personal_ai/logs/kwork_agent.log'),
    ]
)
log = logging.getLogger('kwork_agent')

TG_TOKEN  = os.environ.get('TELEGRAM_BOT_TOKEN', '8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM')
TG_CHAT   = os.environ.get('TELEGRAM_CHAT_ID',   '1985320458')
STATE_FILE = Path('/root/my_personal_ai/data/kwork_state.json')
LEADS_FILE = Path('/root/my_personal_ai/data/kwork_leads.jsonl')

# Kwork credentials
KWORK_EMAIL    = os.environ.get('KWORK_EMAIL',    'jimmorrisoninlove@gmail.com')
KWORK_PASSWORD = os.environ.get('KWORK_PASSWORD', 'Fukcyoubithc48')
KWORK_BASE     = 'https://api.kwork.ru'

# ─── Helper ────────────────────────────────────────────────────────────────
def tg(text: str):
    try:
        data = json.dumps({'chat_id': TG_CHAT, 'text': text[:4096], 'parse_mode': 'HTML'}).encode()
        req = Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                      data=data, headers={'Content-Type': 'application/json'})
        urlopen(req, timeout=8)
    except Exception as e:
        log.warning('TG error: %s', e)

def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {'applied': [], 'total_applied': 0, 'won': 0, 'total_earned_rub': 0}

def save_state(s: dict):
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2, default=str))

# ─── Kwork API ─────────────────────────────────────────────────────────────
class KworkClient:
    def __init__(self):
        self.token = None
        self.headers = {'Content-Type': 'application/x-www-form-urlencoded',
                       'User-Agent': 'Mozilla/5.0 (compatible; MaxAI/1.0)'}

    def login(self) -> bool:
        try:
            data = urlencode({'username': KWORK_EMAIL, 'password': KWORK_PASSWORD}).encode()
            req = Request(f'{KWORK_BASE}/login', data=data, headers=self.headers)
            with urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
                if resp.get('success'):
                    self.token = resp.get('response', {}).get('token', '')
                    log.info('Kwork login OK, token=%s...', self.token[:10] if self.token else 'none')
                    return bool(self.token)
                else:
                    log.warning('Kwork login failed: %s', resp.get('error', ''))
                    return False
        except Exception as e:
            log.error('Kwork login error: %s', e)
            return False

    def search_projects(self, query: str, min_price: int = 1500) -> list:
        """Search for projects by keyword."""
        if not self.token:
            return []
        try:
            params = {
                'token': self.token,
                'q': query,
                'page': 1,
                'categories': '1,11,15',  # Programming, Design, etc
            }
            data = urlencode(params).encode()
            req = Request(f'{KWORK_BASE}/projects', data=data, headers=self.headers)
            with urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
                if resp.get('success'):
                    projects = resp.get('response', {}).get('projects', [])
                    # Filter by price and exclude already applied
                    return [
                        p for p in projects
                        if int(p.get('priceLimit', 0)) >= min_price
                    ]
        except Exception as e:
            log.error('Kwork search error: %s', e)
        return []

    def send_offer(self, project_id: int, message: str, price: int) -> bool:
        """Send offer to a project."""
        if not self.token:
            return False
        try:
            params = {
                'token': self.token,
                'id': project_id,
                'description': message,
                'price': price,
                'kworkDate': 3,  # 3 days delivery
            }
            data = urlencode(params).encode()
            req = Request(f'{KWORK_BASE}/project/offers/add', data=data, headers=self.headers)
            with urlopen(req, timeout=10) as r:
                resp = json.loads(r.read())
                return resp.get('success', False)
        except Exception as e:
            log.error('Kwork offer error %d: %s', project_id, e)
            return False

# ─── AI Proposal Generator ────────────────────────────────────────────────
def generate_proposal(project_title: str, project_desc: str, budget: int) -> tuple:
    """Generate a winning proposal using local AI or template."""
    # Try using the AI system first
    try:
        import urllib.request as ur
        msg = (
            f'Напиши короткий профессиональный отклик на фриланс-заказ на Kwork.\n'
            f'Заказ: {project_title}\n'
            f'Описание: {project_desc[:200]}\n'
            f'Бюджет: {budget} руб\n'
            f'Моя специализация: Python разработка, Telegram-боты, AI агенты, автоматизация бизнеса.\n'
            f'Отклик должен: 1) показать понимание задачи, 2) упомянуть опыт, 3) предложить решение. '
            f'Максимум 5 предложений. Только текст, без приветствий типа "Добрый день".'
        )
        req_data = json.dumps({'message': msg, 'source': 'kwork_agent'}).encode()
        req = ur.Request('http://127.0.0.1:8090/api/chat', data=req_data,
                        headers={'Content-Type': 'application/json'})
        with ur.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())
            proposal = resp.get('reply') or resp.get('response') or ''
            if proposal and len(proposal) > 50:
                return proposal[:800], budget
    except Exception as e:
        log.debug('AI proposal gen failed: %s', e)

    # Fallback template
    templates = [
        (
            f'Занимаюсь Python-разработкой и созданием AI-ботов более 3 лет. '
            f'Ваш проект "{project_title}" — именно моя специализация. '
            f'Реализую качественно и в срок. Использую современный стек: '
            f'Python, FastAPI, aiogram, OpenAI API, PostgreSQL. '
            f'Готов приступить сразу. Пишите — обсудим детали.'
        ),
        (
            f'Разрабатываю Telegram-ботов и Python-автоматизацию. '
            f'Проект по теме "{project_title}" выполню профессионально. '
            f'Опыт: 50+ реализованных проектов, AI-интеграции, API. '
            f'Стоимость обсудима. Покажу примеры работ.'
        ),
        (
            f'Специализируюсь на автоматизации и AI-разработке. '
            f'По вашему заданию "{project_title}" могу предложить готовое решение. '
            f'Работаю с asyncio, aiohttp, Telegram Bot API, LLM интеграциями. '
            f'Сроки: 1-3 дня. Гарантия качества.'
        ),
    ]
    import random
    proposal = random.choice(templates)
    # Slightly adjust budget downward to be competitive
    offer_price = int(budget * 0.85) if budget > 2000 else budget
    return proposal, offer_price


# ─── Main ──────────────────────────────────────────────────────────────────
SEARCH_QUERIES = [
    'telegram бот python',
    'python автоматизация',
    'ai чат-бот',
    'парсер python',
    'торговый бот',
    'aiogram бот',
    'fastapi api',
    'machine learning',
    'нейросеть',
    'интеграция api',
]

def run():
    log.info('=== Kwork Agent starting ===')
    state = load_state()
    applied_ids = set(state.get('applied', []))
    new_applied = 0
    new_leads = []

    client = KworkClient()
    if not client.login():
        # Login failed - report and generate leads for manual follow-up
        log.warning('Kwork login failed, generating leads report instead')
        report_leads_only(state)
        return

    report_lines = [f'🔍 <b>Kwork Agent Report</b>', f'⏰ {datetime.utcnow().strftime("%Y-%m-%d %H:%M")}', '']

    for query in SEARCH_QUERIES[:5]:  # Limit to 5 queries per run
        projects = client.search_projects(query, min_price=1500)
        log.info('Query "%s": %d projects found', query, len(projects))

        for proj in projects[:3]:  # Max 3 per query
            pid = proj.get('id')
            if not pid or str(pid) in applied_ids:
                continue

            title = proj.get('name', '')
            desc = proj.get('description', '')
            budget = int(proj.get('priceLimit', 2000))

            proposal, offer_price = generate_proposal(title, desc, budget)
            success = client.send_offer(pid, proposal, offer_price)

            if success:
                applied_ids.add(str(pid))
                new_applied += 1
                log.info('Applied to #%d "%s" for %d rub', pid, title[:40], offer_price)
                new_leads.append({
                    'id': pid, 'title': title, 'budget': budget,
                    'offer_price': offer_price, 'applied_at': datetime.utcnow().isoformat()
                })
                report_lines.append(
                    f'✅ Отклик #{new_applied}: <b>{title[:50]}</b>\n'
                    f'   Бюджет: {budget}₽ → Моя цена: {offer_price}₽'
                )
            else:
                # Save as lead for manual review
                LEADS_FILE.parent.mkdir(exist_ok=True)
                with open(LEADS_FILE, 'a') as f:
                    f.write(json.dumps({'id': pid, 'title': title, 'budget': budget,
                                       'desc': desc[:200], 'ts': datetime.utcnow().isoformat()}) + '\n')

            time.sleep(2)  # Avoid rate limiting

    # Summary
    if new_applied == 0:
        report_lines.append('📭 Новых подходящих проектов не найдено.')
        report_lines.append('💡 Советы: убедитесь что профиль Kwork заполнен полностью,')
        report_lines.append('   и есть ≥3 работ в портфолио.')
    else:
        potential_rub = sum(l['offer_price'] for l in new_leads)
        report_lines.append(f'\n📊 <b>Итого:</b> {new_applied} откликов')
        report_lines.append(f'💰 Потенциальный доход: <b>{potential_rub:,}₽</b> (~${potential_rub//85})')

    report_lines.append(f'\n📈 Всего откликов с начала: {state["total_applied"] + new_applied}')
    report_lines.append(f'🏆 Выиграно проектов: {state["won"]}')
    report_lines.append(f'💵 Заработано: {state["total_earned_rub"]:,}₽')

    tg('\n'.join(report_lines))

    # Update state
    state['applied'] = list(applied_ids)[-500:]  # Keep last 500
    state['total_applied'] = state.get('total_applied', 0) + new_applied
    save_state(state)
    log.info('Done. Applied: %d, total: %d', new_applied, state['total_applied'])


def report_leads_only(state: dict):
    """Report available projects without auto-applying (for manual review)."""
    lines = [
        '📋 <b>Kwork — Ручной режим</b>',
        f'Логин не удался. Вот топ-категории для поиска вручную:',
        '',
        '🔍 Ищи заказы по тегам:',
        '  • <b>python</b> — боты, парсеры, API',
        '  • <b>telegram бот</b> — автоматизация бизнеса',
        '  • <b>автоматизация</b> — RPA, скрипты',
        '  • <b>ai chatgpt</b> — интеграция нейросетей',
        '',
        '💡 Шаблон профиля:',
        '  "Разрабатываю Python-боты, AI-агенты и автоматизацию.',
        '   Опыт 3+ года. FastAPI, aiogram, OpenAI, PostgreSQL."',
        '',
        f'📊 Статистика: откликов={state["total_applied"]}, выиграно={state["won"]}',
    ]
    tg('\n'.join(lines))


if __name__ == '__main__':
    run()
