"""The crew: the stack's housekeeping agents in one place (Mission Control → Agents → Crew).

Most of them are systemd user timers that existed before (memory review, skill sync, curator, backup, restore drill,
upgrade check, digest, code graph); the self-review runs as a runner thread (ops/improve.py). This module reads
their state from systemd and the journal for the app (the app container cannot), starts one on request ("Run now"),
and adds agents of its own:

  maintainability  Claude Code, read-only, over a fresh copy of main in the builder sandbox: complexity hot spots,
                   duplicated logic, dead code, docs drift -> up to 5 proposals (the "The stack suggests" list)
  tests            runs the test suite three times in the CI image: flaky tests, slow tests, untested functions in
                   ops/ -> proposals; no model, $0
  memory           the long-term memory (Hindsight bank "owner"): near-duplicates by text, plus one ChatGPT pass for
                   contradictions, stale facts and test noise -> suggestions the owner accepts one by one ("Forget"
                   soft-retires the fact in Hindsight; reversible). Nothing is retired without the owner's tap.
  doctor           every 6 hours and soon after a new health alert: the open health issues with their logs, diagnosed
                   by Claude Code (expected, noise, external or a real fault) -> fix or detector proposals (ops/doctor.py)
  phone-cleanup    weekly: the AI phone's cleanup facts -> one step per item (old files by year, unused apps, caches),
                   each run on the phone only after the owner's Approve on it, freed space reported (ops/phone_agents.py)
  phone-check      weekly: battery, storage, security patch, connection, screen awake; fails only on a real fault
  inbox            daily, under the owner's Gmail read grant: newsletters worth keeping -> vault raw/_inbox (ops/inbox.py)

  python3 ops/crew.py maintainability|tests|memory|doctor|phone-cleanup|phone-check|inbox|checker      (the crew-*.service units)
Each agent writes /srv/ai/missions/crew/<id>.json (last run, duration, result, findings) for the app.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import journal as J
from textcap import limit, tail                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import notify as N                                # OBS-16: the one notification path

M = I = None                                      # ops/missions.py and ops/improve.py (set by missions.main or run())
STACK = Path.home() / "ai-stack"
OUT = Path("/srv/ai/missions/crew")
BUILDER, HERMES = "aistack-builder-1", "aistack-hermes-1"
CI_IMAGE = "aistack/ci-runner:13.2.0"

CREW = [
    {"id": "memory-review", "name": "Memory gatekeeper", "unit": "memory-review", "area": "memory",
     "what": "Checks every fact Hermes wants to remember: safe ones are kept, sensitive ones wait for your OK."},
    {"id": "memory", "name": "Memory Keeper", "unit": "crew-memory", "area": "memory", "agent": True,
     "what": "Every night, the Memory Keeper looks after every memory: in the long-term memory it retires duplicates, test noise and facts about agents' runs, puts facts into English and dates passing states (only while its trial passes; each change has an Undo), and asks you when two of your facts disagree; a contradiction on a wiki becomes a dispute that a research task settles with sources; it re-checks stale pages agents still read, folds old journal entries and cleans the search index. On Wednesdays it also tidies every wiki (the Librarian: duplicates merged, contradictions marked, hub pages) and checks the subjects wikis share. Nothing is deleted."},
    {"id": "skills-sync", "name": "Skill keeper", "unit": "skills-sync", "area": "skills",
     "what": "Mirrors Hermes' skills to Forgejo, tags what each one may do, and parks risky learned skills for your OK."},
    {"id": "curator", "name": "Skill curator", "unit": "curate", "area": "skills",
     "what": "Weekly: merges and tidies skills, kept only if the benchmark stays as good (otherwise rolled back)."},
    {"id": "self-review", "name": "Self-review", "thread": "improve", "area": "code",
     "what": "Weekly: failures, errors, open work and new versions become small ideas in the swarm's Ledger (Code → The stack suggests)."},
    {"id": "maintainability", "name": "Maintainability review", "unit": "crew-maintainability", "area": "code", "agent": True,
     "what": "Weekly: Claude Code reads the code (read-only): hot spots, duplication, dead code, docs drift. Ideas only where code really costs; a known one gets new evidence instead of a copy."},
    {"id": "tests", "name": "Test agent", "unit": "crew-tests", "area": "code", "agent": True,
     "what": "Weekly: runs the tests three times for flaky ones, finds slow tests and untested functions. Proposals, no model."},
    {"id": "doctor", "name": "Health doctor", "unit": "crew-doctor", "area": "ops", "agent": True,
     "what": "Every 6 hours and after a new health alert: reviews each open issue with its logs; Claude Code tells expected, noise, external and real faults apart and proposes fixes. Changes nothing."},
    {"id": "phone-cleanup", "name": "Phone cleanup", "unit": "crew-phone-cleanup", "area": "phone", "agent": True,
     "what": "Weekly: turns the AI phone's storage into concrete steps (old files by year, unused apps, caches). Each one runs on the phone only after your Approve; it reports the space freed."},
    {"id": "phone-check", "name": "Phone check", "unit": "crew-phone-check", "area": "phone", "agent": True,
     "what": "Weekly: battery, storage, security patch, connection and the screen-awake loop of the AI phone. Raises an alert only for a real fault."},
    {"id": "inbox", "name": "Inbox digest", "unit": "crew-inbox", "area": "memory", "agent": True,
     "what": "Daily, while you grant Gmail read: files the newsletters and updates worth keeping into your vault (the curator makes wiki pages). Never archives or deletes mail."},
    {"id": "coach", "name": "Coach", "unit": "crew-coach", "area": "ops", "agent": True,
     "what": "Monthly: reads every agent's scorecard and turns a real problem (many declined ideas, duplicates, refused writes) into an agent change with its evidence and a target score. Each change is replayed on the agent's past runs first; you tap Build it only after it passed."},
    {"id": "journeys", "name": "Journey checks", "unit": "crew-journeys", "area": "ops", "agent": True,
     "what": "Nightly, without a model: follows your journeys end to end. A task given in a sentence to its result (on replayed answers), every screen of the app at phone width, the newest briefing's e-mail on a phone, every make target dry-run. A failure is an alert here."},
    {"id": "checker", "name": "Checker", "unit": "crew-checker", "area": "ops", "agent": True,
     "what": "Every hour, without a model: checks whether each shipped idea worked (its health issue stays away, CI is green, a log line is gone) and marks it proved, or reopens it with the evidence. Starts ideas your autonomy rules allow, pauses an agent whose runs keep failing."},
    {"id": "swarm-sync", "name": "Swarm sync", "unit": "swarm-sync", "area": "ops",
     "what": "Every minute: puts the swarm's changes (ideas proposed, refined, decided, shipped) on your timeline and refreshes the ideas list in Code."},
    {"id": "graphify-sync", "name": "Code graph", "unit": "graphify-sync", "area": "code",
     "what": "Rebuilds the code graph of your repositories when they change."},
    {"id": "upgrade-check", "name": "Upgrade check", "unit": "upgrade-check", "area": "ops",
     "what": "Monthly: newer releases of every pinned component, for the self-review."},
    {"id": "backup", "name": "Backup", "unit": "backup", "area": "ops",
     "what": "Nightly: encrypted backup of the stack's data to the NAS; the newest also goes to OneDrive."},
    {"id": "restore-drill", "name": "Restore drill", "unit": "restore-drill", "area": "ops",
     "what": "Weekly: restores the latest backup into a scratch area and checks it is complete."},
    {"id": "digest", "name": "Daily digest", "unit": "digest", "area": "ops",
     "what": "Every morning: what the stack did, what failed, what waits for you (Telegram)."},
    {"id": "token-probe", "name": "Token probe", "unit": "token-probe", "area": "ops", "oneoff": True,
     "what": "One-off: measures whether the ChatGPT prompt cache hits after the token fixes."},
]
BY_ID = {a["id"]: a for a in CREW}
_cache = {"t": 0, "data": []}


# ---------- reading systemd ----------
def sh(*cmd, timeout=60, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    return p.stdout


def parse_show(text):
    """`systemctl show` output for several units (blocks separated by blank lines) -> {Id: {prop: value}}."""
    units, cur = {}, {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur.get("Id"):
                units[cur["Id"]] = cur
            cur = {}
        elif "=" in line:
            k, v = line.split("=", 1)
            cur[k] = v
    return units


def ts(v):
    """A systemd time ('@1730000000', or 'Thu 2026-10-29 03:31:05 CET' which some properties print anyway) -> epoch
    seconds in local time, or None."""
    m = re.match(r"@(\d+)", v or "")
    if m:
        return int(m[1]) if int(m[1]) > 0 else None
    m = re.match(r"\w{3} (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", v or "")
    return int(time.mktime(time.strptime(m[1], "%Y-%m-%d %H:%M:%S"))) if m else None


def seconds_of(text):
    """'10min', '5min', '60s', '1h 30min' -> seconds."""
    mult = {"s": 1, "sec": 1, "min": 60, "m": 60, "h": 3600, "d": 86400}
    return sum(int(n) * mult.get(u, 1) for n, u in re.findall(r"(\d+)\s*([a-z]+)?", text or "")) or None


def schedule_of(unit):
    """Human words for a timer's schedule, from its unit file."""
    f = Path.home() / ".config/systemd/user" / f"{unit}.timer"
    if not f.exists():
        return "on request"
    s = f.read_text()
    drop = DROPIN_DIR(unit) / DROPIN
    if drop.exists():                                    # the owner's schedule from Mission Control wins
        s = re.sub(r"^(OnCalendar|OnUnitInactiveSec|OnUnitActiveSec)=.*$", "", s, flags=re.M) + drop.read_text()
    cal = re.search(r"^OnCalendar=(.+)$", s, re.M)
    every = re.search(r"^OnUnitInactiveSec=(.+)$", s, re.M) or re.search(r"^OnUnitActiveSec=(.+)$", s, re.M)
    if cal:
        return plain_calendar(cal[1].strip())
    return f"every {every[1].strip()}" if every else "on boot"


DROPIN = "mission-control.conf"
DROPIN_DIR = lambda unit: Path.home() / ".config/systemd/user" / f"{unit}.timer.d"     # noqa: E731
EVERY = re.compile(r"^\d{1,4}\s*(s|min|h|d)$")


def set_schedule(unit, kind, value):
    """The owner's schedule for a crew timer as a systemd drop-in: kind calendar (OnCalendar) or every (interval);
    kind reset removes it. Validated before anything is written."""
    d, value = DROPIN_DIR(unit), str(value or "").strip()
    if kind == "reset":
        (d / DROPIN).unlink(missing_ok=True)
    elif kind == "calendar":
        if subprocess.run(["systemd-analyze", "calendar", value], capture_output=True, timeout=20).returncode:
            raise ValueError(f"not a valid time: {value} (e.g. 'Mon *-*-* 04:30' or 'daily')")
        d.mkdir(parents=True, exist_ok=True)
        (d / DROPIN).write_text(f"[Timer]\nOnCalendar=\nOnUnitInactiveSec=\nOnUnitActiveSec=\nOnCalendar={value}\n")
    elif kind == "every":
        if not EVERY.match(value):
            raise ValueError("an interval like 10min, 2h or 1d")
        d.mkdir(parents=True, exist_ok=True)
        (d / DROPIN).write_text(f"[Timer]\nOnCalendar=\nOnUnitInactiveSec=\nOnUnitActiveSec=\nOnUnitInactiveSec={value}\n")
    else:
        raise ValueError("kind: calendar, every or reset")
    sh("systemctl", "--user", "daemon-reload")
    sh("systemctl", "--user", "restart", f"{unit}.timer")


def set_enabled(unit, on):
    p = subprocess.run(["systemctl", "--user", "enable" if on else "disable", "--now", f"{unit}.timer"], capture_output=True, text=True, timeout=30)
    if p.returncode:
        raise ValueError(p.stderr.strip())


DAYS = {"Mon": "Mondays", "Tue": "Tuesdays", "Wed": "Wednesdays", "Thu": "Thursdays", "Fri": "Fridays", "Sat": "Saturdays", "Sun": "Sundays"}


def plain_calendar(cal):
    """systemd OnCalendar -> words: 'Sun *-*-* 04:00:00' -> 'Sundays 04:00', '*-*-* 03:30' -> 'daily 03:30'."""
    m = re.fullmatch(r"(?:(\w{3}) )?(\*|\d{4})-(\*|\d\d)-(\*|\d\d) (\d\d:\d\d)(?::\d\d)?", cal)
    if not m:
        return cal
    day, _, _, dom, hm = m.groups()
    if day in DAYS:
        return f"{DAYS[day]} {hm}"
    return f"monthly on day {int(dom)}, {hm}" if dom != "*" else f"daily {hm}"


def unit_status(a, units):
    svc, tim = units.get(f"{a['unit']}.service", {}), units.get(f"{a['unit']}.timer", {})
    start, end = ts(svc.get("ExecMainStartTimestamp")), ts(svc.get("ExecMainExitTimestamp"))
    trig = ts(tim.get("LastTriggerUSec"))         # survives a restart of WSL (the service's own times do not)
    running = svc.get("ActiveState") in ("activating", "active") and svc.get("SubState") in ("start", "running")
    result = "running" if running else ("ok" if trig else "never") if not start else "ok" if svc.get("Result") == "success" else "failed"
    sched = schedule_of(a["unit"])
    nxt = ts(tim.get("NextElapseUSecRealtime"))
    if not nxt and sched.startswith("every ") and (start or trig):      # interval timers have no calendar time
        nxt = (end or start or trig) + (seconds_of(sched[6:]) or 0)
    return {"state": result, "last": start or trig, "seconds": (end - start) if start and end and end >= start else None,
            "next": nxt, "schedule": sched, "installed": svc.get("LoadState") == "loaded",
            "enabled": tim.get("UnitFileState", "enabled") in ("enabled", "static", "linked") if tim else True,
            "custom": (DROPIN_DIR(a["unit"]) / DROPIN).exists()}


def journal_tail(unit, n=8):
    lines = sh("journalctl", "--user", "-u", f"{unit}.service", "-n", str(n), "-o", "cat", "--no-pager", timeout=20).splitlines()
    return [ln for ln in lines if ln.strip() and "install out of sync" not in ln][-n:]


def agent_file(aid):
    try:
        return json.loads((OUT / f"{aid}.json").read_text())
    except (FileNotFoundError, ValueError):
        return {}


def status():
    """The crew for state.json, refreshed at most once a minute (a dozen systemctl/journalctl calls)."""
    if time.time() - _cache["t"] < 60:
        return _cache["data"]
    names = [f"{a['unit']}.{k}" for a in CREW if a.get("unit") for k in ("service", "timer")]
    units = parse_show(sh("systemctl", "--user", "show", "--timestamp=unix", "-p",
                          "Id,ActiveState,SubState,Result,ExecMainStartTimestamp,ExecMainExitTimestamp,LoadState,NextElapseUSecRealtime,LastTriggerUSec,UnitFileState",
                          *names))
    out = []
    for a in CREW:
        item = {k: a[k] for k in ("id", "name", "what", "area", "unit") if k in a}    # unit: the app names jobs by it (APP-26)
        if a.get("thread") == "improve" and I:
            s = I.last_scan()
            last = dt.datetime.fromisoformat(s["last"]).timestamp() if s.get("last") else None
            item.update(state="waiting" if s.get("retry_at") else "ok" if last else "never", last=last,
                        next=(last + I.EVERY.total_seconds()) if last else None, schedule="weekly", result=s.get("result", ""),
                        installed=True, log=[])
        else:
            item.update(unit_status(a, units))
            if not item["installed"]:
                continue
            item["log"] = journal_tail(a["unit"])
        if a.get("agent"):
            f = agent_file(a["id"])
            if a["id"] == "phone-cleanup":
                try:
                    import phone_agents as PA
                    PA.C, PA.M = sys.modules[__name__], M
                    PA.sync()                                 # the phone's results for approved steps
                    f = agent_file(a["id"])
                except Exception as e:
                    print(f"phone cleanup sync: {type(e).__name__}: {e}", file=sys.stderr)
            item.update(result=f.get("result", item.get("result", "")), findings=f.get("findings", []),
                        suggestions=f.get("suggestions", []), proposals=f.get("proposals", 0))
            for k in ("actions", "freed_total", "free", "total", "summary"):
                if f.get(k) is not None:
                    item[k] = f[k]
            if f.get("seconds"):
                item["seconds"] = f["seconds"]
        hc = _hist.get(a["id"]) or {}
        item.update(runs_7d=hc.get("runs_7d"), success_7d=hc.get("success_7d"), issues=hc.get("issues", []), payoff=hc.get("payoff", ""))
        if a.get("oneoff") and not item.get("next") and item["state"] != "running" and \
                (not item.get("last") or time.time() - item["last"] > 86400):
            continue                               # a one-off that is done (a day ago) leaves the list
        out.append(item)
    _cache.update(t=time.time(), data=out)
    return out


def state():
    return {"crew": status()}


def handle(req, c):
    a = req.get("action")
    if a == "crew_run":
        ag = BY_ID.get(str(req.get("id", "")))
        if not ag:
            raise ValueError("no such crew agent")
        if ag.get("thread") == "improve":
            I.save_scan(requested=M.now().isoformat(timespec="seconds"))
        else:
            p = subprocess.run(["systemctl", "--user", "start", "--no-block", f"{ag['unit']}.service"], capture_output=True, text=True)
            if p.returncode:
                raise ValueError(f"could not start it: {p.stderr.strip()}")
        _cache["t"] = 0
        M.event("crew", "", f"{ag['name']}: started on request", title="Crew")
        return {"started": ag["id"]}
    if a == "crew_schedule":
        ag = BY_ID.get(str(req.get("id", "")))
        if not ag or not ag.get("unit"):
            raise ValueError("this crew agent's schedule is set by the stack")
        if "enabled" in req:
            set_enabled(ag["unit"], bool(req["enabled"]))
        if req.get("kind"):
            set_schedule(ag["unit"], req["kind"], req.get("value"))
        _cache["t"] = 0
        M.event("crew", "", f"{ag['name']}: schedule now {schedule_of(ag['unit'])}" + ("" if req.get("enabled", True) else " (switched off)"), title="Crew")
        return {"schedule": schedule_of(ag["unit"])}
    if a == "crew_memory_forget":
        return forget(req.get("ids") or [], limit(str(req.get("why", "")), 2000, "the reason"))
    if a == "crew_memory_undo":                           # the owner's Undo of one Memory Keeper change (MEM-21)
        import keeper as K
        K.M = M
        r = K.undo(str(req.get("change", "")))
        cur = agent_file("memory")
        if cur.get("keeper"):
            save("memory", keeper={**cur["keeper"], "changes": K.changes(40)[::-1]})
        _cache["t"] = 0
        M.event("memory", "", f"Memory Keeper: undone, as you asked: “{r['fact']}”", title="Crew")
        return r
    if a == "health_ack":
        return acknowledge([str(k)[:200] for k in (req.get("keys") or [])][:100])  # cap: id
    if a in ("phone_cleanup_do", "phone_cleanup_do_all", "phone_cleanup_dismiss"):
        import phone_agents as PA
        PA.C, PA.M = sys.modules[__name__], M
        _cache["t"] = 0
        return PA.handle(req, c)
    raise ValueError("unknown crew action")


# ---------- observability: history, payoff, health (ops/observe.py) ----------
_hist = {}                                           # crew id -> {runs_7d, success_7d, issues, payoff}
RUN = {}                                             # the crew run in progress (its ledger writes show in its run view)
_hist_t = {"t": 0}
_health = {"t": 0, "data": {}}
PROPOSERS = ("maintainability", "tests", "doctor")             # crew agents that make proposals (proposals.source); the rest is self-review


def interval_of(sched):
    """A schedule in words -> seconds between runs (for 'did not run when scheduled')."""
    s = sched or ""
    if s.startswith("every "):
        return seconds_of(s[6:])
    return 86400 if s.startswith("daily") else 30 * 86400 if s.startswith("monthly") else 7 * 86400 if s.split(" ")[0] in DAYS.values() else None


def payoff_of(c, aid):
    """What a crew agent produced: its ideas in the Ledger and their fate (accepted, built, dismissed, open)."""
    if aid not in PROPOSERS and aid != "self-review":
        return {}
    import swarm_client as SW
    return SW.payoff(aid)


def refresh_history(c):
    """Every 5 minutes: each crew job's runs from journald -> crew/<id>.history.json (the detail page) + stats."""
    import observe as O
    if time.time() - _hist_t["t"] < 300:
        return
    _hist_t["t"] = time.time()
    hist = {a["id"]: O.crew_history(a["unit"]) for a in CREW if a.get("unit")}
    sr = payoff_of(c, "self-review")                    # the self-review runs in a thread, not as a unit
    if sr.get("proposals"):
        _hist["self-review"] = {"payoff": f"{sr['proposals']} proposals: {sr['accepted']} accepted, {sr['built']} built, {sr['dismissed']} dismissed"}
    for a in CREW:
        if not a.get("unit"):
            continue
        runs = hist.get(a["id"], [])
        f = agent_file(a["id"]) if a.get("agent") else {}
        if runs and f.get("result", "").startswith("failed") and (runs[0]["state"] != "failed" or not runs[0].get("error")):
            runs[0]["state"], runs[0]["error"] = "failed", f["result"]       # the reason, for the alert's text (FND-65)
        pay = payoff_of(c, a["id"])
        sched = schedule_of(a["unit"])
        j = O.judge(a["name"], "crew", runs, interval=interval_of(sched), enabled=True)
        ok = [r["seconds"] for r in runs if r["state"] == "ok"]
        stats = {"runs": len(runs), "ok": sum(r["state"] == "ok" for r in runs), "failed": sum(r["state"] == "failed" for r in runs),
                 "avg_s": round(sum(ok) / len(ok), 1) if ok else None, "max_s": max(ok) if ok else None}
        words = (f"{pay['proposals']} proposals: {pay['accepted']} accepted, {pay['built']} built, {pay['dismissed']} dismissed"
                 if pay.get("proposals") else f"{stats['ok']} successful run{'' if stats['ok'] == 1 else 's'} in 30 days" if runs else "")
        _hist[a["id"]] = {"runs_7d": j["runs_7d"], "success_7d": j["success_7d"], "issues": j["issues"], "payoff": words}
        OUT.mkdir(parents=True, exist_ok=True)
        tmp = OUT / f".{a['id']}.history.tmp"
        tmp.write_text(json.dumps({"id": a["id"], "runs": runs, "stats": stats, "payoff": pay, "payoff_text": words,
                                   "health": j, "updated": time.time()}, ensure_ascii=False))
        tmp.replace(OUT / f"{a['id']}.history.json")


MISSION_EVERY = {"daily": 86400, "weekdays": 86400 * 3, "weekly": 7 * 86400}


def mission_health(c, m):
    import observe as O
    runs = []
    for r in c.execute("select id, status, started, seconds, tokens, summary from runs where slug=? and status in ('ok','failed') "
                       "order by id desc limit 21", (m["slug"],)).fetchall():  # cap: parse (the last 20 runs give the usual)
        try:
            start = M.dt.datetime.fromisoformat(r["started"]).timestamp()
        except (TypeError, ValueError):
            continue
        warn, probs = [], []
        tl = M.RUNLOGS / f"{r['id']}.timeline.json"
        if not runs and tl.exists():
            try:
                t = json.loads(tl.read_text())
                warn, probs = t.get("warnings", []), t.get("problems", [])
            except ValueError:
                pass
        runs.append({"start": start, "seconds": r["seconds"], "tokens": r["tokens"], "state": r["status"],
                     "error": r["summary"] if r["status"] == "failed" else "", "warnings": warn, "problems": probs})
    sched = (m.get("schedule") or "").split(" ")[0]
    every = MISSION_EVERY.get(sched) or (int(re.findall(r"\d+", m["schedule"])[0]) * 3600 if sched == "every" else None)
    j = O.judge(m["title"], "mission", runs, interval=every, enabled=m.get("status") == "active")
    seen = {i["kind"] for i in j["issues"]}                  # the problems detector feeds the board (last run only)
    for p in (runs[0].get("problems") if runs else []) or []:
        if p["kind"] in ("unknown-tool", "empty-args", "repeat", "partial-read", "no-end") and p["kind"] not in seen:
            seen.add(p["kind"])
            j["issues"].append({"kind": p["kind"], "text": f"last run: {p['text']}"})
    for i in j["issues"]:
        i.setdefault("at", runs[0]["start"] if runs else 0)
    for q in M._queue_cache:
        if q.get("slug") == m["slug"] and q.get("status") == "waiting":
            since = _ts(q.get("started"))
            long = since and time.time() - since > 3600
            j["issues"].append({"kind": "limit-long" if long else "limit", "at": since or 0,
                                "text": "blocked by a usage limit for over an hour" if long else "waiting for a usage limit"})
    st = m.get("stats", {})
    outs = len(m.get("outputs") or [])
    j.update(slug=m["slug"], payoff=f"{outs} reports · {st.get('runs', 0)} runs in 30 days · {st.get('tokens', 0):,} tokens")
    return j


# Health (owner's rules, 28 Oct 2026): one item per agent (missions, crew, the engines); sessions, scout runs and
# reviews count for the agent that started them. Alerts (push + Telegram, once per issue) only for what needs a
# human; everything else is a note on the card and in the run log. A good next run clears an issue; Acknowledge
# hides it until it happens again (health-ack.json, logged in the activity feed).
ALERTS = {"failing", "overdue", "stalled", "limit-long", "drift", "over-limit", "app-error", "drill-old", "memory-low",
          "network-cut", "journey"}
CURATOR_ITEM = {"wiki-curator": "curator"}           # a memory store's curator -> its crew item (the vault lint runs in curate)
ENGINES = {"main": "Hermes (chat)", "mission": "Hermes (missions)", "scout": "Research (scout)", "curator": "Wiki curator",
           "builder": "Builder", "claude-builder": "Builder", "claude-task": "Claude worker", "claude-review": "Claude worker",
           "claude-maintainability": "Claude worker", "ai-phone": "AI phone", "mail": "Gmail", "runner": "Runner"}
ACK = OUT / "health-ack.json"


def _ts(iso):
    try:
        return M.dt.datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError, AttributeError):
        return None


def issue_key(item, i):
    return f"{item['kind']}:{item.get('slug') or item.get('id') or item['name']}:{i['kind']}"


def acks():
    try:
        return json.loads(ACK.read_text())
    except (OSError, ValueError):
        return {}


def acknowledge(keys, by="The owner"):
    """Hide these issues until they happen again (a newer occurrence shows), and log it."""
    cur = {issue_key(it, i): (it, i) for it in (_health["data"] or {}).get("items", []) for i in it.get("issues", []) + it.get("acked", [])}
    a, done = acks(), []
    for k in keys:
        if k in cur:
            it, i = cur[k]
            a[k] = {"at": i.get("at") or time.time(), "acked": time.time(), "by": by}
            done.append(f"{it['name']}: {i['text']}")
    OUT.mkdir(parents=True, exist_ok=True)
    ACK.write_text(json.dumps(a))
    _health["t"] = 0
    if done:
        M.event("health", "", f"Acknowledged {len(done)}: " + "; ".join(done), title="Agent health")
    return {"acknowledged": len(done)}


def _merge_runtime(items):
    """The runtime record's problems, rolled up per owning agent, into the mission, crew or engine item."""
    import runtime as RTM
    by = {("mission:" + it["slug"]) if it["kind"] == "mission" else ("crew:" + it["id"]): it for it in items if it["kind"] in ("mission", "crew")}
    engines = {}
    for p in RTM.problems(48, by="agent"):
        agent = p.get("agent") or ""
        it = by.get(agent)
        if not it and agent.startswith(("mission:", "crew:")):
            continue                                     # an archived mission or a retired crew job: nobody to tell
        if not it:
            name = ENGINES.get(agent, agent or "Agent")
            it = engines.setdefault(name, {"name": name, "kind": "engine", "id": name, "status": "issues", "last": None, "runs_7d": None,
                                           "success_7d": None, "issues": [], "payoff": "", "run": p.get("root")})
        known = {x["kind"] for x in it["issues"]}
        for i in p["issues"]:
            if i["kind"] not in known:
                it["issues"].append({**i, "text": i["text"] if it["kind"] == "engine" or i["kind"] in ("stalled", "drift") else f"a run: {i['text']}"})
                known.add(i["kind"])
    return list(engines.values())


CLIENT_ERRORS = Path("/srv/ai/missions/app/client-errors.jsonl")     # the app's errors, kept by Mission Control (APP-24)


def app_errors(now=None, path=None):
    """APP-24: errors the app hit in the last 24 h as one alert on "Mission Control (the app)" (FND-53: a broken Start
    mission was reported only to a log nobody read). [] when there were none."""
    now = now or time.time()
    try:
        rows = [json.loads(x) for x in (path or CLIENT_ERRORS).read_text().splitlines() if x.strip()]
    except (OSError, ValueError):
        return []
    rows = [r for r in rows if now - float(r.get("ts") or 0) < 86400]
    if not rows:
        return []
    by = {}
    for r in rows:
        by.setdefault(r.get("msg") or "?", []).append(r)
    msg, top = max(by.items(), key=lambda kv: len(kv[1]))
    where = top[-1].get("url") or ""
    text = (f"{len(rows)} error{'s' if len(rows) != 1 else ''} in the app in 24 h; most often “{msg}” ({len(top)}×"
            + (f", on {where}" if where else "") + ")" + (f" and {len(by) - 1} other kind{'s' if len(by) > 2 else ''}" if len(by) > 1 else ""))
    return [{"name": "Mission Control (the app)", "kind": "engine", "id": "app", "status": "issues", "last": top[-1].get("ts"), "runs_7d": None,
             "success_7d": None, "issues": [{"kind": "app-error", "text": text, "at": max(float(r.get("ts") or 0) for r in rows)}], "payoff": ""}]


JOURNEYS = OUT / "journeys.json"                  # the journey checks' last report (ops/journeys.py)


def journey_issues(path=None):
    """TSK-32: the last journey check's failures as one alert on "Journey checks", naming the first ones; [] when they
    all passed (the next good night clears it)."""
    try:
        rep = json.loads((path or JOURNEYS).read_text())
    except (OSError, ValueError):
        return []
    fails = [f"{j['name']}: {f}" for j in rep.get("journeys", []) for f in j.get("failures", [])]
    if not fails:
        return []
    more = f" and {len(fails) - 3} more" if len(fails) > 3 else ""
    return [{"kind": "journey", "at": rep.get("at") or 0,
             "text": f"{len(fails)} journey check{'s' if len(fails) != 1 else ''} failed: " + "; ".join(fails[:3]) + more + " (make journeys shows them all)"}]


def journeys(c):
    """The nightly journey checks (ops/journeys.py), saved like any crew job's result; their failures are the alert."""
    import journeys as JY
    t0 = time.time()
    save("journeys", result="checking…", started=t0)
    rep = JY.run_all()
    save("journeys", result=JY.summary(rep), findings=[{"kind": j["name"], "issue": f} for j in rep["journeys"] for f in j["failures"]],
         seconds=round(time.time() - t0), last=time.time())
    return 0


def health(c, missions):
    """The Agent health board: every active mission, crew agent and engine; new alerts go out once (push + Telegram)."""
    import observe as O
    if time.time() - _health["t"] < 120 and _health["data"]:
        return _health["data"]
    refresh_history(c)
    items = [mission_health(c, m) for m in missions if m.get("status") == "active"]
    for a in status():
        hc = _hist.get(a["id"])
        iss = [{**i, "at": i.get("at") or a.get("last") or 0} for i in (hc or {}).get("issues", [])] if a.get("enabled", True) else []
        if a["id"] == "journeys":
            iss += journey_issues()
        items.append({"name": a["name"], "kind": "crew", "id": a["id"], "status": a.get("state"), "last": a.get("last"),
                      "runs_7d": (hc or {}).get("runs_7d"), "success_7d": (hc or {}).get("success_7d"),
                      "issues": iss, "payoff": (hc or {}).get("payoff", "")})
    try:
        items += _merge_runtime(items)
    except Exception as e:
        M.log(f"health runtime: {type(e).__name__}: {e}")
    memory_alarms(items)
    items += recovery_alarms(items)
    items += app_errors()
    unfinished_notes(items)
    ack = acks()
    for it in items:
        shown, hidden = [], []
        for i in it["issues"]:
            i["severity"] = "alert" if i["kind"] in ALERTS else "note"
            i["key"] = issue_key(it, i)
            a = ack.get(i["key"])
            (hidden if a and (i.get("at") or 0) <= a["at"] else shown).append(i)
        it["issues"], it["acked"] = shown, hidden
    keep = {i["key"] for it in items for i in it["issues"] + it["acked"]}
    if set(ack) - keep:                                   # an issue that is over forgets its acknowledgement
        ACK.write_text(json.dumps({k: v for k, v in ack.items() if k in keep}))
    out = []
    def send(lines):
        text = "\n".join(f"• {html_escape(x)}" for x in lines[:8]) + (f"\n… and {len(lines) - 8} more" if len(lines) > 8 else "")
        N.send(f"⚠️ <b>Agent health</b>\n{text}", "health", buttons=[[("🔍 Open", f"{M.X.APP}/#/missions")]], push_on=True,
               event_kind="health", title="Agent health", is_html=True)
    try:
        O.notify([{**it, "issues": [i for i in it["issues"] if i["severity"] == "alert"]} for it in items], OUT / "health-notified.json", out.append)
        if out:
            send(out)
            call_doctor(out)
    except Exception as e:
        M.log(f"health notify: {e}")
    data = {"items": items, "issues": sum(len(i["issues"]) for i in items), "alerts": sum(i["severity"] == "alert" for it in items for i in it["issues"]),
            "updated": time.time()}
    _health.update(t=time.time(), data=data)
    return data


def memory_alarms(items, inv=None, now=None):
    """MEM-08: a memory store over its limit for a week and a day is an alert on its curator (the Librarian by default)."""
    try:
        import memory as MEM
        for s, text in MEM.alarms(inv if inv is not None else MEM.last(), now):
            cid = CURATOR_ITEM.get(s.get("curator"), s.get("curator")) if s.get("curator") in BY_ID or s.get("curator") in CURATOR_ITEM else "memory"
            it = next((x for x in items if x["kind"] == "crew" and x["id"] == cid), None)
            if it and not any(i["kind"] == "over-limit" and i["text"] == text for i in it["issues"]):
                it["issues"].append({"kind": "over-limit", "text": text, "at": s["over_since"]})
    except Exception as e:
        M.log(f"health memory: {type(e).__name__}: {e}")


BACKUPS = Path("/srv/ai/state/backups.jsonl")
DRILL_DAYS = 8                                        # a weekly drill, a day's grace
_images = {"t": 0, "text": ""}


def image_drift(lock=None, run=None):
    """S1/FND-67: containers that run another build than their image's tag (a recreate would run something untested),
    and running images that versions.lock lacks (PLT-20). -> text, or "" (checked every 10 minutes)."""
    run = run or (lambda *a: subprocess.run(["docker", *a], capture_output=True, text=True, timeout=30).stdout)
    if time.time() - _images["t"] < 600 and lock is None:
        return _images["text"]
    old, missing = [], []
    try:
        locked = (lock if lock is not None else (Path(__file__).resolve().parent.parent / "versions.lock").read_text())
        for line in run("ps", "--filter", "label=com.docker.compose.project=aistack", "--format", "{{.Names}}\t{{.Image}}").splitlines():
            name, image = line.split("\t")
            want = run("inspect", "-f", "{{.Config.Image}}", name).strip()
            has = run("inspect", "-f", "{{.Image}}", name).strip()
            tag = run("image", "inspect", "-f", "{{.Id}}", want).strip()
            short = name.removeprefix("aistack-").removesuffix("-1")
            if tag and has and tag != has:
                old.append(short)
            elif want not in locked:
                missing.append(want)
    except (OSError, ValueError, subprocess.SubprocessError):
        return _images["text"]
    text = "; ".join(x for x in (
        f"{', '.join(old)} run{'s' if len(old) == 1 else ''} another build than {'its' if len(old) == 1 else 'their'} image tag names: recreate after checking that build" if old else "",
        f"versions.lock lacks {len(set(missing))} running image{'s' if len(set(missing)) != 1 else ''} ({', '.join(sorted(set(missing)))}): make lock" if missing else "") if x)
    _images.update(t=time.time(), text=text)
    return text


_cut = {}                                             # container -> when its network was first seen cut (one issue, not one per refresh)


def cut_networks(run=None, now=None):
    """FND-74: a container that shares another's network (network_mode service:x) keeps the old network when x is
    recreated without it, and nothing reaches it any more (the Hermes dashboard's gate, 31 Oct 2026: HTTP 000).
    -> network-cut issues for This PC, [] when every shared network belongs to a running container."""
    run = run or (lambda *a: subprocess.run(["docker", *a], capture_output=True, text=True, timeout=30).stdout)
    now = now or time.time()
    try:
        alive = set(run("ps", "-q", "--no-trunc").split())
        service = dict(ln.split("\t") for ln in run("ps", "--format", '{{.Names}}\t{{.Label "com.docker.compose.service"}}').splitlines()
                       if ln.strip())                 # every running container: ua-viewer-port is not in compose
        mode = dict(ln.lstrip("/").split("\t") for ln in run("inspect", "-f", "{{.Name}}\t{{.HostConfig.NetworkMode}}", *service).splitlines()
                    if ln.strip()) if service else {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    cut = sorted(n for n, m in mode.items() if m.startswith("container:") and m.split(":", 1)[1] not in alive)
    for n in set(_cut) - set(cut):
        del _cut[n]
    return [{"kind": "network-cut", "at": _cut.setdefault(n, now),
             "text": f"{service.get(n) or n} shares the network of a container that no longer runs, so nothing reaches it: "
                     + (f'recreate it (make up UP_SERVICES="--no-deps --force-recreate {service[n]}")' if service.get(n)
                        else "recreate it after the container whose network it shares")} for n in cut]


def recovery_alarms(items, now=None, backups=None, meminfo=None, drift=None, nets=None):
    """FND-66, FND-67, FND-74: an alert on the Restore drill when no drill has passed for 8 days; a note on This PC when
    swap is over 90 % full (an alert when RAM is short too, CST-14) and when the running images drifted from their tags
    or the lock file; an alert on This PC when a container is cut off from the network it shares (PLT-23).
    -> new engine items (This PC); the drill's issue goes onto its crew item."""
    now = now or time.time()
    try:
        rows = [json.loads(x) for x in (backups or BACKUPS).read_text().splitlines() if x.strip()]
    except (OSError, ValueError):
        rows = []
    drills = [r for r in rows if r.get("kind") == "restore-drill" and r.get("result") == "ok"]
    newest = max((r for r in rows if r.get("kind") == "backup"), key=lambda r: r.get("ts", 0), default=None)
    last = max((r.get("ts", 0) for r in drills), default=0)
    it = next((x for x in items if x.get("kind") == "crew" and x.get("id") == "restore-drill"), None)
    if it is not None and rows and now - last > DRILL_DAYS * 86400:
        days = round((now - last) / 86400) if last else None
        it["issues"].append({"kind": "drill-old", "at": now, "text": (f"no restore drill has passed for {days} days" if days else "no restore drill has passed yet")
                             + (f"; the newest backup ({newest.get('size', '?')}, {time.strftime('%d %b', time.localtime(newest['ts']))}) is unproven" if newest else "")
                             + ": make restore-drill"})
    pc = []
    try:
        mi = {ln.split(":")[0]: int(ln.split()[1]) for ln in (meminfo if meminfo is not None else open("/proc/meminfo").read()).splitlines()
              if ln.split(":")[0] in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")}
        if mi.get("SwapTotal") and (mi["SwapTotal"] - mi["SwapFree"]) / mi["SwapTotal"] > 0.9:
            low = mi["MemAvailable"] / mi["MemTotal"] < 0.1
            pc.append({"kind": "memory-low" if low else "swap-full", "at": now,
                       "text": f"swap is {round(100 * (mi['SwapTotal'] - mi['SwapFree']) / mi['SwapTotal'])} % full and {mi['MemAvailable'] / 1048576:.1f} GB of RAM is free"
                       + (": close a Claude session or stop a build" if low else ": memory runs at its limit (CST-14)")})
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        pass
    d = image_drift() if drift is None else drift
    if d:
        pc.append({"kind": "image-drift", "at": now, "text": d})
    pc += cut_networks() if nets is None else nets
    return [{"name": "This PC", "kind": "engine", "id": "pc", "status": "issues", "last": None, "runs_7d": None,
             "success_7d": None, "issues": pc, "payoff": ""}] if pc else []


def unfinished_notes(items, report=None):
    """SWM-64: a swarm run that started and never finished (killed, crashed outside its handler, a Hermes wake that
    never called swarm_finish) is a note on its agent's card (crew item, else an engine item)."""
    try:
        runs = json.loads((report or M.PUBLIC / "swarm.json").read_text()).get("unfinished") or []
    except (OSError, ValueError, AttributeError):
        return items
    by = {it["id"]: it for it in items if it.get("kind") == "crew"}
    for u in runs:
        it = by.get(u["agent"])
        if not it:
            name = ENGINES.get(u["agent"], u["agent"])
            it = next((x for x in items if x.get("kind") == "engine" and x.get("name") == name), None)
            if not it:
                it = {"name": name, "kind": "engine", "id": name, "status": "issues", "last": None, "runs_7d": None, "success_7d": None,
                      "issues": [], "payoff": ""}
                items.append(it)
        if not any(i["kind"] == "no-finish" for i in it["issues"]):
            it["issues"].append({"kind": "no-finish", "at": u["started"],
                                 "text": f"a run started {time.strftime('%d %b %H:%M', time.localtime(u['started']))} never finished ({u['run']})"})
    return items


DOCTOR_EVERY = 30 * 60


def call_doctor(lines, now=None):
    """A new health alert: the Health doctor looks at it soon (at most once per 30 minutes, never for its own issues,
    not when the owner switched it off)."""
    now = now or time.time()
    lines = [x for x in lines if not x.startswith(BY_ID["doctor"]["name"] + ":")]
    f = OUT / "doctor-trigger.json"
    try:
        last = json.loads(f.read_text()).get("t", 0)
    except (OSError, ValueError):
        last = 0
    if not lines or now - last < DOCTOR_EVERY:
        return False
    if sh("systemctl", "--user", "is-enabled", "crew-doctor.timer", timeout=20).strip() not in ("enabled", "static", "linked"):
        return False
    f.write_text(json.dumps({"t": now, "why": lines[:5]}))
    subprocess.run(["systemctl", "--user", "start", "--no-block", "crew-doctor.service"], capture_output=True, timeout=30)
    M.event("crew", "", f"Health doctor: looking at {len(lines)} new issue{'s' if len(lines) != 1 else ''}", title="Crew")
    return True


def html_escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------- shared bits of the agents ----------
def save(aid, **kw):
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{aid}.json"
    cur = agent_file(aid)
    cur.update(kw)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, ensure_ascii=False))
    tmp.replace(f)


def propose(c, proposals, signal, source=None):
    """A crew agent's ideas go to the swarm's Ledger (ops/swarm_client.propose): by identity key, a near-copy becomes
    evidence on the idea it matches, no caps (DEC-10). Returns how many were new."""
    import swarm_client as SW
    RUN["signal"] = tail(RUN.get("signal", "") + "\n" + str(signal or ""), 8000)     # the run's replay input (SWM-82)  # cap: prompt
    new, _ = SW.propose(source or "self-review", proposals, signal, run=RUN.get("id") or "")
    return new


def json_in(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m[0]) if m else {}


# ---------- maintainability review (Claude Code, read-only) ----------
MAINT_PROMPT = P.text("maintainability", "REVIEW")


def churn(days=30, top=12):
    """Files of ai-stack by commits in the last `days`: [(commits, path)], most first."""
    out = subprocess.run(["git", "-C", str(STACK), "log", f"--since={days}.days", "--format=", "--name-only"],
                         capture_output=True, text=True, timeout=60).stdout
    n = {}
    for f in (x.strip() for x in out.splitlines()):
        if f and not f.startswith(("docs/", "tests/")):
            n[f] = n.get(f, 0) + 1
    return sorted(((v, f) for f, v in n.items()), reverse=True)[:top]


def maint_context(c):
    hot = "\n".join(f"- {f}: {v} commits" for v, f in churn()) or "- (none)"
    import swarm_client as SW
    old = "\n".join(f"- {t}" for t in SW.open_titles()) or "- (none)"
    lessons = SW.lessons_text("maintainability")
    return (f"\n\nFiles changed most in the last 30 days:\n{hot}\n\nAlready proposed and still open (do not repeat or reword these):\n{old}"
            + (f"\n\n{lessons}" if lessons else ""))


def maintainability(c):
    t0 = time.time()
    save("maintainability", result="reviewing…", started=t0)
    subprocess.run(["git", "-C", "/srv/ai/workbench/ai-stack", "fetch", "-q", "origin"], capture_output=True, timeout=120)
    prep = subprocess.run(["docker", "exec", "-u", "hermes", BUILDER, "sh", "-c",
                           "rm -rf /tmp/crew-review && mkdir -p /tmp/crew-review && git -C /work/ai-stack archive origin/main | tar -x -C /tmp/crew-review"],
                          capture_output=True, text=True, timeout=300)
    if prep.returncode:
        raise RuntimeError(f"could not copy main into the sandbox: {tail(prep.stderr.strip(), 4000)}")  # cap: store
    import runtime as RTM
    P.record(MAINT_PROMPT)                                # MEM-11: the run records the prompt's version
    p = subprocess.run(["docker", "exec", "-u", "hermes", "-e", "CLAUDE_CODE_OAUTH_TOKEN", "-w", "/tmp/crew-review", *RTM.env_args(),
                        "-e", "AISTACK_AGENT=claude-maintainability", "-e", "AISTACK_TITLE=Maintainability review", BUILDER,
                        "timeout", "1500", "claude", "-p", J.take(MAINT_PROMPT + maint_context(c), tools=False), "--output-format", "json", "--max-turns", "60",
                        "--allowedTools", "Read,Grep,Glob", "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
                        "--settings", "/config/claude-hooks/claude-runtime-settings.json"],
                       capture_output=True, text=True, timeout=1600, env={**os.environ})
    out = json.loads(p.stdout).get("result", "") if p.stdout.strip().startswith("{") else p.stdout
    if re.search(r"usage limit|hit your limit", out or "", re.I):
        raise RuntimeError("Claude usage limit: try again later")
    d = json_in(out)
    if not d:
        raise RuntimeError(f"no review came back: {tail(out or p.stderr, 4000)}")  # cap: store
    findings = [f for f in d.get("findings", []) if isinstance(f, dict)][:12]
    new = propose(c, d.get("proposals") or [], "maintainability review", "maintainability")
    save("maintainability", result=f"{len(findings)} findings, {new} new proposal{'s' if new != 1 else ''}", findings=findings,
         proposals=new, seconds=round(time.time() - t0), last=time.time())
    return new


# ---------- test agent (no model) ----------
TEST_SCRIPT = r"""
set -e
mkdir /tmp/w && cd /tmp/w && tar x
python -m venv /tmp/v && /tmp/v/bin/pip install -q --disable-pip-version-check -r tests/requirements.txt
for i in 1 2 3; do
  echo "=== RUN $i"
  /tmp/v/bin/pytest -q -p no:cacheprovider -rf --durations=12 tests 2>&1 | tail -60 || true
done
"""


def untested(root, corpus):
    """Top-level functions in ops/*.py whose name no test mentions, largest first: [(file, name, lines)]."""
    out = []
    for f in sorted((root / "ops").glob("*.py")):
        src = f.read_text(errors="replace").splitlines()
        defs = [(i, m[1]) for i, ln in enumerate(src) if (m := re.match(r"def ([a-zA-Z_]\w*)\(", ln))]
        for k, (i, name) in enumerate(defs):
            end = defs[k + 1][0] if k + 1 < len(defs) else len(src)
            if name.startswith("_") or name in ("main", "worker") or re.search(rf"\b{re.escape(name)}\b", corpus):
                continue
            out.append((f"ops/{f.name}", name, end - i))
    return sorted(out, key=lambda x: -x[2])


def parse_runs(text):
    """Three pytest runs -> (failures per run, slow tests [(seconds, test)], summary lines)."""
    runs = text.split("=== RUN ")[1:]
    fails = [set(re.findall(r"^FAILED (\S+)", r, re.M)) for r in runs]
    worst = {}
    for sec, t in re.findall(r"^(\d+\.\d+)s call\s+(\S+)", text, re.M):
        worst[t] = max(worst.get(t, 0.0), float(sec))
    slow = sorted(((v, t) for t, v in worst.items()), reverse=True)          # each test once, its slowest run
    summary = [m for r in runs for m in re.findall(r"^\d+ (?:passed|failed).*$", r, re.M)]
    return fails, slow, summary


def tests(c):
    t0 = time.time()
    save("tests", result="testing…", started=t0)
    tar = subprocess.run(["git", "-C", str(STACK), "archive", "HEAD"], capture_output=True, timeout=120).stdout
    p = subprocess.run(["docker", "run", "--rm", "-i", "--entrypoint", "sh", CI_IMAGE, "-c", TEST_SCRIPT],      # like `make check`
                       input=tar, capture_output=True, timeout=3600)
    text = p.stdout.decode(errors="replace") + p.stderr.decode(errors="replace")
    if "=== RUN" not in text:
        raise RuntimeError(f"the test container did not run: {tail(text, 4000)}")  # cap: store
    fails, slow, summary = parse_runs(text)
    always = set.intersection(*fails) if fails else set()
    flaky = sorted(set.union(*fails) - always) if fails else []
    corpus = "\n".join(f.read_text(errors="replace") for f in (STACK / "tests").glob("*.py"))
    gaps = untested(STACK, corpus)
    findings = ([{"kind": "flaky", "issue": t} for t in flaky] + [{"kind": "failing", "issue": t} for t in sorted(always)]
                + [{"kind": "slow", "issue": f"{t} takes {s:.1f} s"} for s, t in slow[:3] if s >= 2]
                + [{"kind": "untested", "file": f, "issue": f"{n}() ({ln} lines) has no test that mentions it"} for f, n, ln in gaps[:8]])
    props = [{"title": f"Make the flaky test {t.split('::')[-1]} reliable", "why": "A test that sometimes fails hides real failures.",
              "signal": f"failed in some of 3 runs: {t}", "area": "other", "covers": [f"flaky:{t}"],
              "description": f"The test {t} failed in some but not all of three identical runs of the suite. Find the cause "
                             "(timing, ordering, shared state, real time or network) and make it deterministic. Run it 20 times to verify."}
             for t in flaky[:2]]
    by_file, hot = {}, {f for _, f in churn(30, 40)}
    for f, n, ln in gaps:
        if f in hot and ln >= 25:                 # untested and changed lately: where a missing test costs (not "never mentioned")
            by_file.setdefault(f, []).append((n, ln))
    for f, fs in sorted(by_file.items(), key=lambda kv: -sum(x[1] for x in kv[1]))[:1]:
        names = ", ".join(f"{n}()" for n, _ in fs[:5])
        props.append({"title": f"Add tests for {f.split('/')[-1]}: {fs[0][0]} and more"[:100],  # cap: id
                      "why": "These functions changed lately and no test covers them, so a regression would go unnoticed.", "signal": f"untested in {f}: {names}",
                      "area": "other", "covers": [f"untested:{f}"], "description": f"In {f}, these top-level functions are not mentioned by any test in tests/: {names}. "
                      "Add focused unit tests (with fakes, like the existing tests in tests/; no network, Docker or real services) for "
                      "their main paths and one edge case each. Keep production code unchanged unless a test finds a real bug."})
    new = propose(c, props, "test agent", "tests")
    res = (f"3 runs: {'; '.join(summary[-3:]) or 'no result'} · {len(flaky)} flaky, {len(always)} failing, "
           f"{len(gaps)} untested functions · {new} new proposal{'s' if new != 1 else ''}")
    save("tests", result=res, findings=findings, proposals=new, seconds=round(time.time() - t0), last=time.time())
    return new


# ---------- the Memory Keeper ----------
def memory(c):
    """The Memory Keeper's night (ops/keeper.py, MEM-21): long-term memory, the wikis' disputes and re-checks, the agents'
    journals, the search index; on Wednesdays its judgement parts and the Librarian's tidy of every wiki."""
    import keeper as K
    import librarian as LIB                               # MEM-08: every wiki and the search index
    K.M, LIB.M = M, M
    t0 = time.time()
    save("memory", result="reading the memory…", started=t0)
    try:
        rep = K.run_pass(c)
        res = K.summary(rep)
    except Exception as e:
        rep, res = {"suggestions": [], "changed": [], "gate": {"open": False, "why": "the pass failed"}}, f"the pass failed: {type(e).__name__}: {e}"
    tidied = J.curate()                                   # the agents' journals: old entries fold into standing notes
    lib = ""
    if rep.get("deep"):
        save("memory", result="tidying the wikis…")
        try:
            lib = LIB.summary(LIB.run())
        except Exception as e:
            lib = f"the wiki tidy failed: {type(e).__name__}: {e}"
    else:
        import memory as MEM
        try:
            if (MEM.measure("qmd", time.time()).get("orphaned_share") or 0) > MEM.ORPHAN_SHARE:
                ix = LIB.clean_index()
                lib = f"search index: {ix['before']['orphaned']} → {ix['after']['orphaned']} orphaned chunks"
        except Exception as e:
            lib = f"the search index cleanup failed: {type(e).__name__}: {e}"
    sug = rep.get("suggestions") or []
    if not rep.get("deep"):                               # a night without judgement keeps the last judgement's list
        have = {x["id"] for x in sug} | {e["target"] for e in K.changes() if not e.get("undone")}
        sug += [s for s in agent_file("memory").get("suggestions") or [] if s["id"] not in have]
    result = res + (f", {tidied} agent journal{'s' if tidied != 1 else ''} tidied" if tidied else "") + (f" · {lib}" if lib else "")
    save("memory", result=result, suggestions=sug[:60], more=max(0, len(sug) - 60), findings=[],  # cap: list
         keeper={"gate": rep.get("gate"), "changes": K.changes(40)[::-1], "changes_total": len(K.changes()),
                 "disputes": rep.get("disputes"), "rechecks": rep.get("rechecks"), "cross": rep.get("cross")},
         seconds=round(time.time() - t0), last=time.time())
    if rep.get("changed") or (rep.get("disputes") or {}).get("tasks"):
        M.event("memory", "", f"Memory Keeper: {res} (its page under Agents lists each change with its Undo)", title="Crew")
    return len(sug)


def forget(ids, why=""):
    """The owner's tap: soft-retire these facts in Hindsight (state 'invalidated': out of recall, kept for audit, reversible)."""
    ids = TC.limit_items([i for i in ids if re.fullmatch(r"[0-9a-f-]{8,64}", str(i))], 50, "facts to forget at once")   # the owner's tap: refused, never cut
    if not ids:
        raise ValueError("no facts given")
    code = ("import json,sys,urllib.request as u\n"
            "ok=0\n"
            "for i in json.loads(sys.argv[1]):\n"
            "  r=u.Request('http://hindsight:8888/v1/default/banks/owner/memories/'+i, method='PATCH', data=json.dumps("
            "{'state':'invalidated','reason':sys.argv[2]}).encode(), headers={'Content-Type':'application/json'})\n"
            "  try:\n    u.urlopen(r,timeout=60); ok+=1\n  except Exception as e:\n    print('fail',i,e,file=sys.stderr)\n"
            "print(ok)")
    p = subprocess.run(["docker", "exec", HERMES, "/opt/hermes/.venv/bin/python", "-c", code, json.dumps(ids),
                        why or "forgotten by the owner (memory curator)"], capture_output=True, text=True, timeout=300)
    done = int(p.stdout.strip() or 0) if p.returncode == 0 else 0
    cur = agent_file("memory")
    save("memory", suggestions=[s for s in cur.get("suggestions", []) if s["id"] not in ids])
    _cache["t"] = 0
    M.event("memory", "", f"Librarian: {done} fact{'s' if done != 1 else ''} forgotten (reversible)", title="Crew")
    return {"forgotten": done}


def _journal(name, rid, state, summary, seconds):
    try:
        J.record(f"crew:{name}", BY_ID[name]["name"], rid, state, summary, seconds)
    except Exception as e:
        print(f"journal: {type(e).__name__}: {e}", file=sys.stderr)


def run(name):
    """Entry point of the crew-*.service units."""
    global M, I
    sys.path.insert(0, str(Path(__file__).parent))
    import missions
    import improve
    M, I = missions, improve
    I.M = J.M = M
    import runtime as RTM
    import doctor as D
    import inbox as INB
    import phone_agents as PA
    D.C, D.M = sys.modules[__name__], M
    PA.C, PA.M = INB.C, INB.M = sys.modules[__name__], M
    import checker as CK
    CK.M = M
    import coach as COACH
    fn = {"maintainability": maintainability, "tests": tests, "memory": memory, "doctor": D.doctor,
          "phone-cleanup": PA.cleanup, "phone-check": PA.check, "inbox": INB.digest, "checker": CK.run, "coach": COACH.run, "journeys": journeys}[name]
    import registry as REG
    import swarm_client as SW
    if SW.paused(name):                                   # SWM-26: the owner paused this agent (or all) in the app
        save(name, result="skipped: paused by the owner", last=time.time())
        print(f"{name}: paused by the owner, not run", flush=True)
        return
    c = M.db()
    rid, t0 = f"crew:{name}:{time.strftime('%Y%m%d-%H%M%S')}", time.time()
    RTM.set_ref(rid, f"crew:{name}")                      # a Claude review inside reports under this run
    RTM.start(rid, f"crew:{name}", f"Crew · {BY_ID[name]['name']}", data={"manifest": {"agent": f"crew:{name}", "card": REG.hash_of(name), "prompts": P.version(name)}})
    RUN["id"], RUN["signal"] = rid, ""
    SW.run_start(name, rid)                              # SWM-64: a run that never finishes shows on the health board
    J.begin(f"crew:{name}", BY_ID[name]["name"], run=rid, tools=False)        # its journal goes in front of its model prompt
    try:
        n = fn(c)
        res = agent_file(name).get("result", "")
        try:
            k = answer_requests(name, rid)                # the requests that woke it get its model's answers (SWM-13)
            res += f" · answered {k} request{'s' if k != 1 else ''}" if k else ""
        except Exception as e:
            print(f"answers: {type(e).__name__}: {e}", file=sys.stderr)
        M.event("crew", "", f"{BY_ID[name]['name']}: {res}", push=bool(n), title="Crew")
        RTM.emit(rid, "say", agent=f"crew:{name}", title="Result", detail=str(res))
        J.end()
        _journal(name, rid, "done", str(res), time.time() - t0)
        RTM.end(rid, f"crew:{name}", "done", str(res), time.time() - t0)
        SW.run_finish(name, rid, str(res), signal=RUN.get("signal"))
    except Exception as e:
        J.end()
        _journal(name, rid, "limit" if "limit" in str(e).lower() else "failed", f"{type(e).__name__}: {str(e)}", time.time() - t0)
        save(name, result=f"failed: {type(e).__name__}: {str(e)}", last=time.time())
        RTM.end(rid, f"crew:{name}", "limit" if "limit" in str(e).lower() else "failed", f"{type(e).__name__}: {str(e)}", time.time() - t0)
        SW.run_finish(name, rid, f"failed: {type(e).__name__}: {str(e)}")
        raise


ANSWER_PROMPT = P.text("shared", "ANSWER")


def answer_requests(name, run, ask=None, send=None):
    """A woken host agent with a model answers the requests addressed to it (the Board's request-to-answer loop for
    agents that are not Hermes profiles). Claude Code agents read the repo read-only in the sandbox. -> answers sent."""
    import swarm_client as SW
    import registry as REG
    card = next((x for x in REG.load().get("agents") or [] if x["id"] == name), {})
    if card.get("model") in (None, "none") or card.get("wake") == "never":
        return 0
    send = send or SW.call
    r = send("inbox", {"mark": False}, name)
    reqs = [m for m in ((r.get("result") or {}).get("open_requests") or []) if r.get("ok")
            and name in json.loads(m.get("recipients") or "[]") and m.get("sender") != name][:8]
    if not reqs:
        return 0
    rows = []
    for m in reqs:
        art = ""
        if m.get("artifact_id"):
            a = send("get", {"id": m["artifact_id"]}, name).get("result") or {}
            art = f"\n  about {a.get('kind')} #{a.get('id')} \"{a.get('title')}\" ({a.get('state')}, owner {a.get('owner')}): {TC.cut((a.get('body') or ''), 600)}"  # cap: prompt
        rows.append(f"- [{m['mid']}] from {m['sender']}: {TC.cut(m['text'], 1500)}{art}")  # cap: prompt
    prompt = ANSWER_PROMPT.format(agent=name, purpose=card.get("purpose", ""), resp="; ".join(card.get("responsibilities") or []),
                                  requests="\n".join(rows))
    P.record(prompt)                                  # MEM-11: the run records the prompt's version
    out = (ask or _ask_claude)(prompt, name)
    d = json_in(out)
    return SW.reply_all(name, d.get("replies") or [], run=run, send=send)


def _ask_claude(prompt, name):
    import runtime as RTM
    p = subprocess.run(["docker", "exec", "-u", "hermes", "-e", "CLAUDE_CODE_OAUTH_TOKEN", "-w", "/work/ai-stack", *RTM.env_args(),
                        "-e", f"AISTACK_AGENT=claude-{name}", "-e", f"AISTACK_TITLE={name}: answers on the Board", BUILDER,
                        "timeout", "600", "claude", "-p", prompt, "--output-format", "json", "--max-turns", "20",
                        "--allowedTools", "Read,Grep,Glob", "--disallowedTools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch",
                        "--settings", "/config/claude-hooks/claude-runtime-settings.json"],
                       capture_output=True, text=True, timeout=660, env={**os.environ})
    out = json.loads(p.stdout).get("result", "") if p.stdout.strip().startswith("{") else p.stdout
    if re.search(r"usage limit|hit your limit", out or "", re.I):
        raise RuntimeError("Claude usage limit: the answers wait for the next run")
    return out


if __name__ == "__main__":
    run(sys.argv[1])
