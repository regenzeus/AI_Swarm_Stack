"""WFL-11: where each n8n workflow stands, for the app's Workflows page, a task's "Where it runs" and an agent's
"In workflows".

The step service (ops/flows.py) keeps a request in flows/pending/ until n8n has its answer and writes the answer to
flows/done/<id>.json. Each request names its workflow and its n8n run (execution). This watcher reads every new request
once, keeps what it says in flows/seen.json (its own file), and writes public/workflows-runs.json: every workflow in
the repository with its schedule in words, its AI Stack steps in the order they run, the agents and crew jobs it uses,
and its newest runs, each with its state, the step it is on, and its steps' states and times.

A run's state is its AI Stack steps' states: a step still pending is running (a question to the owner is waiting), an
answer settles it. What n8n's own nodes do between them is in n8n's execution view, which the app shows on the desk.

    python3 ops/flows_view.py      the view as JSON, from this machine's files
"""
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import flows as FW

STEP = "CUSTOM.aistackStep"
SEEN = FW.ROOT / "seen.json"
OUT = "workflows-runs.json"
RUNS_SHOWN = 10                                      # limit: drops, a workflow's runs past its 10 newest stay out of the app's view; n8n's executions keep every one
SEEN_KEPT = 3000                                     # limit: drops, the oldest steps remembered past 3,000 are forgotten here; n8n keeps its own history (WFL-04)
LOOK_S = 1                                           # how often the pending folder is read: a step lives there at least until the runner has run it
WRITE_S = 10
DAYS = ["Sundays", "Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays"]
OPEN = ("running", "waiting")
BAD = ("failed", "refused", "cancelled")

M = None                                             # ops/missions.py, set by start()


def iso(ts):
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def cron_words(e):
    """A five-field cron expression in the owner's words where it is a common one; else the expression itself."""
    f = str(e).split()
    if len(f) != 5:
        return str(e)
    mi, h, dom, mon, dow = f
    if mon != "*" or (dom != "*" and not (dom.isdigit() and dow == "*" and mi.isdigit() and h.isdigit())):
        return str(e)
    if dom != "*":
        return f"monthly on day {int(dom)}, {int(h):02d}:{int(mi):02d}"
    if mi == h == dow == "*":
        return "every minute"
    if dow == "*" and h == "*" and mi.isdigit():
        return f"hourly at :{int(mi):02d}"
    if dow == "*" and h == "*" and mi.startswith("*/") and mi[2:].isdigit():
        return f"every {int(mi[2:])} minutes"
    if dow == "*" and h.startswith("*/") and h[2:].isdigit() and mi.isdigit():
        return f"every {int(h[2:])} hours"
    if mi.isdigit() and h.isdigit():
        at = f"{int(h):02d}:{int(mi):02d}"
        if dow == "*":
            return f"daily {at}"
        if dow.isdigit():
            return f"{DAYS[int(dow) % 7]} {at}"
        if dow == "1-5":
            return f"weekdays {at}"
    return str(e)


def schedule_of(wf):
    """-> how the workflow starts, in words: its schedule, "when called" (a webhook), "on an event" (another trigger),
    or "by hand"."""
    nodes = wf.get("nodes") or []
    for n in nodes:
        if n.get("type") == "n8n-nodes-base.scheduleTrigger":
            iv = (((n.get("parameters") or {}).get("rule") or {}).get("interval") or [{}])[0]
            if iv.get("field") == "cronExpression":
                return cron_words(iv.get("expression", ""))
            every = next((v for k, v in iv.items() if k.endswith("Interval")), 1)
            return f"every {every} {iv.get('field') or 'days'}" if every != 1 else f"every {(iv.get('field') or 'days').rstrip('s')}"
    if any(n.get("type") == "n8n-nodes-base.webhook" for n in nodes):
        return "when called"
    if any("trigger" in str(n.get("type", "")).lower() and "manual" not in str(n.get("type", "")).lower() for n in nodes):
        return "on an event"
    return "by hand"


def steps_of(wf):
    """The workflow's AI Stack steps in the order they run: along its connections from its first nodes, then any that
    no connection reaches, left to right."""
    nodes = {n["name"]: n for n in wf.get("nodes") or [] if n.get("name")}
    conn = wf.get("connections") or {}
    nxt = {a: [c["node"] for outs in (v.get("main") or []) for c in (outs or []) if c.get("node") in nodes] for a, v in conn.items()}
    fed = {b for bs in nxt.values() for b in bs}
    order, todo = [], [n for n in nodes if n not in fed]
    while todo:
        n = todo.pop(0)
        if n in order:
            continue
        order.append(n)
        todo += nxt.get(n, [])
    order += sorted((n for n in nodes if n not in order), key=lambda n: (nodes[n].get("position") or [0, 0])[0])
    out = []
    for name in order:
        n = nodes[name]
        if n.get("type") != STEP:
            continue
        p = n.get("parameters") or {}
        s = {"name": name, "title": p.get("title") or name, "kind": p.get("kind") or "agent"}
        for k in ("agent", "job"):
            if p.get(k):
                s[k] = str(p[k])
        if p.get("task") not in (None, ""):
            s["task"] = int(p["task"])
        out.append(s)
    return out


def look(seen, pending=None):
    """Every new request in the pending folder that names its workflow and run -> seen[id]. -> how many were new."""
    new = 0
    for f in sorted(Path(pending or FW.PENDING).glob("*.json")):
        rid = f.stem
        if rid in seen or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid):
            continue
        try:
            req, at = json.loads(f.read_text()), f.stat().st_mtime
        except (OSError, ValueError):
            continue                                 # being written, or gone already: looked at again, or n8n has it
        if not isinstance(req, dict) or not req.get("workflow") or not req.get("execution"):
            continue
        rec = {"workflow": str(req["workflow"]), "execution": str(req["execution"]), "kind": req.get("kind") or "agent",
               "title": str(req.get("title") or ""), "started": iso(at)}
        for k in ("agent", "job", "task"):
            if req.get(k) not in (None, ""):
                rec[k] = req[k]
        seen[rid] = rec
        new += 1
    if len(seen) > SEEN_KEPT:                        # limit: drops, SEEN_KEPT above
        for rid in sorted(seen, key=lambda r: seen[r]["started"])[:len(seen) - SEEN_KEPT]:
            del seen[rid]
    return new


def state_of(rid, rec, done=None):
    """-> (state, ended) of one step: its answer's, or running (waiting, for a question) while it has none."""
    f = Path(done or FW.DONE) / f"{rid}.json"
    try:
        a, at = json.loads(f.read_text()), f.stat().st_mtime
    except (OSError, ValueError):
        return ("waiting" if rec.get("kind") == "ask" else "running"), None
    st = a.get("status") or "done"
    return ("done" if st in ("done", "skipped") else st), iso(at)


def runs(seen, done=None):
    """-> {workflow id: [run, newest first]}; a run is one n8n execution with the steps the stack ran for it."""
    by = {}
    for rid, rec in seen.items():
        st, end = state_of(rid, rec, done)
        step = {"title": rec["title"] or rec["kind"], "kind": rec["kind"], "state": st, "started": rec["started"], "ended": end}
        for k in ("agent", "job", "task"):
            if k in rec:
                step[k] = rec[k]
        by.setdefault(rec["workflow"], {}).setdefault(rec["execution"], []).append(step)
    out = {}
    for wid, execs in by.items():
        rs = []
        for ex, steps in execs.items():
            steps.sort(key=lambda s: s["started"])
            live = [s for s in steps if s["state"] in OPEN]
            state = ("waiting" if any(s["state"] == "waiting" for s in live) else "running" if live
                     else "failed" if any(s["state"] in BAD for s in steps) else "done")
            ends = [s["ended"] for s in steps if s["ended"]]
            rs.append({"execution": ex, "state": state, "on": (live[0] if live else steps[-1])["title"], "started": steps[0]["started"],
                       "ended": None if live or not ends else max(ends), "steps": steps})
        out[wid] = sorted(rs, key=lambda r: r["started"], reverse=True)
    return out


def view(repo=None, seen=None, done=None, made=None):
    """-> {"generated", "workflows": [{"id", "name", "active", "schedule", "for", "steps", "agents", "crew", "runs", "runs_total"}]};
    the repository's workflows and those the runner made since the last export (ops/n8n_jobs.py)."""
    import n8n_jobs as NJ
    rs = runs(seen if seen is not None else load(), done)
    out = []
    for _, w in sorted(NJ.workflows(repo or FW.REPO_WORKFLOWS, made if made is not None else NJ.MADE).items(), key=lambda x: x[1]["file"]):
        wf, p = w["wf"], Path(w["file"])
        try:
            kind, key = NJ.target(wf)
        except (ValueError, KeyError, TypeError):
            continue
        steps, mine = steps_of(wf), rs.get(str(wf.get("id")), [])
        out.append({"id": str(wf.get("id")), "name": wf.get("name") or p.stem, "active": bool(wf.get("active")),
                    "schedule": schedule_of(wf), "for": f"{kind}:{key}" if kind else "", "steps": steps,
                    "agents": sorted({s["agent"] for s in steps if s.get("agent")}), "crew": sorted({s["job"] for s in steps if s.get("job")}),
                    "runs": mine[:RUNS_SHOWN], "runs_total": len(mine)})   # cap: list, RUNS_SHOWN above; runs_total counts every one
    return {"generated": iso(time.time()), "workflows": out}


def load(path=None):
    try:
        d = json.loads(Path(path or SEEN).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save(seen, path=None):
    p = Path(path or SEEN)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen, ensure_ascii=False))
    tmp.replace(p)


def write(public, seen):
    out = Path(public) / OUT
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(view(seen=seen), ensure_ascii=False))
    tmp.replace(out)


def worker():
    seen, wrote = load(), 0.0
    while not M.stop.is_set():
        try:
            new = look(seen)
            if new:
                save(seen)
            if new or time.time() - wrote > WRITE_S:
                wrote = time.time()
                write(M.PUBLIC, seen)
        except Exception as e:                       # logged; the pages show the last view meanwhile
            M.log(f"flows_view: {type(e).__name__}: {e}")
        M.stop.wait(LOOK_S)


def start(m):
    global M
    M = m
    threading.Thread(target=worker, daemon=True, name="flows-view").start()


if __name__ == "__main__":
    print(json.dumps(view(), indent=1, ensure_ascii=False))
