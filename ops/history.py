"""The telemetry history (TSK-25): one row a day per agent, model, harness and kind of work, kept for a year.

Each row counts the agent's runs that ended that day (from the runtime record): how many, how many ended well or
failed, the judge's verdicts on the tasks they worked for (task_metrics, ops/staffing.py), tokens in, out and cached,
the median and 95th-percentile time of a run, and what the tokens would cost at list price (ops/prices.py). A run's
model is the one it used most; its tokens of every model are priced each at its own price. The kind of work is the
task's kind when the run worked for a task, else what it was: a mission run, a build, a chat, a crew job, an intake.

The runner rolls up today and yesterday every hour (a day is written again whole, so a late run is counted) and keeps
365 days; public/telemetry.json holds the rows for the app's Stack → Telemetry, whose numbers open their runs.
"""
import datetime as dt
import json
import sqlite3
import statistics
import threading
from pathlib import Path

import prices as PR

RUNTIME_DB = Path("/srv/ai/missions/app/runtime.db")
KEEP_DAYS = 365
M = None                                          # ops/missions.py, set by its main()
HARNESS = {"hermes": "hermes", "claude": "claude-code", "runner": "python", "conductor": "conductor", "watchdog": "runner"}
KIND_OF = (("mission-run:", "mission"), ("build:", "build"), ("crew:", "crew"), ("claude-task:", "claude"), ("hermes:main", "chat"),
           ("task-intake:", "intake"), ("phone", "phone"), ("mail", "mail"))


def table(c):
    c.execute("""create table if not exists agent_days (day text, agent text, model text, harness text, kind text, runs integer,
                 ok integer, failed integer, met integer, partly integer, not_met integer, tin integer, tout integer, cached integer,
                 p50_s real, p95_s real, cost real, unpriced text, primary key (day, agent, model, harness, kind))""")


def p95(xs):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))] if xs else None


def kind_of(run, refs, task_kind):
    """The task's kind when the run (or a run it is inside) worked for a task, else what the run itself is."""
    r, seen, near = run, 0, None
    while r and seen < 8:                             # up the runs it is inside: a task wins, else the nearest known kind
        if r.startswith("task:") and r.split(":")[1].split(".")[0].isdigit():
            return task_kind.get(int(r.split(":")[1].split(".")[0])) or "task"
        near = near or next((k for p, k in KIND_OF if r.startswith(p)), None)
        r, seen = refs.get(r), seen + 1
    return near or "other"


def rollup(c, day, db=None, table_=None):
    """The rows of one day (YYYY-MM-DD, local time), written again whole."""
    table(c)
    t0 = dt.datetime.fromisoformat(day).astimezone().timestamp()
    t1 = t0 + 86400
    try:
        r = sqlite3.connect(f"file:{db or RUNTIME_DB}?mode=ro", uri=True)
        runs = r.execute("select run, ref, agent, source, started, ended, end_state from runs where ended >= ? and ended < ?", (t0, t1)).fetchall()
        refs = dict(r.execute("select run, ref from runs").fetchall())
        usage = {}
        for run, model, data in r.execute("select e.run, e.title, e.data from events e join runs x on x.run = e.run where e.kind='llm' "
                                          "and x.ended >= ? and x.ended < ?", (t0, t1)):
            tok = (json.loads(data or "{}").get("tokens") or {})
            u = usage.setdefault(run, {}).setdefault(model or "", {"in": 0, "out": 0, "cached": 0})
            for k in u:
                u[k] += int(tok.get(k) or 0)
        r.close()
    except sqlite3.Error as e:
        M.log(f"history: the runtime record not read for {day}: {e}")
        return 0
    task_kind = {row[0]: row[1] for row in c.execute("select id, kind from tasks")} if c.execute(
        "select 1 from sqlite_master where name='tasks'").fetchone() else {}
    prices = table_ or PR.load()
    rows = {}
    for run, ref, agent, source, started, ended, state in runs:
        u = usage.get(run, {})
        model = max(u, key=lambda m: u[m]["in"] + u[m]["out"]) if u else ""
        key = (day, agent or "?", model, HARNESS.get(source or "", source or "?"), kind_of(run, refs, task_kind))
        x = rows.setdefault(key, {"runs": 0, "ok": 0, "failed": 0, "tin": 0, "tout": 0, "cached": 0, "secs": [], "cost": 0.0, "unpriced": set()})
        x["runs"] += 1
        x["ok"] += state in ("done", "ok")
        x["failed"] += state in ("failed", "stalled", "limit")
        x["secs"].append(max(0.0, (ended or started) - started))
        for k, src in (("tin", "in"), ("tout", "out"), ("cached", "cached")):
            x[k] += sum(v[src] for v in u.values())
        usd, missing = PR.total(u, prices)
        x["cost"] += usd
        x["unpriced"].update(m for m in missing if m)
    verdicts = {}                                     # the judge's verdicts of the day: on the row of the same agent, harness,
    if c.execute("select 1 from sqlite_master where name='task_metrics'").fetchone():   # model and kind, else on that agent's
        for a, h, mo, k, met, partly, nm in c.execute("select agent, harness, model, kind, sum(met), sum(partly), sum(not_met) from task_metrics "
                                                      "where day=? group by agent, harness, model, kind", (day,)):   # busiest row of the kind
            exact = (day, a, mo or "", h, k)
            if exact not in rows:
                cands = [key for key in rows if key[1] == a and key[4] == k]
                exact = max(cands, key=lambda key: rows[key]["runs"]) if cands else None
            if exact:
                v = verdicts.get(exact, (0, 0, 0))
                verdicts[exact] = (v[0] + (met or 0), v[1] + (partly or 0), v[2] + (nm or 0))
    c.execute("delete from agent_days where day=?", (day,))
    for (d, agent, model, harness, kind), x in rows.items():
        met, partly, nm = verdicts.get((d, agent, model, harness, kind), (0, 0, 0))
        c.execute("insert into agent_days values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (d, agent, model, harness, kind, x["runs"], x["ok"], x["failed"], met, partly, nm, x["tin"], x["tout"], x["cached"],
                   round(statistics.median(x["secs"]), 1), round(p95(x["secs"]), 1), round(x["cost"], 6), ",".join(sorted(x["unpriced"]))))
    c.execute("delete from agent_days where day < ?", ((dt.date.fromisoformat(day) - dt.timedelta(days=KEEP_DAYS)).isoformat(),))
    c.commit()
    return len(rows)


def rows(c, days=KEEP_DAYS):
    table(c)
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    cols = [r[1] for r in c.execute("pragma table_info(agent_days)")]
    return [dict(zip(cols, r)) for r in c.execute("select * from agent_days where day >= ? order by day", (since,))]


def write(c):
    """public/telemetry.json: the year's rows and the price table, for Stack → Telemetry."""
    out = {"rows": rows(c), "prices": PR.load(), "written": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
    tmp = M.PUBLIC / "telemetry.json.tmp"
    tmp.write_text(json.dumps(out))
    tmp.replace(M.PUBLIC / "telemetry.json")


def worker():
    """Every hour: today and yesterday rolled up, the file for the app written; the first pass also fills the days the
    runtime record still holds (its events stay 90 days)."""
    c = M.db()
    table(c)
    first = True
    while not M.stop.is_set():
        try:
            today = dt.date.today()
            back = 90 if first and not c.execute("select 1 from agent_days limit 1").fetchone() else 1
            for n in range(back, -1, -1):
                rollup(c, (today - dt.timedelta(days=n)).isoformat())
            write(c)
            first = False
        except Exception as e:                        # the next hour tries again; logged
            M.log(f"history: {type(e).__name__}: {e}")
        M.rest(c, "history", 3600)


def start():
    threading.Thread(target=worker, daemon=True, name="history").start()
