"""A task's own page (APP-35): the runner writes each task's data, the run record says which agents worked on it, what
they did, and what they read from and kept in memory, and an agent's page lists the tasks it worked on."""
import json
import sqlite3
import time
import types

import pytest


@pytest.fixture
def RT(tmp_path, monkeypatch):
    import runrecord as RT
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    return RT


def ev(run, kind, ts, agent, **kw):
    return {"run": run, "kind": kind, "ts": ts, "agent": agent, **kw}


def seed(RT, t, extra=()):
    """Task 5 as the runner and Hermes record it: planned by the intake, step 1 on the mission agent (its own Hermes
    session inside the step, which calls in the scout), step 2 on the builder; and another task the scout worked on.
    `extra` events join in time order (an ended run takes none)."""
    RT.ingest(sorted([*extra, ev("task-intake:5-0", "run", t, "intake"), ev("task-intake:5-0", "llm", t + 1, "intake", tokens={"in": 900, "out": 100}),
               ev("task-intake:5-0", "end", t + 2, "intake"),
               ev("task:5", "run", t + 3, "conductor"),
               ev("task:5:step:1", "run", t + 4, "mission", ref="task:5"),
               ev("hermes:mission:a", "run", t + 5, "mission", ref="task:5:step:1"),
               ev("hermes:mission:a", "call", t + 6, "mission", title="mcp__vault__qmd_query", detail='{"query": "Reddit app on Android"}'),
               ev("hermes:mission:a", "call", t + 7, "mission", title="journal_write", detail='{"text": "the phone has no Reddit"}'),
               ev("hermes:mission:a", "call", t + 8, "mission", title="write_file", detail='{"path": "/work/app/main.py"}'),
               ev("hermes:mission:a", "call", t + 9, "mission", title="write_file", detail='{"path": "/vault/missions/x/wiki/reddit.md"}'),
               ev("hermes:scout:b", "run", t + 10, "scout", ref="hermes:mission:a"),
               ev("hermes:scout:b", "call", t + 11, "scout", title="web_search", detail='{"query": "reddit humour"}'),
               ev("hermes:scout:b", "llm", t + 12, "scout", tokens={"in": 1000, "out": 200}),
               ev("hermes:scout:b", "end", t + 13, "scout"),
               ev("hermes:mission:a", "end", t + 14, "mission"),
               ev("task:5:step:1", "end", t + 15, "mission"),
               ev("task:5:step:2", "run", t + 16, "builder", ref="task:5"), ev("task:5:step:2", "end", t + 20, "builder", status="failed"),
               ev("task:5", "end", t + 21, "conductor"),
               ev("task:6:step:1", "run", t + 30, "scout", ref="task:6"), ev("task:6:step:1", "end", t + 31, "scout")], key=lambda e: e["ts"]))


def test_a_task_s_agents_actions_and_memory_come_from_its_run_tree(RT):
    t = time.time() - 600
    seed(RT, t)
    a = RT.task_activity(5)
    who = {g["agent"]: g for g in a["agents"]}
    assert set(who) == {"intake", "conductor", "mission", "scout", "builder"}
    assert who["intake"]["roles"] == ["planned it"] and who["intake"]["tokens"] == 1000
    assert who["mission"]["roles"] == ["step 1"]                        # its own session inside its step is that step
    assert who["scout"]["roles"] == ["called in by Hermes (mission)"] and who["scout"]["calls"] == 1 and who["scout"]["tokens"] == 1200
    assert who["builder"]["states"] == {"failed": 1}
    mem = {k: [(m["agent"], m["tool"]) for m in v] for k, v in a["memory"].items()}
    assert mem["read"] == [("mission", "mcp__vault__qmd_query")]
    assert mem["write"] == [("mission", "journal_write"), ("mission", "write_file")]   # the vault write; the code file is work
    assert all(x["kind"] != "llm" for x in a["actions"]) and a["actions_total"] == len(a["actions"])
    lanes = {x["run"]: x for x in a["lanes"]}
    assert "task:5" not in lanes and lanes["task:5:step:1"]["role"] == "step 1" and lanes["hermes:scout:b"]["depth"] == 2 and lanes["hermes:mission:a"]["role"] == "its session"
    assert RT.task_activity(99) == RT.EMPTY_ACTIVITY and RT.task_activity(99)["edges"] == []


def test_the_page_says_where_each_memory_call_went_who_started_whom_and_what_failed(RT):
    """APP-36: a memory call names its store and what it read or kept; the agents' starts, calls and the plan are links
    of the map; errors are listed; each agent's tools counted."""
    t = time.time() - 600
    seed(RT, t, [ev("hermes:mission:a", "call", t + 9.5, "mission", title="mcp__vault__swarm_swarm_context", detail="{}"),
                 ev("hermes:mission:a", "call", t + 9.6, "mission", title="mcp__vault__swarm_swarm_finish", detail='{"summary": "no Reddit yet", "idem": "x"}'),
                 ev("hermes:mission:a", "call", t + 9.7, "mission", title="memory_recall", detail='{"query": "Reddit humour'),   # cut by the record
                 ev("task:5:step:2", "error", t + 19, "builder", title="tests failed", detail="2 of 9")])
    a = RT.task_activity(5)
    m = {(x["store"], x["target"]) for x in a["memory"]["read"] + a["memory"]["write"]}
    assert {("notes", "Reddit app on Android"), ("journal", "the phone has no Reddit"), ("wiki", "missions/x/wiki/reddit.md"),
            ("board", "no Reddit yet"), ("long-term", "Reddit humour")} <= m
    assert any(s == "board" and x.startswith("the task's context") for s, x in m)
    assert {(x["from"], x["to"], x["kind"]): x["n"] for x in a["edges"]} == {("conductor", "mission", "started"): 1, ("conductor", "builder", "started"): 1,
                                                                             ("mission", "scout", "called"): 1, ("intake", "conductor", "planned"): 1}
    assert a["errors_total"] == 1 and a["errors"][0]["title"] == "tests failed"
    tools = {g["agent"]: g["tools"] for g in a["agents"]}["mission"]
    assert tools["write_file"] == 2 and tools["swarm_context"] == 1 and list(tools)[0] == "write_file"   # most used first


def test_a_door_task_s_page_finds_its_own_run_and_a_recurring_task_shows_one_run(RT):
    t = time.time() - 600
    RT.ingest([ev("claude-task:7", "run", t, "claude-task", ref="crew:doctor"), ev("claude:claude-task:x", "run", t + 1, "claude-task", ref="claude-task:7"),
               ev("claude:claude-task:x", "llm", t + 2, "claude-task", tokens={"in": 50, "out": 5}), ev("claude:claude-task:x", "end", t + 3, "claude-task"),
               ev("claude-task:7", "end", t + 4, "claude-task"),
               ev("task:8", "run", t, "conductor"), ev("task:8:step:1", "run", t + 1, "scout", ref="task:8"), ev("task:8:step:1", "end", t + 2, "scout"),
               ev("task:8.2", "run", t + 50, "conductor"), ev("task:8.2:step:1", "run", t + 51, "desk", ref="task:8.2"), ev("task:8.2:step:1", "end", t + 52, "desk")])
    a = RT.task_activity(9, door="claude", ref="7")
    assert [(g["agent"], g["roles"], g["tokens"]) for g in a["agents"]] == [("claude-task", ["did it"], 55)]
    assert [(x["run"], x["depth"], x["role"]) for x in a["lanes"]] == [("claude-task:7", 0, "its run"), ("claude:claude-task:x", 1, "its session")]
    assert RT.task_activity(9, door="claude", ref="8")["agents"] == []
    assert {g["agent"] for g in RT.task_activity(8, occ=2)["agents"]} == {"conductor", "desk"}
    assert {g["agent"] for g in RT.task_activity(8)["agents"]} == {"conductor", "scout", "desk"}


def test_a_scout_run_goes_under_the_run_that_asked_its_question_not_a_task_s_live_scout_step(RT):
    """FND-111: the RAM mission's research ran while the China briefing's scout steps were live and was filed under them
    (its price searches became the briefing's top sources). A scout run that answers a research call now goes under the
    run that asked that question; a step's own scout run stays under the step; the repair moves the misfiled ones."""
    t = time.time() - 600
    q = ("Verify Silicon Power SP016GXLZU320BDAJ5 German offer at https://geizhals.de/silicon-power-a3633271.html: kit size, "
         "named merchant, stock, EUR126.97 free shipping")
    RT.ingest([ev("task:79", "run", t, "conductor"), ev("task:79:step:6", "run", t + 1, "scout", ref="task:79"),
               ev("hermes:mission:m", "run", t + 2, "mission", ref="mission-run:64"),
               ev("hermes:mission:m", "call", t + 3, "mission", title="mcp__vault__research_research",
                  detail=json.dumps({"question": q, "depth": "quick"})[:130]),                  # kept cut: the question's start is there
               ev("hermes:scout:r", "run", t + 4, "scout", run_title=q[:200]),
               ev("hermes:scout:s", "run", t + 5, "scout", run_title="You are scout in the owner's self-hosted AI stack: research the week")])
    ref = lambda r: RT.db().execute("select ref from runs where run=?", (r,)).fetchone()["ref"]
    assert (ref("hermes:scout:r"), ref("hermes:scout:s")) == ("hermes:mission:m", "task:79:step:6")
    RT.db().execute("update runs set ref='task:79:step:6' where run='hermes:scout:r'")         # as the guess filed it before
    RT.db().commit()
    assert RT.reparent_research(t - 1) == [("hermes:scout:r", "task:79:step:6", "hermes:mission:m")]
    assert RT.reparent_research(t - 1) == [] and ref("hermes:scout:s") == "task:79:step:6"


def test_the_page_shows_one_run_s_answer_its_sources_and_what_it_made(tmp_path, monkeypatch):
    """APP-36: the server picks the run (asked for, else the newest), its answer, and from its swarm map the sources
    (cited or not, by which agent in which step), what it made and each agent's cost and models."""
    import server as S
    for name, sub in (("MAPS", "maps"), ("TASK_PAGES", "tasks"), ("VAULT", "vault")):
        monkeypatch.setattr(S, name, tmp_path / sub)
        (tmp_path / sub).mkdir()
    asked = []
    monkeypatch.setattr(S.RT, "task_activity", lambda tid, **k: asked.append(k) or {"agents": []})
    (tmp_path / "vault/tasks").mkdir()
    (tmp_path / "vault/tasks/8-a-1.md").write_text("first")
    (tmp_path / "vault/tasks/8-a-2.md").write_text("second")
    (tmp_path / "tasks/8.json").write_text(json.dumps({"id": 8, "door": "plan", "ref": "8", "created": "2026-11-01T08:00:00+01:00", "result": "tasks/8-a-2.md",
                                                       "runs": [{"occ": 2, "result": "tasks/8-a-2.md"}, {"occ": 1, "result": "tasks/8-a-1.md"}]}))
    arts = [{"id": "p", "kind": "page", "title": "VW", "uri": "https://a.com/1", "site": "a.com"}, {"id": "s", "kind": "search", "title": "Web search: vw", "uri": "search:vw", "site": "search"},
            {"id": "f", "kind": "finding", "title": "Step 1", "uri": "finding:8.1.1", "site": "finding"},
            {"id": "w", "kind": "wiki", "title": "entities/vw", "uri": "vault:topics/c/wiki/entities/vw.md", "site": "vault"}]
    links = [{"step": 1, "run": "hermes:scout:x", "rel": "used", "artifact": "p"}, {"step": 1, "run": "hermes:scout:x", "rel": "used", "artifact": "s"},
             {"step": 1, "run": "task:8:step:1", "rel": "generated", "artifact": "f"}, {"step": 2, "run": "task:8:step:2", "rel": "generated", "artifact": "w"},
             {"step": 0, "run": "task:8", "rel": "cited", "artifact": "p"}, {"step": 1, "run": "task:8:step:1", "rel": "derived", "artifact": "f", "src": "p"}]
    lanes = [{"run": "task:8:step:1", "agent": "scout", "cost": 0.01, "models": ["gpt-sub"]}, {"run": "hermes:scout:x", "agent": "scout", "cost": 0.02, "models": ["gpt-sub-fast"]},
             {"run": "task:8:step:2", "agent": "desk", "cost": None, "models": []}]
    (tmp_path / "maps/8.1.json").write_text(json.dumps({"artifacts": arts, "links": links, "lanes": lanes, "numbers": {"read": 1, "cited": 1},
                                                        "steps": [{"idx": 1, "agent": "scout"}, {"idx": 2, "agent": "desk"}]}))
    d = S.task_page(8, 1)
    assert d["occ"] == 1 and d["answer"] == "first" and asked[-1]["occ"] == 1 and asked[-1]["door"] == "plan"
    src = {x["id"]: x for x in d["prov"]["sources"]}
    assert set(src) == {"p", "s"} and src["p"]["cited"] and not src["s"]["cited"] and (src["p"]["agents"], src["p"]["steps"]) == (["scout"], [1])
    assert {x["id"] for x in d["prov"]["made"]} == {"f", "w"} and d["prov"]["by_agent"]["scout"] == {"cost": 0.03, "models": ["gpt-sub", "gpt-sub-fast"]}
    d = S.task_page(8)                                                   # no run named: the newest, which has no map yet
    assert d["occ"] == 2 and d["answer"] == "second" and d["prov"] is None
    assert S.task_page(8, 7)["occ"] == 2                                 # a run it does not have: the newest


def test_an_agent_s_page_lists_the_tasks_it_worked_on_with_its_part(RT):
    t = time.time() - 600
    seed(RT, t)
    rows = {r["task"]: r for r in RT.agent_tasks("scout")}
    assert rows[5]["roles"] == ["called in"] and rows[6]["roles"] == ["step 1"]
    assert [r["task"] for r in RT.agent_tasks("scout")] == [6, 5]       # newest first
    assert RT.agent_tasks("mission")[0]["roles"] == ["step 1"]          # its session in the step adds no "called in"
    assert RT.agent_tasks("intake")[0]["roles"] == ["planned it"]


def test_the_runner_writes_each_task_s_page_with_every_run_and_its_steps(tmp_path):
    import conductor as CD
    import tasks as TK
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    TK.table(c)
    CD.table(c)
    c.execute("insert into tasks (id, text, title, goal, kind, door, ref, done, rhythm, status, source, created, updated, spec) values "
              "(5, 'do it', 'Do it', 'Do it well', 'errand', 'plan', '5', '[\"it is done\"]', '{\"type\": \"once\"}', 'failed', 'app', "
              "'2026-11-01T20:00:00+01:00', '2026-11-01T20:01:00+01:00', ?)", (json.dumps({"plan": [{"step": "a", "agent": "mission"}], "result": None}),))
    c.execute("insert into task_occ (task, occ, trigger, started, status) values (5, 1, 'start', '2026-11-01T20:00:10+01:00', 'failed')")
    c.execute("insert into task_steps (task, occ, idx, title, agent, harness, after, status, output, error) values "
              "(5, 1, 1, 'a', 'mission', 'hermes', '[]', 'failed', 'BLOCKED: no phone', 'blocked: no phone')")
    written = []
    TK.M = types.SimpleNamespace(PUBLIC=tmp_path, log=written.append)
    TK.publish(c, [5])
    d = json.loads((tmp_path / "tasks/5.json").read_text())
    assert d["title"] == "Do it" and d["runs"][0]["occ"] == 1 and d["steps"]["1"][0]["error"] == "blocked: no phone"
    m = (tmp_path / "tasks/5.json").stat().st_mtime_ns
    TK.publish(c, [5])                                                    # nothing changed: the file is not written again
    assert (tmp_path / "tasks/5.json").stat().st_mtime_ns == m and not written


def test_each_subscription_s_load_in_its_window_and_who_used_it(RT):
    """OBS-17: the Stack page shows what each subscription carried in the last 5 hours (ChatGPT's usage window) and 24
    hours, from the run record's model calls, and the agents that used most."""
    now = time.time()
    RT.ingest([ev("hermes:mission:a", "run", now - 7200, "mission"),
               ev("hermes:mission:a", "llm", now - 7100, "mission", title="gpt-sub", tokens={"in": 1000, "out": 200}),
               ev("hermes:mission:a", "llm", now - 20 * 3600, "mission", title="gpt-sub-fast", tokens={"in": 5000, "out": 0}),
               ev("claude:task:1", "run", now - 600, "claude-task"),
               ev("claude:task:1", "llm", now - 500, "claude-task", title="claude-sonnet-5-5", tokens={"in": 300, "out": 30}),
               ev("hermes:mission:a", "llm", now - 3 * 86400, "mission", title="gpt-sub", tokens={"in": 9, "out": 9})])
    u = {x["engine"]: x for x in RT.usage(now)}
    assert (u["ChatGPT"]["tokens_5h"], u["ChatGPT"]["calls_5h"], u["ChatGPT"]["tokens_24h"], u["ChatGPT"]["calls_24h"]) == (1200, 1, 6200, 2)
    assert [tuple(x) for x in u["ChatGPT"]["top"]] == [("mission", 1200)]
    assert u["Claude"]["tokens_5h"] == 330 and u["Claude"]["top"][0][0] == "claude"

