"""WFL-05: the step service's runner side. n8n decides when work starts and in what order; the stack does the work.

An n8n workflow posts a step to Mission Control's step service (port 8099, reachable from n8n's network only), which
drops it here as /srv/ai/missions/flows/pending/<id>.json and answers at once. This worker runs it the way the
Conductor runs a plan's step, through CD.run_step on a row of its own: the same adapters, routing, headroom, slots, two
attempts, budget, trace and record (TSK-23). A crew job runs as its own unit, as "Run now" starts it. When the step has
settled, the result goes to done/<id>.json and to the waiting n8n execution's resume URL. A request stays pending until
n8n has its answer, so after a restart of the runner the step is looked at again (a finished row answers at once) and
the answer is delivered then.

A task on a schedule (a briefing, a price watch, a mission's task) runs from its own n8n workflow, the one scheduler
(WFL-09): one run per request, a plan task's as one occurrence of its plan (CD.start), a mission's as one run of the
mission, answered when that run has finished. A task that is not waiting for a run (running, cancelled) is not started.
The runner makes a task's workflow when the task gets its schedule and switches it off when the task is over
(ops/n8n_jobs.py reconcile, every minute in this worker).

A question for the owner (WFL-07) waits in Needs you (ops/decisions.py, source _flows) with the answers the workflow
offers; the owner's tap there (the action flow_answer) is the step's answer, and the workflow goes on.

The other blocks of the palette (WFL-06), each through the stack's own code:
    build     a coding change: the Conductor's build step (run_build, a builder assignment in the sandbox), waited for
              through its checks and the owner's review; the answer names the build, its state, branch, pull request
              and checks
    recall    a search of the stack's memory (the memory tool's search, MEM-28); the answer is its hits
    remember  a note through the memory tool's write gate (MEM-28, MEM-35): it enters memory only after its check
    command   a job kind at a place (ops/domain/places.py: wsl, wsl-host, windows), only when the owner approved that
              kind there by its fingerprint (Needs you); submitted once per request, waited for
    plan      an improvised plan: its steps are rows of one task, run in waves through the same path as an agent step;
              a step waits for the steps it names in "after", and the answer carries every step's output

Request: {"kind": one of KINDS, "agent": <card id>, "brief": <text>, "title": <text>, "job": <crew id>,
          "task": <plan task id>, "question": <text>, "why": <text>, "answers": [<label>, ...], "message": <text>,
          "repo": <repository>, "query": <words>, "scope": <collection>, "note": lesson|fact|failure|skill,
          "text": <note>, "evidence": <where it comes from>, "place": wsl|wsl-host|windows, "command": <job kind>,
          "values": {<parameter>: <value>}, "steps": [{"agent", "brief", "title", "after": [<step number>, ...]}, ...],
          "workflow": <n8n workflow id>, "execution": <n8n execution id>, "resume_url": <$execution.resumeUrl>}

    python3 ops/flows.py             what is pending, running and done
"""
import json
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import textcap as TC
from textcap import tail

ROOT = Path("/srv/ai/missions/flows")
PENDING, DONE = ROOT / "pending", ROOT / "done"
N8N = "http://127.0.0.1:5678"                        # n8n's port on this machine (compose/core.yaml); the runner is on the host
RESUME_PATH = re.compile(r"^/webhook-waiting/[A-Za-z0-9_-]{1,64}(/[A-Za-z0-9_-]{1,64})?$")
RESUME_QUERY = re.compile(r"^(signature=[0-9a-f]{16,128})?$")   # n8n 2.x signs its resume URLs; nothing else may ride along
KINDS = ("agent", "crew", "task", "ask", "notify", "build", "recall", "remember", "command", "plan")
NOTE_MAX = 2000                                      # limit: refuses, a message from a workflow is a note, not a report
ASKS = ROOT / "asks"
JOBS = ROOT / "jobs"                                 # a command's job at its place, per request: submitted once, also after a restart
ANSWERS_MAX = 4                                      # limit: refuses, a question offers at most four answers (Needs you shows them as buttons)
BRIEF_MAX = 20000                                    # limit: refuses, a step's brief is instructions, not a document
QUERY_MAX = 500                                      # limit: refuses, a memory search is words, as the memory tool's search takes them
MEMO_MAX = 2000                                      # limit: refuses, a note to memory is kept whole or not at all (the gate reads it whole, as the memory tool's note)
EVIDENCE_MAX = 500                                   # limit: refuses, the evidence names where a note comes from, as the memory tool's
NOTES = ("lesson", "fact", "failure", "skill")       # what a workflow may write to memory; the owner's facts are the owner's to give
COMMAND = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")   # a job kind's name, as a pack names it (<pack>.<kind>)
HIT_CHARS = 400                                      # of one memory hit in the answer; memory open gives the entry whole
WAIT_AGAIN_S = 30                                    # limit: paces, a step that waits (its work elsewhere, no headroom) is looked at again after 30 s
POLL_S = 2                                           # limit: paces, a command's job is looked at every 2 s, as places.run_job does
DELIVER_EVERY_S = 60                                 # limit: paces, an undelivered answer is sent again every minute
DELIVER_FOR_S = 86400                                # limit: stops, after a day without n8n taking it the answer stays in done/ and the owner is told
SCAN_S = 2
SETTLED = ("done", "skipped", "failed", "cancelled")

M = None                                             # ops/missions.py, set by start()
_busy = set()
_lock = threading.Lock()


def _brief(req):
    brief = req.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        return "the step needs a brief"
    if len(brief) > BRIEF_MAX:                       # limit: refuses, BRIEF_MAX above
        return f"the brief is {len(brief):,} characters; the limit is {BRIEF_MAX:,}"
    return ""


def validate(req, cards, crew, repos=None):
    """-> the problem with a request in words, or "" (SEC-11: the runner checks every request it acts on). repos: the
    repositories the builder may change (asked of ops/builds.py when None)."""
    if not isinstance(req, dict):
        return "the request is not an object"
    kind = req.get("kind")
    if kind not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}"
    if kind == "agent":
        if req.get("agent") not in cards:
            return f"no agent {req.get('agent')!r}"
        if _brief(req):
            return _brief(req).replace("the step", "an agent step")
    if kind == "crew" and (req.get("job") not in crew or not crew[req["job"]].get("unit")):
        return f"no crew job {req.get('job')!r}"
    if kind == "task" and not isinstance(req.get("task"), int):
        return "a task step names its plan task by number"
    if kind == "notify":
        m = req.get("message")
        if not isinstance(m, str) or not m.strip() or len(m) > NOTE_MAX:   # limit: refuses, NOTE_MAX above
            return f"a message needs its text, at most {NOTE_MAX:,} characters"
    if kind == "ask":
        q, ans = req.get("question"), req.get("answers") or ["Yes", "No"]
        if not isinstance(q, str) or not q.strip() or len(q) > 500:   # limit: refuses, a question fits a card (500 characters)
            return "a question needs its text, at most 500 characters"
        if not isinstance(ans, list) or not 1 <= len(ans) <= ANSWERS_MAX or not all(isinstance(a, str) and 0 < len(a) <= 40 for a in ans):   # limit: refuses, ANSWERS_MAX buttons of 40 characters
            return f"answers are 1 to {ANSWERS_MAX} labels of at most 40 characters"
    if kind == "build":
        if _brief(req):
            return _brief(req).replace("the step", "a coding change")
        if repos is None:
            import builds as B
            repos = B.repos()
        if req.get("repo") not in repos:
            return f"no repository {req.get('repo')!r} the builder may change (there: {', '.join(repos) or 'none'})"
    if kind == "recall":
        q = req.get("query")
        if not isinstance(q, str) or not q.strip() or len(q) > QUERY_MAX:   # limit: refuses, QUERY_MAX above
            return f"a search needs its words, at most {QUERY_MAX} characters"
        if not isinstance(req.get("scope") or "", str):
            return "a search's scope is a collection's name"
    if kind == "remember":
        t, ev = req.get("text"), req.get("evidence") or ""
        if req.get("note") not in NOTES:
            return f"a note is one of {', '.join(NOTES)}"
        if not isinstance(t, str) or not t.strip() or len(t) > MEMO_MAX:   # limit: refuses, MEMO_MAX above
            return f"a note needs its text, at most {MEMO_MAX:,} characters"
        if not isinstance(ev, str) or len(ev) > EVIDENCE_MAX:              # limit: refuses, EVIDENCE_MAX above
            return f"the evidence is at most {EVIDENCE_MAX} characters"
        if req.get("agent") and req["agent"] not in cards:
            return f"no agent {req.get('agent')!r}"
    if kind == "command":
        from domain import places as PL
        if req.get("place") not in PL.PLACES:
            return f"place must be one of {', '.join(PL.PLACES)}"
        if not isinstance(req.get("command"), str) or not COMMAND.fullmatch(req["command"]):
            return "a command is a job kind's name"
        if not isinstance(req.get("values") if req.get("values") is not None else {}, dict):
            return "a command's values are an object of its parameters"
    if kind == "plan":
        why = plan_problem(req.get("steps"), cards)
        if why:
            return why
    if req.get("resume_url") and not resume_target(req["resume_url"]):
        return "resume_url must be n8n's own resume URL"
    return ""


def plan_problem(steps, cards):
    """-> what is wrong with a plan's steps, or "": each names an agent and a brief, waits only for other steps, and
    the plan has no cycle and at most the Conductor's number of steps."""
    import conductor as CD
    if not isinstance(steps, list) or not 1 <= len(steps) <= CD.MAX_STEPS:   # limit: refuses, a plan holds at most the Conductor's MAX_STEPS
        return f"a plan has 1 to {CD.MAX_STEPS} steps"
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            return f"step {i} is not an object"
        if s.get("agent") not in cards:
            return f"step {i}: no agent {s.get('agent')!r}"
        if _brief(s):
            return f"step {i}: {_brief(s).replace('the step ', 'it ')}"
        after = s.get("after") or []
        if not isinstance(after, list) or not all(isinstance(a, int) and 1 <= a <= len(steps) and a != i for a in after):
            return f"step {i} waits for a step that is not another step of the plan"
    try:
        waves([s.get("after") or [] for s in steps])
    except ValueError as e:
        return str(e)
    return ""


def waves(afters):
    """afters: each step's steps it waits for (1-based) -> the steps in waves, each wave the steps whose steps before
    are all in earlier waves; ValueError for a cycle."""
    placed, out = set(), []
    while len(placed) < len(afters):
        wave = [i for i, a in enumerate(afters, 1) if i not in placed and set(a) <= placed]
        if not wave:
            raise ValueError("the plan has a cycle: " + ", ".join(f"step {i}" for i in range(1, len(afters) + 1) if i not in placed))
        out.append(wave)
        placed |= set(wave)
    return out


def resume_target(url):
    """n8n's resume URL, re-aimed at n8n's port on this machine: only its path is used, so a request can never make the
    runner call anywhere else. -> the URL, or "" when it is not a resume URL."""
    try:
        p = urllib.parse.urlsplit(str(url))
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not RESUME_PATH.match(p.path) or not RESUME_QUERY.match(p.query) or p.fragment:
        return ""
    return N8N + p.path + (f"?{p.query}" if p.query else "")


def harness_of(card):
    return card["step_kind"] if card.get("step_kind") else card.get("harness") or "hermes"


def row_of(card, agent, brief, title="", after=(), harness=None):
    """One step row: its title is the step as the agent reads it ("Your step: ..."), its why the card's own prompt and
    the brief."""
    return {"agent": agent, "title": f"{title}: {brief}" if title else brief, "after": list(after), "harness": harness or harness_of(card),
            "model": card.get("model") or "", "why": (f"As the agent {agent}: {card['prompt']}\n\n" if card.get("prompt") else "") + brief}


def open_task(c, rid, req, rows, text, spec=None):
    """The task and its step rows of a request, made once (keyed by the request id). -> the task id."""
    import conductor as CD
    c.execute("create table if not exists flow_steps (id text primary key, task integer, created text)")
    r = c.execute("select task from flow_steps where id=?", (rid,)).fetchone()
    if r:
        return r["task"]
    now = CD.now()
    title = TC.cut(req.get("title") or text.strip().splitlines()[0], 120)   # cap: preview, the whole brief is the task's text
    ref = f"n8n:{req.get('workflow', '')}/{req.get('execution', '')}"
    cur = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, "
                    "source, created, updated) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (text, title, title, "workflow", "workflow", ref, "[]", "standard", "auto", json.dumps({"type": "once"}),
                     json.dumps({"workflow": req.get("workflow"), "execution": req.get("execution"), **(spec or {})}), "[]", "[]",
                     "running", "crew:n8n", now, now))
    tid = cur.lastrowid
    for i, s in enumerate(rows, 1):
        c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts) "
                  "values (?,?,?,?,?,?,?,?,?,?,?,0)", (tid, 1, i, s["title"], "", s["agent"], s["harness"], s["model"],
                                                      json.dumps(s["after"]), s["why"], "pending"))
    c.execute("insert or replace into task_occ (task, occ, trigger, started, status) values (?,?,?,?,?)", (tid, 1, "n8n", now, "running"))
    c.execute("insert into flow_steps (id, task, created) values (?,?,?)", (rid, tid, now))
    c.commit()
    return tid


def open_step(c, rid, req, cards):
    """The task and the one step row of an agent step. -> (task id, step row)."""
    import conductor as CD
    tid = open_task(c, rid, req, [row_of(cards[req["agent"]], req["agent"], req["brief"], req.get("title") or "")], req["brief"])
    return tid, CD.steps(c, tid, 1)[0]


def settle(c, task, idx=1, stop=None, sleep=time.sleep):
    """Runs one step of the task until it has settled, as the Conductor's tick would: headroom, one of its slots, two
    attempts, a step whose work runs elsewhere looked at again. -> the row (unsettled when the runner is stopping)."""
    import conductor as CD
    import tasks as TK
    agents = CD.cards()

    def row():
        return next(x for x in CD.steps(c, task, 1) if x["idx"] == idx)
    for _ in range(100000):                          # limit: stops, a step looked at this often has hung; it fails
        s = row()
        if s["status"] in SETTLED:
            return s
        if stop is not None and stop.is_set():
            return s
        rest = CD.resting.get(s["id"], 0) - time.time()
        if rest > 0 or (s["status"] == "waiting" and s["harness"] not in CD.WAITS):
            sleep(max(rest, WAIT_AGAIN_S))
            continue
        if s["attempts"] >= CD.ATTEMPTS and s["status"] == "pending":
            CD.put(c, s["id"], status="failed", error=s["error"] or "two attempts failed")
            continue
        looks = s["status"] == "waiting"            # looking at work elsewhere takes no slot (TSK-08)
        if not looks:
            why = CD.headroom(s)
            if why:
                if s["waiting_for"] != why:
                    CD.put(c, s["id"], waiting_for=why)
                sleep(WAIT_AGAIN_S)
                continue
            if not CD.slots.acquire(blocking=False):  # as many steps at once as the Conductor runs (SLOTS), its own and n8n's
                sleep(WAIT_AGAIN_S)
                continue
        try:
            if not looks:                           # claimed, then started (an attempt); a look at waiting work is no attempt
                CD.put(c, s["id"], status="running")
                s = {**s, "status": "starting"}
            CD.run_step(c, TK.row(c, task), s, CD.steps(c, task, 1), agents)
        finally:
            if not looks:
                CD.slots.release()
        if row()["status"] == "waiting":
            sleep(WAIT_AGAIN_S)
    s = row()
    CD.put(c, s["id"], status="failed", error="the step did not settle")
    return row()


def drive(c, task, stop=None, sleep=time.sleep):
    """The task's one step, settled. -> its row."""
    return settle(c, task, 1, stop=stop, sleep=sleep)


def close(c, task, ok):
    import conductor as CD
    c.execute("update tasks set status=?, updated=? where id=?", ("done" if ok else "failed", CD.now(), task))
    c.execute("update task_occ set status=?, ended=? where task=? and occ=1", ("done" if ok else "failed", CD.now(), task))
    c.commit()


COVERED = "already running: this run is covered by the one in progress"


def run_crew(job, by_id, run=subprocess.run):
    """A crew job as "Run now" starts it, waited for; its own result file says how it went. A job whose unit is still
    running answers at once that this run is covered by that one: never two at once, as its timer kept it, and no
    n8n runs piling up behind a job that outlasts its schedule's spacing."""
    ag = by_id[job]
    q = run(["systemctl", "--user", "is-active", f"{ag['unit']}.service"], capture_output=True, text=True)
    if (q.stdout or "").strip() in ("active", "activating", "reloading"):
        return {"status": "done", "output": COVERED, "crew": {}}
    p = run(["systemctl", "--user", "start", "--wait", f"{ag['unit']}.service"], capture_output=True, text=True)
    res = Path(f"/srv/ai/missions/crew/{job}.json")
    try:
        last = json.loads(res.read_text())
    except (OSError, ValueError):
        last = {}
    return {"status": "done" if p.returncode == 0 else "failed", "output": last.get("result") or last.get("summary") or "",
            "error": tail((p.stderr or "").strip(), 2000) if p.returncode else "", "crew": last}   # cap: store, an error's tail in the answer; the journal has it all


WAITING = ("scheduled", "done", "failed")            # a task that may start a run (as Run again on its page)


def run_task(c, rid, tid, stop=None, sleep=time.sleep):
    """One run of a task, started once per request (kept in flow_steps), waited for until it has finished: an occurrence
    of a plan task, or a run of the mission that does the task. -> the answer, or None when the runner is stopping (the
    request is looked at again after its restart)."""
    import conductor as CD
    import tasks as TK
    c.execute("create table if not exists flow_steps (id text primary key, task integer, created text)")
    cols = [r[1] for r in c.execute("pragma table_info(flow_steps)")]
    for col in ("occ", "run"):
        if col not in cols:
            c.execute(f"alter table flow_steps add column {col} integer")
    try:
        t = TK.row(c, tid)
    except ValueError:
        t = None
    if not t or t["door"] not in ("plan", "mission"):
        return {"status": "refused", "error": f"no plan task #{tid}"}
    r = c.execute("select occ, run from flow_steps where id=?", (rid,)).fetchone()
    if t["door"] == "mission":
        return run_mission(c, rid, t, r["run"] if r else None, stop=stop, sleep=sleep)
    if r and r["occ"]:
        occ = r["occ"]
    else:
        if t["status"] not in WAITING:
            return {"status": "refused", "error": f"task #{tid} is {t['status']}, not waiting for a run"}
        CD.start(c, t, trigger="n8n")
        TK.put(c, tid, status="running")
        occ = CD.occ_of(c, tid)
        c.execute("insert or replace into flow_steps (id, task, created, occ) values (?,?,?,?)", (rid, tid, CD.now(), occ))
        c.commit()
        CD.M.event("task", "", f"Task #{tid} run {occ} started by n8n: {t['title']}", title="Tasks")
    for _ in range(100000):                          # limit: stops, an occurrence looked at this often has hung
        o = c.execute("select status, result, verdict from task_occ where task=? and occ=?", (tid, occ)).fetchone()
        if o and o["status"] not in ("running", None):
            return {"status": "done" if o["status"] in ("done", "ok") else o["status"], "task": tid, "occ": occ,
                    "output": o["result"] or "", "verdict": o["verdict"] or ""}
        if stop is not None and stop.is_set():
            return None
        sleep(WAIT_AGAIN_S)
    return {"status": "failed", "task": tid, "occ": occ, "error": "the occurrence did not finish"}


def run_mission(c, rid, t, run_id=None, stop=None, sleep=time.sleep):
    """One run of the mission that does a task (its door), queued as the mission's own runs are and waited for. A run
    already queued or running for it is the one waited for, never a second. -> the answer, or None when stopping."""
    if not run_id:
        if t["status"] != "scheduled":
            return {"status": "refused", "error": f"task #{t['id']} is {t['status']}, not waiting for a run"}
        M.enqueue(c, t["ref"], "n8n")
        got = c.execute("select max(id) from runs where slug=? and status in ('queued', 'running', 'waiting')", (t["ref"],)).fetchone()
        if not got or not got[0]:
            return {"status": "refused", "error": f"the mission {t['ref']} took no run"}
        run_id = got[0]
        c.execute("insert or replace into flow_steps (id, task, created, run) values (?,?,?,?)", (rid, t["id"], time.strftime("%Y-%m-%dT%H:%M:%S"), run_id))
        c.commit()
        M.event("task", t["ref"], f"Task #{t['id']}: its mission's run started by n8n: {t['title']}", title="Tasks")
    for _ in range(100000):                          # limit: stops, a run looked at this often has hung
        o = c.execute("select status, summary from runs where id=?", (run_id,)).fetchone()
        if not o or o["status"] not in ("queued", "running", "waiting"):
            st = o["status"] if o else "failed"
            return {"status": "done" if st == "ok" else st, "task": t["id"], "run": run_id, "output": (o["summary"] if o else "") or ""}
        if stop is not None and stop.is_set():
            return None
        sleep(WAIT_AGAIN_S)
    return {"status": "failed", "task": t["id"], "run": run_id, "error": "the mission's run did not finish"}


def run_build(c, rid, req, cards, stop=None, sleep=time.sleep):
    """A coding change: one build step on the task's repository, as the Conductor runs it (run_build: a builder
    assignment, its checks, the owner's review). -> the answer, or None when the runner is stopping."""
    import conductor as CD
    card = cards.get(CD.BUILDER) or {}
    tid = open_task(c, rid, req, [row_of(card, CD.BUILDER, req["brief"], req.get("title") or "", harness="build")], req["brief"],
                    spec={"repo": req["repo"]})
    s = settle(c, tid, 1, stop=stop, sleep=sleep)
    if s["status"] not in SETTLED:
        return None
    close(c, tid, s["status"] in CD.FINISHED)
    r = c.execute("select ref from step_refs where kind='build' and task=? order by cast(ref as integer) desc", (tid,)).fetchone()
    b = c.execute("select * from builds where id=?", (int(r["ref"]),)).fetchone() if r else None
    return {**answer_of(tid, s), "build": int(r["ref"]) if r else None, "state": b["status"] if b else "",
            "branch": (b["branch"] or "") if b else "", "pr": (b["pr"] or "") if b else "", "ci": (b["ci"] or "") if b else "",
            "checks": tail(b["checks"] or "", 4000, "the build keeps the whole log") if b else ""}   # cap: preview, the checks' end; the build's page has them all


def run_plan(c, rid, req, cards, stop=None, sleep=time.sleep, db=None):
    """An improvised plan as one task: its steps are rows, run in waves (every step whose steps before have finished,
    together), each through the same path as an agent step. A step after one that failed does not run. -> the answer
    with every step's output, or None when the runner is stopping."""
    import conductor as CD
    steps = req["steps"]
    rows = [row_of(cards[s["agent"]], s["agent"], s["brief"], s.get("title") or "", after=s.get("after") or []) for s in steps]
    tid = open_task(c, rid, req, rows, req.get("title") or "\n".join(s["brief"].strip().splitlines()[0] for s in steps))
    for _ in range(CD.MAX_STEPS + 1):                # a wave per round: never more rounds than steps
        ss = CD.steps(c, tid, 1)
        state = {s["idx"]: s["status"] for s in ss}
        for s in ss:
            gone = [a for a in s["after"] if state.get(a) in ("failed", "cancelled")]
            if s["status"] == "pending" and gone:
                CD.put(c, s["id"], status="cancelled", error=f"step {gone[0]} did not finish", ended=CD.now())
                state[s["idx"]] = "cancelled"
        wave = [s["idx"] for s in ss if state[s["idx"]] not in SETTLED and all(state.get(a) in CD.FINISHED for a in s["after"])]
        if not wave:
            break
        if stop is not None and stop.is_set():
            return None
        threads = [threading.Thread(target=_settle_in, args=(db or M.db, tid, i, stop, sleep), daemon=True, name=f"flow-{rid}-{i}")
                   for i in wave]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    ss = CD.steps(c, tid, 1)
    if any(s["status"] not in SETTLED for s in ss):
        return None                                  # the runner is stopping: the plan goes on after its restart
    ok = all(s["status"] in CD.FINISHED for s in ss)
    close(c, tid, ok)
    last = [s for s in ss if not any(s["idx"] in x["after"] for x in ss)]
    out = last[0]["output"] or "" if len(last) == 1 else "\n\n".join(f"### Step {s['idx']}: {s['title']}\n{s['output'] or ''}" for s in last)
    bad = next((s for s in ss if s["status"] not in CD.FINISHED), None)
    return {"status": "done" if ok else "failed", "task": tid, "output": out,
            "error": f"step {bad['idx']}: {bad['error'] or bad['status']}" if bad else "",
            "steps": [{"step": s["idx"], **answer_of(tid, s)} for s in ss]}


def _settle_in(db, task, idx, stop, sleep):
    c = db()
    try:
        settle(c, task, idx, stop=stop, sleep=sleep)
    except Exception as e:                          # an adapter bug fails the step, not the plan's worker; it is logged
        import conductor as CD
        s = next(x for x in CD.steps(c, task, 1) if x["idx"] == idx)
        CD.put(c, s["id"], status="failed", error=f"{type(e).__name__}: {e}")
        if M:
            M.log(f"flows: task {task} step {idx}: {type(e).__name__}: {e}")
    finally:
        c.close()


def recall(req):
    """The memory tool's search (MEM-28), as the owner's: every collection. -> its hits, each with its collection."""
    import memstack as MS
    text = MS.handle({"action": "mem_search", "query": req["query"], "scope": req.get("scope") or "", "access": "all",
                      "agent": req.get("agent") or ""})["text"]
    hits, coll = [], ""
    for line in text.splitlines():
        if line.startswith("### "):
            coll = line[4:].strip()
        elif line.startswith("- ") and coll:
            hits.append({"collection": coll, "hit": TC.cut(line[2:], HIT_CHARS, "memory open gives the entry whole")})   # cap: preview, a hit names its ref to open
    return {"status": "done", "hits": hits, **({} if hits else {"said": text})}


KEPT = ("Kept", "Already known", "Already held", "Queued")   # memwrite.candidate's words for a note memory holds or will


def remember(req):
    """A note through the memory tool's write gate (MEM-28, MEM-35): it enters memory only after its check."""
    import memstack as MS
    said = MS.handle({"action": "mem_note", "kind": req["note"], "text": req["text"], "evidence": req.get("evidence") or "",
                      "agent": req.get("agent") or "n8n", "repo": req.get("repo") or "", "access": "all"})["text"]
    return {"status": "done", "kept": said.startswith(KEPT), "said": said}


def _job_spec(kind):
    """The job kind's typed parameters from the running packs, so a value outside its type is refused before the
    request; the worker checks again."""
    try:
        from domain import packs as PK
        return next((j["spec"] for p in PK.load()["packs"] for j in p["jobs"] if j["kind"] == kind), None)
    except Exception as e:                           # the worker still checks every value against its own copy; logged
        if M:
            M.log(f"flows: packs for {kind}: {type(e).__name__}: {e}")
        return None


def _place_worker(name):
    """The wsl place's worker is a thread of the runner; the engine's bridge starts it when Temporal runs, the step
    service when it does not."""
    if name != "wsl" or M is None or any(t.name == "place-wsl" and t.is_alive() for t in threading.enumerate()):
        return
    from domain import places as PL
    threading.Thread(target=PL.worker_loop, args=(M.stop,), daemon=True, name="place-wsl").start()


def command(rid, req, stop=None, sleep=time.sleep):
    """A job kind at a place (GEN-22): only a kind the owner approved there by its fingerprint runs; the approval waits
    in Needs you and the step is refused with that reason meanwhile. -> the answer, or None when the runner is stopping."""
    from domain import places as PL
    JOBS.mkdir(parents=True, exist_ok=True)
    mine = JOBS / f"{rid}.json"
    try:
        p = PL.place(req["place"])
        if mine.exists():
            job = json.loads(mine.read_text())
        else:
            _place_worker(req["place"])
            job = {"rid": p.submit(req["command"], req.get("values") or {}, spec=_job_spec(req["command"])), "at": time.time()}
            mine.write_text(json.dumps(job))
    except PL.Refused as e:
        return {"status": "refused", "error": str(e)}
    while True:
        st = p.state(job["rid"], submitted=job["at"])
        if st["status"] in ("done", "failed", "refused", "lost", "not picked up"):
            log = p.answers / job["rid"] / "artifacts" / "log.txt"
            return {"status": st["status"] if st["status"] in ("done", "refused") else "failed", "place": req["place"],
                    "command": req["command"], "job": f"{req['place']}/{job['rid']}", "error": st.get("error") or "",
                    "steps": st.get("steps") or [], "artifacts": [a.name for a in p.artifacts(job["rid"])],
                    "log": tail(log.read_text(errors="replace"), 4000, f"the whole log is {log}") if log.is_file() else ""}   # cap: preview, the log's end; the job keeps it whole
        if stop is not None and stop.is_set():
            return None
        sleep(POLL_S)


def ask(rid, req, notify=None):
    """The question waits in Needs you until the owner answers. -> the answer, or None while there is none."""
    ASKS.mkdir(parents=True, exist_ok=True)
    got = ASKS / f"{rid}.answer.json"
    if got.exists():
        a = json.loads(got.read_text())
        return {"status": "done", "answer": a["answer"], "answered": a.get("at", "")}
    q = ASKS / f"{rid}.json"
    if not q.exists():
        q.write_text(json.dumps({"id": rid, "question": req["question"], "why": req.get("why") or "", "answers": req.get("answers") or ["Yes", "No"],
                                 "workflow": req.get("workflow"), "execution": req.get("execution"),
                                 "created": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, ensure_ascii=False))
        if notify:
            notify(f"A workflow asks you: {req['question']} (Needs you)")
    return None


def answer(req):
    """The owner's tap in Needs you (action flow_answer): the answer of one waiting question."""
    rid, a = str(req.get("id") or ""), req.get("answer")
    q = ASKS / f"{rid}.json"
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid) or not q.exists():
        return {"ok": False, "error": "that question is not waiting any more"}
    if a not in json.loads(q.read_text())["answers"]:
        return {"ok": False, "error": "that is not one of the question's answers"}
    got = ASKS / f"{rid}.answer.json"
    if got.exists():
        return {"ok": False, "error": "it was answered already"}
    got.write_text(json.dumps({"answer": a, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}))
    return {"ok": True, "answer": a}


def waiting():
    """The questions without an answer, for Needs you."""
    if not ASKS.is_dir():
        return []
    return [json.loads(p.read_text()) for p in sorted(ASKS.glob("*.json"))
            if not p.name.endswith(".answer.json") and not (ASKS / f"{p.stem}.answer.json").exists()]


def answer_of(task, s):
    return {"status": "done" if s["status"] in ("done", "skipped") else s["status"], "task": task, "step": s["id"],
            "output": s.get("output") or "", "error": s.get("error") or "", "agent": s.get("agent"), "harness": s.get("harness")}


WORD = {"done": "done", "failed": "failed", "refused": "refused", "cancelled": "cancelled"}
WHAT = {"crew": lambda r: f"crew job {r['job']}", "task": lambda r: f"task #{r['task']}", "build": lambda r: f"a coding change in {r['repo']}",
        "recall": lambda r: "a memory search", "remember": lambda r: f"a {r['note']} for memory",
        "command": lambda r: f"{r['command']} at {r['place']}", "plan": lambda r: f"a plan of {len(r['steps'])} steps"}


def report(req, answer):
    """WFL-10: Home's feed hears how each step of a workflow ended, in the owner's words, with the run's place in n8n."""
    ev = getattr(M, "event", None)
    if not ev or req.get("kind") == "ask":
        return
    try:
        what = req.get("title") or WHAT[req["kind"]](req)
    except (KeyError, TypeError):
        what = req.get("agent") or "a step"
    st = WORD.get(answer.get("status"), answer.get("status"))
    why = f": {answer['error']}" if answer.get("error") and st != "done" else ""
    run = f" (n8n run {req['execution']})" if req.get("execution") else ""
    ev("workflow", "", f"{what}: {st}{why}{run}", title="Workflows", push=st in ("failed", "refused"))


def deliver(url, answer, post=None):
    """POSTs the answer to n8n's resume URL. -> True when n8n took it."""
    target = resume_target(url)
    if not target:
        return False
    data = json.dumps(answer, ensure_ascii=False).encode()
    req = urllib.request.Request(target, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with (post or urllib.request.urlopen)(req, timeout=30) as r:
            return 200 <= r.status < 300
    except OSError:
        return False


def all_cards():
    """The agents a step may name: the stack's cards and each running pack's (<pack>:<agent>)."""
    import conductor as CD
    try:
        from domain import packs as PK
        return {**CD.cards(), **PK.cards()}
    except Exception as e:                           # the stack's own agents still run; the pack's wait for its fix
        if M:
            M.log(f"flows: packs: {type(e).__name__}: {e}")
        return CD.cards()


def work(rid, req, cards, crew, sleep):
    """The request's work, by its kind. -> the answer, or None while it waits (looked at again on the next scan, or after
    the runner's restart)."""
    k = req["kind"]
    if k == "crew":
        return run_crew(req["job"], crew)
    if k == "notify":                                # the stack's own notification path: quiet hours, the data guard (OBS-16, GEN-14)
        M.notify(req["message"])
        return {"status": "done", "sent": True}
    if k == "ask":
        return ask(rid, req, notify=M.notify if M else None)
    if k == "task":
        return run_task(M.db(), rid, req["task"], stop=M.stop, sleep=sleep)
    if k == "recall":
        return recall(req)
    if k == "remember":
        return remember(req)
    if k == "command":
        return command(rid, req, stop=M.stop, sleep=sleep)
    if k == "build":
        return run_build(M.db(), rid, req, cards, stop=M.stop, sleep=sleep)
    if k == "plan":
        return run_plan(M.db(), rid, req, cards, stop=M.stop, sleep=sleep)
    c = M.db()
    task, _ = open_step(c, rid, req, cards)
    s = drive(c, task, stop=M.stop, sleep=sleep)
    if s["status"] not in SETTLED:
        return None                                  # the runner is stopping: looked at again after its restart
    import conductor as CD
    close(c, task, s["status"] in CD.FINISHED)
    return answer_of(task, s)


def handle(rid, path, cards=None, crew=None, post=None, sleep=time.sleep, repos=None):
    """One request, from validation to the answer n8n gets."""
    import crew as CR
    cards = cards if cards is not None else all_cards()
    crew = crew if crew is not None else CR.BY_ID
    req = json.loads(path.read_text())
    DONE.mkdir(parents=True, exist_ok=True)
    out = DONE / f"{rid}.json"
    if out.exists():
        answer = json.loads(out.read_text())
    else:
        why = validate(req, cards, crew, repos=repos)
        answer = {"status": "refused", "error": why} if why else work(rid, req, cards, crew, sleep)
        if answer is None:
            return
        out.write_text(json.dumps(answer, ensure_ascii=False))
        report(req, answer)
    if not req.get("resume_url"):
        path.unlink(missing_ok=True)
        return
    first = time.time()
    while time.time() - first < DELIVER_FOR_S:
        if deliver(req["resume_url"], answer, post):
            path.unlink(missing_ok=True)
            return
        if M and M.stop.is_set():
            return
        sleep(DELIVER_EVERY_S)
    path.unlink(missing_ok=True)
    M.notify(f"n8n did not take the answer of step {rid} for a day; it is kept in {out}.")


def _run(rid, path):
    try:
        handle(rid, path)
    except Exception as e:                              # logged; the request stays pending and is looked at after a restart
        M.log(f"flows: {rid}: {type(e).__name__}: {e}")
    finally:
        with _lock:
            _busy.discard(rid)


REPO_WORKFLOWS = Path(__file__).resolve().parent.parent / "n8n/workflows"
CATALOG_EVERY_S = 60
PLACE_NAMES = {"wsl": "WSL (the stack's own user)", "wsl-host": "WSL host (the owner's tools and repositories)", "windows": "Windows"}


def catalog(repo=REPO_WORKFLOWS, made=None):
    """WFL-11: which crew job and task has which n8n workflow, and whether n8n runs it now, for the app's pages (the
    repository's workflows and those the runner made since the last export, ops/n8n_jobs.py).
    -> {"jobs": {"crew:<job>" | "task:<id>": {"id", "name", "active"}}}"""
    import n8n_jobs as NJ
    idx = NJ.index(repo, made or NJ.MADE)
    return {"jobs": {f"{k}:{key}": {"id": w["id"], "name": w["name"], "active": w["active"]} for (k, key), w in sorted(idx.items(), key=str)}}


STEP_HARNESSES = ("hermes", "claude-code", "python", "opencode")   # the harnesses a step can run on (TSK-07)
CARD_STEPS = ("build", "check")                   # TRL-07, TRL-08: a card's steps are builds in its lane, or the judge's checks


def runs_steps(card):
    """Can this agent do a step? Its steps are builds or checks, or its harness has an adapter and a python agent has its
    own key."""
    if card.get("step_kind") in CARD_STEPS:
        return True
    return card.get("harness") in STEP_HARNESSES and (card["harness"] != "python" or card.get("key") not in (None, "none"))


def step_agents(packs=()):
    """The agents a step may name: the stack's (config/agents.yaml, those that can do a step) and each running pack's
    (<pack>:<agent>), with their harness and purpose."""
    import yaml
    try:
        reg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config/agents.yaml").read_text())
    except OSError:
        reg = {}
    core = [{"id": a["id"], "name": a.get("name") or a["id"], "harness": a.get("harness", ""), "purpose": a.get("purpose", "")}
            for a in reg.get("agents") or [] if runs_steps(a)]
    return core + [{k: a.get(k, "") for k in ("id", "name", "harness", "purpose", "pack")} for p in packs or () for a in p["agents"]]


def step_catalog(packs=None, repos=None, places=None):
    """WFL-06: what the node's pickers offer, live: the agents that can do a step (the stack's and each running pack's),
    the crew jobs, the places with the commands approved at each, the repositories the builder may change, and the kinds.
    A part that cannot be read is empty, with its reason under "problems"."""
    import crew as CR
    out = {"kinds": list(KINDS), "agents": [], "crew": [], "places": [], "repos": [], "problems": []}

    def part(name, f):
        try:
            out[name] = f()
        except Exception as e:                      # one part missing leaves the others
            out["problems"].append(f"{name}: {type(e).__name__}: {e}")

    def agents():
        from domain import packs as PK
        return step_agents(packs if packs is not None else PK.load()["packs"])

    def where():
        from domain import places as PL
        names = places if places is not None else [n for n in PL.PLACES if n in PL.config() or n == "windows"]
        got = []
        for n in names:
            st = PL.place(n).status() or {}
            got.append({"id": n, "name": PLACE_NAMES.get(n, n), "answering": bool(st),
                        "commands": sorted(k for k, v in (st.get("kinds") or {}).items() if v.get("approved"))})
        return got

    def code():
        import builds as B
        return [{"id": r, "name": r} for r in (repos if repos is not None else B.repos())]
    part("agents", agents)
    part("crew", lambda: [{"id": j, "name": a.get("name") or j} for j, a in sorted(CR.BY_ID.items()) if a.get("unit")])
    part("places", where)
    part("repos", code)
    return out


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)


def write_catalog(public):
    """public/workflows.json for the app's pages (WFL-11), public/step-catalog.json for the node's pickers (WFL-06)."""
    _write(Path(public) / "workflows.json", catalog())
    _write(Path(public) / "step-catalog.json", step_catalog())


def worker():
    PENDING.mkdir(parents=True, exist_ok=True)
    PENDING.chmod(0o777)                                # the app container (another uid) drops requests here
    shown = 0.0
    while not M.stop.is_set():
        if time.time() - shown > CATALOG_EVERY_S:
            shown = time.time()
            try:                                        # WFL-09: a task that got a schedule gets its workflow
                import n8n_jobs as NJ
                for said in NJ.reconcile(M.db(), say=M.log):
                    M.event("task", "", said[:1].upper() + said[1:], title="Tasks")
            except Exception as e:                      # logged; tried again on the next pass
                M.log(f"flows: workflows of tasks: {type(e).__name__}: {e}")
            try:
                write_catalog(M.PUBLIC)
            except Exception as e:                      # logged; the pages show no link meanwhile
                M.log(f"flows: catalog: {type(e).__name__}: {e}")
        for f in sorted(PENDING.glob("*.json")):
            rid = f.stem
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid):
                continue
            with _lock:
                if rid in _busy:
                    continue
                _busy.add(rid)
            threading.Thread(target=_run, args=(rid, f), daemon=True, name=f"flow-{rid}").start()
        M.stop.wait(SCAN_S)


def start(m):
    global M
    M = m
    threading.Thread(target=worker, daemon=True, name="flows").start()


if __name__ == "__main__":
    for d in (PENDING, DONE):
        print(d, sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else "none")
