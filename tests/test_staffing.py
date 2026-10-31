"""Self-staffing (TSK-13 to TSK-17): a finished task is judged point by point against its definition of done (a build by
what happened to it), the day's history credits each agent, measured results route a step to the agent that does that
kind best or away from a subscription at its limit, a step no agent fits gets a temporary agent within its grants (own
key, no tools, ended with the task), and a design that met three tasks becomes an idea for a permanent agent."""
import json
import sqlite3
import threading
import types

import pytest

import conductor as CD
import runtime as RTM
import staffing as ST
import tasks as TK

CARDS = {"scout": {"harness": "hermes", "model": "gpt-sub-fast", "roles": ["research"], "key": "vk-scout", "purpose": "web"},
         "mission": {"harness": "hermes", "model": "gpt-sub", "roles": ["missions", "research"], "key": "vk-mission", "purpose": "missions"},
         "planner": {"harness": "claude-code", "model": "claude-subscription", "roles": ["code", "research"], "key": "none", "purpose": "plans"},
         "desk": {"harness": "python", "model": "gpt-sub", "roles": ["briefings"], "key": "vk-desk", "purpose": "briefs"}}


@pytest.fixture
def K(tmp_path, monkeypatch):
    db = tmp_path / "m.sqlite"

    def conn():
        c = sqlite3.connect(db, timeout=5)
        c.row_factory = sqlite3.Row
        return c
    c = conn()
    TK.table(c)
    CD.table(c)
    ST.table(c)
    c.execute("create table builds (id integer primary key, status text)")
    c.execute("create table claude_tasks (id integer primary key, status text, answer text, error text)")
    c.execute("create table runs (id integer primary key, slug text, status text, output text, summary text)")
    ev, proposed = [], []
    ns = types.SimpleNamespace(db=conn, event=lambda *a, **k: ev.append(a), log=print, VAULT=tmp_path, stop=threading.Event(),
                               paused=__import__("missions").paused, vault_commit=lambda *a: None, X=types.SimpleNamespace(APP="x"))
    CD.M = TK.M = ST.M = ns
    import swarm_client as SW
    monkeypatch.setattr(SW, "propose", lambda src, ps, why: proposed.append((src, ps)) or (1, 0))
    for f in ("start", "end", "set_ref"):
        monkeypatch.setattr(RTM, f, lambda *a, **k: None)
    ST._keys.clear()
    return types.SimpleNamespace(c=c, ev=ev, proposed=proposed, tmp=tmp_path)


def task(K, door="plan", ref="1", kind="research", done=("names the release and its date", "lists three changes"), result=None, source="app", status="done"):
    t0 = TK.now()
    spec = {"plan": []}
    if result:
        (K.tmp / "tasks").mkdir(exist_ok=True)
        (K.tmp / "tasks/1-x.md").write_text(result)
        spec["result"] = "tasks/1-x.md"
    tid = K.c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, source, created, updated) "
                      "values ('x','X','find it',?,?,?,?,'standard','auto','{\"type\":\"once\"}',?,'[]','[]',?,?,?,?)",
                      (kind, door, ref, json.dumps(list(done)), json.dumps(spec), status, source, t0, t0)).lastrowid
    K.c.commit()
    return tid


def test_a_finished_task_is_judged_point_by_point_and_a_build_by_what_happened(K):
    tid = task(K, result="Python 3.15.2 came out on 25 Oct 2026.")
    j = ST.judge(K.c, TK.row(K.c, tid), ask=lambda p: {"points": [{"met": True, "why": "named"}, {"met": False, "why": "no changes listed"}]})
    assert j["verdict"] == "partly" and j["points"][1] == {"point": "lists three changes", "met": False, "why": "no changes listed"}
    K.c.execute("insert into builds (id, status) values (7, 'deployed')"); K.c.commit()
    assert ST.judge(K.c, TK.row(K.c, task(K, door="build", ref="7", kind="coding")))["verdict"] == "met"
    assert ST.judge(K.c, TK.row(K.c, task(K, door="claude", ref="9")))["verdict"] == "not judged"


def test_judged_tasks_credit_each_agent_and_measure_it(K, monkeypatch):
    monkeypatch.setattr(ST, "tokens_of", lambda run, db=None: 500)
    tid = task(K, result="Python 3.15.2, 25 Oct; changes: a, b, c")
    for i, a in enumerate(("scout", "desk"), 1):
        K.c.execute("insert into task_steps (task, idx, title, agent, harness, model, after, status, started, ended) values (?,?,?,?,?,?,?,?,?,?)",
                    (tid, i, "s", a, CARDS[a]["harness"], CARDS[a]["model"], "[]", "done", "2026-10-31T10:00:00+01:00", "2026-10-31T10:01:00+01:00"))
    K.c.commit()
    task(K, door="chat", ref="abc", source="door")                               # a chat: never judged
    ST.judge_due(K.c, ask=lambda p: {"points": [{"met": True, "why": ""}, {"met": True, "why": ""}]})
    t = TK.row(K.c, tid)
    assert (t["verdict"], t["tokens"]) == ("met", 500) and t["spec"]["judgement"]["verdict"] == "met"
    ab = ST.abilities(K.c)
    assert ab[("scout", "research")]["tasks"] == 1 and ab[("scout", "research")]["success"] == 1.0 and ab[("desk", "research")]["seconds"] == 60
    assert K.c.execute("select count(*) from tasks where judged is not null").fetchone()[0] == 1


def test_a_step_goes_to_the_agent_that_did_that_kind_best_or_away_from_a_limit():
    measured = {("mission", "research"): {"tasks": 4, "success": 0.5}, ("scout", "research"): {"tasks": 5, "success": 0.9},
                ("planner", "research"): {"tasks": 2, "success": 1.0}}
    free = lambda e: False
    a, why = ST.route({"agent": "mission"}, "research", CARDS, measured, free)
    assert a == "scout" and "90%" in why and "50%" in why                          # planner: only 2 tasks, not counted
    assert ST.route({"agent": "mission"}, "research", CARDS, {**measured, ("scout", "research"): {"tasks": 5, "success": 0.55}}, free) == ("mission", "")
    assert ST.route({"agent": "mission"}, "analysis", CARDS, measured, free) == ("mission", "")     # nothing measured for this kind
    a, why = ST.route({"agent": "planner"}, "research", CARDS, {}, lambda e: e == "claude")
    assert a in ("scout", "mission") and "usage limit" in why
    assert ST.route({"agent": "desk"}, "research", CARDS, {}, lambda e: e == "chatgpt") == ("desk", "")   # no one shares its role


def test_a_temporary_agent_stays_within_its_grants_and_ends_with_its_task(K):
    for bad in ({"tools": ["mail"]}, {"model": "claude-subscription"}, {"name": "Bad Name"}, {"instructions": "short"}):
        with pytest.raises(ValueError):
            ST.admit({"name": "contract-reader", "model": "gpt-sub", "tools": [], "instructions": "x" * 60, **bad})
    calls = []
    call = lambda path, body: calls.append((path, body)) or {"key": "sk-tmp"}
    assert ST.key_for("vk-tmp-5-2", "gpt-sub", call) == "sk-tmp" and ST.key_for("vk-tmp-5-2", "gpt-sub", call) == "sk-tmp"
    gen = calls[0][1]
    assert len(calls) == 1 and gen["models"] == ["gpt-sub"] and gen["object_permission"] == {"mcp_servers": []} and gen["max_budget"] == 0.02
    ST.key_for("vk-tmp-6-1", "gpt-sub", call)
    assert ST.end_keys(5, call) == ["vk-tmp-5-2"] and calls[-1] == ("/key/delete", {"key_aliases": ["vk-tmp-5-2"]}) and list(ST._keys) == ["vk-tmp-6-1"]
    listed = lambda path, body: {"keys": [{"key_alias": "vk-tmp-9-1"}, {"key_alias": "vk-main"}]} if path.startswith("/key/list") else calls.append((path, body))
    assert ST.sweep(listed) == ["vk-tmp-9-1"] and calls[-1] == ("/key/delete", {"key_aliases": ["vk-tmp-9-1"]})


def test_a_design_is_archived_reused_by_name_and_proposed_after_three_met_tasks(K):
    ask = lambda p: {"name": "contract-reader", "purpose": "reads supply contracts", "instructions": "You read contracts. " * 5, "model": "gpt-sub", "tools": []}
    d = ST.design_for(K.c, {"title": "read the contract", "why": "needs a contract reader"}, "find terms", ask=ask)
    again = ST.design_for(K.c, {"title": "read it", "why": "x"}, "y", ask=lambda p: {**ask(p), "purpose": "something else"})
    assert d["id"] == again["id"] and again["purpose"] == "reads supply contracts"
    for t in (1, 2):
        ST.design_scored(K.c, "contract-reader", t, "met")
    ST.design_scored(K.c, "contract-reader", 2, "met")                           # the same task again: counted once
    assert not K.proposed
    ST.design_scored(K.c, "contract-reader", 3, "met")
    src, ps = K.proposed[0]
    assert src == "staffing" and "contract-reader" in ps[0]["title"] and "prompts/contract-reader.md" in ps[0]["description"]
    ST.design_scored(K.c, "contract-reader", 4, "met")
    assert len(K.proposed) == 1


def test_a_step_no_agent_fits_gets_a_temporary_agent_that_ends_with_the_task(K, monkeypatch):
    plan = [{"step": "find the contract", "agent": "scout", "why": "web", "after": []},
            {"step": "read its terms", "agent": "new", "why": "someone who reads supply contracts", "after": [1]}]
    tid = task(K, status="running", result=None)
    TK.put(K.c, tid, spec={"plan": plan})
    CD.start(K.c, TK.row(K.c, tid))
    s2 = CD.steps(K.c, tid)[1]
    assert (s2["agent"], s2["harness"], s2["model"]) == ("new", "temp", "gpt-sub")
    monkeypatch.setattr(ST, "design_for", lambda c, s, goal, ask=None: {"name": "contract-reader", "purpose": "reads contracts", "instructions": "i" * 50, "model": "gpt-sub"})
    ran = []
    monkeypatch.setattr(ST, "run_temp", lambda c, t, s, prompt, d, call=None: ran.append((s["agent"], prompt)) or "the terms")
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "hermes": lambda c, t, s, p, card: "found it"})
    monkeypatch.setattr(CD, "headroom", lambda s: None)
    ended = []
    monkeypatch.setattr(ST, "end_keys", lambda task_id, call=None: ended.append(task_id))
    monkeypatch.setattr(CD, "cards", lambda: CARDS)
    monkeypatch.setattr(CD, "RESULTS", K.tmp / "tasks")
    import notify as N
    monkeypatch.setattr(N, "send", lambda *a, **k: {})
    import swarm_client as SW
    monkeypatch.setattr(SW, "limited", lambda e, now=None: False)
    for _ in range(3):
        CD.tick(K.c, start_thread=lambda f: f())
    s2 = CD.steps(K.c, tid)[1]
    assert s2["agent"] == "contract-reader" and s2["output"] == "the terms" and "temporary agent: reads contracts" in s2["why"]
    assert ran[0][0] == "contract-reader" and "reads contracts" in ran[0][1] and "found it" in ran[0][1]
    assert TK.row(K.c, tid)["status"] == "done" and ended == [tid]


def test_the_conductor_routes_a_step_before_its_first_attempt_and_says_why(K, monkeypatch):
    tid = task(K, status="running")
    TK.put(K.c, tid, spec={"plan": [{"step": "look it up", "agent": "mission", "why": "researches", "after": []}]})
    CD.start(K.c, TK.row(K.c, tid))
    monkeypatch.setattr(ST, "abilities", lambda c, days=30: {("mission", "research"): {"tasks": 4, "success": 0.4}, ("scout", "research"): {"tasks": 6, "success": 0.95}})
    import swarm_client as SW
    monkeypatch.setattr(SW, "limited", lambda e, now=None: False)
    s = CD.routed(K.c, TK.row(K.c, tid), CD.steps(K.c, tid)[0], CARDS)
    assert (s["agent"], s["harness"], s["model"]) == ("scout", "hermes", "gpt-sub-fast") and "(routed: scout met research tasks 95%" in s["why"]
    assert CD.steps(K.c, tid)[0]["agent"] == "scout"
