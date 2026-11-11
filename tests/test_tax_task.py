"""One Tasks list of the stack's whole work (TSK-51 to TSK-55: areas, the Upkeep row, one workflow one task, Home) and the
tax desk as the task Your taxes with its result in the app (TAX-09 to TAX-12). Synthetic step records, synthetic desk
outputs and fakes only: nothing here is a real document, person or amount; n8n and the NAS are fakes. The list and Home
run the app's own rendering code in node with fake state."""
import json
import os
import re
import sqlite3
import struct
import subprocess
import threading
import time
import types
import urllib.error
from pathlib import Path

import pytest
import webjs
import yaml

import areas as AR
import conductor as CD
import crew as CR
import flow_tasks as FT
import flows as FW
import tasks as TK
from test_tax import TODAY, conf, nas, read_all  # noqa: F401 (nas is the NAS fixture)

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "images/mission-control/web/static"
JS = webjs.app_js()
TASK_JS, TAX_JS, WF_JS = (STATIC / "task.js").read_text(), (STATIC / "tax.js").read_text(), (STATIC / "app-workflows.js").read_text()
TASKS_JS, RUNS_JS, SWARM_JS = (STATIC / "app-tasks.js").read_text(), (STATIC / "app-runs.js").read_text(), (STATIC / "swarm.js").read_text()
WF = {f.stem: json.loads(f.read_text()) for f in (ROOT / "n8n/workflows").glob("*.json")}
TAX_WID = WF["tax-desk"]["id"]
FLOWS = {"tax-desk", "item-home-inbox", "stack-self-test"}           # every workflow that is no crew duty's and no task's own


@pytest.fixture
def K(tmp_path, monkeypatch):
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("create table runs (id integer primary key, slug text, status text, summary text, output text, started text, ended text)")
    TK.table(c)
    CD.table(c)
    c.execute("create table flow_steps (id text primary key, task integer, created text)")
    events = []
    import missions as MM
    TK.M = types.SimpleNamespace(event=lambda *a, **k: events.append(a), log=print, valid_schedule=MM.valid_schedule, load_missions=dict,
                                 stop=threading.Event(), now=MM.now)
    monkeypatch.setattr(CD, "M", TK.M)
    monkeypatch.setattr(CR, "status", lambda: [])
    monkeypatch.setattr(TK, "CHATS", tmp_path / "chats")
    (tmp_path / "done").mkdir()
    monkeypatch.setattr(FW, "DONE", tmp_path / "done")
    rec = {}
    monkeypatch.setattr(FT, "seen", lambda: rec)
    FT._answers.clear()
    return types.SimpleNamespace(c=c, rec=rec, done=tmp_path / "done", events=events, tmp=tmp_path)


def step(K, rid, ex, kind, started, wf=TAX_WID, answer=None, **kw):
    """One step n8n sent, as the step service's records keep it; with its answer when it has settled."""
    K.rec[rid] = {"workflow": wf, "execution": ex, "kind": kind, "title": kw.pop("title", ""), "started": started, **kw}
    if answer is not None:
        (K.done / f"{rid}.json").write_text(json.dumps(answer))


def flow_id(c, stem):
    return c.execute("select id from tasks where door='flow' and ref=?", (stem,)).fetchone()["id"]


# ---------------------------------------------------------------- the app's list and Home, run in node
def blocks(names):
    """The top-level definitions of these names in the app's script, whole (a const runs until the next top-level line)."""
    lines, out = JS.split("\n"), []
    for name in names:
        i = next(i for i, ln in enumerate(lines) if re.match(rf"^(const|let|function|async function) {re.escape(name)}\b", ln))
        j = i + 1
        while j < len(lines) and (not lines[j] or lines[j][0] in " \t})]`"):
            j += 1
        out.append("\n".join(lines[i:j]))
    return out


FORMAT = re.search(r"// ---------- formatting \(TSK-31\).*?// ---------- end of formatting ----------", JS, re.S)[0]
NAMES = ("esc", "TSTATUS", "rhythmText", "firstLine", "TGROUPS", "AREAS", "ASKED", "NEEDS_T", "tRepeats", "tOver", "taskAgentOf", "tNeeds",
         "asksText", "tLive", "tRepeating", "tFailed", "tWhen", "RECENT_MS", "tGroup", "tArea", "tHref", "tMine", "tNext", "KIND_IC", "tIcon",
         "tAsked", "whenChip", "stateChip", "avatars", "tRow", "tasksGrouped", "upkeepRowHtml", "tasksListHtml", "HOME_GROUPS", "HOME_ROWS",
         "stackWords", "stackHtml", "CREW_AREAS", "CREW_IC", "crewAgent", "agentHealth")


def node(state, expr):
    script = "\n".join(['const ic = new Proxy({}, {get: (_, key) => `<svg data-icon="${key}"></svg>`}); const taskWho = (a) => a;',
                        FORMAT, "let tasksArea = '', tasksQuery = '', netMap = new Map(); const missionAgent = () => null;",
                        f"let S = {json.dumps(state)};", *blocks(NAMES), f"process.stdout.write(String({expr}));"])
    return subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True).stdout


def iso(minutes_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - 60 * minutes_ago))


def board():
    now = time.time()
    t = lambda i, title, area, status, **kw: {"id": i, "title": title, "area": area, "status": status, "door": kw.pop("door", "plan"),  # noqa: E731
                                              "ref": kw.pop("ref", str(i)), "asked": kw.pop("asked", "you"), "created": iso(600),
                                              "updated": kw.pop("updated", iso(5)), "rhythm": kw.pop("rhythm", {"type": "once"}), **kw}
    tasks = [t(1, "Which kit fits my PC?", "research", "needs_answer"),
             t(2, "Fix the share sheet", "code", "failed", updated=iso(30), error="the build failed"),
             t(3, "Copper briefing", "briefings", "running", rhythm={"type": "schedule", "schedule": "daily 06:30"}),
             t(4, "RAM upgrade to 32 GB", "shopping", "done", updated=iso(10)),
             t(5, "Your taxes", "taxes", "scheduled", door="flow", ref="tax-desk", rhythm={"type": "schedule", "schedule": "monthly on day 3, 07:00"},
               last_run={"status": "ok", "ended": iso(60 * 24 * 5)}, asks=0),
             t(6, "Swarm sync", "upkeep", "scheduled", door="crew", ref="swarm-sync", asked="stack", rhythm={"type": "schedule", "schedule": "every minute"}),
             t(7, "Tracker poll", "upkeep", "scheduled", door="crew", ref="tracker-poll", asked="stack", rhythm={"type": "schedule", "schedule": "every 5 minutes"}),
             t(8, "Nightly restart", "upkeep", "scheduled", door="crew", ref="recycle", asked="stack", rhythm={"type": "schedule", "schedule": "daily 03:50"}),
             t(9, "A chat", "research", "done", door="chat")]
    crew = [{"id": "swarm-sync", "name": "Swarm sync", "area": "upkeep", "state": "ok", "last": now - 60},
            {"id": "tracker-poll", "name": "Tracker poll", "area": "upkeep", "state": "ok", "last": now - 120},
            {"id": "recycle", "name": "Nightly restart", "area": "upkeep", "state": "failed", "last": now - 3600}]
    return {"tasks": tasks, "crew": crew}


def test_every_task_is_in_one_list_in_the_order_of_what_matters_now():
    html = node(board(), "tasksListHtml()")
    heads = [h for h in ("Needs you", "Failed", "Running now", "Recent results", "Scheduled") if h in html]
    assert heads == ["Needs you", "Failed", "Running now", "Recent results", "Scheduled"]
    pos = {x: html.index(x) for x in ("Which kit fits", "Fix the share sheet", "Copper briefing", "RAM upgrade", "Your taxes")}
    assert sorted(pos, key=pos.get) == ["Which kit fits", "Fix the share sheet", "Copper briefing", "RAM upgrade", "Your taxes"]
    assert "A chat" not in html                                                 # a chat lives on Chat
    assert ">Briefings<" in html and ">Taxes<" in html and "you asked" in html   # its area and who asked, as information
    for gone in ('["you", "User"]', "tasksOwner", "netOwner", "data-to=", "data-no="):
        assert gone not in JS, gone                                              # no yours/stack filter anywhere
    body = blocks(["tasksBodyHtml"])[0]
    assert "data-tarea" in body and "phoneBanner()" in body                     # the areas as an optional filter
    state = TK.state.__doc__ and Path(TK.__file__).read_text()
    assert '"area": area_of(c, t), "asked": asked_by(t)' in state


def test_upkeep_is_one_row_with_its_health_and_a_failing_job_shows_alone():
    html = node(board(), "tasksListHtml()")
    failed = html[html.index("Failed"):html.index("Running now")]
    assert "Nightly restart" in failed                                           # failure is never folded away
    row = html[html.index('class="card tupkeep"'):]
    assert "3 jobs, " in row and "1 failing: Nightly restart" in row and "last run 1 min ago" in row
    assert all(x in row for x in ("Swarm sync", "Tracker poll"))                 # a tap opens them as rows
    assert "Swarm sync" not in html[:html.index('class="card tupkeep"')]          # a fine job only in the row
    fine = board()
    fine["crew"][2]["state"] = "ok"
    assert "3 jobs, all fine" in node(fine, "tasksListHtml()")
    assert 'class="card tupkeep"' not in node(board(), "(tasksArea = 'upkeep', tasksListHtml())")   # picked: its jobs as rows


def test_home_shows_what_is_going_on_across_the_stack():
    html = node(board(), "stackHtml()")
    for part, title in (("Running now", "Copper briefing"), ("Waiting for you", "Which kit fits"), ("Failed", "Nightly restart"), ("Done today", "RAM upgrade")):
        assert part in html and title in html, part
    assert 'href="#/task/3"' in html and 'href="#/crew/recycle"' in html         # each row opens its task
    assert "3 jobs, 1 failing" in html and 'href="#/tasks?area=upkeep"' in html
    home = blocks(["vHome"])[0]
    assert "${needsHtml()}${stackHtml()}${nowHtml()}" in home
    assert "NOT_YOURS" not in JS and "const QUIET = (t) => t.area === \"upkeep\"" in JS   # Results: every area, upkeep when it fails


# ---------------------------------------------------------------- TSK-52 areas
def test_every_workflow_and_crew_job_declares_its_area(tmp_path):
    for stem, wf in WF.items():
        assert wf.get("area") in AR.AREAS, f"{stem}.json declares no area"
    for a in CR.CREW:
        assert a.get("area") in AR.AREAS, f"crew job {a['id']} declares no area"
    by = {a["id"]: a["area"] for a in CR.CREW}
    assert by["mail-sort"] == "mail" and by["tax-find"] == by["tax-file"] == "taxes" and by["memory"] == "memory"
    assert {by[j] for j in ("graphify-sync", "memory-review", "swarm-sync", "tracker-poll", "recycle", "rotation", "backup")} == {"upkeep"}
    for stem, wf in WF.items():                                   # a crew job's workflow is its job's area
        steps = [n["parameters"] for n in wf["nodes"] if n["type"] == "CUSTOM.aistackStep"]
        if len(steps) == 1 and steps[0].get("kind") == "crew":
            assert wf["area"] == by[steps[0]["job"]], stem
    assert WF["tax-desk"]["area"] == "taxes" and WF["item-home-inbox"]["area"] == "inbox"
    import n8n_gen as G                                           # the generator writes it
    assert G.workflow("task", 7, "Task #7: News", "30 6 * * *", {"kind": "task", "task": 7}, "", area="briefings")["area"] == "briefings"
    assert G.workflow("crew", "doctor", "Crew: Health doctor", "0 */6 * * *", {"kind": "crew", "job": "doctor"}, "")["area"] == "upkeep"
    assert json.loads(G.chain("Area test", "0 6 * * 1", ["crew:tax-find=First"], out=tmp_path, area="taxes").read_text())["area"] == "taxes"
    with pytest.raises(SystemExit):
        G.chain("No area", "0 6 * * 1", ["crew:tax-find=First"], out=tmp_path)
    with pytest.raises(ValueError):
        G.workflow("task", 8, "Task #8", "30 6 * * *", {"kind": "task", "task": 8}, "", area="crypto")
    import n8n_jobs as NJ
    assert "area=AR.of_kind(t.get(\"kind\"))" in Path(NJ.__file__).read_text()   # a task's workflow: its task's kind


def test_a_task_s_area_comes_from_what_it_is_for(K):
    c = K.c
    assert AR.of_kind("briefing") == "briefings" and AR.of_kind("change") == "code" and AR.of_kind(None) == "research"
    TK.discover_crew(c)
    TK.discover_flows(c)
    rows = {(r["door"], r["ref"]): dict(r) for r in c.execute("select * from tasks")}
    area = lambda door, ref: TK.area_of(c, TK.row(c, rows[(door, ref)]["id"]))  # noqa: E731
    assert area("crew", "mail-sort") == "mail" and area("crew", "swarm-sync") == "upkeep" and area("flow", "tax-desk") == "taxes"
    assert area("flow", "stack-self-test") == "upkeep" and area("flow", "item-home-inbox") == "inbox"
    t = TK.create({"text": "Every morning a briefing on copper mining news", "kind": "briefing"}, c)["task"]
    assert TK.area_of(c, TK.row(c, t)) == "briefings"
    run = TK.register(c, "workflow", f"n8n:{TAX_WID}/7", "reads", "Read them", source="crew:n8n")
    assert TK.area_of(c, TK.row(c, run)) == "taxes"
    tr = TK.create({"text": "Build the mustache library from its specification", "source": "trial:mustache"}, c)["task"]
    assert TK.area_of(c, TK.row(c, tr)) == "code"
    TK.discover(c, {"u": {"slug": "u", "title": "Copper", "type": "briefing", "status": "active", "schedule": "daily 06:30"}})
    assert TK.area_of(c, TK.row(c, c.execute("select id from tasks where door='mission'").fetchone()["id"])) == "briefings"
    asked = {r["ref"]: TK.asked_by(dict(r)) for r in c.execute("select ref, source, owner from tasks where door='crew'")}
    assert asked["mail-sort"] == "you" and asked["swarm-sync"] == "stack"          # who asked: information, from the area


def test_a_crew_duty_and_a_workflow_s_run_are_their_owner_s(K):
    """TSK-40's owner stays as information (who asked): the stack's own upkeep, everything else asked for."""
    c = K.c
    assert TK.owner_of(c, "crew", "crew", "mail-sort") == "you" and TK.owner_of(c, "crew", "crew", "doctor") == "stack"
    assert TK.owner_of(c, "crew:n8n", "workflow", f"n8n:{TAX_WID}/9") == "you"
    assert TK.owner_of(c, "crew:n8n", "workflow", f"n8n:{WF['stack-self-test']['id']}/9") == "stack"


# ---------------------------------------------------------------- TSK-54 one workflow, one task
def test_each_workflow_is_one_task_with_its_runs_and_result(K, monkeypatch):
    c = K.c
    TK.discover_crew(c)
    TK.discover_flows(c)
    TK.discover_flows(c)                                                               # once per workflow
    rows = {r["ref"]: dict(r) for r in c.execute("select * from tasks where door='flow'")}
    assert set(rows) == FLOWS and all(r["status"] == "scheduled" for r in rows.values())
    assert {r["title"] for r in rows.values()} == {"Your taxes", "Your inbox: an answer to each new item", "Stack self-test"}
    assert TK.detail(c, rows["item-home-inbox"]["id"])["agent"] == "main"
    crew = {r["ref"] for r in c.execute("select ref from tasks where door='crew'")}
    assert {"mail-sort", "memory", "inbox"} <= crew                                    # a crew job's workflow is its duty's task
    mail = next(x for x in TK.state(c)["tasks"] if x["door"] == "crew" and x["ref"] == "mail-sort")
    assert mail["result_href"] == "#/mail" and mail["result_label"] == "Your mail" and mail["area"] == "mail"
    assert "crewResultHtml(c.id)" in TASKS_JS and "Its result" in TASK_JS                # its result one tap away
    gone = {s: w for s, w in FT.flows().items() if s != "stack-self-test"}
    monkeypatch.setattr(FT, "flows", lambda repo=None, made=None: gone)              # a workflow gone from the deployment
    FT.sync(c)
    assert c.execute("select status from tasks where door='flow' and ref='stack-self-test'").fetchone()["status"] == "cancelled"


def test_older_runs_of_a_workflow_keep_their_history(K):
    c = K.c
    old = TK.register(c, "workflow", f"n8n:{TAX_WID}/12", "Reads the papers", "Read them (Hermes, ChatGPT)", source="crew:n8n")
    c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts, started, ended, output) "
              "values (?,1,1,'Read them','','tax','tax-read','gpt-sub','[]','','done',1,'2026-11-01T20:01:00+01:00','2026-11-01T20:20:00+01:00','Read 4 mails')", (old,))
    step(K, "n1", "40", "crew", "2026-11-10T20:00:00+01:00", job="tax-find", answer={"status": "done", "output": "2 new to read"})
    TK.discover_flows(c)
    d = TK.detail(c, flow_id(c, "tax-desk"))
    assert [r["execution"] for r in d["runs"]] == ["40", "12"]                         # the run the step records forgot, kept
    first = d["steps"]["1"]
    assert first[1]["status"] == "done" and first[1]["output"] == "Read 4 mails" and first[1]["live"] == f"task:{old}:step:1"
    assert c.execute("select count(*) from tasks where id=?", (old,)).fetchone()[0] == 1   # nothing deleted
    assert old not in {x["id"] for x in TK.state(c)["tasks"]}                            # and not listed on its own


# ---------------------------------------------------------------- TAX-09 the task
def test_your_taxes_is_one_task_with_the_workflow_s_runs_as_its_runs(K):
    c = K.c
    step(K, "a1", "41", "crew", "2026-11-10T20:00:00+01:00", job="tax-find", title="Find tax papers",
         answer={"status": "done", "output": "12 candidates by their headers (n 3, sonstige 9); 12 new to read"})
    step(K, "a2", "41", "agent", "2026-11-10T20:01:00+01:00", agent="tax", title="Read them (Hermes, ChatGPT)",
         answer={"status": "done", "output": "Read with Hermes (ChatGPT): 10 mails sorted, 2 unclear"})
    c.execute("insert into flow_steps values ('a2', 77, '2026-11-10')")
    step(K, "a3", "41", "crew", "2026-11-10T20:30:00+01:00", job="tax-file", title="File copies and prepare the drafts",
         answer={"status": "done", "output": "3 new copies in Steuern. 2025 (open): 3 papers (Anlage N 1); 1 expected papers missing"})
    step(K, "b1", "42", "crew", "2026-11-11T07:00:00+01:00", job="tax-find", answer={"status": "done", "output": "0 new to read"})
    step(K, "b2", "42", "agent", "2026-11-11T07:05:00+01:00", agent="tax")             # still reading
    TK.discover_flows(c)
    t = dict(c.execute("select * from tasks where door='flow' and ref='tax-desk'").fetchone())
    assert t["title"] == "Your taxes" and t["kind"] == "tax" and t["status"] == "running"
    assert json.loads(t["rhythm"]) == {"type": "schedule", "schedule": "monthly on day 3, 07:00"}   # on since its first run (10 Nov)
    row = next(x for x in TK.state(c)["tasks"] if x["id"] == t["id"])
    assert [r["occ"] for r in row["runs"]] == [2, 1] and row["agent"] == "tax" and row["result_view"] == "tax" and row["workflow"] == TAX_WID
    assert row["area"] == "taxes" and [s["status"] for s in row["steps"]] == ["done", "running", "pending"]
    d = TK.detail(c, t["id"])
    one = d["steps"]["1"]
    assert [s["title"] for s in one] == ["Find the tax papers", "Read the papers (ChatGPT)", "File the copies and prepare the drafts"]
    assert one[1]["live"] == "task:77:step:1" and one[0]["href"] == "#/crew/tax-find" and d["runs"][1]["tasks"] == [77]
    assert d["runs"][1]["status"] == "done" and d["runs"][1]["result"].startswith("3 new copies")
    assert [p["agent"] for p in d["plan"]] == ["crew:tax-find", "tax", "crew:tax-file"]
    assert 't.door === "flow" && t.workflow' in WF_JS and "s.live ||" in TASK_JS                 # Where it runs, each step's log
    import runrecord as RT
    assert 'door == "flow"' in Path(RT.__file__).read_text()                                    # its reader's runs are its agents'


def test_the_desk_s_crew_duties_and_reader_tasks_leave_the_lists(K):
    c = K.c
    TK.discover_crew(c)
    reader = TK.register(c, "workflow", f"n8n:{TAX_WID}/41", "Reads the papers", "Read them (Hermes, ChatGPT)", source="crew:n8n")
    probe = TK.register(c, "workflow", f"n8n:{WF['stack-self-test']['id']}/5", "Ask the scout", "Ask the scout", source="crew:n8n")
    TK.discover_flows(c)
    ids = {x["id"] for x in TK.state(c)["tasks"]}
    crew = {r["ref"]: r["id"] for r in c.execute("select id, ref from tasks where door='crew'")}
    assert not {crew["tax-find"], crew["tax-file"], reader, probe} & ids                     # the steps of a workflow's task
    assert {crew["mail-sort"], crew["memory"], crew["doctor"]} <= ids and {flow_id(c, s) for s in FLOWS} <= ids
    assert "t.asks > 0" in TASKS_JS and 'tax: "coin"' in TASKS_JS


def test_run_now_on_your_taxes_starts_its_workflow(K, monkeypatch):
    c = K.c
    TK.discover_flows(c)
    tid = flow_id(c, "tax-desk")
    off = {**WF["tax-desk"], "active": False}                                      # a workflow switched off says so
    monkeypatch.setattr(FT, "workflow", lambda stem, repo=None, made=None: off)
    with pytest.raises(ValueError, match="switched off"):
        TK.handle({"action": "task_run", "id": tid}, c)
    wf = {**WF["tax-desk"], "active": True}
    monkeypatch.setattr(FT, "workflow", lambda stem, repo=None, made=None: wf)
    posted = []
    monkeypatch.setattr(FT, "_post", posted.append)
    r = TK.handle({"action": "task_run", "id": tid}, c)
    assert posted == ["http://127.0.0.1:5678/webhook/run/tax-desk"] and r["message"].startswith("Started")

    def refused(url):
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)
    monkeypatch.setattr(FT, "_post", refused)
    with pytest.raises(ValueError, match="did not start"):
        TK.handle({"action": "task_run", "id": tid}, c)
    with pytest.raises(ValueError, match="Workflows"):
        TK.handle({"action": "task_cancel", "id": tid}, c)
    assert "data-tflow" in TASK_JS and "Run now" in TASK_JS


# ---------------------------------------------------------------- TAX-10 the result
def test_the_result_view_shows_each_year_from_the_desk_s_outputs(nas, monkeypatch):  # noqa: F811
    import deployment as DEPLOY
    import tax as TX
    import tax_view as VIEW
    read_all(nas)
    TX.file(conf=conf(), call=nas["call"], today=TODAY)
    monkeypatch.setattr(TX, "share", lambda: "/volume1/Shared_Data/Steuern")
    monkeypatch.setitem(DEPLOY.VALUES, "NAS_HOST", "nas.example")
    v = VIEW.build(conf(), TODAY)
    years = {y["year"]: y for y in v["years"]}
    assert list(years) == sorted(years, reverse=True) and {2024, 2025, 2026} <= set(years)
    pdf = "2026-02-09_Arbeitgeber-Beispiel-GmbH_Lohnsteuerbescheinigung.pdf"
    y = years[2025]
    assert y["prepared"] and y["open"] and y["total"] == 1 and y["papers"] == [{"form": "n", "name": conf()["forms"]["n"]["name"], "n": 1}]
    assert any(ln["label"] == "Bruttoarbeitslohn" and ln["sum"] == 41000.0 and ln["papers"] == [pdf] for ln in y["lines"])
    b = y["belege"][0]
    assert b["name"] == pdf and b["amount"] == 41000.0 and b["nas"] == "\\\\nas.example\\Shared_Data\\Steuern\\2025\\Anlage-N\\" + pdf
    assert [m["label"] for m in y["missing"]] == ["Haftpflichtversicherung"] and y["missing"][0]["last_year"] == 2024
    assert y["questions"] and all(q["id"].startswith("2025:") and q["text"] for q in y["questions"])
    assert "not tax advice" in y["workbook"] and y["files"]["folder"] == "\\\\nas.example\\Shared_Data\\Steuern\\2025"
    assert y["files"]["workbook"].endswith("\\2025\\Steuer-2025.md") and y["files"]["belege"].endswith("\\2025\\Belege.csv")
    r = years[2024]["return"]
    assert r["assessment"] == "single" and [i["label"] for i in r["items"]] == ["Bruttoarbeitslohn", "Haftpflichtversicherung"]
    assert "2024" in years[2024]["erklaerung"] and years[2024]["files"]["erklaerung"].endswith("Erklaerung-2024.md")
    assert v["draft"].startswith("A draft for your own ELSTER return, not tax advice") and "**" not in v["draft"]
    shared = []
    monkeypatch.setattr(VIEW, "publish", lambda view, **k: shared.append(view))
    TX.answer({"id": "2025:assessment", "answer": "Single"})                 # an answer leaves the view at once
    after = {y["year"]: y for y in shared[-1]["years"]}[2025]
    assert "2025:assessment" not in [q["id"] for q in after["questions"]] and len(after["questions"]) == len(y["questions"]) - 1


def test_the_task_page_shows_the_result_and_its_files_as_pages():
    for part in ("Papers found", "Sums per form line", "Missing", "Questions for you", "Answer in Needs you", "as read", "The workbook",
                 "Belege", "data-tcopy", "d.draft"):
        assert part in TAX_JS, part
    assert "taxViewInto($(\"#tresult\", box), t)" in TASK_JS and "localStorage" not in TAX_JS      # never kept on the device
    base = (STATIC / "app-base.js").read_text()
    assert "tax: vTax" in base and '"tax"].includes(route.name)' in base
    web = ROOT / "images/mission-control/web"
    assert '<script src="/static/tax.js"></script>' in (web / "index.html").read_text() and '"/static/tax.js"' in (web / "sw.js").read_text()
    guide = (ROOT / "images/mission-control/guide/23-taxes.md").read_text()
    assert "views: [tax]" in guide and "Your taxes" in guide


# ---------------------------------------------------------------- TAX-11 for the owner only
def test_the_view_is_shared_with_the_app_s_user_alone(tmp_path):
    import tax_view as VIEW
    p = VIEW.publish({"years": []}, out=tmp_path / "tax", uid=10006)
    assert json.loads(p.read_text()) == {"years": []}
    for path, perm in ((p, 4), (p.parent, 5)):
        entries = {tag: (perms, uid) for tag, perms, uid in struct.iter_unpack("<HHI", os.getxattr(path, VIEW.ACL_KEY)[4:])}
        assert entries[VIEW.USER] == (perm, 10006) and entries[VIEW.GROUP_OBJ][0] == 0 and entries[VIEW.OTHER][0] == 0
        assert path.stat().st_mode & 0o007 == 0                                    # nobody else
    assert VIEW.app_uid(tmp_path) == tmp_path.stat().st_uid
    (tmp_path / "tax" / VIEW.NAME).unlink()

    def no_acl(path, key, value):
        if path.endswith(".tmp"):
            raise OSError(95, "Operation not supported")
        os.setxattr(path, key, value)
    with pytest.raises(OSError):
        VIEW.publish({"years": [{"year": 2025}]}, out=tmp_path / "tax", uid=10006, setx=no_acl)
    assert list((tmp_path / "tax").iterdir()) == []                               # fail closed: no view, no half file
    said = []
    assert VIEW.refresh(say=said.append) is False and "(" in said[0] and not re.search(r"\d", said[0])   # said by its kind, the desk goes on


def test_the_figures_reach_only_the_owner_s_signed_in_session(tmp_path, monkeypatch):
    import server as S
    from starlette.testclient import TestClient
    monkeypatch.setattr(S, "TAX_VIEW", tmp_path / "view.json")
    c = TestClient(S.app)
    owner = {"Tailscale-User-Login": "owner@test"}
    assert c.get("/api/tax").status_code == 403                                   # no sign-in
    assert c.get("/api/tax", headers=owner).json() == {"years": [], "made": None}
    (tmp_path / "view.json").write_text(json.dumps({"years": [{"year": 2025, "total": 1}], "made": "2026-11-11T08:00:00+01:00"}))
    r = c.get("/api/tax", headers=owner)
    assert r.json()["years"][0]["year"] == 2025 and r.headers["cache-control"] == "no-store"
    assert c.get("/api/tax", headers={"Tailscale-User-Login": "journeys@stack.local"}).status_code == 403
    monkeypatch.setattr(S, "from_ai_phone", lambda request: True)
    assert c.get("/api/tax", headers=owner).status_code == 403                    # PHN-07


def test_no_figure_reaches_the_board_or_its_pages(K, monkeypatch):
    c = K.c
    step(K, "a3", "41", "crew", "2026-11-10T20:30:00+01:00", job="tax-file",
         answer={"status": "done", "output": "3 new copies in Steuern. 2025 (open): 3 papers (Anlage N 1); 1 expected papers missing; 2 questions open"})
    import tax as TX
    monkeypatch.setattr(TX, "HOME", K.tmp / "taxhome")
    TX.save("questions.json", [{"id": "2025:assessment", "year": 2025, "text": "Assessed alone or jointly?", "answers": ["Single"], "ask": None}])
    TK.discover_flows(c)
    tid = flow_id(c, "tax-desk")
    row = next(x for x in TK.state(c)["tasks"] if x["id"] == tid)
    d = TK.detail(c, tid)
    assert row["asks"] == d["asks"] == 1                                          # a count, never the question's text
    for data in (row, d):
        text = json.dumps(data)
        assert not re.search(r"\d+[.,]\d\d\b", text) and "Assessed alone" not in text
        assert not {"lines", "belege", "workbook", "years"} & set(data)
    readers = [p.name for p in (ROOT / "images/mission-control").glob("*.py") if "tax/view.json" in p.read_text()]
    assert readers == ["server.tax.py"]                                          # not in the state every screen gets


# ---------------------------------------------------------------- TAX-12 the reader
def test_the_tax_reader_has_its_name_and_shows_where_it_belongs(K):
    card = next(a for a in yaml.safe_load((ROOT / "config/agents.yaml").read_text())["agents"] if a["id"] == "tax")
    assert card["name"] == "Tax reader" and "ChatGPT only, no tools" in card["purpose"] and "Tax desk" in card["purpose"]
    assert card["tools"] == [] and card["model"] == "gpt-sub"
    c = K.c
    TK.discover_flows(c)
    st = TK.state(c)
    assert next(a for a in st["task_agents"] if a["id"] == "tax")["name"] == "Tax reader"
    assert next(x for x in st["tasks"] if x["door"] == "flow" and x["ref"] == "tax-desk")["plan"][1]["agent"] == "tax"   # Tasks it did steps for
    assert next(a for a in FW.step_agents() if a["id"] == "tax")["name"] == "Tax reader"                                # the node's picker
    assert "cardName(a)" in RUNS_JS and "cardName(id)" in SWARM_JS and "esc(swName(a.id))" in SWARM_JS
    assert 'wfInInto($("#swwfin", box), "agent", id)' in SWARM_JS                                                         # its workflow
