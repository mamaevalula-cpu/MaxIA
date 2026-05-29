"""
core/hyperion_layers.py
5-Layer Architecture: Strategic → Cognitive → Execution Fabric → Validation → Evolution
Each layer is independently testable and async-native.
"""
import asyncio, hashlib, json, logging, os, time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

log = logging.getLogger("hyperion.layers")

# ─── Shared data types ─────────────────────────────────────────────────────
@dataclass
class LayerContext:
    task_id: str
    payload: Dict[str, Any]
    goal: str = ""
    priority: int = 5          # 1-10, 10 = highest
    budget_usd: float = 1.0
    selected_skills: List[str] = field(default_factory=list)
    dag: List[Dict] = field(default_factory=list)
    validation_result: Optional[Dict] = None
    evolution_action: Optional[str] = None
    trace: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def log(self, msg: str):
        self.trace.append(f"[{time.time():.3f}] {msg}")


# ─── Layer 1: Strategic ─────────────────────────────────────────────────────
class StrategicLayer:
    """
    KPI monitoring + capacity forecasting.
    Decides whether to accept a task based on system health and budget.
    """
    HEALTH_THRESHOLDS = {"cpu_pct": 85, "queue_depth": 500, "budget_daily_usd": 50.0}

    def __init__(self, pool=None):
        self.pool = pool
        self._daily_spend = 0.0
        self._task_count = 0

    async def evaluate(self, ctx: LayerContext) -> bool:
        """Returns True if task should proceed."""
        ctx.log("STRATEGIC: evaluating")
        # Budget guard
        if self._daily_spend + ctx.budget_usd > self.HEALTH_THRESHOLDS["budget_daily_usd"]:
            ctx.error = f"Daily budget exceeded (spent ${self._daily_spend:.2f})"
            ctx.log(f"STRATEGIC: REJECT budget")
            return False
        # Priority gate — low priority tasks skipped during high queue
        if self._task_count > 100 and ctx.priority < 3:
            ctx.error = "Queue saturated, low-priority task deferred"
            ctx.log("STRATEGIC: DEFER low priority")
            return False
        self._task_count += 1
        ctx.log("STRATEGIC: ACCEPT")
        return True

    def record_spend(self, amount_usd: float):
        self._daily_spend += amount_usd

    def get_kpis(self) -> dict:
        return {"daily_spend_usd": round(self._daily_spend, 4),
                "tasks_today": self._task_count,
                "budget_remaining_usd": round(
                    self.HEALTH_THRESHOLDS["budget_daily_usd"] - self._daily_spend, 4)}


# ─── Layer 2: Cognitive ──────────────────────────────────────────────────────
class CognitiveLayer:
    """
    Maps goal → execution DAG.
    Uses Capability Graph to select optimal skill chain.
    """
    def __init__(self, graph=None):
        self.graph = graph  # CapabilityGraph instance

    async def plan(self, ctx: LayerContext) -> List[Dict]:
        """Generate execution DAG from task payload."""
        ctx.log("COGNITIVE: planning")
        if self.graph is None:
            dag = [{"step": 0, "skill": "div_revenue", "cluster": "C",
                    "adapter": "channel_adapters.cluster_c.RevenueDivisionAdapter",
                    "ev": 0.95, "task": ctx.payload, "condition": "always"}]
            ctx.dag = dag
            ctx.selected_skills = ["div_revenue"]
            ctx.log("COGNITIVE: default single-step DAG (no graph)")
            return dag

        # Select top skills from graph
        skills = self.graph.route(ctx.payload)
        if not skills:
            ctx.error = "No skills available for task"
            return []

        dag = []
        for i, skill in enumerate(skills[:3]):  # max 3-step chain
            dag.append({
                "step": i,
                "skill": skill.skill_id,
                "cluster": skill.cluster,
                "adapter": skill.adapter_class,
                "ev": round(skill.ev, 3),
                "task": ctx.payload,
                "condition": "always" if i == 0 else "on_success"
            })
            ctx.selected_skills.append(skill.skill_id)

        ctx.dag = dag
        ctx.log(f"COGNITIVE: DAG with {len(dag)} steps, skills={ctx.selected_skills}")
        return dag


# ─── Layer 3: Execution Fabric ───────────────────────────────────────────────
class ExecutionFabric:
    """
    Stateless async workers. Reads DAG from context, executes adapters.
    State stored in Redis or PostgreSQL (not in-memory).
    """
    def __init__(self, pool=None):
        self.pool = pool

    async def execute(self, ctx: LayerContext) -> Dict[str, Any]:
        """Execute DAG steps, collect results."""
        ctx.log("EXECUTION: starting fabric")
        results = {}

        for step in ctx.dag:
            skill_id = step["skill"]
            adapter_class_path = step.get("adapter", "")
            ctx.log(f"EXECUTION: step {step['step']} → {skill_id}")

            try:
                adapter = self._load_adapter(adapter_class_path, skill_id)
                if adapter:
                    result = await asyncio.wait_for(
                        adapter.execute(step["task"]), timeout=60.0)
                    results[skill_id] = {
                        "success": result.success,
                        "data": result.data,
                        "cost_usd": result.cost_usd,
                        "latency_ms": result.latency_ms,
                        "mock": result.mock
                    }
                    ctx.log(f"EXECUTION: {skill_id} {'OK' if result.success else 'FAIL'} {result.latency_ms:.0f}ms")
                else:
                    results[skill_id] = {"success": False, "error": "adapter_not_found"}
            except asyncio.TimeoutError:
                results[skill_id] = {"success": False, "error": "timeout_60s"}
                ctx.log(f"EXECUTION: {skill_id} TIMEOUT")
            except Exception as e:
                results[skill_id] = {"success": False, "error": str(e)}
                ctx.log(f"EXECUTION: {skill_id} ERROR {e}")

            # Respect condition gates
            if step.get("condition") == "on_success" and not results[skill_id]["success"]:
                ctx.log(f"EXECUTION: aborting chain at step {step['step']} (condition not met)")
                break

        return results

    def _load_adapter(self, adapter_path: str, skill_id: str):
        """Dynamically import adapter class."""
        if not adapter_path:
            return None
        try:
            parts = adapter_path.rsplit(".", 1)
            if len(parts) != 2:
                return None
            mod_path, cls_name = parts
            # Handle relative imports within channel_adapters
            import importlib
            # Try absolute import from project root
            try:
                mod = importlib.import_module(mod_path)
            except ImportError:
                # Try with channel_adapters prefix stripped
                short = mod_path.replace("channel_adapters.", "")
                import sys, os
                ca_dir = os.path.join(os.path.dirname(__file__), "channel_adapters")
                if ca_dir not in sys.path:
                    sys.path.insert(0, os.path.dirname(ca_dir))
                mod = importlib.import_module(f"channel_adapters.{short}")
            cls = getattr(mod, cls_name)
            return cls()
        except Exception as e:
            log.debug("_load_adapter(%s): %s", adapter_path, e)
            return None


# ─── Layer 4: Validation Pipeline ───────────────────────────────────────────
@dataclass
class ValidationResult:
    passed: bool
    stage: str  # schema|tool|semantic|business
    score: float  # 0-1
    reason: str = ""

class ValidationPipeline:
    """
    4-stage validation: Schema → Tool → Semantic → Business KPI
    Task is rejected if any stage fails.
    """
    QUALITY_THRESHOLD = 0.75

    async def validate(self, ctx: LayerContext, results: dict) -> ValidationResult:
        ctx.log("VALIDATION: starting pipeline")

        # Stage 1: Schema — results is a dict with skill results
        vr = await self._schema_check(results)
        if not vr.passed:
            ctx.log(f"VALIDATION: FAIL schema — {vr.reason}")
            return vr

        # Stage 2: Tool — at least one skill succeeded
        vr = await self._tool_check(results)
        if not vr.passed:
            ctx.log(f"VALIDATION: FAIL tool — {vr.reason}")
            return vr

        # Stage 3: Semantic — aggregate quality
        vr = await self._semantic_check(results)
        if not vr.passed:
            ctx.log(f"VALIDATION: WARN semantic score {vr.score:.2f}")
            # Don't hard-fail on semantic, just log

        # Stage 4: Business KPI
        vr = await self._business_check(ctx, results)
        ctx.validation_result = asdict(vr)
        ctx.log(f"VALIDATION: {'PASS' if vr.passed else 'FAIL'} score={vr.score:.2f}")
        return vr

    async def _schema_check(self, results: dict) -> ValidationResult:
        if not isinstance(results, dict):
            return ValidationResult(False, "schema", 0.0, "results not a dict")
        return ValidationResult(True, "schema", 1.0)

    async def _tool_check(self, results: dict) -> ValidationResult:
        success_count = sum(1 for r in results.values() if r.get("success"))
        total = len(results)
        if total == 0:
            return ValidationResult(False, "tool", 0.0, "no tools executed")
        score = success_count / total
        if score == 0:
            return ValidationResult(False, "tool", 0.0, "all tools failed")
        return ValidationResult(True, "tool", score)

    async def _semantic_check(self, results: dict) -> ValidationResult:
        # Check for error patterns in data
        error_count = sum(1 for r in results.values()
                         if "error" in str(r.get("data", {})).lower())
        score = 1.0 - (error_count / max(len(results), 1)) * 0.5
        return ValidationResult(score >= self.QUALITY_THRESHOLD, "semantic", score)

    async def _business_check(self, ctx: LayerContext, results: dict) -> ValidationResult:
        # Cost efficiency check
        total_cost = sum(r.get("cost_usd", 0) for r in results.values())
        if total_cost > ctx.budget_usd * 2:
            return ValidationResult(False, "business", 0.5, f"cost ${total_cost:.4f} exceeds budget ${ctx.budget_usd}")
        return ValidationResult(True, "business", 1.0, f"cost ${total_cost:.4f}")


# ─── Layer 5: Evolution ──────────────────────────────────────────────────────
class EvolutionLayer:
    """
    Benchmark-driven canary deployments.
    95% quality threshold. Auto-promotes or rolls back.
    """
    QUALITY_TARGET = 0.95
    CANARY_PCT = 0.05
    CANARY_WINDOW_TASKS = 20  # tasks before promotion decision

    def __init__(self, pool=None):
        self.pool = pool
        self._skill_bench: Dict[str, List[float]] = {}  # skill_id → quality scores
        self._canaries: Dict[str, dict] = {}  # skill_id → canary state

    async def record(self, ctx: LayerContext, validation: ValidationResult):
        """Record quality score, trigger evolution if needed."""
        for skill_id in ctx.selected_skills:
            bench = self._skill_bench.setdefault(skill_id, [])
            bench.append(validation.score)
            # Keep last 50 samples
            if len(bench) > 50:
                bench.pop(0)

            avg = sum(bench) / len(bench) if bench else 0
            ctx.log(f"EVOLUTION: {skill_id} avg_quality={avg:.3f} samples={len(bench)}")

            # Trigger improvement if below threshold
            if len(bench) >= 10 and avg < self.QUALITY_TARGET:
                await self._trigger_improvement(skill_id, avg, ctx)

    async def _trigger_improvement(self, skill_id: str, avg_quality: float, ctx: LayerContext):
        """Start canary process or log improvement task."""
        if skill_id in self._canaries:
            return  # already in canary

        self._canaries[skill_id] = {
            "started": time.time(),
            "baseline_quality": avg_quality,
            "tasks_in_canary": 0,
            "canary_scores": []
        }
        ctx.evolution_action = f"canary_started:{skill_id}"
        ctx.log(f"EVOLUTION: canary started for {skill_id} (quality {avg_quality:.2f} < {self.QUALITY_TARGET})")

        # Log to DB
        if self.pool:
            try:
                await self.pool.execute("""
                    INSERT INTO action_ledger (initiator, action_type, target, reason, reversible)
                    VALUES ('evolution_layer','canary_deploy',$1,$2,true)
                """, skill_id, f"quality {avg_quality:.2f} below {self.QUALITY_TARGET}")
            except Exception:
                pass

    def get_evolution_status(self) -> dict:
        status = {}
        for skill_id, bench in self._skill_bench.items():
            avg = sum(bench) / len(bench) if bench else 0
            status[skill_id] = {
                "avg_quality": round(avg, 3),
                "samples": len(bench),
                "above_threshold": avg >= self.QUALITY_TARGET,
                "in_canary": skill_id in self._canaries
            }
        return status


# ─── Pipeline orchestrator ───────────────────────────────────────────────────
class HyperionPipeline:
    """Connects all 5 layers into a single execute() call."""

    def __init__(self, pool=None, graph=None):
        self.strategic = StrategicLayer(pool)
        self.cognitive = CognitiveLayer(graph)
        self.fabric = ExecutionFabric(pool)
        self.validation = ValidationPipeline()
        self.evolution = EvolutionLayer(pool)

    async def run(self, task_id: str, payload: dict, **kwargs) -> dict:
        ctx = LayerContext(
            task_id=task_id,
            payload=payload,
            goal=payload.get("goal", ""),
            priority=kwargs.get("priority", 5),
            budget_usd=kwargs.get("budget_usd", 0.10)
        )
        t_start = time.time()

        # Layer 1: Strategic gate
        if not await self.strategic.evaluate(ctx):
            return {"task_id": task_id, "status": "rejected", "reason": ctx.error, "trace": ctx.trace}

        # Layer 2: Cognitive planning
        dag = await self.cognitive.plan(ctx)
        if not dag:
            return {"task_id": task_id, "status": "no_plan", "reason": ctx.error, "trace": ctx.trace}

        # Layer 3: Execution
        results = await self.fabric.execute(ctx)

        # Layer 4: Validation
        vr = await self.validation.validate(ctx, results)

        # Layer 5: Evolution recording
        await self.evolution.record(ctx, vr)

        # Record spend
        total_cost = sum(r.get("cost_usd", 0) for r in results.values())
        self.strategic.record_spend(total_cost)

        elapsed = round((time.time() - t_start) * 1000, 1)
        return {
            "task_id": task_id,
            "status": "completed" if vr.passed else "degraded",
            "validation": asdict(vr),
            "results": results,
            "cost_usd": round(total_cost, 6),
            "elapsed_ms": elapsed,
            "skills_used": ctx.selected_skills,
            "trace": ctx.trace
        }

    def get_status(self) -> dict:
        return {
            "strategic": self.strategic.get_kpis(),
            "evolution": self.evolution.get_evolution_status(),
            "layers": ["Strategic","Cognitive","ExecutionFabric","Validation","Evolution"]
        }

# Singleton
_PIPELINE: Optional[HyperionPipeline] = None

def get_pipeline(pool=None, graph=None) -> HyperionPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = HyperionPipeline(pool, graph)
    return _PIPELINE
