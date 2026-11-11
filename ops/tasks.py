"""The task kernel (TSK-01 to TSK-04; phase 1 of docs/SWARM-ROADMAP.md). Every piece of work is a task: its goal,
definition of done, budget, deadline, autonomy and rhythm (once, on a schedule, on an event, or after another task).

- A task given in one sentence (the app's composer, request task_create) goes to the intake agent, which writes its
  specification: a checkable definition of done, the plan with the agent for each step and why, and at most two
  questions. Then the Conductor runs its plan (ops/conductor.py, TSK-21): once, on a schedule or each time its trigger
  fires, a briefing as the Topic Desk's plan, a price watch as checks of its shopping agent, coding as a build step.
  A plan the Conductor cannot run goes to its door: a mission, a build (coding) or a Claude task (a question about code).
- Work started at a door directly (a new mission, build, Claude task or chat) becomes a task too (sync), so the board
  shows every piece of work of the last 7 days.
- The door keeps its own approvals (deploy taps, purchases, the AI phone); the task's autonomy decides only whether
  the plan waits for the owner first (TSK-20 proposes the default: it does not).

  python3 ops/tasks.py gate      the phase 1 gate: eval/tasks-v1.yaml's 20 one-sentence tasks through the intake
"""
import datetime as dt
import json
import re
import sys
import threading
import time
from pathlib import Path

import yaml
import textcap as TC                              # visible caps (AGENTS.md, truncation)

ROOT = Path(__file__).resolve().parent.parent
CHATS = Path("/srv/ai/missions/app/chats")       # the app's chats (images/mission-control/server.py)
WINDOW = 7 * 86400                                # the board shows the work of the last 7 days, and every open task
KINDS = {"change": "change", "coding": "build", "code_question": "claude", "research": "mission", "analysis": "mission", "errand": "mission",
         "watching": "mission", "briefing": "mission", "shopping": "mission", "cleanup": "mission"}   # cleanup: only when the owner picks it
MISSION_TYPE = {"briefing": "briefing", "shopping": "shopping", "cleanup": "cleanup"}   # every other mission kind is a task mission
DELIVER = ("telegram", "app", "email")
# TSK-52 (TSK-40's split superseded): every task is in one list, labelled by its area (ops/areas.py). Who asked stays as
# information on a task, never a filter: work the stack gives itself (trials, probes, gates, onboarding, its upkeep)
# is the stack's, everything else yours.
STACK_SOURCE = re.compile(r"^(trial|probe|gate|crew|onboard|commission)\b")
EFFORTS = ("light", "standard", "deep")
REPLAN_H = 6                                       # a planning a restart cut off is planned again within this; older, it fails and says why
AUTONOMY = ("auto", "ask")                       # auto: start when planned (TSK-20's proposal); ask: the plan waits for the owner
RUNS = 10                                          # runs of a recurring task its card lists (newest first)
OPEN = ("intake", "needs_answer", "waiting_approval", "planned", "running", "waiting_owner", "scheduled", "after")
DONE_OF = {"briefing": "Each briefing is delivered with the sources it used", "task": "The report answers the goal, with its sources",
           "shopping": "A proposal within the owner's limits, or a price alert", "cleanup": "A ranked cleanup report the owner can act on",
           "build": "The change is merged and deployed with its checks passing", "claude": "The question is answered",
           "chat": "The question is answered in the chat", "crew": "Each run does its duty and reports what it found"}
QUESTIONS = 2                                     # TSK-03: at most two questions, only when the goal cannot be planned without them
STEPS = 8                                         # cap: list (a plan of more steps is a task for the Conductor's plan graph; 8 holds the spec roles, TRL-07)
M = None                                          # ops/missions.py, set by its main()
lock = threading.Lock()


def table(c):
    c.execute("""create table if not exists tasks (id integer primary key, text text, title text, goal text, kind text,
                 door text, ref text, done text, effort text, deadline text, autonomy text, rhythm text, after integer,
                 spec text, questions text, answers text, status text, source text, created text, updated text, error text)""")
    c.execute("create index if not exists tasks_door_ref on tasks (door, ref)")    # not unique: two tasks may reach one mission
                                                                                    # (a duplicate title joins the existing one)
    if "owner" not in {r[1] for r in c.execute("pragma table_info(tasks)")}:       # TSK-40: yours or the stack's
        c.execute("alter table tasks add column owner text")
    fixed = 0
    for r in c.execute("select id, text, title from tasks where title like '% …' or title like '%…'").fetchall():   # APP-57: a title cut
        whole = title_of(r[1])                                                        # before 9 Nov 2026 is made whole again
        if whole and whole != r[2]:
            c.execute("update tasks set title=? where id=?", (whole, r[0]))
            fixed += 1
    if fixed:                                        # PLT-40: a repair is committed here, never left open for the caller's loop
        c.commit()


def owner_of(c, source, door=None, ref=None):
    """Who asked (TSK-52: information, never a filter): "stack" for the work the stack gives itself, else "you". A crew
    duty and a workflow's run are the stack's when their area is Upkeep (ops/crew.py, the workflow's file); a question to
    Claude is the stack's when one of its own asked it (the Health doctor, an onboarding)."""
    if door == "crew":
        import crew as CR
        return "stack" if (CR.BY_ID.get(str(ref)) or {}).get("area", "upkeep") == "upkeep" else "you"
    if door == "workflow":
        import flow_tasks as FT
        return "stack" if FT.area_of_run(ref) == "upkeep" else "you"
    if STACK_SOURCE.match(str(source or "")):
        return "stack"
    if door == "claude" and str(ref or "").isdigit() and _has(c, "claude_tasks"):
        q = c.execute("select source from claude_tasks where id=?", (int(ref),)).fetchone()
        if q and STACK_SOURCE.match(str(q["source"] or "")):
            return "stack"
    return "you"


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def title_of(text):
    """A task's name: the first sentence of its words (or its first line), whole, never cut (APP-57; the owner, 9 Nov 2026,
    of titles ending "(origin …" and "Look at …": "Again we have truncation. Not good."). A long one wraps."""
    first = next((ln.strip() for ln in str(text or "").splitlines() if ln.strip()), "")
    m = re.match(r"^(.+?[.!?])(?=\s|$)", first)
    return re.sub(r"\s+", " ", m.group(1) if m else first).strip()


def put(c, tid, **kw):
    kw["updated"] = now()
    for k in ("done", "rhythm", "spec", "questions", "answers"):
        if k in kw and not isinstance(kw[k], str) and kw[k] is not None:
            kw[k] = json.dumps(kw[k], ensure_ascii=False)
    c.execute(f"update tasks set {', '.join(f'{k}=?' for k in kw)} where id=?", (*kw.values(), tid))
    c.commit()


def row(c, tid):
    r = c.execute("select * from tasks where id=?", (tid,)).fetchone()
    if not r:
        raise ValueError(f"no task {tid}")
    d = dict(r)
    for k, empty in (("done", []), ("rhythm", {"type": "once"}), ("spec", {}), ("questions", []), ("answers", [])):
        d[k] = json.loads(d[k]) if d.get(k) else empty
    return d


# ---------- every door's work is a task (TSK-01) ----------
def register(c, door, ref, goal, title="", *, done=None, rhythm=None, status="running", source="door", created=None, owner=None):
    """The task of a piece of work started at a door; once per (door, ref)."""
    if c.execute("select 1 from tasks where door=? and ref=?", (door, str(ref))).fetchone():
        return None
    t = created or now()
    cur = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, deadline, autonomy, rhythm, spec, questions, "
                    "answers, status, source, created, updated, owner) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (goal, title_of(title or goal), goal, None, door, str(ref), json.dumps(done or []), "standard", None,
                     "door", json.dumps(rhythm or {"type": "once"}), "{}", "[]", "[]", status, source, t, t,
                     owner or owner_of(c, source, door, ref)))
    c.commit()
    return cur.lastrowid


def rhythm_of_mission(m):
    """A mission's rhythm as its task holds it: on a schedule (its alerts riding along, as a moved briefing's), on an
    event, or once."""
    sched = m.get("schedule") if m.get("schedule") and m["schedule"] != "manual" and not m.get("once") else None
    if sched:
        return {"type": "schedule", "schedule": sched, **({"triggers": m["triggers"]} if m.get("triggers") else {})}
    if m.get("triggers"):
        return {"type": "event", "triggers": m["triggers"]}
    return {"type": "once"}


def _recent(iso, now_ts):
    try:
        return now_ts - dt.datetime.fromisoformat(iso).timestamp() < WINDOW
    except (TypeError, ValueError):
        return False


def discover(c, missions, now_ts=None):
    """Every mission (TSK-41: a task for good, however old; an archived one as done), and the builds, Claude tasks and
    chats of the last 7 days, that no task holds yet become tasks."""
    now_ts = now_ts or time.time()
    for m in missions.values():
        if not m.get("task"):                                             # a task's own shopping agent is that task
            register(c, "mission", m["slug"], m.get("goal") or m["title"], m["title"], done=[DONE_OF.get(m.get("type"), DONE_OF["task"])],
                     rhythm=rhythm_of_mission(m), created=m.get("created"), status="done" if m.get("status") == "archived" else "running")
            if MISSION_TYPE.get(m.get("type")):                            # TSK-52: its area follows its kind
                c.execute("update tasks set kind=? where door='mission' and ref=? and kind is null", (m["type"], m["slug"]))
    held = {(r["kind"], r["ref"]) for r in c.execute("select kind, ref from step_refs")} if _has(c, "step_refs") else set()   # FND-91
    for b in c.execute("select id, title, description, created from builds").fetchall() if _has(c, "builds") else []:
        if _recent(b["created"], now_ts) and ("build", str(b["id"])) not in held:
            register(c, "build", b["id"], b["description"] or b["title"], b["title"], done=[DONE_OF["build"]], created=b["created"])
    for q in c.execute("select id, question, created from claude_tasks").fetchall() if _has(c, "claude_tasks") else []:
        if _recent(q["created"], now_ts) and ("claude", str(q["id"])) not in held:
            register(c, "claude", q["id"], q["question"], title_of(q["question"]), done=[DONE_OF["claude"]], created=q["created"])
    for f in CHATS.glob("*.json") if CHATS.exists() else []:
        if now_ts - f.stat().st_mtime < WINDOW and not c.execute("select 1 from tasks where door='chat' and ref=?", (f.stem,)).fetchone():
            try:
                ch = json.loads(f.read_text())
            except (OSError, ValueError) as e:
                print(f"tasks: chat {f.name} not read ({type(e).__name__})", flush=True)
                continue
            first = next((m["content"] for m in ch.get("messages", []) if m.get("role") == "user"), ch.get("title") or "chat")
            register(c, "chat", f.stem, first, ch.get("title") or first, done=[DONE_OF["chat"]],
                     created=dt.datetime.fromtimestamp(ch.get("created") or f.stat().st_mtime).astimezone().isoformat(timespec="seconds"))


def _has(c, name):
    return bool(c.execute("select 1 from sqlite_master where type='table' and name=?", (name,)).fetchone())


def discover_crew(c):
    """TSK-42: each crew duty is the stack's own repeating task: its plan fixed (the duty), its When the duty's schedule
    (its n8n workflow's, WFL-09; the backup's and the restore drill's their timers), shown under the Tasks tab's "The
    stack's" and on Team, never in your own list."""
    import crew as CR
    try:
        sched = {a["id"]: a.get("schedule") for a in CR.status()}
    except Exception as e:                             # no systemd (a test, a fresh machine): the duties are still tasks
        print(f"tasks: the crew's schedules not read ({type(e).__name__})", flush=True)
        sched = {}
    for a in CR.CREW:
        if a.get("oneoff"):
            continue
        r = {"type": "schedule", "schedule": sched.get(a["id"]) or "on its workflow"}
        who = owner_of(c, "crew", "crew", a["id"])       # who asked follows the job's area (TSK-52)
        if register(c, "crew", a["id"], a["what"], a["name"], done=[DONE_OF["crew"]], rhythm=r, status="scheduled",
                    source="crew", owner=who) is None and sched.get(a["id"]):
            c.execute("update tasks set rhythm=? where door='crew' and ref=? and rhythm<>?", (json.dumps(r), a["id"], json.dumps(r)))
        c.execute("update tasks set owner=? where door='crew' and ref=? and owner is not ?", (who, a["id"], who))
    c.commit()


def area_of(c, t):
    """TSK-52: what a task is for (ops/areas.py): a crew duty's and a workflow's their declared area, a task's own
    workflow the task's, code work Code, a mission's its type, a task given in a sentence its kind's, a trial Code."""
    import areas as AR
    door, ref, src = t.get("door"), str(t.get("ref") or ""), str(t.get("source") or "")
    if door == "crew":
        import crew as CR
        return (CR.BY_ID.get(ref) or {}).get("area") or AR.UPKEEP
    if door in ("flow", "workflow"):
        import flow_tasks as FT
        wf = FT.workflow(ref) if door == "flow" else FT.workflow_of_run(ref)
        return FT.area_of_workflow(wf) if wf else "research"
    if door in ("build", "claude") or src.startswith(("trial", "onboard")):
        return "code"
    if src.startswith(("probe", "gate", "commission")):
        return AR.UPKEEP
    return AR.of_kind(t.get("kind"))                  # a mission's task has its type as its kind (discover)


def asked_by(t):
    """Who asked for it, in a word the list shows: you, a rule of yours, an outside agent, the inbox, or the stack."""
    src = str(t.get("source") or "")
    if src.startswith("rule:"):
        return "rule"
    if src.startswith("a2a:"):
        return "agent"
    return "stack" if t.get("owner") == "stack" else "you"


def crew_result(t):
    """A crew duty's result where it has a page of its own (ops/crew.py "result": the mail sorter's Your mail)."""
    if t.get("door") != "crew":
        return {}
    import crew as CR
    r = (CR.BY_ID.get(str(t.get("ref"))) or {}).get("result")
    return {"result_href": r[0], "result_label": r[1]} if r else {}


def discover_flows(c):
    """TAX-09: a workflow that is one of the owner's tasks (ops/flow_tasks.py: the tax desk's Your taxes) has its task,
    its When and its state from the workflow's runs."""
    import flow_tasks as FT
    try:
        FT.sync(c)
    except Exception as e:                             # logged; the board shows the rest
        M.log(f"tasks: flow tasks: {type(e).__name__}: {e}")


def own(c):
    """TSK-40: every task without an owner gets one (the tasks from before owners)."""
    rows = c.execute("select id, source, door, ref from tasks where owner is null").fetchall()
    for r in rows:
        c.execute("update tasks set owner=? where id=?", (owner_of(c, r["source"], r["door"], r["ref"]), r["id"]))
    if rows:
        c.commit()


BUILD = {"review": "waiting_owner", "deployed": "done", "merged": "done", "failed": "failed", "rolled_back": "failed",
         "reverted": "failed", "rejected": "cancelled"}


def status_of(c, t, missions):
    """The task's status from its door: the mission's runs, the build, the Claude task, the chat."""
    door, ref = t["door"], t["ref"]
    if door == "mission":
        m = missions.get(ref)
        if not m or m.get("status") == "archived":
            return "done" if m else "cancelled"
        r = c.execute("select status from runs where slug=? order by id desc limit 1", (ref,)).fetchone()
        st = r["status"] if r else None
        periodic = t["rhythm"].get("type") in ("schedule", "event")
        if st in ("running", "queued", "waiting"):
            return "running"
        if periodic:
            return "scheduled" if m.get("status") == "active" else "cancelled"
        return {"ok": "done", "failed": "failed", "skipped": "cancelled"}.get(st, "running")
    if door == "build":
        r = c.execute("select status from builds where id=?", (int(ref),)).fetchone()
        return BUILD.get(r["status"], "running") if r else "cancelled"
    if door == "claude":
        r = c.execute("select status from claude_tasks where id=?", (int(ref),)).fetchone()
        return {"done": "done", "failed": "failed"}.get(r["status"], "running") if r else "cancelled"
    if door == "chat":
        try:
            return "running" if json.loads((CHATS / f"{ref}.json").read_text()).get("pending") else "done"
        except (OSError, ValueError):
            return "done"
    return t["status"]


def sync(c, missions):
    """Discover new door work, follow each open task's door, and start tasks whose 'after' task has finished."""
    table(c)
    with lock:
        discover(c, missions)
        discover_crew(c)
        discover_flows(c)
        own(c)
        for r in c.execute(f"select id from tasks where status in ({','.join('?' * len(OPEN))})", OPEN).fetchall():
            try:
                t = row(c, r["id"])
            except ValueError:                         # a dispatch earlier in this pass removed it (its door's duplicate)
                continue
            if t["status"] == "after":
                a = c.execute("select status from tasks where id=?", (t["after"],)).fetchone()
                if a and a["status"] == "done":
                    dispatch(c, t)
                elif a and a["status"] in ("failed", "cancelled"):
                    put(c, t["id"], status="cancelled", error=f"task #{t['after']} it waited for did not finish ({a['status']})")
            elif t["door"] and t["ref"] and t["status"] in ("running", "waiting_owner", "scheduled"):
                st = status_of(c, t, missions)
                if st != t["status"]:
                    put(c, t["id"], status=st)
                    if st in ("done", "failed"):                              # TSK-10: a finished task is an event
                        import events as EV
                        EV.task_done(c, t, st)
                    if st in ("done", "failed") and t["source"] != "door":    # a door reports its own work: only the
                                                                              # composer's tasks are told here (65 lines once)
                        M.event("task", "", f"Task #{t['id']} {'done' if st == 'done' else 'failed'}: {t['title']}", title="Tasks")


# ---------- a task given in a sentence (TSK-02, TSK-03) ----------
def preset_of(req):
    """Deliberate mode: the fields the owner set before the start; anything else is the intake's to decide."""
    p = {}
    if req.get("kind") in KINDS:
        p["kind"] = req["kind"]
    if str(req.get("ref") or "").strip():               # TSK-48: a code question about a commit, tag or branch, not main
        p["ref"] = str(req["ref"]).strip()
    if req.get("history"):                              # TSK-48: the copy brings this many commits of history
        p["history"] = req["history"]
    if req.get("effort") in EFFORTS:
        p["effort"] = req["effort"]
    import conductor as CD
    cards = CD.cards()
    asked = list(dict.fromkeys(str(x) for x in req.get("agents") or []))
    unknown = [a for a in asked if a not in cards or not CD.runs_steps(cards[a])]
    if unknown:                                        # review SWM-R12: an agent the owner named was dropped without a word
        raise ValueError(f"no agent that runs task steps: {', '.join(unknown)}")
    picked = TC.limit_items(asked, 6, "agents for one task")   # limit: refuses (more agents than a task's plan gives steps to)
    if picked:                                         # TSK-30: the owner's own agents for this task
        p["agents"] = picked
    if req.get("model"):
        import prices as PR
        if req["model"] not in PR.load().get("models", {}):
            raise ValueError(f"{req['model']!r} is no model the gateway serves")
        p["model"] = req["model"]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(req.get("deadline") or "")):
        p["deadline"] = req["deadline"]
    r = req.get("rhythm") or {}
    if r.get("type") == "schedule" and M.valid_schedule(str(r.get("schedule", ""))):
        p["rhythm"] = {"type": "schedule", "schedule": r["schedule"]}
    elif r.get("type") == "once":
        p["rhythm"] = {"type": "once"}
    elif r.get("type") == "after" and str(r.get("task", "")).isdigit():
        p["rhythm"] = {"type": "after", "task": int(r["task"])}
    elif r.get("type") == "event":                     # the New task form's "On event": its triggers, checked like a mission's
        import mission_extras as X
        tr = X.clean_triggers(r.get("triggers") or [])
        if not tr:
            raise ValueError("say what starts it: news on a subject, a price move or an SEC filing")
        p["rhythm"] = {"type": "event", "triggers": tr}
    dl = [x for x in req.get("deliver") or [] if x in DELIVER]
    if dl:                                             # where its results go; none chosen: the app and Telegram
        p["deliver"] = list(dict.fromkeys(dl))
    b = req.get("budget") or {}                       # TRL-11: hours and tokens the task's run may use
    if isinstance(b, dict) and (b.get("hours") or b.get("tokens")):
        if float(b.get("hours") or 0) > 24:             # limit: refuses (a task's run is planned within a day; trials.load refuses past it too)
            raise ValueError(f"a task's budget is at most 24 hours, not {b.get('hours')}")
        p["budget"] = {k: v for k, v in (("hours", float(b.get("hours") or 0)), ("tokens", int(b.get("tokens") or 0))) if v}
    done = [d.strip() for d in req.get("done") or [] if str(d).strip()]
    if done:
        p["done"] = TC.limit_items(done, 8, "points in the definition of done")   # limit: refuses (more points is a plan; SWM-R12)
    if str(req.get("repo") or "") in B_repos():
        p["repo"] = req["repo"]
    return p


def B_repos():
    """Every repository the stack knows: those the builder may change and those studied in ~/code (a work site, 9 Nov 2026:
    a code question about a repository not on Forgejo lost its repository and ran with none)."""
    import builds as B
    names = set(B.repos())
    names |= {p.name for p in B.CODE.iterdir() if (p / ".git").exists()} if B.CODE.exists() else set()
    return sorted(names)


def create(req, c):
    """task_create: the owner's sentence (and deliberate presets) -> a task the intake worker picks up."""
    table(c)
    text = re.sub(r"\s+", " ", str(req.get("text", ""))).strip()
    if len(text) < 8:
        raise ValueError("say what the stack should do (at least a few words)")
    # limit: refuses, a task given in a sentence, with its size: the rest goes in a document
    if len(text) > 4000:
        raise ValueError(f"the task is {len(text):,} characters; keep it under 4,000 and put the rest in a document")
    autonomy = req.get("autonomy") if req.get("autonomy") in AUTONOMY else "auto"
    if str(req.get("source") or "").startswith("a2a:"):     # TSK-19: an outside agent's task always waits for the owner's OK
        autonomy = "ask"
    p = preset_of(req)
    w = wiki_target(req["wiki"]) if req.get("wiki") else None
    if w:                                              # a refinement: the intake reads which wiki (and page) it is about
        text += f" (On the wiki “{w['title']}”" + (f", its page “{w['page_title']}”" if w.get("page") else "") + ": what is found is written into it.)"
    after = p.get("rhythm", {}).get("task") if p.get("rhythm", {}).get("type") == "after" else None
    if after and not c.execute("select 1 from tasks where id=?", (after,)).fetchone():
        raise ValueError(f"there is no task #{after} to wait for")
    t = now()
    cur = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, deadline, autonomy, rhythm, after, spec, questions, "
                    "answers, status, source, created, updated) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (text, title_of(text), text, p.get("kind"), None, None, json.dumps(p.get("done") or []), p.get("effort", "standard"),
                     p.get("deadline"), autonomy, json.dumps(p.get("rhythm") or {"type": "once"}), after,
                     json.dumps({"preset": p, **({"wiki": w} if w else {}), **({"repo": p.get("repo"), "change": req["change"]} if isinstance(req.get("change"), dict) else {})}),
                     "[]", "[]", "intake", req.get("source") or "app", t, t))
    c.execute("update tasks set owner=? where id=?", (owner_of(c, req.get("source") or "app"), cur.lastrowid))
    c.commit()
    M.event("task", "", f"Task #{cur.lastrowid}: {text[:120]}", title="Tasks")  # cap: list (the feed line; the task holds all of it)
    return {"task": cur.lastrowid}


def wiki_target(w):
    """A refinement's wiki (and page): one that exists and still grows -> {root, title, page, page_title}."""
    import wikis as W
    roots = dict(W.roots())
    root, page = str(w.get("root") or ""), str(w.get("page") or "").strip()
    if root not in roots:
        raise ValueError(f"there is no wiki {root!r} to improve")
    out = {"root": root, "title": roots[root]}
    if page:
        f = M.VAULT / root / f"{page}.md"
        if not re.fullmatch(r"[a-z0-9][a-z0-9_./-]{0,120}", page) or ".." in page or not f.is_file():
            raise ValueError(f"the wiki {roots[root]!r} has no page {page!r}")
        meta, _ = M.split_front(f.read_text(errors="replace"))
        out.update(page=page, page_title=str(meta.get("title") or page.split("/")[-1]))
    return out


def wiki_plan(c, t):
    """A refinement task (TSK-34): the intake's research steps, then the wiki's writer folds what they found into the
    wiki (the page first), correcting what the findings contradict and keeping the superseded facts."""
    plan, w = list(t["spec"].get("plan") or []), t["spec"]["wiki"]
    if not plan:
        plan = [{"step": "Research what the owner asked", "agent": "scout", "why": "reads the web", "after": []}]
    leaves = [i for i in range(1, len(plan) + 1) if not any(i in (p.get("after") or []) for p in plan)]
    plan.append({"step": f"Write it into the wiki “{w['title']}”" + (f", page “{w['page_title']}” first" if w.get("page") else ""),
                 "agent": "mission", "harness": "wiki", "after": leaves,
                 "why": "the wiki's writer folds the findings in: corrects what they contradict, keeps the old fact as superseded, adds what is new"})
    s = {**t["spec"], "plan": plan, "intake_plan": t["spec"].get("intake_plan") or t["spec"].get("plan") or []}
    put(c, t["id"], spec=s)
    return row(c, t["id"])


TOOL_WORDS = {"phone": "the AI phone (open and install apps, tap, type, read the screen)", "house": "Home Assistant (lights, speakers)",
              "mail": "e-mail", "research": "web research", "qmd": "the vault's search", "browser": "a web browser (shops)",
              "fetch": "reading web pages", "jobs": "the federal job board", "claude": "Claude Code questions about code",
              "graphify": "the code graph", "missions": "the stack's missions and builds"}


CODE_AGENT = "analyst"                             # who takes a code question's step that another agent cannot do (TSK-45)


def code_readers():
    """The agents that read a task's repository in a step: a Claude Code or OpenCode harness with a code role (a work site,
    9 Nov 2026: a code question was planned with a step on the assistant, which has no repository, and failed "blocked")."""
    reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())
    return {a["id"] for a in reg["agents"] if a.get("harness") in ("claude-code", "opencode") and "code" in (a.get("roles") or [])}


def cards():
    """Each agent with what it does and what it can reach, so the plan gives a step to an agent that can do it (task
    #104 went to an agent without the phone, 1 Nov 2026)."""
    reg = yaml.safe_load((ROOT / "config/agents.yaml").read_text())
    return {a["id"]: a["purpose"] + (f" Its tools: {'; '.join(TOOL_WORDS[x] for x in a.get('tools') or [] if x in TOOL_WORDS)}."
                                     if any(x in TOOL_WORDS for x in a.get("tools") or []) else "") for a in reg["agents"]}


def intake_prompt(t, repos, agents):
    import prompts as P
    return P.text("intake", "INTAKE").format(
        text=t["text"], today=dt.date.today().isoformat(), preset=json.dumps(t["spec"].get("preset") or {}, ensure_ascii=False),
        answers="\n".join(f"- {q}: {a}" for q, a in t["spec"].get("answered") or []) or "(none)",
        repos=", ".join(repos) or "(none)", agents="\n".join(f"- {k}: {v}" for k, v in agents.items()))


def validate(spec, preset, repos, agents):
    """The intake's answer -> a clean specification, or ValueError saying what is wrong with it."""
    s = {**spec, **{k: v for k, v in preset.items() if k in ("kind", "effort", "deadline", "rhythm", "done", "repo")}}
    if s.get("kind") not in KINDS:
        raise ValueError(f"the intake chose no known kind ({s.get('kind')!r})")
    done = [str(d).strip() for d in s.get("done") or [] if len(str(d).split()) >= 3]
    if not done:
        raise ValueError("the intake wrote no checkable definition of done")
    qs = TC.first([str(q).strip() for q in s.get("questions") or [] if str(q).strip()], QUESTIONS, "intake questions")  # cap: untrusted (its prompt names the limit)
    plan = []
    for st in TC.first(s.get("plan") or [], STEPS, "plan steps"):  # cap: untrusted (its prompt names the limit)
        a = str(st.get("agent", ""))
        named = a and a not in agents and a != "new"   # TSK-15: an agent the intake names that does not exist = no agent fits
        lp = st.get("loop") if isinstance(st.get("loop"), dict) else None   # TRL-08: a check's fix loop, checked by the graph
        plan.append({**({"loop": {"to": lp.get("to"), "max": lp.get("max", 2)}} if lp else {}),
                     "step": str(st.get("step", "")).strip(), "agent": a if a in agents or a == "new" else "new" if named else "mission",
                     "after": [int(x) for x in st.get("after") or [] if str(x).isdigit()],
                     **({"each": [str(x).strip() for x in st["each"] if str(x).strip()][:8]} if st.get("each") else {}),   # cap: list (TSK-22's fan-out, as CD.EACH)
                     "why": str(st.get("why", "")).strip() + (f" (the intake named {a!r}, which is no agent: a temporary agent is written for it)" if named
                                                              else "" if a in agents or a == "new" else " (no agent named: the mission agent takes it)")})
    chosen = preset.get("agents") or []
    for i, st in enumerate(plan):                      # TSK-30: the owner's agents do the steps; the plan says so
        if not chosen:
            break
        if st["agent"] in chosen:
            st["why"] += " (your choice)"
        else:
            was, st["agent"] = st["agent"], chosen[i % len(chosen)]
            st["why"] = f"{st['why']} (your choice: {st['agent']} instead of {was})".strip()
    if s["kind"] == "code_question" and not chosen:     # TSK-45: every step of a code question on an agent that reads the repository
        readers = code_readers()
        for st in plan:
            if st["agent"] not in readers:
                was, st["agent"] = st["agent"], CODE_AGENT
                st["why"] = f"{st['why']} (a code question: {was} cannot read the repository, so the {CODE_AGENT} takes it)".strip()
    if preset.get("model"):
        for st in plan:
            st["model"] = preset["model"]
    if not plan and not qs:
        raise ValueError("the intake wrote no plan")
    r = s.get("rhythm") or {"type": "once"}
    if r.get("type") == "schedule" and not M.valid_schedule(str(r.get("schedule", ""))):
        r = {"type": "once"}
    if r.get("type") == "event":
        r = {"type": "event", "triggers": M.X.clean_triggers(r.get("triggers"))}
    repo = s.get("repo") if s.get("repo") in repos else None
    if KINDS[s["kind"]] in ("build", "change") and not repo and not qs:
        qs = ["Which repository should this change go into: " + ", ".join(repos) + "?"]
    title = title_of(s.get("title") or s.get("goal")) or "Task"
    return {"title": title if len(title) >= 3 else "Task " + title, "goal": str(s.get("goal") or title).strip(), "kind": s["kind"],
            "done": done, "plan": plan, "questions": qs, "rhythm": r, "repo": repo,
            "effort": s.get("effort") if s.get("effort") in EFFORTS else "standard",
            "deadline": s.get("deadline") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.get("deadline") or "")) else None,
            **{k: preset[k] for k in ("ref", "history") if preset.get(k)}}             # TSK-48: kept as the owner set them


resting, waits = {}, {}                          # task id -> when its intake may try again / how often it waited (RUN-R9)
LIMIT_REST_S, MAX_WAITS = 1800, 16                # limit: waits (an intake at a usage limit tries again every 30 min, 16 times, as missions do)


def wait_for_limit(c, tid, what):
    """RUN-R9: an intake or a specification that met the usage limit waits for it, like every other job (ops/AGENTS.md),
    instead of failing the task for good. -> False after MAX_WAITS waits: then it fails and says why."""
    n = waits[tid] = waits.get(tid, 0) + 1
    if n > MAX_WAITS:
        return False
    resting[tid] = time.time() + LIMIT_REST_S
    at = (dt.datetime.now().astimezone() + dt.timedelta(seconds=LIMIT_REST_S)).strftime("%H:%M")
    put(c, tid, status="intake", error=f"{what} waits for the subscription's usage limit; it tries again at {at}")
    return True


def intake(c, tid, ask=None):
    """One task through the intake agent (its own key, vk-intake), then to its door or to the owner."""
    import os
    import runtime as RTM
    t = row(c, tid)
    if t["kind"] == "change" and (t["spec"].get("repo") or (t["spec"].get("preset") or {}).get("repo")):    # CHG-02: its own specification
        import changes as CH
        return CH.specify(c, t, ask)
    repos, agents = B_repos(), cards()
    run, t0 = f"task-intake:{tid}-{len(t['answers'])}", time.time()      # one run per pass (a pass after answers is another)
    RTM.start(run, "intake", f"Task #{tid}: specification", detail=t["text"], ref=f"task:{tid}")   # under the task's run (TSK-26)
    RTM.set_ref(run, "intake")
    try:
        raw = (ask or (lambda p: M.ask_json(p, os.environ["VK_INTAKE"])))(intake_prompt(t, repos, agents))
        s = validate(raw, t["spec"].get("preset") or {}, repos, agents)
    except Exception as e:                             # a failed intake says why on the task; the owner can retry it
        if M.paused(str(e)) and wait_for_limit(c, tid, "The intake"):
            RTM.end(run, "intake", "limit", str(e), time.time() - t0)
            RTM.set_ref(None)
            return
        put(c, tid, status="failed", error=f"intake: {type(e).__name__}: {e}")
        M.event("task", "", f"Task #{tid} could not be planned: {e}", title="Tasks")
        RTM.end(run, "intake", "limit" if M.paused(str(e)) else "failed", str(e), time.time() - t0)
        RTM.set_ref(None)
        return
    RTM.end(run, "intake", "done", f"{s['kind']}: {len(s['done'])} done criteria, {len(s['plan'])} steps, {len(s['questions'])} questions",
            time.time() - t0)
    RTM.set_ref(None)
    if (s["kind"] in ("coding", "change") and s["repo"] and not s["questions"] and not str(t.get("source") or "").startswith("trial:")
            and not (t["spec"].get("preset") or {}).get("agents")):     # the owner's own agents keep their plan
        import changes as CH                           # CHG-01: a sentence that changes code is a change request
        put(c, tid, kind="change", spec={**t["spec"], "repo": s["repo"], "change": t["spec"].get("change") or {}})
        return CH.specify(c, row(c, tid), ask)
    spec = {**t["spec"], **s}
    put(c, tid, title=s["title"], goal=s["goal"], kind=s["kind"], done=s["done"], rhythm=s["rhythm"], effort=s["effort"],
        deadline=s["deadline"], spec=spec, questions=s["questions"], error=None)
    if s["questions"]:
        put(c, tid, status="needs_answer")
        M.notify_task(tid, s["title"], "has a question for you" if len(s["questions"]) == 1 else "has two questions for you")
    elif t["autonomy"] == "ask":
        put(c, tid, status="waiting_approval")
        M.notify_task(tid, s["title"], "waits for your OK on its plan")
    elif s["rhythm"].get("type") == "after" or t["after"]:
        put(c, tid, status="after")
    else:
        dispatch(c, row(c, tid))


def conducted(t):
    """TSK-21: every planned task runs as a plan graph under the Conductor, one step or many, once, on a schedule or on
    an event; coding work needs a builder step to change code; a briefing gets the desk's plan (TSK-22) and a price
    watch its shopping agent's check. A plan with an agent that cannot do a step goes to its door."""
    import conductor as CD
    if t["rhythm"].get("type") not in ("once", "after", "schedule", "event") or t["kind"] == "cleanup":
        return False                                   # a cleanup analysis is ops/cleanup.py's (the phone's or the PC's facts)
    if t["kind"] in ("briefing", "shopping") or t["spec"].get("wiki"):
        return True
    plan, agents = t["spec"].get("plan") or [], CD.cards()
    return (bool(plan) and (t["kind"] != "coding" or any(p["agent"] == CD.BUILDER for p in plan))
            and all(p["agent"] == CD.NEW or (p["agent"] in agents and CD.runs_steps(agents[p["agent"]])) for p in plan))


def briefing_brief(t):
    """FND-77: the desk drafts its writer's notes from this; a plan for agents only confused it."""
    s = t["spec"]
    return (f"{t['goal']}\n\nWhat each report must deliver:\n" + "\n".join(f"- {d}" for d in t["done"])
            + ("\n\nThe owner's answers:\n" + "\n".join(f"- {q}: {a}" for q, a in s["answered"]) if s.get("answered") else "")
            + "\n\nMission Control runs the schedule and delivers each report; the notes are about the content only.")


def door_brief(t):
    """What a door (a mission, a build, a Claude task) is given: the goal, the definition of done, the plan, the answers."""
    s = t["spec"]
    return (f"{t['goal']}\n\nDefinition of done:\n" + "\n".join(f"- {d}" for d in t["done"])
            + ("\n\nPlan:\n" + "\n".join(f"{i + 1}. {p['step']} ({p['agent']}: {p['why']})" for i, p in enumerate(s.get("plan") or []))
               if s.get("plan") else "")
            + ("\n\nThe owner's answers:\n" + "\n".join(f"- {q}: {a}" for q, a in s["answered"]) if s.get("answered") else "")
            + (f"\n\nDeadline: {t['deadline']}" if t["deadline"] else "") + f"\n\n(Task #{t['id']} in Mission Control)")


def shop_agent(c, t, deliver):
    """A price watch's shopping agent (ops/shopping.py: its limits, proposals, purchase approvals, order tracking), made
    once and held by the task: the Conductor runs its checks, at once, on the schedule or on an event, and when a waiting
    proposal reaches its price or date; buying and following an order stay the agent's own runs (TSK-21)."""
    import shop_steps as SS
    s = t["spec"]
    if not s.get("shop"):
        res = M.handle({"action": "create", "type": "shopping", "title": t["title"], "description": door_brief(t), "schedule": "manual",
                        "triggers": [], "once": False, "run_now": False, "deliver": deliver, "task": t["id"]}, M.load_missions(), c)
        m = M.load_missions().get(res.get("slug") or "")
        if not m or m.get("task") != t["id"]:          # a shopping agent of the same name, made minutes ago, is not this one
            raise ValueError(f"a shopping agent “{t['title']}” was made in the last 30 minutes: give the task another title")
        s = {**s, "shop": m["slug"]}
    s = {**s, "plan": SS.shop_plan(t), "intake_plan": s.get("intake_plan") or s.get("plan") or [], "deliver": deliver}
    put(c, t["id"], spec=s)
    return row(c, t["id"])


def watchers(c):
    """The event-triggered tasks under the Conductor, watched with the missions' triggers (ops/mission_extras.py)."""
    table(c)
    out = []
    for r in c.execute("select id from tasks where door='plan' and status in ('scheduled', 'running')").fetchall():
        t = row(c, r["id"])
        if t["rhythm"].get("type") in ("event", "schedule") and t["rhythm"].get("triggers"):   # a briefing's alerts ride along its schedule
            out.append({"slug": f"task-{t['id']}", "title": t["title"], "task": t["id"], "status": "active", "triggers": t["rhythm"]["triggers"]})
    return out


def briefing_topic(c, t, deliver):
    """A briefing task's topic (topics/<slug>/TOPIC.md, drafted and its sources checked once) and the desk's plan, which
    replaces the intake's: the plan the owner sees is the plan that runs (TSK-22)."""
    import desk_steps as DS
    s = t["spec"]
    if not s.get("topic"):
        slug, n = M.slugify(t["title"], M.load_missions()), 2
        while (M.VAULT / "topics" / slug).exists():      # a topic of another task or mission keeps its name
            slug, n = f"{M.slugify(t['title'], {})}-{n}", n + 1
        M.create_briefing({"slug": slug, "schedule": t["rhythm"].get("schedule") or "manual"}, {"title": t["title"], "description": briefing_brief(t)})
        M.vault_commit([f"topics/{slug}"], f"task {t['id']}: the briefing's topic {slug}")
        s = {**s, "topic": slug}
    (meta, _), _ = M.topic_of({"slug": s["topic"], "topic": s["topic"]})
    plan = DS.alert_plan(t) if t["rhythm"].get("type") == "event" else DS.briefing_plan(t, meta)     # on an event: an alert
    s = {**s, "plan": plan, "intake_plan": s.get("intake_plan") or s.get("plan") or [], "deliver": deliver}
    put(c, t["id"], spec=s)
    return row(c, t["id"])


def dispatch(c, t):
    """Hand the task to its door; the door keeps its own approvals (deploy taps, purchases, the AI phone)."""
    if t["kind"] == "change":
        import changes as CH
        return CH.begin(c, t)
    s, door = t["spec"], KINDS.get(t["kind"])
    asked = " ".join([t["text"] or "", t["goal"] or "", *t["done"]])
    deliver = (s.get("preset") or {}).get("deliver") or (["telegram", "app"] + (["email"] if re.search(r"\be-?mail", asked, re.I) else []))   # the owner's choice, else e-mail when the task asked for it
    if conducted(t):
        import conductor as CD
        on_event = t["rhythm"].get("type") == "event"
        try:
            if t["kind"] == "briefing":
                t = briefing_topic(c, t, deliver)
            elif t["kind"] == "shopping":
                t = shop_agent(c, t, deliver)
            elif t["spec"].get("wiki"):
                t = wiki_plan(c, t)
            CD.graph(t["spec"].get("plan") or [])         # refused now, not when the first event comes
            ref = str(t["id"]) if on_event else CD.start(c, t)
        except Exception as e:                           # a plan with a cycle or a step nobody can do is refused (TSK-05);
            put(c, t["id"], status="failed", door="plan", error=f"plan: {e}")   # a topic whose sources fail is said why
            M.event("task", "", f"Task #{t['id']} could not start: {e}", title="Tasks")
            return
        put(c, t["id"], door="plan", ref=ref, status="scheduled" if on_event else "running")   # a scheduled task's first run starts now
        if on_event:                                     # an event-triggered one waits for its first event
            M.event("task", "", f"Task #{t['id']} waits for its trigger ({len(t['spec']['plan'])} steps each time under the Conductor): {t['title']}", title="Tasks")
            return
        sched = f"; then {t['rhythm']['schedule']}" if t["rhythm"].get("type") == "schedule" else ""
        M.event("task", "", f"Task #{t['id']} started: {len(CD.steps(c, t['id']))} steps under the Conductor{sched}: {t['title']}", title="Tasks")
        return
    brief = door_brief(t)
    try:
        if door == "build":
            import builds as B
            res = B.handle({"action": "build_assign", "repo": s.get("repo"), "title": t["title"], "description": brief}, c)
            ref = res.get("build") or res.get("id")
        elif door == "claude":
            import claude_tasks as CT
            res = CT.handle({"action": "claude_task", "question": brief, "repo": s.get("repo") or "", "mode": "ask",
                             "ref": s.get("ref"), "history": s.get("history")}, c)   # TSK-48: a commit and history the owner set
            ref = res.get("task") or res.get("id")
        else:
            r = t["rhythm"]
            req = {"action": "create", "type": MISSION_TYPE.get(t["kind"], "task"), "title": t["title"], "description": brief,
                   "schedule": r.get("schedule") if r.get("type") == "schedule" else "manual",
                   "triggers": r.get("triggers") if r.get("type") == "event" else [], "once": r.get("type") in ("once", "after"),
                   "depth": "deep" if t["effort"] == "deep" else None, "run_now": r.get("type") != "event", "deliver": deliver}
            res = M.handle(req, M.load_missions(), c)
            ref = res.get("slug")
        if not ref:
            raise ValueError(f"the {door} door gave no reference back: {res}")
    except Exception as e:                             # the door refused (no repo, Claude not connected, ...): say so on the task
        put(c, t["id"], status="failed", door=door, error=f"{door}: {e}")
        M.event("task", "", f"Task #{t['id']} could not start: {e}", title="Tasks")
        return
    if c.execute("select id from tasks where door=? and ref=? and id<>?", (door, str(ref), t["id"])).fetchone():
        c.execute("delete from tasks where door=? and ref=? and id<>? and source='door'", (door, str(ref), t["id"]))   # found first by sync
    put(c, t["id"], door=door, ref=str(ref), status="scheduled" if t["rhythm"].get("type") in ("schedule", "event") else "running")
    M.event("task", "", f"Task #{t['id']} started as {door} {ref}: {t['title']}", title="Tasks")


ACTIONS = {"task_create", "task_answer", "task_approve", "task_cancel", "task_retry", "task_run", "task_conduct"}


def stop_at_door(c, t):
    """TSK-47: cancelling a task that has started at its door stops the work there (a work site, 9 Nov 2026: such a task
    could not be cancelled at all, only on another page, and a Claude task nowhere). -> whether it was stopped."""
    door, ref = t["door"], str(t["ref"] or "")
    if door == "claude" and ref.isdigit():
        import claude_tasks as CT
        CT.cancel(c, int(ref), f"its task #{t['id']} was cancelled")
        return True
    if door == "build" and ref.isdigit():
        import builds as B
        b = c.execute("select status from builds where id=?", (int(ref),)).fetchone()
        if not b or b["status"] in ("rejected", "merged", "deployed", "rolled_back"):
            return True                                 # nothing left running there
        if b["status"] in ("queued", "review", "failed"):
            B.handle({"action": "build_reject", "id": int(ref), "reason": f"its task #{t['id']} was cancelled"}, c)
            return True
        return False                                    # a build at work or deploying: on its page
    if door == "mission" and ref:
        m = M.load_missions().get(ref)
        if m and m.get("status") == "active":           # paused, not archived: its files and wiki stay, Resume on its page
            m["status"] = "paused"
            M.save_mission(m)
            M.event("task", ref, f"{m.get('title') or ref} paused: its task #{t['id']} was cancelled", title="Tasks")
        return True
    return False


def conduct(c, t):
    """task_conduct (TSK-21, DEC-37): a briefing or price watch that runs as its mission moves under the Conductor. The
    mission keeps what it holds (the topic, its wiki and the articles it has seen; or the proposals, limits and price
    history) but runs no more by itself; the task runs it on the mission's schedule (or trigger), the next run when it
    is due. A briefing on a schedule with alerts keeps both: its task's rhythm holds the schedule and the triggers."""
    import conductor as CD
    import desk_steps as DS
    import shop_steps as SS
    m = M.load_missions().get(t["ref"] or "")
    if t["door"] != "mission" or not m or m.get("type") not in ("briefing", "shopping") or m.get("status") != "active":
        raise ValueError("only an active briefing or price watch that runs as its mission can move to the Conductor")
    sched = m.get("schedule") if m.get("schedule") not in (None, "", "manual") and not m.get("once") else None
    rhythm = ({"type": "schedule", "schedule": sched, **({"triggers": m["triggers"]} if m.get("triggers") else {})} if sched
              else {"type": "event", "triggers": m["triggers"]} if m.get("triggers") else {"type": "once"})
    s = {**t["spec"], "deliver": m.get("deliver") or ["telegram", "app"], "moved_from": m["slug"],
         "intake_plan": t["spec"].get("intake_plan") or t["spec"].get("plan") or []}
    if m["type"] == "briefing":
        (meta, _), _ = M.topic_of(m)
        s.update(topic=m.get("topic") or m["slug"], plan=DS.alert_plan(t) if rhythm["type"] == "event" else DS.briefing_plan(t, meta))
    else:
        s.update(shop=m["slug"], plan=SS.shop_plan(t))
    CD.graph(s["plan"])                                    # refused before anything changes
    m.update(task=t["id"], schedule="manual", triggers=[])          # its alerts are the task's now (rhythm.triggers)
    M.save_mission(m)
    M.vault_commit([f"missions/{m['slug']}"], f"mission: {m['slug']} runs as task {t['id']} under the Conductor")
    put(c, t["id"], door="plan", ref=str(t["id"]), kind=m["type"], rhythm=rhythm, spec=s, status="scheduled", error=None)
    M.event("task", m["slug"], f"Task #{t['id']} now runs under the Conductor ({len(CD.graph(s['plan']))} steps"
            + (f", {sched}" if sched else "") + f"); the mission {m['title']} keeps its {'topic and wiki' if m['type'] == 'briefing' else 'proposals and limits'}",
            title="Tasks")
    return {"task": t["id"], "steps": len(CD.graph(s["plan"]))}


_NOT_MOVED = set()                                     # the tasks whose move failed: said once, not every pass


def conduct_all(c, missions):
    """TSK-21 (the owner, 8 Nov 2026: "clear all debt"): one engine for repeating tasks. Every active briefing and price
    watch that still runs as its mission moves under the Conductor, as task_conduct does; the mission keeps its topic,
    wiki, proposals and history. A move that fails is said once and the task keeps running as its mission."""
    moved = []
    for r in c.execute("select id, ref from tasks where door='mission' and status='scheduled'").fetchall():
        m = (missions or {}).get(r["ref"] or "")
        if r["id"] in _NOT_MOVED or not m or m.get("type") not in ("briefing", "shopping") or m.get("status") != "active" or m.get("task"):
            continue
        try:
            conduct(c, row(c, r["id"]))
            moved.append(r["id"])
        except Exception as e:                         # its plan was refused: it stays where it runs, and the owner hears why
            _NOT_MOVED.add(r["id"])
            M.event("task", r["ref"], f"Task #{r['id']} could not move under the Conductor and keeps running as its mission: {e}", title="Tasks")
    return moved


def alerts_to_tasks(c, missions):
    """A briefing moved before 8 Nov 2026 kept its alerts on its mission while its task ran the schedule. Its triggers
    go to the task's rhythm and leave the mission, so one engine watches and runs them. -> [task ids]."""
    moved = []
    for m in (missions or {}).values():
        if not m.get("task") or not m.get("triggers") or m.get("status") != "active":
            continue
        try:
            t = row(c, int(m["task"]))
        except (ValueError, TypeError):
            continue
        if t["door"] != "plan" or t["rhythm"].get("type") != "schedule":
            continue
        put(c, t["id"], rhythm={**t["rhythm"], "triggers": m["triggers"]})
        M.save_mission({**m, "triggers": []})
        M.vault_commit([f"missions/{m['slug']}"], f"mission: {m['slug']}'s alerts are task {t['id']}'s now")
        M.event("task", m["slug"], f"Task #{t['id']} now watches its own alerts ({len(m['triggers'])}), under the Conductor", title="Tasks")
        moved.append(t["id"])
    return moved


def research_titles(c):
    """TSK-49: a briefing planned before 10 Nov 2026 named its research "the last 8 days", a span its runs never kept;
    its plan names the run's window now, as a new one does (each step's prompt has the dates). -> [task ids]."""
    import desk_steps as DS
    old = lambda p: p.get("agent") == "scout" and p.get("each") and str(p.get("step", "")).startswith("Research the last")   # noqa: E731
    out = []
    for r in c.execute("select id from tasks where kind='briefing' and door='plan'").fetchall():
        t = row(c, r["id"])
        plan = t["spec"].get("plan") or []
        if any(old(p) for p in plan):
            put(c, t["id"], spec={**t["spec"], "plan": [{**p, "step": DS.RESEARCH} if old(p) else p for p in plan]})
            out.append(t["id"])
    return out


def handle(req, c):
    table(c)
    a = req["action"]
    if a == "task_create":
        return create(req, c)
    t = row(c, int(req.get("id") or 0))
    if a == "task_answer":
        if t["status"] != "needs_answer":
            raise ValueError("this task asks nothing right now")
        ans = [str(x).strip() for x in req.get("answers") or []]
        if len(ans) != len(t["questions"]) or not all(ans):
            raise ValueError(f"answer each of its {len(t['questions'])} question(s)")
        spec = {**t["spec"], "answered": (t["spec"].get("answered") or []) + [[q, a] for q, a in zip(t["questions"], ans)]}
        put(c, t["id"], answers=ans, spec=spec, status="intake")          # kept: a new pass may ask nothing more
        return {"task": t["id"]}
    if a == "task_approve":
        if t["status"] != "waiting_approval":
            raise ValueError("this task does not wait for your OK")
        put(c, t["id"], status="after" if t["after"] else "planned")
        if not t["after"]:
            dispatch(c, row(c, t["id"]))
        return {"task": t["id"]}
    if a == "task_cancel" and t["door"] == "flow":      # TAX-09: a workflow's own task stops with its workflow
        raise ValueError("it runs from its workflow: switch that off in Workflows (its Active switch)")
    if a == "task_cancel":
        if t["status"] not in OPEN:
            raise ValueError("this task is over already")
        if t["door"] == "plan":                          # the Conductor's own: its steps that have not started never will
            import conductor as CD
            CD.cancel(c, t)
            return {"task": t["id"]}
        if t["ref"] and not stop_at_door(c, t):        # the board must not stop following work that goes on
            raise ValueError(f"it has started as {t['door']} {t['ref']}, which cannot be stopped from here: stop it on that page")
        put(c, t["id"], status="cancelled")
        return {"task": t["id"]}
    if a == "task_retry":
        if t["status"] != "failed" or t["ref"]:
            raise ValueError("only a task that failed before it started can be planned again")
        put(c, t["id"], status="intake", error=None, spec={**t["spec"], "retried": (t["spec"].get("retried") or 0) + 1})
        return {"task": t["id"]}
    if a == "task_conduct":
        return conduct(c, t)
    if a == "task_run" and t["door"] == "flow":         # TAX-09: Run now starts the task's workflow
        import flow_tasks as FT
        return FT.run(c, t)
    if a == "task_run":                                  # TSK-22: run a plan task again now, outside its schedule
        if t["door"] != "plan" or t["status"] not in ("scheduled", "done", "failed"):
            raise ValueError("it is running now" if t["status"] == "running" else "only a planned task that is not running can run again")
        import conductor as CD
        put(c, t["id"], status="running", error=None)
        CD.start(c, row(c, t["id"]), trigger="owner")
        return {"task": t["id"], "run": CD.occ_of(c, t["id"])}
    raise ValueError("unknown task action")


def recover(c, now=None):
    """P6: a planning a restart cut off (task 93 waited 27 h in "planning") is planned again; one older than REPLAN_H
    fails and says why (a day-old alert is not worth starting unasked). -> {task: "replanned" | "failed"}."""
    old = ((now or dt.datetime.now().astimezone()) - dt.timedelta(hours=REPLAN_H)).isoformat(timespec="seconds")
    out = {}
    for r in c.execute("select id, updated from tasks where status='planning'").fetchall():
        if (r["updated"] or "") >= old:
            put(c, r["id"], status="intake")
            out[r["id"]] = "replanned"
        else:
            put(c, r["id"], status="failed", error=f"its planning was cut off by a restart over {REPLAN_H} h ago; Plan it again if it still matters")
            out[r["id"]] = "failed"
        M.log(f"tasks: task {r['id']} was being planned when the runner stopped: {out[r['id']]}")
    return out


def worker():
    """Tasks waiting for the intake, one at a time (one model call each); the runner's main loop never waits on it."""
    c = M.db()
    table(c)
    with lock:
        recover(c)
    while not M.stop.is_set():
        try:
            r = next((x for x in c.execute("select id from tasks where status='intake' order by id").fetchall()
                      if resting.get(x["id"], 0) <= time.time()), None)
            if r:
                with lock:
                    put(c, r["id"], status="planning")
                intake(c, r["id"])
                if row(c, r["id"])["status"] == "planning":   # an intake that ended without a decision
                    put(c, r["id"], status="failed", error="intake ended without a decision")
                continue
        except Exception as e:                         # one bad task must not stop the others; it is logged
            M.log(f"tasks worker: {type(e).__name__}: {e}")
        M.rest(c, "task intake", 3)


FIELDS = ("id", "title", "goal", "text", "kind", "door", "ref", "done", "effort", "deadline", "autonomy", "rhythm", "after", "questions",
          "answers", "status", "source", "created", "updated", "error", "verdict", "tokens", "cost", "owner")
_published = {}                                       # task id -> the text last written (a file is rewritten only when it changes)


def detail(c, tid):
    """APP-35: a task page's data: the task as the board shows it, every run (occurrence) with its verdict, and the steps of
    every run with their full results. The app adds what the run record holds (agents, actions, memory)."""
    import conductor as CD
    t = row(c, tid)
    if t["door"] == "flow":                            # TAX-09: its runs are its workflow's runs, their steps the workflow's
        import flow_tasks as FT
        x = FT.extra(c, t)
        return {k: t.get(k) for k in FIELDS} | {"judgement": None, "result": None, "plan": x["plan"], "runs": x["runs"], "steps": x["steps_of"],
                                                "checkpoints": [], "workflow": x["workflow"], "result_view": x.get("result_view"), "agent": x.get("agent"),
                                                "result_href": x.get("result_href"), "result_label": x.get("result_label"), "asks": x.get("asks", 0),
                                                "area": x.get("area"), "asked": asked_by(t)}
    occs = CD.occurrences(c, tid) if t["door"] == "plan" else []
    sp = t["spec"]
    return ({k: t.get(k) for k in FIELDS} | {"area": area_of(c, t), "asked": asked_by(t), "judgement": sp.get("judgement"), "plan": sp.get("plan") or [], "result": sp.get("result"),
                                           "repo": sp.get("repo"), "budget": sp.get("budget"), "shop": sp.get("shop"), "topic": sp.get("topic"), "change": sp.get("change"),
                                           "wiki": sp.get("wiki"), "runs": occs, "checkpoints": sp.get("checkpoints") or [],
                                           "steps": {str(o["occ"]): CD.steps(c, tid, o["occ"]) for o in occs}})


def publish(c, ids):
    """Write the task pages' files of these tasks (public/tasks/<id>.json); a broken one is logged, never raised."""
    if getattr(M, "PUBLIC", None) is None:            # a runner without its public folder (tests): nothing to write
        return
    d = M.PUBLIC / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    for tid in ids:
        try:
            text = json.dumps(detail(c, tid), ensure_ascii=False, default=str)
            if _published.get(tid) != text:
                (d / f"{tid}.json.tmp").write_text(text)
                (d / f"{tid}.json.tmp").replace(d / f"{tid}.json")
                _published[tid] = text
        except Exception as e:
            M.log(f"tasks: task {tid}: page data not written: {type(e).__name__}: {e}")


def state(c):
    """The task board: every open task, every stopped change and every task of the last 7 days, newest first (TSK-04). Each also gets its task
    page's file; the first call writes every older task's once (APP-35)."""
    table(c)
    since = (dt.datetime.now().astimezone() - dt.timedelta(seconds=WINDOW)).isoformat(timespec="seconds")
    rows = c.execute(f"select id from tasks where status in ({','.join('?' * len(OPEN))}, 'planning') or updated >= ? "
                     "or (kind='change' and status='failed' and door='plan') order by id desc",   # a stopped change waits for the owner's answer (GEN-02)
                     (*OPEN, since)).fetchall()
    out = []
    import conductor as CD
    import flow_tasks as FT
    import n8n_jobs as NJ
    try:
        held = FT.folded(c)                           # TAX-09: the work a flow task holds as its steps is not a task of its own
    except Exception as e:                             # logged; the board shows them as before
        M.log(f"tasks: flow tasks: {type(e).__name__}: {e}")
        held = set()
    rows = [r for r in rows if r["id"] not in held]
    stepped = CD.state(c, [r["id"] for r in rows if c.execute("select door from tasks where id=?", (r["id"],)).fetchone()["door"] == "plan"])
    when = NJ.index()                                 # WFL-09: a task's next run is its n8n workflow's
    for r in rows:
        t = row(c, r["id"])
        last = nxt = None
        if t["door"] == "mission" and t["ref"]:       # a mission task shows its last run and its next one, not only "scheduled"
            run = c.execute("select id, status, summary, output, started, ended from runs where slug=? order by id desc limit 1",
                            (t["ref"],)).fetchone()
            last = dict(run) if run else None
            if t["status"] in ("scheduled", "running"):
                nxt = NJ.next_run("task", t["id"], idx=when)
        runs = []
        if t["door"] == "flow":                       # TAX-09: its workflow's runs, the latest one's steps, its next run
            x = FT.extra(c, t, RUNS)
            out.append({k: t.get(k) for k in FIELDS} | {"judgement": None, "plan": x["plan"], "steps": x["steps"], "result": None,
                                                        "last_run": x["last_run"], "next_run": x["next_run"], "runs": x["runs"], "shop": None,
                                                        "topic": None, "workflow": x["workflow"], "result_view": x.get("result_view"), "agent": x.get("agent"),
                                                        "result_href": x.get("result_href"), "result_label": x.get("result_label"), "asks": x.get("asks", 0),
                                                        "area": x.get("area"), "asked": asked_by(t)})
            continue
        if t["door"] == "plan":                       # the Conductor's: its latest occurrence, and the next on its schedule
            runs = CD.occurrences(c, t["id"])
            occ = (runs or [None])[0]
            if occ:
                res = occ["result"] or ""
                last = {"id": occ["occ"], "status": {"done": "ok"}.get(occ["status"], occ["status"]), "started": occ["started"],
                        "ended": occ["ended"], "live": occ["live"], "output": res if res.startswith("tasks/") else None,
                        "summary": (f"Run {occ['occ']}: " if occ["occ"] > 1 else "") + (("failed: " + res) if occ["status"] == "failed" else
                                                                                         "found nothing new" if occ["verdict"] == "quiet" else
                                                                                         "done" if occ["status"] == "done" else occ["status"] or "")}
            if t["rhythm"].get("type") == "schedule" and t["status"] in ("scheduled", "running"):
                nxt = NJ.next_run("task", t["id"], idx=when)
            runs = runs[:RUNS]                            # cap: list (the card's run history; every run stays in task_occ)
        out.append({k: t.get(k) for k in FIELDS} | {"judgement": t["spec"].get("judgement")}
                   | {"plan": t["spec"].get("plan") or [], "steps": stepped.get(t["id"], []), "result": t["spec"].get("result"),
                      "last_run": last, "next_run": nxt, "runs": runs, "shop": t["spec"].get("shop"), "topic": t["spec"].get("topic"),
                      "area": area_of(c, t), "asked": asked_by(t), **crew_result(t)})
    agents = [{k: a.get(k) for k in ("id", "name", "purpose", "harness", "model")} for a in CD.cards().values() if CD.runs_steps(a)]
    publish(c, [t["id"] for t in out] if _published else [r["id"] for r in c.execute("select id from tasks")])
    return {"tasks": out, "task_agents": agents}                 # TSK-30: the agents the composer offers


def gate(path=None):
    """Phase 1's gate (TSK-03): each one-sentence task of the set gets a specification with a checkable definition of
    done and no more than two questions. One intake call per task; nothing is started."""
    import os
    sys.path.insert(0, str(ROOT / "ops"))
    import missions as MM
    globals()["M"] = MM
    cases = yaml.safe_load((path or ROOT / "eval/tasks-v1.yaml").read_text())["tasks"]
    repos, agents, rows, ok = B_repos(), cards(), [], 0
    for case in cases:
        t = {"text": case["text"], "spec": {}, "questions": [], "answers": []}
        try:
            s = validate(MM.ask_json(intake_prompt(t, repos, agents), os.environ["VK_INTAKE"]), {}, repos, agents)
            good = s["kind"] in case["kinds"] and bool(s["done"]) and len(s["questions"]) <= QUESTIONS
            rows.append({"text": case["text"], "kind": s["kind"], "done": s["done"], "questions": s["questions"], "plan": s["plan"], "pass": good})
        except Exception as e:                         # a failed case is a failed gate case, with its reason
            good = False
            rows.append({"text": case["text"], "error": f"{type(e).__name__}: {e}", "pass": False})
        ok += good
        print(f"{'PASS' if good else 'FAIL'}  {case['text']}", flush=True)
    out = ROOT / "eval/results" / f"{time.strftime('%Y%m%d-%H%M%S')}-tasks-gate.json"
    out.write_text(json.dumps({"set": "eval/tasks-v1.yaml", "passed": ok, "total": len(cases), "cases": rows}, indent=1, ensure_ascii=False))
    print(f"{ok} of {len(cases)} passed; {out.relative_to(ROOT)}")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["gate"]:
        sys.exit(gate())
    sys.exit(__doc__)
