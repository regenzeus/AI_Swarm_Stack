"""Trials (phase 10a, ops/trials.py, docs/SWARM-TRIALS.md): a trial is checked before it runs, its answer key must score
its own reference fully, the scorer runs the delivered code in a sandbox, the clean-room audit catches a forbidden read
or action and not the trial's own names, the similarity check tells copied code from independent code, a trial's build
ends at review and is never merged, and the report says all of it."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import trials as T

ROOT = Path(__file__).resolve().parent.parent


def write_trial(root, file="demo", **over):
    t = {"name": file, "title": "Demo", "task": "Write a tiny library called demolib that adds two numbers, from spec/ only.",
         "key": file, "forbidden": {"urls": [r"github\.com/other/demo"], "commands": [r"\bimport otherdemo\b"]}, "budget": {"hours": 1}, **over}
    (root / f"{file}.yaml").write_text(json.dumps(t))
    return root


def test_a_trial_is_checked_before_it_runs(tmp_path):
    t = T.load("demo", write_trial(tmp_path))
    assert t["flag_similarity"] == 0.3 and t["_commands"][0].search("import otherdemo")
    for over, why in (({"task": "too short"}, "the task must say"), ({"budget": {"hours": 30}}, "between 0 and 24"),
                      ({"forbidden": {"commands": ["("]}}, "does not compile"), ({"name": "other"}, "its name is")):
        with pytest.raises(ValueError, match=why):
            T.load("demo", write_trial(tmp_path, **over))
    with pytest.raises(ValueError, match="no trial called"):
        T.load("../etc", tmp_path)
    real = T.load("semver")                                         # the calibration trial as it is in the repository
    assert real["key"] == "semver" and "clean-room" in real["task"] and real["budget"]["hours"] == 4


def key(tmp_path, reference_body):
    k = tmp_path / "key"
    (k / "reference/demolib").mkdir(parents=True)
    (k / "reference/demolib/__init__.py").write_text(reference_body)
    (k / "score.py").write_text(textwrap.dedent('''
        import json, sys
        sys.path.insert(0, sys.argv[1])
        import demolib
        cases = []
        for a, b in ((1, 2), (2, 2), (-1, 1)):
            try:
                ok = demolib.add(a, b) == a + b
            except Exception:
                ok = False
            cases.append({"id": f"add {a} {b}", "area": "add", "ok": ok, "detail": ""})
        print(json.dumps({"cases": cases, "error": None}))'''))
    return k


def local(cmd, **kw):                                   # the sandbox's docker run, here: the same python, the paths mapped back
    vols = dict(x.split(":")[1::-1] for x in [cmd[i + 1].rsplit(":ro", 1)[0] for i, a in enumerate(cmd) if a == "-v"])
    code, keyd = vols["/code"], vols["/key"]
    return subprocess.run([sys.executable, f"{keyd}/score.py", code], **kw)


def test_the_answer_key_must_score_its_own_reference_fully_and_scores_by_area(tmp_path):
    t = {"name": "demo", "key": "demo"}
    T.KEYS = tmp_path
    k = key(tmp_path, "def add(a, b):\n    return a + b\n")
    (tmp_path / "demo").symlink_to(k)
    s = T.check(t, run=local)
    assert (s["passed"], s["total"], s["areas"]) == (3, 3, {"add": [3, 3]})
    (k / "reference/demolib/__init__.py").write_text("def add(a, b):\n    return a * b\n")      # a key that disagrees with itself
    with pytest.raises(RuntimeError, match="does not pass its own reference"):
        T.check(t, run=local)
    bad = T.score(tmp_path, k, run=lambda *a, **kw: subprocess.CompletedProcess(a, 1, "", "Traceback: boom"))
    assert bad["total"] == 0 and bad["error"].startswith("the scorer gave no result (exit 1)")
    cmd = []
    T.score(Path("/c"), Path("/k"), run=lambda c, **kw: cmd.extend(c) or subprocess.CompletedProcess(c, 0, '{"cases": []}', ""))
    assert cmd[:6] == ["docker", "run", "--rm", "--network", "none", "--memory"] and "--read-only" in cmd and "/c:/code:ro" in cmd


def test_the_clean_room_audit_catches_forbidden_reads_and_actions_but_not_the_trial_s_own_names():
    t = T.load("semver")
    def hit(kind, text):
        return bool(T.audit(t, [("x", kind, text)])["forbidden"])
    for s in ("pip install semver", "pip install pytest semver==3.0", "import semver", "from semver import Version",
              "requests>=2\nsemver>=3\n", '"semver>=3.0"'):
        assert hit("action" if "\n" not in s else "code", s), s
    for s in ("pip install semverlib", "import semverlib", "pip install -e .", "python -m pytest", "semverlib.parse('1.0.0')"):
        assert not hit("action", s), s
    assert hit("url", "https://github.com/python-semver/python-semver/blob/master/src/semver/version.py")
    assert hit("url", "https://pypi.org/project/semver/") and not hit("url", "https://semver.org/") and not hit("url", "https://pypi.org/project/semverlib/")
    steps = json.dumps([{"kind": "call", "tool": "Bash", "text": '{"command": "pip download semver"}'},
                        {"kind": "result", "tool": "Bash", "text": "the brief said: do not use python-semver"}])
    assert T.tool_inputs(steps) == ['{"command": "pip download semver"}']                 # what it did, not what it was told
    stream = "\n".join([json.dumps({"type": "user", "message": {"content": [{"type": "text", "text": "never import semver"}]}}),
                        json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})])
    assert T.tool_inputs(stream) == ['{"command": "ls"}']


def test_similarity_tells_copied_code_from_independent_code(tmp_path):
    up, copy, own = tmp_path / "up", tmp_path / "copy", tmp_path / "own"
    for d in (up, copy, own):
        d.mkdir()
    src = textwrap.dedent('''
        def compare(left, right):
            for a, b in zip(left.split("."), right.split(".")):
                if a.isdigit() and b.isdigit():
                    if int(a) != int(b):
                        return -1 if int(a) < int(b) else 1
                elif a != b:
                    return -1 if a < b else 1
            return (len(left) > len(right)) - (len(left) < len(right))
        ''')
    (up / "v.py").write_text(src)
    (copy / "mine.py").write_text(src.replace("left", "x").replace("right", "y").replace("compare", "cmp_versions"))   # renamed
    (own / "mine.py").write_text("import re\n\nPATTERN = re.compile(r'^(\\d+)$')\n\n\nclass V:\n    def __init__(self, t):\n        self.t = t\n\n    def __str__(self):\n        return self.t\n")
    assert T.similarity(copy, up)["share"] > 0.9 and T.similarity(own, up)["share"] < 0.2


def test_a_trial_s_build_ends_at_review_and_is_never_merged_and_the_judge_scores_it_too():
    cd = (ROOT / "ops/conductor.py").read_text()
    assert 'if r and r["status"] == "review" and str(t.get("source") or "").startswith("trial:"):' in cd
    assert "t.source like 'trial:%'" in (ROOT / "ops/staffing.py").read_text()
    tr = (ROOT / "ops/trials.py").read_text()
    assert '{"action": "build_reject", "id": b["id"]}' in tr and '"action": "repo_remove"' in tr      # scored, archived, closed
    assert 'KEYS = Path("/srv/ai/private/trials")' in tr
    compose = "".join(p.read_text() for p in (ROOT / "compose").glob("*.yaml"))
    assert "/srv/ai/private" not in compose                                                          # no container reaches a key


def test_the_report_says_the_score_the_clean_room_and_how_it_went():
    t = T.load("semver")
    s = T.summarise({"cases": [{"id": "valid '1.0.0'", "area": "valid", "ok": True, "detail": ""},
                               {"id": "compare 1.0.0-1 1.0.0-a", "area": "precedence", "ok": False, "detail": "compare gave 1, want -1"}], "error": None})
    r = {"run": "semver-20261102-0100", "started_at": "2026-11-02 01:00", "task": 90, "repo": "trial-semver-20261102-0100", "dir": "/srv/ai/trials/runs/x",
         "over_budget": False, "asked": 1, "builds": [12], "build": {"id": 12, "status": "review", "branch": "b", "head": "h", "attempts": 2},
         "score": s, "audit": {"ok": False, "forbidden": [{"where": "build #12 (steps)", "pattern": "x", "excerpt": "pip install semver"}]},
         "similarity": {"share": 0.42, "files": []},
         "metrics": {"status": "done", "error": None, "verdict": "met", "minutes": 74, "steps": 2, "plan": ["1 scout: Read the spec (done)", "2 builder: Build it (done)"],
                     "calls": 40, "tokens": 120000, "builder_tokens": 900000}}
    md = T.report(t, r)
    assert "**1 of 2 answer-key cases passed (50%)**" in md and "| precedence | 0 of 1 |" in md and "compare gave 1, want -1" in md
    assert "**1 forbidden reads or actions:**" in md and "(**above 30%: look at it**)" in md and "judged met by the model judge" in md
    assert "Questions the intake asked (answered for the unattended trial): 1" in md and "#12 (review, 2 attempt(s))" in md
    r["score"] = T.summarise({"cases": [{"id": "a", "area": "x", "ok": True, "detail": ""}], "error": None})
    r["metrics"]["verdict"] = "not met"                                   # the second run: 351 of 351, the model said not met
    assert "judged not met by the model judge (**it disagrees with the answer key**)" in T.report(t, r)


def test_a_task_given_straight_to_the_builder_is_followed_through_its_build(tmp_path, monkeypatch):
    import sqlite3
    f = tmp_path / "m.sqlite"
    c = sqlite3.connect(f)
    c.executescript("""create table tasks (id integer primary key, status text, door text, ref text, questions text);
                       create table task_steps (task integer, occ integer, idx integer, resume text);
                       create table builds (id integer primary key, status text);
                       insert into tasks values (1, 'running', 'build', '7', '[]'), (2, 'running', 'plan', '2', '[]');
                       insert into task_steps values (2, 1, 1, '{"build": 9}');
                       insert into builds values (7, 'review'), (9, 'working');""")
    c.commit()
    monkeypatch.setattr(T, "DB", f)
    with T.db() as d:
        assert T.build_ids(d, 1) == [7] and T.build_ids(d, 2) == [9]
    import time
    row, asked, over = T.watch({"budget": {"hours": 1}}, 1, time.time(), poll=0)
    assert row["id"] == 1 and not over and asked == 0                     # its build at review is the delivery


def test_the_runner_s_answer_is_read_in_both_of_its_shapes(tmp_path, monkeypatch):
    """The first real run stopped here: the runner answers task_create with {"ok": true, "task": 88}, other actions
    with {"ok": true, "result": {...}}."""
    monkeypatch.setattr(T, "INBOX", tmp_path / "inbox")
    monkeypatch.setattr(T, "RESULTS", tmp_path / "results")
    (tmp_path / "inbox").mkdir()
    (tmp_path / "results").mkdir()
    import threading

    def answer(body):
        for _ in range(200):
            fs = list((tmp_path / "inbox").glob("trial*.json"))
            if fs:
                (tmp_path / "results" / fs[0].name).write_text(json.dumps(body))
                fs[0].unlink()
                return
            __import__("time").sleep(0.01)
    for body, want in (({"ok": True, "task": 88}, {"task": 88}), ({"ok": True, "result": {"build": 3}}, {"build": 3})):
        th = threading.Thread(target=answer, args=(body,))
        th.start()
        assert T.request({"action": "task_create"}, wait=5) == want
        th.join()


def test_the_scoreboard_holds_every_run_side_by_side_with_its_version(tmp_path):
    """TRL-09: each run's record becomes one row: score per area, clean room, similarity, time, tokens, the model
    judge's verdict and the code version, oldest first; a broken record is left out and named."""
    runs, out, said = tmp_path / "runs", tmp_path / "pub", []
    out.mkdir()
    for run, started, passed in (("semver-1", "2026-11-01 11:31", 0), ("semver-2", "2026-11-01 11:44", 351)):
        (runs / run).mkdir(parents=True)
        (runs / run / "result.json").write_text(json.dumps({
            "trial": "semver", "run": run, "started_at": started, "version": "abc1234", "task": 91, "asked": 0, "over_budget": False,
            "builds": [13], "build": {"attempts": 1}, "score": {"passed": passed, "total": 351, "areas": {"parse": [passed, 351]}},
            "audit": {"ok": True, "forbidden": []}, "similarity": {"share": 0.05},
            "metrics": {"minutes": 2, "tokens": 1000, "builder_tokens": 5000, "steps": 1, "verdict": "not met"}}))
    (out / "maps").mkdir()
    (out / "maps/91.1.json").write_text(json.dumps({"numbers": {"agents": 3, "parallel": 2, "read": 4, "cited": 2}}))
    (runs / "broken").mkdir()
    (runs / "broken/result.json").write_text("{")
    rows = T.publish(runs, out, log=said.append)
    d = json.loads((out / "trials.json").read_text())
    assert [r["run"] for r in d["runs"]] == ["semver-1", "semver-2"] and d["trials"]["semver"] and d["trials"]["mqtt-trace"]
    r = rows[1]
    assert (r["passed"], r["total"], r["clean"], r["version"], r["verdict"], r["report"]) == (351, 351, True, "abc1234", "not met", "trials/semver/semver-2.md")
    assert (r["agents"], r["parallel"], r["read"], r["cited"]) == (3, 2, 4, 2)      # the coordination numbers, from its map
    assert said and "broken" in said[0]


def test_the_trace_trial_gets_the_implementation_beside_its_specification():
    """T2 (TRL-12): the trace trial names its key, its code and its budget; its repository gets code/ beside spec/."""
    t = T.load("mqtt-trace")
    assert t["code"] is True and t["key"] == "mqtt-trace" and "trace.json" in t["task"] and t["_urls"][0].search("https://github.com/mochi-mqtt/server")
    own = T.load("stack-trace")
    assert own["code"] is True and own["key"] == "stack-trace" and own["_commands"][1].search("cat requirements/app.yaml")
    src = (ROOT / "ops/trials.py").read_text()
    assert 'if t.get("code"):' in src and 'shutil.copytree(key_dir(t) / "code", d / "code")' in src

