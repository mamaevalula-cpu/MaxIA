"""Cluster A — Labor Marketplace Channel Adapters (8 platforms)"""
import os, time, logging
from dataclasses import dataclass, field
from typing import Dict, Any

log = logging.getLogger("adapters.cluster_a")

@dataclass
class AdapterResult:
    platform: str; success: bool
    data: Dict[str,Any] = field(default_factory=dict)
    cost_usd: float = 0.0; latency_ms: float = 0.0; mock: bool = False

class _Base:
    platform = "base"; env_key = ""
    def __init__(self):
        self.api_key = os.environ.get(self.env_key, "")
        self.mock = not bool(self.api_key)
    def health(self):
        return {"platform": self.platform, "mock": self.mock, "key_set": bool(self.api_key)}
    async def execute(self, task: dict) -> AdapterResult:
        raise NotImplementedError

try:
    import aiohttp as _aio
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

async def _post(url, headers, payload, timeout=30):
    if not HAS_AIOHTTP:
        return 200, {"mock_no_aiohttp": True}
    import aiohttp
    async with aiohttp.ClientSession() as s:
        r = await s.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=timeout))
        return r.status, await r.json(content_type=None)

class RelevanceAIAdapter(_Base):
    """Relevance AI — MCP-compatible AI workforce"""
    platform = "relevance_ai"; env_key = "RELEVANCE_AI_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True,
                {"agent_run": "mock", "output": "AI workforce task routed", "task_id": task.get("id","?")},
                0.05, round((time.time()-t)*1000, 1), True)
        try:
            s, d = await _post(
                f"https://api.relevanceai.com/latest/agents/{task.get('agent_id','default')}/trigger",
                {"Authorization": f"Key {self.api_key}"},
                {"message": {"role":"user","content": task.get("prompt","")}}
            )
            return AdapterResult(self.platform, s==200, d, 0.05, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class N8NAdapter(_Base):
    """n8n — Redis DAG workflow executor"""
    platform = "n8n"; env_key = "N8N_WEBHOOK_URL"
    async def execute(self, task):
        t = time.time()
        url = os.environ.get("N8N_WEBHOOK_URL", "")
        if not url:
            return AdapterResult(self.platform, True,
                {"workflow": "mock_dag", "nodes": 4, "status": "completed"}, 0.0, 12.0, True)
        try:
            s, d = await _post(url, {}, task)
            return AdapterResult(self.platform, s==200, d, 0.0, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class PipedreamAdapter(_Base):
    """Pipedream — 128MB serverless pod"""
    platform = "pipedream"; env_key = "PIPEDREAM_API_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True,
                {"pod_id":"pd_mock_128mb","memory_mb":42,"result":"ok"}, 0.001, 250.0, True)
        try:
            s, d = await _post("https://api.pipedream.com/v1/workflows",
                {"Authorization": f"Bearer {self.api_key}"}, {"trigger": task})
            return AdapterResult(self.platform, s in (200,201), d, 0.001, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class VellumAdapter(_Base):
    """Vellum — LLM evals + prompt versioning"""
    platform = "vellum"; env_key = "VELLUM_API_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True,
                {"eval_score":0.89,"model":"mock","prompt_version":"v1.2"}, 0.01, 180.0, True)
        try:
            s, d = await _post("https://api.vellum.ai/v1/generate",
                {"X-API-Key": self.api_key},
                {"deployment_name": task.get("deployment","default"), "inputs": task.get("inputs",[])})
            return AdapterResult(self.platform, s==200, d, 0.01, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class MakeComAdapter(_Base):
    """Make.com — JSON contract automation"""
    platform = "make_com"; env_key = "MAKE_WEBHOOK_URL"
    async def execute(self, task):
        t = time.time()
        url = os.environ.get("MAKE_WEBHOOK_URL", "")
        if not url:
            return AdapterResult(self.platform, True,
                {"scenario_run":"mock","ops":5,"transfer_mb":0.2}, 0.001, 300.0, True)
        try:
            s, d = await _post(url, {}, task)
            return AdapterResult(self.platform, s==200, d, 0.001, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class ZapierAdapter(_Base):
    """Zapier — SMB automation connector"""
    platform = "zapier"; env_key = "ZAPIER_WEBHOOK_URL"
    async def execute(self, task):
        t = time.time()
        url = os.environ.get("ZAPIER_WEBHOOK_URL", "")
        if not url:
            return AdapterResult(self.platform, True,
                {"zap_run":"mock","steps":3,"status":"success"}, 0.0, 400.0, True)
        try:
            s, d = await _post(url, {}, task)
            return AdapterResult(self.platform, s==200, d, 0.0, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class FlowiseAdapter(_Base):
    """Flowise — JSON template chatflow"""
    platform = "flowise"; env_key = "FLOWISE_API_KEY"
    async def execute(self, task):
        t = time.time()
        api_url = os.environ.get("FLOWISE_API_URL", "")
        if not api_url:
            return AdapterResult(self.platform, True,
                {"text":"Flowise chatflow mock","tokens":150}, 0.003, 800.0, True)
        try:
            s, d = await _post(
                f"{api_url}/api/v1/prediction/{task.get('flow_id','')}",
                {"Authorization": f"Bearer {self.api_key}"},
                {"question": task.get("prompt",""), "overrideConfig": task.get("config",{})}, 60)
            return AdapterResult(self.platform, s==200, d, 0.003, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class LangflowAdapter(_Base):
    """Langflow — embedding cache pipeline"""
    platform = "langflow"; env_key = "LANGFLOW_API_KEY"
    async def execute(self, task):
        t = time.time()
        api_url = os.environ.get("LANGFLOW_API_URL", "")
        if not api_url:
            return AdapterResult(self.platform, True,
                {"result":"Langflow mock","cache_hit":True,"embed_dim":1536}, 0.002, 120.0, True)
        try:
            s, d = await _post(
                f"{api_url}/api/v1/run/{task.get('flow_id','')}",
                {}, {"inputs": task.get("inputs",{}), "tweaks": task.get("tweaks",{})}, 60)
            return AdapterResult(self.platform, s==200, d, 0.002, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

REGISTRY = {c.platform: c for c in [
    RelevanceAIAdapter, N8NAdapter, PipedreamAdapter, VellumAdapter,
    MakeComAdapter, ZapierAdapter, FlowiseAdapter, LangflowAdapter
]}
def get_all(): return {k: v() for k,v in REGISTRY.items()}
