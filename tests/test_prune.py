"""PLT-21: growing files are pruned after 90 days: the runner's event lines, run logs and build logs (ops/prune.py), the
app's uploads (server.py prune_uploads); what is younger, a build's record and an unreadable line stay."""
import json
import os
import threading
import time


def aged(f, days, now):
    f.parent.mkdir(parents=True, exist_ok=True)
    if not f.exists():
        f.write_text("x")
    os.utime(f, (now - days * 86400, now - days * 86400))
    return f


def test_the_runner_drops_what_is_older_than_90_days(tmp_path):
    import datetime as dt
    import prune as PR
    now = time.time()
    pub, runs, builds = tmp_path / "public", tmp_path / "runs", tmp_path / "builds"
    pub.mkdir()
    old = dt.datetime.fromtimestamp(now - 100 * 86400).astimezone().isoformat(timespec="seconds")
    new = dt.datetime.fromtimestamp(now - 5 * 86400).astimezone().isoformat(timespec="seconds")
    (pub / "events.jsonl").write_text("\n".join([json.dumps({"ts": old, "text": "old"}), json.dumps({"ts": new, "text": "new"}), "{broken"]) + "\n")
    aged(runs / "12.log", 100, now)
    aged(runs / "13.log", 10, now)
    aged(builds / "4.diff", 120, now)
    aged(builds / "4.steps", 120, now)
    aged(builds / "keep.json", 120, now)                     # not a build's log: stays
    n = PR.run(now, pub, runs, builds, threading.Lock())
    assert n == {"events": 1, "run_logs": 1, "build_files": 2}
    lines = (pub / "events.jsonl").read_text().splitlines()
    assert [json.loads(x)["text"] for x in lines[:1]] == ["new"] and lines[1] == "{broken"
    assert not (runs / "12.log").exists() and (runs / "13.log").exists() and (builds / "keep.json").exists()
    assert PR.run(now, pub, runs, builds, threading.Lock()) == {"events": 0, "run_logs": 0, "build_files": 0}


def test_the_app_drops_uploads_older_than_90_days(tmp_path):
    import server as S
    now = time.time()
    a, b = aged(tmp_path / "uploads/old.pdf", 91, now), aged(tmp_path / "files/abc/new.png", 3, now)
    assert S.prune_uploads(now, [tmp_path / "uploads", tmp_path / "files", tmp_path / "none"]) == 1
    assert not a.exists() and b.exists()
