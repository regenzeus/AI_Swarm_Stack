"""The Conductor (TSK-05 to TSK-09): a plan graph whose steps wait for the steps they need and run at the same time
otherwise, a cycle refused; every step recorded so a restart resumes at the first unfinished step and runs no finished
one again (a Claude step keeps waiting for its Claude task); headroom before a step starts; each step its own run in
the task's trace; a step that fails twice fails its task with the reason; the owner can cancel."""
import json
import sqlite3
import time
import types

import pytest
from pathlib import Path

import conductor as CD
import notify as N
import runtime as RTM
import tasks as TK

PLAN = [{"step": "Find the facts", "agent": "scout", "why": "reads the web", "after": []},
        {"step": "List the changes", "agent": "mission", "why": "works through it", "after": [1]},
        {"step": "Name a risk", "agent": "planner", "why": "reasons about code", "after": [1]},
        {"step": "Summarise", "agent": "desk", "why": "writes briefings", "after": [2, 3]}]


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
    c.execute("create table claude_tasks (id integer primary key, status text, answer text, error text)")
    events, runs, sent, ran = [], [], [], []
    import missions as MM
    import threading
    ns = types.SimpleNamespace(db=conn, event=lambda *a, **k: events.append(a), log=print, paused=MM.paused, VAULT=tmp_path,
                               vault_commit=lambda paths, msg: None, X=types.SimpleNamespace(APP="https://x"), stop=threading.Event())
    CD.M = TK.M = ns
    monkeypatch.setattr(CD, "RESULTS", tmp_path / "tasks")
    monkeypatch.setattr(CD, "headroom", lambda s: None)
    monkeypatch.setattr(N, "send", lambda text, category, **k: sent.append(text) or {})
    monkeypatch.setattr(RTM, "start", lambda run, agent, title, data=None, ref=None, detail="": runs.append(("start", run, ref)))
    monkeypatch.setattr(RTM, "end", lambda run, agent, state, detail="", seconds=None: runs.append(("end", run, state)))
    monkeypatch.setattr(RTM, "set_ref", lambda *a, **k: None)

    def adapter(c, t, s, prompt, card):
        ran.append(s["idx"])
        return f"result of step {s['idx']}"
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": adapter, "python": adapter, "claude-code": adapter})
    t0 = TK.now()
    cur = c.execute("insert into tasks (text, title, goal, kind, door, done, effort, autonomy, rhythm, spec, questions, answers, status, source, created, updated) "
                    "values ('x','RAM check','Find the facts','research','plan','[\"three facts\"]','standard','auto','{\"type\":\"once\"}',?, '[]','[]','running','app',?,?)",
                    (json.dumps({"plan": PLAN}), t0, t0))
    c.commit()
    tid = cur.lastrowid
    TK.put(c, tid, ref=CD.start(c, TK.row(c, tid)))
    return types.SimpleNamespace(c=c, tid=tid, events=events, runs=runs, sent=sent, ran=ran, conn=conn, tmp=tmp_path)


def tick(K):
    CD.tick(K.c, start_thread=lambda f: f())


def status(K):
    return {s["idx"]: s["status"] for s in CD.steps(K.c, K.tid)}


def test_branches_run_together_the_join_after_both_and_a_cycle_is_refused(K):
    tick(K)
    assert K.ran == [1] and status(K) == {1: "done", 2: "pending", 3: "pending", 4: "pending"}
    tick(K)
    assert K.ran == [1, 2, 3] and status(K)[4] == "pending"                        # 2 and 3 in the same pass
    tick(K)
    assert K.ran == [1, 2, 3, 4]
    tick(K)
    t = TK.row(K.c, K.tid)
    assert t["status"] == "done" and t["spec"]["result"].startswith("tasks/")
    assert (K.tmp / t["spec"]["result"]).read_text().endswith("result of step 4\n") and "is done" in K.sent[0]
    with pytest.raises(ValueError, match="cycle"):
        CD.graph([{"step": "a", "agent": "scout", "after": [2]}, {"step": "b", "agent": "mission", "after": [1]}])
    with pytest.raises(ValueError, match="not another step"):
        CD.graph([{"step": "a", "agent": "scout", "after": [3]}])
    with pytest.raises(ValueError, match="no agent that can do a step"):
        CD.graph([{"step": "a", "agent": "checker", "after": []}])                  # a script agent has no model


def test_one_trace_the_task_s_run_holds_each_step_s_run(K):
    for _ in range(4):
        tick(K)
    starts = [(r, ref) for kind, r, ref in K.runs if kind == "start"]
    assert (f"task:{K.tid}", f"task-intake:{K.tid}-0") in starts
    assert all((f"task:{K.tid}:step:{i}", f"task:{K.tid}") in starts for i in range(1, 5))
    assert ("end", f"task:{K.tid}", "done") in K.runs


def test_a_restart_runs_the_interrupted_step_again_and_no_finished_step_twice(K):
    tick(K)
    tick(K)                                                                        # 1, 2, 3 done
    s4 = next(s for s in CD.steps(K.c, K.tid) if s["idx"] == 4)
    CD.put(K.c, s4["id"], status="running", attempts=1)                            # the runner died during step 4
    CD.recover(K.c)
    s = {x["idx"]: x for x in CD.steps(K.c, K.tid)}
    assert s[4]["status"] == "pending" and s[4]["attempts"] == 0 and s[4]["waiting_for"] == "the runner restarted"
    tick(K)
    assert K.ran == [1, 2, 3, 4] and all(x["attempts"] == 1 for x in CD.steps(K.c, K.tid))


def test_a_step_cut_off_by_the_runner_stopping_is_interrupted_not_failed(K, monkeypatch):
    import threading
    K.c.execute("select 1")
    stop = threading.Event()
    CD.M.stop = stop

    def cut(c, t, s, prompt, card):
        stop.set()                                                                 # a deploy stops the runner mid-step
        raise RuntimeError("Hermes (scout) ended with exit 0: ")
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "hermes": cut})
    tick(K)
    s1 = CD.steps(K.c, K.tid)[0]
    assert s1["status"] == "running" and not s1["error"] and ("end", f"task:{K.tid}:step:1", "stopped") in K.runs
    CD.recover(K.c)
    s1 = CD.steps(K.c, K.tid)[0]
    assert s1["status"] == "pending" and s1["attempts"] == 0                        # runs again, no attempt spent


def test_a_claude_task_cut_off_by_the_runner_stopping_is_queued_again(monkeypatch, tmp_path):
    import threading
    import claude_tasks as CT
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    CT.table(c)
    c.execute("insert into claude_tasks (question, mode, status, created) values ('why?', 'ask', 'queued', 'now')"); c.commit()
    stop = threading.Event()
    CT.M = types.SimpleNamespace(stop=stop, now=lambda: __import__("datetime").datetime.now(), log=lambda *a: None, event=lambda *a, **k: None)
    monkeypatch.setattr(CT, "B", types.SimpleNamespace(BUILDER="aistack-builder-1", SERENA_FOR_CLAUDE="{}",
                                                       claude_result=lambda log: {"text": "", "limit_reset": None}), raising=False)
    monkeypatch.setattr(CT, "TMP", tmp_path)
    monkeypatch.setattr(CT, "snapshot", lambda *a: str(tmp_path))
    monkeypatch.setattr(CT, "write", lambda *a: None)

    class Proc:
        stdout = iter([])

        def __init__(self, *a, **k):
            stop.set()

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass
    monkeypatch.setattr(CT.subprocess, "Popen", Proc)
    CT.run(c, dict(c.execute("select * from claude_tasks where id=1").fetchone()))
    r = c.execute("select status, error from claude_tasks where id=1").fetchone()
    assert (r["status"], r["error"]) == ("queued", None)                          # asked again after the restart


def test_a_claude_step_waits_for_its_claude_task_also_across_a_restart(K, monkeypatch):
    import claude_tasks as CT
    asked = []
    monkeypatch.setattr(CT, "handle", lambda req, c: asked.append(req) or c.execute("insert into claude_tasks (status) values ('queued')").lastrowid and {"id": 1})
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "claude-code": CD.run_claude})
    tick(K)
    tick(K)
    s3 = next(s for s in CD.steps(K.c, K.tid) if s["idx"] == 3)
    assert s3["status"] == "waiting" and s3["resume"] == {"claude_task": 1} and len(asked) == 1
    assert "## Results of the steps before yours" in asked[0]["context"] and "result of step 1" in asked[0]["context"]
    assert asked[0]["source"] == f"task:{K.tid}:step:3"          # TSK-09: Claude's run nests in the step's, one trace
    CD.recover(K.c)
    assert next(s for s in CD.steps(K.c, K.tid) if s["idx"] == 3)["status"] == "waiting"   # not asked again
    K.c.execute("update claude_tasks set status='done', answer='a risk' where id=1"); K.c.commit()
    tick(K)
    s3 = next(s for s in CD.steps(K.c, K.tid) if s["idx"] == 3)
    assert s3["status"] == "done" and s3["output"] == "a risk" and len(asked) == 1 and s3["attempts"] == 1


def test_a_step_starts_only_with_headroom_and_says_what_it_waits_for(K, monkeypatch, tmp_path):
    monkeypatch.setattr(CD, "headroom", lambda s: "memory: 0.40 GB available on the PC, it starts at 0.5 GB")
    tick(K)
    s1 = CD.steps(K.c, K.tid)[0]
    assert K.ran == [] and s1["status"] == "pending" and s1["waiting_for"].startswith("memory: 0.40 GB")
    host = tmp_path / "host.json"
    host.write_text('{"ram_free_gb": 0.6, "ram_available_gb": 0.8}')
    assert CD.free_gb(host=host) == 0.8                                            # available, not just free
    host.write_text('{"ram_free_gb": 0.6}')
    assert CD.free_gb(host=host) == 0.6                                            # an older probe: free
    assert abs(CD.free_gb(host=host, now=time.time() + 600, meminfo="MemAvailable: 3145728 kB\n") - 3.0) < 0.01   # a stale probe: WSL's own
    monkeypatch.undo()
    ok = lambda e: False
    assert CD.headroom({"model": "gpt-sub", "harness": "python"}, free=0.3, limited=ok) is None      # a model call needs little
    assert CD.headroom({"model": "gpt-sub", "harness": "hermes"}, free=0.6, limited=ok) is None
    assert CD.headroom({"model": "claude-subscription", "harness": "claude-code"}, free=0.6, limited=ok).startswith("memory")
    assert "usage limit" in CD.headroom({"model": "claude-subscription", "harness": "claude-code"}, free=4.0, limited=lambda e: e == "claude")


def test_a_step_that_fails_twice_fails_its_task_and_a_limit_is_waited_out(K, monkeypatch):
    def broken(c, t, s, prompt, card):
        raise RuntimeError("Hermes (scout) ended with exit 1: boom")
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "hermes": broken})
    tick(K)
    assert CD.steps(K.c, K.tid)[0]["status"] == "pending" and CD.steps(K.c, K.tid)[0]["attempts"] == 1
    tick(K)
    assert CD.steps(K.c, K.tid)[0]["status"] == "failed"
    tick(K)
    t = TK.row(K.c, K.tid)
    assert t["status"] == "failed" and "step 1 (scout) failed" in t["error"] and "failed" in K.sent[-1]

    def limited(c, t, s, prompt, card):
        raise RuntimeError("RateLimitError: usage_limit_reached")
    CD.put(K.c, CD.steps(K.c, K.tid)[0]["id"], status="pending", attempts=0)
    TK.put(K.c, K.tid, status="running")
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "hermes": limited})
    tick(K)
    s1 = CD.steps(K.c, K.tid)[0]
    assert s1["status"] == "pending" and s1["attempts"] == 0 and "usage limit" in s1["waiting_for"]


def test_the_owner_can_cancel_and_every_planned_task_goes_to_the_conductor(K):
    tick(K)
    TK.handle({"action": "task_cancel", "id": K.tid}, K.c)
    assert TK.row(K.c, K.tid)["status"] == "cancelled" and set(status(K).values()) == {"done", "cancelled"}
    tick(K)
    assert K.ran == [1]
    base = {"kind": "research", "rhythm": {"type": "once"}, "spec": {"plan": PLAN}}
    assert TK.conducted(base) and TK.conducted({**base, "spec": {"plan": [PLAN[0]]}})                  # TSK-21: one step too
    assert TK.conducted({**base, "rhythm": {"type": "schedule", "schedule": "daily 07:00"}})             # and on a schedule
    assert not TK.conducted({**base, "kind": "coding"})                                                 # code changes need the builder
    assert TK.conducted({**base, "kind": "coding", "spec": {"plan": [{"step": "change it", "agent": "builder", "why": "", "after": []}]}})
    assert TK.conducted({**base, "kind": "briefing", "spec": {"plan": []}})               # the desk's plan replaces the intake's
    assert TK.conducted({**base, "kind": "shopping", "spec": {"plan": []}})                # a price watch: its agent's check
    assert TK.conducted({**base, "rhythm": {"type": "event", "triggers": [{"type": "news", "query": "uranium"}]}})   # on an event
    assert not TK.conducted({**base, "spec": {"plan": []}})


def scheduled(K, plan, schedule="weekly mon 08:00"):
    import missions as MM
    K.c.execute("update tasks set rhythm=?, spec=? where id=?", (json.dumps({"type": "schedule", "schedule": schedule}), json.dumps({"plan": plan}), K.tid))
    K.c.execute("delete from task_steps"); K.c.execute("delete from task_occ"); K.c.commit()
    CD.M.next_due, CD.M.now = MM.next_due, MM.now
    CD.start(K.c, TK.row(K.c, K.tid))
    return MM


def test_a_scheduled_task_runs_at_once_then_each_time_from_its_template_with_its_own_trace(K):
    MM = scheduled(K, [{"step": "Look it up", "agent": "scout", "why": "reads the web", "after": []}])
    tick(K); tick(K)
    t = TK.row(K.c, K.tid)
    assert t["status"] == "scheduled" and t["spec"]["result"].endswith("-1.md") and "Task #%d run 1 is done" % K.tid in K.sent[-1]
    assert [o["status"] for o in CD.occurrences(K.c, K.tid)] == ["done"] and ("end", f"task:{K.tid}", "done") in K.runs
    tick(K)
    assert len(CD.occurrences(K.c, K.tid)) == 1                                       # not due before Monday
    K.c.execute("update task_occ set started=? where task=?", ((MM.now() - __import__("datetime").timedelta(days=8)).isoformat(), K.tid)); K.c.commit()
    tick(K)
    assert [o["occ"] for o in CD.occurrences(K.c, K.tid)] == [2, 1] and TK.row(K.c, K.tid)["status"] == "running"
    assert ("start", f"task:{K.tid}.2", f"task-intake:{K.tid}-0") in K.runs and [s["occ"] for s in CD.steps(K.c, K.tid)] == [2]
    tick(K)
    assert ("start", f"task:{K.tid}.2:step:1", f"task:{K.tid}.2") in K.runs and CD.steps(K.c, K.tid, 1)[0]["status"] == "done"
    nxt = TK.state(K.c)["tasks"][0]
    assert nxt["next_run"] and nxt["last_run"]["live"] in (f"task:{K.tid}", f"task:{K.tid}.2")


def test_a_step_with_items_fans_out_in_parallel_and_the_next_waits_for_every_copy(K):
    scheduled(K, [{"step": "Collect", "agent": "desk", "why": "", "after": []},
                  {"step": "Research", "agent": "scout", "why": "", "after": [1], "each": ["sales", "batteries", "policy"]},
                  {"step": "Write", "agent": "desk", "why": "", "after": [2]}])
    ss = CD.steps(K.c, K.tid)
    assert [(s["idx"], s["title"], s["after"]) for s in ss] == [(1, "Collect", []), (2, "Research — sales", [1]), (3, "Research — batteries", [1]),
                                                                  (4, "Research — policy", [1]), (5, "Write", [2, 3, 4])]
    tick(K)
    assert K.ran == [1]
    tick(K)
    assert K.ran == [1, 2, 3, 4]                                                       # the copies start in one pass (as SLOTS allow)
    tick(K)
    assert K.ran == [1, 2, 3, 4, 5] and "Research — policy" in CD.prompt_of(TK.row(K.c, K.tid), CD.steps(K.c, K.tid)[3], CD.steps(K.c, K.tid), CD.cards())


def test_a_briefing_runs_collect_scouts_write_and_deliver_and_each_desk_step_hands_on_its_work(K, monkeypatch):
    """TSK-22: the desk collects, a scout per key question researches at the same time, the desk writes from both, and
    the report is delivered the ways the task asked; the writing step files under the collecting step's date."""
    import datetime as dt
    import missions as MM
    slug, date = "china-auto", dt.date.today().isoformat()
    monkeypatch.setattr(CD, "DESK", K.tmp / "desk")
    (K.tmp / "desk" / slug / "out").mkdir(parents=True)
    calls, delivered = [], []

    def desk_run(s, mode, d, findings=None):
        calls.append((mode, d, findings))
        if mode == "collect":
            (K.tmp / "desk" / slug / "out" / f"{d}.collected.json").write_text(json.dumps({"stats": {"items": 627, "new": 406, "events": 327},
                "chosen": [[{"items": [{"title": "VW profit falls 99%", "source": "财新", "url": "https://caixin.com/1"}]}, {}]]}))
            return f"x {s} {d} collected: ..."
        rel = f"topics/{slug}/reports/{d[:4]}/{d[5:7]}/{d}.md"
        (K.tmp / rel).parent.mkdir(parents=True)
        (K.tmp / rel).write_text('---\nheadline: "China Automotive Weekly"\nstats: {"chosen": 3}\n---\n\n# China Automotive Weekly\n\nVW [1]\n')
        return f"x {s} {d} filed: {rel} stats: {{}}"
    monkeypatch.setattr(CD, "desk_run", desk_run)
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "desk-collect": CD.run_desk_collect, "desk-write": CD.run_desk_write, "deliver": CD.run_deliver})
    CD.M.X = types.SimpleNamespace(APP="https://x", briefing_empty=lambda text: False,
                                   deliver=lambda m, title, short, rel, kicker, text, empty=False: delivered.append((m, title, kicker)) or True)
    CD.M.period, CD.M.now = MM.period, MM.now
    plan = CD.briefing_plan({"goal": "China car news"}, {"key_questions": ["Sales?", "Batteries?"], "window_hours": 180})
    K.c.execute("update tasks set kind='briefing', rhythm=?, spec=? where id=?", (json.dumps({"type": "schedule", "schedule": "weekly mon 08:00"}),
                json.dumps({"plan": plan, "topic": slug, "deliver": ["telegram", "app", "email"]}), K.tid))
    K.c.execute("delete from task_steps"); K.c.commit()
    CD.start(K.c, TK.row(K.c, K.tid))
    for _ in range(5):
        tick(K)
    ss = CD.steps(K.c, K.tid)
    assert [s["status"] for s in ss] == ["done"] * 5 and [k[0] for k in calls] == ["collect", "write"]
    assert "627 items collected" in ss[0]["output"] and "VW profit falls 99% · 财新 · https://caixin.com/1" in ss[0]["output"]
    assert calls[1][1] == date and [f["question"] for f in calls[1][2]] == ["Sales?", "Batteries?"] and calls[1][2][0]["text"] == "result of step 2"
    m, title, kicker = delivered[0]
    assert m == {"slug": slug, "title": "RAM check", "deliver": ["telegram", "app", "email"]} and title == "China Automotive Weekly"
    assert kicker.startswith("Weekly briefing · ") and ss[4]["output"].startswith("Delivered by Telegram and e-mail and kept in the app")
    t = TK.row(K.c, K.tid)
    assert t["status"] == "scheduled" and "VW [1]" in (K.tmp / t["spec"]["result"]).read_text()


def test_a_build_step_waits_for_its_build_and_the_owner_s_tap_and_a_task_runs_again_on_request(K, monkeypatch):
    import builds as B
    K.c.execute("create table builds (id integer primary key, status text, summary text, error text)")
    K.c.execute("update tasks set kind='coding', spec=? where id=?", (json.dumps({"repo": "ai-stack", "plan": [
        {"step": "Add dark mode", "agent": "builder", "why": "changes code", "after": []}]}), K.tid))
    K.c.execute("delete from task_steps"); K.c.commit()
    asked = []
    monkeypatch.setattr(B, "handle", lambda req, c: asked.append(req) or {"id": c.execute("insert into builds (status) values ('working')").lastrowid})
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "build": CD.run_build})
    CD.start(K.c, TK.row(K.c, K.tid))
    assert CD.steps(K.c, K.tid)[0]["harness"] == "build"
    tick(K)
    s = CD.steps(K.c, K.tid)[0]
    assert asked[0]["repo"] == "ai-stack" and s["status"] == "waiting" and s["waiting_for"] == "build #1: working"
    K.c.execute("update builds set status='review'"); K.c.commit()
    tick(K)
    assert CD.steps(K.c, K.tid)[0]["waiting_for"] == "build #1: waits for your review" and len(asked) == 1
    K.c.execute("update builds set status='deployed', summary='Dark mode toggle in Settings'"); K.c.commit()
    tick(K); tick(K)
    assert TK.row(K.c, K.tid)["status"] == "done" and "Build #1 deployed" in CD.steps(K.c, K.tid)[0]["output"]
    TK.handle({"action": "task_run", "id": K.tid}, K.c)
    assert TK.row(K.c, K.tid)["status"] == "running" and CD.occurrences(K.c, K.tid)[0]["trigger"] == "owner"
    with pytest.raises(ValueError, match="running now"):
        TK.handle({"action": "task_run", "id": K.tid}, K.c)


def test_each_step_s_prompt_carries_the_results_it_waits_for():
    t = {"goal": "Find the facts", "done": ["three facts"]}
    ss = [{"idx": 1, "title": "Find", "agent": "scout", "after": [], "output": "fact A"},
          {"idx": 2, "title": "Sum up", "agent": "desk", "after": [1], "output": None}]
    p = CD.prompt_of(t, ss[1], ss, CD.cards())
    assert "Your step (2 of 2): Sum up" in p and "### Step 1: Find (scout)\nfact A" in p and "last step: yes" in p
    assert p.ref.startswith("shared/TASK_STEP@")


def test_a_long_requirements_list_reaches_the_builder_apart_from_its_brief():
    """FND-99: the analyst's 28,000-character list put the tester's brief over the builder's 20,000; the results now
    travel apart, and the step's own brief and standing instructions stay in the description."""
    t = {"goal": "Build mustachelib", "done": ["every rule"]}
    ss = [{"idx": 1, "title": "Requirements", "agent": "analyst", "after": [], "output": "R-1 a rule.\n" * 2500},
          {"idx": 2, "title": "Acceptance tests", "agent": "tester", "after": [1], "output": None}]
    head, results = CD.split_brief(str(CD.prompt_of(t, ss[1], ss, CD.cards())))
    assert len(head) < 20000 < len(results) and "Your step (2 of 2): Acceptance tests" in head
    assert "standing instructions (tester's card)" in head and "standing instructions" not in results
    assert results.startswith("## Results of the steps before yours\n### Step 1: Requirements (analyst)\nR-1 a rule.")
    assert CD.split_brief("Just a brief") == ("Just a brief", "")


def test_a_result_too_long_for_a_prompt_goes_by_reference_through_every_adapter(tmp_path, monkeypatch):
    """MEM-15 (FND-104), the size contract: a 150,000-character result reaches a Hermes step as its marked start and the
    vault file with the whole of it, an OpenCode step as a file in its work folder, a Claude or build step whole apart
    from its brief; a short one stays whole; no prompt is cut silently and none passes one command-line argument."""
    monkeypatch.setattr(CD, "RESULTS", tmp_path / "tasks")
    t = {"id": 7, "goal": "Build it", "done": ["every rule"]}
    big = "R-1 a rule that matters.\n" * 6000                                         # 150,000 characters
    prev = {"idx": 1, "title": "Requirements", "agent": "analyst", "after": [], "output": big, "occ": 1}
    small = {"idx": 2, "title": "Notes", "agent": "analyst", "after": [], "output": "short notes", "occ": 1}
    for harness in ("hermes", "opencode", "claude", "build"):
        s = {"idx": 3, "title": "Tests", "agent": "tester", "after": [1, 2], "harness": harness, "output": None}
        p = str(CD.prompt_of(t, s, [prev, small, s], CD.cards()))
        if harness in ("claude", "build"):
            assert big in CD.split_brief(p)[1]                                         # whole, apart from the brief
            continue
        assert big not in p and len(p) < CD.HANDOFF + 20000 and len(p.encode()) < CD.ARG_BYTES
        assert "### Step 2: Notes (analyst)\nshort notes" in p and "R-1 a rule that matters." in p
        where = "/step/results/7-1-step-1.md in your work folder" if harness == "opencode" else "the vault file tasks/7-1-step-1.md"
        assert f"more characters cut: the whole result (150,000 characters) is {where}" in p, harness
    assert (tmp_path / "tasks/7-1-step-1.md").read_text() == big
    seen = {}

    def run(cmd, **kw):                                                                # the OpenCode container: what it is given
        d = cmd[cmd.index("-v") + 1].split(":")[0]
        seen.update({f.name: f.read_text() for f in Path(d, "results").iterdir()})
        raise RuntimeError("stop here")
    monkeypatch.setattr(CD, "steps", lambda c, task, occ=None: [prev, small])
    monkeypatch.setenv("VK_OPENCODE", "k")
    s = {"idx": 3, "title": "Tests", "agent": "tester", "after": [1, 2], "harness": "opencode", "occ": 1}
    with pytest.raises(RuntimeError, match="stop here"):
        CD.run_opencode(None, {**t, "spec": {}}, s, "the prompt", {"key": "vk-opencode"}, run=run)
    assert seen["7-1-step-1.md"] == big and seen["7-1-step-2.md"] == "short notes"
    with pytest.raises(RuntimeError, match="one command-line argument holds 122,880"):
        CD.run_hermes(None, t, {"agent": "scout"}, "x" * 130000, {})


def on_event(K, plan, kind="research"):
    K.c.execute("update tasks set kind=?, rhythm=?, spec=?, status='scheduled' where id=?",
                (kind, json.dumps({"type": "event", "triggers": [{"type": "news", "query": "Cameco"}]}), json.dumps({"plan": plan}), K.tid))
    K.c.execute("delete from task_steps"); K.c.execute("delete from task_occ"); K.c.commit()


EV = {"kind": "news", "trigger": "News about “Cameco”", "summary": "1 new article(s) about “Cameco”: Cameco signs a supply deal",
      "items": [{"title": "Cameco signs a supply deal", "url": "https://news.example/1"}]}


def test_an_event_starts_a_run_whose_steps_know_the_event_and_more_events_wait_their_turn(K, monkeypatch):
    """TSK-21: each firing of the task's trigger is an occurrence of its own, its event in every step's prompt; events
    that come while a run is going wait in order (at most QUEUE), and cancelling drops them."""
    prompts = []
    monkeypatch.setattr(CD, "ADAPTERS", {"hermes": lambda c, t, s, prompt, card: prompts.append(prompt) or f"answer {len(prompts)}"})
    on_event(K, [{"step": "Say what it means", "agent": "scout", "why": "reads the web", "after": []}])
    tick(K)
    assert CD.occurrences(K.c, K.tid) == []                                           # nothing until the trigger fires
    CD.fire(K.c, K.tid, EV)
    CD.fire(K.c, K.tid, {**EV, "summary": "a second deal"})
    tick(K)
    o = CD.occurrences(K.c, K.tid)
    assert [(x["occ"], x["trigger"], x["event"]["summary"]) for x in o] == [(1, "event", EV["summary"])] and TK.row(K.c, K.tid)["status"] == "running"
    tick(K); tick(K)
    assert "This run was started by an event: News about “Cameco”: 1 new article(s)" in prompts[0] and "https://news.example/1" in prompts[0]
    assert TK.row(K.c, K.tid)["status"] == "running" and CD.occurrences(K.c, K.tid)[0]["event"]["summary"] == "a second deal"
    tick(K); tick(K)
    assert [x["status"] for x in CD.occurrences(K.c, K.tid)] == ["done", "done"] and TK.row(K.c, K.tid)["status"] == "scheduled"
    assert ("start", f"task:{K.tid}.2", f"task-intake:{K.tid}-0") in K.runs and "Task #%d run 2 is done" % K.tid in K.sent[-1]
    for i in range(CD.QUEUE + 2):
        CD.fire(K.c, K.tid, {**EV, "summary": f"deal {i}"})
    waiting = [json.loads(r["event"])["summary"] for r in K.c.execute("select event from task_events where task=? and occ is null order by id", (K.tid,))]
    assert waiting == [f"deal {i}" for i in range(2, CD.QUEUE + 2)]                # the oldest go first, logged
    TK.handle({"action": "task_cancel", "id": K.tid}, K.c)
    assert K.c.execute("select count(*) from task_events where task=? and occ is null", (K.tid,)).fetchone()[0] == 0


def test_a_price_watch_runs_its_shopping_agent_s_check_and_a_reached_target_starts_its_next_run(K, monkeypatch):
    """TSK-21: a price watch's run is its shopping agent's check; a check without a drop is kept and not judged; when a
    waiting proposal reaches its price, the agent's re-check is the task's next run (buying stays the agent's run)."""
    import shopping as SH
    seen = []
    m = {"slug": "ram-buy", "title": "RAM", "type": "shopping", "status": "active", "watch_pct": 5, "best_price_eur": 100.0, "task": K.tid}

    def research(mm, logf, ev=None):
        seen.append((logf, ev))
        mm["best_price_eur"] = 98.0 if not ev else 90.0                               # 2 % less: no drop; then the target
        (K.tmp / "missions").mkdir(exist_ok=True)
        (K.tmp / f"missions/r{len(seen)}.md").write_text(f"# RAM\n\nreport {len(seen)}")
        return "ok", "best 98 €", f"missions/r{len(seen)}.md"
    monkeypatch.setattr(SH, "research", research)
    monkeypatch.setattr(SH, "proposals", lambda slug=None: [{"id": "p-1", "status": "watching", "item": "32 GB kit", "total_eur": 98.0, "shop": "Amazon"}])
    CD.M.load_missions, CD.M.RUNLOGS = (lambda: {"ram-buy": m}), K.tmp
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "shop": CD.run_shop})
    K.c.execute("update tasks set kind='shopping', rhythm=?, spec=? where id=?", (json.dumps({"type": "schedule", "schedule": "daily 07:00"}),
                json.dumps({"plan": CD.shop_plan({}), "shop": "ram-buy"}), K.tid))
    K.c.execute("delete from task_steps"); K.c.execute("delete from task_occ"); K.c.commit()
    CD.start(K.c, TK.row(K.c, K.tid))
    assert [(s["agent"], s["harness"]) for s in CD.steps(K.c, K.tid)] == [("mission", "shop")]
    tick(K); tick(K)
    o = CD.occurrences(K.c, K.tid)[0]
    out = CD.steps(K.c, K.tid)[0]["output"]
    assert out.startswith("No price drop of 5 % or more: kept in the app, not sent (missions/r1.md). Proposal p-1: watching, 32 GB kit for 98.00 € at Amazon.")
    assert (o["status"], o["verdict"]) == ("done", "quiet") and o["judged"] and "found nothing new" in K.sent[-1]
    SH.recheck(K.c, m, {"trigger": "price target reached", "summary": "32 GB kit now 90.00 € at Amazon"})
    tick(K); tick(K)
    o = CD.occurrences(K.c, K.tid)[0]
    assert (o["occ"], o["trigger"], o["verdict"]) == (2, "event", None) and seen[1][1]["trigger"] == "price target reached"
    assert CD.steps(K.c, K.tid)[0]["output"].startswith("Reported the ways the task asked") and seen[0][0].endswith(f"task-{K.tid}.1-1.log")


def test_an_event_triggered_briefing_writes_the_desk_s_alert_and_delivers_it(K, monkeypatch):
    delivered = []
    rel = "topics/cameco/alerts/2026/11/x.md"
    (K.tmp / rel).parent.mkdir(parents=True)
    (K.tmp / rel).write_text("# Cameco signs\n\nWhat it means [1]")
    CD.M.X = types.SimpleNamespace(APP="https://x", alert_of=lambda topic, ev: ({"title": "Cameco signs", "markdown": "# Cameco signs", "short": "A deal"}, ""),
                                   file_alert=lambda topic, a, ev: rel,
                                   deliver=lambda m, title, short, r, kicker, text, empty=False: delivered.append((title, short, r, kicker)) or True)
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "desk-alert": CD.run_desk_alert, "deliver": CD.run_deliver})
    on_event(K, CD.alert_plan({}), kind="briefing")
    K.c.execute("update tasks set spec=? where id=?", (json.dumps({"plan": CD.alert_plan({}), "topic": "cameco", "deliver": ["telegram", "app"]}), K.tid))
    K.c.commit()
    CD.fire(K.c, K.tid, EV)
    for _ in range(4):
        tick(K)
    assert delivered == [("Cameco signs", "A deal", rel, "Alert · News about “Cameco”")]
    assert CD.steps(K.c, K.tid)[1]["output"].startswith("Delivered by Telegram and kept in the app") and TK.row(K.c, K.tid)["status"] == "scheduled"


def test_a_wiki_refinement_s_research_sees_the_page_and_its_writer_folds_the_findings_in_page_first(K, monkeypatch):
    """TSK-34: every research step gets the page as it stands; the wiki step writes the findings to the vault and folds
    them into the wiki, the page asked about first, then every page the findings name, six at a time."""
    import mission_extras as X
    import missions as MM
    prompts, calls, commits = [], [], []
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "hermes": lambda c, t, s, prompt, card: prompts.append(prompt) or "Cameco produced 31 Mlb; Kazatomprom and Orano unchanged", "wiki": CD.run_wiki})
    pages = [{"path": p, "title": t, "summary": "", "aliases": []} for p, t in (("entities/cameco", "Cameco"), ("entities/kazatomprom", "Kazatomprom"), ("entities/orano", "Orano"), ("entities/other", "Other"))]
    monkeypatch.setattr(X, "wiki_pages", lambda root: pages)
    monkeypatch.setattr(X, "compile_into", lambda root, title, src, text, key, touched=None: calls.append((root, src, list(touched), text)) or list(touched))
    monkeypatch.setenv("VK_MISSION", "k")
    (K.tmp / "missions/u/wiki/entities").mkdir(parents=True)
    (K.tmp / "missions/u/wiki/entities/cameco.md").write_text("---\ntitle: Cameco\n---\n## Key facts\n- 2025 output 30 Mlb")
    CD.M.split_front, CD.M.vault_commit, CD.M.reindex = MM.split_front, lambda paths, msg: commits.append(paths), lambda: None
    w = {"root": "missions/u/wiki", "title": "Uranium mining", "page": "entities/cameco", "page_title": "Cameco"}
    K.c.execute("update tasks set text='Check its facts', spec=? where id=?", (json.dumps({"wiki": w, "plan": [
        {"step": "check it", "agent": "scout", "why": "web", "after": []},
        {"step": "Write it into the wiki", "agent": "mission", "harness": "wiki", "why": "", "after": [1]}]}), K.tid))
    K.c.execute("delete from task_steps"); K.c.execute("delete from task_occ"); K.c.commit()
    CD.start(K.c, TK.row(K.c, K.tid))
    for _ in range(3):
        tick(K)
    assert "The page “Cameco” of the wiki “Uranium mining” as it stands now:" in prompts[0] and "2025 output 30 Mlb" in prompts[0]
    (root, src, touched, text), = calls
    assert root == "missions/u/wiki" and touched == ["entities/cameco", "entities/kazatomprom", "entities/orano"] and src == f"tasks/{K.tid}-wiki-findings-1.md"
    assert text.startswith("The owner asked for this change to the wiki (its page “Cameco”): Check its facts") and "31 Mlb" in (K.tmp / src).read_text()
    out = CD.steps(K.c, K.tid)[1]["output"]
    assert out.startswith("3 pages of the wiki “Uranium mining” written: entities/cameco, entities/kazatomprom, entities/orano") and commits[0] == ["missions/u/wiki", src]
    assert TK.row(K.c, K.tid)["status"] == "done"


def test_the_worker_starts_an_event_s_and_a_schedule_s_run_while_it_holds_its_lock_and_heals_a_half_start(K):
    """FND-84: the worker ticks under CD.lock and start() takes it again; with a plain Lock the first event-triggered
    run deadlocked the Conductor. A task claimed but never started (the runner stopped in between) waits again."""
    on_event(K, [{"step": "Say what it means", "agent": "scout", "why": "reads the web", "after": []}])
    CD.fire(K.c, K.tid, EV)
    done = __import__("threading").Event()
    def go():
        cc = K.conn()                                                     # the worker's own connection, as M.db() gives it
        with CD.lock:
            CD.tick(cc, start_thread=lambda f: f())
        cc.close()
        done.set()
    __import__("threading").Thread(target=go, daemon=True).start()
    assert done.wait(5), "the worker's tick deadlocked on its own lock"
    assert [o["trigger"] for o in CD.occurrences(K.c, K.tid)] == ["event"]
    K.c.execute("update tasks set status='running' where id=?", (K.tid,)); K.c.execute("update task_occ set status='done'"); K.c.commit()
    CD.recover(K.c)
    assert TK.row(K.c, K.tid)["status"] == "scheduled"


def test_a_delivered_briefing_grows_its_topic_wiki_and_a_deleted_one_stays_deleted(K, monkeypatch):
    """The Conductor's briefing path compiles the report into topics/<slug>/wiki on the desk's own key, as a briefing
    mission does; not when the owner deleted that wiki (wiki_off on the mission holding the topic)."""
    import mission_extras as X
    calls, commits = [], []
    monkeypatch.setattr(X, "compile_into", lambda root, title, rel, text, key: calls.append((root, rel, key)) or ["entities/byd"])
    monkeypatch.setenv("VK_DESK", "kd")
    CD.M.load_missions, CD.M.vault_commit = (lambda: {}), (lambda paths, msg: commits.append(paths))
    t = {"id": 5, "title": "China auto"}
    CD.topic_wiki(t, "china-auto", "topics/china-auto/reports/x.md", "text", {"key": "vk-desk"})
    assert calls == [("topics/china-auto/wiki", "topics/china-auto/reports/x.md", "kd")] and commits == [["topics/china-auto/wiki"]]
    CD.M.load_missions = lambda: {"c": {"slug": "c", "topic": "china-auto", "wiki_off": True}}
    CD.topic_wiki(t, "china-auto", "topics/china-auto/reports/y.md", "text", {"key": "vk-desk"})
    assert len(calls) == 1


OPENCODE_EVENTS = [{"type": "step_start", "part": {"type": "step-start"}},
                   {"type": "tool_use", "part": {"type": "tool", "tool": "read", "state": {"status": "completed", "input": {"filePath": "/work/calc.py"}, "output": "def add(a, b): ..."}}},
                   {"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 225, "output": 22, "reasoning": 0, "cache": {"write": 0, "read": 7680}}}},
                   {"type": "text", "part": {"type": "text", "text": "`add(a, b)` returns the sum of a and b."}},
                   {"type": "step_finish", "part": {"type": "step-finish", "tokens": {"input": 178, "output": 26, "reasoning": 0, "cache": {"read": 7808}}}}]


def test_a_step_on_opencode_reads_only_and_records_its_tool_and_model_calls(K, monkeypatch, tmp_path):
    """TSK-07: the OpenCode adapter runs one `opencode run` on the internal network with the card's model and key, the
    task's repository read-only and a config that denies shell, edits and web; the prompt goes in as a file; each tool
    call and model step goes into the step's record (recorded from a real run on 2026-11-01)."""
    import runtime as RTM
    staged, seen = [], {}
    monkeypatch.setattr(RTM, "stage", lambda title, detail="", ms=None, kind="stage", status=None, tokens=None: staged.append((kind, title, tokens)))
    monkeypatch.setattr(CD, "CODE", tmp_path)
    (tmp_path / "calc").mkdir()
    monkeypatch.setenv("VK_CODE", "sk-test")

    def run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw["env"]
        seen["task"] = (__import__("pathlib").Path(cmd[cmd.index("-v") + 1].split(":")[0]) / "task.md").read_text()
        seen["cfg"] = json.loads((__import__("pathlib").Path(cmd[cmd.index("-v") + 1].split(":")[0]) / "oc.json").read_text())
        return types.SimpleNamespace(returncode=0, stdout="\n".join(json.dumps(e) for e in OPENCODE_EVENTS), stderr="")
    t = {"id": 9, "spec": {"repo": "calc"}}
    out = CD.run_opencode(K.c, t, {"idx": 2, "occ": 1}, "What does add return?", {"key": "vk-code", "model": "gpt-sub"}, run=run)
    cmd = seen["cmd"]
    assert out == "`add(a, b)` returns the sum of a and b." and seen["task"] == "What does add return?"
    assert cmd[cmd.index("--network") + 1] == "aistack_backend" and f"{tmp_path / 'calc'}:/work:ro" in cmd and cmd[cmd.index("--model") + 1] == "litellm/gpt-sub"
    assert seen["env"]["LITELLM_API_KEY"] == "sk-test" and "sk-test" not in " ".join(cmd)                # the key by name, never on the command line
    assert seen["cfg"]["permission"] == {"bash": "deny", "edit": "deny", "webfetch": "deny"}
    assert staged == [("call", "read", None), ("result", "read", None), ("llm", "gpt-sub", {"in": 7905, "out": 22, "cached": 7680, "reasoning": 0}),
                      ("llm", "gpt-sub", {"in": 7986, "out": 26, "cached": 7808, "reasoning": 0})]
    with pytest.raises(RuntimeError, match="exit 1"):
        CD.run_opencode(K.c, {"id": 9, "spec": {}}, {"idx": 2}, "x", {"key": "vk-code"}, run=lambda cmd, **kw: types.SimpleNamespace(returncode=1, stdout="", stderr="no model"))
    assert CD.runs_steps({"harness": "opencode", "model": "gpt-sub", "key": "vk-code"}) and "opencode" in CD.HARNESSES


def test_a_trial_s_build_step_ends_at_review_and_is_scored_not_merged(K, monkeypatch):
    """Phase 10a: a trial's build is scored by its answer key at review; it never waits for the owner's tap, never merges."""
    import builds as B
    K.c.execute("create table builds (id integer primary key, status text, summary text, error text, branch text, head text)")
    K.c.execute("update tasks set kind='coding', source='trial:semver', spec=? where id=?", (json.dumps({"repo": "trial-semver-1", "plan": [
        {"step": "Build semverlib", "agent": "builder", "why": "changes code", "after": []}]}), K.tid))
    K.c.execute("delete from task_steps"); K.c.commit()
    monkeypatch.setattr(B, "handle", lambda req, c: {"id": c.execute("insert into builds (status) values ('working')").lastrowid})
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "build": CD.run_build})
    merged = []
    monkeypatch.setattr(B, "trial_merge", lambda c, b: merged.append(b["id"]) or "f00dfeed12")
    CD.start(K.c, TK.row(K.c, K.tid))
    tick(K)
    assert CD.steps(K.c, K.tid)[0]["status"] == "waiting"
    K.c.execute("update builds set status='review', branch='builder/1-semverlib', head='abc123', summary='semverlib with tests'"); K.c.commit()
    tick(K); tick(K)
    out = CD.steps(K.c, K.tid)[0]["output"]
    assert TK.row(K.c, K.tid)["status"] == "done" and merged == [1] and "merged into the trial repository's main as f00dfeed" in out
    assert "never deployed" in out and K.c.execute("select ref from step_refs where kind='build'").fetchone()["ref"] == "1"   # FND-91


def test_consecutive_builder_steps_become_one_build_with_stages():
    """TRL-10, the first trial's finding: read-and-plan, implement, test-and-fix as three builder steps were three builds,
    and the first, committing nothing, failed. A chain of builder steps is one build whose brief lists the stages."""
    agents = {"builder": {"harness": "claude-code"}, "scout": {"harness": "hermes"}, "mission": {"harness": "hermes"}}
    plan = [{"step": "Read the spec and plan", "agent": "builder", "after": []},
            {"step": "Implement it with tests", "agent": "builder", "after": [1]},
            {"step": "Run the tests and fix", "agent": "builder", "after": [2]},
            {"step": "Write the report", "agent": "mission", "after": [3]}]
    out = CD.graph(plan, agents)
    assert [(s["idx"], s["agent"], s["after"]) for s in out] == [(1, "builder", []), (2, "mission", [1])]
    assert out[0]["title"] == "Stage 1: Read the spec and plan; Stage 2: Implement it with tests; Stage 3: Run the tests and fix"
    fork = [{"step": "Look it up", "agent": "scout", "after": []}, {"step": "Build A", "agent": "builder", "after": [1]},
            {"step": "Build B", "agent": "builder", "after": [2]}, {"step": "Review A", "agent": "mission", "after": [2]}]
    assert [s["agent"] for s in CD.graph(fork, agents)] == ["scout", "builder", "builder", "mission"]   # A is needed alone: no fold
    with pytest.raises(ValueError, match="waits for step 5"):
        CD.graph(plan[:3] + [{"step": "x", "agent": "mission", "after": [5]}], agents)


def code_and_check(K, monkeypatch, outputs, loop_max=2):
    """A builder step and a judge that loops back to it; the sandbox's test runs answer from `outputs` in turn."""
    import builds as B
    K.c.execute("update tasks set kind='coding', spec=? where id=?", (json.dumps({"repo": "trial-x", "plan": [
        {"step": "Write it with tests", "agent": "builder", "why": "codes", "after": []},
        {"step": "Run every test", "agent": "judge", "why": "checks", "after": [1], "loop": {"to": 1, "max": loop_max}}]}), K.tid))
    K.c.execute("delete from task_steps"); K.c.execute("delete from task_occ"); K.c.commit()
    briefs, runs = [], iter(outputs)
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "build": lambda c, t, s, prompt, card: briefs.append(s["resume"].get("feedback")) or "built",
                                         "check": CD.run_check})
    monkeypatch.setattr(B, "clone", lambda repo, slot=None: "/w/" + repo)
    monkeypatch.setattr(B, "default_branch", lambda path: "main")
    monkeypatch.setattr(B, "git", lambda *a, **k: "")
    monkeypatch.setattr(B, "sandbox_checks", lambda repo, slot=None, timeout=900: next(runs))
    CD.start(K.c, TK.row(K.c, K.tid))
    return briefs


def test_a_check_sends_failures_back_to_the_builder_until_they_pass(K, monkeypatch):
    """TRL-08: code, test, fix: the judge runs every test; failures go back to the builder with what failed, and the
    judge runs again after the fix."""
    briefs = code_and_check(K, monkeypatch, ["FAILED tests/test_a.py::test_x\n1 failed, 9 passed", "10 passed\nALL CHECKS PASSED"])
    for _ in range(6):
        tick(K)
    ss = CD.steps(K.c, K.tid)
    assert TK.row(K.c, K.tid)["status"] == "done" and briefs[0] is None and "1 failed, 9 passed" in briefs[1]
    assert ss[1]["output"].startswith("All checks pass: 10 passed.") and ss[1]["resume"] == {"rounds": 1} and ss[1]["after"] == [1]


def test_a_check_out_of_fix_rounds_reports_what_still_fails_and_the_plan_goes_on(K, monkeypatch):
    briefs = code_and_check(K, monkeypatch, ["2 failed, 8 passed"] * 3, loop_max=1)
    for _ in range(6):
        tick(K)
    out = CD.steps(K.c, K.tid)[1]["output"]
    assert TK.row(K.c, K.tid)["status"] == "done" and len(briefs) == 2 and out.startswith("The checks still fail after 1 fix round: 2 failed, 8 passed.")


def test_only_a_check_loops_and_only_back_and_a_fold_keeps_the_loop_on_its_build():
    agents = CD.cards()
    with pytest.raises(ValueError, match="only a check loops"):
        CD.graph([{"step": "a", "agent": "builder", "after": []}, {"step": "b", "agent": "scout", "after": [1], "loop": {"to": 1, "max": 2}}], agents)
    with pytest.raises(ValueError, match="only a check loops"):
        CD.graph([{"step": "a", "agent": "judge", "after": [], "loop": {"to": 2, "max": 2}}, {"step": "b", "agent": "builder", "after": []}], agents)
    out = CD.graph([{"step": "plan", "agent": "builder", "after": []}, {"step": "code", "agent": "builder", "after": [1]},
                    {"step": "test", "agent": "judge", "after": [2], "loop": {"to": 2, "max": 9}}], agents)
    assert [(s["agent"], s["harness"], s["loop"]) for s in out] == [("builder", "build", None), ("judge", "check", {"to": 1, "max": CD.LOOP_MAX})]


def test_a_role_s_build_stays_in_its_lane(K, monkeypatch):
    """TRL-07: the tester's build may change tests/acceptance/ only; outside it the build is rejected and the step fails."""
    import builds as B
    K.c.execute("create table builds (id integer primary key, status text, summary text, error text, branch text, head text, files text)")
    K.c.execute("update tasks set kind='coding', spec=? where id=?", (json.dumps({"repo": "ai-stack", "plan": [
        {"step": "Acceptance tests", "agent": "tester", "why": "tests from requirements", "after": []}]}), K.tid))
    K.c.execute("delete from task_steps"); K.c.commit()
    asked, rejected = [], []

    def handle(req, c):
        if req["action"] == "build_reject":
            return rejected.append(req["id"]) or {}
        asked.append(req)
        return {"id": c.execute("insert into builds (status) values ('working')").lastrowid}
    monkeypatch.setattr(B, "handle", handle)
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "build": CD.run_build})
    CD.start(K.c, TK.row(K.c, K.tid))
    tick(K)
    assert "Change only files under: tests/acceptance/" in asked[0]["description"] and "standing instructions (tester's card)" in asked[0]["description"]
    assert "## Results of the steps before yours" not in asked[0]["description"] and asked[0]["context"].startswith("## Results")
    assert asked[0]["source"] == f"task:{K.tid}:step:1"                              # FND-101: its run nests in the step's
    K.c.execute("update builds set status='review', files=? where id=1", (json.dumps([["M", "tests/acceptance/test_r1.py"], ["M", "semverlib/__init__.py"]]),)); K.c.commit()
    tick(K)
    s = CD.steps(K.c, K.tid)[0]
    assert rejected == [1] and "outside its lane" in s["error"] and "semverlib/__init__.py" in s["error"] and s["status"] == "pending"


def test_a_build_inside_the_trace_counts_once_against_the_budget(K, monkeypatch):
    """FND-101: task 108 was stopped at 3.4 of 3 million tokens while it had used about 2.3: the builds whose runs sit in
    the step's trace were counted there and again from the builds table."""
    import staffing as ST
    K.c.execute("create table builds (id integer primary key, status text, tokens integer)")
    K.c.executemany("insert into builds (id, status, tokens) values (?, 'merged', ?)", [(1, 900), (2, 50)])
    CD.step_ref(K.c, "build", 1, K.tid); CD.step_ref(K.c, "build", 2, K.tid)
    monkeypatch.setattr(ST, "usage_of", lambda run, db=None, tree=True: {"claude": {"in": 1000, "out": 100, "cached": 800}})
    monkeypatch.setattr(ST, "runs_of", lambda run, db=None: {run, f"{run}:step:1", "build:1:0:queued"})   # build 2's run is not in it
    _, tokens = CD.spent(K.c, TK.row(K.c, K.tid), {"occ": 1})
    assert tokens == 1150


def test_a_spent_budget_stops_the_next_step(K, monkeypatch):
    """TRL-11: a step does not start once the task's hours or tokens are spent; the task fails saying so."""
    import staffing as ST
    K.c.execute("update tasks set spec=? where id=?", (json.dumps({"plan": PLAN, "preset": {"budget": {"tokens": 1000}}}), K.tid)); K.c.commit()
    monkeypatch.setattr(ST, "usage_of", lambda run, db=None, tree=True: {"gpt-sub": {"in": 900, "out": 200, "cached": 0}})
    tick(K)
    s = CD.steps(K.c, K.tid)[0]
    assert s["status"] == "failed" and s["error"] == "not started: its budget of 1,000 tokens is spent (1,100)"
    tick(K)
    assert TK.row(K.c, K.tid)["status"] == "failed"


def test_a_build_or_claude_task_a_step_started_is_not_a_task_of_its_own(K):
    """FND-91: the board's sync leaves out what a plan's step started."""
    K.c.execute("create table builds (id integer primary key, title text, description text, created text, status text)")
    now = TK.now()
    K.c.executemany("insert into builds (id, title, description, created) values (?,?,?,?)", [(5, "a step's build", "x", now), (6, "the owner's build", "y", now)])
    CD.step_ref(K.c, "build", 5, K.tid)
    K.c.execute("drop table claude_tasks")                 # the fixture's table is not the real one
    TK.discover(K.c, {})
    assert [r["ref"] for r in K.c.execute("select ref from tasks where door='build'")] == ["6"]


def test_a_step_that_says_it_is_blocked_fails_its_task_at_once_and_says_why(K, monkeypatch):
    """TSK-35 (task #104, 1 Nov 2026): a step whose agent had no phone answered "blocked", was counted done, and the owner
    was told the task was done. A step that begins BLOCKED: fails with its reason, is not tried again, and the message
    says why; a step that only mentions the word later is done."""
    def blocked(c, t, s, prompt, card):
        return "BLOCKED: this agent has no AI phone controls\n\nNothing was installed."
    monkeypatch.setattr(CD, "ADAPTERS", {**CD.ADAPTERS, "hermes": blocked})
    tick(K)
    s1 = CD.steps(K.c, K.tid)[0]
    assert s1["status"] == "failed" and s1["error"] == "blocked: this agent has no AI phone controls" and s1["attempts"] == CD.ATTEMPTS
    tick(K)
    t = TK.row(K.c, K.tid)
    assert t["status"] == "failed" and "blocked: this agent has no AI phone controls" in t["error"]
    assert "failed" in K.sent[-1] and "no AI phone controls" in K.sent[-1]
    assert not CD.BLOCKED.match("The vendor was BLOCKED: no reply") and CD.BLOCKED.match("  BLOCKED: x")
    assert CD.BLOCKED.match("Step 1 blocked: this session has no AI phone controls")[1].startswith("this session")   # #104's own words


def test_between_waves_the_orchestrator_keeps_or_changes_the_rest_of_the_plan(K, monkeypatch):
    """TRL-08: after a wave the Orchestrator reads what the finished steps found and may drop a step not yet started,
    rewrite one or add one; each look is kept on the task with its reason, a change also in the activity; it looks once
    per wave, at most CHECKPOINTS times, and the run then goes on with the changed plan."""
    looks = []

    def orchestrator(prompt):
        looks.append(str(prompt))
        if len(looks) == 1:
            return {"keep": False, "why": "step 1 already names the risk", "drop": [3, 4], "edit": [{"step": 2, "text": "List the three changes"}],
                    "add": [{"step": "Check the summary's facts", "agent": "scout", "after": [4]}, {"step": "x", "agent": "nobody"},
                            {"step": "Gather the sources first", "agent": "scout", "after": [1], "before": [2, 1, 9]}]}
        return {"keep": True, "why": "the plan fits"}
    monkeypatch.setattr(CD, "checkpoint_ask", orchestrator)
    tick(K)                                                    # wave 1: step 1
    K.c.execute("update task_steps set started=? where task=? and idx=4", (CD.now(), K.tid)); K.c.commit()   # step 4: in a fix round
    tick(K)                                                    # the checkpoint, no step starts meanwhile
    assert len(looks) == 1 and "result of step 1" in looks[0] and "Find the facts" in looks[0] and "4. [running again]" in looks[0]
    st = {s["idx"]: s for s in CD.steps(K.c, K.tid)}
    assert st[3]["status"] == "skipped" and st[2]["title"] == "List the three changes" and st[2]["status"] == "pending"
    assert st[4]["status"] == "pending"                       # a step in a fix round is not dropped (task 108's builder was)
    assert st[5]["agent"] == "scout" and st[5]["after"] == [4] and "added at the checkpoint" in st[5]["why"]
    assert st[6]["after"] == [1] and st[2]["after"] == [1, 6] and 7 not in st      # FND-100: it comes before step 2; a finished step or none is not held
    cp = TK.row(K.c, K.tid)["spec"]["checkpoints"]
    assert cp[0]["after"] == [1] and not cp[0]["kept"] and len(cp[0]["changes"]) == 4 and cp[0]["why"] == "step 1 already names the risk"
    assert cp[0]["changes"][-1].endswith("(scout), before step 2")
    assert any("changed the plan after step 1" in e[2] for e in K.events)
    for _ in range(14):
        tick(K)
    assert TK.row(K.c, K.tid)["status"] == "done" and status(K) == {1: "done", 2: "done", 3: "skipped", 4: "done", 5: "done", 6: "done"}
    cp = TK.row(K.c, K.tid)["spec"]["checkpoints"]
    assert 2 <= len(cp) <= CD.CHECKPOINTS and all(x["kept"] for x in cp[1:])
    assert len({tuple(x["after"]) for x in cp}) == len(cp)    # once per wave


def test_the_checkpoint_reads_a_long_result_s_start_and_knows_it_is_cut():
    """FND-100: a silent cut at 4,000 characters made the Orchestrator think the analyst's list was broken off, and it
    added a step to finish it; the start it reads now says how much is missing and that the next steps get it whole."""
    seen = []
    t = {"id": 1, "goal": "Build it", "done": ["every rule"], "spec": {}}
    ss = [{"idx": 1, "occ": 1, "title": "Requirements", "agent": "analyst", "after": [], "status": "done", "output": "R-1 a rule. " * 1000},
          {"idx": 2, "occ": 1, "title": "Build", "agent": "builder", "after": [1], "status": "pending", "output": None}]
    with pytest.raises(RuntimeError):                    # its answer is not used here: only what it was shown
        CD.checkpoint(None, t, ss, ask=lambda p: seen.append(str(p)) or (_ for _ in ()).throw(RuntimeError("stop")))
    assert f"[… {12000 - CD.SEEN:,} more characters cut: shown here only; the steps after it get the whole result]" in seen[0]


def test_a_recurring_or_fixed_plan_gets_no_checkpoint():
    ss = [{"idx": 1, "status": "done", "harness": "hermes", "occ": 1}, {"idx": 2, "status": "pending", "harness": "hermes", "occ": 1}]
    once = {"rhythm": {"type": "once"}, "door": "plan", "spec": {}}
    CD.checkpoint_ask = lambda p: {"keep": True}
    try:
        assert CD.between_waves(once, ss)
        assert not CD.between_waves({**once, "rhythm": {"type": "schedule"}}, ss)                 # a template runs as planned
        assert not CD.between_waves(once, [{**s, "harness": "desk-write"} for s in ss])          # a briefing's own steps
        assert not CD.between_waves(once, [ss[0], {**ss[1], "status": "running"}])               # a wave still running
        assert not CD.between_waves({**once, "spec": {"checkpoints": [{"occ": 1, "after": [1]}]}}, ss)   # this wave was seen
    finally:
        CD.checkpoint_ask = None

