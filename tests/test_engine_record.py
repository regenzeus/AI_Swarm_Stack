"""The record and exams (GEN-31, docs/AI-STACK.md §11): a toy run exports one zip a person can follow without the app,
with its chain from item to decisions and the files it made; a toy exam set runs through its template and scores, with
the case it got wrong named."""
import asyncio
import json
import os
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from engine import artifacts as AR
from engine import graph as G
from engine import record as RC
from engine import runner as R

ROOT = Path(__file__).resolve().parents[1]
PACK = {"name": "toy", "dir": str(ROOT / "tests/fixtures/packs/toy")}
RUN = """template: toy/record
nodes:
  item: {block: start, title: A ticket arrives, kind: item}
  build: {block: command, title: Build the fix, kind: toy.reproduce}
  ok: {block: gate, title: Approve the fix, role: owner}
  done: {block: end, title: Delivered, kind: done}
edges:
  - [item, build]
  - [build, ok]
  - [ok, done]
"""


def acts(tmp, decider=None):
    @activity.defn(name="load_graph")
    async def load_graph(ref: dict) -> G.Graph:
        if ref.get("template"):
            return G.canonical((Path(PACK["dir"]) / "templates" / f"{ref['template'].split('/')[1]}.yaml").read_text())
        return G.load(RUN)

    @activity.defn(name="step")
    async def step(inp: R.StepInput) -> dict:
        if inp.node.block == "branch":
            return {"ref": "artifact:route", "pass": True, "branch": (decider or (lambda t: "bug"))(inp.ref["case"]["ticket"])}
        return {"ref": f"artifact:{inp.node.id}", "pass": True}

    @activity.defn(name="command")
    def command(d: dict) -> dict:
        f = tmp / "fix.zip"
        f.write_bytes(b"PK\x05\x06" + b"\0" * 18)
        return {"pass": True, "ref": "job:wsl/abc", "artifacts": [AR.put(f, task=d["task"], step=d["node"], run=d["run"], commit="c0ffee")["id"]]}

    @activity.defn(name="decision")
    async def decision(d: dict) -> dict:
        return {"queued": True, "people": ["owner"]}

    @activity.defn(name="finish")
    async def finish(d: dict) -> dict:
        return {}
    return [load_graph, step, command, decision, finish]


async def workers(e, a):
    pool = ThreadPoolExecutor(4)
    return [Worker(e.client, task_queue=q, workflows=[R.GraphRun, R.NodeRun] if q == R.QUEUE else [], activities=a, activity_executor=pool)
            for q in (R.QUEUE, R.STEP_QUEUE, "place-wsl")]


def test_a_toy_run_exports_one_bundle_with_its_chain_from_item_to_decisions_and_the_files_it_made(tmp_path, monkeypatch):
    monkeypatch.setenv("AISTACK_ARTIFACTS", str(tmp_path / "artifacts"))

    async def go():
        async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
            ws = await workers(e, acts(tmp_path))
            async with ws[0], ws[1], ws[2]:
                h = await e.client.start_workflow(R.GraphRun.run, R.RunInput(task="test/T-9", ref={"kind": "template"}), id="toy/record:T-9", task_queue=R.QUEUE)
                for _ in range(100):
                    if ((await h.query(R.GraphRun.state))["nodes"].get("ok") or {}).get("status") == "waiting":
                        break
                    await asyncio.sleep(0.1)
                await h.signal(R.GraphRun.decide, args=["ok", "yes", "owner"])
                await h.result()
                return await RC.export(e.client, "toy/record:T-9", tmp_path / "out/record.zip")
    out = asyncio.run(go())
    z = zipfile.ZipFile(out)
    run = json.loads(z.read("run.json"))
    assert run["task"] == "test/T-9" and run["status"] == "completed" and [n["id"] for n in run["nodes"]] == ["item", "build", "ok", "done"]
    assert run["nodes"][2]["answer"]["who"] == "owner" and run["nodes"][1]["answer"]["artifacts"][0].startswith("artifact:")
    page = z.read("index.html").decode()
    assert "Item <b>test/T-9</b>" in page and "decided by owner" in page and "Build the fix" in page and page.index("Build the fix") < page.index("Approve the fix")
    sha = run["nodes"][1]["answer"]["artifacts"][0].removeprefix("artifact:")
    assert f"artifacts/{sha}" in z.namelist() and AR.records(sha)[0]["commit"] == "c0ffee"
    assert json.loads(z.read("history.json"))["events"][0]["eventType"] in ("EVENT_TYPE_WORKFLOW_EXECUTION_STARTED", "WorkflowExecutionStarted")


def test_a_toy_exam_set_runs_through_its_template_and_scores_naming_the_case_it_got_wrong(tmp_path):
    def run_exam(decider):
        async def go():
            async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
                ws = await workers(e, acts(tmp_path, decider))
                async with ws[0], ws[1], ws[2]:
                    async def start(template, item, case):
                        return await e.client.start_workflow(R.GraphRun.run, R.RunInput(task=item, ref={"kind": "template", "template": template, "case": case}),
                                                             id=item, task_queue=R.QUEUE)
                    return await RC.exam(e.client, PACK, "bugs", start)
        return asyncio.run(go())
    good = run_exam(lambda t: "bug" if any(w in t for w in ("stops", "fails")) else "question")
    assert good["score"] == 1.0 and good["right"] == 3 and good["template"] == "toy/triage"
    naive = run_exam(lambda t: "bug")
    assert naive["right"] == 2 and [c["case"]["ticket"] for c in naive["cases"] if not c["right"]] == ["How do I export only one folder?"]
