# launch_service

Сервис запуска по 6 каналам для достижения целей по доходу и количеству агентов

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
- fastapi
- uvicorn

## Создан

Проект создан автоматически агентом `ProjectCreatorAgent` системы `my_personal_ai`.
