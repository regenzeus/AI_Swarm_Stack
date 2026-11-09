"""The weekly trial rotation (ops/rotation.py, TRL-14) and the research-accuracy exam's path through the trial runner
(ops/trials.py, TRL-16). Fake shell and state; no trial runs."""
import datetime as dt
import json
from pathlib import Path

import rotation as RO
import trials as TR

ROOT = Path(__file__).resolve().parent.parent


def at(day, hour=1):
    return dt.datetime(2026, 11, day, hour, 0).timestamp()            # 2 Nov 2026 is a Monday


def test_each_night_has_its_trial_and_sunday_rests():
    assert [RO.pick(at(d)) for d in range(2, 9)] == ["research-accuracy", "stack-trace", "semver", "research-accuracy", "mqtt-trace", "mustache", None]
    assert all((ROOT / "eval/trials" / f"{n}.yaml").exists() for n in RO.WEEK.values())   # every night's trial exists
    timer = (ROOT / "ops/systemd/rotation.timer").read_text()
    assert "OnCalendar=*-*-* 01:00" in timer and "Persistent=false" in timer           # a missed night is not run at boot
    assert "ExecStart=/usr/bin/python3 ops/rotation.py" in (ROOT / "ops/systemd/rotation.service").read_text()


def test_it_starts_the_trial_only_when_the_stack_is_idle(tmp_path):
    calls, clock = [], [at(2)]
    st = tmp_path / "state.json"
    st.write_text(json.dumps({"tasks": [{"id": 5, "status": "running", "updated": dt.datetime.fromtimestamp(at(2)).isoformat()}]}))

    def sh(*cmd, timeout=0):
        calls.append(cmd)
        return "trial-semver-0100.service loaded active running x\n" if cmd[:2] == ("systemctl", "--user") and len(calls) < 3 else ""

    def sleep(s):
        clock[0] += s
        if clock[0] > at(2) + 1200:
            st.write_text(json.dumps({"tasks": []}))                       # the task ended; the other trial too
    row = RO.run(sh=sh, state=st, log=tmp_path / "rot.jsonl", sleep=sleep, now=lambda: clock[0])
    assert row["trial"] == "research-accuracy" and row["started"] and "skipped" not in row
    assert ("make", "-C", str(RO.ROOT), "trial", "NAME=research-accuracy") in calls
    (tmp_path / "busy.json").write_text(json.dumps({"running": {"slug": "x"}}))
    busy = RO.run(sh=lambda *c, timeout=0: "", state=tmp_path / "busy.json", log=tmp_path / "rot.jsonl", sleep=lambda s: None,
                  now=lambda: at(3), wait=0)
    assert busy["skipped"] == "a mission is running" and "started" not in busy
    assert RO.run(sh=sh, state=st, log=tmp_path / "rot.jsonl", now=lambda: at(8))["rest"] is True
    assert len((tmp_path / "rot.jsonl").read_text().splitlines()) == 3


def test_the_research_exam_goes_in_as_research_and_hands_the_key_its_answer_and_the_pages_read(tmp_path, monkeypatch):
    t = TR.load("research-accuracy")
    assert t["kind"] == "research" and t["task"].count("?") == 25 and "web address" in t["task"]
    sent = []
    monkeypatch.setattr(TR, "check", lambda t: None)
    monkeypatch.setattr(TR, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(TR, "make_repo", lambda *a: (_ for _ in ()).throw(AssertionError("no repository for research")))
    monkeypatch.setattr(TR, "request", lambda req, **kw: sent.append(req) or {"task": 41})
    monkeypatch.setattr(TR, "follow", lambda t, run_id, repo, tid, started, log: (repo, tid))
    assert TR.run("research-accuracy", log=lambda *a: None) == ("", 41)
    assert sent[0]["kind"] == "research" and "repo" not in sent[0] and sent[0]["source"] == "trial:research-accuracy"
    vault = tmp_path / "vault"
    (vault / "tasks").mkdir(parents=True)
    (vault / "tasks/41-research.md").write_text("1. 1993 (https://home.cern/x)\n")
    monkeypatch.setattr(TR, "VAULT", vault)

    class C:
        def execute(self, q, args):
            return type("R", (), {"fetchone": lambda self: {"result": "tasks/41-research.md"}})()
    got = TR.answered(C(), 41, ["https://home.cern/x", "https://home.cern/x"], tmp_path / "code")
    assert got == {"id": 41, "status": "answered"}
    assert (tmp_path / "code/answer.md").read_text().startswith("1. 1993") and (tmp_path / "code/opened.txt").read_text() == "https://home.cern/x\n"
    assert TR.answered(type("E", (), {"execute": lambda self, q, a: type("R", (), {"fetchone": lambda self: None})()})(), 42, [], tmp_path / "none") is None
