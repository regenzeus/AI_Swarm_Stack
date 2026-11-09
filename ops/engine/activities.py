"""The activities (GEN-22, docs/AI-STACK-PLAN.md WP5, WP6): what the graph runner's blocks do, as the stack does it.

A plan's graph is its run's rows (one node per row, "r<idx>"), made by CD.start as today, so the Orchestrator's
checkpoint, which drops, rewrites or adds rows between waves, changes the graph the run follows. A step runs through
the Conductor's own run_step on its own row: every harness adapter and domain step kind behaves exactly as before (the
prompt and its handed-on results, the budget, the trace, provenance, routing before the first attempt, headroom before
it starts, two attempts, a usage limit or an absent NAS waited out without counting). Only the scheduling moved.

A template's run (a pack's, or home's) gets a task of its own (kind and door "template", so the bridge never starts
it as a plan) with one step row per agent, decision and change block, made by its first such step; each block then runs
through the same run_step, adapters, budget and trace as a plan's step. A pack agent's step carries the agent's own
prompt as its standing instructions; a decision's answer is read for the name of one of its branches.

A step whose work runs elsewhere (a Claude task, a build), or that must wait (a limit, no headroom), answers
{"waiting": why, "again": seconds}: the run sleeps on a durable timer and asks again, holding no slot meanwhile, as the
Conductor's tick looked at waiting steps without a slot. What a step returns is its row's reference ("step:<id>"),
never its output (GEN-36).

    load_graph(ref)       the pinned graph: a plan's from its run's rows, a template's from its file
    step(StepInput)       one step through the Conductor's adapters
    checkpoint(d)         the Orchestrator's look between waves (TRL-08), when the Conductor's rule says it is due
    decision(d)           a gate's or a timeout's question, put where the queue reads it
    remind(d)             a wait's reminder
    finish(d)             the run's end, through the Conductor's finish
"""
import contextvars
import dataclasses
import json
import threading
import time
from pathlib import Path

from temporalio import activity
from temporalio.exceptions import ApplicationError

import conductor as CD
import tasks as TK
import textcap as TC
from engine import graph as G
from engine import roles as RL
from engine.runner import Look, StepInput

BEAT_S = 30                     # a running step tells Temporal it is alive this often (the runner's HEARTBEAT is 2 minutes)
HEADROOM_AGAIN_S = 30           # limit: paces, a step without memory headroom asks again after 30 s (the tick looked every 5 s)
GATES = Path("/srv/ai/state/engine-gates.json")   # the gates and timeouts waiting for a person; the queue reads them (GEN-27)


def _db():
    return CD.M.db()


def rows_graph(c, task, occ):
    """A plan run's graph from its rows: one node per row, its "after" and its loop by row number."""
    nodes = []
    for s in CD.steps(c, task, occ):
        lp = s["loop"] if isinstance(s.get("loop"), dict) else (json.loads(s["loop"]) if s.get("loop") else None)
        nodes.append(G.Node(id=f"r{s['idx']}", block="agent", title=s["title"], after=[f"r{a}" for a in s["after"]],
                            agent=s["agent"] or "", harness=s["harness"] or "", model=s["model"] or "", why=s["why"] or "",
                            loop_to=f"r{lp['to']}" if lp else "", loop_max=int(lp.get("max", 0)) if lp else 0))
    return G.Graph(name=f"task {task}", source="plan", nodes=nodes)


def _row(c, task, occ, node_id):
    idx = int(node_id[1:])
    return next(s for s in CD.steps(c, task, occ) if s["idx"] == idx)


def _beating(fn):
    """Runs fn while a second thread heartbeats the activity, so a 40-minute step is not taken for a lost one."""
    done = threading.Event()
    ctx = contextvars.copy_context()

    def beat():
        while not done.wait(BEAT_S):
            ctx.run(activity.heartbeat)
    threading.Thread(target=beat, daemon=True, name="heartbeat").start()
    try:
        return fn()
    finally:
        done.set()


@activity.defn(name="load_graph")
def load_graph(ref: dict) -> G.Graph:
    if ref.get("kind") == "plan":
        return rows_graph(_db(), int(ref["task"]), int(ref.get("occ") or 1))
    if ref.get("kind") == "template" and ref.get("path"):
        g = G.canonical(Path(ref["path"]).read_text(encoding="utf-8"))
        return dataclasses.replace(g, source=str(ref.get("commit") or ""))
    raise ApplicationError(f"no graph for {TC.cut(json.dumps(ref), 200)}: a plan names its task, a template its file",   # cap: preview
                           non_retryable=True)


def _routable(t, s, agents):
    """The tick's rule: before its first attempt, never away from the owner's choice or a role's own step (TSK-14)."""
    return (s["status"] == "pending" and not s["attempts"] and "(routed:" not in (s["why"] or "") and "(your choice" not in (s["why"] or "")
            and CD.hooks(t).get("routing", True) and not (agents.get(s["agent"]) or {}).get("step_kind"))


TEMPLATE_BLOCKS = ("agent", "branch", "change")   # the blocks of a template that are a step of an agent


def _pack_cards():
    from engine import packs as PK
    out = {}
    for p in PK.load()["packs"]:
        for a in p["agents"]:
            out[a["id"]] = {"id": a["id"], "harness": a["harness"] or "claude-code", "model": a["model"], "prompt": a["prompt"], "pack": p["name"]}
    return out


def template_rows(c, wid, g, item, agents=None):
    """A template run's task and its step rows, made once (keyed by the run's workflow id): -> (task id, {node: idx})."""
    c.execute("create table if not exists engine_template_runs (workflow text primary key, task integer, map text)")
    r = c.execute("select task, map from engine_template_runs where workflow=?", (wid,)).fetchone()
    if r:
        return r["task"], json.loads(r["map"])
    cards = {**(agents or CD.cards()), **_pack_cards()}
    nodes = [n for n in g.nodes if n.block in TEMPLATE_BLOCKS]
    now = CD.now()
    cur = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, "
                    "source, created, updated) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"{g.name}: {item}", TC.cut(f"{g.name} · {item}", 120), g.about or g.name, "template", "template", wid, "[]",   # cap: preview
                     "standard", "auto", json.dumps({"type": "once"}), json.dumps({"template": g.name, "item": item}), "[]", "[]",
                     "running", "engine", now, now))
    tid, mp = cur.lastrowid, {}
    for i, n in enumerate(nodes, 1):
        a = n.agent or (G.BUILDER if n.block == "change" else "")
        card = cards.get(a) or {}
        harness = ("build" if a == G.BUILDER else card["step_kind"] if card.get("step_kind") in G.CARD_STEPS
                   else card.get("harness") or "hermes")
        title = n.title + (f": {n.brief}" if n.brief else "")
        if n.block == "branch":
            title += f" Answer with exactly one of: {', '.join(n.branches)}."
        why = (f"As the agent {a}: {card['prompt']}\n\n" if card.get("prompt") else "") + (n.why or "")
        c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts) "
                  "values (?,?,?,?,?,?,?,?,?,?,?,0)", (tid, 1, i, title, item, a, harness, card.get("model") or "", "[]", why, "pending"))
        mp[n.id] = i
    c.execute("insert or replace into task_occ (task, occ, trigger, started, status) values (?,?,?,?,?)", (tid, 1, "engine", now, "running"))
    c.execute("insert into engine_template_runs (workflow, task, map) values (?,?,?)", (wid, tid, json.dumps(mp)))
    c.commit()
    return tid, mp


def item_row(c, task, base, item):
    """The row of one item of a template block's fan-out: a copy of the block's row with the item, idx base*1000+n."""
    got = c.execute("select idx from task_steps where task=? and idx > ? and idx < ? and item=?", (task, base * 1000, (base + 1) * 1000, item)).fetchone()
    if got:
        return got["idx"]
    n = c.execute("select count(*) from task_steps where task=? and idx > ? and idx < ?", (task, base * 1000, (base + 1) * 1000)).fetchone()[0]
    idx = base * 1000 + n + 1
    c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts) "
              "select task, occ, ?, title, ?, agent, harness, model, after, why, 'pending', 0 from task_steps where task=? and idx=?",
              (idx, item, task, base))
    c.commit()
    return idx


def branch_of(text, names):
    """The branch a decider's answer names: a line that is just a name first, else the first name it mentions."""
    import re
    low = str(text or "").strip().lower()
    for line in low.splitlines():
        w = line.strip(" .:*`'\"")
        if w in [x.lower() for x in names]:
            return next(x for x in names if x.lower() == w)
    hits = sorted((m.start(), x) for x in names for m in [re.search(rf"\b{re.escape(x.lower())}\b", low)] if m)
    return hits[0][1] if hits else low.split()[0] if low.split() else ""


@activity.defn(name="step")
def step(inp: StepInput) -> dict:
    ref = inp.ref or {}
    c = _db()
    if ref.get("kind") == "template":
        g = G.canonical(Path(ref["path"]).read_text(encoding="utf-8")) if ref.get("path") else None
        if g is None:
            raise ApplicationError("a template's run names its file (path)", non_retryable=True)
        task, mp = template_rows(c, inp.run, g, inp.task)
        occ, node_id = 1, f"r{mp[inp.node.id]}"
        if inp.item:                                   # a fan-out's item: a row of its own, made the first time it runs
            node_id = f"r{item_row(c, task, mp[inp.node.id], inp.item)}"
    elif ref.get("kind") == "plan":
        task, occ, node_id = int(ref["task"]), int(ref.get("occ") or 1), inp.node.id
    else:
        raise ApplicationError(f"a step's run is a plan's or a template's, not {ref.get('kind')!r}", non_retryable=True)
    answer = _plan_step(c, task, occ, node_id)
    if inp.node.block == "branch" and answer.get("ref") and not answer.get("waiting"):
        s = _row(c, task, occ, node_id)
        answer["branch"] = branch_of(s["output"], inp.node.branches)
    return answer


def _plan_step(c, task, occ, node_id):
    t = TK.row(c, task)
    agents = CD.cards()
    s = _row(c, task, occ, node_id)
    for _ in range(CD.ATTEMPTS + 2):               # a first attempt, a second, and a look at work elsewhere
        if s["status"] in ("done", "skipped"):
            return {"ref": f"step:{s['id']}", "pass": True, **({"skipped": True} if s["status"] == "skipped" else {})}
        if s["status"] in ("failed", "cancelled"):
            raise ApplicationError(f"step {s['idx']} ({s['agent']}): {s['error'] or s['status']}", non_retryable=True)
        rest = CD.resting.get(s["id"], 0) - time.time()
        if rest > 0:                                # a usage limit or an absent NAS: waited out, no attempt
            return {"waiting": s["waiting_for"] or "a pause", "again": int(rest) + 1}
        if s["status"] == "waiting" and s["harness"] not in CD.WAITS:
            return {"waiting": s["waiting_for"] or "its work elsewhere"}
        if s["status"] in ("pending", "running"):
            if _routable(t, s, agents):
                s = CD.routed(c, t, s, agents)
            why = CD.headroom(s)
            if why:                                 # not enough memory free now: it waits, it does not fail
                if s["waiting_for"] != why:
                    CD.put(c, s["id"], waiting_for=why)
                return {"waiting": why, "again": HEADROOM_AGAIN_S}
            CD.put(c, s["id"], status="running")    # claimed, as the tick claims it
            s = {**s, "status": "starting"}
        _beating(lambda s=s: CD.run_step(c, t, s, CD.steps(c, task, occ), agents))
        s = _row(c, task, occ, node_id)
        if s["status"] == "waiting":
            return {"waiting": s["waiting_for"] or "its work elsewhere"}
        if s["harness"] == "check" and s["status"] == "pending" and not s["error"] and not s["waiting_for"]:
            return {"ref": f"step:{s['id']}", "pass": False, "problems": 1}     # the check sent its work back (TRL-08)
    raise ApplicationError(f"step {s['idx']} did not settle after its attempts ({s['status']})", non_retryable=True)


@activity.defn(name="checkpoint")
def checkpoint(d: dict) -> Look:
    """The Orchestrator's look between waves (TRL-08), under the Conductor's own rule (between_waves) and code."""
    ref = d.get("ref") or {}
    if ref.get("kind") != "plan":
        return Look(changed=False)
    c = _db()
    task, occ = int(ref["task"]), int(ref.get("occ") or 1)
    t = TK.row(c, task)
    ss = CD.steps(c, task, occ)
    if not CD.between_waves(t, ss):
        return Look(changed=False)
    before = [(s["idx"], s["status"], s["title"]) for s in ss]
    try:
        _beating(lambda: CD.checkpoint(c, t, ss))
    except Exception as e:                          # a failed look changes nothing: the plan goes on as it was
        CD.M.log(f"engine: task {task}: checkpoint: {type(e).__name__}: {e}")
        return Look(changed=False)
    after = CD.steps(c, task, occ)
    if [(s["idx"], s["status"], s["title"]) for s in after] == before:
        return Look(changed=False)
    return Look(changed=True, graph=rows_graph(c, task, occ), skipped=[f"r{s['idx']}" for s in after if s["status"] == "skipped"])


@activity.defn(name="decision")
def decision(d: dict) -> dict:
    """A gate's or a timeout's question for a role; written once per run and node, so a run that continued as new and
    asks again does not ask twice. Answers the role's people (GEN-27), so the run knows whose answer counts."""
    GATES.parent.mkdir(parents=True, exist_ok=True)
    have = json.loads(GATES.read_text()) if GATES.is_file() else []
    key = f"{d['run']}/{d['node']}"
    if not any(g.get("key") == key for g in have):
        have.append({**d, "key": key, "asked": time.strftime("%Y-%m-%dT%H:%M:%S")})
        tmp = GATES.with_suffix(".tmp")
        tmp.write_text(json.dumps(have, ensure_ascii=False, indent=1))
        tmp.replace(GATES)
    return {"queued": True, "key": key, "people": RL.people(d.get("role") or "")}


@activity.defn(name="remind")
def remind(d: dict) -> dict:
    CD.M.event("task", "", f"Reminder {d.get('number')} for {d.get('for')} on {d.get('key')} (task {d.get('task')})", title="Tasks")
    return {"sent": True}


@activity.defn(name="command")
def command(d: dict) -> dict:
    """A Command block's job at its place (GEN-22): submitted to the worker of that place, waited for with a heartbeat;
    its files are kept as artifacts (GEN-29), and only their ids come back."""
    from engine import artifacts as AR
    from engine import packs as PK
    from engine import places as PL
    spec = next((j["spec"] for p in PK.load()["packs"] for j in p["jobs"] if j["kind"] == d["kind"]), None)
    values = {k: v for k, v in (d.get("values") or {}).items() if k != "tracker"}
    try:
        r = PL.run_job(d["place"], d["kind"], values, spec=spec, beat=activity.heartbeat, timeout=int(STEP_S))
    except PL.Refused as e:
        return {"refused": True, "why": str(e)}
    arts = [AR.put(p, task=d.get("task", ""), step=d.get("node", ""), run=d.get("run", ""), commit=(d.get("ref") or {}).get("commit", ""))["id"]
            for p in r.get("artifacts") or []]
    if r["status"] != "done":
        return {"refused": True, "why": f"{d['kind']} at {d['place']}: {r['status']}: {r.get('error') or ''}".strip(": "), "artifacts": arts}
    return {"pass": True, "ref": f"job:{d['place']}/{r['rid']}", "artifacts": arts}


@activity.defn(name="tracker_write")
def tracker_write(d: dict) -> dict:
    """A Tracker block's write (GEN-25): in shadow kept for the owner, live written once whatever the retries."""
    from engine import trackers as TR
    t = d.get("tracker") or next((x["name"] for x in TR.config()["trackers"]), "")
    return TR.write({**d, "tracker": t})


@activity.defn(name="finish")
def finish(d: dict) -> dict:
    """The run's end. A plan's, and a template's that ran steps, go through the Conductor's finish: the result file in
    the vault, the task's status, the provenance, the event and the message, exactly as before. A cancelled run was
    closed by CD.cancel already."""
    ref = d.get("ref") or {}
    if d.get("status") == "cancelled":
        return {"finished": False}
    c = _db()
    if ref.get("kind") == "template":
        c.execute("create table if not exists engine_template_runs (workflow text primary key, task integer, map text)")
        r = c.execute("select task from engine_template_runs where workflow=?", (activity.info().workflow_id,)).fetchone()
        if not r:
            return {"finished": False}                 # a template that ran no agent's step has no task of its own
        t = TK.row(c, r["task"])
        CD.finish(c, t, CD.steps(c, t["id"], 1), d.get("status") in ("done", "stopped"))
        return {"finished": True, "task": t["id"]}
    if ref.get("kind") != "plan":
        return {"finished": False}
    t = TK.row(c, int(ref["task"]))
    ss = CD.steps(c, t["id"], int(ref.get("occ") or 1))
    CD.finish(c, t, ss, d.get("status") == "done")
    return {"finished": True}


ALL = [load_graph, step, checkpoint, decision, remind, command, tracker_write, finish]
STEP_S = 40 * 60                # the runner's STEP_TIMEOUT: a job waited for longer is failed with the reason
