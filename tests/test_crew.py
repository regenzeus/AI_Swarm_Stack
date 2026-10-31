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


def test_memory_near_duplicates_keep_the_older(C):
    facts = [{"id": "a" * 8, "text": "The owner prefers English for everything in the stack"},
             {"id": "b" * 8, "text": "The owner prefers English for everything in the stack."},
             {"id": "c" * 8, "text": "The NAS runs Forgejo on port 3000"}]
    sug = C.near_duplicates(facts)
    assert [s["id"] for s in sug] == ["b" * 8] and "duplicate of" in sug[0]["why"]


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


def test_forget_soft_retires_only_the_given_facts(C, monkeypatch, tmp_path):
    C.M = types.SimpleNamespace(event=lambda *a, **k: None)
    monkeypatch.setattr(C, "OUT", tmp_path)
    (tmp_path / "memory.json").write_text(json.dumps({"suggestions": [{"id": "1234abcd"}, {"id": "5678efab"}]}))
    seen = []
    monkeypatch.setattr(C.subprocess, "run", lambda cmd, **k: seen.append(cmd) or types.SimpleNamespace(returncode=0, stdout="1", stderr=""))
    assert C.forget(["1234abcd"]) == {"forgotten": 1}
    assert "'state':'invalidated'" in seen[0][5] and json.loads(seen[0][6]) == ["1234abcd"]       # PATCH, never DELETE
    assert [s["id"] for s in json.loads((tmp_path / "memory.json").read_text())["suggestions"]] == ["5678efab"]
