# HYPERION ENGINE v11.0 — Agent Marketplace

Self-improving agent marketplace: register agents, submit tasks, track results, auto-scale.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    HYPERION ENGINE v11.0                        │
│                   Agent Marketplace                             │
├─────────────┬──────────────┬───────────────┬────────────────────┤
│ API Gateway │ Orchestrator │ TaskExecutor  │ ScalerService      │
│ (FastAPI)   │ (routing)    │ (workers)     │ (auto-scale)       │
├─────────────┴──────────────┴───────────────┴────────────────────┤
│              MessageBus (async pub/sub)                          │
├──────────────────────────────────────────────────────────────────┤
│  AgentRegistry (SQLite)  │  HyperionDB (task journal)           │
└──────────────────────────────────────────────────────────────────┘
```

## Microservices

| Service | File | Description |
|---------|------|-------------|
| API Gateway | `api/gateway.py` | REST API: register agents, submit tasks |
| Orchestrator | `core/orchestrator.py` | Routes tasks to best available agent |
| Task Executor | `agents/task_executor_agent.py` | Executes tasks with retry/timeout |
| Scaler | `agents/scaler_service.py` | Auto-scales workers based on queue depth |
| Message Bus | `libs/messaging.py` | Async pub/sub event bus |
| Agent Registry | `core/agent_registry.py` | Persistent agent catalog |
| Storage | `storage/db.py` | Task journal, audit log, improvement suggestions |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Development mode (without Docker)
python main.py

# Production (Docker)
docker-compose up -d

# API docs
open http://localhost:8000/docs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/agents/register` | Register a new agent |
| GET | `/agents` | List active agents |
| POST | `/tasks/submit` | Submit a task |

## Self-Improvement Loop

1. Tasks executed → results stored in `task_journal`
2. Auditor analyses failures → creates entries in `agent_improvement`
3. ScalerService monitors queue depth → emits scale signals
4. Orchestrator selects agents by success rate (self-improving routing)

## Created

Built by HYPERION ENGINE v11.0 autonomous AI system.
