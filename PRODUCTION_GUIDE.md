# Production Deployment Guide — Personal AI System

## Общая архитектура

```
┌─────────────────────────────────────────────────────────────┐
│              Personal AI — Autonomous System                 │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐        │
│  │  Telegram   │  │   Trading   │  │   Personal   │        │
│  │    Bot      │  │     Bot     │  │     Brain    │        │
│  └──────┬──────┘  └──────┬──────┘  └──────┬───────┘        │
│         │                 │                │                 │
│         └─────────────────┴────────────────┘                 │
│                    Brain Orchestrator                         │
│                           │                                  │
│  ┌────────────────────────┼────────────────────────┐        │
│  │                        │                        │        │
│  ▼        ▼        ▼      ▼      ▼        ▼      ▼        │
│ [Agents] [Memory] [LLMs] [Knowledge] [Tools] [Training]   │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │  Monitoring Layer                                │       │
│  │  - HealthCheck                                   │       │
│  │  - Watchdog                                      │       │
│  │  - Metrics                                       │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
│  ┌──────────────────────────────────────────────────┐       │
│  │  Reliability & Safety Layer                      │       │
│  │  - Compliance Checker                            │       │
│  │  - User Perspective Validator                    │       │
│  │  - System Polisher                               │       │
│  └──────────────────────────────────────────────────┘       │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## 1. 24/7 Работа

### 1.1 Основной механизм

```python
# server_launcher.py
- Запускает main.py в цикле
- Перезапускает при падении (max 5 раз)
- Graceful shutdown при сигналах
- Логирует все события
- Управляет PID файлами
```

### 1.2 Автоматический перезапуск

```bash
# На Linux используем systemd
sudo cp personal-ai.service /etc/systemd/system/
sudo systemctl enable personal-ai
sudo systemctl start personal-ai
sudo systemctl status personal-ai

# Просмотр логов
sudo journalctl -u personal-ai -f
```

### 1.3 Health monitoring

```python
# monitoring/healthcheck.py
- Проверка LLM провайдеров
- Проверка памяти и базы данных
- Проверка агентов (heartbeat)
- Проверка Telegram бота
- Проверка системных ресурсов (CPU, RAM, Disk)
- Каждые 60 сек

# Критические компоненты
- system (CPU > 90%, Memory > 90%)
- telegram (API unreachable)
- database (missing/corrupted)
```

## 2. Автоматическая остановка при критических сбоях

### 2.1 Emergency stop conditions

```python
if (
    critical_component_unhealthy or
    state_corruption_detected or
    knowledge_conflict_found or
    dependent_service_unavailable or
    integrity_loss_detected or
    wrong_action_risk_detected or
    policy_violation_detected
):
    # EMERGENCY SHUTDOWN
    stop_dangerous_loops()
    save_emergency_state()
    send_alert_to_user()
    exit(1)
```

### 2.2 Graceful recovery

```python
on_restart:
    1. Check integrity
    2. Verify memory consistency
    3. Check knowledge conflicts
    4. Recover from persistent journal
    5. Only resume after verification
```

### 2.3 Watchdog (monitoring/watchdog.py)

```python
- Мониторит health checks
- Автоматически перезапускает упавшие компоненты
- Ограничивает количество перезапусков
- Отправляет алерты в Telegram
- Сохраняет emergency state при критических сбоях
```

## 3. User-Perspective Validation

### 3.1 Сценарии проверки

```python
validation/user_perspective.py

Сценарии:
1. system_startup
   - Health checks
   - Memory initialization
   - Agent registration

2. telegram_basic_commands
   - /status → выводит статус
   - /help → выводит справку
   - /health → показывает диагностику

3. ai_interaction
   - Простые вопросы
   - Математические вычисления

4. error_handling
   - Graceful error processing
   - Нет crash системы

5. system_restart
   - State recovery
   - Нет потери данных

6. high_load
   - Множество команд подряд
   - Нет degradation производительности

7. compliance_check
   - Нормальный контент разрешен
   - Запрещенный контент заблокирован
```

### 3.2 Запуск валидации

```python
# В main.py
user_validator.set_brain_callback(brain.process)
user_validator.set_telegram_agent(tg_agent)

# Периодический запуск
results = await user_validator.validate_all_scenarios()
summary = user_validator.get_validation_summary(results)
```

## 4. Compliance & Законы

### 4.1 Поддерживаемые юрисдикции

```python
compliance/compliance_checker.py

Россия (ФЗ-152, 187-ФЗ):
- Хранение персональных данных требует согласия
- Доступ к заблокированным сайтам запрещен
- Генерация политического контента ограничена

США (CFAA, DMCA):
- Копирование защищенного контента запрещено
- Несанкционированный доступ запрещен

ЕУ (GDPR):
- Обработка персональных данных требует compliance

Китай:
- Доступ через Great Firewall ограничен
```

### 4.2 Проверка при запуске

```python
from compliance.compliance_checker import compliance_checker

# Определение текущей юрисдикции
jurisdiction = compliance_checker._current_jurisdiction

# Проверка действия
result = compliance_checker.check_action("store_personal_data", "data_processing")
if not result.allowed:
    log_warning(result.message)
    if result.requires_approval:
        request_user_approval()

# Проверка контента
check = compliance_checker.check_content(user_input)
if not check.allowed:
    block_action(check.message)
```

## 5. Automatic Polishing

### 5.1 Polishing loop

```python
polishing/polisher.py

Каждый час (или по требованию):
1. Поиск слабых мест
   - Health issues
   - Performance bottlenecks
   - Integration problems
   - UX degradation
   - Compliance violations
   - Logic errors

2. Автоматическое исправление
   - Restart unhealthy components
   - Initialize empty databases
   - Enable compliance checks
   - Optimize resources

3. Повторное тестирование
   - Run user perspective validation
   - Check performance improvement
   - Verify compliance
   - Validate UX

4. Запись результатов
   - Log issues found
   - Log fixes applied
   - Generate recommendations
```

### 5.2 Запуск

```python
# Auto-run каждый час
if system_polisher.should_run_polish():
    result = await system_polisher.run_polishing_loop()
    log_polishing_result(result)
    system_polisher.mark_polish_done()

# Ручной запуск
/polish  # в Telegram
```

## 6. Интеграция компонентов

### 6.1 Единая семья систем

```
main.py
├─ Brain Orchestrator
│  ├─ Telegram Agent
│  ├─ Trading Agent
│  ├─ Personal Brain
│  └─ [15+ других агентов]
│
├─ Memory Store
│  ├─ Messages (972)
│  ├─ Knowledge (248)
│  └─ Projects (1)
│
├─ Monitoring
│  ├─ HealthCheck (30s interval)
│  ├─ Watchdog (auto-restart)
│  └─ Metrics (Prometheus)
│
├─ Safety & Compliance
│  ├─ ComplianceChecker
│  ├─ UserValidator
│  └─ SystemPolisher
│
└─ Server Launcher
   ├─ Auto-restart (max 5)
   ├─ Graceful shutdown
   └─ PID management
```

### 6.2 Общие точки данных

```python
# Shared memory
mem = MemoryStore.get()  # Все агенты используют

# Shared LLM
router = LLMRouter.get()  # Маршрутизирует запросы

# Shared state
brain = BrainOrchestrator.get()  # Центральная оркестрация

# Shared monitoring
health_checker.register_agent(name, agent)  # Для мониторинга

# Shared compliance
compliance_checker.check_action(...)  # Для всех операций
```

## 7. Развертывание на сервере

### 7.1 Инициализация production

```bash
# 1. Проверка конфигурации
python3 init_production.py

# 2. Запуск через systemd (Linux)
sudo systemctl start personal-ai
sudo systemctl status personal-ai

# 3. Мониторинг логов
sudo journalctl -u personal-ai -f

# 4. Проверка health
curl http://localhost:8000/metrics
```

### 7.2 Требования сервера (minimum)

```
CPU:    2 cores
RAM:    4GB
Disk:   10GB (для логов + данные)
Network: 1Mbps (для API calls)

OS:     Linux (Ubuntu 20.04+) или Windows Server
Python: 3.11+
```

### 7.3 Мониторинг метрик

```
Prometheus меtrики (порт 8000):
- process_uptime_seconds
- trade_latency_ms (P95)
- drawdown_pct
- daily_pnl_usd
- positions_open
- promo_claims_total
- ws_reconnects_total
- error_rate_pct
```

## 8. Telegram Команды для управления 24/7

```
/status      → Полный статус системы
/health      → Health check результаты
/restart     → Перезапуск компонентов
/polish      → Запуск system polishing
/compliance  → Статус compliance
/validate    → User perspective validation
/uptime      → Время работы
/logs        → Последние логи
```

## 9. Автоматический Telegram бот

### 9.1 Конфигурация

```bash
# В .env
TELEGRAM_BOT_TOKEN=8428552836:AAHRCJZf3G30LSe8vuXpVTwr_mPrzVJVIWM
TELEGRAM_CHAT_ID=1985320458
TELEGRAM_ADMIN_IDS=1985320458
```

### 9.2 Возможности

- ✅ Автоматический heartbeat каждые 5 минут
- ✅ Алерты при health issues
- ✅ Поддержка Claude AI для chat
- ✅ Инвайт-система (invite-only)
- ✅ Multi-user поддержка
- ✅ Rate limiting (cooldown 1.5s)

### 9.3 Исправление SSL ошибок

```python
# В agents/telegram_agent.py уже реализовано:
# 1. Попытка certifi (стандартные сертификаты)
# 2. Попытка Windows system cert store
# 3. Fallback на verify=False (последний резерв)

# Результат: ✅ Telegram агент работает в корпоративных сетях
```

## 10. Troubleshooting

### Проблема: SSL Certificate Error в Telegram

**Решение:**
```bash
python3 -m pip install --upgrade certifi
# Уже реализовано в agents/telegram_agent.py
```

### Проблема: Memory leak

**Решение:**
```python
# Автоматически обнаруживается в SystemPolisher
# Action: restart агента или процесс целиком
```

### Проблема: Высокий CPU usage

**Решение:**
```python
# Обнаруживается в HealthCheck
# Рекомендация: Optimize LLM calls, add caching
```

### Проблема: Database corrupted

**Решение:**
```python
# Обнаруживается в HealthCheck
# Emergency stop + restore from backup
```

## 11. Рекомендуемая архитектура для production

```
┌─────────────────────────────────────────────┐
│         Reverse Proxy (nginx)               │
│  - SSL/TLS termination                      │
│  - Load balancing (если 2+ instances)      │
└───────────────┬─────────────────────────────┘
                │
┌───────────────▼─────────────────────────────┐
│    Personal AI Server (systemd service)     │
│  - Main app + all agents                    │
│  - Health monitoring                        │
│  - Telegram bot integrated                  │
└─────────────────────────────────────────────┘
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌──────────┐
│ SQLite │ │ Logs   │ │Prometheus│
│database│ │/Journal│ │ Metrics  │
└────────┘ └────────┘ └──────────┘
```

## 12. Next Steps

1. ✅ Настроить Telegram бот
2. ✅ Исправить SSL ошибки
3. ✅ Установить недостающие зависимости
4. ✅ Создать HealthCheck систему
5. ✅ Создать Watchdog для auto-restart
6. ✅ Создать Compliance layer
7. ✅ Создать User perspective validator
8. ✅ Создать System polisher
9. → Развернуть на VPS (Ubuntu 20.04)
10. → Настроить systemd service
11. → Запустить init_production.py
12. → Мониторить 24/7

## Контакты & Support

- Основной разработчик: Claude Copilot
- Telegram: @BotFather (для создания ботов)
- Документация: CLAUDE.md, это полное руководство