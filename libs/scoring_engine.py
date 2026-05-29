from abc import ABC, abstractmethod
from typing import Dict, List

class ScoringEngineInterface(ABC):
    @abstractmethod
    def score(self, skills: List[str], query: str) -> Dict[str, float]:
        """Compute scores for skills based on the query."""
        pass

class PgVectorScoringEngine(ScoringEngineInterface):
    def __init__(self, host: str, port: int, database: str, user: str, password: str):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password

    def score(self, skills: List[str], query: str) -> Dict[str, float]:
        # Implement pgvector skill matching logic here
        pass