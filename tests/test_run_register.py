"""WFL-22, WFL-23: the run register is the stack's record of every run n8n drives (n8n holds time and order only). Each
step is kept with its request, its whole answer, its files and its times, across a restart; a stand-in run exports as
one zip from the register alone, with the workflow's shape from git or the pack cache; a customer-class deployment
answers n8n with status, ids and a short summary while the register keeps the whole text, unless the deployment
relaxes it."""
import json
import sqlite3
import types
import zipfile
from pathlib import Path

import pytest

import dataguard as DG
import flows as FW
import runreg as RR
from domain import artifacts as AR
from domain import record as RC

ROOT = Path(__file__).resolve().parents[1]
RESUME = "https://pc.example.ts.net:8450/webhook-waiting/41/s"
TOY = ROOT / "tests/fixtures/packs/toy"
LONG = "The export stops at 2 GB because the writer keeps the whole file in memory. " * 20


class Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def R(tmp_path, monkeypatch):
    monkeypatch.setenv("N8N_HOOK_TOKEN", "hook-test")          # SEC-27: the runner's header for n8n's webhooks
    store = tmp_path / "standin.json"
    store.write_text(json.dumps({"items": {"T-1": {"updated": "2026-11-10T09:00:00", "comments": []}}}))
    (tmp_path / "trackers.yaml").write_text(f"trackers:\n  - {{name: test, kind: standin, path: {store}, workflow: toy/ticket}}\n")
    monkeypatch.setenv("AISTACK_TRACKERS", str(tmp_path / "trackers.yaml"))
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("AISTACK_ARTIFACTS", str(tmp_path / "artifacts"))
    monkeypatch.setattr(RR, "ROOT", tmp_path / "register")
    for name in ("PENDING", "DONE", "ASKS", "BUILDS"):
        monkeypatch.setattr(FW, name, tmp_path / "flows" / name.lower())
    FW.PENDING.mkdir(parents=True)
    FW.M = types.SimpleNamespace(stop=__import__("threading").Event(), log=print, notify=lambda *a: None, db=None, event=lambda *a, **k: None)
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("create table tasks (id integer primary key, title text, status text, created text, updated text)")
    db.execute("create table task_steps (task integer, occ integer, idx integer, title text, agent text, harness text, status text, output text, error text)")
    db.execute("insert into tasks values (5, 'Triage T-1', 'done', '2026-11-10T09:01', '2026-11-10T09:02')")
    db.execute("insert into task_steps values (5, 1, 1, 'Triage T-1', 'toy:intake', 'hermes', 'done', ?, '')", (LONG,))
    made = tmp_path / "repro.log"
    made.write_text("reproduced at 2 GB\n")
    art = AR.put(made, task="test/T-1", step="c1", run="41")["id"]
    stand = {"agent": {"status": "done", "task": 5, "step": 9, "output": LONG, "agent": "toy:intake", "harness": "hermes"},
             "command": {"status": "done", "place": "wsl-host", "command": "toy.reproduce", "job": "wsl-host/j1", "artifacts": ["repro.log"],
                         "artifact_ids": [art], "log": "reproduced at 2 GB"},
             "build": {"status": "done", "build": 3, "state": "review", "branch": "ai/T-1-fix-the-export", "pr": "https://forge.example/pr/7",
                       "pr_number": 7, "draft": True, "changed": True, "output": "Streams the file instead of holding it"}}
    real = FW.work
    monkeypatch.setattr(FW, "work", lambda rid, req, cards, crew, sleep: stand[req["kind"]] if req["kind"] in stand else real(rid, req, cards, crew, sleep))
    sent = []

    def step(rid, **req):
        p = FW.PENDING / f"{rid}.json"
        p.write_text(json.dumps({"resume_url": RESUME, "workflow": "wfbug", "workflow_name": "toy/ticket", "execution": "41", "node": req.get("title", rid), **req}))
        FW.handle(rid, p, cards={"toy:intake": {}}, crew={}, post=lambda r, timeout=30: sent.append(json.loads(r.data)) or Resp(), sleep=lambda s: None,
                  repos=["toy"])
        return p
    return types.SimpleNamespace(step=step, sent=sent, db=db, art=art, store=store, tmp=tmp_path)


def test_every_step_is_kept_in_the_run_register_with_its_request_answer_files_and_times_across_a_restart(R):
    R.step("a1", kind="agent", agent="toy:intake", brief="Triage the ticket", title="Triage")
    R.step("c1", kind="command", place="wsl-host", command="toy.reproduce", title="Reproduce")
    run = RR.run("41")
    assert [s["rid"] for s in run["steps"]] == ["a1", "c1"] and run["name"] == "toy/ticket"
    a1 = run["steps"][0]
    assert a1["request"]["brief"] == "Triage the ticket" and "resume_url" not in a1["request"] and a1["answer"]["output"] == LONG
    assert a1["started"] and a1["ended"] and run["steps"][1]["artifacts"] == [R.art]
    p = FW.PENDING / "a1.json"                                   # after a restart the step is looked at again: kept once
    p.write_text(json.dumps({"resume_url": RESUME, "execution": "41", "kind": "agent", "agent": "toy:intake", "brief": "Triage the ticket"}))
    FW.handle("a1", p, cards={"toy:intake": {}}, crew={}, post=lambda r, timeout=30: Resp(), sleep=lambda s: None)
    assert [s["rid"] for s in RR.run("41")["steps"]] == ["a1", "c1"]


def test_a_stand_in_run_exports_as_one_zip_from_the_run_register_with_the_workflows_shape_from_its_pack(R, monkeypatch):
    t0 = 1_800_000_000.0
    monkeypatch.setattr(RR, "_now", lambda: t0)
    R.step("a1", kind="agent", agent="toy:intake", brief="Triage the ticket", title="Triage")
    R.step("t1", kind="tracker", tracker="test", key="T-1", write="comment", body="Could you attach the log?", title="Ask the reporter")
    R.step("w1", kind="wait_item", tracker="test", key="T-1", timeout_hours=24, title="Wait for the reporter")
    monkeypatch.setattr(RR, "_now", lambda: t0 + 25 * 3600)
    R.step("w1", kind="wait_item", tracker="test", key="T-1", timeout_hours=24, title="Wait for the reporter")
    R.step("t2", kind="tracker", tracker="test", key="T-1", write="comment", body="A reminder: the log, please", title="Remind")
    R.step("c1", kind="command", place="wsl-host", command="toy.reproduce", title="Reproduce")
    R.step("b1", kind="build", repo="toy", brief="Fix the export at 2 GB", item="test/T-1", base="v1.0", target="release/1", title="Fix")
    R.step("s1", kind="tracker", tracker="test", key="T-1", write="summary", body="Fixed; a draft pull request is open", title="Summary")
    packs = [{"name": "toy", "workflows": [{"name": "toy/ticket", "path": str(TOY / "workflows/ticket.json")}]}]
    out = RC.export_run("41", R.tmp / "out/run.zip", db=R.db, packs=packs)
    z = zipfile.ZipFile(out)
    run = json.loads(z.read("run.json"))
    assert [n["block"] for n in run["nodes"]] == ["agent", "tracker", "wait_item", "tracker", "command", "build", "tracker"]
    assert run["id"] == "toy/ticket:test/T-1" and run["task"] == "test/T-1" and run["status"] == "done"
    assert run["nodes"][0]["result"]["output"] == LONG and run["nodes"][0]["task_record"]["steps"][0]["output"] == LONG
    assert run["nodes"][2]["answer"]["branch"] == "timeout"
    assert [w["ref"] for w in run["tracker_writes"]] == ["shadow:comment/n8n/t1", "shadow:comment/n8n/t2", "shadow:summary/n8n/s1"]
    assert all(w["shadow"] for w in run["tracker_writes"])
    assert run["pull_requests"] == [{"url": "https://forge.example/pr/7", "number": 7, "branch": "ai/T-1-fix-the-export", "draft": True, "build": 3}]
    sha = R.art.removeprefix("artifact:")
    assert run["files"][0]["sha256"] == sha and run["files"][0]["made_by"][0]["run"] == "41" and f"artifacts/{sha}" in z.namelist()
    shape = json.loads(z.read("workflow.json"))
    assert shape["name"] == "toy/ticket" and shape["source"].startswith("pack toy") and "Triage" in [n["name"] for n in shape["nodes"]]
    assert "history.json" not in z.namelist()                   # nothing from n8n's internal API
    page = z.read("index.html").decode()
    assert page.index("Triage") < page.index("Wait for the reporter") < page.index("Summary") and "went “timeout”" in page
    assert RC.shape_of("aisc33b90ad7380d", "")["source"] == "git: n8n/workflows/crew-swarm-sync.json"   # a workflow of the repository, by its id


def test_a_customer_deployment_answers_n8n_with_status_ids_and_a_summary_while_the_register_keeps_the_whole_text(R, monkeypatch):
    monkeypatch.setattr(DG, "DATA", {"class": "customer"})
    assert FW.lean_answers()
    R.step("a1", kind="agent", agent="toy:intake", brief="Triage the ticket", title="Triage")
    R.step("b1", kind="build", repo="toy", brief="Fix it", item="test/T-1", base="v1.0", target="release/1", title="Fix")
    a, b = R.sent
    assert a["lean"] and "output" not in a and a["task"] == 5 and a["step"] == 9 and a["status"] == "done"
    assert a["summary"].startswith(LONG[:100]) and len(a["summary"]) < len(LONG) and "task's record" in a["summary"]
    assert b["pr"] == "https://forge.example/pr/7" and b["build"] == 3 and len(json.dumps(b)) < 600
    assert RR.run("41")["steps"][0]["answer"]["output"] == LONG     # the whole text, in the register
    assert json.loads((FW.DONE / "a1.json").read_text())["output"] == LONG


def test_a_customer_deployment_may_relax_lean_answers_and_home_answers_whole():
    assert not FW.lean_answers({"class": "personal"})
    assert not FW.lean_answers({"class": "customer", "n8n_answers": "full"})
    assert FW.lean_answers({"class": "customer"}) and FW.lean_answers({"class": "personal", "repos": {"work": "customer"}})
    assert FW.lean({"status": "failed", "error": "x" * 900, "hits": [1, 2]}) == {
        "status": "failed", "error": FW.TC.cut("x" * 900, FW.SUMMARY_CHARS, "the whole reason is in the run register"), "hits": 2, "lean": True}
