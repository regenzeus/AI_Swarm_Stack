"""ops/onboard.py (BLD-26): onboarding always ends in the whole package or says why not. The owner's dsh-superagent-prototype,
177 source files, was refused in 2 seconds by a limit nobody asked for, and the app kept promising a message."""
import itertools
import json
import re
import subprocess
from pathlib import Path

import pytest

import onboard as O

ROOT = Path(__file__).resolve().parent.parent
SMALL = {"nodes": [{"id": "f", "type": "file", "filePath": "a.py", "summary": "A real explanation of this file."}], "edges": []}


@pytest.fixture
def job(tmp_path, monkeypatch):
    """A job whose outside world is stubbed: what each step would run records itself in `ran`."""
    for attr, sub in (("CODE", "code"), ("STATE", "state"), ("DOCS", "docs"), ("LOGS", "logs"), ("GRAPHS", "graphs"), ("MISSIONS", "missions")):
        (tmp_path / sub).mkdir()
        monkeypatch.setattr(O, attr, tmp_path / sub)
    (tmp_path / "missions" / "inbox").mkdir()
    ran, told = [], []
    monkeypatch.setattr(O, "pause", lambda s: ran.append(("pause", s)))
    monkeypatch.setattr(O, "tell", lambda st, text, key: told.append(text))
    monkeypatch.setenv("VK_CODE", "test-key")
    monkeypatch.setattr(O, "gateway", lambda: None)
    monkeypatch.setattr(O, "free_gb", lambda: 8.0)
    monkeypatch.setattr(O, "qmd_index", lambda: ran.append("qmd"))
    monkeypatch.setattr(O, "qmd_has", lambda doc: True)
    monkeypatch.setattr(O, "run_fix", lambda name: 0)

    def repo(name="big"):
        d = O.CODE / name
        (d / ".git" / "info").mkdir(parents=True)
        (d / "graphify-out").mkdir()
        (d / "graphify-out" / "graph.json").write_text("{}")
        return d

    def fake_clone(st):
        ran.append("clone")
        if not (O.CODE / st["repo"]).exists():
            repo(st["repo"])
        return ""

    def fake_map(name, attempt, log):
        ran.append(f"map{attempt}")
        O.kg_of(name).parent.mkdir(parents=True, exist_ok=True)
        O.kg_of(name).write_text(json.dumps(SMALL))
        log.write_text("log")

    def fake_analysis(st):
        ran.append("analysis")
        O.write_doc(O.DOCS / f"{st['repo']}.analysis.md", "# analysis\n" + "x" * 300)
        return ""

    def fake_search(st):
        ran.append("search")
        O.write_doc(O.DOCS / f"{st['repo']}.md", "digest")
        return ""

    monkeypatch.setattr(O, "run_map", fake_map)
    monkeypatch.setattr(O, "run_enrich", lambda name: ran.append("explain") or 0)
    monkeypatch.setitem(O.STEP_FN, "clone", fake_clone)
    monkeypatch.setitem(O.STEP_FN, "graph", lambda st: ran.append("graph") or "")
    monkeypatch.setitem(O.STEP_FN, "search", fake_search)
    monkeypatch.setitem(O.STEP_FN, "analysis", fake_analysis)
    monkeypatch.setattr(O, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    return type("J", (), {"ran": ran, "told": told, "repo": staticmethod(repo)})


URL = "https://github.com/deepseek-ai/dsh-superagent-prototype"


def test_a_big_repository_gets_the_whole_package_and_one_message(job):
    d = job.repo("dsh-superagent-prototype")
    for i in range(300):                                     # far over the limit that used to refuse it
        (d / f"f{i}.ts").write_text("x")
    assert O.run("dsh-superagent-prototype") == 0
    assert [x for x in job.ran if isinstance(x, str)] == ["map0", "explain", "search", "analysis"]   # its copy and graph are there
    assert O.status("dsh-superagent-prototype")["status"] == "done"
    assert all(O.package("dsh-superagent-prototype").values())
    assert len(job.told) == 1 and "onboarded" in job.told[0] and "written analysis" in job.told[0]


def test_no_size_limit_is_left_anywhere_in_the_job():
    text = (ROOT / "ops/onboard.py").read_text()
    assert "MAX_FILES" not in text and "FORCE" not in text and "ls-files" not in text
    assert not (ROOT / "ops/understand.sh").exists()


def test_a_step_that_keeps_failing_stops_with_its_reason_and_says_so(job, monkeypatch):
    job.repo()

    def boom(name, attempt, log):
        job.ran.append(f"map{attempt}")
        log.write_text("the last words of the run")

    monkeypatch.setattr(O, "run_map", boom)
    assert O.run("big") == 1
    assert [x for x in job.ran if isinstance(x, str) and x.startswith("map")] == ["map0", "map1", "map2"]   # three tries, more memory after the first
    o = O.status("big")
    assert o["status"] == "failed" and o["step"] == "map" and "the last words of the run" in o["why"]
    assert len(job.told) == 1 and "stopped at" in job.told[0] and "Try again" in job.told[0]


def test_try_again_goes_on_from_the_step_that_failed(job, monkeypatch):
    job.repo()
    good = O.run_map

    def boom(name, attempt, log):
        log.write_text("no")

    monkeypatch.setattr(O, "run_map", boom)
    assert O.run("big") == 1
    job.ran.clear()
    monkeypatch.setattr(O, "run_map", good)
    monkeypatch.setattr(O, "launch", lambda name: job.ran.append("launched"))
    monkeypatch.setattr(O, "unit_active", lambda name: False)
    assert O.start("big")["already"] is False and "launched" in job.ran
    assert O.load("big")["steps"]["clone"]["status"] == "done" and O.load("big")["steps"]["map"]["status"] == "pending"
    assert O.run("big") == 0 and "clone" not in job.ran and O.status("big")["status"] == "done"


def test_a_usage_limit_waits_uses_no_try_and_goes_on_by_itself(job, monkeypatch):
    job.repo()
    good = O.run_map
    calls = {"probe": 0, "map": 0}

    def probe():
        calls["probe"] += 1
        return O.Wait("waits for the ChatGPT usage limit", tell=True) if calls["probe"] <= 5 else None

    def flaky(name, attempt, log):
        calls["map"] += 1
        assert attempt == 0                                  # waiting cost no try
        good(name, attempt, log)

    monkeypatch.setattr(O, "gateway", probe)
    monkeypatch.setattr(O, "run_map", flaky)
    assert O.run("big") == 0
    assert calls["map"] == 1 and O.status("big")["status"] == "done"
    assert any("usage limit" in t for t in job.told)         # told once it has to wait
    assert ("pause", O.POLL) in job.ran


def test_too_little_memory_waits_and_a_stopped_enrichment_is_no_failure(job, monkeypatch):
    job.repo()
    mem = iter([0.4, 0.4, 8.0])
    monkeypatch.setattr(O, "free_gb", lambda: next(mem, 8.0))
    good = O.run_map

    def looks(name, attempt, log):                           # seen on a phone, 6 Nov 2026: "waits for memory" while it ran
        st = O.load(name)
        assert st["status"] == "running" and "memory" not in st["steps"]["map"]["note"]
        good(name, attempt, log)

    monkeypatch.setattr(O, "run_map", looks)
    runs = iter([75, 0])
    monkeypatch.setattr(O, "run_enrich", lambda name: next(runs))
    assert O.run("big") == 0
    assert O.load("big")["attempts"] == {}


def test_a_crash_resumes_at_the_first_unfinished_step(job, monkeypatch):
    job.repo()
    st = O.begin("big", None)
    st.update(status="running", step="explain")
    st["steps"]["graph"]["status"] = "done"
    st["steps"]["map"]["status"] = "done"
    st["steps"]["explain"]["status"] = "running"
    O.kg_of("big").parent.mkdir(parents=True, exist_ok=True)
    O.kg_of("big").write_text(json.dumps(SMALL))
    O.save(st)
    assert O.run("big") == 0
    assert [x for x in job.ran if isinstance(x, str)] == ["explain", "search", "analysis"]


def test_the_watchdog_restarts_a_dead_job_and_gives_up_with_a_reason(job, monkeypatch):
    job.repo()
    st = O.begin("big", None)
    st.update(status="running", step="map")
    O.save(st)
    started = []
    monkeypatch.setattr(O, "unit_active", lambda name: False)
    monkeypatch.setattr(O, "launch", lambda name: started.append(name))
    O.tick()
    assert started == ["big"] and O.load("big")["restarts"] == 1
    for _ in range(O.RESTARTS):
        O.tick()
    assert O.status("big")["status"] == "failed" and "journalctl" in O.status("big")["why"]
    assert any("stopped at" in t for t in job.told)
    n = len(started)
    O.tick()                                                 # a stopped job stays stopped until the owner's Try again
    assert len(started) == n


def test_a_tap_while_it_runs_starts_nothing_more(job, monkeypatch):
    job.repo()
    st = O.begin("big", None)
    st.update(status="running", step="map")
    O.save(st)
    monkeypatch.setattr(O, "unit_active", lambda name: True)
    monkeypatch.setattr(O, "launch", lambda name: pytest.fail("a second job"))
    assert O.start("big")["already"] is True


def test_a_complete_package_is_made_anew_on_request_and_a_failed_redo_keeps_the_old_map(job, monkeypatch):
    job.repo()
    assert O.run("big") == 0
    job.ran.clear()
    monkeypatch.setattr(O, "launch", lambda name: None)
    monkeypatch.setattr(O, "unit_active", lambda name: False)
    O.start("big")
    st = O.load("big")
    assert st["redo"] is True and st["steps"]["graph"]["status"] == "done" and st["steps"]["analysis"]["status"] == "pending"
    monkeypatch.setattr(O, "run_map", lambda name, attempt, log: log.write_text("no"))
    assert O.run("big") == 1
    assert O.valid_map("big")                                # the last good map is back


def test_a_different_repository_of_the_same_name_is_refused_with_the_reason(job, monkeypatch):
    job.repo("tool")
    monkeypatch.setattr(O, "origin", lambda name: "https://github.com/someone/tool")
    with pytest.raises(ValueError, match="another repository called tool"):
        O.start("https://github.com/other/tool")
    st = O.begin("tool", "https://github.com/other/tool")
    monkeypatch.setitem(O.STEP_FN, "clone", O.step_clone)
    assert O.do_step(st, "clone") is False and "another repository" in O.status("tool")["why"]


def test_what_can_be_onboarded():
    assert O.parse(URL) == ("dsh-superagent-prototype", URL)
    assert O.parse("https://gitlab.com/group/sub/tool.git")[0] == "tool"
    for bad in ("http://github.com/a/b", "https://192.168.1.10:3000/a/b", "https://nas.local/a/b", "https://x.y." + "ts.net/a/b",
                "https://u:p" + "@github.com/a/b", "--upload-pack=x", "../etc", "no-such-repository"):
        with pytest.raises(ValueError):
            O.parse(bad)


def test_a_half_done_clone_never_looks_like_a_repository(job, monkeypatch):
    monkeypatch.setitem(O.STEP_FN, "clone", O.step_clone)

    def clone(*a, **k):
        tmp = Path(a[-1])
        (tmp / ".git").mkdir(parents=True)
        assert not (O.CODE / "tool").exists()
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(O, "sh", clone)
    O.step_clone({"repo": "tool", "url": "https://github.com/a/tool"})
    assert (O.CODE / "tool" / ".git").exists() and not (O.CODE / ".cloning" / "tool").exists()


def test_files_that_stay_unexplained_are_said_not_hidden(job, monkeypatch):
    job.repo()
    placeholder = {"nodes": [{"id": "f", "type": "file", "filePath": "a.py", "summary": "python code file in the big repository."}], "edges": []}

    def fake_map(name, attempt, log):
        O.kg_of(name).parent.mkdir(parents=True, exist_ok=True)
        O.kg_of(name).write_text(json.dumps(placeholder))
        log.write_text("log")

    monkeypatch.setattr(O, "run_map", fake_map)
    assert O.run("big") == 0
    assert "1 of 1 files" in O.load("big")["steps"]["explain"]["note"]
    assert "One gap" in job.told[-1] and "a.py" in job.told[-1]
    o = O.status("big")
    assert o["status"] == "incomplete" and "a.py" in next(s for s in o["steps"] if s["id"] == "explain")["note"]


def test_the_analysis_is_asked_once_survives_a_restart_and_is_saved(job, monkeypatch):
    job.repo()
    monkeypatch.setitem(O.STEP_FN, "analysis", O.step_analysis)
    monkeypatch.setattr(O, "origin", lambda name: "https://github.com/a/big")
    asked = []
    monkeypatch.setattr(O, "submit", lambda req: asked.append(req) or {"ok": True, "id": 7})
    (O.MISSIONS / "claude").mkdir()
    st = O.begin("big", None)
    with pytest.raises(O.Wait, match="reading the code"):
        O.step_analysis(st)
    assert asked[0]["mode"] == "study" and asked[0]["repo"] == "big" and "https://github.com/a/big" in asked[0]["question"]
    (O.MISSIONS / "claude" / "7.json").write_text(json.dumps({"status": "waiting"}))
    with pytest.raises(O.Wait, match="usage limit"):
        O.step_analysis(O.load("big"))
    (O.MISSIONS / "claude" / "7.json").write_text(json.dumps({"status": "done", "answer": "## What it is\n" + "real " * 100}))
    O.step_analysis(O.load("big"))
    assert len(asked) == 1
    text = (O.DOCS / "big.analysis.md").read_text()
    assert "## What it is" in text and "claude-task:7" in text


def test_the_study_mode_can_not_run_anything():
    import claude_tasks as CT
    tools = CT.MODES["study"]["tools"].split(",")
    assert "Bash" not in tools and not {"Edit", "Write"} & set(tools) and CT.MODES["study"]["turns"] == CT.MODES["analyse"]["turns"]


def test_the_app_shows_the_steps_and_promises_nothing_false():
    app = (ROOT / "images/mission-control/web/static/app.js").read_text()
    assert 'id="ronboard"' in app and "function onboardHtml(r)" in app and 'route.name === "repo") return repoLive()' in app
    for gone in ("rstudy2", "you get a message when", "tap Build code map", "arrive in a few minutes", "No code map yet"):
        assert gone not in app
    server = (ROOT / "images/mission-control/server.py").read_text()
    assert "The owner gets a message when the code map is ready" not in server and "onboard_line(r)" in server


def test_hermes_reads_why_it_stopped_in_repos_overview():
    src = (ROOT / "images/mission-control/server.py").read_text()
    fn = re.search(r"def onboard_line\(r\):.*?(?=\n\n\n)", src, re.S).group(0)
    scope = {}
    exec(fn, scope)
    step = {"id": "map", "title": "Code map", "state": "failed", "note": ""}
    assert "STOPPED at Code map: out of memory" in scope["onboard_line"]({"onboard": {"status": "failed", "step": "map", "steps": [step], "why": "out of memory"}})
    assert scope["onboard_line"]({"onboard": {"status": "done"}}) == "full package"
    assert "missing: Code map" in scope["onboard_line"]({"onboard": {"status": "incomplete", "steps": [step]}})
    live = {"status": "waiting", "step": "map", "index": 3, "total": 6, "steps": [{**step, "note": "waits for memory"}]}
    assert scope["onboard_line"]({"onboard": live}) == "onboarding: step 3 of 6 (Code map), waits for memory"


def test_removing_a_repository_takes_its_job_and_records(job, monkeypatch):
    job.repo()
    O.begin("big", None)
    (O.DOCS / "big.analysis.md").write_text("a")
    (O.LOGS / "ua-enrich-big.json").write_text("{}")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    O.forget("big")
    assert not O.path("big").exists() and not (O.DOCS / "big.analysis.md").exists() and not (O.LOGS / "ua-enrich-big.json").exists()


def test_a_long_wait_tells_the_owner_why(job, monkeypatch):
    job.repo()
    clock = itertools.count(0, 1000)
    monkeypatch.setattr(O.time, "time", lambda: next(clock))
    mem = iter([0.4] * 3 + [8.0])
    monkeypatch.setattr(O, "free_gb", lambda: next(mem, 8.0))
    assert O.run("big") == 0
    assert any("waits for memory" in t for t in job.told)


def test_a_new_address_is_copied_by_the_job_the_runner_starts_by_name(job, monkeypatch):
    """Seen in the first real queue, 6 Nov 2026: the unit runs with the name, and nothing is in ~/code yet."""
    monkeypatch.setattr(O, "launch", lambda name: job.ran.append(f"launch {name}"))
    monkeypatch.setattr(O, "unit_active", lambda name: False)
    assert O.start("https://github.com/octocat/Spoon-Knife")["repo"] == "Spoon-Knife"
    assert "launch Spoon-Knife" in job.ran and O.load("Spoon-Knife")["url"] == "https://github.com/octocat/Spoon-Knife"
    assert O.run("Spoon-Knife") == 0 and "clone" in job.ran and O.status("Spoon-Knife")["status"] == "done"


def test_a_repository_without_code_still_gets_the_whole_package(job, monkeypatch):
    """A page of HTML and CSS: the graph tool finds nothing to read, which was reported as a failure of the graph."""
    d = job.repo("page")
    (d / "graphify-out" / "graph.json").unlink()
    (O.GRAPHS / "page.head").write_text("abc\n")
    monkeypatch.setitem(O.STEP_FN, "graph", O.step_graph)
    monkeypatch.setattr(O, "graph_sync", lambda: (d / "graphify-out" / ".no-code").write_text(""))
    monkeypatch.setattr(O, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "abc\n", ""))
    assert O.run("page") == 0
    assert O.status("page")["status"] == "done" and "no code" in O.load("page")["steps"]["graph"]["note"]
    sync = (ROOT / "ops/graphify-sync.sh").read_text()
    assert 'grep -q "graph is empty"' in sync and ".no-code" in sync
