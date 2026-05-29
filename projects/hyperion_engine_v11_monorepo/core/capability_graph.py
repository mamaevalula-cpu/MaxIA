"""
core/capability_graph.py
Directed Skill Graph routing engine — no hardcoded agent names.
Nodes = capabilities/skills. Edges = dependency/sequence chains.
EV computation: P(success) * value - P(fail) * cost
"""
import asyncio, hashlib, json, logging, os, time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

log = logging.getLogger("hyperion.cap_graph")

@dataclass
class SkillNode:
    skill_id: str
    name: str
    category: str           # labor|depin|division|discovery
    cluster: str            # A|B|C|D
    adapter_class: str      # module.ClassName
    cost_per_call_usd: float = 0.01
    avg_latency_ms: float = 500.0
    success_rate: float = 0.95
    quality_score: float = 0.85
    active: bool = True
    tags: List[str] = field(default_factory=list)

    @property
    def ev(self) -> float:
        """Expected Value = P(success)*quality - P(fail)*cost_normalized"""
        return self.success_rate * self.quality_score - (1 - self.success_rate) * self.cost_per_call_usd * 10

@dataclass
class SkillEdge:
    from_skill: str
    to_skill: str
    weight: float = 1.0
    condition: str = "always"  # always|on_fail|on_success|parallel

class CapabilityGraph:
    """
    In-memory skill graph backed by PostgreSQL for persistence.
    Routes tasks to best-fit skill using EV-based scoring.
    """
    def __init__(self, pool=None):
        self.pool = pool
        self._nodes: Dict[str, SkillNode] = {}
        self._edges: List[SkillEdge] = []
        self._loaded = False

    async def load(self):
        """Load skill graph from PostgreSQL."""
        if self.pool is None:
            self._load_defaults()
            return
        try:
            rows = await self.pool.fetch("SELECT * FROM skill_nodes WHERE active=true")
            for r in rows:
                tags = json.loads(r["tags"]) if r["tags"] else []
                node = SkillNode(
                    skill_id=r["skill_id"], name=r["name"], category=r["category"],
                    cluster=r["cluster"], adapter_class=r["adapter_class"],
                    cost_per_call_usd=float(r["cost_per_call_usd"]),
                    avg_latency_ms=float(r["avg_latency_ms"]),
                    success_rate=float(r["success_rate"]),
                    quality_score=float(r["quality_score"]),
                    active=r["active"], tags=tags
                )
                self._nodes[node.skill_id] = node
            edge_rows = await self.pool.fetch("SELECT * FROM skill_edges")
            for r in edge_rows:
                self._edges.append(SkillEdge(r["from_skill"], r["to_skill"],
                    float(r["weight"]), r["condition"]))
            log.info("Loaded %d skill nodes, %d edges from DB", len(self._nodes), len(self._edges))
        except Exception as e:
            log.warning("DB load failed (%s), using defaults", e)
            self._load_defaults()
        self._loaded = True

    def _load_defaults(self):
        """Seed graph with default skills if DB unavailable."""
        defaults = [
            # Cluster A
            SkillNode("rel_ai_mcp","Relevance AI MCP","labor","A","channel_adapters.cluster_a.RelevanceAIAdapter",0.05,1200,0.92,0.90,True,["ai","workflow","mcp"]),
            SkillNode("n8n_dag","n8n Redis DAG","labor","A","channel_adapters.cluster_a.N8NAdapter",0.01,300,0.97,0.88,True,["automation","dag","redis"]),
            SkillNode("pipedream","Pipedream 128MB","labor","A","channel_adapters.cluster_a.PipedreamAdapter",0.001,250,0.99,0.85,True,["serverless","event"]),
            SkillNode("vellum","Vellum Evals","labor","A","channel_adapters.cluster_a.VellumAdapter",0.02,180,0.95,0.92,True,["eval","llm","quality"]),
            SkillNode("make_com","Make.com JSON","labor","A","channel_adapters.cluster_a.MakeComAdapter",0.005,350,0.96,0.82,True,["automation","smb"]),
            SkillNode("zapier","Zapier SMB","labor","A","channel_adapters.cluster_a.ZapierAdapter",0.005,400,0.98,0.80,True,["automation","smb","webhook"]),
            SkillNode("flowise","Flowise Templates","labor","A","channel_adapters.cluster_a.FlowiseAdapter",0.003,800,0.94,0.87,True,["llm","chatflow"]),
            SkillNode("langflow","Langflow Embed","labor","A","channel_adapters.cluster_a.LangflowAdapter",0.002,120,0.95,0.89,True,["embedding","cache"]),
            # Cluster B
            SkillNode("akash","Akash SDL/KEDA","depin","B","channel_adapters.cluster_b.AkashAdapter",0.001,5000,0.88,0.85,True,["depin","compute","kubernetes"]),
            SkillNode("singnet","SingularityNET","depin","B","channel_adapters.cluster_b.SingularityNetAdapter",0.05,2000,0.80,0.88,True,["ai","marketplace","depin"]),
            SkillNode("fetch_ai","Fetch.ai uAgents","depin","B","channel_adapters.cluster_b.FetchAIAdapter",0.01,1500,0.82,0.84,True,["agent","depin","aea"]),
            SkillNode("ocean","Ocean TEE","depin","B","channel_adapters.cluster_b.OceanAdapter",0.02,3000,0.78,0.82,True,["data","tee","privacy"]),
            SkillNode("warden","Warden Threshold","depin","B","channel_adapters.cluster_b.WardenAdapter",0.001,800,0.90,0.86,True,["security","mpc","threshold"]),
            SkillNode("bitte","Bitte Cross-chain","depin","B","channel_adapters.cluster_b.BitteAdapter",0.005,1200,0.85,0.83,True,["cross-chain","near","agent"]),
            SkillNode("rivalz","Rivalz Data","depin","B","channel_adapters.cluster_b.RivalzAdapter",0.003,2500,0.80,0.81,True,["data","depin","worker"]),
            SkillNode("clawstr","Clawstr L402","depin","B","channel_adapters.cluster_b.ClawstrAdapter",0.0001,600,0.87,0.84,True,["micropayment","l402","lightning"]),
            # Cluster C
            SkillNode("div_revenue","Revenue Division","division","C","channel_adapters.cluster_c.RevenueDivisionAdapter",0.0,0,1.0,0.95,True,["internal","revenue","kpi"]),
            SkillNode("div_content","Content Division","division","C","channel_adapters.cluster_c.ContentDivisionAdapter",0.0,0,1.0,0.93,True,["internal","content"]),
            SkillNode("div_media","Media Division","division","C","channel_adapters.cluster_c.MediaDivisionAdapter",0.0,0,1.0,0.91,True,["internal","media","telegram"]),
            SkillNode("div_website","Website Division","division","C","channel_adapters.cluster_c.WebsiteDivisionAdapter",0.0,0,1.0,0.90,True,["internal","web"]),
            SkillNode("div_social","Social Division","division","C","channel_adapters.cluster_c.SocialDivisionAdapter",0.0,0,1.0,0.89,True,["internal","social","marketing"]),
            SkillNode("div_finance","Finance Division","division","C","channel_adapters.cluster_c.FinanceDivisionAdapter",0.0,0,1.0,0.94,True,["internal","finance","bybit"]),
            SkillNode("div_hr","HR/Factory Division","division","C","channel_adapters.cluster_c.HRDivisionAdapter",0.0,0,1.0,0.92,True,["internal","hr","agents"]),
            SkillNode("div_infra","Infrastructure Division","division","C","channel_adapters.cluster_c.InfraAdapter",0.0,0,1.0,0.96,True,["internal","devops","vps"]),
            # Cluster D
            SkillNode("hf_spaces","HuggingFace Spaces","discovery","D","channel_adapters.cluster_d.HuggingFaceAdapter",0.0,2000,0.90,0.87,True,["ai","ml","models"]),
            SkillNode("gh_actions","GitHub Actions","discovery","D","channel_adapters.cluster_d.GitHubActionsAdapter",0.0,30000,0.97,0.88,True,["ci","automation","code"]),
            SkillNode("gpt_store","GPT Store","discovery","D","channel_adapters.cluster_d.GPTStoreAdapter",0.03,1500,0.88,0.85,True,["ai","gpt","marketplace"]),
            SkillNode("dify_ai","Dify.ai","discovery","D","channel_adapters.cluster_d.DifyAdapter",0.001,900,0.93,0.88,True,["llm","workflow","rag"]),
            SkillNode("coze","Coze Platform","discovery","D","channel_adapters.cluster_d.CozeAdapter",0.0,1000,0.91,0.86,True,["bot","ai","platform"]),
            SkillNode("poe","Poe Platform","discovery","D","channel_adapters.cluster_d.PoeAdapter",0.005,1200,0.89,0.84,True,["ai","monetization","bot"]),
        ]
        for n in defaults:
            self._nodes[n.skill_id] = n
        self._loaded = True
        log.info("Loaded %d default skill nodes", len(self._nodes))

    def route(self, task: dict) -> List[SkillNode]:
        """
        Route task to best-fit skills using EV scoring + tag matching.
        Returns ranked list of SkillNodes.
        """
        if not self._loaded:
            self._load_defaults()

        task_tags = set(task.get("tags", []))
        task_cluster = task.get("cluster", "")
        task_category = task.get("category", "")

        candidates = []
        for node in self._nodes.values():
            if not node.active:
                continue
            score = node.ev
            # Tag match bonus
            overlap = len(task_tags & set(node.tags))
            score += overlap * 0.1
            # Cluster filter
            if task_cluster and node.cluster != task_cluster:
                score -= 0.5
            # Category filter
            if task_category and node.category != task_category:
                score -= 0.3
            candidates.append((score, node))

        candidates.sort(key=lambda x: -x[0])
        return [n for _, n in candidates[:5]]  # top 5

    def best_skill(self, task: dict) -> Optional[SkillNode]:
        """Return single best skill for a task."""
        ranked = self.route(task)
        return ranked[0] if ranked else None

    async def update_skill_stats(self, skill_id: str, success: bool, latency_ms: float):
        """Update EMA stats after execution."""
        node = self._nodes.get(skill_id)
        if not node:
            return
        alpha = 0.1  # EMA factor
        node.success_rate = alpha * (1.0 if success else 0.0) + (1 - alpha) * node.success_rate
        node.avg_latency_ms = alpha * latency_ms + (1 - alpha) * node.avg_latency_ms
        # Persist to DB
        if self.pool:
            try:
                await self.pool.execute(
                    "UPDATE skill_nodes SET success_rate=$1, avg_latency_ms=$2 WHERE skill_id=$3",
                    node.success_rate, node.avg_latency_ms, skill_id
                )
            except Exception:
                pass

    def get_graph_summary(self) -> dict:
        """Return summary for API/UI consumption."""
        by_cluster = {}
        for n in self._nodes.values():
            by_cluster.setdefault(n.cluster, []).append({
                "id": n.skill_id, "name": n.name, "ev": round(n.ev, 3),
                "success_rate": round(n.success_rate, 3),
                "quality_score": round(n.quality_score, 3),
                "latency_ms": round(n.avg_latency_ms, 1),
                "active": n.active, "tags": n.tags
            })
        return {
            "total_skills": len(self._nodes),
            "active_skills": sum(1 for n in self._nodes.values() if n.active),
            "clusters": by_cluster,
            "top_ev_skills": [
                {"id": n.skill_id, "ev": round(n.ev, 3)}
                for n in sorted(self._nodes.values(), key=lambda x: -x.ev)[:10]
            ]
        }

    async def sync_to_db(self):
        """Upsert all nodes to PostgreSQL."""
        if not self.pool:
            return
        for node in self._nodes.values():
            try:
                await self.pool.execute("""
                    INSERT INTO skill_nodes
                        (skill_id,name,category,cluster,adapter_class,cost_per_call_usd,
                         avg_latency_ms,success_rate,quality_score,active,tags)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (skill_id) DO UPDATE SET
                        success_rate=EXCLUDED.success_rate,
                        avg_latency_ms=EXCLUDED.avg_latency_ms,
                        quality_score=EXCLUDED.quality_score,
                        active=EXCLUDED.active
                """, node.skill_id, node.name, node.category, node.cluster,
                    node.adapter_class, node.cost_per_call_usd, node.avg_latency_ms,
                    node.success_rate, node.quality_score, node.active,
                    json.dumps(node.tags))
            except Exception as e:
                log.debug("sync_to_db error for %s: %s", node.skill_id, e)

# Global singleton (lazy-initialized per app startup)
_GRAPH: Optional[CapabilityGraph] = None

def get_graph(pool=None) -> CapabilityGraph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = CapabilityGraph(pool)
    return _GRAPH
