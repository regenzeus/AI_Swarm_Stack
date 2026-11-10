"""Places and artifacts (GEN-22, GEN-29, docs/AI-STACK.md): a toy job kind runs at the wsl-host place by the worker
protocol once approved there by its hash, a value outside its type is refused, and a place the deployment does not
have is refused; two long jobs queued at one place both run, one after the other, and neither is given up (GEN-40); a
step's file is kept by its hash with the run and commit that made it, attached to a stand-in item,
and removed past its retention."""
import datetime as dt
import json
import shutil
import threading
from pathlib import Path

import pytest

import localworker as LW
from domain import artifacts as AR
from domain import places as PL
from domain import trackers as TR

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
    w = LW.Worker(root, beat_s=1)

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
    with pytest.raises(PL.Refused, match="no place 'mars' in this deployment"):
        PL.run_job("mars", "toy.reproduce", {"input": "small"}, spec=SPEC)


def test_a_steps_file_is_kept_by_its_hash_with_its_maker_attached_to_a_stand_in_item_and_removed_past_its_retention(tmp_path, monkeypatch):
    monkeypatch.setenv("AISTACK_ARTIFACTS", str(tmp_path / "artifacts"))
    zip_ = tmp_path / "result.zip"
    shutil.make_archive(str(tmp_path / "result"), "zip", str(ROOT / "tests/fixtures/packs/toy"))
    t0 = dt.datetime(2026, 11, 9, tzinfo=dt.timezone.utc)
    rec = AR.put(zip_, task="test/T-7", step="reproduce", run="toy/ticket:test/T-7", commit="abc123", data_class="private", now=t0)
    assert rec["id"] == f"artifact:{rec['sha256']}" and AR.path_of(rec["id"]).read_bytes() == zip_.read_bytes()
    assert AR.records(rec["id"])[0] | {"run": "toy/ticket:test/T-7", "commit": "abc123", "step": "reproduce"} == AR.records(rec["id"])[0]
    store = tmp_path / "standin.json"
    store.write_text(json.dumps({"items": {"T-7": {"updated": "2026-11-09T10:00:00", "comments": []}}}))
    (tmp_path / "trackers.yaml").write_text(f"trackers:\n  - {{name: test, kind: standin, path: {store}, workflow: toy/ticket}}\n")
    monkeypatch.setenv("AISTACK_TRACKERS", str(tmp_path / "trackers.yaml"))
    monkeypatch.setenv("AISTACK_TRACKER_STATE", str(tmp_path / "state"))
    TR.handle({"action": "tracker_live", "kind": "attach", "live": True})
    TR.write({"tracker": "test", "kind": "attach", "key": "T-7", "body": f"{rec['id']} result.zip", "write_id": "w1"})
    log = json.loads(store.read_text())["items"]["T-7"]["log"]
    assert log[0]["kind"] == "attach" and log[0]["value"].startswith(rec["id"])
    assert AR.prune(t0 + dt.timedelta(days=30)) == [] and AR.path_of(rec["id"])
    assert AR.prune(t0 + dt.timedelta(days=AR.RETAIN_DAYS + 1)) == [rec["sha256"]] and AR.path_of(rec["id"]) is None and AR.records(rec["id"]) == []


def test_commands_are_the_queues():
    import decisions as DQ
    assert DQ._commands in DQ.SOURCES
    cls = __import__("yaml").safe_load((ROOT / "config/autonomy.yaml").read_text())["classes"]["command"]
    assert cls["floor"] == "security" and cls["highest"] == 0
    assert '"command_approve"' in (ROOT / "images/mission-control/server.py").read_text()


LONG = {"kind": "toy.long", "about": "Wait the given seconds, a stand-in for a licensed tool's run of hours",
        "params": {"seconds": {"type": "int", "min": 0, "max": 600}},
        "steps": [["python3", "-c", "import sys, time; time.sleep(int(sys.argv[1])); print('slept', sys.argv[1])", "{seconds}"]],
        "collect": [], "minutes": 11}


def test_two_long_jobs_queued_at_one_place_both_finish_one_after_the_other_and_neither_is_given_up(host, monkeypatch):
    """GEN-40: two 10-minute jobs at wsl-host, scaled to 4 s each against a pick-up timeout of 0.5 s, so the second waits
    four times the timeout behind the first; the worker's status names the running job and the one queued."""
    (host / "jobs.d/toy.long.json").write_text(json.dumps(LONG))
    (host / "approved.json").write_text(json.dumps({"toy.long": __import__("winjobs").digest(host / "jobs.d/toy.long.json")}))
    monkeypatch.setattr(PL, "PICKUP_S", 0.5)
    monkeypatch.setattr(PL, "ALIVE_S", 2.5)          # the worker beats every second
    monkeypatch.setattr(LW, "STALE_S", 2.5)            # the second request is older than this when it is taken; a request's
                                                       # time is in whole seconds, so the first needs this room on a busy PC
    import time
    for _ in range(50):
        if ((PL.place("wsl-host").status() or {}).get("kinds") or {}).get("toy.long", {}).get("approved"):
            break
        time.sleep(0.1)
    got, seen = {}, []

    def job(n):
        got[n] = PL.run_job("wsl-host", "toy.long", {"seconds": 4}, spec=LONG, poll=0.1)
    first = threading.Thread(target=job, args=(1,))
    first.start()
    time.sleep(0.3)
    second = threading.Thread(target=job, args=(2,))
    second.start()
    while first.is_alive() or second.is_alive():
        st = PL.place("wsl-host").status() or {}
        if st.get("running"):
            seen.append((st["running"]["kind"], st.get("queued")))
        time.sleep(0.1)
    assert got[1]["status"] == "done" and got[2]["status"] == "done", got
    assert ("toy.long", 1) in seen                      # one runs, one waits behind it, and the status says so
    ends = {n: json.loads((host / "outbox" / got[n]["rid"] / "result.json").read_text())["ended"] for n in got}
    assert all(got[n]["steps"][0]["seconds"] >= 2 for n in got) and ends[2] - ends[1] >= 1   # one after the other (whole seconds)


def test_the_pickup_clock_stands_while_the_worker_runs_another_job_and_counts_while_it_is_idle_or_gone(tmp_path):
    """GEN-40 on a fast clock: a request waits 10 minutes behind a running job and is still queued; idle or gone, the
    worker's 5 minutes count from its last job's end or from when it was last seen."""
    out = tmp_path / "outbox"
    out.mkdir()
    p = PL.Place("wsl-host", tmp_path / "inbox", out)
    t = 1_000_000.0

    def status(ts, running=None, idle_since=0.0, queued=1):
        (out / "status.json").write_text(json.dumps({"ts": ts, "kinds": {}, "busy": {"toy.long": "a" * 12} if running else {},
                                                     "running": running, "queued": queued, "idle_since": idle_since}))
    status(t + 600, running={"id": "a" * 12, "kind": "toy.long", "since": t})
    st = p.state("b" * 12, submitted=t, now=t + 605)
    assert st["status"] == "queued" and st["behind"]["kind"] == "toy.long" and st["queued"] == 1
    status(t + 700, idle_since=t + 650)                 # the first job ended at +650: the clock starts there
    assert p.state("b" * 12, submitted=t, now=t + 700)["status"] == "queued"
    status(t + 951, idle_since=t + 650)
    st = p.state("b" * 12, submitted=t, now=t + 951)
    assert st["status"] == "not picked up" and "while it was idle or not running" in st["error"]
    status(t + 600, running={"id": "a" * 12, "kind": "toy.long", "since": t})     # last seen busy at +600, then gone
    assert p.state("b" * 12, submitted=t, now=t + 800)["status"] == "queued"
    assert p.state("b" * 12, submitted=t, now=t + 901)["status"] == "not picked up"
    (out / "status.json").unlink()                      # never seen: from the request
    assert p.state("b" * 12, submitted=t, now=t + 301)["status"] == "not picked up"


def test_a_job_kind_sets_its_own_run_limit_in_its_file_and_the_status_carries_it(tmp_path):
    """GEN-40: a kind's minutes, up to a day, is the one run limit (the worker stops a job past it, tests/test_winworker.py);
    the stack adds none of its own."""
    import winjobs as WJ
    assert WJ.kind_problems(LONG) == [] and WJ.kind_problems({**LONG, "minutes": 24 * 60}) == []
    assert any("minutes" in x for x in WJ.kind_problems({**LONG, "minutes": 24 * 60 + 1}))
    root = tmp_path / "w"
    (root / "jobs.d").mkdir(parents=True)
    (root / "jobs.d/toy.long.json").write_text(json.dumps({**LONG, "minutes": 600}))
    w = LW.Worker(root)
    w.status()
    st = json.loads((root / "outbox/status.json").read_text())
    assert st["kinds"]["toy.long"]["minutes"] == 600 and st["running"] is None and st["queued"] == 0
    import inspect
    assert inspect.signature(PL.run_job).parameters["timeout"].default is None
