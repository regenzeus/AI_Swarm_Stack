"""The task kernel (TSK-01 to TSK-04): every door's work is a task with every field, a sentence gets a specification
with a checkable definition of done, at most two questions and a plan whose agents exist, the owner's presets are
kept, 'show me the plan first' and 'after another task' wait, and each task follows its door to the end."""
import json
import sqlite3
import threading
import time
import types

import pytest

import builds as B
import claude_tasks as CT
import runtime as RTM
import tasks as TK


@pytest.fixture
def K(tmp_path, monkeypatch):
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("create table runs (id integer primary key, slug text, status text, summary text, output text, started text, ended text)")
    B.table(c)
    CT.table(c)
    TK.table(c)
    started, events, told = [], [], []

    def handle(req, missions, c):
        started.append(("mission", req))
        return {"slug": "ram-buy" if req["type"] == "shopping" else "ram-prices"}
    import missions as MM
    TK.M = types.SimpleNamespace(event=lambda *a, **k: events.append(a), valid_schedule=MM.valid_schedule, handle=handle, load_missions=lambda: {},
                                 X=types.SimpleNamespace(clean_triggers=lambda t: list(t or [])), notify_task=lambda *a: told.append(a),
                                 paused=lambda s: False, stop=threading.Event(), log=print)
    monkeypatch.setattr(TK, "B_repos", lambda: ["ai-stack", "testrepo"])
    monkeypatch.setattr(TK, "CHATS", tmp_path / "chats")
    monkeypatch.setattr(B, "handle", lambda req, c: started.append(("build", req)) or {"id": 7})
    monkeypatch.setattr(CT, "handle", lambda req, c: started.append(("claude", req)) or {"id": 3})
    for f in ("start", "end", "set_ref"):
        monkeypatch.setattr(RTM, f, lambda *a, **k: None)
    return types.SimpleNamespace(c=c, started=started, events=events, told=told, tmp=tmp_path)


def spec(**kw):
    return {"title": "RAM prices", "goal": "Find the cheapest fitting 32 GB kit", "kind": "research",
            "done": ["names three offers with price, shop and delivery date"], "rhythm": {"type": "once"},
            "plan": [{"step": "search the shops", "agent": "mission", "why": "it researches with the scout"},
                     {"step": "write the report", "agent": "mission", "why": "it writes"}], "questions": [], "effort": "standard", **kw}


def test_every_door_s_work_becomes_a_task_with_every_field(K):
    c, now = K.c, TK.now()
    c.execute("insert into builds (repo, title, description, status, created, updated, attempts) values ('ai-stack','Dark mode','Add a toggle','review',?,?,0)", (now, now))
    c.execute("insert into claude_tasks (question, status, created) values ('How does the deploy roll back?', 'done', ?)", (now,))
    (K.tmp / "chats").mkdir()
    (K.tmp / "chats/abc123def.json").write_text(json.dumps({"title": "Uranium", "created": time.time(), "pending": True,
                                                             "messages": [{"role": "user", "content": "What moved uranium today?"}]}))
    missions = {"u": {"slug": "u", "title": "Uranium", "type": "briefing", "status": "active", "schedule": "daily 06:30", "created": now, "goal": "Daily uranium news"},
                "old": {"slug": "old", "title": "Old", "type": "task", "status": "active", "created": "2026-01-01T00:00:00+01:00"}}
    TK.sync(c, missions)
    ts = {t["door"]: t for t in TK.state(c)["tasks"]}
    assert set(ts) == {"mission", "build", "claude", "chat"}                       # the January mission is outside the 7 days
    for t in ts.values():
        assert t["goal"] and t["done"] and t["rhythm"] and t["autonomy"] == "door" and t["source"] == "door" and "deadline" in t
    assert ts["mission"]["rhythm"] == {"type": "schedule", "schedule": "daily 06:30"} and ts["mission"]["status"] == "scheduled"
    assert ts["build"]["status"] == "waiting_owner" and ts["claude"]["status"] == "done" and ts["chat"]["status"] == "running"
    TK.sync(c, missions)
    assert len(TK.state(c)["tasks"]) == 4                                         # once per piece of work
    assert K.events == []                     # found at a door: the door reports it; no "Task #n done" flood in the feed


def test_a_sentence_gets_a_specification_and_reaches_its_door(K):
    tid = TK.handle({"action": "task_create", "text": "Find out what a 32 GB DDR4 kit for my laptop costs"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda prompt: spec())
    t = TK.row(K.c, tid)
    assert t["status"] == "running" and t["door"] == "mission" and t["ref"] == "ram-prices" and t["kind"] == "research"
    assert t["done"] == ["names three offers with price, shop and delivery date"]
    assert [p["agent"] for p in t["spec"]["plan"]] == ["mission", "mission"]
    kind, req = K.started[0]
    assert kind == "mission" and req["once"] and req["run_now"] and "Definition of done:\n- names three offers" in req["description"]
    assert f"(Task #{tid} in Mission Control)" in req["description"]
    assert req["deliver"] == ["telegram", "app"]                                     # no e-mail unless the task asks for it


def test_a_weekly_briefing_task_gets_its_content_not_the_plan_email_when_asked_and_shows_its_runs(K):
    """FND-77: the plan's agent instructions became the desk's notes and the writer reported itself blocked; the e-mail
    the owner asked for was never set up; the board said only "scheduled" although the first run had finished."""
    import missions as MM
    tid = TK.handle({"action": "task_create", "text": "Send me an email with Chinese automotive news every week"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(kind="briefing", rhythm={"type": "schedule", "schedule": "weekly mon 08:00"},
                                          done=["covers sales and exports", "is emailed to the owner"]))
    kind, req = K.started[0]
    assert kind == "mission" and req["type"] == "briefing" and req["schedule"] == "weekly mon 08:00" and req["run_now"]
    assert "Plan:" not in req["description"] and "search the shops" not in req["description"] and "Task #" not in req["description"]
    assert "- covers sales and exports" in req["description"] and req["deliver"] == ["telegram", "app", "email"]
    assert TK.row(K.c, tid)["status"] == "scheduled"
    K.c.execute("insert into runs (slug, status, summary, output, started, ended) values ('ram-prices','ok','China Automotive Weekly',"
                "'topics/x/reports/2026/10/2026-10-31.md','2026-10-31T16:53:46+01:00','2026-10-31T16:55:33+01:00')")
    TK.M.load_missions, TK.M.next_due, TK.M.now = (lambda: {"ram-prices": {"status": "active", "schedule": "weekly mon 08:00"}}), MM.next_due, MM.now
    t = next(x for x in TK.state(K.c)["tasks"] if x["id"] == tid)
    assert t["last_run"]["summary"] == "China Automotive Weekly" and t["last_run"]["output"].endswith("2026-10-31.md")
    import datetime as dt
    n = dt.datetime.fromisoformat(t["next_run"])
    assert (n.weekday(), n.hour, n.minute) == (0, 8, 0)


def test_a_one_off_task_with_several_agents_goes_to_the_conductor_as_a_plan_graph(K):
    import conductor as CD
    tid = TK.handle({"action": "task_create", "text": "Find out what changed in the newest Python and what it means for me"}, K.c)["task"]
    plan = [{"step": "find the release notes", "agent": "scout", "why": "web", "after": []},
            {"step": "say what matters", "agent": "desk", "why": "writes", "after": [1]}]
    TK.intake(K.c, tid, ask=lambda p: spec(plan=plan))
    t = TK.row(K.c, tid)
    assert (t["door"], t["ref"], t["status"]) == ("plan", str(tid), "running") and not K.started
    assert [(s["idx"], s["agent"], s["harness"], s["after"]) for s in CD.steps(K.c, tid)] == [(1, "scout", "hermes", []), (2, "desk", "python", [1])]
    cyc = TK.handle({"action": "task_create", "text": "A plan that waits for itself in a circle"}, K.c)["task"]
    TK.intake(K.c, cyc, ask=lambda p: spec(plan=[{**plan[0], "after": [2]}, plan[1]]))
    assert TK.row(K.c, cyc)["status"] == "failed" and "cycle" in TK.row(K.c, cyc)["error"]      # refused (TSK-05)
    board = TK.state(K.c)["tasks"]                                                  # newest first
    assert board[0]["id"] == cyc and board[0]["steps"] == [] and len(board[1]["steps"]) == 2


def test_an_agent_the_intake_names_that_does_not_exist_gets_a_temporary_agent(K):
    import conductor as CD
    tid = TK.handle({"action": "task_create", "text": "Find Cameco's newest supply contract and read its terms"}, K.c)["task"]
    plan = [{"step": "find the contract", "agent": "scout", "why": "web", "after": []},
            {"step": "read its terms", "agent": "contract-reader", "why": "reads supply contracts", "after": [1]}]
    TK.intake(K.c, tid, ask=lambda p: spec(plan=plan))
    t = TK.row(K.c, tid)
    p2 = t["spec"]["plan"][1]
    assert p2["agent"] == "new" and "'contract-reader', which is no agent: a temporary agent is written for it" in p2["why"]
    assert t["door"] == "plan" and CD.steps(K.c, tid)[1]["harness"] == "temp"


def test_at_most_two_questions_and_answers_plan_it_again(K):
    tid = TK.handle({"action": "task_create", "text": "Fix the thing on the phone page"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(kind="coding", repo=None, questions=["Which page?", "Which phone?", "Which colour?"]))
    t = TK.row(K.c, tid)
    assert t["status"] == "needs_answer" and t["questions"] == ["Which page?", "Which phone?"] and K.told and not K.started
    with pytest.raises(ValueError):
        TK.handle({"action": "task_answer", "id": tid, "answers": ["the AI phone page"]}, K.c)        # both must be answered
    TK.handle({"action": "task_answer", "id": tid, "answers": ["the AI phone page", "the S22"]}, K.c)
    assert TK.row(K.c, tid)["status"] == "intake"
    seen = []
    TK.intake(K.c, tid, ask=lambda p: seen.append(p) or spec(kind="coding", repo="ai-stack"))
    assert "- Which page?: the AI phone page" in seen[0]
    t = TK.row(K.c, tid)
    assert t["status"] == "running" and t["door"] == "build" and t["ref"] == "7" and K.started[0][1]["repo"] == "ai-stack"
    assert "The owner's answers:\n- Which page?: the AI phone page" in K.started[0][1]["description"]


def test_a_coding_task_without_a_repository_asks_which_one(K):
    tid = TK.handle({"action": "task_create", "text": "Add a dark mode toggle somewhere"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(kind="coding", repo="nonexistent"))
    t = TK.row(K.c, tid)
    assert t["status"] == "needs_answer" and t["questions"] == ["Which repository should this change go into: ai-stack, testrepo?"]


def test_the_owner_s_presets_are_kept_and_show_me_the_plan_first_waits(K):
    req = {"action": "task_create", "text": "Watch the price of 32 GB DDR4 kits", "autonomy": "ask", "kind": "watching", "effort": "deep",
           "deadline": "2026-11-30", "rhythm": {"type": "schedule", "schedule": "daily 07:00"}, "done": ["a message when a kit costs under 60 €"]}
    tid = TK.handle(req, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(kind="research", effort="light", done=["something vague but long enough"]))
    t = TK.row(K.c, tid)
    assert (t["kind"], t["effort"], t["deadline"], t["done"]) == ("watching", "deep", "2026-11-30", ["a message when a kit costs under 60 €"])
    assert t["rhythm"] == {"type": "schedule", "schedule": "daily 07:00"} and t["status"] == "waiting_approval" and not K.started
    TK.handle({"action": "task_approve", "id": tid}, K.c)
    t = TK.row(K.c, tid)
    assert t["status"] == "scheduled" and K.started[0][1]["schedule"] == "daily 07:00" and K.started[0][1]["depth"] == "deep"
    with pytest.raises(ValueError, match="stop it on that page"):              # started work is stopped at its door
        TK.handle({"action": "task_cancel", "id": tid}, K.c)
    other = TK.handle({"action": "task_create", "text": "Plan a trip I may not take", "autonomy": "ask"}, K.c)["task"]
    TK.handle({"action": "task_cancel", "id": other}, K.c)                         # not started yet: cancelled
    assert TK.row(K.c, other)["status"] == "cancelled"


def test_after_another_task_waits_until_that_one_is_done(K):
    first = TK.handle({"action": "task_create", "text": "Research the best 32 GB kits"}, K.c)["task"]
    TK.intake(K.c, first, ask=lambda p: spec())
    then = TK.handle({"action": "task_create", "text": "Then propose the cheapest one to buy", "rhythm": {"type": "after", "task": first}}, K.c)["task"]
    TK.intake(K.c, then, ask=lambda p: spec(kind="shopping"))
    assert TK.row(K.c, then)["status"] == "after" and len(K.started) == 1
    with pytest.raises(ValueError):
        TK.handle({"action": "task_create", "text": "after a task that is not there", "rhythm": {"type": "after", "task": 999}}, K.c)
    K.c.execute("insert into runs (slug, status) values ('ram-prices', 'ok')")
    TK.sync(K.c, {"ram-prices": {"slug": "ram-prices", "title": "RAM prices", "status": "active", "type": "task", "schedule": "manual", "once": True, "created": TK.now()}})
    assert TK.row(K.c, first)["status"] == "done"
    TK.sync(K.c, {s: {"slug": s, "title": s, "status": "active", "type": "task", "schedule": "manual", "once": True, "created": TK.now()}
                  for s in ("ram-prices", "ram-buy")})
    assert TK.row(K.c, then)["status"] == "running" and K.started[-1][1]["type"] == "shopping"


def test_a_failed_intake_says_why_and_can_be_planned_again(K):
    tid = TK.handle({"action": "task_create", "text": "Do something useful with my notes"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(done=["ok"]))                           # no checkable point
    t = TK.row(K.c, tid)
    assert t["status"] == "failed" and "no checkable definition of done" in t["error"] and not K.started
    TK.handle({"action": "task_retry", "id": tid}, K.c)
    assert TK.row(K.c, tid)["status"] == "intake"
    with pytest.raises(ValueError):
        TK.handle({"action": "task_create", "text": "hi"}, K.c)


def test_the_intake_prompt_names_every_agent_and_repository_and_the_app_cannot_be_used_from_the_ai_phone():
    t = {"text": "Fix the wiki map", "spec": {"preset": {"kind": "coding"}, "answered": [["Which page?", "Wiki"]]}, "questions": [], "answers": ["Wiki"]}
    p = TK.intake_prompt(t, ["ai-stack"], TK.cards())
    assert "Fix the wiki map" in p and '"kind": "coding"' in p and "- Which page?: Wiki" in p and "ai-stack" in p
    assert all(f"- {a}:" in p for a in ("intake", "scout", "builder", "mission")) and p.ref.startswith("intake/INTAKE@")
    import server as S
    assert {"task_create", "task_answer", "task_approve", "task_cancel", "task_retry"} <= S.ACTIONS
    src = open(S.__file__).read()
    assert 'str(body.get("action", "")).startswith(("task_", "rule_", "event_")) and from_ai_phone(request)' in src
