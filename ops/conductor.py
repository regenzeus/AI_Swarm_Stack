"""The Conductor (TSK-05 to TSK-09; phase 2 of docs/SWARM-ROADMAP.md): it runs a task's plan graph. Each step is one
agent's work on that agent's own harness and model; a step starts when every step it waits for has finished, steps
that wait for nothing run at the same time (at most SLOTS), and every step is recorded before and after it runs, so a
restart of the runner resumes the task at its first unfinished step and never runs a finished one again.

Every task the intake plans reaches the Conductor (TSK-21, docs/SWARM-DESIGN.md): one-off and scheduled, one step
or many, coding work as a build step and code questions as Claude steps, a briefing as the Topic Desk's plan and a
price watch as checks of its shopping agent (whose purchases stay its own runs, after the owner's approval). A task runs
in **occurrences**: a one-off task once, a scheduled one at once and then each time its n8n workflow starts it (WFL-09,
ops/flows.py run_task), an event-triggered one each time its trigger fires (the event is in every step's prompt); each
occurrence copies the plan (the template) into its own steps (TSK-22) and is judged against the definition of done
(ops/staffing.py). A plan step with "each": [...]
fans out into one step per item, run in parallel as headroom allows; the steps after it get every result.

Harness adapters, one contract (run the step's prompt as its agent, give back its answer or say it is waiting):
  hermes       one turn of the agent's Hermes profile (hermes -z), under the step's run in the runtime record
  claude-code  a read-only Claude task in the task's repository; the step waits for it, also across restarts
  build        a builder assignment; the step waits for the build, its checks and the owner's deploy tap
  python       one model call on the agent's own key
  opencode     one `opencode run` in a throwaway container on the internal network (the gateway only), the card's model
               and key, the task's repository read-only, no shell, edits or web; its tool and model calls recorded
  wiki         a refinement's findings folded into its wiki (mission_extras.compile_into), its page first
Other modules add their own (TSK-36, DOMAINS, loaded by ops/stepkinds.py, which refuses a harness two of them claim):
  changes      a change request's judge, reviewers, prober, delivery and scribe, and what a task of kind change does differently
  shop_steps   shop: a check of a price watch's shopping agent (ops/shopping.py research: offers, a proposal or watching)
  desk_steps   desk-collect, desk-write, desk-alert, deliver: the Topic Desk's steps of a briefing (ops/desk.sh, the desk's
               container) and its delivery
  tax          tax-read: the tax desk's reader, each paper one turn of the tax card's Hermes profile on ChatGPT (TAX-02)
A step starts only with headroom (TSK-08): the memory its harness needs available on the PC (NEED_GB) and its
subscription below its usage limit; otherwise it waits and the board says why.

What each step used and made (TSK-23) is recorded when it ends and again when the run ends (ops/provenance.py),
and the run's swarm map is written whenever it changes (public/maps/<task>.<occ>.json, TSK-24).

The trace (TSK-09): an occurrence is one run in the runtime record (task:<id>, then task:<id>.2, .3 ...), each step a
run inside it (task:<id>:step:<n>), and the agent's own runs (Hermes', the model calls) inside the step.

  python3 ops/conductor.py gate     the phase 2 gate: a five-step task on three harnesses, the runner restarted
                                    during it; it must finish with no finished step run twice and one trace
  python3 ops/conductor.py triggers the trigger proof (MIS-10, TSK-21): a news and a price-move trigger fire through the
                                    real watcher on a replayed watch result, each starts its task's run under the live
                                    Conductor, and each run finishes, is judged and is one trace
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import yaml

import changes                                   # TSK-36: the modules that add step kinds (DOMAINS)
import desk_steps
import shop_steps
import stepkinds
import tax
import textcap
import textcap as TC
import deployment as DEPLOY                        # this deployment's hosts and paths (deployments/<name>/deployment.env)

ROOT = Path(__file__).resolve().parent.parent
# limit: waits, steps at once: the PC's memory and the subscriptions decide (DEC-24)
SLOTS = 2                                         # steps at once: RAM (16 GB) and the subscriptions decide, as for builds (DEC-24)
# limit: stops, a step that failed twice fails its task with the reason; a limit or a restart is no attempt
ATTEMPTS = 2                                      # a step that fails twice fails its task (a limit or a restart is no attempt)
# limit: drops, the oldest event waiting for one task's next run; said in the activity feed (TSK-21)
QUEUE = 5                                         # cap: list (events waiting for one task's next run; the oldest are dropped, said in the feed)
NEW = "new"                                       # TSK-15: the intake's word for "no agent fits": a temporary agent is written
BUILDER = "builder"                               # its steps run as build assignments
HARNESSES = ("hermes", "claude-code", "python", "opencode")   # the harnesses a step can run on (TSK-07)
CARD_STEPS = ("build", "check")                   # TRL-07, TRL-08: a card's steps are builds in its lane, or the judge's checks
EACH = 50                                         # limit: refuses, a plan fanning out over more names the limit on the task: the pools pace the copies
# limit: stops, fix rounds a check may send back (TRL-08)
LOOP_MAX = 4
BLOCKED = re.compile(r"\A\s*(?:\**\s*)?(?:step \d+ (?:is )?)?BLOCKED\**\s*:\s*\**\s*(.+)", re.I)         # a step that could not do its work says so first (TASK_STEP): it fails,
WRITTEN = ("hermes", "python", "temp", "opencode")   # it is not done (task #104 "done" with no phone tool, 1 Nov 2026)
QUIET = ("Nothing new was chosen", "No price drop")   # a run whose answer starts so found nothing to send: kept, not judged
ALERT_CHARS = 1500                                     # cap: preview (an alert's answer in its message: three lines fit; the task page has all of it)
DESK = Path("/srv/ai/desk")                       # the desk's per-topic folders (ops/desk.sh)
# limit: stops, a step past this counts as failed
STEP_TIMEOUT = 40 * 60
OPENCODE_IMAGE = "aistack/opencode:1.19.4-ua1"    # as ops/onboard.py: the pinned OpenCode with its plugins
OPENCODE_CFG = ROOT / "config/opencode-step.json"  # a step may read, never run, edit or fetch (permission: deny)
CODE = Path(DEPLOY.CODE_DIR)                      # the repositories a task may name (read-only in the step)
SEEN = 6000                                       # of each finished step's result, the checkpoint reads (its prompt stays small)
# limit: drops, the Orchestrator's looks at one run's plan between waves; the run goes on as planned (TRL-08)
CHECKPOINTS = 3
# limit: drops, steps one look may add (its prompt says so); a run's plan stays within MAX_STEPS
ADDS = 3
# limit: drops, steps a checkpoint adds past this; the run's plan changes say so
MAX_STEPS = 12
FINISHED = ("done", "skipped")                    # a step the Orchestrator dropped counts as settled for those after it
checkpoint_ask = None                             # tests: the Orchestrator's answer; else the intake's own key (M.ask_json)
looking = set()                                   # tasks whose checkpoint runs now (a thread; the next tick waits for it)
resting = {}                                      # step id -> when it may try again, after the network or the NAS was away
LIMIT_REST_S = 1800                               # limit: waits (a step at a usage limit tries again after 30 minutes, as missions do)
inflight = set()                                  # steps a job works on now: a waiting step is looked at again each tick, and a slow look must not run twice
HOST = Path("/srv/win-exports/.host/host.json")   # Windows' free memory, written every 30 s by ops/windows/host-probe.ps1
RESULTS = Path("/srv/vault/tasks")                # the finished task's answer, for the vault's search
M = None                                          # ops/missions.py, set by its main()
slots = threading.BoundedSemaphore(SLOTS)
lock = threading.RLock()                          # FND-84: the worker ticks under it and start() takes it again


class Waiting(Exception):
    """The step's agent is working elsewhere (a Claude task): keep the step waiting, check again later."""


class Cancelled(Exception):
    """The step's task was cancelled while the step ran, and the step stopped its work: it ends stopped, never tried again."""


class Reopened(Exception):
    """A check sent its work back (TRL-08): it set the steps to run again itself; the step is not done and not failed."""


def table(c):
    c.execute("""create table if not exists task_steps (id integer primary key, task integer, idx integer, title text,
                 agent text, harness text, model text, after text, why text, status text, output text, error text,
                 waiting_for text, resume text, attempts integer default 0, started text, ended text)""")
    cols = {r[1] for r in c.execute("pragma table_info(task_steps)")}
    for col, decl in (("occ", "integer default 1"), ("item", "text"), ("loop", "text")):   # TSK-22: occurrence, fan-out item; TRL-08
        if col not in cols:
            c.execute(f"alter table task_steps add column {col} {decl}")
    c.execute("create index if not exists task_steps_task on task_steps (task, idx)")
    c.execute("""create table if not exists task_occ (task integer, occ integer, trigger text, started text, ended text, status text,
                 result text, primary key (task, occ))""")
    cols = {r[1] for r in c.execute("pragma table_info(task_occ)")}
    for col, decl in (("event", "text"), ("verdict", "text"), ("judged", "text"), ("tokens", "integer"), ("judgement", "text"), ("cost", "real"),
                      ("window", "text")):
        if col not in cols:                               # TSK-21: the event that started it; TSK-22: its own verdict; TSK-49: its window
            c.execute(f"alter table task_occ add column {col} {decl}")
    c.execute("create table if not exists task_events (id integer primary key, task integer, at text, event text, occ integer)")
    c.execute("create table if not exists step_refs (kind text, ref text, task integer, primary key (kind, ref))")   # FND-91


def run_of(task, occ=1):
    """The occurrence's run in the runtime record: task:<id> for the first, task:<id>.<n> after it."""
    return f"task:{task}" if (occ or 1) <= 1 else f"task:{task}.{occ}"


def occ_of(c, task):
    return c.execute("select max(coalesce(occ, 1)) from task_steps where task=?", (task,)).fetchone()[0] or 0   # rows before occurrences: 1


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def put(c, sid, **kw):
    if "resume" in kw and not isinstance(kw["resume"], str) and kw["resume"] is not None:
        kw["resume"] = json.dumps(kw["resume"])
    c.execute(f"update task_steps set {', '.join(f'{k}=?' for k in kw)} where id=?", (*kw.values(), sid))
    c.commit()


def steps(c, task, occ=None):
    """The steps of one occurrence, the latest by default."""
    occ = occ or occ_of(c, task)
    return [dict(r) | {"after": json.loads(r["after"] or "[]"), "resume": json.loads(r["resume"] or "{}")}
            for r in c.execute("select * from task_steps where task=? and coalesce(occ, 1)=? order by idx", (task, occ)).fetchall()]


def cards():
    reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())
    return {a["id"]: a for a in reg["agents"]}


def step_ref(c, kind, ref, task):
    """A build or a Claude task a step started: the board shows it as that step, not as a task of its own (FND-91)."""
    c.execute("insert or ignore into step_refs (kind, ref, task) values (?,?,?)", (kind, str(ref), task))
    c.commit()


# ---------- the plan graph (TSK-05) ----------
def runs_steps(card):
    """Can this agent do a step? Its steps are builds or checks (TRL-07), or its harness has an adapter and a python agent
    has its own key."""
    if card.get("step_kind") in CARD_STEPS:
        return True
    return card.get("harness") in HARNESSES and (card["harness"] != "python" or card.get("key") not in (None, "none"))


def fold_builders(plan):
    """Consecutive builder steps become one build, each a stage of its brief (TRL-10). Every builder step is a build and
    a build that commits nothing fails, so the first trial's plan (read the spec and plan; implement; run the tests and
    fix) failed at its first step though the builder did that work well (trial semver, 1 Nov 2026). A builder step
    whose only predecessor is a builder step that nothing else waits for joins it as its next stage."""
    steps = [dict(p, after=sorted({int(a) for a in p.get("after") or [] if str(a).isdigit()})) for p in plan]
    while True:
        for j, p in enumerate(steps, 1):
            k = p["after"][0] if len(p["after"]) == 1 else 0
            q = steps[k - 1] if 1 <= k <= len(steps) and k != j else None
            if (p.get("agent") != BUILDER or p.get("each") or not q or q.get("agent") != BUILDER or q.get("each")
                    or any(k in s["after"] for n, s in enumerate(steps, 1) if n != j)):
                continue
            stages = (q.get("stages") or [str(q.get("step", "")).strip()]) + [str(p.get("step", "")).strip()]
            joined = {**q, "stages": stages, "step": "; ".join(f"Stage {n}: {s}" for n, s in enumerate(stages, 1)),
                      "why": "; ".join(x for x in (q.get("why"), p.get("why")) if x)}
            out = []
            for n, s in enumerate(steps, 1):
                if n == j:
                    continue
                s = joined if n == k else s
                after = sorted({k if a == j else a for a in s["after"]})
                lp = s.get("loop")
                if isinstance(lp, dict) and str(lp.get("to", "")).isdigit():      # a check that loops to a folded stage loops to the build
                    to = k if int(lp["to"]) == j else int(lp["to"])
                    lp = {**lp, "to": to - (to > j)}
                out.append({**s, "after": [a - (a > j) for a in after], **({"loop": lp} if lp else {})})
            steps = out
            break
        else:
            return steps


def plan_nodes(plan, agents, own_steps=None):
    """The intake's plan -> its nodes, each {title, agent, after (1-based), items, harness, model, why, loop}, or
    ValueError: a step that waits for a step that is not there, an agent that cannot do a step, a loop that is not a
    check's, or a plan with a cycle, is refused."""
    own_steps = own_steps or {}
    n = len(plan)
    for i, p in enumerate(plan, 1):                      # a step that waits for one that is not there: refused before folding
        bad = [a for a in {int(a) for a in p.get("after") or [] if str(a).isdigit()} if not 1 <= a <= n or a == i]
        if bad:
            raise ValueError(f"step {i} waits for step {bad[0]}, which is not another step of the plan")
    plan = fold_builders(plan)
    nodes, n = [], len(plan)
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
        items = TC.limit_items([str(x).strip() for x in p.get("each") or [] if str(x).strip()], EACH, f"items to fan out in step {i}")
        harness = (p["harness"] if p.get("harness") in own_steps.get(a, ()) else "build" if a == BUILDER
                   else card["step_kind"] if card.get("step_kind") in CARD_STEPS else card["harness"])
        lp = p.get("loop")
        if lp is not None:                                 # TRL-08: a check may send failures back to an earlier step
            to, mx = lp.get("to") if isinstance(lp, dict) else None, lp.get("max", 2) if isinstance(lp, dict) else None
            if harness != "check" or not str(to).isdigit() or not 1 <= int(to) < i or not str(mx).isdigit():
                raise ValueError(f"step {i}: only a check loops, back to an earlier step, a few times")
            lp = {"to": int(to), "max": min(int(mx), LOOP_MAX)}
        model = p["model"] if p.get("model") and harness in ("python", "temp") else card.get("model")   # TSK-30: the owner's model where a
        nodes.append({"title": str(p.get("step", "")).strip() or f"Step {i}", "agent": a, "after": after, "items": items or [None],   # step makes its own call
                      "harness": harness, "model": model, "why": str(p.get("why", "")).strip(), "loop": lp})
    _acyclic({i: nd["after"] for i, nd in enumerate(nodes, 1)})
    return nodes


def _acyclic(after):
    """after: step -> the steps it waits for. A cycle is refused, naming it."""
    done = set()

    def visit(i, path):
        if i in path:
            raise ValueError(f"the plan has a cycle: step {' → step '.join(map(str, path[path.index(i):] + [i]))}")
        if i in done:
            return
        for a in after[i]:
            visit(a, path + [i])
        done.add(i)
    for i in after:
        visit(i, [])


def graph(plan, agents=None):
    """The intake's plan -> steps with their dependencies (1-based step numbers in "after"), or ValueError: a step
    that waits for a step that is not there, or a plan with a cycle, is refused (plan_nodes). A plan step
    with "each": [items] becomes one step per item (TSK-22), and a step that waits for it waits for every copy."""
    nodes = plan_nodes(plan, agents or cards(), OWN_STEPS)
    idxs, out = {}, []                                 # plan step -> its steps (one, or one per item)
    for i, nd in enumerate(nodes, 1):
        idxs[i] = list(range(len(out) + 1, len(out) + 1 + len(nd["items"])))
        for k, item in zip(idxs[i], nd["items"]):
            out.append({"idx": k, "title": nd["title"] + (f" — {item}" if item else ""), "item": item, "agent": nd["agent"],
                        "harness": nd["harness"], "model": nd["model"], "why": nd["why"],
                        "after": sorted(x for a in nd["after"] for x in idxs[a]),
                        "loop": {**nd["loop"], "to": idxs[nd["loop"]["to"]][0]} if nd["loop"] else None})
    return out


def start(c, t, trigger="start", event=None):
    """Open the task's next occurrence: copy its plan (the template) into the occurrence's steps and open its run (its
    trace); the worker does the rest. An event that started it is kept with it. -> the task's reference on the board."""
    import runtime as RTM
    table(c)
    plan = t["spec"].get("plan") or []
    if event and t.get("kind") == "briefing" and t["rhythm"].get("type") == "schedule":   # a briefing's alert: the desk's short one, not the whole briefing
        import desk_steps as DS
        plan = DS.alert_plan(t)
    plan = graph(plan)
    win = None if event else window_for(t, dt.datetime.now().astimezone())
    with lock:
        occ = occ_of(c, t["id"]) + 1
        for s in plan:
            c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts, loop) "
                      "values (?,?,?,?,?,?,?,?,?,?,?,0,?)", (t["id"], occ, s["idx"], s["title"], s["item"], s["agent"], s["harness"], s["model"],
                                                             json.dumps(s["after"]), s["why"], "pending", json.dumps(s["loop"]) if s["loop"] else None))
        c.execute("insert or replace into task_occ (task, occ, trigger, started, status, event, window) values (?,?,?,?,?,?,?)",
                  (t["id"], occ, trigger, now(), "running", json.dumps(event, ensure_ascii=False) if event else None,
                   json.dumps(win) if win else None))
        c.commit()
    RTM.start(run_of(t["id"], occ), "conductor", f"Task #{t['id']}: {t['title']}" + (f" · run {occ}" if occ > 1 else "")
              + (f" · {event.get('trigger', 'an event')}" if event else ""), detail=t["goal"] + (f"\n\n{event_text(event)}" if event else ""),
              ref=None)   # the root: its planning runs hang under it (TSK-26)
    mapped(c, t["id"], occ)
    return str(t["id"])


def fire(c, task, ev):
    """An event for a task (its trigger fired, or its shopping agent's price target was reached): the task's next
    occurrence starts with it as soon as no other occurrence of the task runs; until then events wait in order."""
    table(c)
    c.execute("insert into task_events (task, at, event) values (?,?,?)", (int(task), now(), json.dumps(ev, ensure_ascii=False)))
    for r in c.execute("select id, event from task_events where task=? and occ is null order by id desc limit -1 offset ?", (int(task), QUEUE)).fetchall():
        c.execute("update task_events set occ=0 where id=?", (r["id"],))         # 0: dropped, too many waiting
        M.log(f"conductor: task {task}: an event dropped, {QUEUE} newer ones wait: {json.loads(r['event']).get('summary', '')}")
        M.event("task", "", f"Task #{task}: an event was dropped because {QUEUE} newer ones wait for its next run: {json.loads(r['event']).get('summary', '')}", title="Tasks")
    c.commit()


def event_of(c, task, occ):
    r = c.execute("select event from task_occ where task=? and occ=?", (task, occ or 1)).fetchone()
    return json.loads(r["event"]) if r and r["event"] else None


# ---------- a scheduled run's window (TSK-49) ----------
def window_for(t, at):
    """The period an occurrence of a scheduled task covers, when it starts at `at`: back from `at` by its schedule's gap
    (ops/n8n_jobs.py window), in its n8n workflow's time zone, else the runner's. The workflow's schedule wins over the
    task's words, as n8n starts the runs. -> {"start", "end", "tz"} (ISO, to the minute) or None (not on a schedule)."""
    import n8n_jobs as NJ
    if (t.get("rhythm") or {}).get("type") != "schedule":
        return None
    try:
        w = NJ.of("task", t["id"]) or {}
    except Exception:                                     # the workflows cannot be read now: the task's own words
        w = {}
    cron, tz = w.get("cron") or NJ.cron_of_rhythm(t["rhythm"].get("schedule")), w.get("tz") or ""
    span = NJ.window(cron, at, tz) if cron else None
    if not span:
        return None
    return {"start": span[0].isoformat(timespec="minutes"), "end": span[1].isoformat(timespec="minutes"),
            "tz": tz or span[1].tzname() or span[1].strftime("UTC%z")}


def window_of(c, task, occ):
    r = c.execute("select window from task_occ where task=? and occ=?", (task, occ or 1)).fetchone()
    return json.loads(r["window"]) if r and r["window"] else None


def when(iso):
    d = dt.datetime.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b %Y %H:%M}"


def period_text(w):
    """The window in the owner's words, the same in every step, the report and the e-mail: "Mon 2 Nov 2026 08:00 to Mon
    9 Nov 2026 08:00 (Europe/Berlin)"."""
    return f"{when(w['start'])} to {when(w['end'])} ({w['tz']})"


def window_text(w):
    """The window in a step's prompt: every research and writing step of the run covers the same one."""
    return (f"This run covers exactly {period_text(w)}, the end being when the run started. Use only what was published or "
            "happened inside this window (mark anything older as background, with its date), and name this window in your answer.")


def event_text(ev):
    """The event in a step's prompt, as a mission's event run has it."""
    items = "\n".join(f"- {i.get('title', '')} {i.get('url', '')}".rstrip() for i in (ev.get("items") or [])[:4])  # cap: list (as the event's own)
    return f"This run was started by an event: {ev.get('trigger', 'an event')}: {ev.get('summary', '')}" + (f"\n{items}" if items else "")


# ---------- headroom (TSK-08) ----------
WINDOWS_FLOOR_GB = 0.3   # limit: waits, Windows itself this short: nothing starts, whatever WSL holds (the owner's PC comes first)


def free_gb(host=None, meminfo=None, now=None):
    """The PC's room for a step: Windows' own available memory when the host probe is fresh (available, else free from an
    older probe), or more where WSL's VM already holds memory it does not use: a step inside WSL uses that without taking
    anything from Windows (overnight 8 Nov 2026: WSL held 8 GB with 5 GB of it free and never handed it back, Windows had
    0.5 GB, and onboarding waited for hours). With no fresh probe, what WSL has available."""
    text = meminfo if meminfo is not None else open("/proc/meminfo").read()
    mi = {ln.split(":")[0]: int(ln.split()[1]) for ln in text.splitlines() if ln.split(":")[0] in ("MemAvailable", "MemTotal")}
    wsl = mi.get("MemAvailable", 0) / 1048576
    try:
        h = HOST if host is None else host
        if (now or time.time()) - h.stat().st_mtime < 180:
            d = json.loads(h.read_text(encoding="utf-8-sig"))
            win = float(d["ram_available_gb"] if "ram_available_gb" in d else d["ram_free_gb"])   # the default is not read eagerly
            vm = float(d.get("wsl_vm_gb") or 0)
            if not vm or "MemTotal" not in mi or win < WINDOWS_FLOOR_GB:
                return win
            held_free = max(0.0, vm - (mi["MemTotal"] - mi["MemAvailable"]) / 1048576)   # the VM's memory that its own work does not use
            return max(win, min(wsl, held_free))
    except (OSError, ValueError, KeyError):
        pass
    return wsl


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
HANDOFF = 60000        # cap: prompt (the earlier results in one step's prompt; past it each is cut, marked, with where the whole is)
HANDOFF_MIN = 4000     # the least of one result a step sees before its reference
ARG_BYTES = 120 * 1024                 # one command-line argument holds 128 KiB (Linux MAX_ARG_STRLEN): a prompt is refused before that
WHOLE_CONTEXT = {"claude", "build"}    # these take the earlier results apart from the brief (FND-99), whole


def result_file(t, x):
    """An earlier step's whole result as a vault file (tasks/), for a step that reads it by reference (MEM-15)."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    f = RESULTS / f"{t['id']}-{x.get('occ') or 1}-step-{x['idx']}.md"
    if not f.exists() or f.stat().st_size != len((x["output"] or "").encode()):
        f.write_text(x["output"] or "")
    return f


def handoff(t, s, prev):
    """MEM-15: the results a step builds on. Each whole while they fit HANDOFF together; past it each gets its share,
    marked, with where the whole result is: a file in its work folder (OpenCode) or in the vault (/vault/tasks/, read
    with the vault tools). A Claude or build step takes them whole apart from its brief."""
    whole = lambda x: f"### Step {x['idx']}: {x['title']} ({x['agent']})\n{x['output']}"   # noqa: E731
    if s.get("harness") in WHOLE_CONTEXT or sum(len(x["output"] or "") for x in prev) <= HANDOFF:
        return "\n\n".join(whole(x) for x in prev)
    share = max(HANDOFF_MIN, HANDOFF // len(prev))
    parts = []
    for x in prev:
        out = x["output"] or ""
        if len(out) <= share:
            parts.append(whole(x))
            continue
        f = result_file(t, x)
        where = (f"/step/results/{f.name} in your work folder" if s.get("harness") == "opencode"
                 else f"the vault file tasks/{f.name} (/vault/tasks/{f.name}): read it whole with your vault tools before you rely on its end")
        parts.append(f"### Step {x['idx']}: {x['title']} ({x['agent']})\n" + TC.cut(out, share, f"the whole result ({len(out):,} characters) is {where}"))  # cap: prompt
    return "\n\n".join(parts)


def prompt_of(t, s, all_steps, agents, purpose=None, memory=True):
    import prompts as P
    prev = [x for x in all_steps if x["idx"] in s["after"]]
    ins = (agents.get(s["agent"]) or {}).get("instructions") or []
    p = P.text("shared", "TASK_STEP").format(
        agent=s["agent"], purpose=purpose or (agents.get(s["agent"]) or {}).get("purpose", "a temporary agent written for this step"), goal=t["goal"], n=len(all_steps), i=s["idx"], step=s["title"],
        done="\n".join(f"- {d}" for d in t["done"]),
        before=handoff(t, s, prev) or "(this step waits for none)",
        last="yes" if not any(s["idx"] in x["after"] for x in all_steps) else "no")
    mem = step_memory(t, s, prev) if memory else ""
    if ins or mem:                                       # TRL-07: a role's rules travel with every step it does
        q = P.Prompt(p + (f"\n\n## Your standing instructions ({s['agent']}'s card)\n" + "\n".join(f"- {x}" for x in ins) if ins else "")
                     + (f"\n\n{mem}" if mem else ""))
        q.ref, q.fills = p.ref, getattr(p, "fills", {})
        return q
    return p


def step_memory(t, s, prev):
    """MEM-33: what the stack remembers for this step, chosen from its own inputs (the goal, the step, the start of each result it
    builds on) through the memory stack, under the step's run. A run goes on without it, and is told."""
    try:
        import memstack as MS
        card = s["agent"] if s["agent"] in MS.registry() else None
        task = "\n".join([t["goal"], s["title"], *[(x.get("output") or "")[:600] for x in prev]])  # cap: parse (the words the memory is chosen by; the step gets every result whole)
        return MS.opening(f"crew:{s['agent']}", kind="task", task=task, card=card, role=None if card else "default",
                          run=f"{run_of(t['id'], s.get('occ') or 1)}:step:{s['idx']}", repo=(t.get("spec") or {}).get("repo"))
    except Exception as e:
        return f"## Memory for this run\nIt could not be built this time ({type(e).__name__}: {e}); the run goes on without it."


BEFORE = "\n\n## Results of the steps before yours\n"
OWN_RULES = "\n\n## Your standing instructions"


def split_brief(prompt):
    """A step's prompt as (its brief, the earlier steps' results): the results can be long (a whole requirements list) and
    go where the harness takes long text; the standing instructions stay in the brief (FND-99)."""
    head, _, rest = prompt.partition(BEFORE)
    results, _, rules = rest.partition(OWN_RULES)
    return head + (OWN_RULES + rules if rules else ""), (BEFORE.lstrip("\n") + results) if rest else ""


def run_hermes(c, t, s, prompt, card):
    import runtime as RTM
    import swarm_client as SW
    prof = SW.PROFILE.get(s["agent"])
    prompt = f"[run: {run_of(t['id'], s.get('occ') or 1)}:step:{s.get('idx')}]\n{prompt}"   # FND-114: Hermes' resident
    # gateway gets no AISTACK_REF from `docker exec`; the run's title (the prompt's head) names its step exactly
    if len(str(prompt).encode()) > ARG_BYTES:            # FND-104: refused with its size, not lost to "argument list too long"
        raise RuntimeError(f"the step's prompt is {len(str(prompt).encode()):,} bytes; one command-line argument holds "
                           f"{ARG_BYTES:,}: its brief or the standing instructions are too long")
    p = subprocess.run(["docker", "exec", "-u", "hermes", *RTM.env_args(), M.HERMES, "timeout", str(STEP_TIMEOUT), "hermes",
                        *(["-p", prof] if prof else []), "-z", prompt], capture_output=True, text=True, timeout=STEP_TIMEOUT + 60)
    out = p.stdout.strip()
    if p.returncode or not out:
        raise RuntimeError(f"Hermes ({prof or 'main'}) ended with exit {p.returncode}: {TC.tail((p.stderr or out).strip(), 600)}")  # cap: preview
    return out


def run_claude(c, t, s, prompt, card):
    """A read-only Claude task; its id is the step's resume point, so a restart waits for it instead of asking again."""
    import claude_tasks as CT
    tid = s["resume"].get("claude_task")
    if not tid:
        head, context = split_brief(str(prompt))
        tid = CT.handle({"action": "claude_task", "question": TC.fit(head, 19000), "mode": "ask", "repo": t["spec"].get("repo") or "",  # cap: api (its question limit)
                         "context": context,
                         "source": f"{run_of(t['id'], s.get('occ') or 1)}:step:{s['idx']}"}, c)["id"]   # TSK-09: its run sits in the step's
        put(c, s["id"], resume={"claude_task": tid})
        step_ref(c, "claude", tid, t["id"])
        M.event("task", "", f"Task #{t['id']} step {s['idx']} asked Claude (task #{tid})", title="Tasks")
    r = c.execute("select status, answer, error from claude_tasks where id=?", (tid,)).fetchone()
    if not r or r["status"] in ("queued", "running", "waiting"):
        raise Waiting(f"Claude task #{tid}")
    if r["status"] != "done":
        put(c, s["id"], resume={})                        # a failed Claude task is asked again on the next attempt
        raise RuntimeError(f"Claude task #{tid} {r['status']}: {r['error'] or ''}")
    return r["answer"]


BUILD_DONE, BUILD_FAILED = ("deployed", "merged"), ("failed", "rolled_back", "reverted", "rejected")


def run_build(c, t, s, prompt, card):
    """A builder assignment in the task's repository; its id is the resume point. The step waits while the build works,
    is checked and waits for the owner's review and deploy tap (the builder's own approvals, DEC-34)."""
    import builds as B
    bid = s["resume"].get("build")
    if not bid:
        if not t["spec"].get("repo"):
            raise RuntimeError("a build step needs the task's repository; the intake asks for it")
        prompt, context = split_brief(str(prompt))       # FND-99: the earlier results apart, past the description's limit
        fb = s["resume"].get("feedback")                 # TRL-08: a check sent this back with what failed
        if fb:
            prompt += ("\n\n## Fix round " + str(s["resume"].get("round", 1)) + ": the checks failed after the last build\n"
                       "Make the failing tests pass without weakening or deleting them; then run them all.\n\n```\n" + fb + "\n```")
        if card.get("lane") and hooks(t).get("lane", True):
            prompt += ("\n\n## Your lane\nChange only files under: " + ", ".join(card["lane"]) + ". A change anywhere else fails this step.")
        res = B.handle({"action": "build_assign", "repo": t["spec"]["repo"], "title": f"{s['agent']}: {t['title']}"[:80], "description": prompt, "context": context,  # cap: id
                         "source": f"{run_of(t['id'], s.get('occ') or 1)}:step:{s['idx']}",       # FND-101: its run nests in the step's
                         **(hooks(t)["assign"](t, s) if "assign" in hooks(t) else {})}, c)
        bid = res.get("build") or res.get("id")
        put(c, s["id"], resume={**s["resume"], "build": bid})   # its feedback stays for an attempt after this one
        step_ref(c, "build", bid, t["id"])
        M.event("task", "", f"Task #{t['id']} step {s['idx']} became build #{bid}", title="Tasks")
    r = c.execute("select * from builds where id=?", (bid,)).fetchone()
    if r and r["status"] in BUILD_DONE:
        return f"Build #{bid} {r['status']}.\n\n{r['summary'] or ''}".strip()
    if r and r["status"] == "review" and "built" in hooks(t):                 # its task kind takes it from here
        return hooks(t)["built"](c, t, s, r)
    if r and r["status"] == "review" and card.get("lane"):                    # TRL-07: a role's build stays in its lane
        outside = [f[-1] for f in json.loads(r["files"] or "[]") if not any(f[-1].startswith(p) for p in card["lane"])]
        if outside:
            B.handle({"action": "build_reject", "id": bid}, c)
            put(c, s["id"], resume={})
            raise RuntimeError(f"build #{bid} of {s['agent']} changed {', '.join(outside[:5])}: outside its lane ({', '.join(card['lane'])})")
    if r and r["status"] == "review" and str(t.get("source") or "").startswith("trial:"):   # a trial's build: into its scratch repository
        if str(t["spec"].get("repo") or "").startswith("trial-"):                         # so the next stage sees it (TRL-05)
            sha = B.trial_merge(c, dict(r))
            if not sha:
                put(c, s["id"], resume={})
                raise RuntimeError(f"build #{bid} does not merge onto the trial's main (it conflicts with a build merged since)")
            return f"Build #{bid} merged into the trial repository's main as {sha[:8]} (never deployed).\n\n{r['summary'] or ''}".strip()
        return (f"Build #{bid} is ready (a trial: its answer key scores branch {r['branch']} at {r['head']}; it is never "   # scored, never merged
                f"merged or deployed).\n\n{r['summary'] or ''}").strip()
    if r and r["status"] in BUILD_FAILED:
        put(c, s["id"], resume={k: v for k, v in s["resume"].items() if k != "build"})   # the next attempt assigns a new build
        raise RuntimeError(f"build #{bid} {r['status']}: {r['error'] or ''}")
    raise Waiting(f"build #{bid}: " + ("waits for your review" if r and r["status"] == "review" else (r["status"] if r else "starting")))


def run_check(c, t, s, prompt, card):
    """The judge's step (TRL-08): every test of the task's repository, on its main as the steps before left it, in the
    builder's sandbox. Passing: the counts. Failing with fix rounds left: the step it loops to runs again with the failures
    in its brief, and this check waits for it again. Out of rounds: the failures, for the steps after it and the owner."""
    import builds as B
    repo = t["spec"].get("repo")
    if not repo:
        raise RuntimeError("a check needs the task's repository")
    path = B.clone(repo)
    main = B.default_branch(path)
    B.git(path, "fetch", "-q", "origin")
    B.git(path, "checkout", "-q", main)
    B.git(path, "reset", "-q", "--hard", f"origin/{main}")
    out = B.sandbox_checks(repo, None, timeout=1800)
    ok = B.checks_passed(out)                             # one rule with the builds (RUN-R14)
    counts = ", ".join(f"{n} {w}" for n, w in re.findall(r"\b(\d+) (passed|failed|errors?|skipped)\b", out)[-4:]) or "no test counts"
    lp = json.loads(s.get("loop") or "null") if isinstance(s.get("loop"), str) else s.get("loop")
    rounds = s["resume"].get("rounds", 0)
    if not ok and lp and rounds < lp["max"]:
        target = next((x for x in steps(c, t["id"], s.get("occ")) if x["idx"] == lp["to"]), None)
        if target:
            tail = TC.tail(out, 6000)  # cap: prompt (the end of the test run names what fails)
            put(c, target["id"], status="pending", attempts=0, error=None, waiting_for=None, resume={"feedback": tail, "round": rounds + 1})
            put(c, s["id"], status="pending", attempts=0, waiting_for=None, resume={"rounds": rounds + 1},
                after=json.dumps(sorted(set(s["after"]) | {lp["to"]})))
            M.event("task", "", f"Task #{t['id']}: the checks fail ({counts}); step {lp['to']} fixes it, round {rounds + 1} of {lp['max']}", title="Tasks")
            raise Reopened(f"sent back to step {lp['to']} (round {rounds + 1} of {lp['max']}): {counts}")
    verdict = "All checks pass" if ok else f"The checks still fail after {rounds} fix round{'s' if rounds != 1 else ''}"
    return f"{verdict}: {counts}.\n\n```\n{TC.tail(out, 4000)}\n```"  # cap: preview (the step's output; the run's log keeps all of it)


def spent(c, t, s):
    """TRL-11: what the task's run has used: hours since it started, and tokens (its trace's model calls, and the builds'
    whose runs are not in the trace)."""
    import staffing as ST
    occ = s.get("occ") or 1
    o = c.execute("select started from task_occ where task=? and occ=?", (t["id"], occ)).fetchone()
    hours = (dt.datetime.now().astimezone() - dt.datetime.fromisoformat(o["started"])).total_seconds() / 3600 if o and o["started"] else 0
    tokens = sum(u["in"] + u["out"] for u in ST.usage_of(run_of(t["id"], occ)).values())
    inside = ST.runs_of(run_of(t["id"], occ))           # FND-101: a build whose run is in the trace is counted there, once
    refs = [r["ref"] for r in c.execute("select ref from step_refs where kind='build' and task=?", (t["id"],))
            if not any(x.startswith(f"build:{r['ref']}:") for x in inside)]
    if refs:
        tokens += sum(r[0] or 0 for r in c.execute(f"select tokens from builds where id in ({','.join('?' * len(refs))})", refs))
    return hours, tokens


def over_budget(c, t, s):
    if s["harness"] in KINDS.even_spent:
        return None
    b = t["spec"].get("budget") or (t["spec"].get("preset") or {}).get("budget") or {}
    if not b:
        return None
    hours, tokens = spent(c, t, s)
    if b.get("hours") and hours > float(b["hours"]):
        return f"its budget of {b['hours']} h is spent ({hours:.1f} h)"
    if b.get("tokens") and tokens > int(b["tokens"]):
        return f"its budget of {int(b['tokens']):,} tokens is spent ({tokens:,})"
    return None


WIKI_GROUP, WIKI_GROUPS = 6, 4                     # cap: prompt (pages per write call; calls per refinement: 24 pages, said in its answer)


def wiki_context(w):
    """The wiki a refinement is about, for its research steps: the page as it stands, or every page's title and line."""
    import mission_extras as X
    if w.get("page"):
        _, body = M.split_front((M.VAULT / w["root"] / f"{w['page']}.md").read_text(errors="replace"))
        return f"The page “{w['page_title']}” of the wiki “{w['title']}” as it stands now:\n\n{TC.cut(body, 8000)}"  # cap: prompt
    idx = "\n".join(f"- {p['title']}: {p['summary']}" for p in X.wiki_pages(w["root"]))
    return f"The wiki “{w['title']}” as it stands now (every page and its line):\n{TC.cut(idx, 8000)}"  # cap: prompt


def run_wiki(c, t, s, prompt, card):
    """TSK-34: the research steps' findings folded into the wiki, the owner's request first: the page asked about and
    every page the findings name, in groups; corrections keep the old fact as superseded (MEM-12)."""
    import mission_extras as X
    w = t["spec"]["wiki"]
    found = [x for x in steps(c, t["id"], s.get("occ") or 1) if x["idx"] in s["after"]]
    text = (f"The owner asked for this change to the wiki" + (f" (its page “{w['page_title']}”)" if w.get("page") else "") + f": {t['text']}\n"
            "Correct what the findings below show to be wrong, add what they add.\n\n"
            + "\n\n".join(f"### {x['title']} ({x['agent']})\n{x['output'] or ''}" for x in found))
    RESULTS.mkdir(parents=True, exist_ok=True)
    f = RESULTS / f"{t['id']}-wiki-findings-{s.get('occ') or 1}.md"
    f.write_text(f"---\ntask: {t['id']}\nwiki: {w['root']}\n---\n# Findings for the wiki “{w['title']}”\n\n{text}\n")
    src = str(f.relative_to(M.VAULT))
    names = [p["path"] for p in X.mentioned(X.wiki_pages(w["root"]), text)]
    order = ([w["page"]] if w.get("page") else []) + [n for n in names if n != w.get("page")]
    groups = [order[i:i + WIKI_GROUP] for i in range(0, len(order), WIKI_GROUP)][:WIKI_GROUPS] or [[]]  # cap: list (the step's answer names the pages left)
    key = os.environ["VK_" + card["key"][3:].upper().replace("-", "_")]    # the writer's own key (its card), as a python step's
    written = []
    for g in groups:
        written += [p for p in X.compile_into(w["root"], w["title"], src, text, key, touched=g) if p not in written]
    M.vault_commit([w["root"], src], f"task {t['id']}: refined the wiki {w['title']}")
    M.reindex()
    left = order[WIKI_GROUP * WIKI_GROUPS:]
    return (f"{len(written)} page{'s' if len(written) != 1 else ''} of the wiki “{w['title']}” written"
            + (": " + ", ".join(written) if written else ": the findings changed nothing") + f" (findings: {src})."
            + (f" {len(left)} more pages the findings name were not looked at in this run: {', '.join(left)}." if left else ""))


def run_opencode(c, t, s, prompt, card, run=subprocess.run):
    """TSK-07: a step on OpenCode. The prompt goes in as an attached file (a long one would not fit an argument, and the
    agent itself may read only its work folder); the JSON events
    come back: each tool call and its result, each model step with its tokens (in the runtime record under the step,
    so the trace, the map and the costs see them), and the answer's text."""
    import runtime as RTM
    import tempfile
    key = os.environ["VK_" + card["key"][3:].upper().replace("-", "_")]
    repo = t["spec"].get("repo")
    work = CODE / repo if repo and re.fullmatch(r"[A-Za-z0-9._-]+", repo) and (CODE / repo).is_dir() else None
    model = s.get("model") or card.get("model") or "gpt-sub"
    with tempfile.TemporaryDirectory(prefix="opencode-step-") as d:
        (Path(d) / "task.md").write_text(prompt)
        (Path(d) / "results").mkdir()                     # MEM-15: the earlier results whole, where its prompt points
        for x in steps(c, t["id"], s.get("occ") or 1):
            if x["idx"] in s["after"] and x["output"]:
                (Path(d) / "results" / result_file(t, x).name).write_text(x["output"])
        (Path(d) / "oc.json").write_text(OPENCODE_CFG.read_text())
        cmd = (["docker", "run", "--rm", "--network", "aistack_backend", "--memory", "1g", "--name", f"step-{t['id']}-{s.get('occ') or 1}-{s['idx']}",
                "-e", "LITELLM_API_KEY", "-e", "HOME=/root", "-e", "OPENCODE_CONFIG=/step/oc.json", "-v", f"{d}:/step:ro"]
               + (["-v", f"{work}:/work:ro", "-w", "/work"] if work else ["-w", "/tmp"])
               + [OPENCODE_IMAGE, "opencode", "run", "--pure", "--format", "json", "--model", f"litellm/{model}", "-f", "/step/task.md", "--",
                  "Your task is in the attached task.md: do it. You can read files, never run, edit or fetch anything."])
        p = run(cmd, capture_output=True, text=True, timeout=STEP_TIMEOUT, env=dict(os.environ, LITELLM_API_KEY=key))
    texts = []
    for line in (p.stdout or "").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        part = e.get("part") or {}
        if e.get("type") == "tool_use":
            st = part.get("state") or {}
            RTM.stage(part.get("tool") or "tool", json.dumps(st.get("input") or {}), kind="call")
            RTM.stage(part.get("tool") or "tool", str(st.get("output") or st.get("status") or ""), kind="result",
                      status="failure" if st.get("status") == "error" else "success")
        elif e.get("type") == "step_finish":
            tok = part.get("tokens") or {}
            cached = int((tok.get("cache") or {}).get("read") or 0)
            RTM.stage(model, "", kind="llm", status="success", tokens={"in": int(tok.get("input") or 0) + cached, "out": int(tok.get("output") or 0),
                                                                       "cached": cached, "reasoning": int(tok.get("reasoning") or 0)})
        elif e.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
    out = "\n\n".join(texts).strip()
    if p.returncode or not out:
        raise RuntimeError(f"OpenCode ended with exit {p.returncode}: {TC.tail((p.stderr or '').strip(), 600) or 'no answer'}")  # cap: preview
    return out


def run_python(c, t, s, prompt, card):
    key = "VK_" + card["key"][3:].upper().replace("-", "_")
    return M.ask_text(prompt, os.environ[key], s.get("model") or card.get("model") or "gpt-sub", timeout=STEP_TIMEOUT)   # the step's model (TSK-30)


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


# TSK-36: the Conductor's own step kinds, declared as a domain module declares its own (ops/stepkinds.py).
# gb, TSK-08: what a step needs available on the PC (Windows' available memory: free plus the cache it hands back). A model
# call starts nothing; a Hermes turn starts one process in the running Hermes container; Claude Code starts its own
# process. The owner keeps playing on this PC (31 Oct 2026): steps ask for what they use, not for a fixed margin.
OWN_KINDS = {"hermes": {"run": run_hermes, "gb": 0.5},
             "claude-code": {"run": run_claude, "gb": 0.75, "waits": True},
             "build": {"run": run_build, "gb": 0.25, "waits": True},                                  # the builder admits its own work
             "python": {"run": run_python, "gb": 0.25},
             "temp": {"run": run_temp, "gb": 0.25},
             "check": {"run": run_check, "gb": 0.3},                                                  # the builder's tests
             "opencode": {"run": run_opencode, "gb": 1.0},                                            # its container
             "wiki": {"run": run_wiki, "owners": ("mission",), "gb": 0.25, "fixed_plan": True}}       # a wiki write (TSK-34): a model call
DOMAINS = (changes, shop_steps, desk_steps, tax)        # what else runs as steps; missions.main wires its M onto each
KINDS = stepkinds.load(DOMAINS, OWN_KINDS)         # a clash or a kind without its function stops the import here, with the reason
ADAPTERS, OWN_STEPS, NEED_GB, WAITS = KINDS.adapters, KINDS.own_steps, KINDS.need_gb, KINDS.waits


def hooks(t):
    """What the task's kind does differently (ops/stepkinds.py), nothing for most."""
    return KINDS.tasks.get(t.get("kind"), {})


def mapped(c, task, occ, t=None, s=None):
    """TSK-23, TSK-24: what the finished step used and made, then the run's map; never raises into the run."""
    import provenance as PV
    try:
        if s is not None:
            fresh = next((x for x in steps(c, task, occ) if x["idx"] == s["idx"]), None)
            if fresh and fresh["status"] in ("done", "failed"):
                PV.record_step(c, t, fresh)
        PV.write_map(c, task, occ)
    except Exception as e:
        M.log(f"conductor: task {task} run {occ}: provenance not recorded: {type(e).__name__}: {e}")


def run_step(c, t, s, all_steps, agents):
    """One step through its adapter, under its own run in the occurrence's trace. Recorded before (running) and after,
    with what it used and made (TSK-23)."""
    try:
        _run_step(c, t, s, all_steps, agents)
    finally:
        mapped(c, t["id"], s.get("occ") or 1, t, s)


def _run_step(c, t, s, all_steps, agents):
    import runtime as RTM
    occ_run = run_of(t["id"], s.get("occ") or 1)
    run = f"{occ_run}:step:{s['idx']}"
    ev = event_of(c, t["id"], s.get("occ") or 1)
    if ev:                                                # TSK-21: every step of an event's run knows the event
        t = {**t, "event": ev, "goal": f"{t['goal']}\n\n{event_text(ev)}"}
    win = window_of(c, t["id"], s.get("occ") or 1)
    if win:                                               # TSK-49: and every step of a scheduled run the one window it covers
        t = {**t, "window": win, "goal": f"{t['goal']}\n\n{window_text(win)}"}
    if t["spec"].get("wiki") and s["harness"] != "wiki":  # TSK-34: a refinement's research knows the wiki as it is
        t = {**t, "goal": f"{t['goal']}\n\n{wiki_context(t['spec']['wiki'])}"}
    first = s["status"] != "waiting"
    over = over_budget(c, t, s) if first else None       # TRL-11: a step does not start once the task's budget is spent
    if over:
        put(c, s["id"], status="failed", error=f"not started: {over}", attempts=ATTEMPTS, waiting_for=None)
        M.event("task", "", f"Task #{t['id']} stopped: {over}", title="Tasks")
        return
    if first:
        put(c, s["id"], status="running", started=now(), waiting_for=None, attempts=(s["attempts"] or 0) + 1)
        RTM.start(run, s["agent"], f"Step {s['idx']}: {s['title']}", detail=s["why"], ref=occ_run)
        mapped(c, t["id"], s.get("occ") or 1)             # the map shows it running
    RTM.set_ref(run, s["agent"])
    t0 = time.time()
    try:
        made = (hooks(t).get("brief") or prompt_of)(t, s, all_steps, agents)
        out = ADAPTERS[s["harness"]](c, t, s, made, agents.get(s["agent"]) or {})   # a temporary agent has no card
    except Waiting as w:
        put(c, s["id"], status="waiting", waiting_for=str(w), error=None)
        return
    except Reopened as r:                                 # TRL-08: the check set its steps to run again
        RTM.end(run, s["agent"], "done", str(r), time.time() - t0)
        return
    except Cancelled as e:                                # the owner cancelled the task; the step stopped its suite
        put(c, s["id"], status="cancelled", error=str(e), waiting_for=None, ended=now())
        RTM.end(run, s["agent"], "stopped", str(e), time.time() - t0)
        return
    except Exception as e:                                # the step's failure is recorded on it; a limit is waited out
        msg = f"{type(e).__name__}: {e}"
        if M.stop.is_set():                               # the runner stops (a deploy): interrupted, not failed; it stays
            RTM.end(run, s["agent"], "stopped", "the runner stopped", time.time() - t0)   # running, and recover() runs it again
            return
        if M.paused(msg):                                 # a usage limit is no attempt: the count goes back
            resting[s["id"]] = time.time() + LIMIT_REST_S     # RUN-R8: not again on the next 5-second tick against the 429
            put(c, s["id"], status="pending", waiting_for="the subscription's usage limit", attempts=s["attempts"] or 0)
            RTM.end(run, s["agent"], "limit", msg, time.time() - t0)
        elif RTM.unreachable(msg):                          # nor is the network or the NAS away for a moment: it looks again in a minute
            resting[s["id"]] = time.time() + 60
            put(c, s["id"], status="pending", waiting_for="the NAS could not be reached", attempts=s["attempts"] or 0)
            RTM.end(run, s["agent"], "limit", msg, time.time() - t0)
        else:
            put(c, s["id"], status="pending" if (s["attempts"] or 0) + (1 if first else 0) < ATTEMPTS else "failed", error=msg, waiting_for=None)
            RTM.end(run, s["agent"], "failed", msg, time.time() - t0)
        return
    finally:
        RTM.set_ref(None)
    b = BLOCKED.match(out or "") if s["harness"] in WRITTEN else None
    if b:                                                 # no second attempt: the same agent lacks the same thing
        why = f"blocked: {b.group(1).strip()}"
        put(c, s["id"], status="failed", output=out, ended=now(), waiting_for=None, error=why, attempts=ATTEMPTS)
        RTM.end(run, s["agent"], "failed", why, time.time() - t0)
        M.event("task", "", f"Task #{t['id']}: step {s['idx']} ({s['agent']}) is {why}", title="Tasks")
        return
    put(c, s["id"], status="done", output=out, ended=now(), waiting_for=None, error=None)
    RTM.end(run, s["agent"], "done", TC.cut(out, 2000), time.time() - t0)  # cap: preview (the step keeps all of it)


# ---------- the Orchestrator's checkpoint between waves (TRL-08) ----------
def between_waves(t, ss):
    """A one-off plan between two waves: steps finished since the Orchestrator last looked, none runs or waits, some are
    still to come, and it has looks left. A briefing's, a price watch's or a wiki's plan is fixed and never looked at."""
    if t["rhythm"].get("type") not in ("once", None) or t["door"] != "plan" or len(ss) < 2:
        return False
    if any(s["harness"] in KINDS.fixed_plan for s in ss):
        return False
    if "checkpoints" in hooks(t) and not hooks(t)["checkpoints"](t):
        return False                                      # its task kind says this plan needs no second look
    if (checkpoint_ask or getattr(M, "ask_json", None)) is None:
        return False                                      # a runner without a model to ask (tests of other things)
    if any(s["status"] in ("running", "waiting") for s in ss) or not any(s["status"] == "pending" for s in ss):
        return False
    occ = ss[0].get("occ") or 1
    seen = [x for x in t["spec"].get("checkpoints") or [] if x.get("occ", 1) == occ]
    done = sorted(s["idx"] for s in ss if s["status"] == "done")
    return bool(done) and len(seen) < CHECKPOINTS and (not seen or seen[-1]["after"] != done)


def again(s):
    """A pending step that ran before: a check sent it back for a fix round, or it waits for its next attempt."""
    return s["status"] == "pending" and bool(s.get("started"))


def checkpoint(c, t, ss, ask=None):
    """TRL-08: after a wave, the Orchestrator (the intake agent, on its own key) reads what the finished steps found and
    may drop a step not yet started, rewrite one, or add up to ADDS; every look is kept on the task (spec.checkpoints)
    with its reason and shown on the task's page, a change also in the activity. -> the look's record."""
    import prompts as P
    import runtime as RTM
    import tasks as TK
    import textcap as TC
    occ = ss[0].get("occ") or 1
    done = sorted(s["idx"] for s in ss if s["status"] == "done")
    agents = cards()
    plan = "\n".join(f"{s['idx']}. [{'running again' if again(s) else s['status']}] {s['title']} — {s['agent']}"
                     + (f" (after {', '.join(map(str, s['after']))})" if s["after"] else "") for s in ss)
    found = "\n\n".join(f"### Step {s['idx']} ({s['agent']})\n" + TC.cut(s["output"] or "", SEEN, "shown here only; the steps after it get the whole result")  # cap: prompt
                          for s in ss if s["status"] == "done")  # cap: prompt (each step's start, marked; the task page has all)
    p = P.text("shared", "TASK_CHECKPOINT").format(goal=t["goal"], done="\n".join(f"- {d}" for d in t["done"]), plan=plan, found=found,
                                                  agents="\n".join(f"- {k}: {v}" for k, v in TK.cards().items() if runs_steps(agents.get(k) or {})))
    run = f"{run_of(t['id'], occ)}:checkpoint:{len(t['spec'].get('checkpoints') or []) + 1}"
    RTM.start(run, "intake", f"Checkpoint after step {', '.join(map(str, done))}", detail=plan, ref=run_of(t["id"], occ))
    t0 = time.time()
    try:
        raw = (ask or checkpoint_ask or (lambda q: M.ask_json(q, os.environ["VK_INTAKE"])))(p)
        d = raw if isinstance(raw, dict) else json.loads(re.search(r"\{.*\}", str(raw), re.S).group(0))
    except Exception as e:
        RTM.end(run, "intake", "failed", f"{type(e).__name__}: {e}", time.time() - t0)
        raise
    changes = []
    if not d.get("keep", True):
        pend = {s["idx"]: s for s in ss if s["status"] == "pending" and not again(s) and s["harness"] not in KINDS.held}   # not yet started: a fix round is held, and so is a step its module keeps out of the plan's reach
        for n in [int(x) for x in d.get("drop") or [] if str(x).isdigit()][:len(pend)]:
            if n in pend:
                put(c, pend[n]["id"], status="skipped", why=f"{pend[n]['why']} (dropped at the checkpoint: {d.get('why', '')})".strip())
                changes.append(f"dropped step {n}: {pend[n]['title']}")
        for e in d.get("edit") or []:
            n = int(e.get("step", 0)) if str(e.get("step", "")).isdigit() else 0
            text = str(e.get("text", "")).strip()
            if n in pend and text and pend[n]["status"] == "pending":
                put(c, pend[n]["id"], title=text)
                changes.append(f"rewrote step {n}: {text}")
        idxs = {s["idx"] for s in ss}
        nxt = max(idxs) + 1
        for a in TC.first(d.get("add") or [], ADDS, "steps a checkpoint added"):  # cap: untrusted (its prompt names the limit)
            if nxt > MAX_STEPS:                          # limit: drops, a checkpoint's further steps; the run's plan changes say so
                changes.append(f"not added, the plan is at its {MAX_STEPS} steps: {str(a.get('step', '')).strip()}")
                continue
            try:
                node = graph([{"step": str(a.get("step", "")).strip(), "agent": str(a.get("agent", "")), "why": "added at the checkpoint", "after": []}], agents)[0]
            except (ValueError, IndexError):
                continue                                  # no such agent, or one that cannot do a step: not added
            after = sorted({int(x) for x in a.get("after") or [] if str(x).isdigit() and int(x) in idxs})
            before = sorted({int(x) for x in a.get("before") or [] if str(x).isdigit() and int(x) in pend and int(x) not in after})
            c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts, loop) "
                      "values (?,?,?,?,?,?,?,?,?,?,?,0,null)", (t["id"], occ, nxt, node["title"], None, node["agent"], node["harness"],
                                                                 node["model"], json.dumps(after), f"added at the checkpoint: {d.get('why', '')}", "pending"))
            for n in before:                              # the steps it must come first for wait for it too
                put(c, pend[n]["id"], after=json.dumps(sorted(set(pend[n]["after"]) | {nxt})))
            c.commit()
            changes.append(f"added step {nxt}: {node['title']} ({node['agent']})" + (f", before step {', '.join(map(str, before))}" if before else ""))
            idxs.add(nxt)
            nxt += 1
    rec = {"occ": occ, "after": done, "at": now(), "kept": not changes, "why": str(d.get("why", "")).strip(), "changes": changes}
    TK.put(c, t["id"], spec={**TK.row(c, t["id"])["spec"], "checkpoints": (TK.row(c, t["id"])["spec"].get("checkpoints") or []) + [rec]})
    RTM.end(run, "intake", "done", ("Kept the plan: " if not changes else "Changed the plan: ") + "; ".join(changes or [rec["why"]]), time.time() - t0)
    if changes:
        M.event("task", "", f"Task #{t['id']}: the Orchestrator changed the plan after step {', '.join(map(str, done))}: {'; '.join(changes)}"
                + (f" ({rec['why']})" if rec["why"] else ""), title="Tasks")
    mapped(c, t["id"], occ)
    return rec


def cancel(c, t):
    """The owner stops a plan task: its steps that have not started never will; a step already running ends on its own,
    and its answer is not used."""
    import runtime as RTM
    import tasks as TK
    table(c)
    occ = occ_of(c, t["id"])
    c.execute("update task_steps set status='cancelled', waiting_for=null where task=? and status in ('pending', 'waiting')", (t["id"],))
    c.execute("update task_occ set status='cancelled', ended=? where task=? and status='running'", (now(), t["id"]))
    c.execute("update task_events set occ=0 where task=? and occ is null", (t["id"],))     # events waiting for it: dropped
    c.commit()
    try:                                                  # and the Claude tasks its steps started
        import claude_tasks as CT
        CT.cancel_for(c, t["id"])
    except Exception as e:
        M.log(f"conductor: task {t['id']}: its Claude tasks not cancelled: {type(e).__name__}: {e}")
    TK.put(c, t["id"], status="cancelled")                # a recurring task stops for good: no further occurrence starts
    RTM.end(run_of(t["id"], occ), "conductor", "stopped", "cancelled by the owner", None)


# ---------- the worker ----------
def recover(c):
    """After a restart: a step that was running when the runner stopped runs again; a step waiting for a Claude task
    keeps waiting for it. Finished steps are never touched."""
    table(c)
    for r in c.execute("select id from tasks where door='plan' and status='running' and not exists "
                       "(select 1 from task_occ o where o.task = tasks.id and o.status = 'running')").fetchall():
        c.execute("update tasks set status='scheduled' where id=?", (r["id"],))   # FND-84: claimed, never started: it waits again
    c.commit()
    for r in c.execute("select id, resume, attempts from task_steps where status='running'").fetchall():
        if json.loads(r["resume"] or "{}"):
            put(c, r["id"], status="waiting", waiting_for=None)
        else:                                             # a restart is no attempt: the count goes back
            put(c, r["id"], status="pending", waiting_for="the runner restarted", attempts=max(0, (r["attempts"] or 1) - 1))


def ready(c, task):
    """The steps that may start now: pending, every step they wait for done; and waiting steps, to look again."""
    ss = steps(c, task)
    state = {s["idx"]: s["status"] for s in ss}
    return ss, [s for s in ss if (s["status"] == "pending" and all(state.get(a) in FINISHED for a in s["after"])) or s["status"] == "waiting"]


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
    occ = ss[0].get("occ") or 1
    recurring = t["rhythm"].get("type") in ("schedule", "event")
    leaves = [s for s in ss if s["status"] == "done" and not any(s["idx"] in x["after"] and x["status"] == "done" for x in ss)]
    result, path = ("\n\n".join(s["output"] or "" for s in leaves) if ok else ""), None
    quiet = ok and all((s["output"] or "").startswith(QUIET) for s in leaves)
    if ok:
        RESULTS.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[^a-z0-9]+', '-', t['title'].lower()).strip('-')[:50]  # cap: id
        f = RESULTS / (f"{t['id']}-{name}-{dt.date.today()}-{occ}.md" if recurring or occ > 1 else f"{t['id']}-{name}.md")
        f.write_text(f"---\ntask: {t['id']}\nrun: {occ}\ndate: {dt.date.today()}\n---\n# {t['title']}\n\n{result}\n")
        path = str(f.relative_to(M.VAULT))
        M.vault_commit([path], f"task {t['id']}" + (f" run {occ}" if recurring else "") + f": {t['title']}")
        TK.put(c, t["id"], status="scheduled" if recurring else "done", error=None, spec={**TK.row(c, t["id"])["spec"], "result": path})
    else:
        bad = next(s for s in ss if s["status"] == "failed")
        result = f"step {bad['idx']} ({bad['agent']}) failed: {bad['error']}"
        TK.put(c, t["id"], status="scheduled" if recurring else "failed", error=result)   # a failed run; the schedule goes on
    c.execute("update task_occ set status=?, ended=?, result=?, verdict=?, judged=? where task=? and occ=?",   # a quiet run is not judged
              ("done" if ok else "failed", now(), path or TC.cut(result, 500), "quiet" if quiet else None, now() if quiet else None, t["id"], occ))  # cap: preview
    c.commit()
    try:                                                  # TSK-23: late tool events, the answer and its citations
        import provenance as PV
        PV.record_run(c, t, occ, ss)
    except Exception as e:
        M.log(f"conductor: task {t['id']} run {occ}: provenance not recorded: {type(e).__name__}: {e}")
    mapped(c, t["id"], occ)
    RTM.end(run_of(t["id"], occ), "conductor", "done" if ok else "failed", TC.cut(result, 2000), None)  # cap: preview (the vault file keeps all of it)
    EV.task_done(c, t, "done" if ok else "failed")      # TSK-10: a finished task is an event
    run = f" run {occ}" if recurring else ""
    alert = ok and not quiet and str(t.get("source") or "").startswith("rule:")      # P6: an alert's answer is read on the phone, not opened
    N.send(f"Task #{t['id']}{run} {'found nothing new' if quiet else 'is done' if ok else 'failed'}: {t['title']}"
           + (f"\n\n{textcap.cut(re.sub(r'(?m)^#+ .*\n?', '', result).strip(), ALERT_CHARS)}" if alert else "")  # cap: preview (the task page has all of it)
           + ("" if ok else f"\n{textcap.cut(result, 600)}"), "result", by="conductor", title="Tasks",  # cap: preview (why it failed; the task page has all of it)
           push_on=not quiet, event_kind="task",
           buttons=[[("🔍 Open the task", f"{M.X.APP}/#/task/{t['id']}")]])


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


def tick_starts(c):
    """The runs that start now: a task's next run for the oldest event waiting for it (TSK-21). A run on a schedule is
    started by the task's n8n workflow through the step service (WFL-09, ops/flows.py run_task), never here."""
    import tasks as TK
    for r in c.execute("select distinct e.task from task_events e join tasks t on t.id = e.task where e.occ is null and t.door='plan' "
                       "and t.status in ('scheduled', 'done', 'failed')").fetchall():           # TSK-21: an event starts a run
        e = c.execute("select id, event from task_events where task=? and occ is null order by id limit 1", (r["task"],)).fetchone()
        ev = json.loads(e["event"])
        start(c, TK.row(c, r["task"]), trigger="event", event=ev)          # first the run, then the claim (FND-84)
        TK.put(c, r["task"], status="running")
        c.execute("update task_events set occ=? where id=?", (occ_of(c, r["task"]), e["id"]))
        c.commit()
        M.event("task", "", TC.cut(f"Task #{r['task']} run {occ_of(c, r['task'])} started by an event: {ev.get('trigger', '')}: {ev.get('summary', '')}", 300),  # cap: preview
                title="Tasks")


def tick(c, start_thread=None):
    """One pass over the running plan tasks: runs that start now start, finished ones close, ready steps start (with
    headroom, within SLOTS)."""
    import tasks as TK
    agents = cards()
    tick_starts(c)
    for r in c.execute("select id from tasks where door='plan' and status='running'").fetchall():
        t = TK.row(c, r["id"])
        ss, go = ready(c, t["id"])
        if ss and all(s["status"] in FINISHED for s in ss):
            finish(c, t, ss, True)
            continue
        if any(s["status"] == "failed" for s in ss):
            finish(c, t, ss, False)
            continue
        if t["id"] in looking:
            continue                                      # the Orchestrator is looking at this plan now
        if between_waves(t, ss):
            looking.add(t["id"])

            def look(t=t, ss=ss):
                cc = M.db()
                try:
                    checkpoint(cc, t, ss)
                except Exception as e:                    # a failed look changes nothing: the plan goes on as it was
                    M.log(f"conductor: task {t['id']}: checkpoint: {type(e).__name__}: {e}")
                finally:
                    looking.discard(t["id"])
                    cc.close()
            (start_thread or (lambda f: threading.Thread(target=f, daemon=True, name=f"task-{t['id']}-checkpoint").start()))(look)
            continue
        for s in go:
            if (s["status"] == "pending" and not s["attempts"] and "(routed:" not in (s["why"] or "") and "(your choice" not in (s["why"] or "")
                    and hooks(t).get("routing", True) and not (agents.get(s["agent"]) or {}).get("step_kind")):        # a role's step stays its role's
                s = routed(c, t, s, agents)                   # TSK-14: before its first attempt; never away from the owner's choice
            if resting.get(s["id"], 0) > time.time():
                continue
            if s["status"] == "pending":
                why = headroom(s)
                if why:
                    if s["waiting_for"] != why:
                        put(c, s["id"], waiting_for=why)
                    continue
            if s["status"] == "waiting" and s["harness"] not in WAITS:
                continue
            if s["id"] in inflight:
                continue
            looks = s["status"] == "waiting"              # TSK-08: looking at what a step waits for is no work: two changes in review took both slots
            if not looks and not slots.acquire(blocking=False):  # on every pass, and no other step of any task started for four hours
                continue
            inflight.add(s["id"])

            def job(t=t, s=s, ss=ss, looks=looks):
                cc = M.db()
                try:
                    run_step(cc, t, s, ss, agents)
                except Exception as e:                    # an adapter bug fails the step, not the worker; it is logged
                    M.log(f"conductor: task {t['id']} step {s['idx']}: {type(e).__name__}: {e}")
                    put(cc, s["id"], status="failed", error=f"{type(e).__name__}: {e}")
                finally:
                    inflight.discard(s["id"])
                    if not looks:
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
    import asks as AK
    while not M.stop.is_set():
        try:
            if AK.stopped():                              # ASK-08: the stop switch: no step starts; what runs finishes
                M.rest(c, "conductor", 5)
                continue
            with lock:
                tick(c)
        except Exception as e:                            # the next pass tries again; it is logged
            M.log(f"conductor: {type(e).__name__}: {e}")
        M.rest(c, "conductor", 5)


def state(c, task_ids):
    """The board's view of plan tasks: the latest occurrence's steps."""
    table(c)
    return {tid: [{k: s[k] for k in ("idx", "title", "item", "agent", "harness", "after", "why", "status", "waiting_for", "error", "attempts",
                                     "started", "ended", "occ")} | {"output": s["output"] or ""} for s in steps(c, tid)] for tid in task_ids}


def occurrences(c, tid):
    """A task's occurrences, newest first: each run's number, how it started, its state and its result."""
    table(c)
    return [dict(r) | {"live": run_of(tid, r["occ"]), "event": json.loads(r["event"]) if r["event"] else None,
                       "judgement": json.loads(r["judgement"]) if r["judgement"] else None, "window": json.loads(r["window"]) if r["window"] else None}
            for r in c.execute("select occ, trigger, started, ended, status, result, event, verdict, judged, tokens, cost, judgement, window from task_occ "
                               "where task=? order by occ desc", (tid,)).fetchall()]


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


# ---------- the trigger proof (MIS-10) ----------
PROOF_QUERY, PROOF_SYMBOL = "zzqx trigger proof replay 7d1f", "PROOF.TEST"   # nothing real matches them: only the replay fires
PROOF_STEP = [{"step": "Say what the event that started this run is, and in at most two lines why it may matter to the owner.",
               "agent": "desk", "why": "one model call on the desk's own key", "after": []}]


def recorded_item():
    """A real article from the newest briefing in the vault (title and link): the news event the proof replays."""
    for f in sorted((M.VAULT / "topics").glob("*/reports/*/*/*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        m = re.search(r"\[([^\]]{12,200})\]\((https?://[^)\s]+)\)", f.read_text(errors="replace"))
        if m:
            return {"id": "proof-" + m.group(2)[-40:], "title": m.group(1), "url": m.group(2), "source": str(f.relative_to(M.VAULT))}  # cap: id
    raise SystemExit("no briefing report with a linked article in the vault to replay")


def triggers_proof():
    """Two event tasks (a news search and a price move nothing real matches), the real watcher (mission_extras
    check_events) run twice on a replayed watch result: a baseline, then a new article and a 7 % move. The live
    Conductor then runs each task's occurrence; the proof waits for both to finish and be judged, checks them, writes
    eval/results/<time>-trigger-proof.json and cancels both tasks."""
    sys.path.insert(0, str(ROOT / "ops"))
    import types
    import missions as MM
    import mission_extras as X
    import tasks as TK
    globals()["M"] = MM
    X.M = TK.M = MM
    c = MM.db()
    TK.table(c)
    table(c)
    item, today = recorded_item(), dt.date.today().isoformat()
    t0, ids = TK.now(), {}
    for kind, trig in (("news", {"type": "news", "query": PROOF_QUERY}), ("price", {"type": "price_move", "symbol": PROOF_SYMBOL, "pct": 5.0})):
        cur = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, source, created, updated) "
                        "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"Trigger proof: tell me when the {kind} trigger fires", f"Trigger proof: {kind}", "Say what happened and why it may matter.",
                         "watching", "plan", None, json.dumps(["names the event that started the run", "says in at most two lines why it may matter"]),
                         "light", "auto", json.dumps({"type": "event", "triggers": [trig]}), json.dumps({"plan": PROOF_STEP}), "[]", "[]", "scheduled", "gate", t0, t0))
        ids[kind] = cur.lastrowid
        TK.put(c, cur.lastrowid, ref=str(cur.lastrowid))
    print(f"proof tasks: news #{ids['news']}, price #{ids['price']}; replaying {item['title']!r} ({item['url']})", flush=True)
    payloads = iter([{"sec": {}, "news": {PROOF_QUERY: []}, "prices": {PROOF_SYMBOL: {"last": 10.05, "prev": 10.0, "pct": 0.5, "currency": "USD", "date": today}}},
                     {"sec": {}, "news": {PROOF_QUERY: [item]}, "prices": {PROOF_SYMBOL: {"last": 10.7, "prev": 10.0, "pct": 7.0, "currency": "USD", "date": today}}}])
    X.subprocess = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(returncode=0, stdout=json.dumps(next(payloads)), stderr=""))
    try:
        for _ in range(2):                                # the baseline, then the replayed news and move
            X._last_watch["t"] = 0
            X.check_events({}, c)
    finally:
        X.subprocess = subprocess
    queued = {k: [json.loads(r["event"]) for r in c.execute("select event from task_events where task=?", (v,))] for k, v in ids.items()}
    print(f"events queued: {[(k, [e['trigger'] for e in v]) for k, v in queued.items()]}; waiting for the live Conductor", flush=True)
    deadline = time.time() + 45 * 60
    while time.time() < deadline:
        occ = {k: c.execute("select status, verdict from task_occ where task=? and occ=1", (v,)).fetchone() for k, v in ids.items()}
        if all(o and o["status"] in ("done", "failed") and o["verdict"] for o in occ.values()):
            break
        time.sleep(15)
    runs = dict(__import__("sqlite3").connect("/srv/ai/missions/app/runtime.db").execute(
        "select run, ref from runs where run like 'task:%'").fetchall())
    checks, detail = {}, {}
    for k, v in ids.items():
        o = (occurrences(c, v) or [{}])[-1]
        s = (steps(c, v, 1) or [{}])[0]
        host = urllib.parse.urlparse(item["url"]).netloc.removeprefix("www.").split(".")[0]
        marks = re.findall(r"\d+(?:\.\d+)?", item["title"]) + [host] if k == "news" else [PROOF_SYMBOL]   # the article may be in another language
        checks[f"{k}: the trigger queued one event"] = len(queued[k]) == 1
        checks[f"{k}: the event started run 1 under the Conductor"] = o.get("trigger") == "event" and bool(o.get("event"))
        checks[f"{k}: the run finished"] = o.get("status") == "done"
        checks[f"{k}: its step knew the event"] = any(w.lower() in (s.get("output") or "").lower() for w in marks)
        checks[f"{k}: the run was judged"] = o.get("verdict") not in (None, "not judged")
        checks[f"{k}: one trace"] = runs.get(f"task:{v}:step:1") == f"task:{v}"
        detail[k] = {"task": v, "event": queued[k], "run": {x: o.get(x) for x in ("status", "verdict", "result", "judgement")}, "step_output": s.get("output")}
    for v in ids.values():
        cancel(c, TK.row(c, v))                           # nothing more to watch
    out = ROOT / "eval/results" / f"{time.strftime('%Y%m%d-%H%M%S')}-trigger-proof.json"
    out.write_text(json.dumps({"replayed": item, "checks": checks, "tasks": detail}, indent=1, ensure_ascii=False))
    for k, v in checks.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"{out.relative_to(ROOT)}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["gate"]:
        sys.exit(gate())
    if sys.argv[1:] == ["triggers"]:
        sys.exit(triggers_proof())
    sys.exit(__doc__)
