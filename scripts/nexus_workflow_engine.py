#!/usr/bin/env python3
"""
MaxAI Workflow Engine — Agent-to-Agent (A2A) Chains
====================================================
Chains multiple agents in sequence for complex tasks.

Workflows:
  research_and_present: researcher → analyst → presenter
  find_and_apply:       researcher → hunter
  scrape_and_analyze:   parser → analyst
  market_pitch:         researcher → finance → presenter
  legal_and_hr:         legal → hr
  full_startup:         researcher → coder → designer → finance → presenter
"""
import json, time, logging
from datetime import datetime, timezone
import redis as _redis
import os

log = logging.getLogger('nexus.workflow')
rdb = _redis.from_url('redis://127.0.0.1:6379/0', decode_responses=True)

BUILTIN_WORKFLOWS = {
    "research_and_present": {
        "name": "Исследование + Презентация",
        "emoji": "🔬🎨",
        "desc": "Исследует тему и создаёт профессиональную презентацию",
        "steps": [
            {"agent": "researcher", "prompt": "Подготовь детальное исследование: {input}"},
            {"agent": "analyst",    "prompt": "Проанализируй результаты: {step_0_result}. Ключевые метрики."},
            {"agent": "presenter",  "prompt": "Создай презентацию о '{input}'. Данные: {step_1_result}"},
        ],
        "price": 15, "time_est": "3-5 мин"
    },
    "find_and_apply": {
        "name": "Поиск клиентов + Отклик",
        "emoji": "🎯📝",
        "desc": "Ищет проекты на фриланс-биржах и пишет персональные предложения",
        "steps": [
            {"agent": "researcher", "prompt": "Найди актуальные проекты для: {input}. Kwork, Upwork, Freelancer."},
            {"agent": "hunter",     "prompt": "Напиши убедительный отклик для проекта: {input}. Контекст: {step_0_result}"},
        ],
        "price": 8, "time_est": "2-4 мин"
    },
    "scrape_and_analyze": {
        "name": "Парсинг + Аналитика",
        "emoji": "🕷️📈",
        "desc": "Пишет парсер и анализирует данные с выдачей инсайтов",
        "steps": [
            {"agent": "parser",   "prompt": "Напиши полный код парсера для: {input}"},
            {"agent": "analyst",  "prompt": "Проанализируй данные: {step_0_result}. Дай инсайты и рекомендации."},
        ],
        "price": 10, "time_est": "3-6 мин"
    },
    "market_pitch": {
        "name": "Рынок + Финмодель + Питч",
        "emoji": "📊💰🎨",
        "desc": "Полный инвестиционный пакет",
        "steps": [
            {"agent": "researcher", "prompt": "Исследуй рынок: {input}"},
            {"agent": "finance",    "prompt": "Финансовая модель для: {input}. Рынок: {step_0_result}"},
            {"agent": "presenter",  "prompt": "Инвестиционный питч для: {input}. Финмодель: {step_1_result}"},
        ],
        "price": 25, "time_est": "5-8 мин"
    },
    "legal_and_hr": {
        "name": "Договор + HR пакет",
        "emoji": "⚖️👥",
        "desc": "Полный юридический и HR комплект для найма",
        "steps": [
            {"agent": "legal", "prompt": "Составь договор для: {input}"},
            {"agent": "hr",    "prompt": "Создай HR пакет (вакансия + вопросы + оффер) для: {input}"},
        ],
        "price": 20, "time_est": "4-7 мин"
    },
    "full_startup": {
        "name": "Full Startup Kit",
        "emoji": "🚀",
        "desc": "Полный стартап-пакет: исследование, MVP, дизайн, финмодель, презентация",
        "steps": [
            {"agent": "researcher", "prompt": "Исследуй рынок и конкурентов для стартапа: {input}"},
            {"agent": "coder",      "prompt": "Разработай MVP архитектуру для: {input}. Рынок: {step_0_result}"},
            {"agent": "designer",   "prompt": "Создай лендинг и UI для: {input}. MVP: {step_1_result}"},
            {"agent": "finance",    "prompt": "Финансовая модель для: {input}. Рынок: {step_0_result}"},
            {"agent": "presenter",  "prompt": "Инвестиционная презентация для: {input}. Данные: {step_3_result}"},
        ],
        "price": 50, "time_est": "10-15 мин"
    },
    "content_campaign": {
        "name": "Контент-кампания",
        "emoji": "📣✍️",
        "desc": "Разрабатывает стратегию и создаёт контент для всех каналов",
        "steps": [
            {"agent": "researcher", "prompt": "Исследуй аудиторию и тренды для: {input}"},
            {"agent": "marketer",   "prompt": "Создай контент-стратегию для: {input}. Данные: {step_0_result}"},
            {"agent": "marketer",   "prompt": "Напиши 5 постов для Telegram и LinkedIn о: {input}. Стратегия: {step_1_result}"},
        ],
        "price": 12, "time_est": "3-5 мин"
    },
}


def create_workflow_job(workflow_id: str, user_input: str, client_id: str) -> dict:
    """Create a workflow execution job."""
    wf = BUILTIN_WORKFLOWS.get(workflow_id)
    if not wf:
        return {"error": f"Workflow '{workflow_id}' not found. Available: {list(BUILTIN_WORKFLOWS.keys())}"}

    job_id = 'WF' + str(int(time.time()))[-8:]
    job = {
        "id": job_id,
        "workflow_id": workflow_id,
        "workflow_name": wf["name"],
        "input": user_input,
        "client_id": client_id,
        "status": "pending",
        "steps_total": len(wf["steps"]),
        "steps_done": 0,
        "results": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "final_result": None,
    }

    rdb.set(f"nexus:workflow:{job_id}", json.dumps(job), ex=86400 * 3)
    rdb.lpush("nexus:workflow:queue", json.dumps({
        "job_id": job_id, "workflow_id": workflow_id,
        "input": user_input, "client_id": client_id
    }))
    log.info("Workflow %s created: %s", job_id, workflow_id)
    return job


def get_workflow_job(job_id: str) -> dict:
    raw = rdb.get(f"nexus:workflow:{job_id}")
    return json.loads(raw) if raw else {"error": "Not found"}


def list_workflows() -> list:
    return [
        {"id": wid, "name": w["name"], "emoji": w.get("emoji", "🤖"),
         "desc": w["desc"], "steps": len(w["steps"]),
         "price": w["price"], "time_est": w["time_est"]}
        for wid, w in BUILTIN_WORKFLOWS.items()
    ]


if __name__ == '__main__':
    print(f'Workflows: {len(BUILTIN_WORKFLOWS)}')
    for wid, w in BUILTIN_WORKFLOWS.items():
        print(f'  {w.get("emoji","")} {w["name"]} ({len(w["steps"])} steps) — ${w["price"]}')
