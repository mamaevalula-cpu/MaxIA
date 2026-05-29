# telegram_mini_app_react

Базовая структура React-проекта для Telegram Mini App с интеграцией TWA, настройкой Vite, маршрутизацией и поддержкой тактильной обратной связи

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
- python-telegram-bot

## Создан

Проект создан автоматически агентом `ProjectCreatorAgent` системы `my_personal_ai`.
