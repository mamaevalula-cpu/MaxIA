from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import List, Dict

from brain.llm_router import LLMProvider
from core.config import cfg
from memory.memory_store import KnowledgeEntry

@dataclass
class Agent:
    id: str
    load: float
    skills: List[str]
    success_history: List[KnowledgeEntry]
    metrics: Dict[str, float]  # метрики по 14 осям

@dataclass
class Task:
    id: str
    priority: int
    required_skills: List[str]
    weight_profile: Dict[str, float]  # профиль весов для задачи

class ScoringEngine:
    def __init__(self, agents: List[Agent]):
        self.agents = agents

    def select_best_agent(self, task: Task, available_agents: List[Agent]) -> Agent:
        best_agent = None
        best_score = -np.inf

        for agent in available_agents:
            score = self.calculate_score(task, agent)
            if score > best_score:
                best_score = score
                best_agent = agent

        return best_agent

    def calculate_score(self, task: Task, agent: Agent) -> float:
        # взвешенный общий балл качества
        weighted_score = 0
        for metric, weight in task.weight_profile.items():
            weighted_score += agent.metrics.get(metric, 0) * weight

        return weighted_score

    def update_metrics(self, agent: Agent, metrics: Dict[str, float]):
        agent.metrics.update(metrics)

    def get_metrics(self, agent: Agent) -> Dict[str, float]:
        return agent.metrics