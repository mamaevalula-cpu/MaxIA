# nest_microservice_monorepo

NestJS монорепозиторий с микросервисной архитектурой, включающий базовые конфигурации для TypeScript, ESLint, Jest, Docker, RabbitMQ, PostgreSQL и Kubernetes

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
