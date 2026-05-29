# MaxAI System — AI Agent Training Brief
## Дата: 2026-05-24

## КРИТИЧЕСКИЕ ПРАВИЛА ДЛЯ АГЕНТА-КОДЕРА:

### Перед любым изменением файла:
1. ВСЕГДА читай файл через read_file/shell сначала
2. Редактируй ТОЧЕЧНО (edit_file), не переписывай весь файл
3. Проверяй синтаксис: python3 -m py_compile <файл>
4. Целевой файл определяй по заданию, не создавай новые

### Маршруты инструментов:
- Изменение dashboard → /root/my_personal_ai/dashboard/static/index.html
- Изменение агентов → /root/my_personal_ai/agents/<agent_name>.py
- Изменение brain → /root/my_personal_ai/brain/orchestrator.py
- Гиги на kwork → /root/my_personal_ai/data/kwork_gigs.json
- Каталог агентов → /root/my_personal_ai/data/agent_catalog.json
- Расписание → /root/my_personal_ai/scripts/project_runner.py

### Структура компании MaxAI:
- CEO: maxwell | CTO: helix | CMO: aurora | CFO: nexus | HR: titan
- Dept: maxai-dev (боты, API) | maxai-sales | maxai-marketing | maxai-trading
- Гиги опубликованы: kwork.ru (3 гига) — telegram bot, trading bot, parser
- Цель: 1000 агентов продать/сдать в аренду

### Hyperion v12:
- Control Plane: localhost:8006 | nginx proxy: /api/hyperion/
- Dashboard: localhost:8080 (nginx) → 8090 (personal-ai)
- DB: postgresql://postgres:hyperion_v12_pass@127.0.0.1/hyperion_v12
- Capabilities: 15 зарегистрировано

### Связи с Claude (claude.ai):
- claude_dev_agent.py — использует ANTHROPIC_API_KEY из .env
- Используй для сложных многошаговых задач с инструментами
- Команда: brain.register_agent('claude_dev', ClaudeDevAgent())
- Оркестратор теперь маршрутизирует code_change → claude_dev первым

### Активные LLM:
- Groq (GROQ_API_KEY) — быстрый, бесплатный, для простых задач
- Claude (ANTHROPIC_API_KEY) — для кода, сложного анализа
- Grok-3-mini — для творческих задач


## Lessons learned 2026-05-24:
- Coder agent JSON: use _extract_json_safe(), never raw json.loads()
- All agents must have process() method — add to base_agent check