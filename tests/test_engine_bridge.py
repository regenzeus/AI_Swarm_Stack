"""The bridge (GEN-35, docs/AI-STACK-PLAN.md WP6): with ENGINE=temporal the app's plan tasks run on the engine. Runs
start as before (CD.start, a queued event, a schedule); the bridge starts each running occurrence's workflow once;
a cancel stops it; a step waiting for work elsewhere holds no slot and finishes when its work is done; and the
Orchestrator's look between waves adds a step that the run then follows. The Conductor's own fixture and plan."""
import asyncio
import concurrent.futures
import os
from datetime import timedelta

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import conductor as CD
import tasks as TK
from engine import activities as A
from engine import bridge as EB
from engine import runner as R


async def serve(body):
    async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
        pool = concurrent.futures.ThreadPoolExecutor(4)
        async with Worker(e.client, task_queue=R.QUEUE, workflows=[R.GraphRun, R.NodeRun], activities=A.ALL, activity_executor=pool), \
                Worker(e.client, task_queue=R.STEP_QUEUE, activities=A.ALL, activity_executor=pool, max_concurrent_activities=CD.SLOTS):
            loop = asyncio.get_running_loop()

            def call(fn):
                return asyncio.run_coroutine_threadsafe(fn(e.client), loop).result(60)
            return await body(e, call)


def sync(K, call):
    return asyncio.to_thread(lambda: EB.sync(K.conn(), call))


async def until(cond, limit=150):
    for _ in range(limit):
        if cond():
            return True
        await asyncio.sleep(0.2)
    return False


def test_the_deployment_chooses_the_engine_and_the_conductor_stays_the_default():
    assert EB.on({"ENGINE": "temporal"}) is True and EB.on({"ENGINE": "conductor"}) is False
    assert EB.on({"AISTACK_DEPLOYMENT": "home"}) is False                     # home's file says conductor until the cutover


def test_a_started_plan_runs_on_the_engine_once_and_ends_as_the_conductor_ends_it(K):
    async def body(e, call):
        assert await sync(K, call) == [f"task:{K.tid}:1"]
        assert await sync(K, call) == []                                         # once: the bridge remembers it
        out = await e.client.get_workflow_handle(f"task:{K.tid}:1").result()
        assert out["status"] == "done", out
    asyncio.run(serve(body))
    assert sorted(K.ran) == [1, 2, 3, 4] and TK.row(K.c, K.tid)["status"] == "done"
    assert list((K.tmp / "tasks").glob(f"{K.tid}-*.md"))


def test_a_queued_event_starts_the_next_run_on_the_engine(K):
    async def body(e, call):
        await sync(K, call)
        await e.client.get_workflow_handle(f"task:{K.tid}:1").result()
        CD.fire(K.c, K.tid, {"trigger": "a price fell", "summary": "below the target"})
        CD.tick_starts(K.c)                                                     # as the bridge's pass does
        assert await sync(K, call) == [f"task:{K.tid}:2"]
        return await e.client.get_workflow_handle(f"task:{K.tid}:2").result()
    out = asyncio.run(serve(body))
    assert out["status"] == "done" and K.ran.count(1) == 2


def test_a_cancel_stops_the_engines_run(K, monkeypatch):
    def waits(c, t, s, prompt, card):
        if s["idx"] == 2:
            raise CD.Waiting("its Claude task")
        return "fine"
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": waits, "python": waits, "claude-code": waits})
    monkeypatch.setattr(CD, "ON_CANCEL", [])

    async def body(e, call):
        CD.ON_CANCEL.append(EB.cancel_hook(call))
        await sync(K, call)
        assert await until(lambda: CD.steps(K.conn(), K.tid)[1]["status"] == "waiting")
        await asyncio.to_thread(lambda: CD.cancel(K.conn(), TK.row(K.conn(), K.tid)))
        return await e.client.get_workflow_handle(f"task:{K.tid}:1").result()
    out = asyncio.run(serve(body))
    assert out["status"] == "cancelled" and TK.row(K.c, K.tid)["status"] == "cancelled"


def test_a_step_waiting_for_its_work_elsewhere_holds_no_slot_and_finishes_when_the_work_is_done(K, monkeypatch):
    looks = []

    def later(c, t, s, prompt, card):
        if s["idx"] == 2 and len(looks) < 2:
            looks.append(s["status"])
            raise CD.Waiting("its Claude task")
        return f"result of step {s['idx']}"
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": later, "python": later, "claude-code": later})
    monkeypatch.setattr(CD, "WAITS", (*CD.WAITS, "hermes"))                   # this harness's work runs elsewhere here

    async def body(e, call):
        await sync(K, call)
        h = e.client.get_workflow_handle(f"task:{K.tid}:1")
        assert await until(lambda: CD.steps(K.conn(), K.tid)[2]["status"] == "done")   # step 3 ran while 2 waited
        await e.sleep(timedelta(minutes=10))                                          # the run looks again on its timer
        return await h.result()
    out = asyncio.run(serve(body))
    assert out["status"] == "done" and len(looks) == 2 and CD.steps(K.c, K.tid)[1]["output"] == "result of step 2"


def test_the_orchestrator_looks_again_between_waves_and_the_run_follows_its_added_step(K, monkeypatch):
    asked = []

    def orchestrator(prompt):
        asked.append(prompt)
        if len(asked) == 1:
            return {"keep": False, "add": [{"step": "Check the summary", "agent": "desk", "after": [4]}], "why": "one more look"}
        return {"keep": True, "why": "fine"}
    monkeypatch.setattr(CD, "checkpoint_ask", orchestrator)

    async def body(e, call):
        await sync(K, call)
        return await e.client.get_workflow_handle(f"task:{K.tid}:1").result()
    out = asyncio.run(serve(body))
    assert out["status"] == "done" and asked, out
    assert out["nodes"]["r5"]["status"] == "done" and 5 in K.ran                  # the added step ran, after step 4
    assert CD.steps(K.c, K.tid)[4]["title"] == "Check the summary"
