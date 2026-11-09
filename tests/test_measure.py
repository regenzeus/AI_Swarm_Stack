"""A measured change (GEN-17): one command runs the arms on one case and records each run's tests, tokens, builds,
minutes and memory side by side."""
import json

import measure as MZ


def result(d, name, arm, task, passed, total, tokens, builds, minutes, start):
    (d / name).mkdir(parents=True)
    (d / name / "result.json").write_text(json.dumps({"started_at": start, "arm": arm, "version": "abc1234", "task": task,
                                                      "score": {"passed": passed, "total": total}, "builds": list(range(builds)),
                                                      "metrics": {"tokens": tokens, "minutes": minutes}}))


def test_the_command_runs_every_arm_on_one_case_and_reports_them_side_by_side(tmp_path, monkeypatch):
    runs, mem = tmp_path / "runs", tmp_path / "runs.jsonl"
    result(runs, "replay-demo-7-one-coder-20261108-0100", "one-coder", 11, 10, 10, 300_000, 1, 5, "2026-11-08 01:00")
    result(runs, "replay-demo-7-stack-20261108-0200", "stack", 12, 10, 10, 500_000, 4, 30, "2026-11-08 02:00")
    result(runs, "replay-demo-8-stack-20261108-0300", "stack", 13, 99, 102, 900_000, 6, 40, "2026-11-08 03:00")
    mem.write_text("\n".join(json.dumps(x) for x in (
        {"run": "task-intake:12-0", "chars": 1000, "measurable_chars": 800, "used_chars": 800},
        {"run": "task:12:step:2", "chars": 2000, "measurable_chars": 1200, "used_chars": 400},
        {"run": "task:120:step:2", "chars": 9999, "measurable_chars": 9999, "used_chars": 9999})))      # another task: not counted
    monkeypatch.setattr(MZ, "RUNS", runs)
    monkeypatch.setattr(MZ, "MEMORY", mem)
    called = []
    table = MZ.run("demo", 7, call=lambda cmd, check: called.append(cmd[-3:]))
    assert called == [["demo", "7", "one-coder"], ["demo", "7", "stack"]]
    assert "| 2026-11-08 02:00 | 7 | stack | abc1234 | 10 of 10 | 500,000 | 4 | 30 | 3,000 | 60% |" in table
    assert "| 2026-11-08 01:00 | 7 | one-coder | abc1234 | 10 of 10 | 300,000 | 1 | 5 | 0 | – |" in table
    assert "| 7 | one-coder | 1 | 1 of 1 | 300,000 | 1 | 5 |" in table and "case 8" not in table and "| 8 |" not in table
    assert "| 8 | stack | 1 | 0 of 1 | 900,000 | 6 | 40 |" in MZ.report(MZ.runs("demo", since="2026-11-08 02:30"))
