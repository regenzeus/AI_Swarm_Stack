"""The ways in for a site's agents (WAY-01 to WAY-08, docs/CLI.md): the `stack` command line against the app's own test
client, the app's rule for it (only its actions, recorded as via cli), the runner's side (a run through Run now with the
runner's header, a pack's approval as a gate Ask), a gate that refuses the command line and the agents' tools whole, the
stack MCP tools, the doctor and the installed command."""
import asyncio
import datetime as dt
import io
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import asks as A
import stack_cli as SC
import stack_requests as SR

ROOT = Path(__file__).resolve().parents[1]
H = {"Tailscale-User-Login": "owner@test"}
T0 = 1_800_000_000.0
FLOWS = {"workflows": [
    {"id": "aisdemo0000000001", "name": "Morning briefing", "active": True, "schedule": "daily 06:30", "for": "", "agents": ["writer"],
     "crew": [], "runs_total": 2, "steps": [{"name": "Write", "title": "Write", "kind": "agent", "agent": "writer"}],
     "runs": [{"execution": "702", "state": "waiting", "on": "Your OK", "started": "2026-11-11T06:30:01+01:00", "ended": None,
               "steps": [{"title": "Write", "kind": "agent", "agent": "writer", "state": "done", "started": "2026-11-11T06:30:01+01:00",
                          "ended": "2026-11-11T06:31:40+01:00"},
                         {"title": "Your OK", "kind": "ask", "state": "waiting", "started": "2026-11-11T06:31:41+01:00", "ended": None}]},
              {"execution": "650", "state": "done", "on": "Write", "started": "2026-11-10T06:30:01+01:00", "ended": "2026-11-10T06:31:12+01:00",
               "steps": [{"title": "Write", "kind": "agent", "agent": "writer", "state": "done", "started": "2026-11-10T06:30:01+01:00",
                          "ended": "2026-11-10T06:31:12+01:00"}]}]},
    {"id": "aisdemo0000000002", "name": "Backup check", "active": True, "schedule": "hourly at :00", "for": "crew:backup", "agents": [],
     "crew": ["backup"], "runs_total": 1, "steps": [],
     "runs": [{"execution": "699", "state": "failed", "on": "Check", "started": "2026-11-11T06:00:00+01:00", "ended": "2026-11-11T06:00:09+01:00",
               "steps": [{"title": "Check", "kind": "crew", "job": "backup", "state": "failed", "started": "2026-11-11T06:00:00+01:00",
                          "ended": "2026-11-11T06:00:09+01:00"}]}]}]}
CATALOG = {"agents": [{"id": "writer", "name": "writer", "harness": "hermes", "purpose": "Writes the briefing."},
                      {"id": "reviewer", "name": "reviewer", "harness": "claude-code", "purpose": "Reviews a change."}]}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ASKS_DIR", str(tmp_path / "asks"))
    monkeypatch.setenv("AISTACK_ROLES", str(tmp_path / "none.yaml"))
    monkeypatch.setattr(A, "TYPES", {})
    monkeypatch.setattr(A, "APPLY", {})
    A.register("toy", "A toy question", action="answer", outcomes=(("go", "Go"), ("stop", "Stop")))
    A.register("toy-gate", "A toy gate", action="deploy", outcomes=(("approve", "Approve"), ("reject", "Reject")), gate=True, role="reviewer")
    return tmp_path


@pytest.fixture
def site(store, tmp_path, monkeypatch):
    """The app on its test client with demo workflows, agents and Asks; the command line's calls go to it, and a stand-in
    runner takes each request from the inbox with the runner's own handlers."""
    import server as S
    m = tmp_path / "missions"
    for d in ("inbox", "public/results", "app"):
        (m / d).mkdir(parents=True)
    (m / "public/workflows-runs.json").write_text(json.dumps(FLOWS))
    (m / "public/step-catalog.json").write_text(json.dumps(CATALOG))
    for k, v in {"STATE": m / "public/state.json", "INBOX": m / "inbox", "RESULTS": m / "public/results", "DATA": m / "app",
                 "FLOWS_VIEW": m / "public/workflows-runs.json", "STEP_CATALOG": m / "public/step-catalog.json"}.items():
        monkeypatch.setattr(S, k, v)
    orig = S.submit
    monkeypatch.setattr(S, "submit", lambda req, wait=8.0: orig(req, wait=0.05))
    go = A.open_ask({"kind": "toy", "source": "toy:1", "question": "Send the briefing to the team?", "task": "n8n:aisdemo0000000001/702"}, now=T0)
    gate = A.open_ask({"kind": "toy-gate", "source": "toy:2", "question": "Approve the release?"}, now=T0)
    private = A.open_ask({"kind": "toy", "source": "toy:3", "question": "Your income was 51,234?", "sensitivity": "private"}, now=T0)

    def publish():
        S.STATE.write_text(json.dumps({"missions": [], "activity": [], "calls": [], "system": {}, "running": None, "queue": [],
                                       **A.published(now=T0)}))
    publish()
    c = TestClient(S.app)
    done = []

    def runner(req):                                      # the runner's dispatch, as ops/missions.requests.py does it
        if req["action"] in A.ACTIONS:
            return A.handle(req, now=T0)
        return {"stand-in": req["action"]}

    def wait(_s):
        for f in sorted(S.INBOX.glob("*.json")):
            req = json.loads(f.read_text())
            done.append(req)
            try:
                res = {"ok": True, **runner(req)}
            except ValueError as e:
                res = {"ok": False, "error": str(e)}
            (S.RESULTS / f.name).write_text(json.dumps(res))
            f.unlink()
        publish()

    def opener(req, timeout=None):
        u = urllib.parse.urlsplit(req.full_url)
        r = c.request(req.get_method(), u.path + (f"?{u.query}" if u.query else ""), content=req.data, headers=dict(req.header_items()))
        if r.status_code >= 400:
            raise urllib.error.HTTPError(req.full_url, r.status_code, "", {}, io.BytesIO(r.content))
        return io.BytesIO(r.content)

    monkeypatch.setattr(SC, "OPEN", [opener])
    monkeypatch.setattr(SC, "WAIT", [wait])
    monkeypatch.setenv("STACK_OPERATOR", "operator@test")
    return {"S": S, "client": c, "done": done, "go": go, "gate": gate, "private": private, "runner": runner}


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = SC.main(list(argv), out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_the_command_line_lists_workflows_agents_runs_and_one_run_from_the_app_s_api(site):
    code, out, _ = run("workflows")
    assert code == 0 and "Morning briefing  (aisdemo0000000001)" in out and "daily 06:30 · on · last run 702 waiting" in out
    code, out, _ = run("agents")
    assert code == 0 and "writer (hermes): Writes the briefing." in out and "used in: Morning briefing" in out
    assert "reviewer (claude-code)" in out and "used in: no workflow yet" in out
    code, out, _ = run("runs")
    assert code == 0 and [x.split()[0] for x in out.splitlines()] == ["702", "699", "650"]           # newest first
    assert run("runs", "--status", "failed")[1].split()[0] == "699"
    assert [x.split()[0] for x in run("runs", "--workflow", "morning briefing")[1].splitlines()] == ["702", "650"]
    code, _, err = run("runs", "--workflow", "nothing like it")
    assert code == 1 and "no workflow 'nothing like it'" in err
    code, out, _ = run("run", "show", "702")
    assert code == 0 and "Run 702 of Morning briefing: waiting" in out
    assert re.search(r"1\. Write \(agent step, writer\): done, \d\d \w+ \d\d:\d\d to \d\d:\d\d:40\n", out)   # the same day: only the time
    assert "Send the briefing to the team?" in out and "/n8n/workflow/aisdemo0000000001/executions/702" in out
    code, out, _ = run("--json", "run", "show", "702")
    d = json.loads(out)
    assert d["steps"][1]["kind"] == "ask" and d["asks"][0]["id"] == site["go"]["id"] and d["asks"][0]["choices"][0] == {"id": "go", "label": "Go"}
    assert run("run", "show", "1")[0] == 1


def test_the_command_line_lists_the_open_asks_and_a_private_one_shows_no_figure(site):
    code, out, _ = run("asks")
    assert code == 0 and site["go"]["id"] in out and "answer: go (Go), stop (Stop) or your own words" in out
    assert "a gate: only a person in the role reviewer answers it, by a tap in the app" in out
    assert "51,234" not in out and "A private question waits in the app." in out
    d = json.loads(run("--json", "asks")[1])["asks"]
    assert next(a for a in d if a["id"] == site["private"]["id"])["facts"] == [] and all("acts" not in a for a in d)


def test_an_answer_by_the_command_line_is_a_chip_or_words_by_the_operator_via_cli_and_a_gate_is_refused(site):
    code, out, _ = run("answer", site["go"]["id"][:6], "go")
    assert code == 0 and out.startswith("Answered: Go. It is held until")
    req = site["done"][-1]
    assert (req["source"], req["via"], req["who"], req["outcome"]) == ("cli", "cli", "operator@test", "go") and req["answer_id"].startswith("cli-")
    a = A.get(site["go"]["id"])
    assert a["pending"]["state"] == "held" and A.history(a["id"])[-1]["via"] == "cli"
    n = len(site["done"])
    code, _, err = run("answer", site["gate"]["id"], "approve")
    assert code == 1 and "a gate is answered only by a tap in the app by a person in its role (reviewer)" in err
    code, _, err = run("answer", site["private"]["id"], "yes")
    assert code == 1 and "a private question is answered in the app" in err
    assert len(site["done"]) == n                                                    # neither reached the runner


def test_the_app_takes_only_the_command_line_s_actions_and_never_the_page_s_word_for_who_or_how(site):
    S, c = site["S"], site["client"]
    cli = {**H, "X-Aistack-Via": "cli"}
    for action in ("pack_approve", "build_approve", "ask_rule_save", "ask_stop", "task_approve", "command_approve", "tracker_live"):
        r = c.post("/api/request", headers=cli, json={"action": action, "name": "toy", "commit": "abc1234"})
        assert r.status_code == 403 and "the command line does not do" in r.json()["error"], action
    assert c.post("/api/request", headers={**H, "X-Aistack-Via": "robot"}, json={"action": "workflow_run"}).status_code == 400
    assert not list(S.INBOX.glob("*.json"))
    r = c.post("/api/request", headers=cli, json={"action": "ask_answer", "id": site["go"]["id"], "reply": "Stop", "always": True}).json()
    req = json.loads((S.INBOX / f"{r['id']}.json").read_text())
    assert req["outcome"] == "stop" and "always" not in req and req["via"] == "cli"            # a standing rule is the owner's, in the app
    r = c.post("/api/request", headers=H, json={"action": "run", "slug": "u", "via": "cli", "source": "cli"}).json()
    assert json.loads((S.INBOX / f"{r['id']}.json").read_text()) == {"action": "run", "slug": "u", "source": "app", "who": "owner@test"}
    r = c.post("/api/request", headers=cli, json={"action": "ask_answer", "id": site["gate"]["id"], "reply": "Approve"})
    assert r.status_code == 403 and "never answer one" in r.json()["error"]


def test_a_gate_refuses_the_command_line_and_the_agents_tools_whole(store):
    g = A.open_ask({"kind": "toy-gate", "source": "toy:g", "question": "Approve?"}, now=T0)
    for via in ("cli", "mcp"):
        for do in (lambda: A.answer(g["id"], answer_id=f"{via}-00000001", person="me@x", via=via, outcome="approve", chip=True, now=T0),
                   lambda: A.answer(g["id"], answer_id=f"{via}-00000002", person="me@x", via=via, words="yes approve", now=T0),
                   lambda: A.dismiss(g["id"], answer_id=f"{via}-00000003", person="me@x", via=via, now=T0),
                   lambda: A.later(g["id"], answer_id=f"{via}-00000004", person="me@x", via=via, until="tomorrow morning", now=T0)):
            with pytest.raises(ValueError, match="never answer one"):
                do()
    assert A.get(g["id"])["status"] == "open" and not A.get(g["id"]).get("pending")
    t = A.open_ask({"kind": "toy", "source": "toy:t", "question": "Go?"}, now=T0)
    assert A.answer(t["id"], answer_id="cli-00000005", person="me@x", via="cli", outcome="go", chip=True, now=T0)["state"] == "held"


def flows(active=True, hook=True):
    nodes = [{"name": "On its schedule", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}},
             {"name": "Write", "type": "CUSTOM.aistackStep", "parameters": {"kind": "agent", "agent": "writer"}}]
    if hook:
        nodes.append({"name": "Run now", "type": SR.WEBHOOK, "parameters": {"path": "run/morning-briefing"}})
    return [("morning-briefing", {"id": "aisdemo0000000001", "name": "Morning briefing", "active": active, "nodes": nodes}),
            ("backup-check", {"id": "aisdemo0000000002", "name": "Backup check", "active": True, "nodes": []})]


def test_a_run_starts_through_its_run_now_webhook_with_the_runner_s_header_and_the_inputs(store, monkeypatch):
    sent, lines = [], []

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"
    monkeypatch.setenv("N8N_HOOK_TOKEN", "hook-secret")
    monkeypatch.setattr(SR.urllib.request, "urlopen", lambda req, timeout=None: sent.append(req) or R())
    r = SR.run_workflow({"workflow": "Morning Briefing", "input": {"topic": "copper"}, "who": "operator@test", "via": "cli"},
                        event=lambda *a, **k: lines.append(a[2]), flows=flows(), now=T0)
    assert r["workflow"] == "morning-briefing" and r["id"] == "aisdemo0000000001" and r["started"] == T0
    req = sent[0]
    assert req.full_url == "http://127.0.0.1:5678/webhook/run/morning-briefing" and req.get_header("X-aistack-hook") == "hook-secret"
    assert json.loads(req.data) == {"input": {"topic": "copper"}, "by": "operator@test", "via": "cli"}
    assert lines == ["Morning briefing: started by operator@test through the command line"]
    for wf, why in ((flows(active=False), "is switched off"), (flows(hook=False), "has no Run now trigger")):
        with pytest.raises(ValueError, match=why):
            SR.run_workflow({"workflow": "morning-briefing"}, flows=wf, post=lambda *a: None)
    with pytest.raises(ValueError, match="no workflow 'briefing' on this site; did you mean morning-briefing"):
        SR.run_workflow({"workflow": "briefing"}, flows=flows(), post=lambda *a: None)
    with pytest.raises(ValueError, match="an input's name is a short word"):
        SR.run_workflow({"workflow": "morning-briefing", "input": {"a b": "x"}}, flows=flows(), post=lambda *a: None)
    A.stop_set(True, "owner@test")
    with pytest.raises(ValueError, match="the stop switch is on"):
        SR.run_workflow({"workflow": "morning-briefing"}, flows=flows(), post=lambda *a: None)
    assert len(sent) == 1


def test_stack_run_starts_a_run_and_names_it_once_its_first_step_reports(site, monkeypatch):
    def runner(req):
        assert (req["action"], req["via"], req["who"], req["input"]) == ("workflow_run", "cli", "operator@test", {"topic": "copper", "lang": "en"})
        return {"workflow": "morning-briefing", "name": "Morning briefing", "id": "aisdemo0000000001",
                "started": dt.datetime.fromisoformat("2026-11-11T06:30:00+01:00").timestamp(),
                "message": "Started Morning briefing: its run shows in its runs as soon as its first step reports"}
    monkeypatch.setattr(SR, "handle", lambda req, event=None: runner(req))
    S = site["S"]
    orig = SC.WAIT[0]

    def wait(s):
        for f in sorted(S.INBOX.glob("*.json")):
            req = json.loads(f.read_text())
            (S.RESULTS / f.name).write_text(json.dumps({"ok": True, **SR.handle(req)}))
            f.unlink()
        orig(s)
    monkeypatch.setattr(SC, "WAIT", [wait])
    code, out, _ = run("run", "morning briefing", "--input", "topic=copper", "--input", "lang=en")
    assert code == 0 and "Started Morning briefing" in out and "Run 702: waiting (stack run show 702)" in out
    assert run("run", "morning briefing", "--input", "topic")[0] == 1


def test_a_pack_s_approval_is_a_gate_ask_and_the_command_line_never_approves(store, tmp_path, monkeypatch):
    from domain import packs as PK
    src = tmp_path / "elsewhere/toy"
    shutil.copytree(ROOT / "tests/fixtures/packs/toy", src)
    git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@localhost", *a], cwd=src, check=True,   # noqa: E731
                                    capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "first")
    head = git("rev-parse", "HEAD")
    (tmp_path / "packs.txt").write_text(f"toy {src} {head}\n")
    for k, v in (("AISTACK_PACKS_TXT", "packs.txt"), ("AISTACK_PACKS", "cache"), ("AISTACK_PACK_APPROVALS", "approvals.json")):
        monkeypatch.setenv(k, str(tmp_path / v))
    (src / "NOTE.md").write_text("a second commit\n")
    git("add", "-A")
    git("commit", "-q", "-m", "second")
    second = git("rev-parse", "HEAD")
    r = SR.pack_ask({"name": "toy", "commit": second[:10], "who": "operator@test", "via": "cli"})
    a = A.get(r["ask"])
    assert r["gate"] and a["gate"] and a["kind"] == "pack-commit" and a["role"] == "owner" and a["question"] == f"Approve pack toy at {second[:12]}?"
    assert a["acts"] == {"approve": {"action": "pack_approve", "name": "toy", "commit": second}} and "the command line never approves" in r["message"]
    assert "Asked by operator@test through the command line" in a["why"] and not (tmp_path / "approvals.json").exists()
    again = SR.pack_ask({"name": "toy", "commit": second})
    assert again["ask"] == a["id"] and again["message"].startswith("Waiting already")                # asked again: the same Ask
    with pytest.raises(ValueError, match="never answer one"):
        A.answer(a["id"], answer_id="cli-00000009", person="operator@test", via="cli", outcome="approve", chip=True, now=T0)
    applied = []
    monkeypatch.setattr(A, "DISPATCH", [lambda req: applied.append(req) or {"ok": True}])
    A.answer(a["id"], answer_id="app-00000009", person="owner@test", via="app", outcome="approve", chip=True, now=T0)
    A.tick(now=T0 + A.HOLD_S)
    assert applied[0]["action"] == "pack_approve" and applied[0]["commit"] == second and applied[0]["who"] == "owner@test"
    PK.approve("toy", second, "owner@test")
    assert SR.pack_ask({"name": "toy", "commit": second})["state"] == "approved"
    PK.refuse("toy", head, "owner@test", "not this one")
    with pytest.raises(ValueError, match="was refused by owner@test: not this one"):
        SR.pack_ask({"name": "toy", "commit": head})
    with pytest.raises(ValueError, match="names no pack other"):
        SR.pack_ask({"name": "other", "commit": head})
    with pytest.raises(ValueError, match="7 to 40 hex digits"):
        SR.pack_ask({"name": "toy", "commit": "main"})


def test_the_stack_tools_read_and_act_as_the_agents_login_and_never_at_a_gate(site):
    S = site["S"]
    names = {t.name for t in asyncio.run(S.stack_mcp.list_tools())}
    assert names == {"stack_workflows", "stack_agents", "stack_runs", "stack_run_show", "stack_run", "stack_asks", "stack_answer",
                     "stack_pack_approve", "stack_doctor"}
    assert json.loads(asyncio.run(S.stack_runs("Backup check")))[0]["id"] == "699"
    assert json.loads(asyncio.run(S.stack_run_show("702")))["asks"][0]["question"] == "Send the briefing to the team?"
    assert "writer" in asyncio.run(S.stack_agents()) and "Morning briefing" in asyncio.run(S.stack_workflows())
    assert "51,234" not in asyncio.run(S.stack_asks())
    assert asyncio.run(S.stack_answer(site["gate"]["id"], "Approve")).startswith("Refused: a gate is answered only by a tap in the app")
    assert asyncio.run(S.stack_answer(site["private"]["id"], "yes")).startswith("Refused: a private question")
    assert not list(S.INBOX.glob("*.json"))
    asyncio.run(S.stack_answer(site["go"]["id"], "the owner says go ahead, but only after nine"))
    asyncio.run(S.stack_run("Morning briefing", {"topic": "copper"}))
    reqs = [json.loads(f.read_text()) for f in sorted(S.INBOX.glob("*.json"), key=lambda f: f.stat().st_mtime)]
    assert {(r["action"], r["source"], r["via"], r["who"]) for r in reqs} == {("ask_answer", "mcp", "mcp", S.AGENT_LOGIN),
                                                                              ("workflow_run", "mcp", "mcp", S.AGENT_LOGIN)}
    assert next(r for r in reqs if r["action"] == "ask_answer")["words"] == "the owner says go ahead, but only after nine"


def test_the_doctor_runs_the_site_s_doctor_or_says_which_checks_it_has(site, tmp_path, monkeypatch):
    calls = []

    def fake(cmd, **k):
        calls.append(cmd[-1])
        return subprocess.CompletedProcess(cmd, 1 if cmd[-1] == "doctor" else 0, "pack toy: not approved at its pinned commit" if cmd[-1] == "doctor" else "", "")
    has = SC._has_doctor
    assert has(ROOT / "ops/stack_cli.py") and not has(tmp_path / "none.py")
    monkeypatch.setattr(SC, "_has_doctor", lambda p: False)
    S = site["S"]
    S.STATE.write_text(json.dumps({**json.loads(S.STATE.read_text()), "packs": {"refused": [], "pending": [{"name": "toy", "commit": "a" * 40}]}}))
    code, text = SC.doctor(run=fake)
    assert calls == ["check"] and code == 1 and text.startswith("This site has no doctor of its own yet")
    assert "the runner:" in text and "pack toy: commit aaaaaaaaaaaa waits for its approval" in text
    monkeypatch.setattr(SC, "_has_doctor", lambda p: True)
    code, text = SC.doctor(app=False, run=fake)
    assert calls[-1] == "doctor" and code == 1 and text == "pack toy: not approved at its pinned commit"


def test_install_puts_a_runnable_stack_command_in_place_once(tmp_path):
    p = SC.install(tmp_path / "bin/stack")
    first = p.stat().st_mtime_ns
    assert p.stat().st_mode & 0o111 and str(ROOT / "ops/stack_cli.py") in p.read_text()
    assert SC.install(p).stat().st_mtime_ns == first                                           # the same text: left as it is
    r = subprocess.run([str(p), "--help"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "stack" in r.stdout and "pack" in r.stdout
    with pytest.raises(SystemExit) as e:
        SC.parser().parse_args(["nonsense"])
    assert e.value.code == 2
