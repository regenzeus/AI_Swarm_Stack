"""The Conductor (TSK-05 to TSK-09): a plan graph whose steps wait for the steps they need and run at the same time
otherwise, a cycle refused; every step recorded so a restart resumes at the first unfinished step and runs no finished
one again (a Claude step keeps waiting for its Claude task); headroom before a step starts; each step its own run in
the task's trace; a step that fails twice fails its task with the reason; the owner can cancel."""
import json
import sqlite3
import time
import types

import pytest

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


def test_the_owner_can_cancel_and_only_multi_agent_one_off_work_goes_to_the_conductor(K):
    tick(K)
    TK.handle({"action": "task_cancel", "id": K.tid}, K.c)
    assert TK.row(K.c, K.tid)["status"] == "cancelled" and set(status(K).values()) == {"done", "cancelled"}
    tick(K)
    assert K.ran == [1]
    base = {"kind": "research", "rhythm": {"type": "once"}, "spec": {"plan": PLAN}}
    assert TK.conducted(base)
    assert not TK.conducted({**base, "spec": {"plan": [PLAN[0], {**PLAN[1], "agent": "scout"}]}})       # one agent: its door
    assert not TK.conducted({**base, "kind": "coding"}) and not TK.conducted({**base, "rhythm": {"type": "schedule", "schedule": "daily 07:00"}})


def test_each_step_s_prompt_carries_the_results_it_waits_for():
    t = {"goal": "Find the facts", "done": ["three facts"]}
    ss = [{"idx": 1, "title": "Find", "agent": "scout", "after": [], "output": "fact A"},
          {"idx": 2, "title": "Sum up", "agent": "desk", "after": [1], "output": None}]
    p = CD.prompt_of(t, ss[1], ss, CD.cards())
    assert "Your step (2 of 2): Sum up" in p and "### Step 1: Find (scout)\nfact A" in p and "last step: yes" in p
    assert p.ref.startswith("shared/TASK_STEP@")
