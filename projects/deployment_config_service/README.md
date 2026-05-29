# deployment_config_service

Конфигурация для стабильного развертывания сервиса на порту 8005 с автоперезапуском: Docker/K8s, systemd или cloud deployment

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
