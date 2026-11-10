"""Self-staffing (TSK-13 to TSK-17; phase 4 of docs/SWARM-ROADMAP.md): each finished task is judged against its
definition of done, a daily history keeps how each agent, model and harness did per kind of task, the Conductor routes a
step to the agent that does that kind of work best (and away from a subscription at its usage limit), and a step no
agent fits gets a temporary agent written for it; one that keeps doing well is proposed as a permanent agent.

Judging (TSK-17): a Conductor task's answer, a mission's report or a Claude answer is read by a model (vk-eval) against
each point of the definition of done; a build counts by what happened to it (deployed or merged: met). A Conductor task
is judged per occurrence (TSK-22): every run of a scheduled or event-triggered task gets its own verdict, and the
task shows its latest; a run that found nothing to send (a quiet briefing, no price drop) is not judged. A point about
when the task runs ("every Monday at 08:00, starting 2 November") is no point a report can show: it is checked against
the task's schedule instead, and the run's window and its delivery's own record go to the judge (TSK-50). Chats and work
found at a door (without the owner's definition of done) are not judged.

Temporary agents (TSK-15), within the grants of a task that starts by itself (DEC-34): one model call per step on the
agent's own LiteLLM key (no tools, no MCP server, 0.02 a day, the subscription models only), made when the step starts
and deleted when its task ends; the design (name, purpose, instructions, model) stays in an archive with its scores.
A design that served three tasks that met their definition of done becomes an idea for a permanent agent (TSK-16),
which the owner reviews and the builder makes like any agent change (its prompt replay-tested).
"""
import datetime as dt
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import json
import os
import re
import sqlite3
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DB = Path("/srv/ai/missions/app/runtime.db")
LITELLM = "http://127.0.0.1:4000"
MIN_TASKS = 3                                      # measured results count for routing from 3 judged tasks of a kind on
ROUTE_MARGIN = 0.15                                # another agent takes a step only when it did at least this much better
PROMOTE_AFTER = 3                                  # TSK-16: tasks that met their definition of done before a design is proposed
TEMP_MODELS = ("gpt-sub", "gpt-sub-fast")          # TSK-15: what a temporary agent may run on (the subscription only)
# limit: stops, a temporary agent key's daily budget; subscription models cost nothing, so it only bites if a paid model appears
TEMP_BUDGET = 0.02                                 # its key's daily budget (as the background jobs' keys, ops/keys.sh)
TEMP_GRANTS = ()                                   # its tools: none (a model call); anything asked for beyond this is refused
JUDGED_SOURCES = ("app", "gate")                   # and "rule:<id>": tasks with the owner's (or a rule's) definition of done
M = None                                           # ops/missions.py, set by its main()
_keys = {}                                         # temporary agent alias -> its key (process memory only; never written down)
lock = threading.Lock()


def table(c):
    c.executescript("""
      create table if not exists task_metrics (day text, agent text, harness text, model text, kind text, tasks integer,
        met integer, partly integer, not_met integer, failed integer, seconds real, tokens integer, corrections integer,
        primary key (day, agent, harness, model, kind));
      create table if not exists agent_designs (id integer primary key, name text unique, purpose text, instructions text,
        model text, created text, uses integer default 0, met integer default 0, partly integer default 0,
        not_met integer default 0, last_task integer, proposed text);""")
    cols = {r[1] for r in c.execute("pragma table_info(tasks)")}
    for col, decl in (("verdict", "text"), ("judged", "text"), ("tokens", "integer"), ("cost", "real")):
        if col not in cols:                               # cost: the tokens at list price (TSK-27)
            c.execute(f"alter table tasks add column {col} {decl}")
    c.commit()


def now():
    return dt.datetime.now().astimezone()


# ---------- what a task used (the runtime record) ----------
def tokens_of(run, db=None):
    """Tokens of a run and every run inside it (the agents of a step, Hermes' own runs)."""
    try:
        r = sqlite3.connect(f"file:{db or RUNTIME_DB}?mode=ro", uri=True).execute(
            """with recursive tree(run) as (select ? union select r.run from runs r join tree t on r.ref = t.run)
               select coalesce(sum(coalesce(json_extract(e.data, '$.tokens.in'), 0) + coalesce(json_extract(e.data, '$.tokens.out'), 0)), 0)
               from events e where e.run in (select run from tree) and e.kind = 'llm'""", (run,)).fetchone()
        return int(r[0] or 0)
    except sqlite3.Error:
        return 0


def usage_of(run, db=None, tree=True):
    """{model: {in, out, cached}} of a run (and every run inside it): what ops/prices.py prices (TSK-27)."""
    q = ("with recursive t(run) as (select ? union select r.run from runs r join t on r.ref = t.run) "
         "select e.title, e.data from events e where e.run in (select run from t) and e.kind = 'llm'") if tree else \
        "select e.title, e.data from events e where e.run = ? and e.kind = 'llm'"
    out = {}
    try:
        c = sqlite3.connect(f"file:{db or RUNTIME_DB}?mode=ro", uri=True)
        for model, data in c.execute(q, (run,)):
            tok = json.loads(data or "{}").get("tokens") or {}
            u = out.setdefault(model or "", {"in": 0, "out": 0, "cached": 0})
            for k in u:
                u[k] += int(tok.get(k) or 0)
        c.close()
    except (sqlite3.Error, ValueError):
        return {}
    return out


def runs_of(run, db=None):
    """The run and every run inside it (FND-101: what a count over the tree already holds)."""
    try:
        c = sqlite3.connect(f"file:{db or RUNTIME_DB}?mode=ro", uri=True)
        out = {r[0] for r in c.execute("with recursive t(run) as (select ? union select r.run from runs r join t on r.ref = t.run) "
                                       "select run from t", (run,))}
        c.close()
        return out
    except sqlite3.Error:
        return set()


def cost_of(run, db=None):
    """USD at list price of a run's tokens (None when none of its models has a price)."""
    import prices as PR
    u = usage_of(run, db)
    usd, missing = PR.total(u)
    return usd if u and len(missing) < len(u) else None


# ---------- judging (TSK-17) ----------
def result_of(c, t):
    """What the task produced, for the judge: (text, None) or (None, verdict by ground truth), or (None, None)."""
    door, ref = t["door"], t["ref"]
    if door == "plan" and t["spec"].get("result"):
        f = M.VAULT / t["spec"]["result"]
        return (f.read_text() if f.exists() else None), None
    if door == "build":
        r = c.execute("select status from builds where id=?", (int(ref),)).fetchone()
        return None, ("met" if r and r["status"] in ("deployed", "merged") else "not met")
    if door == "claude":
        r = c.execute("select answer from claude_tasks where id=?", (int(ref),)).fetchone()
        return (r["answer"] if r else None), None
    if door == "mission":
        r = c.execute("select output, summary from runs where slug=? and status='ok' order by id desc limit 1", (ref,)).fetchone()
        if r:
            f = M.VAULT / (r["output"] or "")
            return (f.read_text() if r["output"] and f.is_file() else r["summary"]), None
    return None, None


MEASURED = "## Measured by the stack (its own programs, not the agents' words)"
PAGES = 40                                         # cap: list (pages named for the judge; the run's map has every one)
CALLS = 80                                         # cap: list (tool calls named for the judge; the task page's timeline has every one)


def calls_of(run, db=None):
    """The tool calls of a run and every run inside it, in order -> [(agent, tool, its first argument)]."""
    q = ("with recursive t(run) as (select ? union select r.run from runs r join t on r.ref = t.run) "
         "select r.agent, e.title, e.detail from events e join runs r on r.run = e.run "
         "where e.run in (select run from t) and e.kind = 'call' order by e.ts, e.id")
    try:
        c = sqlite3.connect(f"file:{db or RUNTIME_DB}?mode=ro", uri=True)
        rows = c.execute(q, (run,)).fetchall()
        c.close()
    except sqlite3.Error:
        return []
    out = []
    for agent, tool, detail in rows:
        try:
            d = json.loads(detail or "{}")
        except ValueError:
            d = detail
        arg = next(iter(d.values()), "") if isinstance(d, dict) and d else d
        out.append((agent or "", tool or "", " ".join(str(arg or "").split())))
    return out


def evidence_of(c, t, occ=None):
    """FND-92: what the stack's own programs measured about a task's work, for the judge: each build's checks (the
    tests it ran), each check step's result and the pages its agents opened. A judge that reads only the agents' words
    cannot tell working code from a modest report. The run record's tool calls show what the agents ran and read.
    -> markdown, or "" when nothing was measured."""
    import conductor as CD
    import textcap as TC
    out = []
    for r in c.execute("select ref from step_refs where kind='build' and task=? order by ref", (t["id"],)).fetchall():
        b = c.execute("select id, status, checks, files from builds where id=?", (int(r["ref"]),)).fetchone()
        if b and b["checks"]:
            files = [f[-1] for f in json.loads(b["files"] or "[]")]
            out.append(f"### Build #{b['id']} ({b['status']}): its checks on the delivered code\n"
                       + (f"Files: {', '.join(files)}\n" if files else "") + f"```\n{TC.tail(b['checks'], 3000)}\n```")  # cap: prompt (the end names the counts)
    if t["door"] == "plan":
        for s in CD.steps(c, t["id"], occ):
            if s["harness"] == "check" and s["output"]:
                out.append(f"### Step {s['idx']}: the judge's checks\n{TC.cut(s['output'], 3000)}")  # cap: prompt (verdict and counts come first)
    try:
        pages = [r["uri"] for r in c.execute("select distinct a.uri from prov p join artifacts a on a.id = p.artifact "
                                             "where p.task=? and a.uri like 'http%' order by a.uri", (t["id"],))]
    except Exception:                                  # no provenance tables yet (a fresh database)
        pages = []
    out += [x for x in (run_record(c, t, occ),) if x]
    calls = calls_of(CD.run_of(t["id"], occ or 1))       # what the agents ran and read: a clean room is shown, not claimed
    if out or pages or calls:
        out.append(f"### Web pages the agents opened ({len(pages)})\n" + ("\n".join(f"- {u}" for u in pages[:PAGES]) or "none")  # cap: list (the next line says how many more)
                   + (f"\n- … and {len(pages) - PAGES} more" if len(pages) > PAGES else ""))
    if calls:
        out.append(f"### What the agents ran and read ({len(calls)} tool calls in the run record)\n"
                   + "\n".join(f"- {a}: {tool} {TC.cut(arg, 160)}" for a, tool, arg in calls[:CALLS])  # cap: list (each call's start, marked; the next line says how many more)
                   # limit: drops, tool calls named for the judge; the text says how many more and the task's page has them
                   + (f"\n- … and {len(calls) - CALLS} more (the task's page has every one)" if len(calls) > CALLS else ""))
    return f"{MEASURED}\n\n" + "\n\n".join(out) if out else ""


def run_record(c, t, occ):
    """TSK-50: what the stack itself recorded about one run of a plan task that its report cannot show: the window it
    covered and when it started (TSK-49), and each way its delivery went out or not (the delivery's own result)."""
    import conductor as CD
    if t["door"] != "plan" or not occ:
        return ""
    o = c.execute("select trigger, started from task_occ where task=? and occ=?", (t["id"], occ)).fetchone()
    win = CD.window_of(c, t["id"], occ)
    lines = ([f"- This run started {o['started']} ({o['trigger']})" + (f" and covered exactly {CD.period_text(win)}" if win else "")] if o else [])
    for s in CD.steps(c, t["id"], occ):
        sent = (s.get("resume") or {}).get("sent") if s["harness"] == "deliver" else None
        for way, r in (sent or {}).items():
            state = "sent" if r.get("ok") else "failed" if r.get("ok") is False else str(r.get("said") or "not sent")
            lines.append(f"- Delivery by {'e-mail' if way == 'email' else way}: {state}"
                         + (f", subject “{r['subject']}”, to the owner's address the stack's e-mail is set up with" if r.get("subject") else ""))
    return "### This run, as the stack recorded it\n" + "\n".join(lines) if lines else ""


# ---------- points no report can show (TSK-50) ----------
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WHEN = re.compile(r"\bevery\s+(?:day|week|month|hour|weekday|(?:mon|tues|wednes|thurs|fri|satur|sun)day)s?\b|\bat\s+\d{1,2}:\d{2}\b"
                  r"|\b(?:runs?|scheduled?|activity|recurring)\b[^.;]*\b(?:daily|weekly|monthly|hourly|weekdays|(?:mon|tues|wednes|thurs|fri|satur|sun)days?)\b", re.I)
MADE = re.compile(r"\b(?:report|briefing|summary|items?|sources?|covers?|includes?|contains?|lists?|e-?mail|sent|sends?|deliver\w*|answer|result)\b", re.I)
START = re.compile(r"\b(?:starting|from|beginning)\s+(?:on\s+)?(\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2},? \d{4}|\d{1,2} [A-Z][a-z]+ \d{4})")


def about_schedule(point):
    """A point about when the task runs (its rhythm), with nothing about what a run makes: "An enabled weekly activity
    runs every Monday at 08:00, starting November 2, 2026"."""
    return bool(WHEN.search(point)) and not MADE.search(point)


def day_of(text):
    for f in ("%Y-%m-%d", "%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(text, f).date()
        except ValueError:
            continue
    return None


def schedule_point(c, t, point, now=None):
    """TSK-50: a point about when the task runs, checked against its schedule (its n8n workflow's, else its rhythm's), its
    switch and its runs: the days and times it names, "enabled", and the day it starts. -> {point, met, why}."""
    import n8n_jobs as NJ
    try:
        w = NJ.of("task", t["id"]) or {}
    except Exception:                                  # the workflows cannot be read now: the task's own words
        w = {}
    cron = w.get("cron") or (NJ.cron_of_rhythm(t["rhythm"].get("schedule")) if t["rhythm"].get("type") == "schedule" else "")
    head = "Checked against the task's schedule, not the report (a report cannot show when its task runs): "
    p = NJ.parse(cron)
    if not p:
        return {"point": point, "met": False, "why": head + "the task has no schedule."}
    mins, hours, _, _, dows, _, dow_any = p
    tz = w.get("tz") or ""
    wrong, low = [], point.lower()
    named = {(i + 1) % 7 for i, d in enumerate(DAYS) if re.search(rf"\b{d}s?\b", low)}
    if named and (dow_any or named != dows):
        wrong.append(f"it does not run on {' and '.join(d.title() for i, d in enumerate(DAYS) if (i + 1) % 7 in named)} only")
    if re.search(r"\b(?:daily|every day)\b", low) and not dow_any:
        wrong.append("it does not run every day")
    wrong += [f"it does not run at {h}:{m}" for h, m in re.findall(r"\b(\d{1,2}):(\d{2})\b", point) if int(h) not in hours or int(m) not in mins]
    if re.search(r"\b(?:enabled|active|switched on)\b", low) and (w and not w.get("active") or t["status"] not in ("scheduled", "running")):
        wrong.append("its schedule is switched off" if w and not w.get("active") else f"the task is {t['status']}")
    runs = [r["started"] for r in c.execute("select started from task_occ where task=? and started is not null order by occ", (t["id"],))]
    m = START.search(point)
    first = day_of(m.group(1)) if m else None
    days = [r[:10] for r in runs]                      # cap: parse (the day of each run's ISO start, in the runner's zone)
    if first and days and first.isoformat() not in days and days[0] > first.isoformat():
        wrong.append(f"its first run started {days[0]}, after {first.isoformat()}")
    said = (f"{'its n8n workflow' if w.get('cron') else 'its rhythm'} runs it {NJ.words(cron)} ({tz or 'the runner’s time zone'})"
            + (", published in n8n" if w.get("active") else "") + f"; the task is {t['status']}"
            + (f"; its first run started {runs[0]}" if runs else "; it has not run yet"))
    return {"point": point, "met": not wrong, "why": head + said + "".join(f"; but {x}" for x in wrong) + "."}


def judge(c, t, ask=None, text=None, occ=None):
    """The task's result (or one run's, `text`) against each point of its definition of done -> {verdict, points:
    [{point, met, why}]}. What the stack measured itself (evidence_of) goes in after the result; a point about when the
    task runs is checked against its schedule, not read in the result (TSK-50); one run is judged with its window."""
    import conductor as CD
    import prompts as P
    text, truth = (text, None) if text is not None else result_of(c, t)
    if truth:
        return {"verdict": truth, "points": [{"point": d, "met": truth == "met", "why": "what happened to the build"} for d in t["done"]]}
    if not text:
        return {"verdict": "not judged", "points": [], "why": "no result to read"}
    fixed = {i: schedule_point(c, t, d) for i, d in enumerate(t["done"]) if about_schedule(d)}
    asked = [d for i, d in enumerate(t["done"]) if i not in fixed]
    got = []
    if asked:
        win = CD.window_of(c, t["id"], occ) if t["door"] == "plan" and occ else None
        goal = t["goal"] + (f"\n\nThis run covered exactly {CD.period_text(win)}, the end being when it started." if win else "")
        ev = evidence_of(c, t, occ)
        p = P.text("shared", "TASK_JUDGE").format(goal=goal, done="\n".join(f"{i + 1}. {d}" for i, d in enumerate(asked)),
                                                  result=TC.cut(text, 30000) + (f"\n\n{ev}" if ev else ""))  # cap: prompt (the answer; the vault keeps all of it)
        raw = (ask or (lambda q: __import__("evals").ask({"id": "eval", "model": "gpt-sub"}, q, ref=f"judge task {t['id']}")))(p)
        d = json.loads(re.search(r"\{.*\}", raw, re.S).group(0)) if isinstance(raw, str) else raw
        got = [{"point": asked[i] if i < len(asked) else str(x.get("point", "")), "met": bool(x.get("met")), "why": str(x.get("why", ""))}
               for i, x in enumerate(d.get("points") or [])]
    rest = iter(got)
    pts = [p for p in (fixed[i] if i in fixed else next(rest, None) for i in range(len(t["done"]))) if p] + list(rest)
    n = sum(x["met"] for x in pts)
    verdict = "met" if pts and n == len(pts) else "partly" if n else "not met"
    return {"verdict": verdict, "points": pts}


def credit(c, t, verdict, day=None, occ=None):
    """The day's history row of each agent, harness and model the task (or its run `occ`) used, for its kind."""
    import conductor as CD
    day = day or now().date().isoformat()
    run = CD.run_of(t["id"], occ or 1)
    tok = tokens_of(run) if t["door"] == "plan" else 0
    corrections = len(t["spec"].get("answered") or []) + (1 if t["spec"].get("retried") else 0)
    if t["door"] == "plan":
        rows = [(s["agent"], s["harness"], s["model"], tokens_of(f"{run}:step:{s['idx']}"),
                 (dt.datetime.fromisoformat(s["ended"]) - dt.datetime.fromisoformat(s["started"])).total_seconds() if s["started"] and s["ended"] else 0)
                for s in CD.steps(c, t["id"], occ)]
    else:
        agent = {"mission": "desk" if t["kind"] == "briefing" else "mission", "build": "builder", "claude": "claude-task"}.get(t["door"], t["door"] or "?")
        card = CD.cards().get(agent) or {}
        seconds = (dt.datetime.fromisoformat(t["updated"]) - dt.datetime.fromisoformat(t["created"])).total_seconds()
        rows = [(agent, card.get("harness") or ("claude-code" if agent == "claude-task" else "?"), card.get("model") or "", tok, seconds)]
    v = {"met": (1, 0, 0, 0), "partly": (0, 1, 0, 0), "not met": (0, 0, 1, 0), "failed": (0, 0, 0, 1)}.get(verdict)
    if not v:
        return tok
    for agent, harness, model, tokens, seconds in rows:
        c.execute("""insert into task_metrics values (?,?,?,?,?,1,?,?,?,?,?,?,?)
                     on conflict (day, agent, harness, model, kind) do update set tasks=tasks+1, met=met+excluded.met,
                     partly=partly+excluded.partly, not_met=not_met+excluded.not_met, failed=failed+excluded.failed,
                     seconds=seconds+excluded.seconds, tokens=tokens+excluded.tokens, corrections=corrections+excluded.corrections""",
                  (day, agent, harness, model or "", t["kind"] or "?", *v, seconds, tokens, corrections))
    c.commit()
    return tok


def judge_due(c, ask=None):
    """Finished tasks with the owner's definition of done that are not judged yet: judge, record, credit, tell the archive.
    A Conductor task is judged per run (judge_runs)."""
    import conductor as CD
    import tasks as TK
    table(c)
    CD.table(c)
    judge_runs(c, ask)
    rows = c.execute("select id from tasks where status in ('done', 'failed') and judged is null and (source in ('app', 'gate') or source like 'rule:%') "
                     "and not (door = 'plan' and exists (select 1 from task_occ o where o.task = tasks.id)) order by id limit 5").fetchall()  # cap: parse (five a pass; the rest the next pass)
    for r in rows:
        t = TK.row(c, r["id"])
        try:
            j = judge(c, t, ask) if t["status"] == "done" else {"verdict": "failed", "points": []}
        except Exception as e:                       # a usage limit or a broken answer: tried again on the next pass; logged
            M.log(f"staffing: judging task {t['id']} failed: {type(e).__name__}: {e}")
            continue
        tok = credit(c, t, j["verdict"])
        TK.put(c, t["id"], verdict=j["verdict"], judged=TK.now(), tokens=tok, cost=cost_of(f"task:{t['id']}") if t["door"] == "plan" else None,
               spec={**t["spec"], "judgement": j})
        for d in {s["agent"] for s in __import__("conductor").steps(c, t["id"])} if t["door"] == "plan" else ():
            design_scored(c, d, t["id"], j["verdict"])
        M.event("task", "", f"Task #{t['id']} judged: {j['verdict']} ({sum(p['met'] for p in j['points'])} of {len(j['points'])} points)", title="Tasks")


def judge_runs(c, ask=None):
    """Each finished run of a Conductor task (TSK-22) against the task's definition of done: the run's verdict, points and
    tokens on the run, the day's history credited for the run's own steps, and the task showing its latest verdict."""
    import conductor as CD
    import tasks as TK
    rows = c.execute("""select o.task, o.occ, o.status, o.result from task_occ o join tasks t on t.id = o.task
                        where o.status in ('done', 'failed') and o.judged is null and t.door = 'plan'
                        and (t.source in ('app', 'gate') or t.source like 'rule:%' or t.source like 'trial:%') order by o.ended limit 5""").fetchall()  # cap: parse (five a pass; the rest the next pass)
    for r in rows:
        t = TK.row(c, r["task"])
        f = M.VAULT / (r["result"] or "")
        try:
            j = ({"verdict": "failed", "points": []} if r["status"] == "failed" else
                 judge(c, t, ask, text=f.read_text() if r["result"] and f.is_file() else "", occ=r["occ"]))
        except Exception as e:                       # a usage limit or a broken answer: tried again on the next pass; logged
            M.log(f"staffing: judging task {t['id']} run {r['occ']} failed: {type(e).__name__}: {e}")
            continue
        tok = credit(c, t, j["verdict"], occ=r["occ"])
        usd = cost_of(CD.run_of(t["id"], r["occ"]))
        c.execute("update task_occ set verdict=?, judged=?, tokens=?, cost=?, judgement=? where task=? and occ=?",
                  (j["verdict"], TK.now(), tok, usd, json.dumps(j, ensure_ascii=False), t["id"], r["occ"]))
        c.commit()
        CD.mapped(c, t["id"], r["occ"])                  # the map's numbers show the verdict
        TK.put(c, t["id"], verdict=j["verdict"], judged=TK.now(), tokens=tok, cost=usd, spec={**TK.row(c, t["id"])["spec"], "judgement": {**j, "run": r["occ"]}})
        for d in {s["agent"] for s in CD.steps(c, t["id"], r["occ"])}:
            design_scored(c, d, t["id"], j["verdict"])
        run = f" run {r['occ']}" if t["rhythm"].get("type") in ("schedule", "event") or r["occ"] > 1 else ""
        M.event("task", "", f"Task #{t['id']}{run} judged: {j['verdict']} ({sum(p['met'] for p in j['points'])} of {len(j['points'])} points)", title="Tasks")


# ---------- measured abilities (TSK-13) ----------
def abilities(c, days=30):
    """{(agent, kind): {tasks, met share, seconds per task, tokens per task, harness, model}} over the last `days`."""
    table(c)
    since = (now().date() - dt.timedelta(days=days)).isoformat()
    out = {}
    for r in c.execute("""select agent, kind, harness, model, sum(tasks) n, sum(met) met, sum(partly) partly, sum(not_met) nm, sum(failed) f,
                          sum(seconds) s, sum(tokens) tok, sum(corrections) cor from task_metrics where day >= ? group by agent, kind""", (since,)):
        out[(r["agent"], r["kind"])] = {"tasks": r["n"], "success": round((r["met"] + 0.5 * r["partly"]) / r["n"], 2),
                                        "seconds": round(r["s"] / r["n"]), "tokens": round(r["tok"] / r["n"]), "corrections": r["cor"],
                                        "harness": r["harness"], "model": r["model"], "failed": r["f"]}
    return out


# ---------- routing (TSK-14) ----------
def route(step, kind, cards, measured, limited):
    """The agent for a step: the planned one, unless another agent sharing a role did that kind of task clearly better
    (from MIN_TASKS judged tasks on), or the planned one's subscription is at its limit and another one's is not.
    -> (agent, why or "")."""
    import conductor as CD
    import swarm_client as SW
    planned = step["agent"]
    if planned not in cards:                           # a temporary agent: no one to route to
        return planned, ""
    roles = set(cards[planned].get("roles") or [])
    alts = [a for a, cd in cards.items() if a != planned and CD.runs_steps(cd) and roles & set(cd.get("roles") or [])]
    score = lambda a: measured.get((a, kind), {}).get("success") if measured.get((a, kind), {}).get("tasks", 0) >= MIN_TASKS else None
    engine = lambda a: SW.ENGINE.get(cards[a].get("model") or "", "")
    if limited(engine(planned)):
        free = [a for a in alts if engine(a) and not limited(engine(a))]
        if free:
            best = max(free, key=lambda a: score(a) or 0)
            return best, f"{planned}'s subscription is at its usage limit; {best} shares its role ({', '.join(sorted(roles & set(cards[best].get('roles') or [])))})"
    mine = score(planned)
    better = [(score(a), a) for a in alts if score(a) is not None and score(a) >= (mine if mine is not None else 0) + ROUTE_MARGIN]
    if mine is not None and better:
        s, best = max(better)
        return best, f"{best} met {kind} tasks {s:.0%} of the time, {planned} {mine:.0%} (last 30 days)"
    return planned, ""


# ---------- temporary agents (TSK-15, TSK-16) ----------
def admit(design):
    """A temporary agent's design within the grants of a task that starts by itself, or ValueError."""
    if design.get("model") not in TEMP_MODELS:
        raise ValueError(f"a temporary agent runs on {' or '.join(TEMP_MODELS)}, not {design.get('model')!r}")
    if set(design.get("tools") or []) - set(TEMP_GRANTS):
        raise ValueError(f"a temporary agent gets no tools; asked for {sorted(set(design['tools']) - set(TEMP_GRANTS))}")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,40}", design.get("name") or ""):
        raise ValueError("a temporary agent's name is lower-case letters, digits and dashes")
    if len(design.get("instructions") or "") < 40:
        raise ValueError("a temporary agent needs instructions (at least a few sentences)")
    return design


def design_for(c, step, goal, ask=None):
    """The temporary agent for a step: an archived design of the same name if there is one, else one the intake writes."""
    import prompts as P
    table(c)
    want = step.get("needs") or step["why"]
    raw = (ask or (lambda q: M.ask_json(q, os.environ["VK_INTAKE"])))(P.text("intake", "TEMP_AGENT").format(goal=goal, step=step["title"], needs=want))
    d = admit({"name": str(raw.get("name", "")).strip().lower(), "purpose": str(raw.get("purpose", "")).strip(),
               "instructions": str(raw.get("instructions", "")).strip(), "model": raw.get("model") or "gpt-sub", "tools": raw.get("tools") or []})
    old = c.execute("select * from agent_designs where name=?", (d["name"],)).fetchone()
    if old:                                            # the archive's design is reused as it is: its scores stay its own
        return dict(old)
    c.execute("insert into agent_designs (name, purpose, instructions, model, created) values (?,?,?,?,?)",
              (d["name"], d["purpose"], d["instructions"], d["model"], now().isoformat(timespec="seconds")))
    c.commit()
    return dict(c.execute("select * from agent_designs where name=?", (d["name"],)).fetchone())


def _litellm(path, body):
    req = urllib.request.Request(LITELLM + path, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def key_for(alias, model, call=None):
    """The temporary agent's own key: models, no MCP server, a small daily budget. Kept in memory only."""
    with lock:
        if alias not in _keys:
            r = (call or _litellm)("/key/generate", {"key_alias": alias, "models": [model], "max_budget": TEMP_BUDGET, "budget_duration": "1d",
                                                      "object_permission": {"mcp_servers": []}, "metadata": {"tags": ["temporary-agent"]}})
            _keys[alias] = r["key"]
        return _keys[alias]


def end_keys(task_id, call=None):
    """TSK-15: a temporary agent ends with its task: its keys are deleted."""
    pre = f"vk-tmp-{task_id}-"
    gone = [a for a in list(_keys) if a.startswith(pre)]
    if gone:
        (call or _litellm)("/key/delete", {"key_aliases": gone})
        for a in gone:
            _keys.pop(a, None)
    return gone


def run_temp(c, t, s, prompt, design, call=None):
    """One step by a temporary agent: its instructions, then the step, on its own key."""
    key = key_for(f"vk-tmp-{t['id']}-{s['idx']}", design["model"], call)
    return M.ask_text(f"{design['instructions']}\n\n{prompt}", key, design["model"])


def design_scored(c, name, task_id, verdict):
    """The archive's score of a design after a judged task; three met -> an idea for a permanent agent (TSK-16)."""
    import swarm_client as SW
    r = c.execute("select * from agent_designs where name=?", (name,)).fetchone()
    if not r or r["last_task"] == task_id:
        return
    col = {"met": "met", "partly": "partly", "not met": "not_met"}.get(verdict)
    c.execute(f"update agent_designs set uses=uses+1, last_task=?{f', {col}={col}+1' if col else ''} where id=?", (task_id, r["id"]))
    c.commit()
    r = dict(c.execute("select * from agent_designs where id=?", (r["id"],)).fetchone())
    if r["met"] >= PROMOTE_AFTER and not r["proposed"]:
        SW.propose("staffing", [{"title": f"Make the temporary agent “{r['name']}” a permanent agent", "area": "ops", "size": "small",
                                 "why": f"It served {r['uses']} tasks; {r['met']} met their definition of done.",
                                 "signal": f"temporary agent {r['name']}: {r['met']} of {r['uses']} tasks met",
                                 "description": f"Add a card for {r['name']} to config/agents.yaml (purpose: {r['purpose']}; harness python; model "
                                                f"{r['model']}; its own key in ops/keys.sh) and its instructions as prompts/{r['name']}.md, "
                                                f"replay-tested like any agent change. Instructions:\n\n{r['instructions']}"}], "temporary agent archive")
        c.execute("update agent_designs set proposed=? where id=?", (now().isoformat(timespec="seconds"), r["id"]))
        c.commit()


def sweep(call=None):
    """After a restart: temporary keys left from tasks that are over are deleted (the keys lived in memory only)."""
    try:
        r = (call or (lambda p, b: json.load(urllib.request.urlopen(urllib.request.Request(
            LITELLM + p, headers={"Authorization": f"Bearer {os.environ['LITELLM_MASTER_KEY']}"}), timeout=30))))(
            "/key/list?return_full_object=true&size=100", None)   # LiteLLM's largest page; temporary keys are few
        old = [k.get("key_alias") for k in r.get("keys") or [] if str(k.get("key_alias") or "").startswith("vk-tmp-")]
        if old:
            _litellm("/key/delete", {"key_aliases": old}) if call is None else call("/key/delete", {"key_aliases": old})
        return old
    except Exception as e:                             # LiteLLM not up yet: the next start sweeps; logged
        M.log(f"staffing: temporary key sweep failed: {type(e).__name__}: {e}")
        return []


def worker():
    c = M.db()
    table(c)
    sweep()
    while not M.stop.is_set():
        try:
            judge_due(c)
        except Exception as e:                         # the next pass tries again; it is logged
            M.log(f"staffing: {type(e).__name__}: {e}")
        M.rest(c, "staffing", 30)


def state(c):
    """Tasks → Agents, measured: each agent's results per kind of task, and the temporary agents' archive."""
    table(c)
    ab = [{"agent": a, "kind": k, **v} for (a, k), v in sorted(abilities(c).items())]
    designs = [dict(r) for r in c.execute("select id, name, purpose, model, created, uses, met, partly, not_met, proposed from agent_designs order by id desc limit 30").fetchall()]  # cap: list
    return {"staffing": {"abilities": ab, "designs": designs}}
