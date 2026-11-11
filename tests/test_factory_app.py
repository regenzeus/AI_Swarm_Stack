"""APP-71 to APP-73 (the factory design's phase A): everything the stack does is a workflow and every piece of work a run.
The n8n workflows come with their diagram (ops/flows_view.py graph_of); the old sources without an n8n workflow show as
runs of the standard workflow they become (Request, Change, Briefing); the app reads both through one read-only API
(images/mission-control/server.workflows.py) and draws the list, a workflow's page with its diagram and a run's page."""
import json
import re
import subprocess
from pathlib import Path

import pytest
from starlette.testclient import TestClient

import flows_view as FV
import webjs

ROOT = Path(__file__).resolve().parents[1]
H = {"Tailscale-User-Login": "owner@example.com"}
NOW = "2026-11-11T09:00:00+01:00"


def graph(name):
    return FV.graph_of(json.loads((ROOT / f"n8n/workflows/{name}.json").read_text()))


def wfv():
    """The runner's view of three workflows: a scheduled job's, a chain of steps with an If, and a request's own."""
    return {"workflows": [
        {"id": "w-coach", "name": "Crew: Coach", "file": "crew-coach", "area": "upkeep", "factory": "", "graph": graph("crew-coach"), "active": True,
         "schedule": "monthly on day 2, 06:00", "for": "crew:coach", "steps": [{"title": "Crew: Coach", "kind": "crew", "job": "coach"}], "agents": [], "crew": ["coach"],
         "runs": [{"execution": "9", "state": "failed", "on": "Crew: Coach", "started": NOW, "ended": NOW,
                   "steps": [{"title": "Crew: Coach", "kind": "crew", "state": "failed", "started": NOW, "ended": NOW, "job": "coach"}]}], "runs_total": 1},
        {"id": "w-inbox", "name": "Item: home/inbox", "file": "item-home-inbox", "area": "inbox", "factory": "", "graph": graph("item-home-inbox"), "active": True,
         "schedule": "when called", "for": "", "steps": [], "agents": ["main"], "crew": [], "runs": [], "runs_total": 0},
        {"id": "w-brief", "name": "Task 41", "file": "task-41-x", "area": "briefings", "factory": "home", "graph": graph("crew-coach"), "active": False,
         "schedule": "Mondays 07:00", "for": "task:41", "steps": [], "agents": [], "crew": [],
         "runs": [{"execution": "12", "state": "running", "on": "Write", "started": NOW, "ended": None, "steps": []}], "runs_total": 1}]}


def state():
    t = lambda i, door, status, **kw: {"id": i, "title": f"Work {i}", "door": door, "status": status, "area": kw.pop("area", "research"), "asked": "you",
                                       "created": NOW, "updated": NOW, "runs": [], "steps": [], **kw}
    return {"tasks": [t(41, "plan", "running", kind="briefing", title="Weekly market briefing", next_run="2026-11-16T07:00:00+01:00",
                        runs=[{"occ": 3, "execution": "12", "status": "running", "trigger": "n8n", "started": NOW}]),
                      t(60, "crew", "scheduled", ref="coach", area="upkeep", asked="stack"),
                      t(63, "flow", "running", workflow="w-inbox", title="Your inbox: an answer to each new item", area="inbox"),
                      t(50, "plan", "needs_answer", kind="shopping"), t(51, "claude", "done", last_run={"summary": "It lists only images. The rest is fine."}),
                      t(52, "build", "waiting_owner"), t(53, "plan", "failed", kind="change", error="Its checks failed"),
                      t(54, "mission", "done", ref="m1"), t(55, "chat", "done"),
                      t(56, "plan", "scheduled", kind="research", runs=[{"occ": 1, "status": "done", "started": "2026-11-09T08:00:00+01:00", "result": "one"},
                                                                       {"occ": 2, "status": "failed", "started": "2026-11-10T08:00:00+01:00", "result": "two"}])],
            "missions": [{"slug": "m1", "type": "briefing", "title": "M"}],
            "crew": [{"id": "coach", "name": "Coach", "next": 1763000000, "workflow": "w-coach"}],
            "asks": [{"id": "a1", "status": "open", "task": 50, "question": "Which one?"}, {"id": "a2", "status": "open", "task": 63, "question": "Post it?"},
                     {"id": "a3", "status": "answered", "task": 63}, {"id": "a4", "status": "open", "task": 50, "test": True}]}


@pytest.fixture
def app(tmp_path, monkeypatch):
    import server as S
    m = tmp_path / "missions/public"
    m.mkdir(parents=True)
    (m / "state.json").write_text(json.dumps(state()))
    (m / "workflows-runs.json").write_text(json.dumps(wfv()))
    monkeypatch.setattr(S, "STATE", m / "state.json")
    return S


def test_a_workflow_s_diagram_is_its_n8n_nodes_and_connections():
    """APP-72: every node with its place and what it is (a trigger in words, an AI Stack step's kind and agent or job, n8n's
    own), every connection with its output (an If's yes and no)."""
    g = graph("item-home-inbox")
    kinds = {n["name"]: (n["type"], n.get("kind"), n.get("agent"), n.get("trigger")) for n in g["nodes"]}
    assert any(t == "aistackStep" and k == "agent" and a == "main" for t, k, a, _ in kinds.values())
    assert any(t == "if" for t, *_ in kinds.values()) and any(trig == "when called" for *_, trig in kinds.values())
    assert {e[2] for e in g["edges"] if kinds[e[0]][0] == "if"} == {0, 1}                # both ways out of the If
    assert all(a in kinds and b in kinds for a, b, _ in g["edges"])
    c = graph("crew-coach")
    assert {n.get("trigger") for n in c["nodes"]} >= {"monthly on day 2, 06:00", "Run now"}
    assert [n.get("job") for n in c["nodes"] if n["type"] == "aistackStep"] == ["coach"]
    v = FV.view(repo=ROOT / "n8n/workflows", seen={}, made=ROOT / "n8n/none", done=ROOT / "n8n/none")
    assert v["workflows"] and all(w["graph"]["nodes"] and w["file"] and "area" in w for w in v["workflows"])   # every workflow has its diagram


def test_every_workflow_is_in_one_list_grouped_by_factory_and_area(app):
    """APP-71: the n8n workflows and the standard ones, each with its factory (upkeep is the platform's), area, trigger,
    last run, next run, open Asks and result; a scheduled job's workflow is named as its job, a request's as the request."""
    d = TestClient(app.app).get("/api/factory", headers=H).json()
    by = {w["id"]: w for w in d["workflows"]}
    assert d["factories"] == {"home": "Home", "platform": "Platform"} and d["areas"]["standard"] == "Standard workflows"
    assert set(by) == {"w-coach", "w-inbox", "w-brief", "request", "change", "briefing"}
    coach = by["w-coach"]
    assert (coach["name"], coach["factory"], coach["area"], coach["trigger"]) == ("Coach", "platform", "upkeep", "monthly on day 2, 06:00")
    assert coach["last_run"]["state"] == "failed" and coach["next_run"] == 1763000000 and coach["page"] == "#/crew/coach"
    assert (by["w-inbox"]["name"], by["w-inbox"]["factory"], by["w-inbox"]["asks"]) == ("Your inbox: an answer to each new item", "home", 1)   # its record's open Ask
    assert by["w-brief"]["name"] == "Weekly market briefing" and by["w-brief"]["active"] is False and by["w-brief"]["next_run"].startswith("2026-11-16")
    req = by["request"]
    assert (req["source"], req["factory"], req["area"]) == ("standard", "home", "standard") and req["asks"] == 1   # the test Ask is no Ask
    assert [n["name"] for n in req["graph"]["nodes"]][1:] == ["Understand", "Work out the steps", "Do", "Check", "Deliver"]
    assert all(not re.search(r"\b(task|mission|crew|plan)\b", w["name"], re.I) for w in d["workflows"])


def test_old_sources_are_runs_of_the_standard_workflow_they_become(app):
    """APP-73: a sentence, a Claude question, a chat request and research are runs of Request; a build and a change, of
    Change; a briefing, of Briefing; the path of each is its template's steps up to where its record stands; a request
    that repeats is one run per time it ran; a scheduled job and a workflow's own record are never counted twice."""
    cl = TestClient(app.app)
    runs = lambda k: cl.get(f"/api/factory/workflow/{k}", headers=H).json()["runs"]
    req, chg, brf = runs("request"), runs("change"), runs("briefing")
    assert {r["task"] for r in req} == {50, 51, 55, 56} and {r["task"] for r in chg} == {52, 53} and {r["task"] for r in brf} == {54}
    assert [r["id"] for r in req if r["task"] == 56] == ["t56.2", "t56.1"] and req[0]["id"] == "t50"          # what waits comes first
    wait = next(r for r in req if r["task"] == 50)
    assert wait["state"] == "waiting" and wait["asks"] == 1 and wait["path"] == {"Understand": "waiting"} and wait["href"] == "#/task/50"
    assert next(r for r in req if r["task"] == 51)["path"] == {n: "done" for n in ("Understand", "Work out the steps", "Do", "Check", "Deliver")}
    assert next(r for r in chg if r["task"] == 52)["path"]["Ship"] == "waiting"
    failed = next(r for r in chg if r["task"] == 53)
    assert failed["state"] == "failed" and "failed" in failed["path"].values() and failed["result"] == "Its checks failed"
    assert not {41, 60, 63} & {r["task"] for r in req + chg + brf}                    # theirs are n8n's runs
    assert cl.get("/api/factory/workflow/nothing", headers=H).status_code == 404


def test_a_run_s_page_has_its_workflow_its_path_and_its_asks(app):
    """APP-73: the run of a workflow with its diagram, the path it took (each step's state), its Asks and its record."""
    cl = TestClient(app.app)
    d = cl.get("/api/factory/run/w-coach/9", headers=H).json()
    assert d["workflow"]["id"] == "w-coach" and d["run"]["path"] == {"Coach": "failed"} and d["run"]["asked"] == "stack"
    r = cl.get("/api/factory/run/w-brief/12", headers=H).json()["run"]
    assert (r["state"], r["task"], r["occ"], r["href"]) == ("running", 41, 3, "#/task/41?o=3")
    q = cl.get("/api/factory/run/request/t50", headers=H).json()
    assert [a["id"] for a in q["asks"]] == ["a1"] and q["workflow"]["source"] == "standard"
    assert cl.get("/api/factory/run/request/t999", headers=H).status_code == 404
    assert cl.get("/api/factory/run/w-coach/9").status_code == 403                    # behind the gate like every /api route


def node_js(code):
    js = webjs.app_js()
    out = subprocess.run(["node", "-e", code.replace("$JS", js)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def test_the_diagram_is_drawn_in_layers_from_its_triggers_readable_on_a_phone():
    """APP-72: the app lays the nodes out by their longest way from a trigger (a loop back ends), one under the other on a
    phone and side by side on the desk, each label wrapped whole; on a run's page what led to a step that ran is lit."""
    js = webjs.app_js()
    lay = re.search(r"^function graphLayout\(g\) \{.*?^\}$", js, re.M | re.S)[0]
    g = graph("item-home-inbox")
    loop = {"nodes": [{"name": "a", "at": [0, 0]}, {"name": "b", "at": [1, 0]}], "edges": [["a", "b", 0], ["b", "a", 0]]}
    out = json.loads(subprocess.run(["node", "-e", f"{lay}\nprocess.stdout.write(JSON.stringify([graphLayout({json.dumps(g)}).map((l) => l.map((n) => n.name)), graphLayout({json.dumps(loop)}).length]))"],
                                    capture_output=True, text=True, check=True, timeout=30).stdout)
    layers, n_loop = out
    trig = [n["name"] for n in g["nodes"] if n.get("trigger")]
    assert layers[0] == trig and sum(len(l) for l in layers) == len(g["nodes"]) and n_loop >= 1
    draw = re.search(r"^function diagramInto\(.*?^\}$", js, re.M | re.S)[0]
    assert "const vertical = W < 640 || wide < 130" in draw and "wrapWords(nodeTitle(n)" in draw and "ellipsis" not in draw
    assert "while (grew)" in draw and 'class="wfe${on ? " on"' in draw                 # the path: what led to a step that ran
    assert 'diagramInto($("#wfdiagram"), w.graph' in js and "Edit in n8n" in js


def test_the_workflows_page_lists_by_factory_and_area_and_a_card_says_one_line_each():
    """APP-71: the page groups the cards by factory, then area; a card says its name, area, trigger, last and next run,
    open Asks and its result's first sentence, never a dump of the run's output."""
    js = webjs.app_js()
    card = re.search(r"^function wfCardHtml\(w\) \{.*?^\}$", js, re.M | re.S)[0]
    for part in ("esc(w.name)", "a-${esc(w.area)}", "triggerWords(w)", "last ${esc(when(r.started))}", "next ${when(", "Ask${w.asks === 1", "oneLine(w.result)"):
        assert part in card, part
    one = re.search(r"^function oneLine\(.*?^\}$", js, re.M | re.S)[0]
    fs = re.search(r"^const firstSentence = .*?;$", js, re.M)[0]
    got = json.loads(subprocess.run(["node", "-e", f"{fs}\n{one}\nprocess.stdout.write(JSON.stringify([oneLine('Done. The rest\\nof a long dump'), oneLine('x '.repeat(200))]))"],
                                    capture_output=True, text=True, check=True, timeout=30).stdout)
    assert got[0] == "Done." and got[1].endswith(" …") and len(got[1]) < 150
    assert "wfListHtml(v)" in js and 'class="wf-factory"' in js and "v.factories[f]" in js


def test_every_ask_but_a_gate_has_its_reply_box_on_every_card():
    """APP-74: Home's Needs you drew its cards without the reply box; an Ask that takes words has it on every card."""
    js = webjs.app_js()
    asks = re.search(r"^function askCard\(a, compact = false\) \{.*?^\}$", js, re.M | re.S)[0]
    cond = re.search(r"\$\{(holds && !a\.app_only .*?) \? `<form class=\"areply row\"", asks)[1]
    run = lambda a, compact: subprocess.run(["node", "-e", f"const a = {json.dumps(a)}, compact = {json.dumps(compact)}, holds = true; process.stdout.write(String(!!({cond})))"],
                                            capture_output=True, text=True, check=True, timeout=30).stdout
    assert run({"id": "x"}, True) == "true" and run({"id": "x"}, False) == "true"            # Home's compact card too
    assert run({"id": "x", "allow_words": False}, True) == "false" and run({"id": "x", "app_only": True}, False) == "false"
    assert run({"id": "x", "gate": True}, True) == "false" and run({"id": "x", "gate": True}, False) == "true"   # a gate: its comment box on its page


def test_a_build_is_answered_on_its_card():
    """APP-74: Deploy and Reject on the card, each the runner's own request; the review's summary is in its why."""
    import decisions as DQ
    st = {"builds": [{"id": 7, "status": "review", "title": "Footer", "checks": True, "checks_ok": True, "ci": "passed",
                      "ai_review": {"verdict": "approve", "summary": "Small and tested."}}]}
    d = next(x for x in DQ._builds(st))
    assert [a["label"] for a in d["answers"]] == ["Deploy", "Reject"] and not any(a.get("href") for a in d["answers"])
    assert [a["act"] for a in d["answers"]] == [{"action": "build_approve", "id": 7}, {"action": "build_reject", "id": 7}]
    assert "The review: Small and tested." in d["why"] and d["recommend"]["answer"] == "yes"
    spec = DQ.ask_spec(d, 0)
    assert [c["label"] for c in spec["choices"]] == ["Deploy", "Reject"] and spec["acts"]["deploy"]["action"] == "build_approve"


def test_a_text_about_the_owner_reads_in_the_second_person():
    """APP-75: for display only; the stored fact keeps its words."""
    js = webjs.app_js()
    fn = re.search(r"^function youText\(.*?^\}$", js, re.M | re.S)[0]
    cases = ["Sam does not want calls before 9.", "Involving: Sam", "Sam prefers tea. Sam's bike is blue.", "Sam watches the news; ask Sam first.",
             "Sam Doe lives in a flat.", "Nothing about anyone."]
    out = json.loads(subprocess.run(["node", "-e", f"{fn}\nprocess.stdout.write(JSON.stringify({json.dumps(cases)}.map((c) => youText(c, 'Sam Doe'))))"],
                                    capture_output=True, text=True, check=True, timeout=30).stdout)
    assert out == ["You don't want calls before 9.", "Involving: you", "You prefer tea. Your bike is blue.", "You watch the news; ask you first.",
                   "You live in a flat.", "Nothing about anyone."]
    assert "youText(f.text)" in js and "youText(a.question)" in js and "youText(e.fact" in js


def test_an_agent_s_page_lists_every_workflow_it_is_used_in():
    """APP-76: an agent is used in a workflow when a step names it or one of its jobs; its page says what it does, its
    model, tools, knowledge and budget, the workflows it is used in, its recent steps and its scores (from phase C)."""
    js = webjs.app_js()
    fn = re.search(r"^function agentUsedIn\(.*?^\}$", js, re.M | re.S)[0]
    ws = [{"id": "a", "agents": ["tax"]}, {"id": "b", "jobs": ["tax-find"]}, {"id": "c", "graph": {"nodes": [{"agent": "tax"}]}}, {"id": "d", "agents": ["main"], "jobs": ["coach"]}]
    card = {"id": "tax", "jobs": ["crew-tax-find", "crew-tax-file"]}
    got = json.loads(subprocess.run(["node", "-e", f"{fn}\nprocess.stdout.write(JSON.stringify({json.dumps(ws)}.filter((w) => agentUsedIn(w, {json.dumps(card)}, 'tax')).map((w) => w.id)))"],
                                    capture_output=True, text=True, check=True, timeout=30).stdout)
    assert got == ["a", "b", "c"]
    page = re.search(r"^async function vAgentOne\(\) \{.*?^\}$", js, re.M | re.S)[0]
    for part in ("Model", "Tools", "Knowledge", "Skills", "Budget", "Used in", "Recent steps", "Scores", "wfCardHtml", "swAgentPanel("):
        assert part in page, part
    assert "agent: vAgentOne" in js and 'return `#/agent/${encodeURIComponent(id)}`;' in (ROOT / "images/mission-control/web/static/swarm.js").read_text()


def test_ideas_are_a_page_of_code_and_the_measures_are_reached_from_workflows():
    """APP-83, the owner on the phone, 11 Nov 2026: "We lost code? Why? Code was good. And improve is shit." Code is a
    place again; the agents' ideas are a page of it (#/ideas), the measures and benchmarks one tap from Workflows."""
    js = webjs.app_js()
    v = re.search(r"^function vIdeas\(\) \{.*?^\}$", js, re.M | re.S)[0]
    assert 'href="#/build">${ic.back}Code</a>' in v and 'swRender($("#tvbody"), "improve"' in v and "ideas: vIdeas" in js and "vImprove" not in js
    assert 'href="#/measures">${ic.pulse}Measures of your records</a>' in js and 'href="#/trials">${ic.target}Benchmarks</a>' in js
    assert '<a class="banner info section" href="#/ideas">' in js                         # Code's own way to them


def test_home_is_the_cockpit_with_activity_and_no_ai_phone():
    """APP-78: Today is the stop switch, Needs you (the open Asks), what runs, waits, failed and is done today; Activity
    is a part of Home; no AI phone card."""
    js = webjs.app_js()
    home = re.search(r"^function vHome\(\) \{.*?^\}$", js, re.M | re.S)[0]
    assert "${stopHtml()}${needsHtml()}${stackHtml()}${nowHtml()}" in home and 'data-hp="activity"' in home and "devicesHtml" not in home
    assert 'const HOME_GROUPS = [["running", "Running now"], ["needs", "Waiting for you"], ["failed", "Failed"], ["today", "Done today"]];' in js
    assert 'if (HOME_TABS.some(([k]) => k === route.q.get("tab"))) homeTab = route.q.get("tab");' in js


def test_a_card_says_one_short_line_and_who_started_it():
    """APP-79: a card's text is one short line (never a run's whole output), a scheduled job is named by its job, and a
    run on its schedule never says you asked."""
    js = webjs.app_js()
    tt = re.search(r"^const tTitle = .*?;$", js, re.M)[0]
    got = json.loads(subprocess.run(["node", "-e", f"let S = {{crew: [{{id: 'k', name: 'Memory Keeper'}}]}};\n{tt}\nprocess.stdout.write(JSON.stringify([tTitle({{door: 'crew', ref: 'k', title: 'Crew: Memory Keeper'}}), tTitle({{door: 'crew', ref: 'x', title: 'Crew: Coach'}}), tTitle({{door: 'plan', title: 'Ask'}})]))"],
                                    capture_output=True, text=True, check=True, timeout=30).stdout)
    assert got == ["Memory Keeper", "Coach", "Ask"]
    assert "esc(oneLine(youText(x.head), 200))" in js and "prose(oneLine(w.result))" in js and "prose(oneLine(r.result))" in js
    assert 'stack: "on its schedule"' in js and 'schedule: "on its schedule"' in js and 'const ASKED = { you: "you asked", rule: "a trigger of yours", agent: "an outside agent", stack: "on its schedule" };' in js


def test_a_workflow_shows_every_run_its_records_hold_newest_first_with_its_last_result():
    """APP-80, live 11 Nov 2026: a request's workflow said "Runs 0" and "No result yet" after three runs. Its history is
    every record that holds one: n8n's executions, the request's own runs with their results (matched to an execution
    by its id or its start), a chain's runs, a scheduled job's run history; one run once, newest first."""
    import server as S
    g = graph("crew-coach")
    brief = {"id": "w79", "name": "Task #79: Weekly news", "file": "task-79-x", "area": "briefings", "for": "task:79", "schedule": "Mondays 08:00",
             "active": True, "graph": json.loads(json.dumps(g).replace('"kind": "crew"', '"kind": "task"')), "runs": [], "runs_total": 0}
    for n in brief["graph"]["nodes"]:
        if n["type"] == "aistackStep":
            n.update({"kind": "task", "title": "Task #79: Weekly news", "task": 79})
            n.pop("job", None)
    ten = {**brief, "id": "w10", "name": "Task #10", "file": "task-10-x", "for": "task:10",
           "runs": [{"execution": "4839", "state": "failed", "started": "2026-11-11T08:00:05+01:00", "ended": "2026-11-11T08:01:00+01:00",
                     "steps": [{"title": "Task #79: Weekly news", "state": "failed", "task": 10}]}], "runs_total": 1}
    coach = wfv()["workflows"][0]
    occ = lambda o, day, st, res: {"occ": o, "status": st, "trigger": "schedule", "started": f"2026-11-{day}T08:00:00+01:00", "ended": f"2026-11-{day}T08:20:00+01:00", "result": res}   # noqa: E731
    st = {"tasks": [{"id": 79, "door": "plan", "status": "scheduled", "title": "Weekly news", "asked": "you", "plan": [{"agent": "scout"}, {"agent": "mission"}],
                     "runs": [occ(3, "10", "done", "Newest report."), occ(2, "03", "done", "Older."), occ(1, "02", "failed", "")]},
                    {"id": 10, "door": "plan", "status": "scheduled", "title": "RAM", "asked": "you", "runs": [occ(2, "11", "failed", "Shop closed."), occ(1, "09", "done", "Found one.")]},
                    {"id": 60, "door": "crew", "ref": "coach", "status": "scheduled", "title": "Crew: Coach", "runs": []}],
          "crew": [{"id": "coach", "name": "Coach", "payoff": "Two agent changes proposed"}], "asks": []}
    hist = {"coach": [{"start": S._ts(NOW) + 30, "end": S._ts(NOW) + 90, "state": "failed"}, {"start": S._ts("2026-11-01T06:00:00+01:00"), "end": None, "state": "ok"}]}
    wfs, runs = S.factory_model(st, {"workflows": [brief, ten, coach]}, hist)
    by = {w["id"]: w for w in wfs}
    r79 = runs["w79"]
    assert [r["id"] for r in r79] == ["o3", "o2", "o1"] and [r["state"] for r in r79] == ["done", "done", "failed"]
    assert by["w79"]["runs_total"] == 3 and by["w79"]["result"] == "Newest report." and by["w79"]["last_run"]["id"] == "o3"
    assert by["w79"]["agents"] == ["mission", "scout"]                                   # its own steps' agents (APP-84)
    assert r79[0]["path"] == {"Research and write": "done"} and r79[0]["href"] == "#/task/79?o=3"
    r10 = runs["w10"]
    assert [(r["id"], r["occ"], r["result"]) for r in r10] == [("4839", 2, "Shop closed."), ("o1", 1, "Found one.")]   # one run once
    assert r10[0]["path"] == {"Research and write": "failed"}
    assert all(r["trigger"] in ("schedule", "n8n") for r in r79 + r10)                  # a scheduled run never says "you asked" (APP-79)
    rc = runs["w-coach"]
    assert [r["id"] for r in rc] == ["9", f"j{int(S._ts('2026-11-01T06:00:00+01:00'))}"] and by["w-coach"]["result"] == "Two agent changes proposed"


def test_the_diagram_names_a_trigger_and_a_step_by_what_it_does():
    """APP-81: a trigger is "On its schedule · Mondays 08:00", never its cron; a step that holds a request's own steps is
    named by what it does ("Research and write" for a request in a sentence, else its workflow's name) and says once,
    in its detail, that those steps run inside it until phase B."""
    import server as S
    w = {"name": "Task #79: Weekly news", "graph": graph("crew-coach")}
    for n in w["graph"]["nodes"]:
        if n["type"] == "aistackStep":
            n.update({"kind": "task", "title": "Task #79: Weekly news", "task": 79})
    g = S.tidy_graph(w["graph"], w, {"door": "plan", "title": "Weekly news"})
    trig = [n for n in g["nodes"] if n.get("trigger")]
    assert {n["title"] for n in trig} == {"On its schedule", "Run now"} and not any("(" in n["title"] for n in trig)
    step = next(n for n in g["nodes"] if n["type"] == "aistackStep")
    assert (step["title"], step["step_title"], step["inside"]) == ("Research and write", "Task #79: Weekly news", True)
    assert next(n for n in S.tidy_graph(w["graph"], w, {"door": "flow", "title": "Your inbox"})["nodes"] if n["type"] == "aistackStep")["title"] == "Your inbox"
    js = webjs.app_js()
    nt = re.search(r"^const nodeTitle = .*?;$", js, re.M)[0]
    got = json.loads(subprocess.run(["node", "-e", f"{nt}\nprocess.stdout.write(JSON.stringify([nodeTitle({{name: 'On its schedule (0 8 * * 1)', title: 'On its schedule', trigger: 'Mondays 08:00'}}), nodeTitle({{name: 'Run now', title: 'Run now', trigger: 'Run now'}})]))"],
                                    capture_output=True, text=True, check=True, timeout=30).stdout)
    assert got == ["On its schedule · Mondays 08:00", "Run now"]
    assert "`Request #${n.task}`" not in js and "run inside this one step until phase B" in js


def test_a_workflow_names_its_agents_under_its_title():
    """APP-84: "Its agents is very unprominent": the agents a step names, and the agent whose card holds a job a step
    runs, are chips under the workflow's title, each opening the agent's page."""
    js = webjs.app_js()
    fn = re.search(r"^function wfAgentsHtml\(.*?^\}$", js, re.M | re.S)[0]
    w = {"agents": ["tax"], "jobs": ["tax-find"], "graph": {"nodes": [{"agent": "main"}, {"job": "doctor"}]}}
    cards = [{"id": "tax", "jobs": ["crew-tax-find"]}, {"id": "doctor", "jobs": ["crew-doctor"]}]
    out = subprocess.run(["node", "-e", f"const esc = (s) => String(s), ic = {{brain: ''}}, agentName = (a) => a.toUpperCase(), agentHref = (a) => `#/agent/${{a}}`;\n{fn}\n"
                          f"process.stdout.write(wfAgentsHtml({json.dumps(w)}, {json.dumps(cards)}))"], capture_output=True, text=True, check=True, timeout=30).stdout
    assert "Agents in this workflow" in out and re.findall(r'href="#/agent/(\w+)"', out) == ["tax", "main", "doctor"]
    page = re.search(r"^async function vWorkflow\(\) \{.*?^\}$", js, re.M | re.S)[0]
    assert page.index('id="wfagents"') < page.index('id="wfdiagram"') and "<h2>Its agents</h2>" not in page

