"""The activities (GEN-22, docs/AI-STACK-PLAN.md WP5): a home plan runs on Temporal through the Conductor's own step
runner and adapters, on the Conductor's own rows, and ends through its own finish: the same answers, the same result
file and message, the same failure with its reason. The Conductor's fixture K (tests/conftest.py) is reused, so what is
proven is the same."""
import asyncio
import os

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import conductor as CD
import tasks as TK
from engine import activities as A
from engine import runner as R


def run_plan(K, tid, occ=1):
    async def go():
        async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
            pool = __import__("concurrent.futures").futures.ThreadPoolExecutor(4)
            async with Worker(e.client, task_queue=R.QUEUE, workflows=[R.GraphRun, R.NodeRun], activities=A.ALL, activity_executor=pool), \
                    Worker(e.client, task_queue=R.STEP_QUEUE, activities=A.ALL, activity_executor=pool):
                h = await e.client.start_workflow(R.GraphRun.run, R.RunInput(task=str(tid), ref={"kind": "plan", "task": tid, "occ": occ}),
                                                  id=f"task:{tid}:{occ}", task_queue=R.QUEUE)
                return await h.result()
    return asyncio.run(go())


def test_a_home_plan_runs_on_the_engine_through_the_conductors_own_steps_and_finish(K):
    out = run_plan(K, K.tid)
    assert out["status"] == "done", out
    assert sorted(K.ran) == [1, 2, 3, 4] and K.ran[0] == 1 and K.ran[-1] == 4               # the join after both branches
    rows = CD.steps(K.c, K.tid)
    assert [r["status"] for r in rows] == ["done"] * 4 and rows[3]["output"] == "result of step 4"
    assert out["nodes"]["r4"]["answer"] == {"ref": f"step:{rows[3]['id']}", "pass": True}   # a reference, not the output
    assert TK.row(K.c, K.tid)["status"] == "done" and list((K.tmp / "tasks").glob(f"{K.tid}-*.md"))
    assert any("is done" in m for m in K.sent)                                               # the Conductor's own message


def test_a_step_that_fails_twice_fails_the_run_and_the_task_with_its_reason(K, monkeypatch):
    def broken(c, t, s, prompt, card):
        if s["idx"] == 2:
            raise RuntimeError("the scout's page did not load")
        return "fine"
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": broken, "python": broken, "claude-code": broken})
    out = run_plan(K, K.tid)
    assert out["status"] == "failed" and "the scout's page did not load" in out["why"]
    row = CD.steps(K.c, K.tid)[1]
    assert row["status"] == "failed" and row["attempts"] == CD.ATTEMPTS                       # two attempts, as before
    assert TK.row(K.c, K.tid)["status"] == "failed" and "failed" in TK.row(K.c, K.tid)["error"]


def test_a_gate_is_asked_once_per_run_and_node_even_when_asked_again(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "GATES", tmp_path / "gates.json")
    d = {"task": "T-1", "run": "toy/bug:T-1", "node": "approve", "role": "spec-approver", "title": "Approve the spec"}
    assert A.decision(d)["key"] == "toy/bug:T-1/approve"
    A.decision(d)                                                                             # a continued run asks again
    import json
    assert len(json.loads((tmp_path / "gates.json").read_text())) == 1


LIVE = """template: home/triage
nodes:
  item: {block: start, title: A request arrives, kind: item}
  read: {block: agent, title: Read the request, agent: scout, brief: Say what it asks for}
  route: {block: branch, title: Bug or question, agent: planner}
  answer: {block: agent, title: Answer it, agent: desk}
  fixed: {block: end, title: Fixed, kind: done}
  answered: {block: end, title: Answered, kind: done}
edges:
  - [item, read]
  - [read, route]
  - [route, answer, question]
  - [route, fixed, bug]
  - [answer, answered]
"""


def test_a_templates_agent_and_decision_blocks_run_through_the_conductors_steps_and_its_task_finishes(K, monkeypatch, tmp_path):
    from engine import graph as G
    path = tmp_path / "triage.yaml"
    path.write_text(LIVE)
    G.canonical(LIVE)
    told = []

    def adapter(c, t, s, prompt, card):
        told.append((s["idx"], s["title"]))
        return "question\nIt asks how to export one folder." if "Answer with exactly one of" in s["title"] else f"result of {s['title']}"
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": adapter, "python": adapter, "claude-code": adapter})

    async def go():
        async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
            pool = __import__("concurrent.futures").futures.ThreadPoolExecutor(4)
            async with Worker(e.client, task_queue=R.QUEUE, workflows=[R.GraphRun, R.NodeRun], activities=A.ALL, activity_executor=pool), \
                    Worker(e.client, task_queue=R.STEP_QUEUE, activities=A.ALL, activity_executor=pool):
                h = await e.client.start_workflow(R.GraphRun.run, R.RunInput(task="R-1", ref={"kind": "template", "path": str(path)}),
                                                  id="home/triage:R-1", task_queue=R.QUEUE)
                return await h.result()
    out = asyncio.run(go())
    assert out["status"] == "done" and out["why"] == "ended at Answered", out
    assert out["nodes"]["route"]["answer"]["branch"] == "question" and out["nodes"]["fixed"]["status"] == "skipped"
    assert [i for i, _ in told] == [1, 2, 3] and told[0][1] == "Read the request: Say what it asks for"
    assert "Answer with exactly one of: question, bug." in told[1][1]
    tid = K.c.execute("select task from engine_template_runs where workflow='home/triage:R-1'").fetchone()[0]
    t = TK.row(K.c, tid)
    assert t["kind"] == "template" and t["door"] == "template" and t["status"] == "done"
    assert [r["status"] for r in CD.steps(K.c, tid)] == ["done", "done", "done"]


def test_a_deciders_answer_is_read_for_one_of_its_branches():
    assert A.branch_of("Bug.\nThe export stops.", ["bug", "question"]) == "bug"
    assert A.branch_of("I think this is a question about exporting, not a bug.", ["bug", "question"]) == "question"
    assert A.branch_of("**Feature**", ["bug", "feature"]) == "feature"


def test_each_item_of_a_template_blocks_fan_out_gets_a_row_of_its_own(K):
    from engine import graph as G
    g = G.load(LIVE)
    tid, mp = A.template_rows(K.c, "home/triage:R-2", g, "R-2")
    assert mp == {"read": 1, "route": 2, "answer": 3}
    a, b = A.item_row(K.c, tid, 1, "a.txt"), A.item_row(K.c, tid, 1, "b.txt")
    assert (a, b) == (1001, 1002) and A.item_row(K.c, tid, 1, "a.txt") == 1001
    rows = {r["idx"]: r for r in CD.steps(K.c, tid)}
    assert rows[1001]["item"] == "a.txt" and rows[1001]["title"] == rows[1]["title"] and rows[1002]["status"] == "pending"
    assert A.template_rows(K.c, "home/triage:R-2", g, "R-2") == (tid, mp)                  # made once per run
