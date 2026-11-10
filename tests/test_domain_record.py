"""The record of a run and a pack's exams (GEN-31, docs/AI-STACK.md): a toy run exports one bundle a person can follow
without the app, with its chain from the item to the decisions and the files it made, and a toy exam set runs through
its workflow and scores, naming the case it got wrong."""
import json
import zipfile
from pathlib import Path

from domain import artifacts as AR
from domain import record as RC

ROOT = Path(__file__).resolve().parents[1]
PACK = {"name": "toy", "dir": str(ROOT / "tests/fixtures/packs/toy")}


def test_a_toy_run_exports_one_bundle_with_its_chain_from_item_to_decisions_and_the_files_it_made(tmp_path, monkeypatch):
    monkeypatch.setenv("AISTACK_ARTIFACTS", str(tmp_path / "artifacts"))
    f = tmp_path / "fix.zip"
    f.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    art = AR.put(f, task="test/T-9", step="build", run="toy/record:T-9", commit="c0ffee")["id"]
    run = {"id": "toy/record:T-9", "task": "test/T-9", "workflow": "toy/record", "status": "done", "started": "2026-11-10T09:00:00",
           "ended": "2026-11-10T09:30:00", "nodes": [
               {"id": "item", "title": "A ticket arrives", "block": "start", "status": "done"},
               {"id": "build", "title": "Build the fix", "block": "command", "status": "done", "answer": {"ref": "job:wsl/abc", "artifacts": [art]}},
               {"id": "ok", "title": "Approve the fix", "block": "ask", "status": "done", "answer": {"who": "owner", "branch": "yes"}},
               {"id": "done", "title": "Delivered", "block": "end", "status": "done"}]}
    out = RC.export(run, tmp_path / "out/record.zip", history={"execution": 41, "status": "success"})
    z = zipfile.ZipFile(out)
    got = json.loads(z.read("run.json"))
    assert got["task"] == "test/T-9" and [n["id"] for n in got["nodes"]] == ["item", "build", "ok", "done"]
    page = z.read("index.html").decode()
    assert "Item <b>test/T-9</b>" in page and "decided by owner" in page and "went “yes”" in page
    assert page.index("Build the fix") < page.index("Approve the fix") and "history.json" in page
    sha = art.removeprefix("artifact:")
    assert f"artifacts/{sha}" in z.namelist() and AR.records(sha)[0]["commit"] == "c0ffee"
    assert json.loads(z.read("history.json"))["execution"] == 41
    bare = zipfile.ZipFile(RC.export(run, tmp_path / "out/bare.zip"))                  # no orchestrator history: none in the bundle
    assert "history.json" not in bare.namelist() and "history.json" not in bare.read("index.html").decode()


def test_a_toy_exam_set_runs_through_its_workflow_and_scores_naming_the_case_it_got_wrong():
    def runner(decide):
        def run_case(workflow, item, case):
            assert workflow == "toy/triage" and item.startswith("exam/toy/bugs/")
            return {"status": "done", "nodes": {"route": {"answer": {"branch": decide(case["ticket"])}}}}
        return run_case
    good = RC.exam(PACK, "bugs", runner(lambda t: "bug" if any(w in t for w in ("stops", "fails")) else "question"))
    assert good["score"] == 1.0 and good["right"] == 3 and good["workflow"] == "toy/triage"
    naive = RC.exam(PACK, "bugs", runner(lambda t: "bug"))
    assert naive["right"] == 2 and [c["case"]["ticket"] for c in naive["cases"] if not c["right"]] == ["How do I export only one folder?"]
