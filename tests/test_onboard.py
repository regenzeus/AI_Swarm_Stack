"""ops/onboard.py (BLD-26): onboarding always ends in the whole package or says why not. The owner's dsh-superagent-prototype,
177 source files, was refused in 2 seconds by a limit nobody asked for, and the app kept promising a message."""
import pysrc
import webjs
import itertools
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

import onboard as O
import repofacts as RF

ROOT =Path(__file__).resolve().parent.parent
SMALL = {"nodes": [{"id": "file:a.py", "type": "file", "name": "a.py", "filePath": "a.py", "summary": "A real explanation of this file."},
                   {"id": "function:a.py:f", "type": "function", "name": "f", "filePath": "a.py", "lineRange": [1, 2], "summary": "Does the one thing."}],
         "edges": [{"source": "file:a.py", "target": "function:a.py:f", "type": "contains"}]}
HOLLOW = {"nodes": [{"id": "file:a.py", "type": "file", "name": "a.py", "filePath": "a.py", "summary": "Auto-generated node for a.py"}], "edges": []}
GRAPH = {"nodes": [{"id": "a_f", "label": "f", "source_file": "a.py", "_callable": True, "community_name": "a"}, {"id": "a_g", "label": "g", "source_file": "a.py", "_callable": True, "community_name": "a"}],
         "links": [{"source": "a_f", "target": "a_g", "relation": "calls"}]}
ANALYSIS = "# analysis\n\n" + "".join(f"## Section {i}\n\n" + "words " * 120 + "\n\n" for i in range(4))


@pytest.fixture
def job(tmp_path, monkeypatch):
    """A job whose outside world is stubbed: what each step would run records itself in `ran`."""
    for attr, sub in (("CODE", "code"), ("STATE", "state"), ("DOCS", "docs"), ("LOGS", "logs"), ("GRAPHS", "graphs"), ("MISSIONS", "missions")):
        (tmp_path / sub).mkdir()
        monkeypatch.setattr(O, attr, tmp_path / sub)
    (tmp_path / "missions" / "inbox").mkdir()
    monkeypatch.setattr(RF, "DOCS", tmp_path / "docs")
    monkeypatch.setattr(RF, "STATE", tmp_path / "state" / "repofacts")
    ran, told = [], []
    monkeypatch.setattr(O, "pause", lambda s: ran.append(("pause", s)))
    monkeypatch.setattr(O, "tell", lambda st, text, key: told.append(text))
    monkeypatch.setenv("VK_CODE", "test-key")
    monkeypatch.setattr(O, "gateway", lambda: None)
    monkeypatch.setattr(O, "free_gb", lambda: 8.0)
    monkeypatch.setattr(O, "qmd_index", lambda: ran.append("qmd"))
    monkeypatch.setattr(O, "qmd_has", lambda doc: True)
    monkeypatch.setattr(O, "run_fix", lambda name: 0)
    for f in ("start", "end", "emit"):
        monkeypatch.setattr(O.RTM, f, lambda *a, **k: None)
    O._quality.clear()

    def repo(name="big"):
        d = O.CODE / name
        (d / ".git" / "info").mkdir(parents=True)
        (d / "graphify-out").mkdir()
        (d / "graphify-out" / "graph.json").write_text(json.dumps(GRAPH))
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
        O.write_doc(O.DOCS / f"{st['repo']}.analysis.md", ANALYSIS)
        return ""

    def fake_wiki(st):
        ran.append("wiki")
        (O.VAULT / "repos" / st["repo"] / "wiki").mkdir(parents=True, exist_ok=True)
        for page in ("conventions", "fragile-areas", "overview"):
            (O.VAULT / "repos" / st["repo"] / "wiki" / f"{page}.md").write_text("x")
        return ""

    def fake_search(st):
        ran.append("search")
        O.write_doc(O.DOCS / f"{st['repo']}.md", "digest")
        return ""

    def fake_facts(st):
        ran.append("facts")
        O.write_doc(RF.path(st["repo"]), json.dumps({"commit": "abc", "errors": []}))
        return ""

    monkeypatch.setattr(O, "run_map", fake_map)
    monkeypatch.setattr(O, "run_enrich", lambda name: ran.append("explain") or 0)
    monkeypatch.setitem(O.STEP_FN, "clone", fake_clone)
    monkeypatch.setitem(O.STEP_FN, "graph", lambda st: ran.append("graph") or "")
    monkeypatch.setitem(O.STEP_FN, "facts", fake_facts)
    monkeypatch.setitem(O.STEP_FN, "search", fake_search)
    monkeypatch.setitem(O.STEP_FN, "analysis", fake_analysis)
    monkeypatch.setitem(O.STEP_FN, "wiki", fake_wiki)
    monkeypatch.setattr(O, "VAULT", tmp_path / "vault")
    monkeypatch.setattr(O, "sh", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    return type("J", (), {"ran": ran, "told": told, "repo": staticmethod(repo)})


URL = "https://github.com/deepseek-ai/dsh-superagent-prototype"


def test_a_big_repository_gets_the_whole_package_and_one_message(job):
    d = job.repo("dsh-superagent-prototype")
    for i in range(300):                                     # far over the limit that used to refuse it
        (d / f"f{i}.ts").write_text("x")
    assert O.run("dsh-superagent-prototype") == 0
    assert [x for x in job.ran if isinstance(x, str)] == ["facts", "map0", "explain", "search", "analysis", "wiki"]   # its copy and graph are there
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
    st["steps"]["facts"]["status"] = "done"
    st["steps"]["map"]["status"] = "done"
    st["steps"]["explain"]["status"] = "running"
    O.kg_of("big").parent.mkdir(parents=True, exist_ok=True)
    O.kg_of("big").write_text(json.dumps(SMALL))
    O.save(st)
    assert O.run("big") == 0
    assert [x for x in job.ran if isinstance(x, str)] == ["explain", "search", "analysis", "wiki"]


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


def test_a_new_clone_has_its_whole_history_with_its_hooks_off(job, monkeypatch):
    monkeypatch.setitem(O.STEP_FN, "clone", O.step_clone)
    asked = []

    def clone(*a, **k):
        asked.append(a)
        (Path(a[-1]) / ".git").mkdir(parents=True)
        return subprocess.CompletedProcess(a, 0, "", "")

    monkeypatch.setattr(O, "sh", clone)
    O.step_clone({"repo": "tool", "url": "https://github.com/a/tool"})
    assert "--depth" not in asked[0] and "core.hooksPath=/dev/null" in asked[0]
    assert "--depth" not in (ROOT / "ops/onboard.py").read_text()


def test_the_facts_step_comes_after_the_graph_is_resumable_and_says_what_is_unknown(job, monkeypatch):
    assert [k for k, _ in O.STEPS][:3] == ["clone", "graph", "facts"]
    job.repo()
    monkeypatch.setitem(O.STEP_FN, "facts", O.step_facts)
    doc = {"commit": "abc", "commits": 3, "hotspots": [{"path": "a.py"}], "coupling": [], "ownership": [], "code_age": [], "health": {"sections": []},
           "errors": [{"tool": "repowise", "analysis": "health", "error": "exit 1: it fell over"}]}
    builds = []

    def build(name):
        builds.append(name)
        O.write_doc(RF.path(name), json.dumps(doc))
        RF._read.pop(name, None)
        return doc

    monkeypatch.setattr(RF, "build", build)
    assert O.run("big") == 0 and builds == ["big"]
    assert "Unknown: health: exit 1: it fell over" in O.load("big")["steps"]["facts"]["note"]
    assert "One gap" in job.told[-1] and "it fell over" in job.told[-1]        # the message says so
    o = O.status("big")
    facts = next(s for s in o["steps"] if s["id"] == "facts")
    assert o["status"] == "incomplete" and facts["state"] == "pending" and "it fell over" in facts["note"]   # the page offers to finish it
    assert O.package("big")["facts"] is False
    doc["errors"] = []
    O.write_doc(RF.path("big"), json.dumps(doc))
    RF._read.pop("big", None)
    assert O.package("big")["facts"] is True and O.status("big")["status"] == "done"
    builds.clear()
    assert O.begin("big", None, redo=True)["steps"]["facts"]["status"] == "pending"   # a package made anew makes them anew, the graph stays


def test_the_facts_wait_for_memory_and_only_no_result_at_all_is_a_failed_try(job, monkeypatch):
    job.repo()
    monkeypatch.setitem(O.STEP_FN, "facts", O.step_facts)
    st = O.begin("big", None)
    monkeypatch.setattr(O, "free_gb", lambda: 0.5)
    monkeypatch.setattr(RF, "build", lambda name: pytest.fail("no room for it"))
    with pytest.raises(O.Wait, match="waits for memory"):
        O.step_facts(st)
    monkeypatch.setattr(O, "free_gb", lambda: 8.0)
    monkeypatch.setattr(RF, "build", lambda name: {"hotspots": [], "coupling": [], "ownership": [], "code_age": [], "health": {"sections": []}, "errors": [{"tool": "codelore", "analysis": "hotspots", "error": "no image"}]})
    with pytest.raises(RuntimeError, match="neither tool could run.*no image"):
        O.step_facts(st)


def test_removing_a_repository_takes_its_facts(job):
    job.repo()
    O.write_doc(RF.path("big"), "{}")
    O.forget("big")
    assert not RF.path("big").exists()


def test_files_that_stay_unexplained_are_said_not_hidden(job, monkeypatch):
    job.repo()
    placeholder = {"nodes": [{"id": "file:a.py", "type": "file", "filePath": "a.py", "summary": "python code file in the big repository."},
                             {"id": "function:a.py:f", "type": "function", "name": "f", "filePath": "a.py", "lineRange": [1, 2], "summary": "Function defined in a.py."}],
                   "edges": [{"source": "file:a.py", "target": "function:a.py:f", "type": "contains"}]}

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
    app = webjs.app_js()
    assert 'id="ronboard"' in app and "function onboardHtml(r)" in app and 'route.name === "repo") return repoLive()' in app
    assert "function onbStep(s, live)" in app and 'data-onbstep="${esc(s.id)}"' in app and "ran ${rel(s.ended)}" in app and "${tok(s.tokens)} tokens" in app   # BLD-30: the checklist, always, with each step's record
    assert "if (!o) return \"\";" in app and 'o.status === "done" ? `All ${o.total} steps done${late}`' in app and "weak step" in app
    assert "const viewerUrl = () =>" in app and app.count("${HOSTURL}:8446/") == 1 and "http://${location.hostname}:5173/" in app   # BLD-32: the viewer off the tailnet
    assert 'data-ark="own" class="on"' in app and 'repo: v, kind }' in app                                                     # BLD-31: the repository's kind
    assert "/file?path=${encodeURIComponent(n.file)}" in app and "lines, its own ${nf(n.line || n.code.start)} to ${nf(n.code.end)} marked" in app   # the whole file, always (owner 9 Nov)
    assert '<mark class="rn-hl" id="rnhl">' in app and "data-rnmore" in app and "whole file</button>" not in app
    assert 'llm ? s.model : ""' in app                                                   # a deterministic step names no model
    css = (ROOT / "images/mission-control/web/static/app.css").read_text()
    assert ".rn-code pre.code { white-space: pre-wrap; overflow-wrap: anywhere;" in css
    assert 'id="ronbup"' in app and "update: true" in app and 'commit${s.behind === 1 ? "" : "s"} behind' in app and "behind the code</b>" in app and "made at ${esc(s.sha.slice(0, 7))}" in app   # Update, and how far behind
    for gone in ("your own work", "to evaluate</span>", "rstudy2", "you get a message when", "tap Build code map", "arrive in a few minutes", "No code map yet"):
        assert gone not in app
    server = pysrc.server()
    assert "The owner gets a message when the code map is ready" not in server and "onboard_line(r)" in server


def test_hermes_reads_why_it_stopped_in_repos_overview():
    src = pysrc.server()
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


def test_a_hollow_map_is_a_failed_try_and_the_map_runs_without_a_model(job, monkeypatch):
    """BLD-29, DEC-48: a map with nodes and no edges (what a shortcut leaves) fails its try with the reason; the map step
    runs ops/ua_map_in.py in a container with no network and no model, never an agent."""
    def hollow(name, attempt, log):
        job.ran.append(f"map{attempt}")
        O.kg_of(name).parent.mkdir(parents=True, exist_ok=True)
        O.kg_of(name).write_text(json.dumps(HOLLOW))
        log.write_text("log")
    monkeypatch.setattr(O, "run_map", hollow)
    assert O.run(URL) == 1
    st = O.load("dsh-superagent-prototype")
    assert st["status"] == "failed" and st["step"] == "map" and "map hollow: 1 nodes and no edges" in st["why"] and job.ran.count("map2") == 1
    src = Path(O.__file__).read_text().split("def run_map(name, attempt, log):")[1].split(chr(10) + "def ")[0]   # the real one, not this test's fake
    assert '"--network", "none"' in src and "/ua_map_in.py" in src and "opencode" not in src and "MAP_ANALYSE" not in src
    assert not O.map_quality("dsh-superagent-prototype")["ok"]
    q = O.map_quality("nope")
    assert q == {"ok": False, "text": "no code map", "n": {}}


def test_every_placeholder_form_is_known():
    """BLD-29: the explain step fills what the map or any plugin fallback left as a placeholder, in every form seen."""
    import ua_enrich as U
    for p in ("(not yet explained)", "Auto-generated node for src/Main.java", "python code file in the x repository.", "Function defined in a.py."):
        assert U.is_placeholder(p), p
    assert not U.is_placeholder("Parses the ECUC parameters of one module.")
    assert __import__("ua_map_in").PLACEHOLDER == "(not yet explained)"


def test_every_step_has_its_record_and_a_weak_step_is_never_done(job):
    """BLD-30: each step records when it ran, how long, its quality; a thin result after the fact makes the step weak and
    the package incomplete, with the reason on the page."""
    assert O.run(URL) == 0
    name = "dsh-superagent-prototype"
    st = O.load(name)
    for k, _ in O.STEPS:
        rec = st["steps"][k]
        assert rec["status"] == "done" and rec["ended"] and rec["seconds"] is not None and rec["quality"]["ok"], (k, rec)
    s = O.status(name)
    assert s["status"] == "done" and s["kind"] == "evaluate" and all(x["state"] == "done" and x["quality"] for x in s["steps"])
    assert next(x for x in s["steps"] if x["id"] == "map")["quality"] == "2 nodes · 1 edges · 1 symbols"
    assert next(x for x in s["steps"] if x["id"] == "explain")["model"] == "gpt-sub-fast"
    (O.DOCS / f"{name}.analysis.md").write_text("# too short\n\nnothing much")              # thin after the fact
    O._quality.clear()
    s = O.status(name)
    a = next(x for x in s["steps"] if x["id"] == "analysis")
    assert s["status"] == "incomplete" and a["state"] == "weak" and "too thin to work from" in a["quality"]
    assert O.package(name)["analysis"]                                                       # it exists; existing is not enough


def test_a_step_runs_again_on_its_own_from_the_checklist(job, monkeypatch):
    """BLD-30: Run again on a step does that step and the ones after it; a step no one knows is refused."""
    assert O.run(URL) == 0
    name = "dsh-superagent-prototype"
    st = O.begin(name, URL, "app", step="search")
    assert [k for k, _ in O.STEPS if st["steps"][k]["status"] == "pending"] == ["search", "analysis", "wiki", "card"]
    assert st["steps"]["map"]["status"] == "done" and st["steps"]["map"].get("quality")        # the earlier record stays
    monkeypatch.setattr(O, "unit_active", lambda n: False)
    with pytest.raises(ValueError):
        O.start(name, "app", step="nope")
    with pytest.raises(ValueError):
        O.start(name, "app", kind="mine")


def test_the_owner_s_own_repository_gets_the_engineer_s_guide_from_its_structure(job, monkeypatch):
    """BLD-31: the kind from the origin when not said (a forge or local origin is the owner's own, GitHub is to evaluate);
    the owner's own work is asked for the engineer's guide with the repository's packages as context."""
    assert O.kind_of("https://github.com/pallets/click") == "evaluate" and O.kind_of("https://forge.lan/owner/notes.git") == "own"
    assert O.kind_of("") == "own" and O.kind_of("https://desktop.example.ts.net/owner/x") == "own"
    asked = []
    monkeypatch.setattr(O, "submit", lambda req: asked.append(req) or {"ok": True, "id": 7})
    monkeypatch.setattr(O, "task_of", lambda tid: None)
    monkeypatch.setattr(O, "origin", lambda name: "https://forge.lan/owner/big.git")
    job.repo("big")
    st = O.begin("big", "https://forge.lan/owner/big.git", "app")
    assert st["kind"] == "own"
    with pytest.raises(O.Wait):
        O.step_analysis(st)
    assert "engineer's guide" in asked[-1]["question"] and "- (root): 1 files: f (a.py), g (a.py)" in asked[-1]["context"], asked[-1]["context"]
    st = O.begin("big", "https://forge.lan/owner/big.git", "app", kind="evaluate")
    st["task"] = None
    with pytest.raises(O.Wait):
        O.step_analysis(st)
    assert asked[-1]["question"].startswith("Onboard the repository big")


def test_update_redoes_the_steps_that_follow_the_code_and_run_again_really_runs(job, monkeypatch):
    """BLD-33, DEC-49: Update marks clone to search, the wiki's recheck and the card to be done again from the latest code while the analysis stays;
    Run again on the map really makes it again (the earlier map set aside for its unchanged explanations), never skips."""
    assert O.run(URL) == 0
    name = "dsh-superagent-prototype"
    st = O.begin(name, URL, "app", update=True)
    assert st["fresh"] == list(O.UPDATE_STEPS) and not st["redo"]
    assert [k for k, _ in O.STEPS if st["steps"][k]["status"] == "pending"] == [*O.CODE_STEPS, "wiki", "card"]
    assert st["steps"]["analysis"]["status"] == "done"
    st = O.begin(name, URL, "app", step="map")
    assert st["fresh"] == ["map", "explain", "search", "analysis", "wiki", "card"]
    before = job.ran.count("map0")
    monkeypatch.setattr(O, "kg_of", lambda n: O.CODE / n / ".ua" / "knowledge-graph.json")
    O.step_map(st)
    assert job.ran.count("map0") == before + 1                                                    # it ran, though the map was good


def test_every_step_says_its_commit_and_how_far_behind_the_code_is(job, monkeypatch):
    """BLD-33: a step records the commit it was made at; the checklist says how many commits the code has moved on since,
    and a step from before records is read from what it left (the map from its own commit and date)."""
    monkeypatch.setattr(O, "sh", lambda *a, **k: subprocess.run(a, capture_output=True, text=True))   # real git here
    d = O.CODE / "real"
    d.mkdir()
    g = lambda *a: subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout.strip()
    g("init", "-q")
    shas = []
    for i in range(3):
        (d / "a.py").write_text(f"x = {i}" + chr(10))
        g("add", "a.py")
        g("commit", "-q", "-m", f"c{i}")
        shas.append(g("rev-parse", "HEAD"))
    assert O.behind("real", shas[0][:12]) == 2 and O.behind("real", shas[2][:12]) == 0 and O.behind("real", None) is None
    (d / ".ua").mkdir()
    (d / ".ua" / "knowledge-graph.json").write_text(json.dumps({**SMALL, "project": {"gitCommitHash": shas[0], "analyzedAt": "2026-10-28T19:31:46Z"}}))
    monkeypatch.setattr(O, "kg_of", lambda n: O.CODE / n / ".ua" / "knowledge-graph.json")
    O._known.clear()
    row = O.step_row("map", "Code map", {}, "done", "real")
    assert row["sha"] == shas[0][:12] and row["behind"] == 2 and row["ended"] == "2026-10-28T19:31:46" and row["model"]
    assert O.behind_of([row, {"id": "analysis", "behind": 9}]) == 2                                 # the code-made steps say how far behind
    row = O.step_row("analysis", "Analysis", {"ended": "x", "model": "claude-code", "sha": shas[1][:12]}, "done", "real", kind="own")
    assert row["model"] == "Claude Code" and row["behind"] == 1 and row["quality"].startswith("a guide to your own code")


def test_a_claim_by_a_short_name_resolves_only_when_one_file_has_it_and_the_line_exists(job, monkeypatch):
    """BLD-30: the analysis' file:line claims are checked as a reader would follow them: a short name counts when exactly one
    file ends with it, never when two do, and the line must exist in that file."""
    d = job.repo("guide")
    for rel in ("app/app.py", "deploy/ops.sh", "a/util.py", "b/util.py"):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text("x" + chr(10) * 40)
    monkeypatch.setattr(O, "_files_of", lambda repo: ["app/app.py", "deploy/ops.sh", "a/util.py", "b/util.py"])
    assert O.claim_resolves(d, "app/app.py", 12) and O.claim_resolves(d, "app.py", 30) and O.claim_resolves(d, "ops.sh", 1)
    assert not O.claim_resolves(d, "util.py", 3)                  # two files end with it: ambiguous
    assert not O.claim_resolves(d, "app.py", 400)                 # no such line
    assert not O.claim_resolves(d, "missing.py", 1)


def test_a_job_with_only_the_card_left_does_not_wait_for_another_repository(job, monkeypatch):
    """Overnight exercise, 8 Nov 2026: TestRepo's card (no model, two seconds) queued behind ai-stack and sympy for hours."""
    assert O.run(URL) == 0
    name = "dsh-superagent-prototype"
    O.begin(name, URL, "app", step="card")
    monkeypatch.setattr(O, "take_turn", lambda st: (_ for _ in ()).throw(AssertionError("waited for a turn")))
    assert O.run(name) == 0 and O.load(name)["steps"]["card"]["status"] == "done"


def test_the_search_step_does_not_wait_for_embeddings():
    """Overnight exercise, 9 Nov 2026: embedding sympy's 4.4 MB digest outlasted the search step's 30 minutes twice."""
    src = Path(O.__file__).read_text().split("def qmd_index():", 1)[1].split("def qmd_has", 1)[0]
    assert 'sh("docker", "exec", QMD, "qmd", "update", timeout=QMD_TIMEOUT)' in src
    assert '"-d", QMD, "sh", "-c", "qmd embed' in src and "&& qmd embed" not in src


def test_the_guides_context_keeps_the_layers_when_the_package_list_is_cut(tmp_path, monkeypatch):
    """Overnight 9 Nov 2026: sympy's package list alone outgrew the guide's context, and the code map's layer descriptions,
    which came last, were cut off; the guide's writer said its list "was cut off after about 66 packages". The layers come
    first, and the cut says where every package is."""
    import json as _json
    import onboard as O
    monkeypatch.setattr(O, "CODE", tmp_path / "code")
    monkeypatch.setattr(O, "MODULES_CHARS", 400)
    g = {"nodes": [{"id": f"n{i}", "source_file": f"pkg{i}/sub/mod.py", "label": f"f{i}()", "_callable": True, "source_location": "L3"} for i in range(40)],
         "links": []}
    (tmp_path / "code/demo/graphify-out").mkdir(parents=True)
    (tmp_path / "code/demo/graphify-out/graph.json").write_text(_json.dumps(g))
    O.kg_of("demo").parent.mkdir(parents=True, exist_ok=True)
    O.kg_of("demo").write_text(_json.dumps({"layers": [{"name": "core", "description": "The expression trees everything builds on."}]}))
    text = O.modules_text("demo")
    assert text.startswith("# What the code map says about each layer\n- core: The expression trees everything builds on.")
    assert "more characters cut: the smaller packages; every one is in graphify-out/graph.json (40 packages)]" in text

