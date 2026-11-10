"""ops/crew.py: reading the crew from systemd, the test agent's analysis, the memory curator's suggestions."""
import json
import types

import pytest

SHOW = """Id=backup.service
ActiveState=inactive
SubState=dead
Result=success
ExecMainStartTimestamp=@1800000000
ExecMainExitTimestamp=@1800000300
LoadState=loaded

Id=backup.timer
NextElapseUSecRealtime=@1800086400
LoadState=loaded

Id=digest.service
ActiveState=inactive
SubState=dead
Result=exit-code
ExecMainStartTimestamp=@1800001000
ExecMainExitTimestamp=@1800001010
LoadState=loaded
"""


@pytest.fixture
def C():
    import crew
    return crew


def test_systemd_state_becomes_crew_cards(C):
    units = C.parse_show(SHOW)
    b = C.unit_status(C.BY_ID["backup"], units)
    assert (b["state"], b["last"], b["seconds"], b["next"], b["installed"]) == ("ok", 1800000000, 300, 1800086400, True)
    assert C.unit_status(C.BY_ID["digest"], units)["state"] == "failed"
    assert C.unit_status(C.BY_ID["tests"], units)["installed"] is False           # not installed yet: left out of the list


def test_text_times_and_intervals(C):
    import time
    t = C.ts("Thu 2026-10-29 03:31:05 CET")
    assert time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) == "2026-10-29 03:31:05"
    assert [C.plain_calendar(x) for x in ("Sun *-*-* 04:00:00", "*-*-* 03:30", "*-*-01 09:00", "Mon *-*-* 04:30")] == \
        ["Sundays 04:00", "daily 03:30", "monthly on day 1, 09:00", "Mondays 04:30"]
    assert C.seconds_of("10min") == 600 and C.seconds_of("1h 30min") == 5400 and C.ts("") is None


def test_test_agent_finds_flaky_failing_and_slow(C):
    out = ("=== RUN 1\nFAILED tests/test_a.py::test_x - x\n0.50s call tests/test_b.py::test_y\n3 passed, 1 failed in 2s\n"
           "=== RUN 2\nFAILED tests/test_a.py::test_x - x\nFAILED tests/test_c.py::test_z - z\n4.20s call tests/test_b.py::test_y\n2 passed, 2 failed\n"
           "=== RUN 3\nFAILED tests/test_a.py::test_x - x\n3 passed, 1 failed\n")
    fails, slow, summary = C.parse_runs(out)
    assert set.intersection(*fails) == {"tests/test_a.py::test_x"}                 # always failing
    assert set.union(*fails) - set.intersection(*fails) == {"tests/test_c.py::test_z"}   # flaky
    assert slow == [(4.2, "tests/test_b.py::test_y")] and len(summary) == 3          # once, with its slowest time


def test_untested_functions(C, tmp_path):
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "x.py").write_text("def covered():\n    pass\n\ndef lonely(a):\n    return a\n    # more\n\ndef _private():\n    pass\n")
    gaps = C.untested(tmp_path, "from x import covered\ncovered()")
    assert gaps == [("ops/x.py", "lonely", 4)]


def test_crew_actions_are_validated(C, monkeypatch):
    C.M = types.SimpleNamespace(now=lambda: __import__("datetime").datetime(2027, 1, 1), event=lambda *a, **k: None)
    with pytest.raises(ValueError):
        C.handle({"action": "crew_run", "id": "rm -rf"}, None)
    with pytest.raises(ValueError):
        C.forget(["not an id; drop"], "")
    calls = []
    monkeypatch.setattr(C.subprocess, "run", lambda cmd, **k: calls.append(cmd) or types.SimpleNamespace(returncode=0, stderr="", stdout=""))
    assert C.handle({"action": "crew_run", "id": "backup"}, None) == {"started": "backup"}
    assert calls[-1] == ["systemctl", "--user", "start", "--no-block", "backup.service"]


def test_the_review_and_the_board_answers_get_the_builders_clone_first_also_on_a_fresh_machine(C, monkeypatch):
    """The maintainability review once failed before any model call: it read a workbench clone a fresh machine does not
    have. The review, a crew agent's Board answers and a replay take the clone through the builder's own path first."""
    import builds as B
    import evals as EV
    from pathlib import Path
    calls = []
    monkeypatch.setattr(B, "clone", lambda repo, slot=None: calls.append(("clone", repo)) or Path("/srv/ai/workbench/ai-stack"))
    monkeypatch.setattr(B, "git", lambda path, *a, **k: calls.append(("git", *a)) or "")
    monkeypatch.setattr(C, "save", lambda *a, **k: None)

    def run(cmd, **k):
        calls.append(("run", *cmd[:2]))
        raise RuntimeError("the sandbox is not here in a test")
    monkeypatch.setattr(C.subprocess, "run", run)
    for go in (lambda: C.maintainability(None), lambda: C._ask_claude("answer", "tests"),
               lambda: EV.ask({"id": "x", "model": "claude-subscription"}, "text")):
        calls.clear()
        with pytest.raises(RuntimeError, match="sandbox"):
            go()
        assert calls[0] == ("clone", "ai-stack") and calls[-1] == ("run", "docker", "exec")       # the clone first, then the sandbox
    calls.clear()
    with pytest.raises(RuntimeError):
        C.maintainability(None)
    assert calls[:2] == [("clone", "ai-stack"), ("git", "fetch", "-q", "origin")]              # the review reads origin's newest main


def test_forget_soft_retires_only_the_given_facts(C, monkeypatch, tmp_path):
    C.M = types.SimpleNamespace(event=lambda *a, **k: None)
    monkeypatch.setattr(C, "OUT", tmp_path)
    (tmp_path / "memory.json").write_text(json.dumps({"suggestions": [{"id": "1234abcd"}, {"id": "5678efab"}]}))
    seen = []
    monkeypatch.setattr(C.subprocess, "run", lambda cmd, **k: seen.append(cmd) or types.SimpleNamespace(returncode=0, stdout="1", stderr=""))
    assert C.forget(["1234abcd"]) == {"forgotten": 1}
    assert "'state':'invalidated'" in seen[0][5] and json.loads(seen[0][6]) == ["1234abcd"]       # PATCH, never DELETE
    assert [s["id"] for s in json.loads((tmp_path / "memory.json").read_text())["suggestions"]] == ["5678efab"]


def test_a_crew_job_without_a_swarm_card_opens_no_swarm_run(monkeypatch):
    """FND-113: the journeys have no swarm card; their run was started (as system) but its finish was refused ("no card
    for 'journeys'"), so every night left a run "never finished" on the health board. A job without a card now opens no
    swarm run; a job with one opens and finishes it."""
    import crew as C
    import inbox as INB
    import missions
    import registry as REG
    import runtime as RTM
    import swarm_client as SW
    calls = []
    monkeypatch.setattr(SW, "paused", lambda n: False)
    monkeypatch.setattr(SW, "run_start", lambda agent, run, **k: calls.append(("start", agent)))
    monkeypatch.setattr(SW, "run_finish", lambda agent, run, summary, **k: calls.append(("finish", agent)))
    for f in ("start", "end", "emit", "set_ref"):
        monkeypatch.setattr(RTM, f, lambda *a, **k: None)
    monkeypatch.setattr(missions, "db", lambda: None)
    monkeypatch.setattr(missions, "event", lambda *a, **k: None)
    monkeypatch.setattr(C, "journeys", lambda c: 0)
    monkeypatch.setattr(INB, "digest", lambda c: 0)
    monkeypatch.setattr(C, "agent_file", lambda n: {"result": "ok"})
    monkeypatch.setattr(C, "answer_requests", lambda n, r: 0)
    monkeypatch.setattr(C, "_journal", lambda *a, **k: None)
    monkeypatch.setattr(C.J, "begin", lambda *a, **k: None)
    monkeypatch.setattr(C.J, "end", lambda *a, **k: None)
    monkeypatch.setattr(REG, "hash_of", lambda n, *a: None if n == "journeys" else "h")
    C.run("journeys")
    assert calls == []
    C.run("inbox")
    assert calls == [("start", "inbox"), ("finish", "inbox")]
