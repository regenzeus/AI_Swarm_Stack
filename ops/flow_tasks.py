"""DEC-46, TSK-52, TAX-09: one workflow, one task. Every task of the stack is in one list (TSK-40's yours/stack split is
gone: the owner, 11 Nov 2026, "I want the app to show me whats going on in stack"); a workflow is one task of it.

A crew job's workflow is its crew duty's task (door crew); a task's own workflow is that task. Every other workflow (a
chain like the tax desk, the home inbox's item workflow, the stack's self-test) is one task here:

- door "flow", ref the workflow's file stem (n8n/workflows/<stem>.json); its area the workflow's (ops/areas.py); its
  When the workflow's schedule; running while a run of the workflow is
- its runs are the workflow's runs (n8n executions), one occurrence each, numbered from the first; each run's steps are
  the workflow's AI Stack steps in order, named for what they do, with their state, times and answer (the step
  service's records, ops/flows_view.py, and for runs older than those, the step service's own task of each run, so
  no run's history is lost); an agent step's own log one tap away
- Run now on it starts the workflow through its Run now webhook (WFL-13), as n8n's own Run now would
- its result: a view of its own (the tax desk's drafts) or the page that holds it
- the work it folds in leaves the list: the crew duties of its steps and the task the step service makes for each run
  of an agent step (ops/flows.py still makes it, as the step's record; it keeps its page and shows here as a step)

    python3 ops/flow_tasks.py      every workflow with its area, and the flow tasks with their runs
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# How a workflow's task reads where its file's name and steps do not say it well enough: its file stem -> title, kind,
# agent, its result (a view of its own, or the page that holds it), goal and definition of done.
SHOW = {
    "tax-desk": {"title": "Your taxes", "kind": "tax", "agent": "tax", "result": "tax",
                 "goal": "Find your German income tax papers in the copy of your mail, file a copy of each in Steuern on the NAS "
                         "and prepare a draft per year from your earlier returns, for you to enter in ELSTER yourself.",
                 "done": ["Each run files the new papers by year and form and brings each year's draft up to date",
                          "What only you know is asked in Needs you, never guessed"]},
    "item-home-inbox": {"title": "Your inbox: an answer to each new item", "agent": "main",
                        "goal": "Answer each new item in your home inbox, post the answer, wait for your reply, and close it with a summary."},
}
SOURCE = "flow"                                      # who asked (tasks.asked_by): its workflow's area says whether it is upkeep
RUN_TIMEOUT_S = 15                                   # limit: stops, n8n answers its Run now webhook at once; a silent n8n is said so
CACHE_S = 30                                         # the workflow files are read again at most every 30 s (the board is made every few)
_seen = {"mtime": None, "data": {}}
_wfs = {"t": 0.0, "data": None}
_answers = {}                                         # a settled step's answer never changes: read once


# ---------------------------------------------------------------- what it is for
def area_of_workflow(wf):
    """The workflow's area: what its file says (TSK-52); a file from before says nothing, so a crew job's workflow is
    its job's area and anything else research."""
    import areas as AR
    if wf.get("area") in AR.AREAS:
        return wf["area"]
    import n8n_jobs as NJ
    kind, key = NJ.target(wf)
    if kind == "crew":
        import crew as CR
        return (CR.BY_ID.get(key) or {}).get("area") or "upkeep"
    return "research"


def workflows(repo=None, made=None):
    """{file stem: workflow} of this deployment, as n8n should have it (the runner's newer word over git's); read again
    at most every CACHE_S unless the folders are given (tests)."""
    import n8n_jobs as NJ
    fresh = repo is None and made is None
    if fresh and _wfs["data"] is not None and time.time() - _wfs["t"] < CACHE_S:
        return _wfs["data"]
    out = {Path(w["file"]).stem: w["wf"] for w in NJ.workflows(repo or NJ.REPO, made or NJ.MADE).values()}
    if fresh:
        _wfs.update(t=time.time(), data=out)
    return out


def single_crew(wf):
    """A workflow of one crew job's step: that job's task is the workflow's task (door crew)."""
    import flows_view as FV
    steps = FV.steps_of(wf)
    return len(steps) == 1 and steps[0]["kind"] == "crew"


def flows(repo=None, made=None):
    """{file stem: workflow} of the workflows that are a task here: not a task's own workflow, not one crew job's."""
    import n8n_jobs as NJ
    return {s: wf for s, wf in workflows(repo, made).items() if NJ.target(wf)[0] != "task" and not single_crew(wf)}


def workflow(stem, repo=None, made=None):
    return workflows(repo, made).get(stem)


def workflow_of_run(ref, repo=None, made=None):
    """The workflow of the task the step service made for one run (ref n8n:<workflow id>/<execution>), or None."""
    wid = str(ref or "").removeprefix("n8n:").split("/")[0]
    return next((w for w in workflows(repo, made).values() if str(w.get("id")) == wid), None)


def area_of_run(ref, repo=None, made=None):
    wf = workflow_of_run(ref, repo, made)
    return area_of_workflow(wf) if wf else "research"


# ---------------------------------------------------------------- its runs
def seen():
    """The step service's records of each step n8n sent (ops/flows_view.py keeps them), read again when they change."""
    import flows_view as FV
    try:
        m = FV.SEEN.stat().st_mtime
    except OSError:
        return {}
    if _seen["mtime"] != m:
        _seen.update(mtime=m, data=FV.load())
    return _seen["data"]


def _same(p, rec):
    """A record is this plan step's: the same kind, crew job or agent (a step renamed since keeps its runs)."""
    if p["kind"] != (rec.get("kind") or "agent"):
        return False
    if p["kind"] == "crew":
        return rec.get("job") == p.get("job")
    if p["kind"] == "agent":
        return rec.get("agent") == p.get("agent")
    return (rec.get("title") or "") == p["title"]


def _answer(rid, done):
    if rid in _answers:
        return _answers[rid]
    try:
        d = json.loads((Path(done) / f"{rid}.json").read_text())
        d = d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}
    _answers[rid] = {k: d.get(k) for k in ("output", "error")}
    return _answers[rid]


def _hidden(c, rid):
    """The task the step service made for an agent step's run (ops/flows.py open_task), or None."""
    try:
        r = c.execute("select task from flow_steps where id=?", (rid,)).fetchone()
    except Exception:                                # no step has run on this machine yet: no table
        return None
    return r[0] if r else None


def older(c, wid, have):
    """The step service's task of each run of this workflow's agent steps whose execution the step records do not hold
    (they keep the newest 3,000 steps): {key: record as runs() reads it}. Nothing is moved or deleted."""
    out = {}
    try:
        rows = c.execute("select t.id, t.ref, s.agent, s.title, s.status, s.started, s.ended, s.output, s.error from tasks t "
                         "join task_steps s on s.task=t.id and s.idx=1 where t.door='workflow' and t.ref like ?", (f"n8n:{wid}/%",)).fetchall()
    except Exception:                                # no step has run on this machine yet
        return out
    for r in rows:
        ex = str(r["ref"]).split("/", 1)[1]
        if ex in have or not r["started"]:
            continue
        st = {"done": "done", "skipped": "done", "failed": "failed", "cancelled": "cancelled"}.get(r["status"], "running")
        out[f"task-{r['id']}"] = {"workflow": wid, "execution": ex, "kind": "agent", "agent": r["agent"], "title": r["title"],
                                  "started": r["started"], "ended": r["ended"], "status": st, "output": r["output"] or "",
                                  "error": r["error"] or "", "from_task": r["id"]}
    return out


def plan_of(wf):
    """The workflow's AI Stack steps as the task's plan: each step, who does it and what it does."""
    import crew as CR
    import flows_view as FV
    import yaml
    try:
        cards = {a["id"]: a for a in yaml.safe_load((ROOT / "config/agents.yaml").read_text())["agents"]}
    except (OSError, KeyError, TypeError):
        cards = {}
    out = []
    for p in FV.steps_of(wf):
        if p["kind"] == "crew":
            out.append({"step": p["title"], "agent": f"crew:{p.get('job')}", "why": (CR.BY_ID.get(p.get("job")) or {}).get("what", "")})
        else:
            a = cards.get(p.get("agent")) or {}
            out.append({"step": p["title"], "agent": p.get("agent") or p["kind"], "why": a.get("purpose", "")})
    return out


def runs(c, wf, records=None, done=None):
    """The workflow's runs as the task's occurrences, newest first: each n8n execution with its number (from the first),
    state, times, the last answer and the hidden tasks of its agent steps; and each run's steps in the workflow's order.
    -> (occurrences, {occ: [step]})."""
    import flows as FW
    import flows_view as FV
    wid, plan = str(wf.get("id")), FV.steps_of(wf)
    done = done or FW.DONE
    by = {}
    for rid, rec in (seen() if records is None else records).items():
        if str(rec.get("workflow")) == wid and rec.get("execution"):
            by.setdefault(str(rec["execution"]), []).append((rid, rec))
    for rid, rec in older(c, wid, set(by)).items():  # runs the step records no longer hold: from the step service's tasks
        by.setdefault(rec["execution"], []).append((rid, rec))
    occs, steps = [], {}
    for n, (ex, recs) in enumerate(sorted(by.items(), key=lambda x: min(r["started"] for _, r in x[1])), 1):
        recs.sort(key=lambda x: x[1]["started"])
        rows, used, hidden = [], set(), []
        for i, p in enumerate(plan, 1):
            hit = next(((rid, rec) for rid, rec in recs if rid not in used and _same(p, rec)), None)
            row = {"idx": i, "title": p["title"], "agent": f"crew:{p.get('job')}" if p["kind"] == "crew" else p.get("agent") or p["kind"],
                   "harness": "crew job" if p["kind"] == "crew" else p["kind"], "after": [i - 1] if i > 1 else [], "occ": n,
                   "status": "pending", "started": None, "ended": None, "output": "", "error": "", "attempts": 0, "waiting_for": None}
            if p["kind"] == "crew":
                row["href"] = f"#/crew/{p.get('job')}"
            if hit and hit[1].get("from_task"):          # an older run, as its task kept it
                rid, rec = hit
                used.add(rid)
                row.update(status=rec["status"], started=rec["started"], ended=rec["ended"], attempts=1, output=rec["output"],
                           error=rec["error"], live=f"task:{rec['from_task']}:step:1")
                hidden.append(rec["from_task"])
            elif hit:
                rid, rec = hit
                used.add(rid)
                st, end = FV.state_of(rid, rec, done)
                a = _answer(rid, done) if end else {}
                row.update(status={"refused": "failed"}.get(st, st), started=rec["started"], ended=end, attempts=1,
                           output=str(a.get("output") or ""), error=str(a.get("error") or ""))
                t = _hidden(c, rid) if p["kind"] == "agent" else None
                if t:
                    row["live"] = f"task:{t}:step:1"          # the agent step's own log (ops/flows.py runs it as task <t>, step 1)
                    hidden.append(t)
            rows.append(row)
        live = [r for r in rows if r["status"] in ("running", "waiting")]
        bad = [r for r in rows if r["status"] in ("failed", "cancelled")]
        ran = [r for r in rows if r["started"]]
        if not live:                                 # an ended run: a step it never reached did not run
            for r in rows:
                if not r["started"]:
                    r["status"] = "not run"
        said = next((r["output"] or r["error"] for r in reversed(ran) if r["output"] or r["error"]), "")
        ends = [r["ended"] for r in rows if r["ended"]]
        occs.append({"occ": n, "trigger": "n8n", "execution": ex, "started": ran[0]["started"] if ran else None,
                     "ended": None if live or not ends else max(ends), "status": "running" if live else "failed" if bad else "done",
                     "result": said, "verdict": None, "live": None, "tasks": hidden})
        steps[n] = rows
    return occs[::-1], steps


def asks(stem):
    """How many of the flow's questions wait in Needs you: a count, never their text (the board is every screen's)."""
    if (SHOW.get(stem) or {}).get("result") == "tax":
        import tax as TX
        return len(TX.load("questions.json", []) or [])
    return 0


def schedule_words(wf):
    import flows_view as FV
    words = FV.schedule_of(wf)
    return words if wf.get("active") else f"{words} · switched off"


def show(stem, wf):
    """How the task of a workflow reads: SHOW's words over what the workflow and its crew job say."""
    import crew as CR
    import flows_view as FV
    s = SHOW.get(stem) or {}
    steps = FV.steps_of(wf)
    jobs = [p["job"] for p in steps if p.get("job")]
    agent = s.get("agent") or next((p["agent"] for p in steps if p.get("agent")), None)
    what = (CR.BY_ID.get(jobs[0]) or {}).get("what", "") if len(steps) == 1 and jobs else ""
    return {"title": s.get("title") or str(wf.get("name") or stem).removeprefix("Crew: "), "kind": s.get("kind"), "agent": agent, "area": area_of_workflow(wf),
            "goal": s.get("goal") or what or str(wf.get("name") or stem), "result": s.get("result"),
            "result_href": s.get("result_href"), "result_label": s.get("result_label"),
            "done": s.get("done") or ["Each run does its work and says what it found"]}


# ---------------------------------------------------------------- on the board
def sync(c, repo=None, made=None):
    """Each workflow that is a task here has its task, once; its When follows the workflow's schedule and its state the
    workflow's runs (running while one is). A workflow gone from the deployment leaves the list. -> the task ids."""
    import tasks as TK
    out, mine = [], flows(repo, made)
    for stem, wf in mine.items():
        sh = show(stem, wf)
        rhythm = {"type": "schedule", "schedule": schedule_words(wf)}
        TK.register(c, "flow", stem, sh["goal"], sh["title"], done=sh["done"], rhythm=rhythm, status="scheduled", source=SOURCE,
                    owner="stack" if sh["area"] == "upkeep" else "you")
        r = c.execute("select id, kind, rhythm, status, title from tasks where door='flow' and ref=?", (stem,)).fetchone()
        occs, _ = runs(c, wf)
        want = {"kind": sh["kind"], "rhythm": rhythm, "title": sh["title"],
                "status": "running" if occs and occs[0]["status"] == "running" else "scheduled"}
        have = {"kind": r["kind"], "rhythm": json.loads(r["rhythm"] or "{}"), "title": r["title"], "status": r["status"]}
        if want != have:
            TK.put(c, r["id"], **{k: v for k, v in want.items() if have[k] != v})
        out.append(r["id"])
    for r in c.execute("select id, ref from tasks where door='flow' and status<>'cancelled'").fetchall():
        if r["ref"] not in mine:
            TK.put(c, r["id"], status="cancelled", error="its workflow is gone from this deployment")
    return out


def folded(c, repo=None, made=None):
    """The ids of the tasks a flow task holds as its steps: the crew duties of its steps and the step service's task of
    each run of its agent steps. They leave the lists; their pages stay."""
    import flows_view as FV
    ids = set()
    for wf in flows(repo, made).values():
        jobs = [p["job"] for p in FV.steps_of(wf) if p.get("job")]
        if jobs:
            ids |= {r[0] for r in c.execute(f"select id from tasks where door='crew' and ref in ({','.join('?' * len(jobs))})", jobs)}
        ids |= {r[0] for r in c.execute("select id from tasks where door='workflow' and ref like ?", (f"n8n:{wf.get('id')}/%",))}
    return ids


def extra(c, t, limit=None):
    """What the board and the task's page add to a flow task: its workflow, its result, its plan, its runs (newest
    first, `limit` of them) and each run's steps, the latest run's steps, its last run and its next."""
    import flows_view as FV
    import n8n_jobs as NJ
    wf = workflow(t["ref"])
    if not wf:
        return {"workflow": None, "area": "research", "plan": [], "runs": [], "steps_of": {}, "steps": [], "last_run": None, "next_run": None, "asks": 0}
    sh = show(t["ref"], wf)
    occs, steps = runs(c, wf)
    last = None
    if occs:
        o = occs[0]
        last = {"id": o["occ"], "status": {"done": "ok"}.get(o["status"], o["status"]), "started": o["started"], "ended": o["ended"],
                "summary": (f"Run {o['occ']}: " if o["occ"] > 1 else "") + (o["result"].splitlines()[0] if o["result"] else o["status"])}
    jobs = [p["job"] for p in FV.steps_of(wf) if p.get("job")]
    nxt = NJ.next_run("crew", jobs[0]) if jobs else None
    shown = occs[:limit] if limit else occs           # cap: list (the board's run history; every run stays in n8n and the step records)
    return {"workflow": str(wf.get("id")), "area": sh["area"], "result_view": sh["result"], "result_href": sh["result_href"], "result_label": sh["result_label"],
            "agent": sh["agent"], "plan": plan_of(wf), "asks": asks(t["ref"]),
            "runs": shown, "steps_of": {str(o["occ"]): steps[o["occ"]] for o in shown},
            "steps": steps[occs[0]["occ"]] if occs else [], "last_run": last, "next_run": nxt}


def run(c, t, post=None):
    """task_run on a flow task: its workflow's Run now webhook (WFL-13), as the canvas's Run now. A workflow that is
    switched off is said so: n8n answers no webhook of an unpublished workflow."""
    import flows as FW
    wf = workflow(t["ref"])
    if not wf:
        raise ValueError("this deployment does not run its workflow")
    if not wf.get("active"):
        raise ValueError(f"its workflow {wf.get('name') or t['ref']} is switched off: switch it on in Workflows (its Active switch), then Run now starts it")
    url = f"{FW.N8N}/webhook/run/{t['ref']}"
    try:
        (post or _post)(url)
    except urllib.error.HTTPError as e:
        raise ValueError(f"n8n did not start it (HTTP {e.code}): is its workflow published in n8n?") from None
    except OSError as e:
        raise ValueError(f"n8n did not answer ({type(e).__name__}): is it running?") from None
    import tasks as TK
    TK.M.event("task", "", f"Task #{t['id']} {t['title']}: Run now started its workflow {wf.get('name') or t['ref']}", title="Tasks")
    return {"task": t["id"], "message": "Started: its steps show here as they run"}


def _post(url):
    req = urllib.request.Request(url, data=b"{}", headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=RUN_TIMEOUT_S) as r:  # nosemgrep: dynamic-urllib-use-detected -- n8n on this machine
        r.read()


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "ops"))
    import sqlite3
    db = sqlite3.connect("/srv/ai/missions/missions.sqlite")
    mine = flows()
    for stem, wf in sorted(workflows().items()):
        print(f"{area_of_workflow(wf):9}  {stem}" + ("  (a task here)" if stem in mine else ""))
    for stem, wf in mine.items():
        occs, steps = runs(db, wf)
        print(f"{stem}: {len(occs)} runs; {schedule_words(wf)}")
        for o in occs[:5]:                            # cap: list (the newest five here; the app shows every one)
            print(f"  run {o['occ']} ({o['execution']}): {o['status']}; " + "; ".join(f"{s['title']} {s['status']}" for s in steps[o["occ"]]))
    sys.exit(0)
