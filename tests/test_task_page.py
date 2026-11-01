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


def seed(RT, t):
    """Task 5 as the runner and Hermes record it: planned by the intake, step 1 on the mission agent (its own Hermes
    session inside the step, which calls in the scout), step 2 on the builder; and another task the scout worked on."""
    RT.ingest([ev("task-intake:5-0", "run", t, "intake"), ev("task-intake:5-0", "llm", t + 1, "intake", tokens={"in": 900, "out": 100}),
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
               ev("task:6:step:1", "run", t + 30, "scout", ref="task:6"), ev("task:6:step:1", "end", t + 31, "scout")])


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
    assert RT.task_activity(99) == {"agents": [], "actions": [], "memory": {"read": [], "write": []}, "runs": 0, "actions_total": 0}


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

