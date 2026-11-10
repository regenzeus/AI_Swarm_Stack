"""WFL-09: n8n decides when every scheduled job runs. This reads it from the jobs' workflows: which workflow starts a
crew job or a task, its schedule in words, whether n8n runs it, when it runs next and how often. And it makes the
workflow of a task that gets a schedule, once: a task given in a sentence ("every Monday at 8"), a briefing or price
watch a mission hands over, a mission made with a schedule. After that the schedule is n8n's: changed on the canvas
inside the app (Workflows) and exported to git (WFL-08); the runner never edits it.

A workflow is the repository's (n8n/workflows/*.json) or one the runner made or switched off since the last export
(/srv/ai/missions/flows/made/*.json, the runner's newer word: it wins until an export brings the same into git, then
its file goes). A deploy's import keeps that word too (ops/n8n_sync.py). Of the repository's files only those the
deployment runs count (PLT-38, deployments/<name>/workflows.yaml): a work deployment shows no schedule of home's jobs.

    python3 ops/n8n_jobs.py        every job n8n starts: its workflow, schedule, and next run
"""
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

R = Path(__file__).resolve().parent.parent
REPO = R / "n8n/workflows"
MADE = Path("/srv/ai/missions/flows/made")
STEP = "CUSTOM.aistackStep"
CACHE_S = 30                                         # the files are read again at most every 30 s (the state is written every few)
_cache = {"t": 0.0, "data": None}


# ---------- reading the workflows ----------
def cron_of(wf):
    """The workflow's schedule as a cron expression, or "" (started only when called, or by an event)."""
    for n in wf.get("nodes") or []:
        if n.get("type") == "n8n-nodes-base.scheduleTrigger":
            for iv in ((n.get("parameters") or {}).get("rule") or {}).get("interval") or []:
                if iv.get("field") == "cronExpression":
                    return str(iv.get("expression") or "").strip()
    return ""


def target(wf):
    """-> ("crew", job) or ("task", id) from the workflow's AI Stack step, or (None, None)."""
    for n in wf.get("nodes") or []:
        p = n.get("parameters") or {}
        if n.get("type") == STEP and p.get("kind") == "crew" and p.get("job"):
            return "crew", str(p["job"])
        if n.get("type") == STEP and p.get("kind") == "task" and str(p.get("task", "")).isdigit():
            return "task", int(p["task"])
    return None, None


def _files(folder):
    out = {}
    for p in sorted(Path(folder).glob("*.json")) if Path(folder).is_dir() else []:
        try:
            out[p.name] = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
    return out


def chosen(repo=REPO):
    """PLT-38: which of the repository's files this deployment runs: the names of its workflows.yaml and what its
    trackers imply (ops/deployment.py) for the stack's own folder; every file of any other folder (a test's)."""
    if Path(repo).resolve() != REPO.resolve():
        return ["*"]
    import deployment as DEPLOY
    return DEPLOY.workflow_names()


def workflows(repo=REPO, made=MADE, names=None):
    """Every workflow of this deployment by its id, as n8n should have it: the repository's that the deployment runs
    (names, default chosen(repo); ["*"] for every file), with the runner's newer word over it (the runner made it
    here, so it is always this deployment's). -> {id: {"wf", "file", "made"}}"""
    import fnmatch
    names = chosen(repo) if names is None else names
    out = {}
    for src, folder in ((False, repo), (True, made)):
        for name, wf in _files(folder).items():
            if wf.get("id") and (src or any(fnmatch.fnmatchcase(name.removesuffix(".json"), n) for n in names)):
                out[str(wf["id"])] = {"wf": wf, "file": name, "made": src}
    return out


def index(repo=None, made=None):
    """-> {("crew", job) | ("task", id): {"id", "name", "active", "cron", "tz", "file", "made"}}; read again at most every
    CACHE_S unless the folders are given (tests)."""
    fresh = repo is None and made is None
    if fresh and _cache["data"] is not None and time.time() - _cache["t"] < CACHE_S:
        return _cache["data"]
    out = {}
    for wid, w in workflows(repo or REPO, made or MADE).items():
        kind, key = target(w["wf"])
        if kind:
            out[(kind, key)] = {"id": wid, "name": w["wf"].get("name") or w["file"], "active": bool(w["wf"].get("active")),
                                "cron": cron_of(w["wf"]), "tz": (w["wf"].get("settings") or {}).get("timezone") or "",
                                "file": w["file"], "made": w["made"]}
    if fresh:
        _cache.update(t=time.time(), data=out)
    return out


def of(kind, key, idx=None):
    return (idx if idx is not None else index()).get((kind, int(key) if kind == "task" else str(key)))


# ---------- when ----------
def _field(spec, lo, hi):
    out = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part == "*":
            a, b = lo, hi
        elif "-" in part:
            a, b = (int(x) for x in part.split("-", 1))
        else:
            a = b = int(part)
            if step > 1:
                b = hi                                 # "5/15": from 5, every 15
        out.update(range(a, b + 1, step))
    return out


def parse(cron):
    """A five-field cron expression -> (minutes, hours, days, months, weekdays, day of month any, weekday any), or None."""
    f = str(cron or "").split()
    if len(f) != 5:
        return None
    try:
        dow = {d % 7 for d in _field(f[4], 0, 7)}     # 0 and 7 are Sunday
        return (_field(f[0], 0, 59), _field(f[1], 0, 23), _field(f[2], 1, 31), _field(f[3], 1, 12), dow, f[2] == "*", f[4] == "*")
    except ValueError:
        return None


def _zone(name, after):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name) if name else after.astimezone().tzinfo
    except Exception:                                # no time zone data here: the offset the time came with
        return after.tzinfo or after.astimezone().tzinfo


def next_fire(cron, after, tz=""):
    """The first time after `after` (aware) at which the cron fires, in its workflow's time zone; None if it never does
    within four years (or is no cron)."""
    p = parse(cron)
    if not p:
        return None
    mins, hours, days, months, dows, dom_any, dow_any = p
    zone = _zone(tz, after)
    t = after.astimezone(zone).replace(tzinfo=None, second=0, microsecond=0) + dt.timedelta(minutes=1)
    end = t + dt.timedelta(days=4 * 366)
    while t < end:
        if t.month not in months:
            t = (t.replace(day=1) + dt.timedelta(days=32)).replace(day=1, hour=0, minute=0)
            continue
        dom_ok, dow_ok = t.day in days, (t.weekday() + 1) % 7 in dows
        if not (dom_ok and dow_ok if dom_any or dow_any else dom_ok or dow_ok):
            t = (t + dt.timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if t.hour not in hours:
            t = (t + dt.timedelta(hours=1)).replace(minute=0)
            continue
        if t.minute not in mins:
            t += dt.timedelta(minutes=1)
            continue
        return t.replace(tzinfo=zone)
    return None


def every(cron, after=None, tz=""):
    """Seconds between two runs (the next two), for "did it run when it should" (OBS-11); None for no cron."""
    after = after or dt.datetime.now().astimezone()
    a = next_fire(cron, after, tz)
    b = a and next_fire(cron, a, tz)
    return round((b - a).total_seconds()) if a and b else None


def words(cron):
    """A cron expression in the owner's words ("daily 04:30", "every 5 minutes", "Mondays 04:30")."""
    import flows_view as FV
    return FV.cron_words(cron)


def next_run(kind, key, now=None, idx=None):
    """When n8n starts the job next (ISO, to the minute), or None: no workflow, not published, or no schedule."""
    w = of(kind, key, idx)
    if not w or not w["active"] or not w["cron"]:
        return None
    n = next_fire(w["cron"], now or dt.datetime.now().astimezone(), w["tz"])
    return n.isoformat(timespec="minutes") if n else None


def schedule(kind, key, idx=None):
    """The job's schedule in words, "switched off" for a workflow n8n does not run, or None when it has no workflow."""
    w = of(kind, key, idx)
    if not w:
        return None
    if not w["active"]:
        return "switched off"
    return words(w["cron"]) if w["cron"] else "when called"


# ---------- a task that gets a schedule ----------
def cron_of_rhythm(s):
    """A task's or mission's schedule (the runner's words: daily HH:MM, weekdays HH:MM, weekly mon,thu HH:MM, every Nh)
    -> a cron expression, or ""."""
    s = str(s or "").strip().lower()
    days = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}
    m = re.fullmatch(r"(daily|weekdays) (\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m[3])} {int(m[2])} * * {'*' if m[1] == 'daily' else '1-5'}"
    m = re.fullmatch(r"weekly ((?:mon|tue|wed|thu|fri|sat|sun)(?:,(?:mon|tue|wed|thu|fri|sat|sun))*) (\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m[3])} {int(m[2])} * * {','.join(str(days[d]) for d in m[1].split(','))}"
    m = re.fullmatch(r"every (\d{1,2})h", s)
    if m and 1 <= int(m[1]) <= 24:
        return "0 * * * *" if int(m[1]) == 1 else f"0 */{int(m[1])} * * *"
    return ""


LIVE = ("scheduled", "running")                     # a repeating task between its runs, or in one
OVER = ("cancelled", "done", "failed")               # a cancelled task, or a mission archived (TSK-41: its task is done)


def wants(c, repo=REPO, made=MADE):
    """The tasks that run on a schedule and have no workflow yet: a plan task, or a task whose mission does the work.
    -> [(task row, its schedule)]"""
    have = index(repo, made)
    out = []
    for r in c.execute("select id, title, door, ref, status, rhythm from tasks where door in ('plan', 'mission') "
                       "and status in (?, ?) order by id", LIVE).fetchall():
        try:
            rh = json.loads(r["rhythm"] or "{}")
        except ValueError:
            continue
        if rh.get("type") == "schedule" and ("task", r["id"]) not in have:
            out.append((dict(r), rh.get("schedule") or ""))
    return out


def make(t, sched, run=subprocess.run, made=MADE):
    """The task's workflow: written to the runner's folder, imported into n8n and published (n8n restarts to load it,
    about 30 s; a waiting run survives). -> the file's name. Raises when n8n refuses."""
    import n8n_gen as G
    import n8n_switch as SW
    cron = cron_of_rhythm(sched)
    if not cron:
        raise ValueError(f"its schedule {sched!r} is not one n8n can take")
    wf = G.workflow("task", t["id"], f"Task #{t['id']}: {t['title']}", cron, {"kind": "task", "task": t["id"]},
                    f"Made by the runner when the task got its schedule ({sched}); one run of the task (WFL-05).")
    import n8n_sync as NS
    Path(made).mkdir(parents=True, exist_ok=True)
    p = Path(made) / NS.file_name(wf)
    p.write_text(json.dumps(wf, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    q = NS.put(p, run=run)
    if q.returncode:
        p.unlink(missing_ok=True)
        raise ValueError(f"n8n refused it: {(q.stderr or q.stdout).strip()}")
    try:
        SW.switch(p, True, run=run)
    except Exception:                                # not published: no file, so the next pass makes it again
        p.unlink(missing_ok=True)
        raise
    return p.name


def retire(t, run=subprocess.run, repo=REPO, made=MADE):
    """A cancelled task's workflow is switched off (unpublished); the runner's word on it is kept in its folder until an
    export brings it into git. -> the file's name, or None when n8n does not start it."""
    import n8n_switch as SW
    w = of("task", t["id"], index(repo, made))
    if not w or not w["active"]:
        return None
    p = Path(made) / w["file"]
    if not w["made"]:                                # the repository's file stays as it is: the live checkout is never edited
        Path(made).mkdir(parents=True, exist_ok=True)
        p.write_text((Path(repo) / w["file"]).read_text())
    SW.switch(p, False, run=run)
    return p.name


def settled(repo=REPO, made=MADE):
    """The runner's words that git now holds the same (an export landed): their files go. -> the names removed."""
    gone = []
    have = {str(wf.get("id")): wf for wf in _files(repo).values()}
    for name, wf in _files(made).items():
        g = have.get(str(wf.get("id")))
        if g and bool(g.get("active")) == bool(wf.get("active")) and cron_of(g) == cron_of(wf):
            (Path(made) / name).unlink(missing_ok=True)
            gone.append(name)
    return gone


_told = set()                                       # tasks whose workflow could not be made: said once, tried again each pass


def reconcile(c, run=subprocess.run, say=print, repo=REPO, made=MADE):
    """One pass (the step service's worker, every minute): each task that got a schedule gets its workflow, each one
    that is over has its workflow switched off, and what git holds now leaves the runner's folder.
    -> [what changed, in words]."""
    done = []
    for t, sched in wants(c, repo, made):
        try:
            done.append(f"task #{t['id']} runs from its n8n workflow {make(t, sched, run=run, made=made)} ({words(cron_of_rhythm(sched))})")
            _told.discard(t["id"])
        except Exception as e:                        # n8n down or a schedule it cannot take: tried again on the next pass
            if t["id"] not in _told:
                _told.add(t["id"])
                say(f"task #{t['id']}: its n8n workflow was not made yet: {type(e).__name__}: {e}")
    idx = index(repo, made)
    for r in c.execute("select id, title, status from tasks where door in ('plan', 'mission') and status in (?, ?, ?) order by id", OVER).fetchall():
        w = of("task", r["id"], idx)
        if w and w["active"]:
            try:
                done.append(f"task #{r['id']} is {r['status']}: its n8n workflow {retire(dict(r), run=run, repo=repo, made=made)} is off")
            except Exception as e:                    # tried again on the next pass
                say(f"task #{r['id']}: its n8n workflow was not switched off yet: {type(e).__name__}: {e}")
    done += [f"{n}: git holds it now" for n in settled(repo, made)]
    if done:
        _cache["data"] = None
    return done


if __name__ == "__main__":
    now = dt.datetime.now().astimezone()
    for (kind, key), w in sorted(index().items(), key=lambda x: (x[0][0], str(x[0][1]))):
        print(f"{kind}:{key}  {w['file']}  {schedule(kind, key) or '-'}  next {next_run(kind, key, now) or '-'}"
              + ("  (the runner's word)" if w["made"] else ""))
    sys.exit(0)
