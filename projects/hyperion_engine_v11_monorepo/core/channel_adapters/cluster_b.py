"""Cluster B — DePIN / Off-chain Compute Adapters (8 platforms)"""
import os, time, logging
from dataclasses import dataclass, field
from typing import Dict, Any

log = logging.getLogger("adapters.cluster_b")

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
    async def execute(self, task: dict) -> AdapterResult: raise NotImplementedError

try:
    import aiohttp as _aio; HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

async def _post(url, headers, payload, timeout=30):
    if not HAS_AIOHTTP: return 200, {"mock_no_aiohttp": True}
    import aiohttp
    async with aiohttp.ClientSession() as s:
        r = await s.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=timeout))
        return r.status, await r.json(content_type=None)

async def _get(url, headers={}, timeout=15):
    if not HAS_AIOHTTP: return 200, {"mock": True}
    import aiohttp
    async with aiohttp.ClientSession() as s:
        r = await s.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout))
        return r.status, await r.json(content_type=None)

class AkashAdapter(_Base):
    """Akash Network — SDL/KEDA auto-scaling decentralized compute"""
    platform = "akash"; env_key = "AKASH_MNEMONIC"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "deployment_id": "akash_mock_001",
                "provider": "akash-provider-1.com",
                "cpu_units": task.get("cpu", 0.5),
                "memory_mb": task.get("memory_mb", 512),
                "status": "running",
                "monthly_cost_usd": 2.5
            }, 0.001, 5000.0, True)
        # Real: use akash-py or subprocess with akash CLI
        return AdapterResult(self.platform, False, {"error": "akash_key_required"}, 0, 0)

class SingularityNetAdapter(_Base):
    """SingularityNET — gRPC AI service marketplace"""
    platform = "singularity_net"; env_key = "SNET_PRIVATE_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "service": task.get("service_id", "mock_service"),
                "result": "AI inference completed",
                "agix_spent": 0.5,
                "confidence": 0.92
            }, 0.05, 2000.0, True)
        return AdapterResult(self.platform, False, {"error": "snet_key_required"}, 0, 0)

class FetchAIAdapter(_Base):
    """Fetch.ai — uAgents autonomous economic agents"""
    platform = "fetch_ai"; env_key = "FETCH_AI_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "agent_address": "agent1q_mock",
                "message_sent": True,
                "dialogue_id": "fetch_mock_001",
                "protocol": "uAgents/0.13"
            }, 0.01, 1500.0, True)
        try:
            s, d = await _post("https://agentverse.ai/v1/submit",
                {"Authorization": f"Bearer {self.api_key}"},
                {"destination": task.get("agent_address",""),
                 "payload": task.get("payload",{})})
            return AdapterResult(self.platform, s==200, d, 0.01, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class OceanAdapter(_Base):
    """Ocean Protocol — TEE data marketplace"""
    platform = "ocean"; env_key = "OCEAN_PRIVATE_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "asset_did": f"did:op:mock_{task.get('dataset','data')}",
                "compute_job_id": "ocean_job_mock",
                "tee_verified": True,
                "data_tokens_spent": 1.0
            }, 0.02, 3000.0, True)
        return AdapterResult(self.platform, False, {"error": "ocean_key_required"}, 0, 0)

class WardenAdapter(_Base):
    """Warden Protocol — threshold-key MPC security"""
    platform = "warden"; env_key = "WARDEN_API_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "keychain_id": "warden_mock_001",
                "threshold": "2/3",
                "key_type": task.get("key_type", "ecdsa"),
                "signed": True
            }, 0.001, 800.0, True)
        try:
            s, d = await _post("https://api.wardenprotocol.org/warden/warden/v1beta3/keys",
                {"Authorization": f"Bearer {self.api_key}"}, task)
            return AdapterResult(self.platform, s==200, d, 0.001, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class BitteAdapter(_Base):
    """Bitte — Cross-chain NEAR AI agent"""
    platform = "bitte"; env_key = "BITTE_API_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "agent_id": "bitte.near",
                "chain": "NEAR",
                "cross_chain": task.get("target_chain","ETH"),
                "tx_hash": "mock_txhash_bitte"
            }, 0.005, 1200.0, True)
        try:
            s, d = await _post("https://wallet.bitte.ai/api/v1/agent/run",
                {"Authorization": f"Bearer {self.api_key}"},
                {"messages": [{"role":"user","content":task.get("prompt","")}]})
            return AdapterResult(self.platform, s==200, d, 0.005, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class RivalzAdapter(_Base):
    """Rivalz — Decentralized data processing workers"""
    platform = "rivalz"; env_key = "RIVALZ_API_KEY"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "worker_id": "rivalz_worker_mock",
                "data_processed_mb": task.get("size_mb", 10),
                "riv_earned": 2.5,
                "consensus_reached": True
            }, 0.003, 2500.0, True)
        try:
            s, d = await _post("https://api.rivalz.ai/v1/process",
                {"Authorization": f"Bearer {self.api_key}"}, task)
            return AdapterResult(self.platform, s==200, d, 0.003, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

class ClawstrAdapter(_Base):
    """Clawstr — L402 Lightning micropayments for AI APIs"""
    platform = "clawstr"; env_key = "CLAWSTR_INVOICE_URL"
    async def execute(self, task):
        t = time.time()
        if self.mock:
            return AdapterResult(self.platform, True, {
                "payment_hash": "clawstr_mock_phash",
                "sats_paid": task.get("sats", 100),
                "service_result": "content_delivered",
                "l402_token": "l402:mock:token"
            }, 0.0001, 600.0, True)
        try:
            invoice_url = os.environ.get("CLAWSTR_INVOICE_URL","")
            s, d = await _post(invoice_url, {}, task)
            return AdapterResult(self.platform, s==200, d, 0.0001, round((time.time()-t)*1000,1))
        except Exception as e:
            return AdapterResult(self.platform, False, {"error":str(e)}, 0, round((time.time()-t)*1000,1))

REGISTRY = {c.platform: c for c in [
    AkashAdapter, SingularityNetAdapter, FetchAIAdapter, OceanAdapter,
    WardenAdapter, BitteAdapter, RivalzAdapter, ClawstrAdapter
]}
def get_all(): return {k: v() for k,v in REGISTRY.items()}
