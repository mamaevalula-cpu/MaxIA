# -*- coding: utf-8 -*-
"""Тест новых NEXT-STAGE компонентов."""
import sys, os, tempfile, time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

passed = 0
total = 0

def chk(name, fn):
    global passed
    try:
        result = fn()
        print(f"  PASS  {name}: {result}")
        passed += 1
        return True
    except Exception as e:
        import traceback
        print(f"  FAIL  {name}: {e}")
        traceback.print_exc()
        return False


# ── 1. ChainOfThoughtEngine singleton + mode selection ──────────────────────
total += 1
def t1():
    from brain.chain_of_thought import ChainOfThoughtEngine, ReasoningMode
    e = ChainOfThoughtEngine.get()
    assert e is ChainOfThoughtEngine.get()

    assert e._select_mode("x", "status").value == "fast"
    assert e._select_mode("x", "monitor").value == "fast"
    assert e._select_mode("реши уравнение x^2=4", "math").value == "chain_of_thought"
    assert e._select_mode("напиши код", "code_change").value == "chain_of_thought"
    assert e._select_mode("что лучше: Django или FastAPI?", "analysis").value == "tree_of_thought"

    # Без LLM -> fast result
    r = e.reason("тест", intent="chat")
    assert r.mode.value == "fast"
    return "singleton + mode_select + no-LLM-fast OK"
chk("ChainOfThoughtEngine", t1)

# ── 2. CoTResult + format_trace ─────────────────────────────────────────────
total += 1
def t2():
    from brain.chain_of_thought import CoTResult, ReasoningMode, ReasoningStep
    r = CoTResult(query="q", mode=ReasoningMode.COT,
                  final_answer="answer", confidence=0.85, verified=True)
    assert r.succeeded
    r2 = CoTResult(query="q", mode=ReasoningMode.COT, final_answer="", confidence=0.3)
    assert not r2.succeeded

    r.steps = [ReasoningStep(1, "think deeply", "conclude X", confidence=0.8)]
    trace = r.format_trace()
    assert "Step 1" in trace and "conclude X" in trace
    return "CoTResult.succeeded + format_trace OK"
chk("CoTResult", t2)

# ── 3. should_use_cot ────────────────────────────────────────────────────────
total += 1
def t3():
    from brain.chain_of_thought import ChainOfThoughtEngine
    assert not ChainOfThoughtEngine.should_use_cot("ok", "status")
    assert not ChainOfThoughtEngine.should_use_cot("ok", "monitor")
    assert ChainOfThoughtEngine.should_use_cot("x", "analysis")
    assert ChainOfThoughtEngine.should_use_cot("x", "code_change")
    long_q = "a" * 110
    assert ChainOfThoughtEngine.should_use_cot(long_q, "chat")
    return "should_use_cot logic OK"
chk("CoT.should_use_cot", t3)

# ── 4. EpisodicMemory: record / recall / context ─────────────────────────────
total += 1
def t4():
    import memory.episodic_memory as em_mod
    orig_path = em_mod.DB_PATH
    em_mod.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
    from memory.episodic_memory import EpisodicMemory
    EpisodicMemory._instance = None
    e = EpisodicMemory.get()

    eid = e.record_episode("ses1", "что такое BTC?", "Bitcoin — это крипта", "trading", importance=0.8)
    assert len(eid) > 5
    e.record_episode("ses1", "покажи баланс", "Баланс: 100 USDT", "trading", importance=0.6)
    e.record_episode("ses2", "напиши код", "def foo(): pass", "code_change", importance=0.7)

    episodes = e.recall("BTC bitcoin", session_id="ses1")
    assert len(episodes) >= 1

    ctx = e.get_session_context("ses1")
    assert "История сессии" in ctx

    # Cross-session: ses2 эпизоды не в ses1
    cross = e.get_cross_session_context("напиши код", current_session_id="ses1")
    # Может быть пустым если score низкий - это ок

    s = e.get_stats()
    assert s["total_episodes"] >= 3
    assert s["unique_sessions"] >= 2

    e.update_outcome(eid, "positive", importance_boost=0.1)

    # Cleanup
    em_mod.DB_PATH = orig_path
    EpisodicMemory._instance = None
    return f"episodes={s['total_episodes']}, sessions={s['unique_sessions']}, recall OK"
chk("EpisodicMemory", t4)

# ── 5. EpisodicMemory: Episode age / decay ──────────────────────────────────
total += 1
def t5():
    from memory.episodic_memory import Episode
    ep = Episode(
        episode_id="test123", session_id="s1",
        query="test", response="resp", intent="chat",
        importance=0.8, created_at=time.time() - 86400 * 5  # 5 дней назад
    )
    assert ep.age_days >= 4.9
    assert ep.decayed_importance < ep.importance  # должно затухнуть
    assert ep.to_summary(100) != ""
    return f"age={ep.age_days:.1f}d, decay={ep.decayed_importance:.3f} < {ep.importance}"
chk("Episode decay", t5)

# ── 6. ToolRegistry: register / find / execute / cache ──────────────────────
total += 1
def t6():
    from core.tool_registry import ToolRegistry, ToolSpec, ToolCategory
    reg = ToolRegistry()

    reg.register(ToolSpec(
        name="test_search",
        description="Search the web for information",
        category=ToolCategory.SEARCH,
        tags=["search", "web", "internet", "найди"],
        capabilities=["search_web"],
        route_patterns=[r"найди|search|поищи"],
        run_fn=lambda q, **kw: f"Results for: {q[:30]}",
        cache_ttl=60,
        priority=8,
    ))

    tool = reg.find_for_task("найди информацию о BTC")
    assert tool is not None and tool.name == "test_search"

    result = reg.execute("test_search", "BTC price")
    assert result.success and "BTC price" in result.output
    assert not result.from_cache

    result2 = reg.execute("test_search", "BTC price")
    assert result2.from_cache

    reg.disable("test_search")
    tool_after = reg.find_for_task("найди информацию")
    assert tool_after is None or tool_after.name != "test_search"

    reg.enable("test_search")
    reg.unregister("test_search")
    assert reg.find_by_name("test_search") is None

    return "register/find/execute/cache/disable/unregister OK"
chk("ToolRegistry", t6)

# ── 7. ToolRegistry: chain execution ────────────────────────────────────────
total += 1
def t7():
    from core.tool_registry import ToolRegistry, ToolSpec, ToolCategory
    reg = ToolRegistry()
    calls = []

    reg.register(ToolSpec(
        name="chain_s1", description="Step 1",
        category=ToolCategory.UTILITY,
        run_fn=lambda q, **kw: (calls.append("s1"), f"s1_out:{q[:20]}")[1],
    ))
    reg.register(ToolSpec(
        name="chain_s2", description="Step 2",
        category=ToolCategory.UTILITY,
        run_fn=lambda q, **kw: (calls.append("s2"), f"s2_out:{q[:30]}")[1],
    ))

    results = reg.execute_chain(["chain_s1", "chain_s2"], "initial", pass_output=True)
    assert len(results) == 2
    assert all(r.success for r in results)
    assert "s1" in calls and "s2" in calls
    assert "s1_out" in results[1].query  # step2 получил вывод step1
    return "chain exec: 2 steps, output passed OK"
chk("ToolRegistry.execute_chain", t7)

# ── 8. ToolRegistry: auto_execute ───────────────────────────────────────────
total += 1
def t8():
    from core.tool_registry import ToolRegistry, ToolSpec, ToolCategory
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="auto_math",
        description="Math calculations",
        category=ToolCategory.MATH,
        tags=["math", "calculate", "вычисли"],
        route_patterns=[r"вычисли|посчитай|calculate"],
        run_fn=lambda q, **kw: "42",
    ))
    result = reg.auto_execute("вычисли 6*7")
    assert result.success and result.output == "42"
    return "auto_execute OK"
chk("ToolRegistry.auto_execute", t8)

# ── 9. TaskQueue: enqueue / status / cancel / scheduled ─────────────────────
total += 1
def t9():
    import core.task_queue as tq_mod
    orig = tq_mod.DB_PATH
    tq_mod.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
    from core.task_queue import TaskQueue, TaskStatus
    TaskQueue._instance = None
    tq = TaskQueue.get()

    tid = tq.enqueue("search", "найди BTC новости", priority=7, session_id="test_ses")
    assert len(tid) > 5

    status = tq.get_status(tid)
    assert status is not None
    assert status["status"] in ("pending", "scheduled")
    assert status["tool_name"] == "search"

    ok = tq.cancel(tid)
    assert ok
    status2 = tq.get_status(tid)
    assert status2["status"] == "cancelled"

    # Отложенная задача
    future = time.time() + 3600
    tid2 = tq.enqueue("math", "посчитай 2+2", scheduled_at=future)
    status3 = tq.get_status(tid2)
    assert status3["status"] == "scheduled"

    tasks = tq.list_tasks(session_id="test_ses")
    assert len(tasks) >= 1

    s = tq.get_stats()
    assert s["enqueued"] >= 2

    tq_mod.DB_PATH = orig
    TaskQueue._instance = None
    return f"enqueue/cancel/scheduled/list OK, stats={s}"
chk("TaskQueue", t9)

# ── 10. TaskQueue: worker execution ─────────────────────────────────────────
total += 1
def t10():
    import core.task_queue as tq_mod
    orig = tq_mod.DB_PATH
    tq_mod.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
    from core.task_queue import TaskQueue, TaskStatus
    from core.tool_registry import ToolRegistry, ToolSpec, ToolCategory
    TaskQueue._instance = None

    # Создать registry с тестовым инструментом
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="fast_tool",
        description="Fast test tool",
        category=ToolCategory.UTILITY,
        run_fn=lambda q, **kw: f"done:{q[:20]}",
    ))

    tq = TaskQueue.get()
    tq.set_tool_registry(reg)
    tq.start()

    results = []
    def on_done(task_id, result, error):
        results.append((task_id, result, error))

    tid = tq.enqueue("fast_tool", "test query", on_complete=on_done)

    # Ждём выполнения (макс 5 сек)
    result = tq.wait_for(tid, timeout_sec=5)
    assert result is not None, "Task did not complete in time"
    assert "done:" in result

    tq.stop()
    tq_mod.DB_PATH = orig
    TaskQueue._instance = None
    return f"worker executed task, result={result!r}"
chk("TaskQueue worker", t10)

# ── 11. ToolRegistry: get_report ────────────────────────────────────────────
total += 1
def t11():
    from core.tool_registry import ToolRegistry, ToolSpec, ToolCategory
    reg = ToolRegistry()
    reg.register(ToolSpec(name="rep_t", description="Report test", category=ToolCategory.UTILITY,
                          run_fn=lambda q, **kw: "ok"))
    reg.execute("rep_t", "test")
    report = reg.get_report()
    assert "Tool Registry" in report
    assert "rep_t" in report
    return "get_report OK"
chk("ToolRegistry.get_report", t11)

# ── 12. EpisodicMemory: consolidation ───────────────────────────────────────
total += 1
def t12():
    import memory.episodic_memory as em_mod
    orig_path = em_mod.DB_PATH
    em_mod.DB_PATH = Path(tempfile.mktemp(suffix=".db"))
    from memory.episodic_memory import EpisodicMemory
    EpisodicMemory._instance = None
    e = EpisodicMemory.get()

    # Записать несколько эпизодов
    for i in range(5):
        e.record_episode(f"ses_con", f"вопрос {i}", f"ответ {i}", "chat", importance=0.6)

    # Принудительная консолидация
    mem = e.consolidate_session("ses_con", force=True)
    # С 5 эпизодами (< CONSOLIDATE_AFTER=50) только force=True сработает
    assert mem is not None
    assert mem.episode_count >= 5

    # Получить consolidated
    summary = e.get_consolidated("ses_con")
    assert summary is not None and len(summary) > 0

    em_mod.DB_PATH = orig_path
    EpisodicMemory._instance = None
    return f"consolidation OK, {mem.episode_count} episodes summarized"
chk("EpisodicMemory.consolidate", t12)

print(f"\n{'='*50}")
print(f"RESULT: {passed}/{total} PASSED")
if passed == total:
    print("ALL TESTS PASSED!")
else:
    print(f"{total - passed} FAILED")
sys.exit(0 if passed == total else 1)
