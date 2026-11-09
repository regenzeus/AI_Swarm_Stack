"""What the app shows of the engine (GEN-34, docs/AI-STACK-PLAN.md §10, M2): the projector's picture of a real run,
with every block's status and timing and the graph's edges; the app's state and its stream carrying it; the Engine
screen and its canvas being part of the app; the demo templates in their canonical form."""
import asyncio
import os
import re
from pathlib import Path

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from engine import graph as G
from engine import projector as P
from engine import runner as R

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "images/mission-control/web/static"
TICKET = ROOT / "config/templates/demo/ticket.yaml"


@activity.defn(name="load_graph")
async def load_graph(ref: dict) -> G.Graph:
    return G.canonical(Path(ref["path"]).read_text())


@activity.defn(name="step")
async def step(inp: R.StepInput) -> dict:
    return {"ref": f"artifact:{inp.node.id}", "pass": True, "items": ["a", "b"] if inp.node.id == "spec" else []}


@activity.defn(name="decision")
async def decision(d: dict) -> dict:
    return {}


@activity.defn(name="remind")
async def remind(d: dict) -> dict:
    return {}


@activity.defn(name="finish")
async def finish(d: dict) -> dict:
    return {}


def test_the_projector_shows_a_running_run_with_its_blocks_edges_status_and_timing():
    async def go():
        async with await WorkflowEnvironment.start_local(namespace="default", download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
            acts = [load_graph, step, decision, remind, finish]
            async with Worker(e.client, task_queue=R.QUEUE, workflows=[R.GraphRun, R.NodeRun], activities=acts), \
                    Worker(e.client, task_queue=R.STEP_QUEUE, activities=acts):
                h = await e.client.start_workflow(R.GraphRun.run, R.RunInput(task="T-1", ref={"kind": "template", "path": str(TICKET)}),
                                                  id="demo/ticket:T-1", task_queue=R.QUEUE)
                for _ in range(100):                                                   # until the run waits for its reporter
                    st = await h.query(R.GraphRun.state)
                    if (st["nodes"].get("reply") or {}).get("status") == "waiting":
                        break
                    await asyncio.sleep(0.2)
                for _ in range(50):                                                    # visibility catches up
                    snap = await P.snapshot(e.client)
                    if snap["runs"]:
                        break
                    await asyncio.sleep(0.2)
                return snap
    snap = asyncio.run(go())
    assert snap["engine"]["up"] and snap["engine"]["namespace"] == "default" and snap["engine"]["running"] == 1
    [run] = snap["runs"]
    assert run["id"] == "demo/ticket:T-1" and run["status"] == "running" and run["graph"] == "demo/ticket"
    by = {n["id"]: n for n in run["nodes"]}
    assert [n["id"] for n in run["nodes"]][:3] == ["report", "intake", "reply"]
    assert by["intake"]["status"] == "done" and by["intake"]["started"] and by["intake"]["ended"]
    assert by["reply"]["status"] == "waiting" and "reporter" in by["reply"]["waiting_for"] and by["reply"]["block"] == "wait"
    assert by["reproduce"]["after"] == ["reply"] and by["approve"]["role"] == "spec-approver"
    assert by["classify"]["loop_to"] == "implement"


def test_the_apps_state_and_its_stream_carry_the_engine():
    srv = (ROOT / "images/mission-control/server.py").read_text()
    assert 's["engine"] = engine_view()' in srv and "'engine': eng" in srv
    assert 'M / "public/engine.json"' in srv and '"engine_decide"' in srv
    bridge = (ROOT / "ops/engine/bridge.py").read_text()
    assert 'M.PUBLIC / "engine.json"' in bridge and "snap = eng.call(P.snapshot)" in bridge and "P.write(shown, snap)" in bridge
    assert 'snap["templates"], snap["agents"] = T.listing(packs=loaded["packs"]), T.agents(loaded["packs"])' in bridge and 'snap["packs"] = loaded' in bridge and "P.down(shown" in bridge


def test_the_engine_screen_and_its_canvas_are_part_of_the_app_and_redraw_live():
    index = (ROOT / "images/mission-control/web/index.html").read_text()
    assert '<script src="/static/app-engine.js"></script>' in index
    js = (STATIC / "app-engine.js").read_text()
    for fn in ("function vEngine(", "function engCanvas(", "function engTimeline(", "function engWires(", "function engineBanner("):
        assert fn in js, fn
    base = (STATIC / "app-base.js").read_text()
    assert 'const LIVE = new Set(["home", "decide", "engine"]);' in base and "engine: vEngine" in base
    assert "${engineBanner()}" in (STATIC / "app.js").read_text()
    assert not re.search(r"text-overflow:\s*ellipsis", (STATIC / "app.css").read_text().split("GEN-34: the engine")[1])   # labels wrap


def test_the_demo_templates_are_in_their_canonical_form():
    for p in sorted((ROOT / "config/templates/demo").glob("*.yaml")):
        assert G.dump(G.canonical(p.read_text())) == p.read_text(), p.name


def test_the_runs_screen_shows_temporals_ui_behind_the_apps_gate_and_its_codec_decrypts_what_the_engine_encrypted(monkeypatch):
    import base64
    import json as J
    import httpx
    from temporalio.api.common.v1 import Payload
    from engine import converter as CV
    key = CV.new_key()
    monkeypatch.setenv("TEMPORAL_CODEC_KEY", key)
    sent = asyncio.run(CV.Encrypting(CV.key_from_env({CV.KEY_ENV: key})).encode([Payload(metadata={"encoding": b"json/plain"}, data=b'{"ref": "step:7"}')]))[0]

    class Resp:
        def __init__(self, body, status_code=200):
            self.body, self.status_code = body, status_code
    ns = {"os": os, "httpx": httpx, "JSONResponse": lambda body, status_code=200: Resp(body, status_code), "Response": Resp}
    src = (ROOT / "images/mission-control/server.engine.py").read_text()
    exec(compile(src, "server.engine.py", "exec"), ns)

    class Req:
        async def json(self):
            return {"payloads": [{"metadata": {k: base64.b64encode(v).decode() for k, v in sent.metadata.items()}, "data": base64.b64encode(sent.data).decode()}]}
    out = asyncio.run(ns["api_codec_decode"](Req())).body["payloads"][0]
    assert base64.b64decode(out["data"]) == b'{"ref": "step:7"}' and base64.b64decode(out["metadata"]["encoding"]) == b"json/plain"
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert 'Route("/api/codec/decode", api_codec_decode, methods=["POST"])' in server and '"/runs")) and not request.headers.get("tailscale-user-login")' in server
    core = (ROOT / "compose/core.yaml").read_text()
    assert "TEMPORAL_UI_PUBLIC_PATH: /runs" in core and "TEMPORAL_CODEC_ENDPOINT: /api/codec" in core
    js = (ROOT / "images/mission-control/web/static/app-engine.js").read_text()
    assert "function vRuns(" in js and 'href="#/runs"' in js and "127.0.0.1:8233" not in js
    assert J.loads(J.dumps({"ok": True}))
