"""WFL-05: the step service. n8n posts a step; the app drops it for the runner; the runner checks it, runs it through the
Conductor's own step runner on a row of its own (same adapters, attempts, record) or a crew job as its unit, and posts the
answer to the waiting n8n execution, keeping the request until n8n has taken it, so a restart loses nothing.
WFL-06: the palette's other blocks (a coding change, recall, remember, a command at a place, a plan in waves) run
through the stack's own code, and the node's pickers read the lists the runner writes."""
import json
import threading
import time
import types
from pathlib import Path

import pytest

import conductor as CD
import localworker as LW
import flows as FW
import tasks as TK
from domain import places as PL

ROOT = Path(__file__).resolve().parents[1]
RESUME = "https://pc.example.ts.net:8450/webhook-waiting/731/ab12"
CARDS = {"scout": {"id": "scout", "harness": "hermes", "prompt": "You find facts."}, "desk": {"id": "desk", "harness": "hermes"}}
CREW = {"memory": {"id": "memory", "unit": "crew-memory"}, "self-review": {"id": "self-review", "thread": "improve"}}
JOB = ROOT / "tests/fixtures/packs/toy/jobs/reproduce.json"
SPEC = json.loads(JOB.read_text())


class Resp:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def took(ok=True):
    sent = []

    def post(req, timeout=30):
        sent.append((req.full_url, json.loads(req.data)))
        if not ok:
            raise OSError("n8n is restarting")
        return Resp()
    return post, sent


@pytest.fixture
def F(K, tmp_path, monkeypatch):
    monkeypatch.setattr(FW, "PENDING", tmp_path / "flows/pending")
    monkeypatch.setattr(FW, "DONE", tmp_path / "flows/done")
    monkeypatch.setattr(__import__("runreg"), "ROOT", tmp_path / "flows/register")
    FW.PENDING.mkdir(parents=True)
    told = []
    FW.M = types.SimpleNamespace(db=K.conn, stop=CD.M.stop, log=print, notify=lambda text, *a: told.append(text))
    K.told = told
    return K


def drop(rid, **req):
    p = FW.PENDING / f"{rid}.json"
    p.write_text(json.dumps(req))
    return p


def test_a_request_is_checked_before_anything_runs():
    ok = {"kind": "agent", "agent": "scout", "brief": "Find three facts.", "resume_url": RESUME}
    assert FW.validate(ok, CARDS, CREW) == ""
    assert "kind" in FW.validate({**ok, "kind": "shell"}, CARDS, CREW)
    assert "no agent" in FW.validate({**ok, "agent": "root"}, CARDS, CREW)
    assert "brief" in FW.validate({**ok, "brief": " "}, CARDS, CREW)
    assert "limit" in FW.validate({**ok, "brief": "x" * (FW.BRIEF_MAX + 1)}, CARDS, CREW)
    assert "no crew job" in FW.validate({"kind": "crew", "job": "rm"}, CARDS, CREW)
    assert "resume_url" in FW.validate({**ok, "resume_url": "http://169.254.169.254/latest/meta-data"}, CARDS, CREW)


def test_the_answer_only_ever_goes_to_n8n_on_this_machine():
    assert FW.resume_target(RESUME) == "http://127.0.0.1:5678/webhook-waiting/731/ab12"
    signed = "https://pc.example.ts.net:8450/webhook-waiting/1?signature=" + "a" * 64       # n8n 2.x signs its resume URLs
    assert FW.resume_target(signed) == "http://127.0.0.1:5678/webhook-waiting/1?signature=" + "a" * 64
    assert FW.resume_target("https://x/webhook-waiting/1?signature=zz&next=http://evil") == ""
    assert FW.resume_target("http://n8n:5678/webhook-waiting/12") == "http://127.0.0.1:5678/webhook-waiting/12"
    for bad in ("http://evil.example/webhook-waiting/1/../../admin", "file:///etc/passwd", "https://x/webhook/1",
                "https://x/webhook-waiting/1?redirect=http://evil", "ftp://x/webhook-waiting/1"):
        assert FW.resume_target(bad) == ""


def test_an_agent_step_runs_through_the_conductors_own_runner_and_n8n_gets_the_answer(F):
    p = drop("a1", kind="agent", agent="scout", brief="Find three facts about RAM.", title="RAM facts", workflow="W1",
             execution="731", resume_url=RESUME)
    post, sent = took()
    FW.handle("a1", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert not p.exists() and (FW.DONE / "a1.json").exists()
    url, answer = sent[0]
    assert url == "http://127.0.0.1:5678/webhook-waiting/731/ab12"
    assert answer["status"] == "done" and answer["output"] == "result of step 1" and answer["agent"] == "scout"
    t = TK.row(F.c, answer["task"])
    assert (t["door"], t["kind"], t["ref"], t["status"]) == ("workflow", "workflow", "n8n:W1/731", "done")
    row = CD.steps(F.c, answer["task"], 1)[0]
    assert row["harness"] == "hermes" and "You find facts." in row["why"] and "Find three facts about RAM." in row["why"]
    assert TK.owner_of(F.c, t["source"], t["door"]) == "stack"


def test_an_answer_n8n_did_not_take_is_sent_again_after_a_restart_without_running_the_step_again(F):
    p = drop("a2", kind="agent", agent="scout", brief="Find facts.", resume_url=RESUME)
    post, sent = took(ok=False)

    def away_then_stop(req, timeout=30):                    # n8n is away, and the runner stops meanwhile
        FW.M.stop.set()
        return post(req, timeout)
    FW.handle("a2", p, cards=CARDS, crew=CREW, post=away_then_stop, sleep=lambda s: None)
    assert p.exists() and len(F.ran) == 1                    # kept pending; the step ran once
    FW.M.stop.clear()
    post2, sent2 = took()
    FW.handle("a2", p, cards=CARDS, crew=CREW, post=post2, sleep=lambda s: None)
    assert not p.exists() and len(F.ran) == 1 and sent2[0][1]["status"] == "done"


def test_a_state_file_write_cut_short_leaves_the_old_file_or_none(tmp_path, monkeypatch):
    import statefile as SF
    old = tmp_path / "done/a.json"
    SF.save(old, {"status": "done", "output": "the old answer"})
    assert oct(old.stat().st_mode & 0o777) == "0o644"                       # the app (another uid) reads the answers

    def killed(fd):                                                          # the runner dies after a part of the text
        raise KeyboardInterrupt("killed by a deploy")
    monkeypatch.setattr(SF.os, "fsync", killed)
    for path in (old, tmp_path / "done/b.json"):
        with pytest.raises(KeyboardInterrupt):
            SF.save(path, {"status": "done", "output": "x" * 100000})
    assert json.loads(old.read_text())["output"] == "the old answer"         # the old file, whole
    assert not (tmp_path / "done/b.json").exists()                          # or none
    assert sorted(f.name for f in (tmp_path / "done").iterdir()) == ["a.json"]   # and no temp file left behind
    (tmp_path / "empty.json").write_text("")
    (tmp_path / "cut.json").write_text('{"status": "do')
    assert SF.load(tmp_path / "empty.json") is None and SF.load(tmp_path / "cut.json", {}) == {} and SF.load(tmp_path / "none.json") is None


def test_an_empty_answer_file_is_handled_again_and_answered(F):
    logged = []
    FW.M.log = logged.append
    p = drop("e1", kind="agent", agent="scout", brief="Find facts.", resume_url=RESUME)
    FW.DONE.mkdir(parents=True)
    (FW.DONE / "e1.json").write_text("")                                    # left by a write a restart cut short
    post, sent = took()
    FW.handle("e1", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert not p.exists() and len(F.ran) == 1 and sent[0][1]["status"] == "done"
    assert json.loads((FW.DONE / "e1.json").read_text())["status"] == "done"
    assert len([x for x in logged if "e1" in x and "empty or unreadable" in x]) == 1     # said once


def test_a_step_that_fails_twice_answers_failed_with_its_reason(F, monkeypatch):
    def broken(c, t, s, prompt, card):
        raise RuntimeError("the page did not load")
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": broken})
    p = drop("a3", kind="agent", agent="scout", brief="Find facts.", resume_url=RESUME)
    post, sent = took()
    FW.handle("a3", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    answer = sent[0][1]
    assert answer["status"] == "failed" and "the page did not load" in answer["error"]
    assert TK.row(F.c, answer["task"])["status"] == "failed"


def test_a_refused_request_runs_nothing_and_says_why(F):
    p = drop("a4", kind="agent", agent="root", brief="x", resume_url=RESUME)
    post, sent = took()
    FW.handle("a4", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert sent[0][1] == {"status": "refused", "error": "no agent 'root'"} and F.ran == []


def test_a_crew_job_runs_as_its_own_unit_and_waits_for_it(tmp_path):
    calls = []

    def run(cmd, **k):
        calls.append(cmd)
        return types.SimpleNamespace(returncode=0 if "start" in cmd else 3, stdout="inactive\n" if "is-active" in cmd else "", stderr="")
    out = FW.run_crew("memory", CREW, run=run)
    assert calls == [["systemctl", "--user", "is-active", "crew-memory.service"], ["systemctl", "--user", "start", "--wait", "crew-memory.service"]]
    assert out["status"] == "done"
    out = FW.run_crew("memory", CREW, run=lambda cmd, **k: types.SimpleNamespace(returncode=3, stdout="", stderr="boom"))
    assert out["status"] == "failed" and out["error"] == "boom"


def test_a_crew_job_still_running_covers_the_next_run_at_once(tmp_path):
    """A job that outlasts its schedule's spacing (the code graph every minute) is never started a second time and its
    n8n runs do not pile up waiting: the next one answers at once that the run in progress covers it."""
    for state in ("activating", "active"):
        calls = []
        run = lambda cmd, **k: calls.append(cmd) or types.SimpleNamespace(returncode=0, stdout=state + "\n", stderr="")
        out = FW.run_crew("memory", CREW, run=run)
        assert out == {"status": "done", "output": "already running: this run is covered by the one in progress", "crew": {}}
        assert calls == [["systemctl", "--user", "is-active", "crew-memory.service"]]               # nothing started, nothing waited for


def test_the_runner_starts_the_step_worker_and_the_app_serves_the_step_port_on_its_own_network():
    root = Path(__file__).resolve().parents[1]
    src = (root / "ops/missions.py").read_text()
    assert "import flows as FW" in src and "FW.start(sys.modules[__name__])" in src
    server = (root / "images/mission-control/server.py").read_text()
    assert '_part("server.flows.py")' in server and "port=8099" in server
    import yaml
    apps = yaml.safe_load((root / "compose/apps.yaml").read_text())["services"]
    core = yaml.safe_load((root / "compose/core.yaml").read_text())
    assert "stepnet" in apps["mission-control"]["networks"] and "stepnet" in core["services"]["n8n"]["networks"]
    assert core["networks"]["stepnet"].get("internal") is True
    assert not any("8099" in p for p in apps["mission-control"].get("ports", []))


def test_the_step_port_drops_a_step_for_the_runner_and_answers_what_is_known(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    import server as S
    monkeypatch.setattr(S, "FLOWS", tmp_path)
    cl = TestClient(S.flows_app, base_url="http://mission-control:8099")
    r = cl.post("/steps", json={"kind": "agent", "agent": "scout", "brief": "Find facts.", "resume_url": RESUME}).json()
    assert r["ok"] and r["status"] == "pending"
    assert json.loads((tmp_path / "pending" / f"{r['id']}.json").read_text())["agent"] == "scout"
    assert cl.get(f"/steps/{r['id']}").json()["status"] == "pending"
    (tmp_path / "done").mkdir()
    (tmp_path / "done" / f"{r['id']}.json").write_text(json.dumps({"status": "done", "output": "three facts"}))
    assert cl.get(f"/steps/{r['id']}").json()["output"] == "three facts"
    assert cl.post("/steps", json={"brief": "x" * 40000}).status_code == 400
    assert TestClient(S.flows_app, base_url="http://evil.example").post("/steps", json={}).status_code == 400


def test_home_hears_how_each_step_of_a_workflow_ended(F):
    said = []
    FW.M.event = lambda kind, slug="", text="", push=False, title="", **k: said.append((kind, text, push, title))
    p = drop("a9", kind="agent", agent="scout", brief="Find facts.", title="RAM facts", execution="731", resume_url=RESUME)
    post, sent = took()
    FW.handle("a9", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert said == [("workflow", "RAM facts: done (n8n run 731)", False, "Workflows")]
    said.clear()
    p = drop("b9", kind="agent", agent="root", brief="x", resume_url=RESUME)
    FW.handle("b9", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert said == [("workflow", "root: refused: no agent 'root'", True, "Workflows")]      # a failure is pushed to the owner


def test_an_agent_reads_its_brief_as_its_step(F, monkeypatch):
    seen = []
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": lambda c, t, s, prompt, card: seen.append(str(prompt)) or "ready"})
    p = drop("a5", kind="agent", agent="scout", brief="Answer with exactly one word: ready", title="Stack self-test", resume_url=RESUME)
    post, sent = took()
    FW.handle("a5", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert "The task: Stack self-test" in seen[0] and "Your step (1 of 1): Stack self-test: Answer with exactly one word: ready" in seen[0]
    assert sent[0][1]["output"] == "ready"
    t = TK.row(F.c, sent[0][1]["task"])
    assert t["status"] == "done" and CD.occurrences(F.c, t["id"])[0]["status"] == "done"


def test_the_new_kinds_are_checked_before_anything_runs():
    v = lambda **r: FW.validate({**r, "resume_url": RESUME}, CARDS, CREW, repos=["ai-stack"])   # noqa: E731
    assert v(kind="build", repo="ai-stack", brief="Add a dark mode toggle.") == ""
    assert "no repository 'secret'" in v(kind="build", repo="secret", brief="Add a dark mode toggle.")
    assert "brief" in v(kind="build", repo="ai-stack", brief=" ")
    assert v(kind="recall", query="RAM prices") == "" and "at most 500" in v(kind="recall", query="x" * 501)
    assert v(kind="remember", note="lesson", text="Check the board's slots first.", evidence="build #12") == ""
    assert "one of lesson" in v(kind="remember", note="owner", text="The owner likes tea.", evidence="chat")
    assert "at most 2,000" in v(kind="remember", note="fact", text="x" * 2001, evidence="a page")
    assert v(kind="command", place="wsl-host", command="toy.reproduce", values={"input": "small"}) == ""
    assert "place must be" in v(kind="command", place="the-nas", command="toy.reproduce")
    assert "job kind" in v(kind="command", place="wsl", command="rm -rf /")
    assert "no crew job 'self-review'" in v(kind="crew", job="self-review")                 # a crew job without a unit of its own
    ok = [{"agent": "scout", "brief": "Find prices."}, {"agent": "desk", "brief": "Sum up.", "after": [1]}]
    assert v(kind="plan", steps=ok) == ""
    assert "cycle" in v(kind="plan", steps=[{**ok[0], "after": [2]}, ok[1]])
    assert "step 2 waits for a step" in v(kind="plan", steps=[ok[0], {**ok[1], "after": [3]}])
    assert "step 1: no agent 'root'" in v(kind="plan", steps=[{**ok[0], "agent": "root"}])
    assert "1 to 12 steps" in v(kind="plan", steps=ok * 7) and "1 to 12 steps" in v(kind="plan", steps=[])


def test_a_coding_change_runs_as_the_conductors_build_step_and_answers_with_its_build(F, monkeypatch):
    import builds as B
    F.c.execute("create table builds (id integer primary key, status text, summary text, error text, branch text, pr text, ci text, checks text)")
    F.c.commit()
    asked = []
    monkeypatch.setattr(B, "handle", lambda req, c: asked.append(req) or {
        "id": c.execute("insert into builds (status, branch) values ('working', 'builder/1-dark-mode')").lastrowid})
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "build": CD.run_build})

    def meanwhile(s):                                       # the builder works; the checks pass; the owner approves; it merges
        c = F.conn()
        c.execute("update builds set status='merged', summary='Dark mode toggle in Settings', pr='https://forge.example/pr/7', ci='success', "
                  "checks='12 passed\nALL CHECKS PASSED\nchecks exit 0'")
        c.commit()
    p = drop("b1", kind="build", repo="ai-stack", brief="Add a dark mode toggle to Settings.", title="Dark mode", resume_url=RESUME)
    post, sent = took()
    FW.handle("b1", p, cards=CARDS, crew=CREW, post=post, sleep=meanwhile, repos=["ai-stack"])
    assert len(asked) == 1 and asked[0]["repo"] == "ai-stack" and "Dark mode: Add a dark mode toggle to Settings." in asked[0]["description"]
    a = sent[0][1]
    assert (a["status"], a["build"], a["state"], a["branch"], a["pr"], a["ci"]) == ("done", 1, "merged", "builder/1-dark-mode", "https://forge.example/pr/7", "success")
    assert "ALL CHECKS PASSED" in a["checks"] and "Build #1 merged" in a["output"]
    assert CD.steps(F.c, a["task"], 1)[0]["harness"] == "build" and TK.row(F.c, a["task"])["spec"]["repo"] == "ai-stack"


def test_a_memory_search_answers_with_its_hits_each_cut(F, monkeypatch):
    import memstack as MS
    asked = []
    monkeypatch.setattr(MS, "search", lambda q, scope="", access="all", agent="", n=12: asked.append((q, scope, access)) or (
        "### world:ram\n- RAM prices (vault:wiki/ram.md): " + "x" * 900 + "\n- DDR5 (vault:wiki/ddr5.md): faster\n\n"
        "### howto:skills\n- Buying RAM (skill:buy-ram): check the board first"))
    p = drop("m1", kind="recall", query="RAM prices", scope="world", resume_url=RESUME)
    post, sent = took()
    FW.handle("m1", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    a = sent[0][1]
    assert asked == [("RAM prices", "world", "all")] and a["status"] == "done"
    assert [h["collection"] for h in a["hits"]] == ["world:ram", "world:ram", "howto:skills"]
    assert len(a["hits"][0]["hit"]) < 500 and "more characters cut: memory open gives the entry whole" in a["hits"][0]["hit"]
    assert a["hits"][2]["hit"] == "Buying RAM (skill:buy-ram): check the board first"
    monkeypatch.setattr(MS, "search", lambda *a, **k: "Nothing in memory matches.")
    p = drop("m2", kind="recall", query="unicorns", resume_url=RESUME)
    FW.handle("m2", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert sent[1][1] == {"status": "done", "hits": [], "said": "Nothing in memory matches."}


def test_a_note_enters_memory_only_through_the_memory_tools_gate(F, monkeypatch):
    import memstack as MS
    import memwrite as MW
    gated = []
    monkeypatch.setattr(MS, "current_run", lambda agent: None)
    monkeypatch.setattr(MW, "reconcile", lambda c, ask=None: gated.append(c) or (
        {"id": "W-1", "outcome": "add", "where": "howto/lessons/research.md"} if c["kind"] == "lesson" else
        {"id": "W-2", "outcome": "reject", "why": "it restates the page"}))
    p = drop("n1", kind="remember", note="lesson", text="Check the board's slots before buying RAM.", evidence="build #12",
             agent="scout", resume_url=RESUME)
    post, sent = took()
    FW.handle("n1", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert sent[0][1] == {"status": "done", "kept": True, "said": "Kept: howto/lessons/research.md [W-1]"}
    assert (gated[0]["kind"], gated[0]["agent"], gated[0]["source"]) == ("lesson", "scout", "note")
    p = drop("n2", kind="remember", note="fact", text="DDR5 prices fell this week.", evidence="a shop page", resume_url=RESUME)
    FW.handle("n2", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    assert sent[1][1]["kept"] is False and sent[1][1]["said"].startswith("Not kept") and gated[1]["agent"] == "n8n"


@pytest.fixture
def host(tmp_path, monkeypatch):
    """The wsl-host place: a worker of the protocol over its own root, in a thread, with the toy job kind copied there."""
    root = tmp_path / "wslhost"
    for d in ("inbox", "outbox", "jobs.d", "repos", "scratch"):
        (root / d).mkdir(parents=True)
    (tmp_path / "places.yaml").write_text(f"places:\n  wsl-host: {{root: {root}, user: aiworker}}\n")
    monkeypatch.setenv("AISTACK_PLACES", str(tmp_path / "places.yaml"))
    monkeypatch.setenv("AISTACK_PLACE_ROOT", str(tmp_path / "places"))
    monkeypatch.setattr(FW, "JOBS", tmp_path / "flows/jobs")
    monkeypatch.setattr(FW, "_job_spec", lambda kind: SPEC if kind == SPEC["kind"] else None)
    PL.sync_jobs([{"name": "toy", "jobs": [{"kind": SPEC["kind"], "file": str(JOB), "sha256": __import__("winjobs").digest(JOB), "spec": SPEC}]}])
    stop = threading.Event()
    w = LW.Worker(root, beat_s=1)

    def loop():
        while not stop.is_set():
            if not w.once():
                stop.wait(0.1)
    threading.Thread(target=loop, daemon=True).start()
    yield root
    stop.set()


def seen_by_worker(name, want):
    for _ in range(100):
        k = ((PL.place(name).status() or {}).get("kinds") or {}).get(SPEC["kind"])
        if k and want(k):
            return
        time.sleep(0.05)
    raise AssertionError(f"the worker never said {SPEC['kind']} is there")


def approve_at_wsl_host():
    act = next(d for d in PL.decisions(lambda *a, **k: {"what": a[2], **k}) if d["what"].endswith("at wsl-host?"))["answers"][0]["act"]
    assert PL.handle(act)["ok"]                                                      # the owner's tap in Needs you
    seen_by_worker("wsl-host", lambda k: k.get("approved"))


def test_a_command_runs_at_its_place_only_once_approved_there_and_is_submitted_once(F, host):
    seen_by_worker("wsl-host", lambda k: True)
    post, sent = took()
    nap = lambda s: time.sleep(0.05)   # noqa: E731
    p = drop("c1", kind="command", place="wsl-host", command="toy.reproduce", values={"input": "small"}, resume_url=RESUME)
    FW.handle("c1", p, cards=CARDS, crew=CREW, post=post, sleep=nap)
    assert sent[0][1] == {"status": "refused", "error": "the job kind toy.reproduce is not approved at wsl-host: the owner approves it in Needs you"}
    approve_at_wsl_host()
    p = drop("c2", kind="command", place="wsl-host", command="toy.reproduce", values={"input": "huge"}, resume_url=RESUME)
    FW.handle("c2", p, cards=CARDS, crew=CREW, post=post, sleep=nap)
    assert sent[1][1]["status"] == "refused" and "input" in sent[1][1]["error"]     # outside its type: refused before the request
    p = drop("c3", kind="command", place="wsl-host", command="toy.reproduce", values={"input": "small"}, resume_url=RESUME)
    FW.M.stop.set()                                                                  # the runner stops while the job runs
    FW.handle("c3", p, cards=CARDS, crew=CREW, post=post, sleep=nap)
    FW.M.stop.clear()
    assert p.exists() and len(sent) == 2
    FW.handle("c3", p, cards=CARDS, crew=CREW, post=post, sleep=nap)                # after its restart: the same job, waited for
    a = sent[2][1]
    assert a["status"] == "done" and a["job"].startswith("wsl-host/") and "reproduced on small" in a["log"] and "log.txt" in a["artifacts"]
    assert len([d for d in (host / "outbox").iterdir() if d.is_dir()]) == 1          # submitted once


def test_a_plan_runs_in_waves_through_the_agent_path_and_answers_every_steps_output(F, monkeypatch):
    said, prompts, together = [], {}, threading.Barrier(2, timeout=60)   # a loaded machine (a publish beside a landing) needed more than 10 s
    FW.M.event = lambda kind, slug="", text="", push=False, title="", **k: said.append(text)

    def agent(c, t, s, prompt, card):
        prompts[s["idx"]] = str(prompt)
        if s["idx"] in (1, 2) and not together.broken and "fail" not in s["title"]:
            together.wait()                                                          # steps 1 and 2 run at the same time
        if "fail" in s["title"]:
            raise RuntimeError("the shop did not answer")
        return f"result of step {s['idx']}"
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": agent})
    steps = [{"agent": "scout", "brief": "Find RAM prices.", "title": "Prices"}, {"agent": "scout", "brief": "Find the board's slots."},
             {"agent": "desk", "brief": "Recommend one kit.", "title": "Advice", "after": [1, 2]}]
    p = drop("p1", kind="plan", steps=steps, title="RAM upgrade", resume_url=RESUME)
    post, sent = took()
    FW.handle("p1", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    a = sent[0][1]
    assert a["status"] == "done" and a["output"] == "result of step 3" and [s["output"] for s in a["steps"]] == [f"result of step {i}" for i in (1, 2, 3)]
    assert not together.broken                                                        # one wave: steps 1 and 2 together, step 3 after them
    together.abort()
    assert "Your step (3 of 3): Advice: Recommend one kit." in prompts[3] and "result of step 1" in prompts[3] and "result of step 2" in prompts[3]
    assert "The task: RAM upgrade" in prompts[1] and TK.row(F.c, a["task"])["status"] == "done"
    assert said[-1] == "RAM upgrade: done"
    steps[0]["title"] = "Prices (fail)"
    p = drop("p2", kind="plan", steps=steps, resume_url=RESUME)
    FW.handle("p2", p, cards=CARDS, crew=CREW, post=post, sleep=lambda s: None)
    a = sent[1][1]
    assert a["status"] == "failed" and [s["status"] for s in a["steps"]] == ["failed", "done", "cancelled"]
    assert a["error"].startswith("step 1: RuntimeError: the shop did not answer") and a["steps"][2]["error"] == "step 1 did not finish"
    assert said[-1].startswith("a plan of 3 steps: failed: step 1")


def test_the_nodes_pickers_read_the_agents_crew_jobs_places_and_repositories_the_runner_writes(F, host, tmp_path, monkeypatch):
    seen_by_worker("wsl-host", lambda k: True)
    approve_at_wsl_host()
    toy = [{"name": "toy", "agents": [{"id": "toy:triage", "name": "triage", "harness": "claude-code", "purpose": "Sorts bug reports", "pack": "toy"}]}]
    cat = FW.step_catalog(packs=toy, repos=["ai-stack"], places=["wsl-host", "windows"])
    assert cat["kinds"] == list(FW.KINDS) and {"build", "recall", "remember", "command", "plan"} <= set(cat["kinds"])
    ids = {a["id"]: a for a in cat["agents"]}
    assert ids["toy:triage"]["purpose"] == "Sorts bug reports" and ids["scout"]["purpose"]   # the stack's own cards and the pack's
    assert {"id": "memory", "name": "Memory Keeper"} in cat["crew"] and "self-review" not in {j["id"] for j in cat["crew"]}
    assert cat["places"][0] == {"id": "wsl-host", "name": FW.PLACE_NAMES["wsl-host"], "answering": True, "commands": ["toy.reproduce"]}
    assert cat["places"][1]["id"] == "windows" and cat["repos"] == [{"id": "ai-stack", "name": "ai-stack"}] and cat["problems"] == []
    monkeypatch.setattr(FW, "step_catalog", lambda: cat)
    monkeypatch.setattr(FW, "catalog", lambda: {"jobs": {}})
    FW.write_catalog(tmp_path)
    from starlette.testclient import TestClient
    import server as S
    monkeypatch.setattr(S, "STEP_CATALOG", tmp_path / "step-catalog.json")
    got = TestClient(S.flows_app, base_url="http://mission-control:8099").get("/catalog").json()
    assert got["ok"] and got["agents"] == cat["agents"] and got["places"][0]["commands"] == ["toy.reproduce"]
    monkeypatch.setattr(S, "STEP_CATALOG", tmp_path / "none.json")
    assert TestClient(S.flows_app, base_url="http://mission-control:8099").get("/catalog").json()["ok"] is False


def test_an_answer_waits_until_n8n_has_finished_starting():
    """WFL-34: during n8n's start-up an answer was taken and dropped, or crashed its run (§11.1); it is posted only once
    /healthz/readiness answers 200, and kept until then."""
    posted, asked = [], []

    def post(req, timeout=30):
        posted.append(req.full_url)
        return Resp()
    starting = iter([False, False, True])
    assert FW.deliver(RESUME, {"status": "done"}, post=post, ready=lambda: next(starting)) is False
    assert FW.deliver(RESUME, {"status": "done"}, post=post, ready=lambda: next(starting)) is False
    assert posted == []                                                    # nothing reached n8n while it was starting
    assert FW.deliver(RESUME, {"status": "done"}, post=post, ready=lambda: next(starting)) is True
    assert posted == ["http://127.0.0.1:5678/webhook-waiting/731/ab12"]

    class NotYet(Resp):
        status = 503

    def get(req, timeout=5):
        asked.append(req.full_url)
        return NotYet() if len(asked) == 1 else Resp()
    assert FW.n8n_ready(get) is False and FW.n8n_ready(get) is True
    assert asked == ["http://127.0.0.1:5678/healthz/readiness"] * 2

    def away(req, timeout=5):
        raise OSError("connection refused")
    assert FW.n8n_ready(away) is False
