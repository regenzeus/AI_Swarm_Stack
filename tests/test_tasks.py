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
    started, events, told, made = [], [], [], {}

    def handle(req, missions, c):
        started.append(("mission", req))
        slug = "ram-buy" if req["type"] == "shopping" else "ram-prices"
        made[slug] = {"slug": slug, "title": req["title"], "type": req["type"], "status": "active", "task": req.get("task")}
        return {"slug": slug}
    import missions as MM
    TK.M = types.SimpleNamespace(event=lambda *a, **k: events.append(a), valid_schedule=MM.valid_schedule, handle=handle, load_missions=lambda: made,
                                 X=types.SimpleNamespace(clean_triggers=lambda t: list(t or [])), notify_task=lambda *a: told.append(a),
                                 paused=lambda s: False, stop=threading.Event(), log=print, next_due=MM.next_due, now=MM.now)
    import conductor as CD
    monkeypatch.setattr(CD, "M", TK.M)
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
    (K.tmp / "chats/abc123def.json").write_text(json.dumps({"title": "Copper", "created": time.time(), "pending": True,
                                                             "messages": [{"role": "user", "content": "What moved copper today?"}]}))
    missions = {"u": {"slug": "u", "title": "Copper", "type": "briefing", "status": "active", "schedule": "daily 06:30", "created": now, "goal": "Daily copper news"},
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
    assert t["status"] == "running" and t["door"] == "plan" and t["kind"] == "research" and not K.started    # TSK-21: the Conductor's
    assert t["done"] == ["names three offers with price, shop and delivery date"]
    assert [p["agent"] for p in t["spec"]["plan"]] == ["mission", "mission"]
    import conductor as CD
    tid = TK.handle({"action": "task_create", "text": "Buy a 32 GB DDR4 kit for my laptop when it is cheap"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda prompt: spec(kind="shopping"))                  # TSK-21: a price watch too, with its agent
    t = TK.row(K.c, tid)
    assert (t["door"], t["status"], t["spec"]["shop"]) == ("plan", "running", "ram-buy") and [s["harness"] for s in CD.steps(K.c, tid)] == ["shop"]
    kind, req = K.started[0]
    assert kind == "mission" and req["type"] == "shopping" and req["task"] == tid and not req["run_now"] and req["schedule"] == "manual"
    assert "Definition of done:\n- names three offers" in req["description"] and f"(Task #{tid} in Mission Control)" in req["description"]
    assert req["deliver"] == ["telegram", "app"]                                     # no e-mail unless the task asks for it
    TK.sync(K.c, TK.M.load_missions())
    assert [x["id"] for x in TK.state(K.c)["tasks"]] == [tid, tid - 1]               # the task's agent is no task of its own


def test_a_weekly_briefing_task_gets_its_content_not_the_plan_email_when_asked_and_shows_its_runs(K):
    """FND-77: the plan's agent instructions became the desk's notes and the writer reported itself blocked; the e-mail
    the owner asked for was never set up; the board said only "scheduled" although the first run had finished."""
    import conductor as CD
    import missions as MM
    drafted = []
    TK.M.slugify, TK.M.VAULT, TK.M.vault_commit = MM.slugify, K.tmp, lambda paths, msg: None
    TK.M.create_briefing = lambda meta, req: drafted.append((meta, req))
    TK.M.topic_of = lambda m: (({"key_questions": ["Sales and exports?", "Batteries?"], "window_hours": 180}, ""), None)
    tid = TK.handle({"action": "task_create", "text": "Send me an email with Chinese automotive news every week"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(kind="briefing", rhythm={"type": "schedule", "schedule": "weekly mon 08:00"},
                                          done=["covers sales and exports", "is emailed to the owner"]))
    t = TK.row(K.c, tid)
    meta, req = drafted[0]
    assert t["door"] == "plan" and t["status"] == "running" and not K.started and meta["schedule"] == "weekly mon 08:00"   # TSK-22
    assert "Plan:" not in req["description"] and "search the shops" not in req["description"] and "Task #" not in req["description"]
    assert "- covers sales and exports" in req["description"] and t["spec"]["deliver"] == ["telegram", "app", "email"]
    assert [p["step"] for p in t["spec"]["intake_plan"]] == ["search the shops", "write the report"]           # kept, not run
    assert [(s["harness"], s["item"]) for s in CD.steps(K.c, tid)] == [("desk-collect", None), ("hermes", "Sales and exports?"),
                                                                     ("hermes", "Batteries?"), ("desk-write", None), ("deliver", None)]
    assert CD.steps(K.c, tid)[1]["title"] == "Research the last 8 days — Sales and exports?"


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
    tid = TK.handle({"action": "task_create", "text": "Find Acme Mining's newest supply contract and read its terms"}, K.c)["task"]
    plan = [{"step": "find the contract", "agent": "scout", "why": "web", "after": []},
            {"step": "read its terms", "agent": "contract-reader", "why": "reads supply contracts", "after": [1]}]
    TK.intake(K.c, tid, ask=lambda p: spec(plan=plan))
    t = TK.row(K.c, tid)
    p2 = t["spec"]["plan"][1]
    assert p2["agent"] == "new" and "'contract-reader', which is no agent: a temporary agent is written for it" in p2["why"]
    assert t["door"] == "plan" and CD.steps(K.c, tid)[1]["harness"] == "temp"


def test_at_most_two_questions_and_answers_plan_it_again(K, monkeypatch):
    tid = TK.handle({"action": "task_create", "text": "Fix the thing on the phone page"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(kind="coding", repo=None, questions=["Which page?", "Which phone?", "Which colour?"]))
    t = TK.row(K.c, tid)
    assert t["status"] == "needs_answer" and t["questions"] == ["Which page?", "Which phone?"] and K.told and not K.started
    with pytest.raises(ValueError):
        TK.handle({"action": "task_answer", "id": tid, "answers": ["the AI phone page"]}, K.c)        # both must be answered
    TK.handle({"action": "task_answer", "id": tid, "answers": ["the AI phone page", "the S22"]}, K.c)
    assert TK.row(K.c, tid)["status"] == "intake"
    seen, specified = [], []
    import changes as CH
    monkeypatch.setattr(CH, "specify", lambda c, t, ask=None: specified.append(t))
    TK.intake(K.c, tid, ask=lambda p: seen.append(p) or spec(kind="coding", repo="ai-stack"))
    assert "- Which page?: the AI phone page" in seen[0]
    t = TK.row(K.c, tid)                                 # CHG-01: a coding task with its repository is a change request now
    assert t["kind"] == "change" and t["spec"]["repo"] == "ai-stack" and specified[0]["id"] == tid and not K.started


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
    assert t["status"] == "running" and t["door"] == "plan" and not K.started     # its first run starts now; then daily 07:00
    TK.handle({"action": "task_cancel", "id": tid}, K.c)                            # a plan task stops here, schedule and all
    assert TK.row(K.c, tid)["status"] == "cancelled"
    shop = TK.handle({**req, "text": "Buy the kit when it costs under 60 €", "kind": "shopping"}, K.c)["task"]
    TK.intake(K.c, shop, ask=lambda p: spec(kind="shopping"))
    TK.handle({"action": "task_approve", "id": shop}, K.c)
    t = TK.row(K.c, shop)
    assert (t["status"], t["door"], t["rhythm"]["schedule"]) == ("running", "plan", "daily 07:00") and K.started[0][1]["schedule"] == "manual"
    TK.sync(K.c, {"ram-old": {"slug": "ram-old", "title": "RAM", "type": "shopping", "status": "active", "schedule": "daily 07:00", "created": TK.now()}})
    door = next(x["id"] for x in TK.state(K.c)["tasks"] if x["door"] == "mission")
    with pytest.raises(ValueError, match="stop it on that page"):              # work started at a mission is stopped there
        TK.handle({"action": "task_cancel", "id": door}, K.c)
    other = TK.handle({"action": "task_create", "text": "Plan a trip I may not take", "autonomy": "ask"}, K.c)["task"]
    TK.handle({"action": "task_cancel", "id": other}, K.c)                         # not started yet: cancelled
    assert TK.row(K.c, other)["status"] == "cancelled"


def test_after_another_task_waits_until_that_one_is_done(K):
    first = TK.handle({"action": "task_create", "text": "Research the best 32 GB kits"}, K.c)["task"]
    TK.intake(K.c, first, ask=lambda p: spec())
    then = TK.handle({"action": "task_create", "text": "Then propose the cheapest one to buy", "rhythm": {"type": "after", "task": first}}, K.c)["task"]
    TK.intake(K.c, then, ask=lambda p: spec(kind="shopping"))
    assert TK.row(K.c, then)["status"] == "after" and TK.row(K.c, first)["door"] == "plan" and not K.started
    with pytest.raises(ValueError):
        TK.handle({"action": "task_create", "text": "after a task that is not there", "rhythm": {"type": "after", "task": 999}}, K.c)
    TK.sync(K.c, {})
    assert TK.row(K.c, then)["status"] == "after"                                  # the research runs: it waits
    TK.put(K.c, first, status="done")                                              # the Conductor finished it
    TK.sync(K.c, {s: {"slug": s, "title": s, "status": "active", "type": "task", "schedule": "manual", "once": True, "created": TK.now()}
                  for s in ("ram-buy",)})
    assert (TK.row(K.c, then)["status"], TK.row(K.c, then)["door"]) == ("running", "plan") and K.started[-1][1]["type"] == "shopping"


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


def test_a_task_on_an_event_waits_for_its_trigger_and_is_watched_with_the_missions_triggers(K):
    """TSK-21: an event-triggered task is the Conductor's too: it starts nothing until its trigger fires; a briefing on
    an event gets the desk's alert plan."""
    import conductor as CD
    import missions as MM
    TK.M.slugify, TK.M.VAULT, TK.M.vault_commit = MM.slugify, K.tmp, lambda paths, msg: None
    TK.M.create_briefing = lambda meta, req: None
    TK.M.topic_of = lambda m: (({"key_questions": ["Contracts?"]}, ""), None)
    news = {"type": "event", "triggers": [{"type": "news", "query": "Acme Mining supply contract"}]}
    tid = TK.handle({"action": "task_create", "text": "When Acme Mining signs a supply contract, tell me what it means for my position"}, K.c)["task"]
    TK.intake(K.c, tid, ask=lambda p: spec(rhythm=news))
    al = TK.handle({"action": "task_create", "text": "Alert me on Acme Mining supply contract news"}, K.c)["task"]
    TK.intake(K.c, al, ask=lambda p: spec(kind="briefing", rhythm=news))
    t, a = TK.row(K.c, tid), TK.row(K.c, al)
    assert (t["door"], t["status"], CD.occurrences(K.c, tid)) == ("plan", "scheduled", []) and not K.started
    assert [p["harness"] for p in a["spec"]["plan"]] == ["desk-alert", "deliver"] and a["status"] == "scheduled"
    assert sorted((w["task"], w["slug"], w["triggers"] == news["triggers"]) for w in TK.watchers(K.c)) == [(tid, f"task-{tid}", True), (al, f"task-{al}", True)]
    board = {x["id"]: x for x in TK.state(K.c)["tasks"]}
    assert board[tid]["runs"] == [] and board[tid]["next_run"] is None


def test_improving_a_wiki_or_a_page_is_a_task_that_ends_writing_into_that_wiki(K, monkeypatch):
    """TSK-34: the owner's correction or research request on a wiki or one of its pages becomes a task: the intake's
    research, then the wiki's writer as the last step after every leaf; a wiki or page that is not there is refused."""
    import conductor as CD
    import missions as MM
    import wikis as W
    monkeypatch.setattr(W, "roots", lambda: [("wiki", "Vault wiki"), ("missions/u/wiki", "Copper mining")])
    TK.M.VAULT, TK.M.split_front = K.tmp, MM.split_front
    (K.tmp / "missions/u/wiki/entities").mkdir(parents=True)
    (K.tmp / "missions/u/wiki/entities/acme-mining.md").write_text("---\ntitle: Acme Mining\n---\n## Key facts\n- 2025 output 30 Mlb")
    tid = TK.handle({"action": "task_create", "text": "Check its facts and fix the mistakes", "kind": "research",
                     "wiki": {"root": "missions/u/wiki", "page": "entities/acme-mining"}}, K.c)["task"]
    t = TK.row(K.c, tid)
    assert t["text"] == "Check its facts and fix the mistakes (On the wiki “Copper mining”, its page “Acme Mining”: what is found is written into it.)"
    assert t["spec"]["wiki"] == {"root": "missions/u/wiki", "title": "Copper mining", "page": "entities/acme-mining", "page_title": "Acme Mining"}
    plan = [{"step": "check the output", "agent": "scout", "why": "web", "after": []}, {"step": "check the price", "agent": "scout", "why": "web", "after": []}]
    TK.intake(K.c, tid, ask=lambda p: spec(plan=plan))
    t = TK.row(K.c, tid)
    assert t["door"] == "plan" and t["spec"]["wiki"]["page"] == "entities/acme-mining"                         # the intake keeps it
    assert [(s["agent"], s["harness"], s["after"]) for s in CD.steps(K.c, tid)] == [("scout", "hermes", []), ("scout", "hermes", []), ("mission", "wiki", [1, 2])]
    assert CD.steps(K.c, tid)[2]["title"] == "Write it into the wiki “Copper mining”, page “Acme Mining” first"
    for bad in ({"root": "missions/x/wiki"}, {"root": "missions/u/wiki", "page": "entities/nobody"}, {"root": "missions/u/wiki", "page": "../../etc"}):
        with pytest.raises(ValueError):
            TK.handle({"action": "task_create", "text": "Research what is missing", "wiki": bad}, K.c)


def test_a_briefing_that_runs_as_its_mission_moves_under_the_conductor_and_its_mission_keeps_the_topic(K, monkeypatch):
    """TSK-21, DEC-37: Run it under the Conductor on a briefing task that still runs as its mission: the task gets the
    desk's plan on the mission's schedule, its first run when due; the mission keeps its topic and wiki but runs no more
    by itself; only an active briefing or price watch can move."""
    import conductor as CD
    saved, commits = [], []
    m = {"slug": "china-auto", "title": "China auto", "type": "briefing", "status": "active", "schedule": "weekly mon 08:00",
         "topic": "china-auto", "deliver": ["telegram", "app", "email"], "triggers": [], "created": TK.now()}
    TK.M.load_missions = lambda: {"china-auto": m}
    TK.M.save_mission, TK.M.vault_commit = (lambda mm: saved.append(dict(mm))), (lambda paths, msg: commits.append(msg))
    TK.M.topic_of = lambda mm: (({"key_questions": ["Sales?", "Batteries?"], "window_hours": 180}, ""), None)
    tid = TK.register(K.c, "mission", "china-auto", "Weekly China auto news", "China auto", done=["covers sales"],
                      rhythm={"type": "schedule", "schedule": "weekly mon 08:00"}, status="scheduled", source="app")
    K.c.execute("update tasks set kind='briefing' where id=?", (tid,)); K.c.commit()
    out = TK.handle({"action": "task_conduct", "id": tid}, K.c)
    t = TK.row(K.c, tid)
    assert (t["door"], t["ref"], t["status"], t["rhythm"]) == ("plan", str(tid), "scheduled", {"type": "schedule", "schedule": "weekly mon 08:00"})
    assert t["spec"]["topic"] == "china-auto" and t["spec"]["deliver"] == ["telegram", "app", "email"] and out["steps"] == 5
    assert [p.get("harness") for p in t["spec"]["plan"]] == ["desk-collect", None, "desk-write", "deliver"]
    assert saved[-1]["task"] == tid and saved[-1]["schedule"] == "manual" and commits
    assert CD.occurrences(K.c, tid) == []                                           # its first run comes when due, not now
    with pytest.raises(ValueError):
        TK.handle({"action": "task_conduct", "id": tid}, K.c)                       # moved already: it is a plan task now


def test_the_intake_keeps_a_check_s_fix_loop_and_a_budget_preset():
    import tasks as TK
    agents = {"builder": "codes", "judge": "runs every test"}
    s = TK.validate({"kind": "research", "done": ["the tests pass on main"], "plan": [{"step": "code", "agent": "builder", "after": []},
                     {"step": "test", "agent": "judge", "after": [1], "loop": {"to": 1, "max": 3}}]}, {}, [], agents)
    assert s["plan"][1]["loop"] == {"to": 1, "max": 3} and "loop" not in s["plan"][0]
    assert TK.preset_of({"budget": {"hours": 30, "tokens": "3000000"}}) == {"budget": {"hours": 24.0, "tokens": 3000000}}


def test_the_plan_sees_what_each_agent_can_reach():
    """TSK-35: the intake gave the AI phone's steps to an agent without the phone (task #104); the agents it plans with
    name their tools in words, so a phone step goes to the agent that holds the phone."""
    import tasks as T
    agents = T.cards()
    assert "the AI phone" in agents["main"] and "the AI phone" not in agents["mission"]
    assert "web research" in agents["mission"] and "Its tools:" not in agents["judge"]



def test_a_long_task_s_name_is_cut_at_a_word_and_marked():
    """Task 93's name was its words cut at 80 characters mid-word ("... estimates as s"), without a mark."""
    long = "A breaking story: Earnings call transcript: Acme Mining misses Q3 2026 estimates as shares fall, and more"
    t = TK.title_of(long)
    assert t.endswith(" …") and len(t) <= TK.TITLE and long.startswith(t[:-2]) and not t[:-2].endswith("as s")
    assert TK.title_of("  Short   one ") == "Short one" and TK.title_of("") == ""
