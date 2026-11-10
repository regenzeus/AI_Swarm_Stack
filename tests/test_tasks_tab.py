"""Everything is a task (DEC-46): a task is yours or the stack's (TSK-40), every mission is a task for good (TSK-41), each
crew duty is the stack's repeating task (TSK-42), the run record says which agents worked on which task (TSK-43), New
task keeps exactly what it was given (TSK-44); the Tasks tab with its five views and its Network (APP-52, APP-53) and
Home's honest count (APP-54)."""
import webjs
import json
import re
import sqlite3
import threading
import types
from pathlib import Path

import pytest

import claude_tasks as CT
import tasks as TK

STATIC = Path(__file__).resolve().parent.parent / "images/mission-control/web/static"
JS, CSS = webjs.app_js(), (STATIC / "app.css").read_text()
SWARM = (STATIC / "swarm.js").read_text()


@pytest.fixture
def K(tmp_path, monkeypatch):
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("create table runs (id integer primary key, slug text, status text, summary text, output text, started text, ended text)")
    CT.table(c)
    TK.table(c)
    import missions as MM
    TK.M = types.SimpleNamespace(event=lambda *a, **k: None, valid_schedule=MM.valid_schedule, load_missions=dict, stop=threading.Event(), log=print,
                                 now=MM.now)
    monkeypatch.setattr(TK, "CHATS", tmp_path / "chats")
    return c


def owner(c, tid):
    return c.execute("select owner from tasks where id=?", (tid,)).fetchone()["owner"]


def test_a_task_is_yours_or_the_stack_s_by_who_gave_it(K):
    c = K
    yours = TK.create({"text": "Find the cheapest 32 GB kit for my PC"}, c)["task"]
    trial = TK.create({"text": "Build the mustache library from its specification", "source": "trial:mustache"}, c)["task"]
    rule = TK.create({"text": "Tell me what this filing means for my copper positions", "source": "rule:2"}, c)["task"]
    assert (owner(c, yours), owner(c, trial), owner(c, rule)) == ("you", "stack", "you")   # your rules' tasks are yours
    c.execute("insert into claude_tasks (question, status, created, source) values ('You are the Health doctor ...', 'done', '2026-11-08', 'crew:doctor')")
    c.execute("insert into claude_tasks (question, status, created, source) values ('Which file serves /api/stats?', 'done', '2026-11-08', 'chat')")
    doc, mine = (TK.register(c, "claude", i, q, q) for i, q in ((1, "You are the Health doctor ..."), (2, "Which file serves /api/stats?")))
    assert (owner(c, doc), owner(c, mine)) == ("stack", "you")              # the doctor's question is the stack's, not on your board
    c.execute("update tasks set owner=null")                                 # tasks from before owners get theirs
    TK.own(c)
    assert [owner(c, t) for t in (yours, trial, rule, doc, mine)] == ["you", "stack", "you", "stack", "you"]
    assert "owner" in TK.FIELDS                                              # the board and a task's page carry it


def test_every_mission_is_a_task_for_good_and_an_archived_one_is_done(K):
    c = K
    old = {"slug": "copper", "title": "Copper", "type": "briefing", "status": "active", "schedule": "daily 06:30", "created": "2026-10-01T06:00:00+01:00"}
    gone = {"slug": "job-report", "title": "Job report", "type": "briefing", "status": "archived", "schedule": "daily 06:30", "created": "2026-10-02T06:00:00+01:00"}
    own_agent = {"slug": "ram-buy", "title": "RAM", "type": "shopping", "status": "active", "task": 9, "created": "2026-11-07T06:00:00+01:00"}
    TK.discover(c, {m["slug"]: m for m in (old, gone, own_agent)})
    rows = {r["ref"]: dict(r) for r in c.execute("select ref, status, rhythm, owner, updated from tasks where door='mission'")}
    assert set(rows) == {"copper", "job-report"}                            # a month old is still a task; a task's own agent is that task
    assert json.loads(rows["copper"]["rhythm"]) == {"type": "schedule", "schedule": "daily 06:30"} and rows["copper"]["owner"] == "you"
    assert rows["job-report"]["status"] == "done" and rows["job-report"]["updated"].startswith("2026-10-02")   # not on this week's board


def test_each_crew_duty_is_the_stack_s_repeating_task(K, monkeypatch):
    import crew as CR
    monkeypatch.setattr(CR, "status", lambda: [{"id": "memory", "schedule": "daily 04:30"}, {"id": "checker", "schedule": "every 1h"}])
    TK.discover_crew(K)
    TK.discover_crew(K)                                                     # once per duty
    rows = {r["ref"]: dict(r) for r in K.execute("select ref, title, status, rhythm, owner, source from tasks where door='crew'")}
    want = {a["id"] for a in CR.CREW if not a.get("oneoff")}
    assert set(rows) == want and all(r["owner"] == "stack" and r["status"] == "scheduled" and r["source"] == "crew" for r in rows.values())
    assert rows["memory"]["title"] == "Memory Keeper" and json.loads(rows["memory"]["rhythm"])["schedule"] == "daily 04:30"
    assert json.loads(rows["backup"]["rhythm"])["schedule"] == "on its workflow"       # a duty whose schedule is not read yet
    monkeypatch.setattr(CR, "status", lambda: [{"id": "memory", "schedule": "daily 03:30"}])
    TK.discover_crew(K)                                                     # a changed schedule follows
    assert json.loads(K.execute("select rhythm from tasks where door='crew' and ref='memory'").fetchone()["rhythm"])["schedule"] == "daily 03:30"


def test_new_task_keeps_the_kind_the_when_and_the_delivery_it_was_given(K, monkeypatch):
    import mission_extras as X
    monkeypatch.setattr(TK, "B_repos", lambda: [])
    p = TK.preset_of({"kind": "cleanup", "rhythm": {"type": "event", "triggers": [{"type": "news", "query": "Acme Mining contract"}]}, "deliver": ["email", "app", "fax", "app"]})
    assert p["kind"] == "cleanup" and p["rhythm"] == {"type": "event", "triggers": X.clean_triggers([{"type": "news", "query": "Acme Mining contract"}])}
    assert p["deliver"] == ["email", "app"]                                  # only places results can go, once each
    with pytest.raises(ValueError, match="say what starts it"):
        TK.preset_of({"rhythm": {"type": "event", "triggers": []}})
    assert "rhythm" not in TK.preset_of({}) and "deliver" not in TK.preset_of({})   # nothing set: the intake reads it from the words
    assert TK.KINDS["cleanup"] == "mission" and TK.MISSION_TYPE["cleanup"] == "cleanup"
    t = {"rhythm": {"type": "once"}, "kind": "cleanup", "spec": {"plan": [{"agent": "mission"}]}}
    assert TK.conducted(t) is False                                          # a cleanup analysis is ops/cleanup.py's, never a plan's


def test_the_network_names_each_run_s_task_and_keeps_tools_and_the_conductor_apart(tmp_path, monkeypatch):
    import runrecord as RT
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    now = 2_000_000_000.0
    rows = [("task:5", None, "conductor", now - 600, now - 60), ("task:5:step:1", "task:5", "scout", now - 590, now - 300),
            ("task:5:step:2", "task:5", "mission:x", now - 290, None),                       # at work now
            ("task-intake:7-0", None, "intake", now - 500, now - 490), ("build:31:1", "task-intake:7-0", "claude-builder", now - 480, now - 100),
            ("mission-run:9", None, "mission:copper", now - 400, now - 300), ("hermes:scout:a", "mission-run:9", "scout", now - 390, now - 350),
            ("build:12:1", None, "builder", now - 300, now - 200), ("claude-task:4", None, "claude-task", now - 200, now - 100),
            ("hermes:main:q", "chat:abc", "main", now - 100, now - 90), ("phone:1", "hermes:main:q", "ai-phone", now - 95, now - 92),
            ("crew-memory:1", None, "crew:memory", now - 80, now - 70), ("mail:1", None, "mail", now - 50, now - 40),
            ("hermes:main:z", None, "main", now - 30, now - 20), ("task:99", None, "conductor", now - 20, now - 10),
            ("task:99:step:1", "task:99", "scout", now - 19, now - 11), ("task:5:old", "task:5", "scout", now - 99 * 86400, now - 99 * 86400)]
    c = RT.db()
    c.executemany("insert into runs (run, ref, agent, started, ended) values (?,?,?,?,?)", rows)
    c.commit()
    board = [{"id": 5}, {"id": 7, "door": "plan", "ref": "7"}, {"id": 11, "door": "mission", "ref": "copper"}, {"id": 12, "door": "build", "ref": "12"},
             {"id": 14, "door": "claude", "ref": "4"}, {"id": 15, "door": "chat", "ref": "abc"}, {"id": 16, "door": "crew", "ref": "memory"}]
    n = RT.network(board, days=7, now=now)
    tasks = {t["id"]: t for t in n["tasks"]}
    agents_of = {k: [g["agent"] for g in t["agents"]] for k, t in tasks.items()}
    assert agents_of[5] == ["scout", "mission"] or sorted(agents_of[5]) == ["mission", "scout"]      # the Conductor is no agent
    assert tasks[5]["live"] and next(g for g in tasks[5]["agents"] if g["agent"] == "mission")["live"]
    assert agents_of[7] == ["builder", "intake"] or sorted(agents_of[7]) == ["builder", "intake"]     # a change request's steps under its intake run
    assert sorted(agents_of[11]) == ["mission", "scout"] and agents_of[12] == ["builder"] and agents_of[14] == ["claude"]
    assert agents_of[15] == ["main"] and tasks[15]["tools"] == {"phone": 1}                          # the AI phone is a tool of the chat's task
    assert agents_of[16] == ["memory"]                                                              # a crew duty's runs are its task's
    assert n["outside"] == {"gmail": 1, "main": 1} and n["elsewhere"] == 1                           # no task holds them; task 99 is off the board
    by = {a["agent"]: a for a in n["agents"]}
    assert by["scout"]["tasks"] == [5, 11] and "conductor" not in by and "phone" not in by


def test_the_tasks_tab_has_five_views_and_the_old_addresses_go_there():
    nav = re.search(r"^const NAV = .*?;$", JS, re.M | re.S)[0]
    assert '["tasks", "#/tasks", "Tasks", ic.tasks]' in nav and '"#/missions"' not in nav and len(re.findall(r'\["\w+", "#/', nav)) == 7   # Workflows (n8n inside the app, WFL-11) is the seventh
    assert re.search(r'const TVIEWS = \[\["tasks", "Tasks"\], \["activity", "Activity"\], \["team", "Team"\], \["network", "Network"\], \["ideas", "Ideas"\]\];', JS)
    assert 'const TLISTS = [["active", "Active"], ["repeating", "Repeating"], ["done", "Done"]];' in JS and '[["you", "User"], ["stack", "Stack"], ["all", "All"]]' in JS and 'tasksOwner = "all"' in JS
    assert "missions: vMissionsGo" in JS and "new: vNewGo" in JS and "function vMissions()" not in JS and "function vNew()" not in JS
    go = JS.split("function vMissionsGo() {", 1)[1].split("\n}", 1)[0]
    assert '"#/tasks?v=team&p=crew"' in go and '"#/tasks?v=activity"' in go
    assert 'location.replace("#/tasks?" + q.toString()' in SWARM and 'const SW_VIEW = { activity: "activity", agents: "team", map: "network", improve: "ideas"' in SWARM
    assert 'swOn("activity")' in SWARM and 'route.name === "swarm" && swTab' not in SWARM            # the agents' views live in the Tasks tab now
    row = JS.split("function tRow(t) {", 1)[1].split("\n}", 1)[0]
    assert all(x in row for x in ("stateChip(t, A)", "whenChip(t)", "avatars(t)", "tHref(t)"))     # where it stands, its When, its agents
    assert 'const tMine = (t) => t.door !== "chat" && (tasksOwner === "all" || (tasksOwner === "stack") === (t.owner === "stack"));' in JS
    assert "[\"agents\", \"Agents\"]" in JS and "taskAgentsInto(box, task.id)" in JS                # a mission's page is its task's page
    assert '"Your task" : "The stack\'s task"' in JS and '#/tasks?v=team&p=crew" : "#/tasks"' in JS


def test_new_task_is_one_form_that_sends_only_what_was_set():
    form = JS.split("function newTaskHtml() {", 1)[1].split("\n}", 1)[0]
    for k in ('"briefing", "Briefing"', '"research", "Research"', '"shopping", "Shopping"', '"cleanup", "Cleanup"', '"", "The stack decides"'):
        assert k in JS.split("const TNEW_KINDS", 1)[1].split("\n", 1)[0]
    assert all(x in form for x in ('name="rtype"', "schedHtml(", "trigEditor(", 'name="after"', 'name="d_${k2}"', "tAgents()", 'name="done"'))
    send = JS.split("function bindNewTask() {", 1)[1].split("\n}", 1)[0]
    assert 'if (kind) req.kind = kind;' in send and 'req.rhythm = { type: "event", triggers: tr }' in send
    assert 'if (dl.join() !== "telegram,app") req.deliver = dl;' in send                  # untouched: e-mail when the words ask for it
    assert "else if (w === \"once\") req.rhythm" in send and "req.rhythm = { type: \"once\" };\n" not in send.split("else if (w === \"once\")")[0]


def test_a_tool_session_names_its_caller(tmp_path, monkeypatch):
    """TSK-43: mail and the AI phone can't see who called them; the caller's run recorded the call a moment before."""
    import runrecord as RT
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    now = 2_000_000_000.0
    ev = lambda run, agent, kind, ts, title="", **k: {"run": run, "agent": agent, "kind": kind, "ts": ts, "title": title, **k}
    RT.ingest([ev("crew:postmaster:1", "crew:postmaster", "run", now, "started", run_title="Postmaster"),
               ev("crew:postmaster:1", "crew:postmaster", "call", now + 1, "mail-mail_search"),
               ev("mail:1", "mail", "run", now + 2, "started", run_title="Gmail"),                     # opened by the call
               ev("phone:1", "ai-phone", "run", now + 600, "started", run_title="AI phone"),           # its own reconnect
               ev("phone:2", "ai-phone", "run", now + 900, "started", run_title="AI phone"),           # opened before its caller's call came in
               ev("mission-run:9", "mission:shop", "run", now + 880, "started"),
               ev("mission-run:9", "mission:shop", "wait", now + 899, "the AI phone (app search): ready"),
               ev("phone:2", "ai-phone", "end", now + 950, "session ended", status="done")])
    ref = {r["run"]: r["ref"] for r in RT.db().execute("select run, ref from runs")}
    assert ref["mail:1"] == "crew:postmaster:1" and ref["phone:1"] is None and ref["phone:2"] == "mission-run:9"


def test_who_worked_on_a_mission_s_task_names_the_agent_not_the_task(tmp_path, monkeypatch):
    """APP-35 (the owner, 8 Nov 2026: "who worked on it is bugged, always shows the same"): a mission's runs are recorded
    as mission:<slug>; its task's page drew one bubble named after the task. They are the mission agent's, and the scout
    it called in shows as called in."""
    import runrecord as RT
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    c = RT.db()
    c.executemany("insert into runs (run, ref, agent, started, ended, end_state) values (?,?,?,?,?,'done')",
                  [("mission-run:9", None, "mission:ram", 100, 200), ("hermes:scout:a", "mission-run:9", "scout", 110, 150),
                   ("build:30:0:queued", None, "builder", 300, 400), ("claude:builder:x", "build:30:0:queued", "claude-builder", 310, 390)])
    c.commit()
    a = RT.task_activity(10, door="mission", ref="ram", since=0)
    assert [(x["agent"], x["name"]) for x in a["agents"]] == [("mission", "Hermes (tasks)"), ("scout", RT.AGENT_NAME.get("scout", "scout"))]
    assert a["edges"] == [{"from": "mission", "to": "scout", "kind": "called", "n": 1}]
    b = RT.task_activity(11, door="build", ref="30")
    assert [x["agent"] for x in b["agents"]] == ["builder", "claude-builder"]                    # the two builders stay apart


def test_the_network_shows_every_name_whole():
    """The owner, 8 Nov 2026: "Not sure if I like the truncation": a task's or an agent's name wraps onto the lines it
    needs, measured in its own font, and the task's box grows to fit; nothing is cut with an ellipsis."""
    draw = JS.split("function netDraw() {", 1)[1].split("\nfunction netBind", 1)[0]
    assert "tmShort" not in draw and "wrapWords(t.title, cT)" in draw and 'svgTextWidth(l, "tml", box) <= TW - 18' in draw
    assert 'height="${tH[i]}"' in draw and "tspans(aL[i]" in draw
    wrap = JS.split("function wrapWords(text, fits) {", 1)[1].split("\n}", 1)[0]
    assert "slice" in wrap and "-`" in wrap                                                    # a too-long word breaks and goes on


def test_an_engine_s_card_opens_a_page_and_seen_says_what_it_does():
    """OBS-10 (the owner, 8 Nov 2026: "What is acknowledged doing? Why can't I click on these crew cards?"): Seen hides an
    issue until it happens again and says so on hover or long-press; an engine's whole card opens its agent's page (Hermes
    (chat) is main) or Stack -> Health, its last run one link inside; a duty's page opens on the agent's card."""
    assert "const engineHref = (h) => swAgentHref(engineAgentOf(h.name) || h.id) || \"#/system?tab=health\"" in JS
    assert "Object.entries(SW_ENGINE).find(([, v]) => v === name)" in JS and "Hermes (chat)" in SWARM.split("const SW_ENGINE =", 1)[1].split("\n", 1)[0]
    assert ">Acknowledge<" not in JS + SWARM and "from the Health doctor until it happens again. Nothing is fixed or deleted." in JS
    card = JS.split('if (a.kind === "engine") return', 1)[1].split("\n  return", 1)[0]
    assert 'data-href="${a.href}"' in card and "its last run" in card and "${SEEN_TIP}>Seen</button>" in card
    team = JS.split("function teamDraw(b, live = false) {", 1)[1].split("\n}", 1)[0]
    assert 'e.target.closest("a, button")' in team and "location.hash = c.dataset.href" in team
    assert '<div id="agcardbox" class="section"></div>' in JS and "swTile(a, x, false)" in JS and "swAgentPanel(box, c.id, true, false)" in JS
    assert '[["team", "Its work"]]' in JS


def test_no_map_cuts_a_name():
    """The owner, 8 Nov 2026, on the Network's ellipses: no map cuts a name. A run's flow map, its lanes and a task's
    timeline wrap names onto the lines they need and grow; only a step's long instruction shows its first lines with a
    visible marker, the panel the rest."""
    import webjs
    allj = webjs.app_js() + SWARM + (STATIC / "task.js").read_text()
    assert "tmShort" not in allj and allj.count("function wrapWords(text, fits) {") == 1 and "function svgTextWidth(text, cls, host) {" in allj
    flow = allj.split("function tmapFlow(box, d, g) {", 1)[1].split("\n}", 1)[0]
    assert "n.h = Math.max(NH," in flow and 'height="${n.h}"' in flow and '"… tap for all"' in flow and "cap: preview" in flow
    lanes = allj.split("function tmapTimeline(box, d) {", 1)[1].split("\n}", 1)[0]
    tline = allj.split("function taskTimeline(box, t, a) {", 1)[1].split("\n}", 1)[0]
    assert "svgTspans(LL[i]" in lanes and "svgTspans(LL[i]" in tline and "RT[i] + (RH[i] - LH) / 2" in lanes + tline


def test_each_idea_is_tied_to_the_task_whose_run_first_saw_it(tmp_path, monkeypatch):
    """AI Change Requests, step 1: an idea's first run is walked up to its task as on the Network (a duty's run to the
    duty, a step to its task); an idea no run recorded (the weekly self-review's) belongs to its writer's duty."""
    import asyncio
    import runrecord as RT
    import server
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    c = RT.db()
    c.executemany("insert into runs (run, ref, agent, started) values (?,?,?,?)",
                  [("crew:doctor:1", None, "crew:doctor", 1), ("task:5", None, "conductor", 2), ("task:5:step:1", "task:5", "scout", 3), ("hermes:main:x", None, "main", 4)])
    c.commit()
    board = [{"id": 215, "door": "crew", "ref": "doctor"}, {"id": 212, "door": "crew", "ref": "self-review"}, {"id": 5}]
    assert RT.tasks_of_runs(["crew:doctor:1", "task:5:step:1", "hermes:main:x", "gone"], board) == {"crew:doctor:1": 215, "task:5:step:1": 5, "hermes:main:x": None, "gone": None}
    (tmp_path / "state.json").write_text(json.dumps({"tasks": board}))
    monkeypatch.setattr(server, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(server, "_swarm_app", lambda op, args: {"result": [{"id": 1, "owner": "doctor", "first_run": "crew:doctor:1", "runs": 3},
                                                                           {"id": 2, "owner": "self-review", "first_run": None, "runs": 0}]} if op == "origins" else {})
    out = json.loads(asyncio.run(server.api_idea_origins(None)).body)["ideas"]
    assert [(x["id"], x["task"], x["by_duty"]) for x in out] == [(1, 215, False), (2, 212, True)]
    assert any(getattr(r, "path", "") == "/api/ideas/origins" for r in server.app.routes)


def test_an_idea_shows_where_it_came_from_and_a_task_its_ideas():
    """Step 1 in the app: an idea's page says how it came about, its card names its task, a task's and a duty's page has
    one quiet line to its ideas (Tasks -> Ideas for that task), and the Network marks a task that had ideas with a dot."""
    import webjs
    app = webjs.app_js()
    assert "function ideaOrigins()" in app and '"/api/ideas/origins"' in app and "Date.now() - ideaOrig.t < 60000" in app
    assert 'data-iorig="${p.id}"' in app and "fillIdeaFrom(body)" in SWARM and '<div id="ionly"></div>' in SWARM
    assert '<div id="iorigin"></div>' in SWARM and "How it came about" in SWARM and "no run of it was recorded" in SWARM
    assert '<div data-tideas="${t.id}"></div>' in (STATIC / "task.js").read_text() and "fillTaskIdeas($(`[data-tideas=\"${task.id}\"]`), task.id)" in app
    assert "#/tasks?v=ideas&task=${tid}" in app and 'route.q.get("task")' in app and 'class="netidea"' in app


def test_the_network_draws_tasks_and_agents_from_the_run_record():
    import server
    assert any(getattr(r, "path", "") == "/api/tasks/network" for r in server.app.routes) and server.NET_DAYS == (1, 7, 30, 90)
    draw = JS.split("function netDraw() {", 1)[1].split("\nfunction netBind", 1)[0]
    assert "api(`/api/tasks/network?days=${netDays}`)" in JS and 'class="netl${g.live ? " live" : ""}' in draw
    assert "Math.log2(1 + g.runs)" in draw and "data-nt=" in draw and "data-na=" in draw and "Not on any task" in draw
    assert 'swRender($("#netteam"), "map")' in draw                                       # "Agents together": who works with whom
    info = JS.split("function netInfo(byId) {", 1)[1].split("\n}", 1)[0]
    assert "steps.map(([a, s, st])" in info and '.join("<i>→</i>")' in info               # a task's agents in the order they worked
    assert ".netl.live" in CSS and ".netl.dim" in CSS


def test_home_counts_what_is_yours_and_the_ideas_apart():
    assert 'const IDEA_CLS = new Set(["ideas", "agent-change"]);' in JS
    head = JS.split("function homeHeadHtml() {", 1)[1].split("\n}", 1)[0]
    assert "const n = yoursN(), ideas = ideasN()" in head and '${ideas ? ` · ${ideas} idea' in head
    assert '<h2>Needs you <span class="hcount">${yoursN()}</span></h2>' in JS and 'IDEA_CLS.has(x.kind) ? \' class="quiet"\'' in JS
    assert "hquick" not in JS.split("function vHome() {", 1)[1].split("\n}", 1)[0]        # no quick link the tab bar has


def test_the_stack_s_own_browsers_are_not_counted_as_visits(tmp_path, monkeypatch):
    import server
    from starlette.testclient import TestClient
    monkeypatch.setattr(server, "SCREEN_VIEWS", tmp_path / "views.json")
    c = TestClient(server.app)
    assert c.post("/api/view", content=json.dumps({"name": "tasks"}), headers={"Tailscale-User-Login": "journeys@stack.local"}).json()["counted"] is False
    assert c.post("/api/view", content=json.dumps({"name": "tasks"}), headers={"Tailscale-User-Login": "owner@example.com"}).json() == {"ok": True}
    assert server.screen_views(path=tmp_path / "views.json") == {"tasks": 1}


def test_the_head_counts_the_tasks_the_list_shows():
    """A work site, 9 Nov 2026: the stack's weekly task stood under Repeating while the head said "0 repeating": the head
    counted only the owner's tasks whichever owner the list showed."""
    js = (Path(__file__).resolve().parents[1] / "images/mission-control/web/static/app-tasks.js").read_text()
    head = js.split("function tasksHeadHtml() {", 1)[1].split("\n}", 1)[0]
    assert "(S.tasks || []).filter(tMine)" in head and 't.owner !== "stack"' not in head

