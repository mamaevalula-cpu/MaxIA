# hyperion_command_center

Monolith skeleton with NestJS backend + React frontend, Redis caching, Docker containerization, and Hyperion Command Center base layout

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

- fastapi
- uvicorn
- jinja2
- python-dotenv

## Создан

Проект создан автоматически агентом `ProjectCreatorAgent` системы `my_personal_ai`.
