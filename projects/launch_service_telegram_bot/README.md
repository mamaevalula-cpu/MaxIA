# launch_service_telegram_bot

Telegram-бот/канал с прямыми предложениями SaaS-API клиентам

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

- python-telegram-bot
- python-dotenv
- httpx
- fastapi
- uvicorn

## Создан

Проект создан автоматически агентом `ProjectCreatorAgent` системы `my_personal_ai`.
