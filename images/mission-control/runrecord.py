"""The agent runtime's record: one event stream for every agent in the stack (design v2, docs/OBSERVABILITY.md).

Sources send events here, nothing else stores them:
  - the Hermes plugin (config/hermes/plugins/aistack-runtime): every Hermes profile, straight over mcnet;
  - Claude Code hooks in the builder sandbox, the AI phone and the mail connector: they spool JSONL files that the
    runner forwards (ops/runtime.py), because those containers can't reach Mission Control;
  - the runner itself: mission runs, builds, Claude tasks and Crew jobs (start, stage, end).
One event: {run, ref?, agent, source, ts, kind, title?, detail?, tokens?, ms?, status?, data?}. `kind` is the format
the timelines already use (obs_core): run | llm | call | result | error | say | think | mcp | conn | stage | end.
`ref` ties a run to what it belongs to (mission-run:15, build:7, chat:abc, claude-task:3): a run view shows the run
and every run that refers to it, merged by time.

Stored in SQLite next to the app's other data. Full events are kept 90 days, a run's summary for good. A run without
an event for STALL_S is closed as "stalled" by the watchdog: every run ends exactly once (done | failed | stopped |
stalled | limit).
"""
import json
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

import obs_core as O

DB = Path(os.environ.get("RUNTIME_DB", "/missions/app/runtime.db"))
STALL_S = 20 * 60              # a phone approval waits up to 15 min, a research call up to 10: longer means stuck
WAIT_S = 3 * 3600             # a run parked on a declared wait (the Windows disk scan) is not stuck until this long
CUT_OFF_S = 5 * 60            # the watchdog looks every 30 seconds: this long past its limit means it wasn't running either
KEEP_EVENTS_S = 90 * 86400
END_STATES = ("done", "failed", "stopped", "stalled", "limit")
# limit: drops, one step's detail past this in the run record, marked
MAX_DETAIL = 20000

# The OpenTelemetry GenAI names (semantic conventions, still in development: mapped here only)
OTEL = {"run": "invoke_agent", "llm": "chat", "call": "execute_tool", "result": "execute_tool", "error": "execute_tool",
        "mcp": "execute_tool", "say": "chat", "think": "chat", "stage": "invoke_workflow", "end": "invoke_agent"}

_lock = threading.Lock()                 # one writer at a time
_open = threading.Lock()                 # opening connections
_db = None                               # {thread id: its connection}; None opens fresh ones (tests point DB elsewhere)


def _connect():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=wal")
    return c


def db():
    """This thread's own connection (FND-88): one connection shared by the server's request threads mixed up the reads
    of requests that came together (sqlite's "bad parameter or other API misuse", a run read back as None), which an
    agent's page, asking for its runs and its room at once, hit every time."""
    global _db
    me = threading.get_ident()
    with _open:
        if _db is None:
            DB.parent.mkdir(parents=True, exist_ok=True)
            c = _connect()
            c.executescript("""
          create table if not exists runs (run text primary key, ref text, agent text, source text, title text,
            started real, last real, ended real, end_state text, manifest text, drift text, box text, summary text);
          create table if not exists events (id integer primary key, run text, ts real, kind text, title text,
            detail text, data text);
          create index if not exists ev_run on events(run, id);
          create index if not exists runs_ref on runs(ref);
          create index if not exists runs_open on runs(ended);
        """)
            _db = {me: c}
        if me not in _db:
            _db[me] = _connect()
        return _db[me]


CHAT_TITLE = None              # set by server.py: chat id → its title
AGENT_NAME = {"main": "Hermes", "mission": "Hermes (tasks)", "scout": "Scout", "curator": "Curator", "builder": "Builder (ChatGPT)",
              "claude-builder": "Claude Code (build)", "claude-task": "Claude Code", "claude-review": "Claude Code (review)",
              "claude-maintainability": "Claude Code (crew review)", "ai-phone": "AI phone", "mail": "Gmail"}


def name_of(r, c=None):
    """A run's name for people: "Chat · <chat title>", "Mission · RAM upgrade · run 18", "Build #8: …", "Claude task #4: …"."""
    run, ref, title, agent = r["run"], r["ref"] or "", (r["title"] or "").strip(), r["agent"] or ""
    who = AGENT_NAME.get(agent, agent)
    if ref.startswith("chat:"):
        ct = None
        try:
            ct = CHAT_TITLE(ref[5:]) if CHAT_TITLE else None
        except Exception:
            pass
        return f"Chat · {ct or title or 'Hermes'}"
    if ref and c is not None:
        p = c.execute("select * from runs where run=?", (ref,)).fetchone()
        if p:
            return f"{who} · in {name_of(p, c)}"
    if run.startswith(("phone:", "mail:")):
        t = time.strftime("%d %b %H:%M", time.localtime(r["started"]))
        return f"{who} · session from {t}"
    if run.startswith(("hermes:", "claude:")):
        return f"{who} · {title}" if title else f"{who} · session {run.split(':')[2][:8]}"
    return title or run


def otel_name(e):
    """The span name an OTel GenAI exporter would use for this event."""
    op = OTEL.get(e.get("kind"), "execute_tool")
    return f"{op} {e.get('title')}" if op == "execute_tool" and e.get("title") else op


def _clip(v):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return TC.cut(s, MAX_DETAIL)  # cap: store (textcap.STORE; the app folds long ones)


def malformed(e):
    """Why an event cannot be stored, or "" (it is skipped and counted, never the batch's end)."""
    if not isinstance(e, dict):
        return f"not an object: {type(e).__name__}"
    try:
        float(e.get("ts") or 0)
    except (TypeError, ValueError):
        return "ts is not a number"
    if e.get("data") is not None and not isinstance(e.get("data"), dict):
        return "data is not an object"
    if any(e.get(k) is not None and not isinstance(e.get(k), (str, int, float)) for k in ("run", "kind", "title", "detail", "agent", "ref", "run_title")):
        return "a text field is not text"
    return ""


def ingest(batch):
    """Store a batch of events; open runs on first sight, close them on their end event. → number stored."""
    n, closed, bad = 0, [], 0
    with _lock:
        c = db()
        for e in batch if isinstance(batch, list) else [batch]:
            why = malformed(e)                            # review APP-R9: one such event made the whole batch fail, for good
            if why:
                bad += 1
                if bad == 1:
                    print(f"run record: an event refused ({why}); the rest of the batch is stored", flush=True)
                continue
            run = str(e.get("run") or "")[:120]  # cap: id
            kind = str(e.get("kind") or "")[:20]  # cap: id (an event kind is a short word)
            if not run or not kind:
                continue
            ts = float(e.get("ts") or time.time())
            row = c.execute("select ended, end_state, manifest from runs where run=?", (run,)).fetchone()
            if not row:
                c.execute("insert into runs (run, ref, agent, source, title, started, last) values (?,?,?,?,?,?,?)",
                          (run, e.get("ref") or _infer_ref(c, e.get("agent"), e.get("run_title"), ts), e.get("agent"), e.get("source"), (e.get("run_title") or "")[:1000], ts, ts))  # cap: id
            elif row["ended"] and row["end_state"] == "stalled" and e.get("source") != "watchdog":
                if kind == "end":                         # the watchdog only guessed: the source's own end replaces "stalled"
                    c.execute("update runs set ended=null, end_state=null where run=?", (run,))
            elif row["ended"]:
                continue                                  # a closed run stays closed: late events and a second end are dropped
            if e.get("ref"):
                c.execute("update runs set ref=coalesce(ref, ?) where run=?", (e["ref"], run))
            if e.get("run_title"):
                c.execute("update runs set title=coalesce(nullif(title,''), ?) where run=?", (e["run_title"][:1000], run))  # cap: id
            if kind == "run" and e.get("data", {}).get("manifest"):
                man = e["data"]["manifest"]
                c.execute("update runs set manifest=?, box=? where run=?", (json.dumps(man), json.dumps(e["data"].get("box")) if e["data"].get("box") else None, run))
                c.execute("update runs set drift=? where run=?", (json.dumps(drift(c, run, e.get("agent"), man)), run))
            data = {k: e[k] for k in ("tokens", "ms", "status") if e.get(k) is not None}
            data.update(e.get("data") or {})
            c.execute("insert into events (run, ts, kind, title, detail, data) values (?,?,?,?,?,?)",
                      (run, ts, kind, TC.cut((e.get("title") or ""), 200), _clip(e.get("detail") or ""), json.dumps(data, default=str)))  # cap: preview
            c.execute("update runs set last=max(last, ?) where run=?", (ts, run))
            if kind == "end":                             # TSK-43: the caller's call may have come in after the session opened
                o = c.execute("select agent, started, ref from runs where run=?", (run,)).fetchone()
                if o["agent"] in TOOL_RUNS and not o["ref"]:
                    c.execute("update runs set ref=? where run=?", (_tool_caller(c, o["agent"], o["started"]), run))
            ref = c.execute("select ref from runs where run=?", (run,)).fetchone()["ref"]
            for _ in range(3):                            # the parents (mission run, build) are alive while their agents work
                if not ref:
                    break
                c.execute("update runs set last=max(last, ?) where run=? and ended is null", (ts, ref))
                up = c.execute("select ref from runs where run=?", (ref,)).fetchone()
                ref = up["ref"] if up else None
            if kind == "end":
                state = e.get("status") if e.get("status") in END_STATES else "done"
                c.execute("update runs set ended=?, end_state=? where run=? and ended is null", (ts, state, run))
                closed.append(run)
            n += 1
        c.commit()
    for r in closed:
        summarise(r)
        trace(r)
    return n


def tokens_by_agent(days=30):
    """{agent id: tokens of its runs in `days`, with the runs that refer to them (a crew job's Claude task)}."""
    c = db()
    since = time.time() - days * 86400
    out = {}
    for r in c.execute("select r.agent, coalesce(p.agent, r.agent) owner, e.data from events e join runs r on r.run=e.run "
                       "left join runs p on p.run=r.ref where e.kind='llm' and e.ts>?", (since,)):
        try:
            t = json.loads(r["data"] or "{}").get("tokens") or {}
        except ValueError:
            continue
        who = str(r["owner"] or "").removeprefix("crew:")
        out[who] = out.get(who, 0) + int(t.get("in", 0)) + int(t.get("out", 0))
    return out


TASK_RUN = re.compile(r"^task:\d+(\.\d+)?$")       # a task's run under the Conductor (TSK-26)
TREE_DELAY = 60                                    # seconds before a task's run is exported: its agents' last events arrive


def tree_of(run):
    """TSK-26: a task's run and every run inside it, with their events -> (runs, {run: events})."""
    c = db()
    rows = c.execute("""with recursive t(run) as (select ? union select r.run from runs r join t on r.ref = t.run)
                        select run, ref, agent, title, started, ended from runs where run in (select run from t)""", (run,)).fetchall()
    runs, evs = [dict(r) for r in rows], {}
    for r in runs:
        evs[r["run"]] = [{"ts": e["ts"], "kind": e["kind"], "title": e["title"], "detail": e["detail"],
                          "tokens": json.loads(e["data"] or "{}").get("tokens"), "status": json.loads(e["data"] or "{}").get("status")}
                         for e in c.execute("select ts, kind, title, detail, data from events where run=? order by id", (r["run"],))]
    return runs, evs


def trace(run):
    """A Claude Code run (outside the gateway, so LiteLLM never traced it) goes to Phoenix as one trace (otlp.py, SWM-79);
    a task's run under the Conductor as one trace tree of its steps and their agents, a minute after it ends (TSK-26)."""
    try:
        import otlp
        if TASK_RUN.match(run):
            otlp.export_later(lambda: otlp.tree_spans(run, *tree_of(run)), delay=TREE_DELAY)
            return True
        c = db()
        r = c.execute("select * from runs where run=?", (run,)).fetchone()
        if not r or r["source"] != "claude":
            return False
        evs = []
        for e in c.execute("select ts, kind, title, detail, data from events where run=? order by id", (run,)):
            d = json.loads(e["data"] or "{}")
            evs.append({"ts": e["ts"], "kind": e["kind"], "title": e["title"], "detail": e["detail"], "tokens": d.get("tokens"), "status": d.get("status")})
        otlp.export_later(otlp.spans_of(run, r["agent"] or "claude", evs, r["title"] or "", r["ref"]))
        return True
    except Exception:
        return False


ASKED_S = 1800                                         # a research question's scout run starts within 30 min of the call that asked it
QUESTION = re.compile(r'"question":\s*"((?:[^"\\]|\\.)*)')
STEP_HEAD = re.compile(r"^\[run: (task:\d+(?:\.\d+)?:step:\d+)\]")   # a Conductor step's Hermes prompt starts with its run


def _words(s, n=100):
    return " ".join(str(s or "").split())[:n]           # cap: id (the question's start is enough to tell two apart)


def _asked_by(c, title, ts):
    """The run whose research call asked exactly this question (a scout run's title is the question it was given), or
    None. Exact where a guess by time is not: a mission's research that started while a task's scout step was live went
    under that step (FND-111)."""
    head = _words(title)
    if len(head) < 20:
        return None
    for r in c.execute("select run, detail from events where kind='call' and title like '%research_research' and ts>=? and ts<=? "
                       "order by ts desc", (ts - ASKED_S, ts + 5)):
        try:
            q = (json.loads(r["detail"] or "{}") or {}).get("question")
        except (ValueError, AttributeError):         # a long call's arguments are kept cut: the question's start is there
            m = QUESTION.search(r["detail"] or "")
            q = json.loads(f'"{m.group(1)}"') if m else ""
        if _words(q) == head:
            return r["run"]
    return None


def reparent_research(since):
    """Put each scout run since <since> that answered a research call under the run that asked it (FND-111: the guess had
    filed some under another task's live scout step). -> [(run, old ref, new ref)]."""
    c, moved = db(), []
    with _lock:
        for r in c.execute("select run, ref, title, started from runs where agent='scout' and started>=?", (since,)).fetchall():
            asker = _asked_by(c, r["title"], r["started"])
            if asker and asker != r["ref"] and asker != r["run"]:
                c.execute("update runs set ref=? where run=?", (asker, r["run"]))
                moved.append((r["run"], r["ref"], asker))
        c.commit()
    return moved


# TSK-43: a tool's session (mail, the AI phone) opens on the first call it serves; the caller's run recorded that call a
# moment before. The tool can't see who called it, the record can. A session with no such call (the phone's own
# reconnects) has no caller.
TOOL_RUNS = {"mail": ("mail:%", ("%mail%",)), "ai-phone": ("phone:%", ("%phone%", "%AI phone%"))}
TOOL_LEAD = 30                                      # seconds: how long before the session a caller's call may be


def _tool_caller(c, agent, ts):
    own, pats = TOOL_RUNS[agent]
    r = c.execute(f"""select run from events where kind in ('call', 'wait', 'stage') and run not like ? and ts between ? and ?
                      and ({' or '.join(['title like ?'] * len(pats))}) order by ts desc limit 1""",
                  (own, ts - TOOL_LEAD, ts + 2, *pats)).fetchone()
    return r["run"] if r else None


def _infer_ref(c, agent, title="", ts=None):
    """`hermes -z` runs inside Hermes' resident process, so AISTACK_REF from `docker exec` doesn't reach the plugin.
    A scout run that answers a research call belongs to the run that asked (exact, by its question). Otherwise: missions
    run one at a time, so a mission-profile run belongs to the live mission run, and a scout run (research) to the live
    mission agent, else the live mission run, else the live chat turn that asked for it; a live Conductor step of the
    same agent comes first: the step started the run, so its tokens count to the task. A step's prompt that names its run
    (FND-114: two scout steps started together could be swapped by the guess) is exact and comes before all of it."""
    if agent in TOOL_RUNS:
        return _tool_caller(c, agent, ts or time.time())
    m = STEP_HEAD.match(title or "")
    if m and c.execute("select 1 from runs where run=?", (m[1],)).fetchone():
        return m[1]
    if agent == "scout":
        asker = _asked_by(c, title, ts or time.time())
        if asker:
            return asker
    r = c.execute("select run from runs where ended is null and run like 'task:%:step:%' and agent=? order by last desc limit 1",
                  (agent or "",)).fetchone()
    if r:
        return r["run"]
    order ={"mission": ("mission-run:%",), "scout": ("hermes:mission:%", "mission-run:%", "hermes:main:%")}.get(agent or "")
    for pat in order or ():
        r = c.execute("select run from runs where ended is null and run like ? order by last desc limit 1", (pat,)).fetchone()
        if r:
            return r["run"]
    return None


def drift(c, run, agent, man):
    """What changed against the previous run of the same agent: model, tool count, connected tool servers."""
    prev = c.execute("select manifest from runs where agent=? and run<>? and manifest is not null order by started desc limit 1",
                     (agent, run)).fetchone()
    if not prev:
        return []
    p, out = json.loads(prev["manifest"]), []
    if p.get("model") and man.get("model") and p["model"] != man["model"]:
        out.append(f"model {p['model']} → {man['model']}")
    if p.get("tool_count") and man.get("tool_count") is not None and man["tool_count"] < p["tool_count"]:
        out.append(f"{p['tool_count'] - man['tool_count']} fewer tools than last time ({man['tool_count']})")
    if p.get("card") and man.get("card") and p["card"] != man["card"]:      # SWM-25: config/agents.yaml changed for it
        out.append(f"agent card changed ({p['card']} → {man['card']})")
    lost = sorted(set(p.get("mcp") or []) - set(man.get("mcp") or []))
    if lost:
        out.append("tool servers not connected: " + ", ".join(lost))
    return out


def events_of(run, after=0, with_children=True):
    c = db()
    runs, todo = [run], [run] if with_children else []
    while todo and len(runs) < 200:                       # the agents inside, and theirs (a mission's agent → its scouts)
        kids = [r["run"] for r in c.execute(f"select run from runs where ref in ({','.join('?' * len(todo))})", todo)]
        todo = [k for k in kids if k not in runs]
        runs += todo
    q = f"select e.*, r.agent from events e join runs r on r.run=e.run where e.run in ({','.join('?' * len(runs))}) and e.id>? order by e.ts, e.id"
    out = []
    for r in c.execute(q, (*runs, after)):
        d = json.loads(r["data"] or "{}")
        out.append({"id": r["id"], "run": r["run"], "agent": r["agent"], "ts": r["ts"], "kind": r["kind"], "title": r["title"],
                    "detail": r["detail"], **{k: d.pop(k) for k in ("tokens", "ms", "status") if k in d}, "data": d})
    return out


def view(run):
    """Everything the two panes show: the run, its events, what it touched, problems, stats."""
    c = db()
    r = c.execute("select * from runs where run=?", (run,)).fetchone() \
        or c.execute("select * from runs where run like ? order by started desc limit 1", (run + ":%",)).fetchone() \
        or c.execute("select * from runs where ref=? order by started desc limit 1", (run,)).fetchone()   # chat:<id>: its last turn
    if not r:
        return None
    run = r["run"]
    ev = events_of(run)
    t0 = r["started"]
    for e in ev:
        e["t"] = round(e["ts"] - t0, 1)
    children = [dict(x) for x in c.execute("select run, agent, started, ended, end_state, title from runs where ref=? order by started", (run,))]
    man = json.loads(r["manifest"]) if r["manifest"] else None
    live = r["ended"] is None
    return {"run": run, "ref": r["ref"], "agent": r["agent"], "source": r["source"], "title": r["title"], "name": name_of(r, c),
            "started": r["started"], "ended": r["ended"], "end_state": r["end_state"], "live": live,
            "seconds": round((r["ended"] or time.time()) - r["started"]), "manifest": man,
            "drift": json.loads(r["drift"]) if r["drift"] else [], "box": json.loads(r["box"]) if r["box"] else None,
            "children": children, "touches": touches(ev), "problems": [p for p in O.problems(ev, finished=not live, final_status=r["end_state"]) if p["kind"] != "no-end"],   # every run here has an explicit end state
            "stats": O.stats_of(ev, (r["ended"] or time.time()) - r["started"]), "events": ev[-1500:], "events_total": len(ev)}  # cap: list (the app says how many earlier events are not shown)


CONN = ("mail_", "phone_", "browser_", "research", "fetch", "web_search", "claude_task")


def touches(ev):
    """The left pane: the shared ledger (read and changed files, pages, searches, refused, cut off) plus connections used."""
    led = O.ledger(ev)
    conns = {}
    for e in ev:
        if e.get("kind") == "call":
            t = O.base(e.get("title"))
            if t.startswith(CONN) or any(k in t for k in CONN):
                conns[t] = conns.get(t, 0) + 1
    return {**led, "connections": [{"tool": k, "calls": v} for k, v in sorted(conns.items(), key=lambda x: -x[1])]}


def summarise(run):
    """A finished run's summary, kept for good (events go after 90 days)."""
    v = view(run)
    if not v:
        return
    k = v["stats"]
    summ = {"seconds": v["seconds"], "end_state": v["end_state"], "model_calls": k["model"]["calls"],
            "tool_calls": sum(t["calls"] for t in k["tools"]), "cache_pct": k["model"]["cache_pct"],
            "tokens_in": sum((e.get("tokens") or {}).get("in", 0) for e in v["events"] if e["kind"] == "llm"),
            "problems": [p["kind"] for p in v["problems"]], "files_changed": sum(1 for f in v["touches"]["files"] if f["modified"]),
            "files_read": sum(1 for f in v["touches"]["files"] if f["read"])}
    with _lock:
        db().execute("update runs set summary=? where run=?", (json.dumps(summ), run))
        db().commit()


def runs(live=None, agent=None, ref=None, limit=60, since=None, until=None):
    c = db()
    where, args = ["1=1"], []
    if since is not None:                                 # TSK-25: a telemetry number opens the runs that ended in its days
        where.append("ended >= ?"); args.append(since)
    if until is not None:
        where.append("ended < ?"); args.append(until)
    if live is not None:
        where.append("ended is null" if live else "ended is not null")
    if agent:
        where.append("agent=?"); args.append(agent)
    if ref:
        where.append("ref=?"); args.append(ref)
    else:
        where.append("(ref is null or ref not in (select run from runs where ended is null))" if live else "1=1")
    rows = c.execute(f"select * from runs where {' and '.join(where)} order by coalesce(ended, last) desc limit ?", (*args, limit)).fetchall()  # cap: list (the caller's page; a larger limit= shows more)
    return [{"run": r["run"], "ref": r["ref"], "agent": r["agent"], "source": r["source"], "title": r["title"], "name": name_of(r, c),
             "started": r["started"], "last": r["last"], "ended": r["ended"], "end_state": r["end_state"],
             "summary": json.loads(r["summary"]) if r["summary"] else None, "drift": json.loads(r["drift"]) if r["drift"] else []} for r in rows]


def live_now(limit=30):
    """SWM-97: the runs going on now (top-level: a mission's scouts count under it), with their tokens so far."""
    out = []
    for r in runs(live=True, limit=limit):
        ev = events_of(r["run"])
        t = [e.get("tokens") or {} for e in ev if e["kind"] == "llm"]
        out.append({k: r[k] for k in ("run", "ref", "agent", "name", "title", "started", "last")}
                   | {"tokens": sum(int(x.get("in") or 0) + int(x.get("out") or 0) for x in t), "calls": len(t), "steps": len(ev)})
    return out


# ---------- the swarm as it works: timeline, who starts whom, what they ask each other (SWM-103 to SWM-105) ----------
def lane_of(agent):
    """A run's agent -> the swarm agent it belongs to (its card id where it has one): crew:doctor -> doctor, a mission
    run and its Hermes profile -> mission, claude-coach -> coach, an experiment's replays -> evals."""
    a = str(agent or "?")
    if a.startswith("crew:"):
        return a[5:]
    if a.startswith("mission:"):
        return "mission"
    if a.startswith("claude-eval-"):
        return "evals"
    if a.startswith("claude-"):
        return {"task": "claude", "review": "reviewers"}.get(a[7:], a[7:])
    return {"ai-phone": "phone", "mail": "gmail"}.get(a, a)


def _window(c, since):
    rows = c.execute("select * from runs where coalesce(ended, last, started) >= ? or ended is null order by started", (since,)).fetchall()
    refs = sorted({r["ref"] for r in rows if r["ref"]})
    parents = {r["run"]: r for r in c.execute(f"select * from runs where run in ({','.join('?' * len(refs))})", refs)} if refs else {}
    return rows, parents


def timeline(hours=24, now=None):
    """Every run in the window, as a bar of its agent's lane: when, how it ended, what started it, its model calls."""
    c, now = db(), now or time.time()
    since = now - float(hours) * 3600
    rows, parents = _window(c, since)
    stats = {r["run"]: (r["n"], r["t"] or 0) for r in c.execute(
        "select run, count(*) n, sum(coalesce(json_extract(data, '$.tokens.in'), 0) + coalesce(json_extract(data, '$.tokens.out'), 0)) t "
        "from events where kind='llm' and ts>=? group by run", (since - 86400,))}
    busy = {r["run"]: r["t"] for r in c.execute("select run, max(ts) t from events where kind<>'end' and ts>=? group by run", (since - 86400,))}
    out = []
    for r in rows:
        man = json.loads(r["manifest"]) if r["manifest"] else {}
        p = parents.get(r["ref"])
        n, t = stats.get(r["run"], (0, 0))
        ref = r["ref"] or ""
        by = (lane_of(p["agent"]) if p else "you" if ref.startswith("chat:") else lane_of(ref) if ref.count(":") == 1 and ref.startswith("crew:")
              else "hermes" if ref == "chat" else None)           # "chat": Hermes' claude tool (the assistant or a mission's agent)
        out.append({"run": r["run"], "lane": lane_of(r["agent"]), "agent": r["agent"], "name": name_of(r, c), "started": r["started"],
                    "ended": r["ended"], "last": r["last"], "state": r["end_state"] or ("running" if r["ended"] is None else "done"),
                    "parent": p["run"] if p else None, "by": by, "calls": n, "tokens": t,   # by: crew:doctor queued a Claude task
                    "ref": r["ref"], "title": r["title"], "recorded": man.get("cause"), "trigger": man.get("trigger"), "repo": man.get("repo"),
                    "until": busy.get(r["run"]) if r["ended"] and busy.get(r["run"]) and r["ended"] - busy[r["run"]] > STALL_S else None})   # silent to its end (the PC was off): the bar stops at its last activity
    return {"since": since, "now": now, "runs": out}


def delegations(hours=168, pair=None, now=None, runs=None):
    """What agents ask each other through their tools (a mission asks the scout, a crew job asks Claude): each
    delegated run as an exchange, its question (the run's title, or the call that started it) and its answer (its
    last words), whole. pair "a+b" keeps the exchanges between two agents. runs: the window's runs, already settled by
    interactions.py. -> newest last."""
    c = db()
    out = []
    for r in timeline(hours, now)["runs"] if runs is None else runs:
        if not r["by"] or r["by"] in ("you", r["lane"]):
            continue
        if pair and set(pair.split("+")) != {r["by"], r["lane"]}:
            continue
        ask = ""
        call = c.execute("select detail from events where run=? and kind='call' and ts<=? and ts>=? order by ts desc limit 1",
                         (r["parent"], r["started"] + 2, r["started"] - 30)).fetchone() if r["parent"] else None   # the call that started it, as sent
        if not call:                                      # a queued task carries its question on its start (claude_tasks.py)
            call = c.execute("select detail from events where run=? and kind='run' and detail<>'' order by id limit 1", (r["run"],)).fetchone()
        if call and call["detail"]:
            try:
                d = json.loads(call["detail"])
                ask = next((str(d[k]) for k in ("question", "prompt", "task", "query", "text", "goal") if isinstance(d, dict) and d.get(k)), "")
            except ValueError:
                ask = call["detail"]
        if not ask:
            row = c.execute("select title from runs where run=?", (r["run"],)).fetchone()
            ask = (row["title"] or "").strip() if row else ""
        say = c.execute("select e.detail from events e where (e.run=? or e.run in (select run from runs where ref=?)) and e.kind='say' "
                        "order by e.ts desc limit 1", (r["run"], r["run"])).fetchone()     # its last words, or its own agent's (a task's Claude run)
        answer = (say["detail"] if say else "") or ("(still working)" if r["state"] == "running" else f"(no answer: {r['state']})")
        out.append({"run": r["run"], "from": r["by"], "to": r["lane"], "ts": r["started"], "ended": r["ended"], "state": r["state"],
                    "ask": ask, "answer": answer, "world": r.get("world"), "certainty": (r.get("cause") or {}).get("certainty")})
    return out


def open_problems(hours=24):
    """Problems of runs that ended in the last hours, for the health board and the once-per-issue alerts."""
    since = time.time() - hours * 3600
    out = []
    for r in db().execute("select * from runs where ended > ?", (since,)):
        s = json.loads(r["summary"]) if r["summary"] else {}
        issues = [{"kind": p, "text": p.replace("-", " ")} for p in sorted(set(s.get("problems") or []))]
        if r["end_state"] in ("stalled", "limit", "failed"):
            issues.append({"kind": r["end_state"], "text": {"stalled": "stopped answering and was closed",
                                                             "limit": "stopped by a usage limit", "failed": "failed"}[r["end_state"]]})
        issues += [{"kind": "drift", "text": d} for d in json.loads(r["drift"] or "[]") if "fewer tools" in d or "not connected" in d]
        if issues:
            out.append({"name": r["agent"] or r["run"], "label": name_of(r, db()), "kind": "agent", "run": r["run"], "issues": issues})
    return out


def _issues_of(r):
    s = json.loads(r["summary"]) if r["summary"] else {}
    issues = [{"kind": p, "text": p.replace("-", " ")} for p in sorted(set(s.get("problems") or []))]
    if r["end_state"] in ("stalled", "limit", "failed"):
        issues.append({"kind": r["end_state"], "text": {"stalled": "stopped answering and was closed",
                                                         "limit": "stopped by a usage limit", "failed": "failed"}[r["end_state"]]})
    issues += [{"kind": "drift", "text": d} for d in json.loads(r["drift"] or "[]") if "fewer tools" in d or "not connected" in d]
    return issues


def agent_issues(hours=48):
    """Problems per owning agent, for the health board: a chat session, a scout run or a Claude review counts for the run
    that started it (its ref chain, up to the root run), and a kind of problem counts only until a later finished root
    run of the agent is free of it, so an issue clears itself with the next run that does not have it, whatever notes
    that run has. → [{agent, root, issues: [{kind, text, run, at}]}], agent = the root run's agent."""
    c = db()
    rows = c.execute("select * from runs where coalesce(ended, last) > ? order by coalesce(ended, last)", (time.time() - hours * 3600,)).fetchall()
    parent = {}
    def root(r):
        run, seen = r["run"], set()
        while run not in seen and len(seen) < 8:
            seen.add(run)
            if run not in parent:
                x = c.execute("select ref from runs where run=?", (run,)).fetchone()
                parent[run] = x["ref"] if x and x["ref"] and c.execute("select 1 from runs where run=?", (x["ref"],)).fetchone() else None
            if not parent[run]:
                return run
            run = parent[run]
        return run
    roots = {}                                       # root run -> {agent, at, issues}
    for r in rows:
        rt = root(r)
        g = roots.get(rt)
        if not g:
            top = c.execute("select agent, ended, last from runs where run=?", (rt,)).fetchone()
            g = roots[rt] = {"agent": (top["agent"] if top else None) or r["agent"] or rt, "at": (top["ended"] or top["last"]) if top else r["last"],
                             "open": bool(top and top["ended"] is None), "issues": []}
        g["issues"] += [{**i, "run": r["run"], "at": r["ended"] or r["last"]} for i in _issues_of(r)]
    out = {}
    for rt, g in sorted(roots.items(), key=lambda x: x[1]["at"] or 0):
        a = out.setdefault(g["agent"], {"agent": g["agent"], "root": rt, "issues": {}})
        if not g["open"]:                            # a finished run without a kind of problem: that kind is over (FND-64:
            kinds = {i["kind"] for i in g["issues"]}  # a note on every run no longer keeps an old stall open)
            a["issues"] = {k: v for k, v in a["issues"].items() if k in kinds}
        if not g["issues"]:
            continue
        for i in g["issues"]:
            a["issues"][i["kind"]] = i                # the newest occurrence of each kind
        a["root"] = rt
    return [{**a, "issues": list(a["issues"].values())} for a in out.values() if a["issues"]]


def watchdog_once(now=None):
    """Close runs that went silent: one guaranteed end for every run."""
    now = now or time.time()
    rows = db().execute("select run, manifest, last from runs where ended is null and last < ?", (now - STALL_S,)).fetchall()
    c = db()
    waiting = []
    for r in rows:                                   # parked on a declared wait (missions.park): give it up to WAIT_S
        e = c.execute("select kind, title from events where run=? order by id desc limit 1", (r["run"],)).fetchone()
        if e and e["kind"] == "wait" and not e["title"].endswith((": ready", ": timed out")) and r["last"] > now - WAIT_S:
            waiting.append(r["run"])
    rows = [r for r in rows if r["run"] not in waiting]
    stale = [r["run"] for r in rows]
    for r in rows:
        idle = json.loads(r["manifest"] or "{}").get("idle_end")     # a phone or mail session simply went quiet: it ended then
        if not idle and now - r["last"] > STALL_S + CUT_OFF_S:       # this watchdog was down too: the PC was off, nobody could answer (SWM-114)
            ingest([{"run": r["run"], "kind": "end", "source": "watchdog", "status": "stopped", "ts": r["last"] + 1, "title": "cut off",
                     "detail": f"Cut off by a shutdown: the stack was down for {round((now - r['last']) / 60)} minutes after its last activity"}])
            continue
        ingest([{"run": r["run"], "kind": "end", "source": "watchdog", "status": "done" if idle else "stalled", "ts": r["last"] + 1 if idle else now,
                 "title": "session ended" if idle else "closed by the watchdog",
                 "detail": f"no activity for {STALL_S // 60} minutes" if idle else f"no event for {STALL_S // 60} minutes"}])
    return stale


def prune(now=None):
    """Drop full events older than 90 days; run summaries stay."""
    with _lock:
        c = db()
        n = c.execute("delete from events where ts < ?", ((now or time.time()) - KEEP_EVENTS_S,)).rowcount
        c.commit()
    return n


# ---------------------------------------------------------------- who reads and writes which wiki (MEM-10)
WIKI_REFS = [(re.compile(r"qmd://vault-wiki/"), lambda m: "wiki"),
             (re.compile(r"(?:qmd://)?(?<![\w.-])(missions|topics)/([a-z0-9][a-z0-9-]*)/wiki/"), lambda m: f"{m.group(1)}/{m.group(2)}/wiki"),
             (re.compile(r"(?<![\w/.-])wiki/[a-z0-9]"), lambda m: "wiki")]
WIKI_WRITES = ("write_file", "patch", "edit_file")


TASK_ROOT = re.compile(r"^task(?:-intake)?:(\d+)")
STEP_OF = re.compile(r"^task:\d+(?:\.(\d+))?:step:(\d+)$")
ACTS = ("run", "call", "say", "error", "stage", "propose", "read", "wait", "end")
MEM_READ = re.compile(r"qmd_|wiki_search|memory_recall|recall|reflect|swarm_context|ledger_(find|get)|board_read")
MEM_WRITE = re.compile(r"journal_write|agent_note|swarm_finish|ledger_(upsert|evidence|transition|link)|retain|vault_add|wiki_write")
MEM_PATH = re.compile(r"/vault/|(^|[\s\"'/])(wiki|journals?|missions/[^/\s]+/wiki|topics/[^/\s]+/wiki)/|MEMORY\.md")
ACTIONS = 1500                                         # cap: list (a task's actions on its page; the run view has every one)
LANES = 200                                            # cap: list (bars on a task's timeline; a trial's builds stay well under it)


def mem_kind(e):
    """A call's part in memory: "read" (searching or reading notes, wikis, journals, long-term memory, the ledger),
    "write" (keeping something there), or None (other work)."""
    t = (e.get("title") or "").split("__")[-1]
    if MEM_WRITE.search(t) or (t in ("write_file", "patch", "edit_file") and MEM_PATH.search(e.get("detail") or "")):
        return "write"
    if MEM_READ.search(t) or (t in ("read_file", "read") and MEM_PATH.search(e.get("detail") or "")):
        return "read"
    return None


ARG = re.compile(r'"(path|file|file_path|query|q|question|key|title|summary|text|kind)":\s*"((?:[^"\\]|\\.)*)')
TARGET_KEYS = ("path", "file", "file_path", "query", "q", "question", "key", "title", "summary", "text")


def mem_store(tool, detail):
    """Where a memory call reads or writes, and what (the task page groups them, APP-36): (store, target).
    store: wiki, notes (the vault: search and files), journal, long-term (Hindsight), board (the swarm's ledger), lessons."""
    t = tool.split("__")[-1]
    try:
        a = json.loads(detail or "{}")
        a = a if isinstance(a, dict) else {}
    except ValueError:                               # a cut argument list: what can be read of it
        a = dict(ARG.findall(detail or ""))
    target = next((str(a[k]) for k in TARGET_KEYS if a.get(k)), "")
    p = target.removeprefix("/vault/")
    if re.search(r"swarm_|ledger_|board_read", t):
        return "board", ("the task's context: the ledger's ideas, findings and messages for it" if "swarm_context" in t else p)
    if re.search(r"memory_recall|recall|reflect|retain", t):
        return "long-term", p
    if "journal" in t or re.search(r"(^|/)journals?/", p):
        return "journal", p
    if "agent_note" in t or "MEMORY.md" in p:
        return "lessons", p
    if "wiki" in t or re.search(r"(^|/)wiki/", p):
        return "wiki", p
    return "notes", p


def task_roots(c, tid, door=None, ref=None, since=None, occ=None):
    """The runs a task's work starts from: the Conductor's (planning, each run, its steps) for a planned task, the door's
    own run for a task handed to Claude, a build, a chat or a mission (APP-36: a door task's page shows its agents too)."""
    if door == "claude" and ref:
        q, a = "select run from runs where run=?", (f"claude-task:{ref}",)
    elif door == "build" and ref:
        q, a = "select run from runs where run like ?", (f"build:{ref}:%",)
    elif door == "chat" and ref:
        q, a = "select run from runs where ref=?", (f"chat:{ref}",)
    elif door == "mission" and ref:
        q, a = "select run from runs where agent=? and started>=?", (f"mission:{ref}", since or 0)
    elif door == "crew" and ref:                     # TSK-42: a crew duty's task: its runs of the last 30 days
        q, a = "select run from runs where agent=? and started>=?", (f"crew:{ref}", time.time() - 30 * 86400)
    elif occ:                                        # one run of a recurring task, and the planning it ran on
        q, a = "select run from runs where run=? or run like ?", (f"task:{tid}" if occ <= 1 else f"task:{tid}.{occ}", f"task-intake:{tid}-%")
    else:
        q, a = "select run from runs where run=? or run like ? or run like ?", (f"task:{tid}", f"task:{tid}.%", f"task-intake:{tid}-%")
    return [r["run"] for r in c.execute(q, a)]


TOOLS = {"phone", "gmail", "house"}                 # TSK-43: what an agent uses, never an agent of its own
NOT_AGENTS = {"conductor", "evals", "?"}            # the Conductor runs plans; an experiment's replays are no one's work
LIVE_H = 6                                          # a run without an end older than this is a leftover, not at work


def _top_of(c, known, run):                                      # the run the work started from (refs may reach before the window)
    seen = set()
    while run in known and known[run]["ref"] and known[run]["ref"] not in seen:
        seen.add(run)
        ref = known[run]["ref"]
        if ref not in known:
            r = c.execute("select run, ref, agent, started, ended from runs where run=?", (ref,)).fetchone()
            if not r:
                return known[run]                  # its ref names no run: a chat ("chat:<id>") or a gone parent
            known[ref] = dict(r)
        run = ref
    return known.get(run)


def _task_of_top(t, by_door):
    m = TASK_ROOT.match(t["run"])
    if m:
        return int(m.group(1))
    a = t["agent"] or ""
    if t["run"].startswith("mission-run:") and a.startswith("mission:"):
        return by_door.get(("mission", a[8:]))
    m = re.match(r"^build:(\d+)", t["run"]) or None
    if m:
        return by_door.get(("build", m.group(1)))
    m = re.match(r"^claude-task:(\d+)$", t["run"])
    if m:
        return by_door.get(("claude", m.group(1)))
    if str(t["ref"] or "").startswith("chat:"):
        return by_door.get(("chat", t["ref"][5:]))
    if a.startswith("crew:"):
        return by_door.get(("crew", a[5:]))
    return None


def tasks_of_runs(runs, tasks):
    """Each run -> the board's task its work belongs to (as on the Network: walked up to the run it started from), or
    None. tasks: the board's tasks (state.json)."""
    c = db()
    by_door = {(t.get("door"), str(t.get("ref"))): t["id"] for t in tasks if t.get("door") and t.get("ref") not in (None, "")}
    on_board, known, out = {t["id"] for t in tasks}, {}, {}
    for run in dict.fromkeys(runs):
        r = c.execute("select run, ref, agent, started, ended from runs where run=?", (run,)).fetchone()
        if not r:
            out[run] = None
            continue
        known[run] = dict(r)
        tid = _task_of_top(_top_of(c, known, run) or known[run], by_door)
        out[run] = tid if tid in on_board else None
    return out


def network(tasks, days=7, now=None):
    """TSK-43: who worked on which task in the last `days` days. Every run is walked up to the run its work started
    from, and that run is named as a task: the Conductor's (its planning and its runs), a mission's run, a build, a
    question to Claude, a chat, a crew duty; then joined to the board's tasks. -> {days, tasks: [{id, runs, live,
    agents: [{agent, runs, live}], tools: {tool: runs}}], agents: [{agent, runs, tasks, live}], outside: {agent: runs},
    elsewhere: n} (outside: runs no task holds; elsewhere: runs of tasks no longer on the board)."""
    c, now = db(), now or time.time()
    since = now - days * 86400
    on_board = {t["id"] for t in tasks}
    by_door = {(t.get("door"), str(t.get("ref"))): t["id"] for t in tasks if t.get("door") and t.get("ref") not in (None, "")}
    rows = {r["run"]: dict(r) for r in c.execute("select run, ref, agent, started, ended from runs where started>=? or ended is null", (since,))}
    known = dict(rows)

    top = lambda run: _top_of(c, known, run)
    task_of = lambda t: _task_of_top(t, by_door)

    work, agents, outside, elsewhere = {}, {}, {}, 0
    for run, r in rows.items():
        a = lane_of(r["agent"])
        if a in NOT_AGENTS:
            continue
        live = r["ended"] is None and now - (r["started"] or 0) < LIVE_H * 3600
        tid = task_of(top(run) or r)
        if tid is None:
            outside[a] = outside.get(a, 0) + 1
            continue
        if tid not in on_board:
            elsewhere += 1
            continue
        w = work.setdefault(tid, {"id": tid, "runs": 0, "live": False, "agents": {}, "tools": {}})
        w["runs"] += 1
        w["live"] |= live
        if a in TOOLS:
            w["tools"][a] = w["tools"].get(a, 0) + 1
            continue
        g = w["agents"].setdefault(a, {"agent": a, "runs": 0, "live": False})
        g["runs"] += 1
        g["live"] |= live
        x = agents.setdefault(a, {"agent": a, "runs": 0, "tasks": set(), "live": False})
        x["runs"] += 1
        x["tasks"].add(tid)
        x["live"] |= live
    return {"days": days, "elsewhere": elsewhere, "outside": dict(sorted(outside.items(), key=lambda x: -x[1])),
            "tasks": [{**w, "agents": sorted(w["agents"].values(), key=lambda g: -g["runs"])} for w in sorted(work.values(), key=lambda w: -w["runs"])],
            "agents": sorted(({**x, "tasks": sorted(x["tasks"])} for x in agents.values()), key=lambda x: (-len(x["tasks"]), -x["runs"]))}


EMPTY_ACTIVITY = {"agents": [], "actions": [], "memory": {"read": [], "write": []}, "runs": 0, "actions_total": 0, "edges": [], "errors": [], "errors_total": 0}
ERRORS = 300                                           # cap: list (a task's errors on its page; errors_total counts all, the run view has each)


def _doer(agent):
    """Who did a run, for a task's page: a mission's runs are recorded as mission:<slug>, which is the task, not who did
    it; they are the mission agent's (Hermes (tasks)), as on the Network. The two builders stay apart (unlike lane_of)."""
    return "mission" if str(agent or "").startswith("mission:") else agent


def task_activity(tid, door=None, ref=None, since=None, occ=None):
    """APP-35: everything the run record holds about task <tid> (its planning, every run, every step and every agent called
    in; or one run of it, occ): {agents: [{agent, name, roles, runs, calls, model_calls, tokens, first, last, states,
    tools}], actions: [...], memory: {read: [...], write: [...]} (each with its store and target), edges: [{from, to,
    kind, n}] (who started, called in or planned for whom), errors: [...], runs: n, actions_total: n}."""
    c = db()
    roots = task_roots(c, tid, door, ref, since, occ)
    seen, todo = set(roots), list(roots)
    while todo and len(seen) < 400:
        todo = [r["run"] for r in c.execute(f"select run from runs where ref in ({','.join('?' * len(todo))})", todo) if r["run"] not in seen]
        seen |= set(todo)
    if not seen:
        return json.loads(json.dumps(EMPTY_ACTIVITY))
    q = ",".join("?" * len(seen))
    runs = {r["run"]: {**dict(r), "agent": _doer(r["agent"])} for r in c.execute(f"select run, ref, agent, title, started, ended, end_state from runs where run in ({q})", tuple(seen))}
    agents, actions, mem = {}, [], {"read": [], "write": []}
    for run, r in runs.items():
        a = agents.setdefault(r["agent"] or "?", {"agent": r["agent"] or "?", "name": AGENT_NAME.get(r["agent"] or "", r["agent"] or "?"), "roles": set(),
                                                  "runs": 0, "calls": 0, "model_calls": 0, "tokens": 0, "first": r["started"], "last": r["ended"] or r["started"],
                                                  "states": {}, "tools": {}})
        a["runs"] += 1
        a["first"], a["last"] = min(a["first"], r["started"]), max(a["last"], r["ended"] or time.time())
        a["states"][r["end_state"] or "running"] = a["states"].get(r["end_state"] or "running", 0) + 1
        m = STEP_OF.match(run)
        if m:
            a["roles"].add(f"step {m.group(2)}" + (f" of run {m.group(1)}" if m.group(1) else ""))
        elif run.startswith("task-intake:"):
            a["roles"].add("planned it")
        elif ":checkpoint:" in run:
            a["roles"].add("checked the plan between waves")
        elif r["ref"] in runs and run not in roots:
            p = runs[r["ref"]]
            if (p["agent"] or "") != (r["agent"] or ""):
                a["roles"].add(f"called in by {AGENT_NAME.get(p['agent'] or '', p['agent'] or '?')}")
        elif run in roots and run.startswith("task:"):
            a["roles"].add("ran the plan")
        elif run in roots:
            a["roles"].add("did it")                 # a door task's own run: the Claude task, the build, the chat
    edges = {}
    for run, r in runs.items():                      # who started, called in or checked whom
        p = runs.get(r["ref"] or "")
        if not p or (p["agent"] or "?") == (r["agent"] or "?"):
            continue
        k = (p["agent"] or "?", r["agent"] or "?", "checked" if ":checkpoint:" in run else "started" if STEP_OF.match(run) else "called")
        edges[k] = edges.get(k, 0) + 1
    plan = {r["agent"] for run, r in runs.items() if run.startswith("task-intake:")}
    for a_ in plan:                                  # the plan the intake made is what the Conductor runs
        for run, r in runs.items():
            if run in roots and run.startswith("task:") and r["agent"] != a_:
                edges[(a_, r["agent"] or "?", "planned")] = 1
    total, errors = 0, []
    for e in c.execute(f"select e.run, e.ts, e.kind, e.title, e.detail, e.data, r.agent from events e join runs r on r.run=e.run "
                       f"where e.run in ({q}) order by e.ts, e.id", tuple(seen)):
        e = {**dict(e), "agent": _doer(e["agent"])}
        a = agents[e["agent"] or "?"]
        d = json.loads(e["data"] or "{}")
        if e["kind"] == "llm":
            a["model_calls"] += 1
            tk = d.get("tokens") or {}
            a["tokens"] += (tk.get("in") or 0) + (tk.get("out") or 0) if isinstance(tk, dict) else int(tk or 0)
            continue
        if e["kind"] not in ACTS:
            continue
        if e["kind"] == "call":
            a["calls"] += 1
            short = re.sub(r"^([a-z]+)_\1_", r"\1_", (e["title"] or "?").split("__")[-1])     # mcp__vault__swarm_swarm_context -> swarm_context
            a["tools"][short] = a["tools"].get(short, 0) + 1
            k = mem_kind(dict(e))
            if k:
                store, target = mem_store(e["title"] or "", e["detail"] or "")
                mem[k].append({"ts": e["ts"], "agent": e["agent"], "run": e["run"], "tool": e["title"], "detail": _clip(e["detail"] or ""),
                               "store": store, "target": target})
        elif e["kind"] == "error":
            errors.append({"ts": e["ts"], "agent": e["agent"], "run": e["run"], "title": e["title"], "detail": _clip(e["detail"] or "")})
        total += 1
        actions.append({"ts": e["ts"], "agent": e["agent"], "run": e["run"], "kind": e["kind"], "title": e["title"], "detail": _clip(e["detail"] or ""),
                        "status": d.get("status")})
    out = sorted(({**a, "roles": sorted(a["roles"]), "tools": dict(sorted(a["tools"].items(), key=lambda x: -x[1]))} for a in agents.values()),
                 key=lambda x: x["first"])

    def depth(run, n=0):
        r = runs.get(run)
        return n if not r or run in roots or r["ref"] not in runs or n > 6 else depth(r["ref"], n + 1)
    off = 1 if any(x.startswith("task:") for x in roots) else 0     # a door task's own run is drawn; a planned task's is not
    def role(run, r):
        m, p = STEP_OF.match(run), runs.get(r["ref"] or "")
        return (f"step {m.group(2)}" if m else "planning" if run.startswith("task-intake:") else "checkpoint" if ":checkpoint:" in run else
                "its run" if run in roots else "its session" if p and p["agent"] == r["agent"] else "called in")
    lanes = [{"run": run, "agent": r["agent"], "started": r["started"], "ended": r["ended"], "state": r["end_state"],
              "depth": max(0, depth(run) - off), "role": role(run, r)}  # the task's own run is not drawn: its steps start the lanes
             for run, r in sorted(runs.items(), key=lambda x: x[1]["started"]) if not (run in roots and run.startswith("task:"))]
    return {"agents": out, "actions": actions[-ACTIONS:], "actions_total": total, "memory": mem, "runs": len(runs), "lanes": lanes[:LANES],  # cap: list (actions_total and runs count what is not shown)
            "edges": [{"from": f, "to": t, "kind": k, "n": n} for (f, t, k), n in sorted(edges.items())],
            "errors": errors[-ERRORS:], "errors_total": len(errors)}  # cap: list (errors_total counts all)


def agent_tasks(agent, days=90, now=None):
    """APP-35: the tasks an agent worked on (a step of its own, called in by another agent, or planning), newest first:
    [{task, roles, runs, last}]."""
    c, now = db(), now or time.time()
    mine = [dict(r) for r in c.execute("select run, ref, agent, started, ended from runs where started>=?", (now - days * 86400,))
            if lane_of(r["agent"]) == agent or r["agent"] == agent]
    parent, out = {}, {}

    def root(run, depth=0):
        m = TASK_ROOT.match(run or "")
        if m or depth > 8 or not run:
            return (int(m.group(1)), run) if m else None
        if run not in parent:
            p = c.execute("select ref from runs where run=?", (run,)).fetchone()
            parent[run] = p["ref"] if p else None
        return root(parent[run], depth + 1)
    for r in mine:
        hit = root(r["run"])
        if not hit:
            continue
        tid, top = hit
        x = out.setdefault(tid, {"task": tid, "roles": set(), "runs": 0, "last": 0})
        x["runs"] += 1
        x["last"] = max(x["last"], r["ended"] or r["started"])
        m = STEP_OF.match(r["run"])
        if m or r["run"].startswith("task-intake:"):
            x["roles"].add(f"step {m.group(2)}" if m else "planned it")
        elif (c.execute("select agent from runs where run=?", (r["ref"] or "",)).fetchone() or {"agent": None})["agent"] != r["agent"]:
            x["roles"].add("called in")                    # its own session inside its step is that step, not a call
    return sorted(({**v, "roles": sorted(v["roles"])} for v in out.values()), key=lambda v: -v["last"])


ENGINE_OF = (("claude", "Claude"), ("gpt", "ChatGPT"), ("chatgpt", "ChatGPT"))   # a model call's title -> its subscription


def usage(now=None):
    """OBS: how much each subscription carried lately, from the model calls in the run record: tokens and calls in the
    last 5 hours (ChatGPT's usage window) and 24 hours, and the agents that used most in the 5 hours.
    -> [{engine, tokens_5h, calls_5h, tokens_24h, calls_24h, top: [[agent, tokens]]}]"""
    c, now = db(), now or time.time()
    out = {}
    for e in c.execute("select e.ts, e.title, e.data, r.agent from events e join runs r on r.run=e.run where e.kind='llm' and e.ts>=?",
                       (now - 86400,)):
        eng = next((n for k, n in ENGINE_OF if str(e["title"] or "").lower().startswith(k)), None)
        if not eng:
            continue
        tk = json.loads(e["data"] or "{}").get("tokens") or {}
        n = (tk.get("in") or 0) + (tk.get("out") or 0) if isinstance(tk, dict) else int(tk or 0)
        u = out.setdefault(eng, {"engine": eng, "tokens_5h": 0, "calls_5h": 0, "tokens_24h": 0, "calls_24h": 0, "by": {}})
        u["tokens_24h"] += n
        u["calls_24h"] += 1
        if e["ts"] >= now - 5 * 3600:
            u["tokens_5h"] += n
            u["calls_5h"] += 1
            a = lane_of(e["agent"])
            u["by"][a] = u["by"].get(a, 0) + n
    return [{**{k: v for k, v in u.items() if k != "by"}, "top": sorted(u["by"].items(), key=lambda x: -x[1])[:3]}  # cap: list (the three that used most)
            for u in sorted(out.values(), key=lambda u: u["engine"])]


def wiki_roots_in(text):
    """The wiki roots a call's arguments or a result names (vault wiki: "wiki"; an agent's: missions|topics/<slug>/wiki)."""
    out = set()
    for rx, root in WIKI_REFS:
        out |= {root(m) for m in rx.finditer(text or "")}
    return out


def who_of(agent):
    """The agent as the access map names it: a mission by its own id, everyone else by its lane."""
    a = agent or ""
    return a if a.startswith("mission:") else lane_of(a)


def wiki_access(hours=168, now=None):
    """MEM-10: which agent read or wrote which wiki in the window, from the run record: a run's start brief (wiki_search),
    its vault searches and reads (qmd), its file reads and writes. -> [{agent, root, reads, writes, last}], counted in runs."""
    c, now = db(), now or time.time()
    acc = {}
    for e in c.execute("select e.run, e.ts, e.kind, e.title, e.detail, case when r.agent='mission' and p.agent like 'mission:%' then p.agent "
                       "else r.agent end as agent from events e join runs r on r.run=e.run left join runs p on p.run=r.ref where e.ts>=? "
                       "and e.kind in ('call', 'result') and (e.title in ('wiki_search', 'read_file', 'write_file', 'patch', 'edit_file') "
                       "or e.title like '%qmd%')", (now - float(hours) * 3600,)):
        write = e["kind"] == "call" and e["title"] in WIKI_WRITES
        for root in wiki_roots_in(e["detail"]):
            a = acc.setdefault((who_of(e["agent"]), root), {"reads": set(), "writes": set(), "last": 0})
            a["writes" if write else "reads"].add(e["run"])
            a["last"] = max(a["last"], e["ts"])
    return sorted(({"agent": k[0], "root": k[1], "reads": len(v["reads"]), "writes": len(v["writes"]), "last": v["last"]}
                   for k, v in acc.items()), key=lambda x: (x["root"], -x["reads"] - x["writes"]))


def ledger_drafts(agent):
    """MIS-23: the Ledger reports the runs of an agent (mission:<slug>, with the agents inside its runs) wrote or
    changed, newest first: [{id, title, ts, run}]. A mission keeps long drafts there; its Results page lists them."""
    c = db()
    roots = [r["run"] for r in c.execute("select run from runs where agent=?", (agent,))]
    seen, todo = set(roots), list(roots)
    while todo and len(seen) < 2000:
        todo = [r["run"] for r in c.execute(f"select run from runs where ref in ({','.join('?' * len(todo))})", todo) if r["run"] not in seen]
        seen |= set(todo)
    if not seen:
        return []
    q, out = ",".join("?" * len(seen)), {}
    calls = {}
    for e in c.execute(f"select run, ts, kind, title, detail, data from events where run in ({q}) and kind in ('call', 'result') "
                       f"and title like '%ledger_upsert' order by ts, id", tuple(seen)):
        cid = _json(e["data"]).get("call_id")
        if e["kind"] == "call":
            calls[cid] = _json(e["detail"])
            continue
        res = _json(e["detail"])
        inner = _json(res.get("result") if isinstance(res.get("result"), str) else json.dumps(res.get("result") or {}))
        r = inner.get("result") if isinstance(inner.get("result"), dict) else inner
        aid = (r or {}).get("id")
        args = calls.get(cid) or {}
        if inner.get("ok") is False or not aid or (args.get("kind") and args.get("kind") != "report"):
            continue
        out[int(aid)] = {"id": int(aid), "title": args.get("title") or r.get("title") or f"Ledger report #{aid}", "ts": e["ts"], "run": e["run"]}
    return sorted(out.values(), key=lambda x: -x["ts"])


# ---------- what a chat made (docs/CHAT-MADE.md, APP-39): read from its turns' tool results, nothing inferred by time ----------
MAKERS = {"mission_create": "mission", "mission_control": "mission", "mission_update": "mission", "mission_set_triggers": "mission",
          "build_assign": "build", "build_request_changes": "build", "build_recheck": "build", "build_switch_engine": "build",
          "claude_task": "claude", "repo_create": "repo", "repo_make_buildable": "repo", "understand_repo": "repo",
          "vault_add": "note", "send_email": "email"}
MADE_LINE = re.compile(r"^(made|changed): ([a-z]+):(\S+)$", re.M)     # the line each maker tool ends its answer with
OLD_WORDING = {                                                       # results from before that line: their present wording
    "mission_create": re.compile(r"(Created|Already exists): \[([^\]]+)\]"),
    "build_assign": re.compile(r"Build #(\d+) queued"),
    "claude_task": re.compile(r"Claude task #(\d+) started"),
    "repo_create": re.compile(r"Created (\S+?)\.$"),
    "vault_add": re.compile(r"Added: (\S+)"),
}
ARG_ID = {"mission": "slug", "build": "id", "repo": "repo"}


def maker_of(title):
    """mcp__vault__missions_mission_create → mission_create (the tools that make or change something), else None."""
    name = O.base(title)
    return next((t for t in sorted(MAKERS, key=len, reverse=True) if name == t or name.endswith("_" + t)), None)


def _json(s):
    try:
        v = json.loads(s or "")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def made_item(tool, args, text):
    """One maker tool's result → {kind, id, verb (made|exists|changed|pending|failed|sent), title, what}; id is
    "request-<rid>" while the runner was still working when the tool answered (the app resolves it)."""
    kind, title = MAKERS[tool], str(args.get("title") or args.get("subject") or args.get("name") or "")
    it = {"kind": kind, "id": None, "verb": "made", "title": title, "what": ""}
    m = MADE_LINE.search(text)
    if m:
        it.update(verb=m[1], kind=m[2], id=m[3])
        if it["id"].startswith("request-"):
            it["verb"] = "pending"
    elif text.startswith("Error"):
        it.update(verb="failed", what=text)
    elif tool in OLD_WORDING and (w := OLD_WORDING[tool].search(text)):
        it.update(id=w[w.lastindex], verb="exists" if w[1] == "Already exists" else "made")
    elif tool == "mission_create" and text.startswith("Creating"):
        it["verb"] = "pending"                                        # the app finds it by its title (titles are unique)
    elif tool == "send_email":
        it["verb"] = "sent"
    elif tool in ("mission_control", "mission_update", "mission_set_triggers", "build_request_changes", "build_recheck",
                  "build_switch_engine", "repo_make_buildable", "understand_repo"):
        it["verb"] = "changed"
    if it["verb"] in ("changed", "failed") and not it["id"]:          # what it changed (or failed on) is in its arguments
        it["id"] = str(args.get(ARG_ID.get(kind, "id")) or "") or None
    if it["verb"] == "changed" and not it["what"]:
        it["what"] = {"mission_control": {"run": "run started", "deep_run": "deep research run started", "pause": "paused",
                                          "resume": "resumed", "archive": "archived"}.get(args.get("action"), "changed"), "mission_update": "settings changed",
                      "mission_set_triggers": "triggers set", "build_request_changes": "sent back with changes",
                      "build_recheck": "checks re-run", "build_switch_engine": f"moved to {args.get('engine', 'the other engine')}",
                      "repo_make_buildable": "moved to Forgejo", "understand_repo": "onboarding started"}.get(tool, "changed")
    return it


def chat_made(chat=None, since=0):
    """APP-39: what chat <chat> (every chat: None) made or changed, oldest first: [{key, chat, run, ts, tool, kind, id, verb,
    title, what}]. key is the result event's id: stable, so the app can keep what it resolved."""
    c, out = db(), []
    q = ("select e.id, e.run, e.ts, e.title, e.detail, e.data, r.ref from events e join runs r on r.run=e.run "
         "where e.kind='result' and r.ref " + ("= ?" if chat else "like 'chat:%'") + " and e.ts>=? and (" +
         " or ".join("e.title like ?" for _ in MAKERS) + ") order by e.ts, e.id")
    rows = c.execute(q, ((f"chat:{chat}",) if chat else ()) + (since,) + tuple(f"%{t}" for t in MAKERS)).fetchall()
    calls = {}
    for r in rows:
        tool = maker_of(r["title"])
        if not tool:
            continue
        cid = _json(r["data"]).get("call_id")
        if cid and r["run"] not in calls:                             # the call's arguments: what it was asked to make
            calls[r["run"]] = {_json(x["data"]).get("call_id"): _json(x["detail"]) for x in
                               c.execute("select data, detail from events where run=? and kind='call'", (r["run"],))}
        res = _json(r["detail"])
        text = str(res.get("result") or r["detail"] or "").strip()
        out.append({"key": r["id"], "chat": r["ref"][5:], "run": r["run"], "ts": r["ts"], "tool": tool,
                    **made_item(tool, (calls.get(r["run"]) or {}).get(cid) or {}, text)})
    return out

