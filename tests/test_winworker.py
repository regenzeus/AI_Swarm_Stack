"""The Windows worker's protocol (GEN-11, docs/PLATFORM.md §6), run against ops/localworker.py so it needs no Windows: a
declared, approved job kind runs end to end, and every hostile or broken request is refused or recovered with its reason."""
import json
import subprocess
import time
from pathlib import Path

import pytest

import localworker as FW
import winjobs as WJ
import winworker as WW

ROOT = Path(__file__).resolve().parents[1]
APP = "def answer():\n    return 41\n"
RUN = ("import sys, pathlib\n"
       "sys.path.insert(0, str(pathlib.Path(__file__).parent / 'src'))\n"
       "import app\n"
       "ok = app.answer() == 42\n"
       "pathlib.Path('report.xml').write_text(f'<testsuite tests=\"1\" failures=\"{0 if ok else 1}\"/>')\n"
       "sys.exit(0 if ok else 1)\n")
KIND = {"kind": "demo.build", "about": "Apply a patch to a clean copy and run its check",
        "params": {"repo": {"type": "name", "from": "repos"}, "commit": {"type": "hex40"},
                   "patch": {"type": "file", "max_kb": 64}, "goal": {"type": "enum", "values": ["check", "full"]}},
        "patch_paths": {"allow": ["src/**"], "deny": ["**/pom.xml", "**/*.cmd"]},
        "steps": [["git", "clone", "--quiet", "{repos}/{repo}", "{scratch}/src"],
                  ["git", "-C", "{scratch}/src", "checkout", "--quiet", "--detach", "{commit}"],
                  ["git", "-C", "{scratch}/src", "apply", "--check", "{patch}"],
                  ["git", "-C", "{scratch}/src", "apply", "{patch}"],
                  ["python3", "src/run.py", "{goal}"]],
        "collect": ["src/src/report.xml", "report.xml"], "minutes": 5, "lock": "build", "retry": True}


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def diff(path, old, new):
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,2 +1,2 @@\n"
            + "".join(f"-{ln}\n" for ln in old.splitlines()) + "".join(f"+{ln}\n" for ln in new.splitlines()))


@pytest.fixture
def W(tmp_path, monkeypatch):
    root = tmp_path / "C_AIWorker"
    repo = root / "repos" / "demo"
    (repo / "src").mkdir(parents=True)
    (repo / "src/app.py").write_text(APP)
    (repo / "run.py").write_text(RUN)
    (repo / "pom.xml").write_text("<project/>\n")
    git("init", "-q", "-b", "main", cwd=repo)
    git("-c", "user.name=t", "-c", "user.email=test@example.com", "add", "-A", cwd=repo)
    git("-c", "user.name=t", "-c", "user.email=test@example.com", "commit", "-qm", "init", cwd=repo)
    commit = git("rev-parse", "HEAD", cwd=repo)
    (root / "jobs.d").mkdir()
    kind = dict(KIND, steps=[*KIND["steps"][:4], ["python3", "{scratch}/src/run.py", "{goal}"]])
    (root / "jobs.d/demo.build.json").write_text(json.dumps(kind))
    (root / "approved.json").write_text(json.dumps({"demo.build": WJ.digest(root / "jobs.d/demo.build.json")}))
    monkeypatch.setattr(WW, "REQUESTS", root / "inbox")
    monkeypatch.setattr(WW, "ANSWERS", root / "outbox")
    w = FW.Worker(root, beat_s=0.05)
    w.status()
    return type("W", (), {"root": root, "w": w, "commit": commit,
                          "values": {"repo": "demo", "commit": commit, "patch": "patch.diff", "goal": "check"},
                          "fix": diff("src/app.py", APP, APP.replace("41", "42"))})


def answer(W, rid):
    W.w.once()
    return WW.state(rid)


def test_a_declared_approved_job_runs_end_to_end_and_brings_its_evidence_back(W):
    rid = WW.submit("demo.build", W.values, files={"patch.diff": W.fix})
    st = answer(W, rid)
    assert st["status"] == "done", st
    assert [s["exit"] for s in st["steps"]] == [0, 0, 0, 0, 0] and "log.txt" in st["artifacts"]
    assert any(a.endswith("report.xml") for a in st["artifacts"])
    progress = (W.root / "outbox" / rid / "progress.jsonl").read_text().splitlines()
    assert len(progress) == 5 and json.loads(progress[-1])["step"] == 5
    assert not (W.root / "scratch" / rid).exists()                      # the scratch copy is gone; the repo is untouched
    assert (W.root / "repos/demo/src/app.py").read_text() == APP


def test_a_failing_build_is_a_failed_job_with_its_step(W):
    rid = WW.submit("demo.build", W.values, files={"patch.diff": diff("src/app.py", APP, APP.replace("41", "40"))})
    st = answer(W, rid)
    assert st["status"] == "failed" and "step 5" in st["error"] and "exited with 1" in st["error"]


def test_the_stack_refuses_at_once_what_windows_would_refuse(W, monkeypatch):
    with pytest.raises(WW.Refused, match="no job kind maven.deploy is declared"):
        WW.submit("maven.deploy", {})
    with pytest.raises(WW.Refused, match="no job kind's name"):
        WW.submit("demo.build; calc.exe", {})
    with pytest.raises(WW.Refused, match="no file name"):
        WW.submit("demo.build", W.values, files={"..\\x": "a"})
    (W.root / "outbox/status.json").write_text(json.dumps({"ts": time.time() - 3600, "kinds": {}}))
    with pytest.raises(WW.Refused, match="not answering"):
        WW.submit("demo.build", W.values)


@pytest.mark.parametrize("change,why", [
    ({"commit": "HEAD; rm -rf /"}, "a commit, 40 lowercase hex"),
    ({"goal": "deploy"}, "one of check, full"),
    ({"repo": "other"}, "one of the names in the worker's repos"),
    ({"patch": "../../secrets.txt"}, "a file name of the request's own folder"),
    ({"extra": "1"}, "values for no parameter: extra"),
])
def test_a_wrong_value_is_refused_by_the_worker_with_which_and_why(W, change, why):
    rid = WW.submit("demo.build", {**W.values, **change}, files={"patch.diff": W.fix})
    st = answer(W, rid)
    assert st["status"] == "refused" and why in st["error"], st
    assert not (W.root / "outbox" / rid / "claimed.json").exists()          # nothing ran


@pytest.mark.parametrize("patch,why", [
    (lambda W: diff("pom.xml", "<project/>", "<project><build/></project>"), "does not let a patch change"),
    (lambda W: diff("run.py", "x", "y"), "outside the paths this job kind allows"),
    (lambda W: "diff --git a/src/x b/src/x\nGIT binary patch\nliteral 1\n", "a binary patch"),
    (lambda W: "diff --git a/src/l b/src/l\nnew file mode 120000\n--- /dev/null\n+++ b/src/l\n@@ -0,0 +1 @@\n+/etc\n", "a symbolic link"),
    (lambda W: diff("src/../run.py", "x", "y"), "leaves the repository"),
])
def test_a_patch_outside_its_kinds_paths_is_refused_before_it_is_applied(W, patch, why):
    rid = WW.submit("demo.build", W.values, files={"patch.diff": patch(W)})
    st = answer(W, rid)
    assert st["status"] == "refused" and why in st["error"], st


def test_an_unapproved_or_changed_kind_does_not_run_even_when_asked_directly(W):
    kind_file = W.root / "jobs.d/demo.build.json"
    kind_file.write_text(kind_file.read_text().replace('"minutes": 5', '"minutes": 6'))     # edited after its approval
    W.w.status()
    with pytest.raises(WW.Refused, match="changed since its approval"):
        WW.submit("demo.build", W.values, files={"patch.diff": W.fix})
    rid = "a1b2c3d4e5f6"                                                    # the worker trusts nothing from WSL
    d = W.root / "inbox" / rid
    d.mkdir(parents=True)
    (d / "patch.diff").write_text(W.fix)
    (d / "request.json").write_text(json.dumps({"id": rid, "kind": "demo.build", "values": W.values, "at": int(time.time())}))
    st = answer(W, rid)
    assert st["status"] == "refused" and "changed since its approval" in st["error"]
    (W.root / "approved.json").write_text("{}")
    W.w.status()
    with pytest.raises(WW.Refused, match="not approved"):
        WW.submit("demo.build", W.values)


def test_a_lost_job_is_reported_and_one_whose_kind_may_retry_runs_once_more(W, monkeypatch):
    rid = "0123456789ab"
    out = W.root / "outbox" / rid
    out.mkdir(parents=True)
    (out / "claimed.json").write_text(json.dumps({"id": rid, "at": 1, "beat": time.time() - 120}))
    assert WW.state(rid)["status"] == "lost"
    waited = []
    st = WW.wait(rid, timeout=30, poll=0, retry_kind="demo.build", values=W.values, files={"patch.diff": W.fix},
                 sleep=lambda s: (waited.append(s), W.w.once()))
    assert st["status"] == "done" and st["id"] != rid                    # a new request, run once
    st = WW.wait(rid, timeout=30, poll=0, sleep=lambda s: None)
    assert st["status"] == "lost"                                         # without a retry it is reported


def test_a_job_past_its_time_limit_is_stopped(W):
    kind = json.loads((W.root / "jobs.d/demo.build.json").read_text())
    kind["steps"] = [["python3", "-c", "import time; time.sleep(30)"]]
    kind["params"] = {}
    kind.pop("patch_paths")
    kind["minutes"] = 1
    (W.root / "jobs.d/demo.build.json").write_text(json.dumps(kind))
    (W.root / "approved.json").write_text(json.dumps({"demo.build": WJ.digest(W.root / "jobs.d/demo.build.json")}))
    W.w.status()
    rid = WW.submit("demo.build", {})
    FW_minute = 60
    try:
        FW.Worker.MINUTE_S = 0.5
        st = answer(W, rid)
    finally:
        FW.Worker.MINUTE_S = FW_minute
    assert st["status"] == "failed" and "time limit" in st["error"], st


def test_a_kind_definition_that_is_unclear_is_not_valid():
    bad = dict(KIND, steps=[["mvn", "{goals}"]], minutes=0)
    bad.pop("patch_paths")
    said = "\n".join(WJ.kind_problems(bad))
    assert "{goals} is no parameter" in said and "minutes" in said and "says which paths it may change" in said
    assert WJ.kind_problems(KIND) == []


def test_the_stack_side_can_start_nothing_on_windows():
    src = (ROOT / "ops/winworker.py").read_text()
    assert "import subprocess" not in src and "import socket" not in src and "powershell" not in src.lower()


def test_a_where_windows_step_runs_end_to_end_and_a_step_kind_says_where_it_runs(W):
    import threading
    import stepkinds as SK
    run = WW.step_kind("demo.build", lambda t, s: W.values, lambda t, s: {"patch.diff": W.fix}, minutes=2)
    tables = SK.load([type("demo", (), {"STEP_KINDS": {"demo-build": {"run": run, "where": "windows"}}, "__name__": "demo"})])
    assert tables.where == {"demo-build": "windows"} and "demo-build" not in tables.need_gb
    stop = threading.Event()
    threading.Thread(target=lambda: [W.w.once() or stop.wait(0.05) for _ in iter(lambda: stop.is_set(), True)], daemon=True).start()
    try:
        said = tables.adapters["demo-build"](None, {}, {}, "", {})
    finally:
        stop.set()
    assert "passed its 5 steps" in said and "untrusted output" in said
    for bad, why in (({"where": "elsewhere"}, "one of wsl, windows"), ({"where": "windows", "gb": 2}, "needs_gb there")):
        with pytest.raises(ValueError, match=why):
            SK.load([type("d", (), {"STEP_KINDS": {"x": {"run": run, **bad}}, "__name__": "d"})])


def test_the_worker_is_a_feature_a_deployment_switches_on(W, monkeypatch):
    import deployment as DEPLOY
    monkeypatch.setattr(DEPLOY, "ON", {"core"})
    with pytest.raises(WW.Refused, match="not configured: the feature windows-worker is off"):
        WW.submit("demo.build", W.values)
