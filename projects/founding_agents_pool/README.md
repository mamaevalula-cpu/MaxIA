# founding_agents_pool

Пул из 29 founding agents с механизмами делегирования, самообучения и масштабирования

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
