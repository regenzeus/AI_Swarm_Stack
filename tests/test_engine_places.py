"""Places, pools and artifacts (GEN-22, GEN-28, GEN-29, docs/AI-STACK.md §7 and §10): a toy job kind runs at the
wsl-host place by the worker protocol once approved there by its hash, a value outside its type is refused; a 10-item
fan-out on a pool of 2 never runs 3 at once, two runs share the pool and a failed attempt is tried again; a step's file
is kept by its hash with the run and commit that made it, attached to a stand-in item, and removed past its retention."""
import asyncio
import datetime as dt
import json
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import fakeworker as FK
from engine import artifacts as AR
from engine import graph as G
from engine import places as PL
from engine import runner as R
from engine import trackers as TR

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "tests/fixtures/packs/toy/jobs/reproduce.json"
SPEC = json.loads(JOB.read_text())


@pytest.fixture
def host(tmp_path, monkeypatch):
    """The wsl-host place: a worker of the protocol over its own root, running in a thread as the test's user."""
    root = tmp_path / "wslhost"
    for d in ("inbox", "outbox", "jobs.d", "repos", "scratch"):
        (root / d).mkdir(parents=True)
    (tmp_path / "places.yaml").write_text(f"places:\n  wsl-host: {{root: {root}, user: aiworker}}\n")
    monkeypatch.setenv("AISTACK_PLACES", str(tmp_path / "places.yaml"))
    monkeypatch.setenv("AISTACK_PLACE_ROOT", str(tmp_path / "places"))
    monkeypatch.setenv("AISTACK_ARTIFACTS", str(tmp_path / "artifacts"))
    stop = threading.Event()
    w = FK.Worker(root, beat_s=1)

    def loop():
        while not stop.is_set():
            if not w.once():
                stop.wait(0.2)
    threading.Thread(target=loop, daemon=True).start()
    yield root
    stop.set()


def pack(job=JOB):
    return [{"name": "toy", "jobs": [{"kind": SPEC["kind"], "file": str(job), "sha256": __import__("winjobs").digest(job), "spec": SPEC}]}]


def test_a_command_runs_at_the_wsl_host_place_only_once_approved_there_by_its_hash_and_a_value_outside_its_type_is_refused(host):
    PL.sync_jobs(pack())
    assert (host / "jobs.d/toy.reproduce.json").read_text() == JOB.read_text()           # copied, not approved
    import time
    for _ in range(50):                                                                   # the worker's status names the kind
        if "toy.reproduce" in ((PL.place("wsl-host").status() or {}).get("kinds") or {}):
            break
        time.sleep(0.1)
    with pytest.raises(PL.Refused, match="not approved at wsl-host: the owner approves it in Needs you"):
        PL.run_job("wsl-host", "toy.reproduce", {"input": "small"}, spec=SPEC, sleep=lambda s: None)
    ds = list(PL.decisions(lambda *a, **k: {"id": a[0], "cls": a[1], "what": a[2], **k}))
    assert sorted(d["what"] for d in ds) == ["Approve the command toy.reproduce at wsl-host?", "Approve the command toy.reproduce at wsl?"]
    assert {d["cls"] for d in ds} == {"command"}                                           # one approval per place, each the owner's
    act = next(d for d in ds if d["what"].endswith("at wsl-host?"))["answers"][0]["act"]
    assert PL.handle({**act, "sha": "0" * 64})["ok"] is False                             # not the one the owner saw
    assert PL.handle(act)["ok"] and [d[2] for d in PL.decisions(lambda *a, **k: a)] == ["Approve the command toy.reproduce at wsl?"]
    for _ in range(50):                                                                   # the worker's status says approved
        if ((PL.place("wsl-host").status() or {}).get("kinds") or {}).get("toy.reproduce", {}).get("approved"):
            break
        time.sleep(0.1)
    with pytest.raises(PL.Refused, match="input"):
        PL.run_job("wsl-host", "toy.reproduce", {"input": "huge"}, spec=SPEC)              # outside its enum: refused here
    r = PL.run_job("wsl-host", "toy.reproduce", {"input": "small"}, spec=SPEC, poll=0.2)
    assert r["status"] == "done", r
    assert any(p.name == "log.txt" and "reproduced on small" in p.read_text() for p in r["artifacts"])


def test_the_engine_queues_are_its_own_the_pools_at_their_size_and_each_place(tmp_path, monkeypatch):
    (tmp_path / "pools.yaml").write_text("pools: {tool: 2, claude: 4}\n")
    (tmp_path / "places.yaml").write_text(f"places:\n  wsl-host: {{root: {tmp_path / 'h'}, user: aiworker}}\n")
    monkeypatch.setenv("AISTACK_POOLS", str(tmp_path / "pools.yaml"))
    monkeypatch.setenv("AISTACK_PLACES", str(tmp_path / "places.yaml"))
    assert PL.queues({"aistack": 4, "steps": 6}) == {"aistack": 4, "steps": 6, "tool": 2, "claude": 4, "place-wsl": 2, "place-wsl-host": 2}
    with pytest.raises(ValueError, match="a command runs at wsl, wsl-host or windows"):
        G.load("""template: t/x
nodes:
  go: {block: start, title: Go, kind: hand}
  run: {block: command, title: Run, kind: toy.reproduce, place: mars}
  end: {block: end, title: End, kind: done}
edges:
  - [go, run]
  - [run, end]
""")


FAN = """template: toy/fan
nodes:
  go: {block: start, title: By hand, kind: hand}
  each: {block: agent, title: One item, agent: 'toy:a', items: [a, b, c, d, e, f, g, h, i, j], pool: tool}
  end: {block: end, title: Done, kind: done}
edges:
  - [go, each]
  - [each, end]
"""


def test_a_ten_item_fan_out_on_a_pool_of_two_never_runs_three_at_once_two_runs_share_it_and_a_failed_attempt_is_retried():
    now, peak, tries = [0], [0], {}
    lock = threading.Lock()

    @activity.defn(name="load_graph")
    async def load_graph(ref: dict) -> G.Graph:
        return G.load(FAN)

    @activity.defn(name="step")
    def step(inp: R.StepInput) -> dict:
        key = f"{inp.run}/{inp.item}"
        with lock:
            tries[key] = tries.get(key, 0) + 1
            now[0] += 1
            peak[0] = max(peak[0], now[0])
        import time
        time.sleep(0.15)
        with lock:
            now[0] -= 1
        if inp.item == "c" and tries[key] == 1:
            raise RuntimeError("lost on its first try")
        return {"ref": f"artifact:{inp.item}", "pass": True}

    @activity.defn(name="finish")
    async def finish(d: dict) -> dict:
        return {}

    async def go():
        async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=os.environ.get("TEMPORAL_DOWNLOAD_DIR")) as e:
            pool = ThreadPoolExecutor(8)
            async with Worker(e.client, task_queue=R.QUEUE, workflows=[R.GraphRun, R.NodeRun], activities=[load_graph, finish], activity_executor=pool), \
                    Worker(e.client, task_queue="tool", activities=[step], activity_executor=pool, max_concurrent_activities=2):
                hs = [await e.client.start_workflow(R.GraphRun.run, R.RunInput(task=f"T-{i}", ref={"kind": "template"}), id=f"toy/fan:T-{i}", task_queue=R.QUEUE)
                      for i in (1, 2)]
                outs = [await h.result() for h in hs]
                assert all(o["status"] == "done" for o in outs), outs
                assert peak[0] == 2                                                        # two at once, never three, across both runs
                assert all(tries[f"toy/fan:T-{i}/c"] == 2 for i in (1, 2)) and len(outs[0]["nodes"]["each"]["items"]) == 10
    asyncio.run(go())


def test_a_steps_file_is_kept_by_its_hash_with_its_maker_attached_to_a_stand_in_item_and_removed_past_its_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("AISTACK_ARTIFACTS", str(tmp_path / "artifacts"))
    zip_ = tmp_path / "result.zip"
    shutil.make_archive(str(tmp_path / "result"), "zip", str(ROOT / "tests/fixtures/packs/toy"))
    t0 = dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc)
    rec = AR.put(zip_, task="test/T-7", step="reproduce", run="toy/bug:test/T-7", commit="abc123", data_class="private", now=t0)
    assert rec["id"] == f"artifact:{rec['sha256']}" and AR.path_of(rec["id"]).read_bytes() == zip_.read_bytes()
    assert AR.records(rec["id"])[0] | {"run": "toy/bug:test/T-7", "commit": "abc123", "step": "reproduce"} == AR.records(rec["id"])[0]
    store = tmp_path / "standin.json"
    store.write_text(json.dumps({"items": {"T-7": {"updated": "2026-11-09T10:00:00", "comments": []}}}))
    (tmp_path / "trackers.yaml").write_text(f"trackers:\n  - {{name: test, kind: standin, path: {store}, template: toy/bug}}\n")
    monkeypatch.setenv("AISTACK_TRACKERS", str(tmp_path / "trackers.yaml"))
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    TR.handle({"action": "tracker_live", "kind": "attach", "live": True})
    TR.write({"tracker": "test", "kind": "attach", "key": "T-7", "body": f"{rec['id']} result.zip", "write_id": "w1"})
    log = json.loads(store.read_text())["items"]["T-7"]["log"]
    assert log[0]["kind"] == "attach" and log[0]["value"].startswith(rec["id"])
    assert AR.prune(t0 + dt.timedelta(days=30)) == [] and AR.path_of(rec["id"])
    assert AR.prune(t0 + dt.timedelta(days=AR.RETAIN_DAYS + 1)) == [rec["sha256"]] and AR.path_of(rec["id"]) is None and AR.records(rec["id"]) == []


def test_commands_are_the_queues_and_the_engines():
    import decisions as DQ
    assert DQ._commands in DQ.SOURCES
    assert "command" in [a.__name__ for a in __import__("engine.activities", fromlist=["ALL"]).ALL]
    cls = __import__("yaml").safe_load((ROOT / "config/autonomy.yaml").read_text())["classes"]["command"]
    assert cls["floor"] == "security" and cls["highest"] == 0
    assert '"command_approve"' in (ROOT / "images/mission-control/server.py").read_text()
