# mlops_eval_system

Структура проекта MLOps/системы оценки качества с модулями validation_results, audit_logger, scoring_engine, routing_policy, agent_lifecycle

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

- scikit-learn
- pandas
- numpy
- joblib

## Создан

Проект создан автоматически агентом `ProjectCreatorAgent` системы `my_personal_ai`.
