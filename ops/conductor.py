"""The Conductor (TSK-05 to TSK-09; phase 2 of docs/SWARM-ROADMAP.md): it runs a task's plan graph. Each step is one
agent's work on that agent's own harness and model; a step starts when every step it waits for has finished, steps
that wait for nothing run at the same time (at most SLOTS), and every step is recorded before and after it runs, so a
restart of the runner resumes the task at its first unfinished step and never runs a finished one again.

A task reaches the Conductor from the intake (ops/tasks.py) when it is a one-off research, analysis or errand task
whose plan uses two or more agents; everything else still goes to its door (a mission, a build, a Claude task).

Harness adapters, one contract (run the step's prompt as its agent, give back its answer or say it is waiting):
  hermes       one turn of the agent's Hermes profile (hermes -z), under the step's run in the runtime record
  claude-code  a read-only Claude task; the step waits for it, also across restarts (its id is the resume point)
  python       one model call on the agent's own key
A step starts only with headroom (TSK-08): the memory its harness needs available on the PC (NEED_GB) and its
subscription below its usage limit; otherwise it waits and the board says why.

The trace (TSK-09): the task is one run in the runtime record (task:<id>), each step a run inside it
(task:<id>:step:<n>), and the agent's own runs (Hermes', the model calls) inside the step: #/live/task:<id>.

  python3 ops/conductor.py gate     the phase 2 gate: a five-step task on three harnesses, the runner restarted
                                    during it; it must finish with no finished step run twice and one trace
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SLOTS = 2                                         # steps at once: RAM (16 GB) and the subscriptions decide, as for builds (DEC-24)
ATTEMPTS = 2                                      # a step that fails twice fails its task (a limit or a restart is no attempt)
# TSK-08: what a step needs available on the PC (Windows' available memory: free plus the cache it hands back). A model
# call starts nothing; a Hermes turn starts one process in the running Hermes container; Claude Code starts its own
# process. The owner keeps playing on this PC (31 Oct 2026): steps ask for what they use, not for a fixed margin.
NEED_GB = {"python": 0.25, "temp": 0.25, "hermes": 0.5, "claude-code": 0.75}
NEW = "new"                                       # TSK-15: the intake's word for "no agent fits": a temporary agent is written
STEP_TIMEOUT = 40 * 60
HARNESSES = ("hermes", "claude-code", "python")   # the harnesses a step can run on (TSK-07); OpenCode has no adapter yet (SWM-28)
HOST = Path("/srv/win-exports/.host/host.json")   # Windows' free memory, written every 30 s by ops/windows/host-probe.ps1
RESULTS = Path("/srv/vault/tasks")                # the finished task's answer, for the vault's search
M = None                                          # ops/missions.py, set by its main()
slots = threading.BoundedSemaphore(SLOTS)
lock = threading.Lock()


class Waiting(Exception):
    """The step's agent is working elsewhere (a Claude task): keep the step waiting, check again later."""


def table(c):
    c.execute("""create table if not exists task_steps (id integer primary key, task integer, idx integer, title text,
                 agent text, harness text, model text, after text, why text, status text, output text, error text,
                 waiting_for text, resume text, attempts integer default 0, started text, ended text)""")
    c.execute("create index if not exists task_steps_task on task_steps (task, idx)")


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def put(c, sid, **kw):
    if "resume" in kw and not isinstance(kw["resume"], str) and kw["resume"] is not None:
        kw["resume"] = json.dumps(kw["resume"])
    c.execute(f"update task_steps set {', '.join(f'{k}=?' for k in kw)} where id=?", (*kw.values(), sid))
    c.commit()


def steps(c, task):
    return [dict(r) | {"after": json.loads(r["after"] or "[]"), "resume": json.loads(r["resume"] or "{}")}
            for r in c.execute("select * from task_steps where task=? order by idx", (task,)).fetchall()]


def cards():
    reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())
    return {a["id"]: a for a in reg["agents"]}


def runs_steps(card):
    """Can this agent do a step? Its harness has an adapter, and a python agent has its own key."""
    return card.get("harness") in HARNESSES and (card["harness"] != "python" or card.get("key") not in (None, "none"))


# ---------- the plan graph (TSK-05) ----------
def graph(plan, agents=None):
    """The intake's plan -> steps with their dependencies (1-based step numbers in "after"), or ValueError: a step
    that waits for a step that is not there, or a plan with a cycle, is refused."""
    agents = agents or cards()
    out, n = [], len(plan)
    for i, p in enumerate(plan, 1):
        after = sorted({int(a) for a in p.get("after") or [] if str(a).isdigit()})
        bad = [a for a in after if not 1 <= a <= n or a == i]
        if bad:
            raise ValueError(f"step {i} waits for step {bad[0]}, which is not another step of the plan")
        a = p.get("agent")
        card = agents.get(a)
        if a == NEW:                                   # a temporary agent, written when the step starts (ops/staffing.py)
            card = {"harness": "temp", "model": "gpt-sub"}
        elif not card or not runs_steps(card):
            raise ValueError(f"step {i}: {a!r} is no agent that can do a step (one on {', '.join(HARNESSES)})")
        out.append({"idx": i, "title": str(p.get("step", "")).strip() or f"Step {i}", "agent": a, "harness": card["harness"],
                    "model": card.get("model"), "after": after, "why": str(p.get("why", "")).strip()})
    seen, done = set(), set()                          # a cycle: a step that waits, through others, for itself

    def visit(i, path):
        if i in path:
            raise ValueError(f"the plan has a cycle: step {' → step '.join(map(str, path[path.index(i):] + [i]))}")
        if i in done:
            return
        for a in out[i - 1]["after"]:
            visit(a, path + [i])
        done.add(i)
    for s in out:
        visit(s["idx"], [])
    return out


def start(c, t):
    """Write the task's plan graph as its steps and open its run (the task's trace); the worker does the rest."""
    import runtime as RTM
    table(c)
    plan = graph(t["spec"].get("plan") or [])
    for s, p in zip(plan, t["spec"].get("plan") or []):
        if s["agent"] == NEW:
            s["why"] = p.get("why") or s["why"]
    with lock:
        c.execute("delete from task_steps where task=? and status='pending'", (t["id"],))
        for s in plan:
            c.execute("insert into task_steps (task, idx, title, agent, harness, model, after, why, status, attempts) values (?,?,?,?,?,?,?,?,?,0)",
                      (t["id"], s["idx"], s["title"], s["agent"], s["harness"], s["model"], json.dumps(s["after"]), s["why"], "pending"))
        c.commit()
    RTM.start(f"task:{t['id']}", "conductor", f"Task #{t['id']}: {t['title']}", detail=t["goal"],
              ref=f"task-intake:{t['id']}-{len(t.get('answers') or [])}")
    return str(t["id"])


# ---------- headroom (TSK-08) ----------
def free_gb(host=None, meminfo=None, now=None):
    """The PC's available memory: Windows' own number when the host probe is fresh (available, else free from an older
    probe), else what WSL has available."""
    try:
        h = HOST if host is None else host
        if (now or time.time()) - h.stat().st_mtime < 180:
            d = json.loads(h.read_text(encoding="utf-8-sig"))
            return float(d.get("ram_available_gb", d["ram_free_gb"]))
    except (OSError, ValueError, KeyError):
        pass
    mi = {ln.split(":")[0]: int(ln.split()[1]) for ln in (meminfo if meminfo is not None else open("/proc/meminfo").read()).splitlines()
          if ln.split(":")[0] == "MemAvailable"}
    return mi.get("MemAvailable", 0) / 1048576


def headroom(step, free=None, limited=None):
    """None when the step may start, else what it waits for (shown on the board)."""
    import swarm_client as SW
    gb, need = free_gb() if free is None else free, NEED_GB.get(step.get("harness"), 0.5)
    if gb < need:
        return f"memory: {gb:.2f} GB available on the PC, it starts at {need} GB"
    engine = SW.ENGINE.get(step["model"] or "", "")
    if engine and (limited or SW.limited)(engine):
        return f"the {'Claude' if engine == 'claude' else 'ChatGPT'} subscription's usage limit"
    return None


# ---------- the harness adapters (TSK-07) ----------
def prompt_of(t, s, all_steps, agents, purpose=None):
    import prompts as P
    prev = [x for x in all_steps if x["idx"] in s["after"]]
    return P.text("shared", "TASK_STEP").format(
        agent=s["agent"], purpose=purpose or (agents.get(s["agent"]) or {}).get("purpose", "a temporary agent written for this step"), goal=t["goal"], n=len(all_steps), i=s["idx"], step=s["title"],
        done="\n".join(f"- {d}" for d in t["done"]),
        before="\n\n".join(f"### Step {x['idx']}: {x['title']} ({x['agent']})\n{x['output']}" for x in prev) or "(this step waits for none)",
        last="yes" if not any(s["idx"] in x["after"] for x in all_steps) else "no")


def run_hermes(c, t, s, prompt, card):
    import runtime as RTM
    import swarm_client as SW
    prof = SW.PROFILE.get(s["agent"])
    p = subprocess.run(["docker", "exec", "-u", "hermes", *RTM.env_args(), M.HERMES, "timeout", str(STEP_TIMEOUT), "hermes",
                        *(["-p", prof] if prof else []), "-z", prompt], capture_output=True, text=True, timeout=STEP_TIMEOUT + 60)
    out = p.stdout.strip()
    if p.returncode or not out:
        raise RuntimeError(f"Hermes ({prof or 'main'}) ended with exit {p.returncode}: {(p.stderr or out).strip()[-600:]}")  # cap: preview
    return out


def run_claude(c, t, s, prompt, card):
    """A read-only Claude task; its id is the step's resume point, so a restart waits for it instead of asking again."""
    import claude_tasks as CT
    tid = s["resume"].get("claude_task")
    if not tid:
        head, _, context = prompt.partition("\n\n## Results of the steps before yours\n")
        tid = CT.handle({"action": "claude_task", "question": head[:19000], "mode": "ask", "repo": "",  # cap: api (its question limit)
                         "context": ("## Results of the steps before yours\n" + context) if context else ""}, c)["id"]
        put(c, s["id"], resume={"claude_task": tid})
        M.event("task", "", f"Task #{t['id']} step {s['idx']} asked Claude (task #{tid})", title="Tasks")
    r = c.execute("select status, answer, error from claude_tasks where id=?", (tid,)).fetchone()
    if not r or r["status"] in ("queued", "running", "waiting"):
        raise Waiting(f"Claude task #{tid}")
    if r["status"] != "done":
        put(c, s["id"], resume={})                        # a failed Claude task is asked again on the next attempt
        raise RuntimeError(f"Claude task #{tid} {r['status']}: {r['error'] or ''}")
    return r["answer"]


def run_python(c, t, s, prompt, card):
    key = "VK_" + card["key"][3:].upper().replace("-", "_")
    return M.ask_text(prompt, os.environ[key], card.get("model") or "gpt-sub", timeout=STEP_TIMEOUT)


def run_temp(c, t, s, prompt, card):
    """TSK-15: a temporary agent written for this step (its design kept in the archive), on its own key."""
    import staffing as ST
    name = s["resume"].get("design")
    d = c.execute("select * from agent_designs where name=?", (name,)).fetchone() if name else None
    if not d:
        d = ST.design_for(c, s, t["goal"])
        put(c, s["id"], resume={"design": d["name"]}, agent=d["name"], why=f"{s['why']} (a temporary agent: {d['purpose']})")
        M.event("task", "", f"Task #{t['id']} step {s['idx']}: temporary agent “{d['name']}” written", title="Tasks")
    d = dict(d)
    return ST.run_temp(c, t, {**s, "agent": d["name"]}, prompt_of(t, {**s, "agent": d["name"]}, steps(c, t["id"]), {}, d["purpose"]), d)


ADAPTERS = {"hermes": run_hermes, "claude-code": run_claude, "python": run_python, "temp": run_temp}


def run_step(c, t, s, all_steps, agents):
    """One step through its adapter, under its own run in the task's trace. Recorded before (running) and after."""
    import runtime as RTM
    run = f"task:{t['id']}:step:{s['idx']}"
    first = s["status"] != "waiting"
    if first:
        put(c, s["id"], status="running", started=now(), waiting_for=None, attempts=(s["attempts"] or 0) + 1)
        RTM.start(run, s["agent"], f"Step {s['idx']}: {s['title']}", detail=s["why"], ref=f"task:{t['id']}")
    RTM.set_ref(run, s["agent"])
    t0 = time.time()
    try:
        out = ADAPTERS[s["harness"]](c, t, s, prompt_of(t, s, all_steps, agents), agents.get(s["agent"]) or {})   # a temporary agent has no card
    except Waiting as w:
        put(c, s["id"], status="waiting", waiting_for=str(w), error=None)
        return
    except Exception as e:                                # the step's failure is recorded on it; a limit is waited out
        msg = f"{type(e).__name__}: {e}"
        if M.stop.is_set():                               # the runner stops (a deploy): interrupted, not failed; it stays
            RTM.end(run, s["agent"], "stopped", "the runner stopped", time.time() - t0)   # running, and recover() runs it again
            return
        if M.paused(msg):                                 # a usage limit is no attempt: the count goes back
            put(c, s["id"], status="pending", waiting_for="the subscription's usage limit", attempts=s["attempts"] or 0)
            RTM.end(run, s["agent"], "limit", msg, time.time() - t0)
        else:
            put(c, s["id"], status="pending" if (s["attempts"] or 0) + (1 if first else 0) < ATTEMPTS else "failed", error=msg, waiting_for=None)
            RTM.end(run, s["agent"], "failed", msg, time.time() - t0)
        return
    finally:
        RTM.set_ref(None)
    put(c, s["id"], status="done", output=out, ended=now(), waiting_for=None, error=None)
    RTM.end(run, s["agent"], "done", out[:2000], time.time() - t0)  # cap: preview (the step keeps all of it)


def cancel(c, t):
    """The owner stops a plan task: its steps that have not started never will; a step already running ends on its own,
    and its answer is not used."""
    import runtime as RTM
    import tasks as TK
    table(c)
    c.execute("update task_steps set status='cancelled', waiting_for=null where task=? and status in ('pending', 'waiting')", (t["id"],))
    c.commit()
    TK.put(c, t["id"], status="cancelled")
    RTM.end(f"task:{t['id']}", "conductor", "stopped", "cancelled by the owner", None)


# ---------- the worker ----------
def recover(c):
    """After a restart: a step that was running when the runner stopped runs again; a step waiting for a Claude task
    keeps waiting for it. Finished steps are never touched."""
    table(c)
    for r in c.execute("select id, resume, attempts from task_steps where status='running'").fetchall():
        if json.loads(r["resume"] or "{}"):
            put(c, r["id"], status="waiting", waiting_for=None)
        else:                                             # a restart is no attempt: the count goes back
            put(c, r["id"], status="pending", waiting_for="the runner restarted", attempts=max(0, (r["attempts"] or 1) - 1))


def ready(c, task):
    """The steps that may start now: pending, every step they wait for done; and waiting steps, to look again."""
    ss = steps(c, task)
    state = {s["idx"]: s["status"] for s in ss}
    return ss, [s for s in ss if (s["status"] == "pending" and all(state.get(a) == "done" for a in s["after"])) or s["status"] == "waiting"]


def finish(c, t, ss, ok):
    import runtime as RTM
    import notify as N
    import tasks as TK
    import events as EV
    import staffing as ST
    try:
        ST.end_keys(t["id"])                             # TSK-15: its temporary agents end with it
    except Exception as e:                               # the key sweep at the next start deletes them; logged
        M.log(f"conductor: task {t['id']}: temporary keys not deleted now: {type(e).__name__}: {e}")
    leaves = [s for s in ss if not any(s["idx"] in x["after"] for x in ss)]
    result = "\n\n".join(s["output"] or "" for s in leaves) if ok else ""
    if ok:
        RESULTS.mkdir(parents=True, exist_ok=True)
        f = RESULTS / f"{t['id']}-{re.sub(r'[^a-z0-9]+', '-', t['title'].lower()).strip('-')[:50]}.md"  # cap: id
        f.write_text(f"---\ntask: {t['id']}\ndate: {dt.date.today()}\n---\n# {t['title']}\n\n{result}\n")
        M.vault_commit([str(f.relative_to(M.VAULT))], f"task {t['id']}: {t['title']}")
        TK.put(c, t["id"], status="done", spec={**t["spec"], "result": str(f.relative_to(M.VAULT))})
    else:
        bad = next(s for s in ss if s["status"] == "failed")
        result = f"step {bad['idx']} ({bad['agent']}) failed: {bad['error']}"
        TK.put(c, t["id"], status="failed", error=result)
    RTM.end(f"task:{t['id']}", "conductor", "done" if ok else "failed", result[:2000], None)  # cap: preview (the vault file keeps all of it)
    EV.task_done(c, t, "done" if ok else "failed")      # TSK-10: a finished task is an event
    N.send(f"Task #{t['id']} {'is done' if ok else 'failed'}: {t['title']}", "result", title="Tasks", push_on=True, event_kind="task",
           buttons=[[("🔍 Open the task", f"{M.X.APP}/#/tasks?t={t['id']}")]])


def routed(c, t, s, agents):
    """TSK-14: the step goes to the agent that did this kind of task best, or away from a subscription at its limit."""
    import staffing as ST
    import swarm_client as SW
    a, why = ST.route(s, t["kind"], agents, ST.abilities(c), lambda e: SW.limited(e))
    if a == s["agent"]:
        return s
    card = agents[a]
    note = f"{s['why']} (routed: {why})"
    put(c, s["id"], agent=a, harness=card["harness"], model=card.get("model"), why=note)
    return {**s, "agent": a, "harness": card["harness"], "model": card.get("model"), "why": note}


def tick(c, start_thread=None):
    """One pass over the running plan tasks: finished ones close, ready steps start (with headroom, within SLOTS)."""
    import tasks as TK
    agents = cards()
    for r in c.execute("select id from tasks where door='plan' and status='running'").fetchall():
        t = TK.row(c, r["id"])
        ss, go = ready(c, t["id"])
        if ss and all(s["status"] == "done" for s in ss):
            finish(c, t, ss, True)
            continue
        if any(s["status"] == "failed" for s in ss):
            finish(c, t, ss, False)
            continue
        for s in go:
            if s["status"] == "pending" and not s["attempts"] and "(routed:" not in (s["why"] or ""):
                s = routed(c, t, s, agents)                   # TSK-14: before its first attempt
            if s["status"] == "pending":
                why = headroom(s)
                if why:
                    if s["waiting_for"] != why:
                        put(c, s["id"], waiting_for=why)
                    continue
            if s["status"] == "waiting" and s["harness"] != "claude-code":
                continue
            if not slots.acquire(blocking=False):
                return
            def job(t=t, s=s, ss=ss):
                cc = M.db()
                try:
                    run_step(cc, t, s, ss, agents)
                except Exception as e:                    # an adapter bug fails the step, not the worker; it is logged
                    M.log(f"conductor: task {t['id']} step {s['idx']}: {type(e).__name__}: {e}")
                    put(cc, s["id"], status="failed", error=f"{type(e).__name__}: {e}")
                finally:
                    slots.release()
                    cc.close()
            if s["status"] == "pending":
                put(c, s["id"], status="running")         # claimed before the thread starts: never started twice
                s = {**s, "status": "starting"}
            (start_thread or (lambda f: threading.Thread(target=f, daemon=True, name=f"task-{t['id']}-{s['idx']}").start()))(job)


def worker():
    c = M.db()
    table(c)
    recover(c)
    while not M.stop.is_set():
        try:
            with lock:
                tick(c)
        except Exception as e:                            # the next pass tries again; it is logged
            M.log(f"conductor: {type(e).__name__}: {e}")
        M.stop.wait(5)


def state(c, task_ids):
    table(c)
    return {tid: [{k: s[k] for k in ("idx", "title", "agent", "harness", "after", "why", "status", "waiting_for", "error", "attempts", "started", "ended")}
                  | {"output": s["output"] or ""} for s in steps(c, tid)] for tid in task_ids}


# ---------- the phase 2 gate ----------
GATE = [{"step": "Find the newest stable Python release, its release date and the URL of its release notes.", "agent": "scout",
         "why": "the only agent that reads the web", "after": []},
        {"step": "From step 1's release notes, list the three changes most relevant to someone running small Python services.",
         "agent": "mission", "why": "works through material on the mission profile", "after": [1]},
        {"step": "From step 1's facts, name one risk of upgrading a Python 3.12 codebase to that release, in two sentences.",
         "agent": "planner", "why": "Claude Code reasons about code changes", "after": [1]},
        {"step": "Write a five-line summary from steps 2 and 3 for the owner.", "agent": "desk", "why": "writes short briefings", "after": [2, 3]},
        {"step": "Check the summary against the definition of done and give the final text.", "agent": "mission",
         "why": "checks the result before it goes to the owner", "after": [4]}]


def gate():
    """Run the gate task, restart the runner while step 3 or 4 runs, wait for the end, and check it."""
    sys.path.insert(0, str(ROOT / "ops"))
    import missions as MM
    import tasks as TK
    globals()["M"] = MM
    c = MM.db()
    TK.table(c)
    table(c)
    t0 = TK.now()
    cur = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, source, created, updated) "
                    "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("Phase 2 gate: the newest Python release in five steps", "Phase 2 gate: Python release check",
                     "Find the newest stable Python release and summarise what matters for small services.", "research", "plan", None,
                     json.dumps(["names the release, its date and the release notes URL", "lists three relevant changes", "a summary of at most five lines"]),
                     "light", "auto", json.dumps({"type": "once"}), json.dumps({"plan": GATE}), "[]", "[]", "running", "gate", t0, t0))
    c.commit()
    tid = cur.lastrowid
    TK.put(c, tid, ref=str(tid))
    start(c, TK.row(c, tid))
    print(f"gate task #{tid} started; waiting for step 3 or 4 to run", flush=True)
    restarted, deadline = None, time.time() + 3 * 3600
    while time.time() < deadline:
        ss = steps(c, tid)
        st = {s["idx"]: s["status"] for s in ss}
        if not restarted and any(st.get(i) in ("running", "waiting") for i in (3, 4)):
            done_before = {s["idx"]: s["attempts"] for s in ss if s["status"] == "done"}
            subprocess.run(["systemctl", "--user", "restart", "missions.service"], check=True)
            restarted = {"at": now(), "while": {i: st[i] for i in (3, 4)}, "done_before": done_before}
            print(f"runner restarted while steps 3/4 were {restarted['while']}", flush=True)
        status = TK.row(c, tid)["status"]
        if status in ("done", "failed"):
            break
        time.sleep(10)
    ss = steps(c, tid)
    runs = dict(__import__("sqlite3").connect("/srv/ai/missions/app/runtime.db").execute(      # run -> the run it is inside
        "select run, ref from runs where run like ?", (f"task:{tid}%",)).fetchall())
    checks = {"finished": TK.row(c, tid)["status"] == "done", "restarted during step 3 or 4": bool(restarted),
              "no finished step ran twice": bool(restarted) and all(s["attempts"] == restarted["done_before"][s["idx"]] for s in ss if s["idx"] in restarted["done_before"]),
              "three harnesses": len({s["harness"] for s in ss}) >= 3,
              "one trace: the task's run holds its five steps": f"task:{tid}" in runs and all(runs.get(f"task:{tid}:step:{i}") == f"task:{tid}" for i in range(1, 6))}
    out = ROOT / "eval/results" / f"{time.strftime('%Y%m%d-%H%M%S')}-conductor-gate.json"
    out.write_text(json.dumps({"task": tid, "restarted": restarted, "checks": checks,
                               "steps": [{k: s[k] for k in ("idx", "agent", "harness", "status", "attempts", "started", "ended", "error")} for s in ss]},
                              indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"{out.relative_to(ROOT)}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["gate"]:
        sys.exit(gate())
    sys.exit(__doc__)
