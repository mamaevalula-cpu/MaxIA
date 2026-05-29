# hyperion_corporation_structure

Структура корпорации на основе Корпорация MaxAI: 5-7 департаментов (Economic Routing, Quality Validation, Data Plane, HR, Finance), лидеры из 29 founding agents, правила 24/7 с SLA (Zero Ambient State, Ephemeral Wrappers), декомпозиция цели '1000 USD/day' в финансовые KPI для каждого департамента.

## Установка

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## Конфигурация

Заполни `.env` на основе `.env.example`.

## Запуск

```bash
python main.py
```

## Зависимости

- python-dotenv
- httpx

## Создан

Проект создан автоматически агентом `ProjectCreatorAgent` системы `my_personal_ai`.
