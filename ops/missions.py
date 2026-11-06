"""Mission Control runner (host side): the one place that starts mission runs.

Missions are files in the vault, missions/<slug>/MISSION.md (YAML front matter + goal text):
  type      briefing (Topic Desk, topics/<slug>/TOPIC.md) | task (a long-term agent mission, Hermes profile "mission")
  status    active | paused | archived
  schedule  daily HH:MM | weekdays HH:MM | weekly mon,thu HH:MM | every Nh | manual (on demand only)
  triggers  events that start a run: sec_filing (tickers), price_move (symbol, pct), news (query)  [mission_extras]
  depth     standard | deep (tasks: plan -> research steps -> synthesis)
  deliver [telegram, app, email]. Subscription only: when ChatGPT pauses the stack, a run waits and retries.
Requests arrive as JSON files in /srv/ai/missions/inbox (from the Mission Control app and its MCP tools, which
Hermes uses in chat); every request is validated here. Runs go one at a time, so a run's model calls are exactly
the calls of its key (vk-desk / vk-mission) between start and end: that gives calls, tokens and paid spend per run.
Every result also updates the mission's LLM wiki. Every few seconds the runner writes public/state.json (missions,
runs, live activity, system) and appends events to public/events.jsonl (the app shows them and sends pushes).
Run: missions.service (sops exec-env: VK_DESK, VK_MISSION, SEC_CONTACT, TELEGRAM_*, optional GMAIL_*/MAIL_TO).
  python3 ops/missions.py [--once]
"""
import datetime as dt, html, json, os, re, signal, sqlite3, subprocess, sys, threading, time, traceback, unicodedata
import urllib.request
from email.utils import parsedate_to_datetime
from pathlib import Path

import yaml

import mission_extras as X
import runtime as RTM
import builds as B
import claude_tasks as CT
import telemetry as T
import improve as I
import repos as R
import shopping as SH
import cleanup as CL
import crew as CR
import journal as J
import wikis as W
import house as H
import swarm_client as SW
import memory as MEM
import registry as REG
import notify as N                                # OBS-16: the one notification path
import tasks as TK                                # TSK-01 to TSK-04: every piece of work is a task
import conductor as CD                            # TSK-05 to TSK-09: a task's plan graph, step by step
import events as EV                               # TSK-10 to TSK-12: the event bus, the owner's rules, breaking news
import staffing as ST                             # TSK-13 to TSK-17: judged tasks, measured agents, routing, temporary agents
import provenance as PV                           # TSK-23, TSK-24: what each step used and made, each run's swarm map
import history as HI                              # TSK-25: the daily telemetry history per agent, model, harness, kind
import prune as PN                                 # PLT-21: growing files pruned once a day
import prices as PR                               # TSK-27: tokens at list price
import a2a as A2                                  # TSK-19: outside agents over A2A, off until the owner switches it on
from textcap import limit, limit_items, tail as tailcut                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import windows_desk as WD                         # PLT-31: asking Windows, through a folder it fetches from
import onboard as O                        # onboarding a repository: the whole package (BLD-26)
import files as FL                                # MIS-23: the files a mission was asked to make (docs/DELIVERABLES.md)
import decisions as DQ                            # AUT-05: everything that waits for the owner, one ranked list, and its shadow
import stack_gate as G                            # PLT-28: is the stack up; nothing starts against one that is not

OPS = Path(__file__).resolve().parent
VAULT = Path("/srv/vault")
MISSIONS = VAULT / "missions"
HOME = Path("/srv/ai/missions")
INBOX, PUBLIC, RUNLOGS = HOME / "inbox", HOME / "public", HOME / "runs"
DB = HOME / "missions.sqlite"
HERMES = "aistack-hermes-1"
LITELLM = "http://127.0.0.1:4000/v1/chat/completions"
KEY_OF = {"briefing": "vk-desk", "task": "vk-mission", "shopping": "vk-mission",   # shopping: ops/shopping.py
          "cleanup": "vk-mission"}                                                    # cleanup: ops/cleanup.py (phone or PC)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# limit: stops, one mission run past this counts as failed
TASK_TIMEOUT = 40 * 60
RETRY_MIN, MAX_WAITS = 30, 16           # subscription only: a paused run retries every 30 min, for up to 8 hours
DOWN_RETRY_MIN = 5                      # a run the stack went away under (PLT-28): it holds the queue until the stack is back
STACK_GONE = re.compile(r"Cannot connect to the Docker daemon|Container \S+ is (?:paused|restarting|not running)|No such container", re.I)
PAUSED = re.compile(r"\b429\b|rate.?limit|usage.?limit|too many requests|quota|no deployments available|cooldown", re.I)


def paused(text):
    """True when a run failed because ChatGPT paused the stack (usage limit), not because of a real error."""
    return bool(PAUSED.search(text or ""))
os.environ.setdefault("DOCKER_HOST", "unix:///run/user/1000/docker.sock")

lock = threading.Lock()
running = {}          # the run holding the run slot: id, slug, title, started, log
# One run does model work at a time (the ChatGPT quota); a run that waits for something slow without model work (the
# Windows disk scan, ...) parks itself with park() and hands the slot to the next mission meanwhile.
slot = threading.Semaphore(1)
active = {}           # run id -> its thread (holding the slot or parked)
parked = {}           # run id -> what it waits for, while parked
_run_local = threading.local()
stop = threading.Event()


def now():
    return dt.datetime.now().astimezone()


def log(*a):
    print(f"{now():%F %T}", *a, flush=True)


def sh(*cmd, timeout=60, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw).stdout
    except Exception as e:
        log("command failed:", cmd[:3], e)
        return ""


def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("""create table if not exists runs (id integer primary key, slug text, trigger text, due text,
                 status text, started text, ended text, seconds real, calls integer, tokens integer, spend real,
                 models text, summary text, output text, log text)""")
    cols = {r[1] for r in c.execute("pragma table_info(runs)")}
    for col in ("event", "steps", "mode", "retry_at", "attempts"):
        if col not in cols:
            c.execute(f"alter table runs add column {col} text")
    c.execute("create table if not exists seen_events (key text primary key, ts text)")
    return c


EVENTS_LOCK = threading.Lock()                     # the event log's writer and its daily pruning (ops/prune.py)
EVENT_DAYS, EVENTS = 3, 200                        # Home's feed: three days of events, at most 200 (the newest 80 lost a morning's alerts by evening, APP-37)


def event(kind, slug="", text="", push=False, title="", category=None, by=""):
    if push:                                       # OBS-16: a push only where the owner's preferences and quiet hours allow it
        push = N.push_allowed(kind, text, title, category, by=by or ("mission" if slug else ""))
    e = {"ts": now().isoformat(timespec="seconds"), "kind": kind, "slug": slug, "title": title, "text": text, "push": push}
    with EVENTS_LOCK, open(PUBLIC / "events.jsonl", "a") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    log(f"event {kind} {slug}: {text}")


def notify(text, category="system"):
    N.send(text, category, by="stack")


# ---------- missions on disk ----------
def split_front(text):
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return {}, text.strip()
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2).strip()
    except yaml.YAMLError:  # broken front matter: treat the page as plain text, never fail the caller
        return {}, text.strip()


def write_front(path, meta, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=110) + "---\n\n" + body.strip() + "\n")
    tmp.replace(path)


def load_missions():
    out = {}
    for p in sorted(MISSIONS.glob("*/MISSION.md")):
        try:
            meta, body = split_front(p.read_text())
            meta["slug"], meta["goal"] = p.parent.name, body
            out[p.parent.name] = meta
        except Exception as e:
            log(f"bad mission file {p}: {e}")
    return out


def save_mission(m):
    meta = {k: m[k] for k in ("title", "type", "status", "schedule", "triggers", "depth", "once", "budget_usd_month", "deliver",
                              "topic", "created", "target", "watch_pct", "best_price_eur", "best_price_at",      # these three: shopping
                              "task",                                         # TSK-21: the task that runs this agent
                              "files_asked")                                  # MIS-23: the files the owner asked it to make
            if m.get(k) not in (None, [], "", False)}
    write_front(MISSIONS / m["slug"] / "MISSION.md", meta, m.get("goal", ""))


def topic_of(m):
    p = VAULT / "topics" / m.get("topic", m["slug"]) / "TOPIC.md"
    return (split_front(p.read_text()), p) if p.exists() else (({}, ""), p)


_mail_seen = {}                     # a handed mail's facts by (path, mtime): the state is written every few seconds


def topic_mail(tdir):
    """MIS-28: the mails the Inbox digest handed to a topic, newest first, and what came of each -> (40 newest, how many)."""
    files = sorted((tdir / "mail").glob("*.md"), key=lambda p: p.name, reverse=True)
    out = []
    for p in files[:40]:                  # cap: list (the count goes with it; the vault has all)
        k = (str(p), p.stat().st_mtime)
        if k not in _mail_seen:
            meta, _ = split_front(p.read_text(errors="replace"))
            try:
                at = parsedate_to_datetime(str(meta.get("date"))).isoformat()
            except (TypeError, ValueError):
                at = ""
            _mail_seen[k] = {"path": str(p.relative_to(VAULT)), "subject": meta.get("subject") or p.stem, "from": meta.get("from") or "",
                             "at": at, "why": meta.get("why") or "", "report": meta.get("report") or "", "cited": bool(meta.get("cited"))}
        out.append(_mail_seen[k])
    return out, len(files)


def read_notes(m):
    """A mission's working state: in its journal (MEM-05); an old NOTES.md until its next run moves it there."""
    st = J.state_text(f"mission:{m['slug']}")
    p = MISSIONS / m["slug"] / "NOTES.md"
    return st or (p.read_text() if p.exists() else "(none yet: this is the first run)")


def private_wikis():
    """MEM-04: the wikis of missions that read the owner's mail; only their own mission reads them."""
    return [X.wiki_root(m) for m in load_missions().values() if any(str(n).startswith("gmail") for n in m.get("needs") or [])]


def vault_commit(paths, msg):
    subprocess.run(["git", "add", *paths], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "commit", "-qm", msg, "-m", "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"],
                   cwd=VAULT, capture_output=True)
    subprocess.run(["git", "push", "-q"], cwd=VAULT, capture_output=True, timeout=60)


def reindex():
    sh("docker", "exec", "aistack-qmd-1", "sh", "-c", "qmd update >/dev/null 2>&1 && qmd embed >/dev/null 2>&1", timeout=600)


# ---------- model calls ----------
def ask_text(prompt, key, model="gpt-sub", timeout=300):
    src = prompt
    P.record(src)                                       # MEM-11: the run records the prompt's version
    prompt = J.take(prompt, tools=False)                # a run's first prompt carries the agent's memory (ops/journal.py)
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(LITELLM, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            res = json.load(r)
    except Exception as e:
        RTM.model_call(model, int((time.time() - t0) * 1000), error=f"{type(e).__name__}: {str(e)}")
        raise
    RTM.model_call(model, int((time.time() - t0) * 1000), res.get("usage"))
    text = TC.answer(res, model)                         # refused when it stopped at its output limit
    RTM.stage("Answer", text, kind="say")
    P.case(src, text, model)                            # a replay case for a later change of this prompt
    return text


def ask_json(prompt, key, model="gpt-sub", timeout=300):
    return json.loads(re.search(r"\{.*\}", ask_text(prompt, key, model, timeout), re.S).group(0))


def hermes_z(prompt, timeout=TASK_TIMEOUT):
    """One agent run of the mission profile (vault search + web research tools, own key vk-mission)."""
    src = prompt
    P.record(src)                                        # MEM-11: the run records the prompt's version
    prompt = J.take(prompt)                              # the run's first prompt: its journal and matching wiki pages
    t0 = time.time()
    RTM.stage("Hermes (mission profile) starts", prompt)
    try:
        p = subprocess.run(["docker", "exec", "-u", "hermes", *RTM.env_args(), HERMES, "timeout", str(timeout), "hermes", "-p", "mission", "-z", prompt],
                           capture_output=True, text=True, timeout=timeout + 60)
        RTM.stage("Hermes (mission profile) finished", f"{len(p.stdout)} characters back" + (f", exit {p.returncode}" if p.returncode else ""),
                  int((time.time() - t0) * 1000), status="failure" if p.returncode else None)
        if not p.returncode:
            P.case(src, p.stdout)                        # a replay case for a later change of this prompt
        return p.stdout
    except subprocess.TimeoutExpired:
        RTM.stage("Hermes (mission profile) timed out", f"after {timeout} s", int((time.time() - t0) * 1000), kind="error", status="failure")
        return ""


# ---------- schedules ----------
SCHED = re.compile(r"^(?:(daily|weekdays) (\d\d):(\d\d)|weekly ((?:mon|tue|wed|thu|fri|sat|sun)(?:,(?:mon|tue|wed|thu|fri|sat|sun))*) (\d\d):(\d\d)|every (\d{1,2})h|manual)$")


def valid_schedule(s):
    m = SCHED.match(s or "")
    if not m:
        return False
    hh, mm = (m[2], m[3]) if m[1] else (m[5], m[6]) if m[4] else ("00", "00")
    return int(hh) < 24 and int(mm) < 60 and (not m[7] or 1 <= int(m[7]) <= 24)


def due_times(s, t):
    """Scheduled times of the last 8 days up to tomorrow (local time), ascending."""
    m = SCHED.match(s or "")
    if not m or s == "manual":
        return []
    base = t.replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for d in range(-8, 2):
        day = base + dt.timedelta(days=d)
        if m[7]:
            out += [day + dt.timedelta(hours=h) for h in range(0, 24, int(m[7]))]
            continue
        hh, mm = (int(m[2]), int(m[3])) if m[1] else (int(m[5]), int(m[6]))
        if m[1] == "daily" or (m[1] == "weekdays" and day.weekday() < 5) or (m[4] and DAYS[day.weekday()] in m[4].split(",")):
            out.append(day.replace(hour=hh, minute=mm))
    return out


def schedule_text(s):
    m = SCHED.match(s or "")
    if not m or s == "manual":
        return "On demand"
    if m[1] == "daily":
        return f"Daily {m[2]}:{m[3]}"
    if m[1] == "weekdays":
        return f"Weekdays {m[2]}:{m[3]}"
    if m[4]:
        return f"{', '.join(d.title() for d in m[4].split(','))} {m[5]}:{m[6]}"
    return f"Every {m[7]} h"


def window_hours(s):
    """The hours of news a briefing on schedule s reads: 36 for a daily one, the gap between runs plus half a day for a
    weekly one (a week for one day a week), so a weekly briefing doesn't read only its last day and a half."""
    m = SCHED.match(s or "")
    return round(168 / len(m[4].split(","))) + 12 if m and m[4] else 36


def period(m):
    return "Weekly" if (m.get("schedule") or "").startswith("weekly") else "Daily"


def next_due(s, t):
    """The next scheduled time after t (looks a week ahead, so weekly schedules always have one)."""
    return next((d for d in due_times(s, t + dt.timedelta(days=7)) if d > t), None)


def check_schedules(missions, c):
    t = now()
    for m in missions.values():
        if m.get("status") != "active":
            continue
        created = dt.datetime.fromisoformat(str(m.get("created", "2000-01-01T00:00:00+00:00")))
        if created.tzinfo is None:
            created = created.astimezone()
        past = [d for d in due_times(m.get("schedule"), t) if created < d <= t and t - d < dt.timedelta(hours=20)]
        if not past:
            continue
        due = past[-1].isoformat()
        if not c.execute("select 1 from runs where slug=? and due=?", (m["slug"], due)).fetchone():
            enqueue(c, m["slug"], "schedule", due)


REPEAT_WINDOW_H = 6                  # an identical event within this many hours is a loop, not news


def enqueue(c, slug, trigger, due=None, event=None, mode=None):
    if not event and c.execute("select 1 from runs where slug=? and status in ('queued','running','waiting') and event is null", (slug,)).fetchone():
        return False
    if event:                         # the loop guard: the same event again (same trigger, same summary) does not run again
        since = (now() - dt.timedelta(hours=REPEAT_WINDOW_H)).isoformat(timespec="seconds")
        same = json.dumps(event, sort_keys=True)
        for r in c.execute("select event from runs where slug=? and trigger='event' and started>=? and status in ('queued','running','waiting','ok')",
                           (slug, since)):
            try:
                if json.dumps(json.loads(r[0] or "{}"), sort_keys=True) == same:
                    log(f"{slug}: the same event again within {REPEAT_WINDOW_H} h, not queued ({event})")
                    return False
            except ValueError:
                continue
    c.execute("insert into runs (slug, trigger, due, status, started, event, mode) values (?,?,?,?,?,?,?)",
              (slug, trigger, due, "queued", now().isoformat(timespec="seconds"), json.dumps(event) if event else None, mode))
    c.commit()
    return True


# ---------- cost of a run: its key's calls between start and end ----------
def calls_of(key, start, end):
    """(calls, tokens, spend, models) of one key in a time window (LiteLLM spend logs are in UTC)."""
    s = start.astimezone(dt.timezone.utc).strftime("%F %T")
    e = (end + dt.timedelta(seconds=5)).astimezone(dt.timezone.utc).strftime("%F %T")
    out = sh("docker", "exec", "aistack-postgres-1", "psql", "-U", "litellm", "-d", "litellm", "-tAF", "|", "-c",
             'select count(*), coalesce(sum(s.total_tokens),0), coalesce(sum(s.spend),0), '
             "coalesce(string_agg(distinct s.model_group, ','),'') from \"LiteLLM_SpendLogs\" s "
             'join "LiteLLM_VerificationToken" k on k.token = s.api_key '
             f"where k.key_alias = '{key}' and s.\"startTime\" between '{s}' and '{e}' and s.model_group <> ''")
    try:
        n, tok, sp, models = out.strip().split("|")
        return int(n), int(tok), float(sp), models
    except ValueError:
        return 0, 0, 0.0, ""


def spend_30d(c, slug):
    return c.execute("select coalesce(sum(spend),0) from runs where slug=? and started > ?",
                     (slug, (now() - dt.timedelta(days=30)).isoformat())).fetchone()[0]


def refresh_costs(c, missions):
    """LiteLLM writes spend logs in batches: recount runs that ended in the last 20 minutes."""
    since = (now() - dt.timedelta(minutes=20)).isoformat()
    for r in c.execute("select id, slug, started, ended, calls from runs where ended > ? and status in ('ok','failed')", (since,)).fetchall():
        m = missions.get(r["slug"])
        if m:
            n, tok, sp, models = calls_of(KEY_OF[m["type"]], dt.datetime.fromisoformat(r["started"]), dt.datetime.fromisoformat(r["ended"]))
            if n != r["calls"]:
                c.execute("update runs set calls=?, tokens=?, spend=?, models=? where id=?", (n, tok, sp, models, r["id"]))
                c.commit()


# ---------- executing runs ----------
def run_briefing(m, logf):
    topic = m.get("topic", m["slug"])
    env = dict(os.environ, DESK_TELEGRAM="0")          # delivery (with buttons) happens below
    RTM.stage("Briefing pipeline starts", f"desk.sh {topic}: feeds, prices and filings, then the model writes the briefing")
    t0, n = time.time(), 0
    with open(logf, "w") as f:
        p = subprocess.Popen(["bash", str(OPS / "desk.sh"), topic], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True)
        try:
            for ln in p.stdout:                       # each line of the pipeline is a step in the live run view
                f.write(ln)
                f.flush()
                if ln.strip() and n < 400:
                    n += 1
                    low = ln.lower()
                    RTM.stage(TC.cut(ln.strip(), 160), ln.strip(), kind="error" if ("error" in low or "failed" in low or "traceback" in low) else "stage")  # cap: preview
            p.wait(timeout=3600)
        except subprocess.TimeoutExpired:
            p.kill()
    RTM.stage("Briefing pipeline finished", f"exit {p.returncode}", int((time.time() - t0) * 1000), status="failure" if p.returncode else None)
    out = Path(logf).read_text()
    filed = re.search(r"filed: (\S+)", out)
    if p.returncode or not filed:
        dl = Path(f"/srv/ai/desk/{topic}/last.log")
        tail = dl.read_text(errors="replace") if dl.exists() else out
        return "failed", tail.strip().splitlines()[-1] if tail.strip() else "no report", ""
    rel = filed.group(1)
    RTM.touched(rel, changed=True, note="the briefing")
    text = (VAULT / rel).read_text() if (VAULT / rel).exists() else ""
    head = re.search(r'^headline: "?(.*?)"?$', text, re.M)
    title = json.loads(f'"{head.group(1)}"') if head else "Briefing"
    tg = Path(f"/srv/ai/desk/{topic}/out/{rel[-13:-3]}.telegram.txt")
    if not X.deliver(m, title, tg.read_text() if tg.exists() else "", rel, f"{period(m)} briefing · {now():%d %b %Y}", text,
                     empty=X.briefing_empty(text)):
        RTM.stage("Nothing new: kept in the app", "no news was chosen, so this briefing is not sent by Telegram or e-mail; "
                  "the next full one names this day")
    try:
        n = X.compile_wiki(m, rel, text, os.environ["VK_DESK"])
        vault_commit([X.wiki_root(m)], f"wiki: {m['slug']} from {rel}")
        log(f"wiki {m['slug']}: {n} pages updated")
    except Exception as e:
        log(f"wiki update failed: {e}")
    reindex()
    return "ok", title, rel


TASK_PROMPT = P.text("mission", "TASK")


def section(text, name):
    m = re.search(rf"^## {name}\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else ""


def file_task_result(m, out, kind="run", deliver=True):
    result, notes, short = section(out, "Result"), section(out, "Notes"), section(out, "Summary")
    if not result:
        return "failed", (out.strip().splitlines() or ["no answer"])[-1], ""
    d = MISSIONS / m["slug"]
    t = now()
    rel = f"missions/{m['slug']}/log/{t:%Y}/{t:%m}/{t:%Y-%m-%d-%H%M}.md"
    text = f"# {m['title']} · {t:%d %b %Y %H:%M}\n\n## Result\n\n{result}\n\n## Summary\n\n{short}\n"
    write_front(VAULT / rel, {"mission": m["slug"], "title": m["title"], "date": t.isoformat(timespec="minutes"),
                              "type": "mission-log", "kind": kind}, text)
    RTM.touched(rel, changed=True, note=f"the run's report ({kind})")
    if notes:                                          # MEM-05: the working state lives in the mission's journal
        old, extra = d / "NOTES.md", []
        if old.exists():
            old.unlink()
            extra = [f"missions/{m['slug']}/NOTES.md"]
        J.set_state(f"mission:{m['slug']}", notes, m["title"], extra)
        RTM.touched(J.rel(f"mission:{m['slug']}"), changed=True, note="working state for the next run")
    try:
        X.compile_wiki(m, rel, text, os.environ["VK_MISSION"])
    except Exception as e:
        log(f"wiki update failed: {e}")
    vault_commit([f"missions/{m['slug']}"], f"mission: {m['slug']} {kind} {t:%F %H:%M}")
    reindex()
    if deliver:
        X.deliver(m, m["title"], short or TC.cut(result, 500), rel, f"Mission {kind} · {t:%d %b %Y}", text)  # cap: preview
    return "ok", short or TC.cut(result, 300), rel  # cap: preview


def run_task(m, logf, ev=None):
    logs = sorted((MISSIONS / m["slug"] / "log").rglob("*.md"))
    last = TC.cut(section(logs[-1].read_text(), "Result"), 2500) if logs else "(none)"  # cap: prompt
    evtext = f"\nThis run was triggered by an event: {ev['trigger']}: {ev['summary']}\nStart with what this event means for the mission.\n" if ev else ""
    out = hermes_z(TASK_PROMPT.format(date=f"{now():%d %b %Y}", title=m["title"], goal=m.get("goal", ""), last=last, event=evtext) + FL.brief(m))
    Path(logf).write_text(out)
    return file_task_result(m, out, "event run" if ev else "run")


def execute(c, row, missions):
    m = missions.get(row["slug"])
    rid = row["id"]
    if not m:
        c.execute("update runs set status='failed', summary='mission not found' where id=?", (rid,)); c.commit()
        return
    budget = float(m.get("budget_usd_month") or 0)
    if spend_30d(c, m["slug"]) >= budget > 0:
        c.execute("update runs set status='skipped', summary='monthly budget reached' where id=?", (rid,)); c.commit()
        event("budget", m["slug"], f"Run skipped: monthly budget ${budget:.2f} reached", push=True, title=m["title"])
        return
    card = "desk" if m["type"] == "briefing" else "mission"            # the agent card this run belongs to (config/agents.yaml)
    if SW.paused(card):                                                  # SWM-26: the owner paused this agent (or all)
        c.execute("update runs set status='skipped', summary='paused by the owner' where id=?", (rid,)); c.commit()
        event("paused", m["slug"], "Run skipped: you paused this agent", title=m["title"])
        return
    ev = json.loads(row["event"]) if row["event"] else None
    mode = row["mode"] or ("alert" if ev and m["type"] == "briefing" else "deep" if m["type"] == "task" and m.get("depth") == "deep" else "standard")
    start = now()
    logf = RUNLOGS / f"{rid}.log"
    c.execute("update runs set status='running', started=?, log=?, mode=? where id=?", (start.isoformat(timespec="seconds"), str(logf), mode, rid))
    c.commit()
    with lock:
        running.update(id=rid, slug=m["slug"], title=m["title"], type=m["type"], started=start.isoformat(timespec="seconds"),
                       log=str(logf), trigger=row["trigger"], mode=mode, event=ev)
    RTM.set_ref(f"mission-run:{rid}", f"mission:{m['slug']}")   # Hermes and Claude report this run's work under it
    RTM.start(f"mission-run:{rid}", f"mission:{m['slug']}", f"Mission · {m['title']} · run {rid}", data={"manifest": {"agent": f"mission:{m['slug']}", "type": m["type"], "mode": mode, "prompts": P.version("mission"),
              "trigger": row["trigger"], "key": KEY_OF.get(m["type"]), "card": REG.hash_of(card)}})
    J.begin(f"mission:{m['slug']}", m["title"], run=f"mission-run:{rid}", card=card, wiki=X.wiki_root(m))   # MEM-05: its opening
    event("run_started", m["slug"], {"schedule": "Scheduled run started", "event": f"Event run started: {(ev or {}).get('trigger', '')}"}
          .get(row["trigger"], "Run started (on demand)") + (" · deep research" if mode == "deep" else ""), title=m["title"])
    try:
        if mode == "alert":
            status, summary, output = X.run_alert(m, ev, logf)
        elif mode == "deep":
            status, summary, output = X.run_deep(m, logf, rid, c, ev)
        elif m["type"] == "briefing":
            status, summary, output = run_briefing(m, logf)
        elif m["type"] == "shopping":
            status, summary, output = SH.run(m, logf, ev)
        elif m["type"] == "cleanup":
            status, summary, output = CL.run(m, logf, ev)
        else:
            status, summary, output = run_task(m, logf, ev)
    except Exception as e:
        status, summary, output = "failed", f"{type(e).__name__}: {e}", ""
        log(traceback.format_exc())
    end = now()
    J.after_run(m, rid, status, summary, output, (end - start).total_seconds())     # its journal entry (before the run ends)
    tries = int(row["attempts"] or 0)
    said = (summary + "\n" + "\n".join(tail(logf, 40))) if status == "failed" else ""   # cap: parse
    down = stack_gone(said) if said and not paused(said) else ""     # PLT-28: the stack went away under this run: not the run's fault
    if (down or (said and paused(said))) and tries < MAX_WAITS:
        retry = end + dt.timedelta(minutes=DOWN_RETRY_MIN if down else RETRY_MIN)
        c.execute("update runs set status='waiting', retry_at=?, attempts=?, summary=? where id=?",
                  (retry.isoformat(timespec="seconds"), tries + 1, f"The stack is not up ({down}); retry at {retry:%H:%M}" if down
                   else f"ChatGPT paused the stack (usage limit); retry {tries + 1} at {retry:%H:%M}", rid))
        c.commit()
        with lock:
            running.clear()
        RTM.end(f"mission-run:{rid}", f"mission:{m['slug']}", "limit", f"waiting to retry: {down}" if down else "usage limit: waiting to retry", (end - start).total_seconds())
        RTM.set_ref(None)
        event("waiting", m["slug"], f"The stack is not up ({down}). Waiting; retry at {retry:%H:%M}." if down
              else f"ChatGPT paused the stack (usage limit). Waiting; retry at {retry:%H:%M}.", push=not down and tries == 0, title=m["title"])
        return
    missing = FL.check_run(m, rid)["missing"] if m.get("files_asked") and status == "ok" else None
    if missing:                                        # MIS-25: a run that left an asked-for file unmade is partial, and says so
        summary = f"Partial: not delivered: {', '.join(missing)}. {summary}"
        RTM.stage(f"Files not delivered: {', '.join(missing)}", "asked for when the mission was made; the run did not save them", kind="error")
    time.sleep(8)                       # LiteLLM writes spend logs in batches (refresh_costs recounts later)
    calls, tokens, spend, models = calls_of(KEY_OF[m["type"]], start, end)
    c.execute("update runs set status=?, ended=?, seconds=?, calls=?, tokens=?, spend=?, models=?, summary=?, output=? "
              "where id=?", (status, end.isoformat(timespec="seconds"), (end - start).total_seconds(), calls, tokens, spend,
                             models, summary, output, rid))
    c.commit()
    with lock:
        running.clear()
    RTM.end(f"mission-run:{rid}", f"mission:{m['slug']}", RTM.mission_state(status, summary), summary, (end - start).total_seconds())
    RTM.set_ref(None)
    mins = (end - start).total_seconds() / 60
    if status == "ok" and m.get("once"):
        m["status"] = "archived"
        save_mission(m)
        vault_commit([f"missions/{m['slug']}"], f"mission: {m['slug']} done (one-off)")
    if status == "ok":
        event("run_done", m["slug"], f"{summary} ({mins:.0f} min, {calls} calls)", push="app" in (m.get("deliver") or []), title=m["title"])
    else:
        event("run_failed", m["slug"], f"Run failed: {summary}", push=True, title=m["title"])
        if "telegram" in (m.get("deliver") or []):
            X.telegram(f"<b>{m['title']}</b>: run failed.\n{summary}", X.links(m["slug"]), category="result")


def park(what, ready, timeout=1800, every=10):
    """Wait for something slow that is not model work (e.g. the Windows disk scan): the run gives its slot to the next
    queued mission meanwhile and shows as waiting. ready() is polled every few seconds; True when it returned True,
    False after the timeout. Outside a worker thread (tests, tools) it simply polls."""
    rid = getattr(_run_local, "rid", None)
    me = {}
    t0 = time.time()
    RTM.emit(RTM.ref() or f"mission-run:{rid}", "wait", title=what, detail="parked: other missions may run meanwhile")
    if rid is not None:
        with lock:
            me = dict(running)
            parked[rid] = {**me, "waiting_for": what, "since": now().isoformat(timespec="seconds")}
            running.clear()
        slot.release()
    ok = False
    try:
        while time.time() - t0 < timeout and not stop.is_set():
            try:
                if ready():
                    ok = True
                    break
            except Exception:
                pass
            stop.wait(every)
    finally:
        if rid is not None:
            slot.acquire()                                 # back in line for model work
            with lock:
                parked.pop(rid, None)
                running.clear()
                running.update(me)
    RTM.emit(RTM.ref() or f"mission-run:{rid}", "wait", title=f"{what}: {'ready' if ok else 'timed out'}",
             status="ok" if ok else "timeout", ms=int((time.time() - t0) * 1000))
    return ok


def requeue_interrupted(c):
    """A runner restart (a deploy) ends the run in progress: mark it, and start it again once, unless it had been
    running for hours (then it is more likely the cause than the victim)."""
    rows = c.execute("select id, slug, trigger, mode, started from runs where status='running'").fetchall()
    c.execute("update runs set status='failed', summary='interrupted (runner restarted)' where status='running'")
    c.commit()
    for r in rows:
        RTM.end(f"mission-run:{r['id']}", f"mission:{r['slug']}", "stopped", "interrupted (runner restarted)")
    for r in rows:
        try:
            fresh = now() - dt.datetime.fromisoformat(r["started"]) < dt.timedelta(hours=2)
        except Exception:
            fresh = False
        if fresh and r["trigger"] != "restart" and enqueue(c, r["slug"], "restart", mode=r["mode"]):
            log(f"requeued {r['slug']} (interrupted by a runner restart)")


def stack_gone(said):
    """Why a failed run was the stack's doing and not its own, or "": the stack is down now, or its log says it was."""
    return G.why_down() or ("the stack was restarting" if STACK_GONE.search(said) else "")


def stack_watch(step=30, down_for=600):
    """PLT-28: the stack down for 10 minutes: one message naming the cause, and one when it is back. (On 4 Nov the owner
    got an alert per job that failed, and none that said Docker had stopped.)"""
    since = told = None
    while not stop.wait(step):
        since, told = stack_watch_step(G.why_down(), since, told, time.time(), down_for)


def stack_watch_step(why, since, told, t, down_for=600):
    """-> (down since, told the owner)."""
    if not why:
        if told:
            notify("The AI stack is back.")
        return None, None
    since = since or t
    if not told and t - since >= down_for:
        notify(f"⚠️ The AI stack has been down for {round((t - since) / 60)} min: {why}. It keeps trying to start by itself; "
               "scheduled work waits and runs when it is back.")
        told = True
    return since, told


def _run_thread(row):
    _run_local.rid = row["id"]
    c = db()
    try:
        execute(c, row, load_missions())
    except Exception:
        log(traceback.format_exc())
    finally:
        c.close()
        active.pop(row["id"], None)
        _run_local.rid = None
        slot.release()


def worker():
    """Starts the next queued run whenever the run slot is free; a parked run (park()) frees it for the next one."""
    while not stop.is_set():
        try:
            if slot.acquire(timeout=3):
                c = db()
                busy = list(active)
                q = ("select * from runs where (status='queued' or (status='waiting' and retry_at <= ?))"
                     + (f" and id not in ({','.join('?' * len(busy))})" if busy else "") + " order by id limit 1")
                row = c.execute(q, (now().isoformat(timespec="seconds"), *busy)).fetchone()
                c.close()
                if row and G.why_down():                # PLT-28: it stays queued until the stack is back
                    row = None
                if row:
                    t = threading.Thread(target=_run_thread, args=(row,), daemon=True, name=f"run-{row['id']}")
                    active[row["id"]] = t
                    t.start()
                else:
                    slot.release()
        except Exception:
            log(traceback.format_exc())
        stop.wait(3)


# ---------- requests (app, chat via MCP) ----------
def slugify(title, missions):
    s = unicodedata.normalize("NFKD", title.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss"))
    s = re.sub(r"[^a-z0-9]+", "-", s.encode("ascii", "ignore").decode()).strip("-")[:40] or "mission"  # cap: id
    base, n = s, 2
    while s in missions or (VAULT / "topics" / s).exists():
        s, n = f"{base}-{n}", n + 1
    return s


def words(t):
    return {w for w in re.findall(r"[a-z0-9]+", t.lower()) if len(w) > 2}


def duplicate_of(title, missions):
    """A mission created in the last 30 minutes with a similar title (chat tools sometimes retry a slow create)."""
    w = words(title)
    for m in missions.values():
        if m.get("status") == "archived":
            continue
        try:
            age = now() - dt.datetime.fromisoformat(str(m.get("created")))
        except ValueError:
            continue
        o = words(m["title"])
        if age < dt.timedelta(minutes=30) and len(w & o) / max(len(w | o), 1) >= 0.4:
            return m
    return None


DRAFT = P.text("desk", "TOPIC_DRAFT")


def create_briefing(meta, req):
    example = (VAULT / "topics/copper/TOPIC.md").read_text()
    d = ask_json(DRAFT.format(example=example, title=req["title"], description=req.get("description", "")), os.environ["VK_DESK"])
    watch = TC.first([w for w in d.get("watchlist", []) if isinstance(w, dict) and w.get("name")], 15, "watchlist entries")  # cap: untrusted (a model's draft the owner reviews; as many as the owner may set)
    spec = {"symbols": [w["symbol"] for w in watch if w.get("symbol")], "feeds": d.get("feeds", []), "filings": d.get("filings", [])}
    chk = subprocess.run(["docker", "run", "--rm", "-i", "--network", "aistack_webonly", "-e", "SEC_CONTACT", "aistack/desk:1", "--check"],
                         input=json.dumps(spec), capture_output=True, text=True, timeout=300)
    if chk.returncode or not chk.stdout.strip():
        raise RuntimeError(f"source check failed: {(chk.stderr.strip().splitlines() or ['?'])[-1]}")
    ok = json.loads(chk.stdout)
    for w in watch:
        if w.get("symbol") not in ok["symbols"]:
            w.pop("symbol", None)
        for k in ("aliases", "proxy"):
            if not w.get(k) or w.get(k) == "null":
                w.pop(k, None)
    # cap: untrusted (a model's draft the owner reviews)
    sections = TC.first([s for s in d.get("sections", []) if isinstance(s, str)], 10, "report sections") or \
               ["Headline", "In 60 seconds", "Key developments", "What to watch", "Open questions"]
    topic = {"topic": d.get("topic") or req["title"], "slug": meta["slug"], "language": "en",
             "mission": d.get("mission", req.get("description", "")), "key_questions": TC.first(d.get("key_questions", []), 8, "key questions"),  # cap: untrusted (a model's draft the owner reviews)
             "watchlist": watch,
             "sources": {"feeds": ok["feeds"], "search": TC.first([q for q in d.get("search", []) if isinstance(q, str)], 10, "search queries"),  # cap: untrusted (a model's draft the owner reviews)
                         "jobs": [{"what": str(j["what"])[:120], "where": str(j.get("where") or "")[:80],   # cap: id
                                   "radius_km": min(max(int(j.get("radius_km") or 50), 0), 200)}
                                  for j in TC.first(d.get("jobs") or [], 6, "job searches") if isinstance(j, dict) and j.get("what")],  # cap: untrusted (a model's draft the owner reviews)
                         "gdelt": [], "filings": ok["filings"], "prefer": d.get("prefer", []), "avoid": d.get("avoid", [])},
             "report": {"sections": sections, "length": "2 minutes to read"}, "window_hours": window_hours(meta.get("schedule"))}
    write_front(VAULT / "topics" / meta["slug"] / "TOPIC.md", topic, d.get("notes", ""))
    dropped = len(spec["symbols"]) - len(ok["symbols"]) + len(spec["feeds"]) - len(ok["feeds"])
    return f"{len(topic['key_questions'])} key questions, {len(watch)} watched, {len(topic['sources']['search'])} searches" + \
           (f", {dropped} broken sources dropped" if dropped else "")


TOPIC_FIELDS = {"key_questions", "search", "feeds", "filings", "watchlist", "mission", "notes"}
DELIVER = ("telegram", "app", "email")


def handle(req, missions, c):
    a = req.get("action")
    slug = req.get("slug", "")
    m = missions.get(slug)
    if a == "create":
        typ = req.get("type")
        title = str(req.get("title", "")).strip()
        sched = req.get("schedule") or ("daily 06:30" if typ == "briefing" else "manual")
        if typ not in KEY_OF or not 3 <= len(title) <= 80 or not valid_schedule(sched):
            raise ValueError("type, title (3-80 characters) or schedule invalid")
        dup = duplicate_of(title, missions)
        if dup:
            return {"slug": dup["slug"], "detail": f"already exists as '{dup['title']}' (created {dup['created']}); nothing new created",
                    "duplicate": True}
        desc = limit(str(req.get("description", "")), 20000, "the description")
        s = slugify(title, missions)
        meta = {"slug": s, "title": title, "type": typ, "status": "active", "schedule": sched,
                "triggers": X.clean_triggers(req.get("triggers")), "depth": "deep" if req.get("depth") == "deep" and typ == "task" else None,
                "budget_usd_month": min(max(float(req.get("budget_usd_month", 0.10)), 0), 1.0),
                "deliver": [x for x in req.get("deliver", ["telegram", "app"]) if x in DELIVER],
                "created": now().isoformat(timespec="seconds"), "goal": desc or title, "once": bool(req.get("once"))}
        asked = FL.asked_of(req.get("files"))         # MIS-23: refused at once (with the reason) when the stack cannot make one
        if asked:
            meta["files_asked"] = asked
        needs = [n for n in (req.get("needs") or []) if n in CONN_SCOPES]      # app access the owner grants on the mission page
        if needs:
            meta["needs"] = needs
        if typ == "cleanup":                  # what to analyse: the AI phone or the PC (guessed from the words if not given)
            meta["target"] = req.get("target") if req.get("target") in ("phone", "pc") else CL.target_of(meta)
        if typ == "shopping":                 # price watch: later runs only report a drop of at least this many percent
            meta["watch_pct"] = min(max(float(req.get("watch_pct") or 0), 0), 50)
            if req.get("task"):               # TSK-21: a task holds it; the Conductor runs its checks
                meta["task"] = int(req["task"])
        if meta["once"]:
            meta["schedule"] = "manual"
        save_mission(meta)                    # first, so a retried create finds it as a duplicate
        if typ == "briefing":
            meta["topic"] = s
            meta["goal"] = f"{period(meta)} briefing: {title}. {desc}".strip() + f"\n\nContent, key questions and sources: topics/{s}/TOPIC.md"
            try:
                detail = create_briefing(meta, req)
            except Exception:
                (MISSIONS / s / "MISSION.md").unlink(missing_ok=True)
                raise
            save_mission(meta)
        else:
            detail = ("shopping agent created (it proposes; it never buys without your approval)" if typ == "shopping" else
                      f"cleanup analysis of the {'AI phone' if meta.get('target') == 'phone' else 'PC'} created (it never deletes)"
                      if typ == "cleanup" else "long-term task created")
        vault_commit([f"missions/{s}"] + ([f"topics/{s}"] if typ == "briefing" else []), f"mission: create {s}")
        reindex()
        if req.get("run_now", True):
            enqueue(c, s, "manual")
        event("created", s, f"New mission ({typ}, {schedule_text(sched)}"
              f"{', ' + str(len(meta['triggers'])) + ' event triggers' if meta['triggers'] else ''}): {detail}"
              + ("; first run starts now" if req.get("run_now", True) else ""), push=True, title=title)
        return {"slug": s, "detail": detail}
    if not m:
        raise ValueError(f"no mission '{slug}'")
    if a == "run":
        if m.get("status") == "archived":
            raise ValueError("mission is archived")
        if not enqueue(c, slug, "manual", mode="deep" if req.get("deep") and m["type"] == "task" else None):
            raise ValueError("already running or queued")
        event("queued", slug, "Run queued (on demand)" + (" · deep research" if req.get("deep") else ""), title=m["title"])
        return {"queued": True}
    if a in ("pause", "resume", "archive"):
        m["status"] = {"pause": "paused", "resume": "active", "archive": "archived"}[a]
        if a == "resume":
            m["created"] = now().isoformat(timespec="seconds")      # no catch-up of runs missed while paused
        save_mission(m)
        vault_commit([f"missions/{slug}"], f"mission: {a} {slug}")
        event(a, slug, {"pause": "paused", "resume": "resumed", "archive": "archived (files stay in the vault)"}[a], push=True, title=m["title"])
        return {"status": m["status"]}
    if a == "update":
        f = req.get("fields") or {}
        changed = []
        if "title" in f and 3 <= len(str(f["title"]).strip()) <= 80:
            m["title"] = str(f["title"]).strip(); changed.append("title")
        if "schedule" in f:
            if not valid_schedule(f["schedule"]):
                raise ValueError(f"schedule '{f['schedule']}' invalid")
            m["schedule"] = f["schedule"]; m["created"] = now().isoformat(timespec="seconds"); changed.append("schedule")
        if "triggers" in f:
            m["triggers"] = X.clean_triggers(f["triggers"]); changed.append("event triggers")
        if "depth" in f and m["type"] == "task":
            m["depth"] = "deep" if f["depth"] == "deep" else None; changed.append("depth")
        if "budget_usd_month" in f:
            m["budget_usd_month"] = min(max(float(f["budget_usd_month"]), 0), 1.0); changed.append("budget")
        if "deliver" in f:
            m["deliver"] = [x for x in f["deliver"] if x in DELIVER]; changed.append("delivery")
        if "watch_pct" in f and m["type"] == "shopping":    # scheduled re-checks only report a drop of at least this much
            m["watch_pct"] = min(max(float(f["watch_pct"] or 0), 0), 50); changed.append("price watch")
        if "goal" in f and m["type"] in ("task", "shopping"):
            m["goal"] = limit(str(f["goal"]), 20000, "the goal"); changed.append("goal")
        paths = [f"missions/{slug}"]
        tf = {k: v for k, v in f.items() if k in TOPIC_FIELDS}
        if tf and m["type"] == "briefing":
            (meta, body), p = topic_of(m)
            for k, v in tf.items():
                if k == "mission":
                    meta["mission"] = limit(str(v), 4000, "the mission")
                elif k == "notes":
                    body = limit(str(v), 20000, "the notes")
                elif k == "key_questions":
                    meta["key_questions"] = [limit(str(x), 1000, "a key question") for x in limit_items(v, 20, "key questions")]
                elif k == "watchlist":
                    meta["watchlist"] = [{kk: vv for kk, vv in w.items() if kk in ("name", "symbol", "aliases", "proxy") and vv}
                                         for w in limit_items(v, 15, "watchlist entries") if isinstance(w, dict) and w.get("name")]
                else:
                    meta.setdefault("sources", {})[k] = [limit(str(x), 1000, "a source") for x in limit_items(v, 30, "sources")]
            write_front(p, meta, body)
            paths.append(f"topics/{m.get('topic', slug)}")
            changed.append("briefing focus")
        if "schedule" in f and m["type"] == "briefing":     # the news window follows the schedule (weekly: a week)
            (meta, body), p = topic_of(m)
            if meta.get("window_hours") != window_hours(m["schedule"]):
                meta["window_hours"] = window_hours(m["schedule"])
                write_front(p, meta, body)
                paths.append(f"topics/{m.get('topic', slug)}")
        save_mission(m)
        vault_commit(paths, f"mission: update {slug} ({', '.join(changed)})")
        event("updated", slug, "changed: " + (", ".join(changed) or "nothing"), title=m["title"])
        return {"changed": changed}
    raise ValueError(f"unknown action '{a}'")




def handle_stack(req):
    """Actions on the rest of the stack: e-mail to the owner, add to the vault, analyse a repo, search / forget memory."""
    a = req["action"]
    if a == "email":
        if not X.email_ready():
            raise ValueError("e-mail is not set up (make email-setup)")
        subject, body = limit(str(req.get("subject", "")).strip(), 300, "the subject"), limit(str(req.get("markdown", "")), 200000, "the e-mail")
        if not subject or not body.strip():
            raise ValueError("subject and text needed")
        if not X.email(subject, body, f"From your assistant · {now():%d %b %Y}", X.APP):
            raise RuntimeError("sending failed")
        event("email", "", f"E-mail sent: {subject}")
        return {"sent": True}
    if a == "vault_add":
        title = limit(re.sub(r"\s+", " ", str(req.get("title", ""))).strip(), 200, "the title")
        inbox = VAULT / "raw" / "_inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        stamp = f"{now():%Y-%m-%d-%H%M%S}"
        if req.get("upload"):
            name = Path(str(req["upload"])).name
            src = HOME / "app" / "uploads" / name
            if not src.is_file():
                raise ValueError("upload not found")
            dst = inbox / name
            dst.write_bytes(src.read_bytes())
        else:
            text, url = limit(str(req.get("text", "")), 200000, "the text"), str(req.get("url", "")).strip()
            if url:
                if not re.match(r"^https?://", url):
                    raise ValueError("not a web address")
                p_ = subprocess.run(["docker", "run", "--rm", "-i", "--network", "aistack_webonly", "aistack/desk:1", "--fetch"],
                                    input=json.dumps({"url": url}), capture_output=True, text=True, timeout=180)
                if p_.returncode or not p_.stdout.strip():
                    raise ValueError(f"page not readable: {(p_.stderr.strip().splitlines() or ['?'])[-1]}")
                d = json.loads(p_.stdout)
                title, text = title or d.get("title") or url, d["text"]
            if len(text.strip()) < 20:
                raise ValueError("nothing to add")
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50] or "note"  # cap: id
            dst = inbox / f"{stamp}-{slug}.md"
            write_front(dst, {"title": title or slug, "source": url or "Mission Control", "added": now().isoformat(timespec="minutes")},
                        f"# {title}\n\n{text}")
        rel = str(dst.relative_to(VAULT))
        event("vault_add", "", f"Added to the vault inbox: {title or dst.name} (wiki pages follow in a few minutes)")
        return {"path": rel}
    if a == "understand":
        r = O.start(req.get("repo"), str(req.get("source") or "app"))   # BLD-26: one job, the whole package, or the reason why not
        if not r["already"]:
            event("understand", "", f"Onboarding {r['repo']}: code graph, code map, explanations, search and a written analysis", title="Code")
        return r
    if a == "forget":
        text = str(req.get("text", "")).strip()
        if not 3 <= len(text) <= 200:
            raise ValueError("give 3-200 characters to forget")
        out = sh("python3", str(OPS / "hindsight_forget.py"), text, timeout=300)
        event("forget", "", f"Long-term memory: forgot conversations containing “{text}”")
        return {"output": tailcut(out.strip(), 4000)}  # cap: store
    if a == "memory_search":
        q = limit(str(req.get("q", "")).strip(), 500, "the search").replace("'", "''")
        if len(q) < 2:
            return {"facts": []}
        rows = sh("docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-tAF", "\t", "-c",
                  f"select fact_type, to_char(created_at, 'YYYY-MM-DD'), left(text, 400) from memory_units "
                  f"where text ilike '%{q}%' order by created_at desc limit 40").splitlines()  # cap: list (the 40 newest matches; a narrower search finds the rest)
        return {"facts": [dict(zip(("type", "date", "text"), r.split("\t"))) for r in rows if r.count("\t") == 2]}
    raise ValueError("unknown action")


def handle_memory(req):
    pid, decision = str(req.get("id", "")), req.get("decision")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid) or decision not in ("approve", "reject"):
        raise ValueError("invalid approval")
    out = sh("docker", "exec", "-u", "hermes", HERMES, "hermes", "-z", f"/memory {decision} {pid}", timeout=180)
    with open("/srv/ai/state/approvals.jsonl", "a") as f:
        f.write(json.dumps({"ts": int(time.time()), "kind": "memory", "item_id": pid, "rule": "user",
                            "decision": "approved" if decision == "approve" else "rejected", "actor": "app"}) + "\n")
    event("memory", "", f"Memory {pid} {'saved' if decision == 'approve' else 'discarded'}")
    return {"output": tailcut(out.strip(), 4000)}  # cap: store


STACK_ACTIONS = {"email", "vault_add", "understand", "forget", "memory_search"}
BUILD_ACTIONS = {"build_assign", "build_revise", "build_approve", "build_approve_all", "build_reject", "build_recheck", "build_revert"}
IMPROVE_ACTIONS = {"improve_scan", "proposal_accept", "proposal_dismiss"}
REPO_ACTIONS = {"codemap", "repo_create", "repo_buildable", "repo_remove"}
CREW_ACTIONS = {"crew_run", "crew_memory_forget", "crew_memory_undo", "crew_schedule", "health_ack", "phone_cleanup_do", "phone_cleanup_do_all", "phone_cleanup_dismiss", "phone_cleanup_undo"}
creating = threading.Lock()            # one new mission at a time (drafting takes a minute or two)


def handle_forgejo_connect(req):
    """The owner's Forgejo token from the app: check it with Forgejo, store it encrypted (sops), restart to load it.
    The token is never logged, echoed or put on a command line."""
    tok = str(req.get("token", "")).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tok):
        raise ValueError("not a Forgejo token")
    def get(path):
        r = urllib.request.Request(B.FORGEJO + path, headers={"Authorization": f"token {tok}"})
        with urllib.request.urlopen(r, timeout=15) as resp:
            return json.load(resp)
    try:
        user = get("/user")["login"]
        get("/user/repos?limit=1")
    except urllib.error.HTTPError as e:
        raise ValueError("Forgejo refused this token (check its permissions: repository read+write, user read)"
                         if e.code in (401, 403) else f"Forgejo answered {e.code}") from None
    except OSError:
        raise ValueError("Forgejo is not reachable from the PC right now (is the NAS on?)") from None
    store_secret("FORGEJO_TOKEN", tok, f"secrets: Forgejo token for {user} (encrypted, set from Mission Control)")
    event("system", "", f"Forgejo connected as {user}", push=True, title="Code")
    subprocess.Popen(["systemd-run", "--user", "--on-active=3", "--quiet", "systemctl", "--user", "restart", "missions.service"])
    return {"user": user}


def store_secret(name, value, msg):
    """Put one secret into secrets/secrets.enc.yaml (sops, value over stdin: never on a command line or in a log)
    and commit the encrypted file at once: a dirty live checkout stops every later build deploy."""
    p = subprocess.run(["sops", "set", "--value-stdin", "secrets/secrets.enc.yaml", f'["{name}"]'], cwd=str(STACK_REPO),
                       input=json.dumps(value), capture_output=True, text=True, timeout=60)
    if p.returncode:
        raise ValueError("could not save it encrypted (sops); nothing changed")
    for cmd in (["git", "add", "secrets/secrets.enc.yaml"], ["git", "commit", "-q", "-m", msg], ["git", "push", "-q", "origin", "HEAD"]):
        subprocess.run(cmd, cwd=str(STACK_REPO), capture_output=True, timeout=120)


def notify_task(tid, title, what):
    """A task that waits for the owner (a question, its plan's OK), through the one notification path."""
    N.send(f"Task #{tid} {what}: {title}", "result", by="conductor", title="Tasks", buttons=[[("🔍 Open the task", f"{X.APP}/#/task/{tid}")]],
           push_on=True, event_kind="task")


def handle_notify(req):
    """The owner's notification preferences (OBS-16), and the app's word that a chat which waited for the usage limit
    is answered (AST-12): the owner may have left the app, so it goes out through the one path."""
    if req["action"] == "notify_prefs":
        return {"prefs": N.set_prefs(req.get("prefs") or {})}
    cid = str(req.get("chat", ""))
    if not re.fullmatch(r"[a-z0-9]{6,24}", cid):
        raise ValueError("no such chat")
    N.send(f"The answer that waited for the usage limit is ready: {req.get('title') or 'your chat'}", "result", by="main", title="Chat",
           buttons=[[("💬 Open the chat", f"{X.APP}/#/chat?c={cid}")]], push_on=True, event_kind="chat")
    return {}


def respond(rid, req):
    c = db()
    try:
        a = req.get("action")
        res = (CT.handle(req, c) if a == "claude_task" else handle_forgejo_connect(req) if a == "forgejo_connect" else handle_memory(req) if a == "memory" else handle_stack(req) if a in STACK_ACTIONS
               else B.handle(req, c) if a in BUILD_ACTIONS else I.handle(req, c) if a in IMPROVE_ACTIONS
               else R.handle(req, c) if a in REPO_ACTIONS else CR.handle(req, c) if a in CREW_ACTIONS else J.handle(req) if a in J.ACTIONS
               else WD.handle(req) if a in WD.ACTIONS else SH.handle(req, c) if a in SH.ACTIONS else W.handle(req) if a in W.ACTIONS else H.handle(req) if a in H.ACTIONS
               else SW.handle(req, c) if a in SW.ACTIONS else FL.handle(req) if a in FL.ACTIONS else handle_notify(req) if a in ("notify_prefs", "chat_ready") else TK.handle(req, c) if a in TK.ACTIONS else EV.handle(req, c) if a in EV.ACTIONS else A2.handle(req) if a in A2.ACTIONS
               else handle(req, load_missions(), c))
        res = {"ok": True, **res}
    except Exception as e:
        res = {"ok": False, "error": str(e)}
        log(f"request {rid} failed: {e}")
        if req.get("action") == "create":
            event("error", "", f"Mission could not be created: {str(e)}", push=True, title=req.get("title", ""))
    finally:
        c.close()
    (PUBLIC / "results").mkdir(exist_ok=True)
    (PUBLIC / "results" / f"{rid}.json").write_text(json.dumps(res, ensure_ascii=False))


def process_inbox():
    for f in sorted(INBOX.glob("*.json")):
        rid = f.stem
        try:
            req = json.loads(f.read_text())
            f.unlink()
        except Exception:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid) or not isinstance(req, dict):
            continue
        if req.get("action") in ("create", "memory", "email", "vault_add", "forget", "build_reject", "codemap", "repo_create", "repo_buildable", "repo_remove", "crew_memory_forget", "crew_memory_undo"):     # slow ones run in a thread
            def slow(rid=rid, req=req):
                with creating:
                    respond(rid, req)
            threading.Thread(target=slow, daemon=True).start()
        else:
            respond(rid, req)
    (PUBLIC / "results").mkdir(exist_ok=True)
    for old in (PUBLIC / "results").glob("*.json"):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink()


# ---------- state for the app ----------
_sys = {"t": 0, "data": {}}


def system_info():
    if time.time() - _sys["t"] < 60:
        return _sys["data"]
    q = lambda sql: [r.split("|") for r in sh("docker", "exec", "aistack-postgres-1", "psql", "-U", "litellm", "-d", "litellm",
                                               "-tAF", "|", "-c", sql).splitlines() if r]
    spend = q('select coalesce(sum(spend) filter (where "startTime" > now() - interval \'1 day\'),0), '
              'coalesce(sum(spend) filter (where "startTime" > now() - interval \'30 days\'),0), coalesce(sum(spend),0), '
              'count(*) filter (where "startTime" > now() - interval \'1 day\' and model_group <> \'\'), '
              'coalesce(sum(total_tokens) filter (where "startTime" > now() - interval \'1 day\'),0) from "LiteLLM_SpendLogs"')
    agents = q('select coalesce(k.key_alias,\'?\'), count(*), coalesce(sum(s.total_tokens),0), coalesce(sum(s.spend),0) '
               'from "LiteLLM_SpendLogs" s left join "LiteLLM_VerificationToken" k on k.token = s.api_key '
               "where s.\"startTime\" > now() - interval '1 day' and s.model_group <> '' group by 1 order by 2 desc")
    timers = []
    try:
        for t in json.loads(sh("systemctl", "--user", "list-timers", "--all", "--output=json") or "[]"):
            if not t.get("unit", "").startswith("launchpad"):
                timers.append({"unit": t["unit"].removesuffix(".timer"), "next": t.get("next"), "last": t.get("last")})
    except Exception:
        pass
    failed = [u for u in sh("systemctl", "--user", "list-units", "--failed", "--plain", "--no-legend").split()
              if u.endswith((".service", ".timer"))]
    services = []
    for line in sh("docker", "ps", "-a", "--filter", "label=com.docker.compose.project=aistack", "--format", "{{json .}}").splitlines():
        try:
            d = json.loads(line)
            services.append({"name": d["Names"].removeprefix("aistack-").removesuffix("-1"), "state": d["State"], "status": d["Status"]})
        except Exception:
            pass

    def jsonl(p):
        try:
            return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]
        except FileNotFoundError:
            return []
    bk = jsonl("/srv/ai/state/backups.jsonl")
    hs = sh("docker", "exec", "aistack-hindsight-db-1", "psql", "-U", "hindsight", "-d", "hindsight", "-tAc",
            "select count(*) filter (where fact_type <> 'observation'), count(*) filter (where fact_type = 'observation') "
            "from memory_units").strip().split("|")
    pending = []
    for fn in sh("docker", "exec", HERMES, "sh", "-c", "ls /opt/data/pending/memory 2>/dev/null").split()[:20]:  # cap: list (20 at a time; the next come once these are decided)
        try:
            item = json.loads(sh("docker", "exec", HERMES, "cat", f"/opt/data/pending/memory/{fn}") or "{}")
            if item.get("id"):
                pending.append({"id": item["id"], "text": ((item.get("payload") or {}).get("content") or item.get("summary", ""))})
        except Exception:
            pass
    s = spend[0] if spend else ["0", "0", "0", "0", "0"]
    _sys.update(t=time.time(), data={
        "spend_today": float(s[0]), "spend_30d": float(s[1]), "spend_total": float(s[2]), "budget_total": 10.0,
        "calls_today": int(s[3]), "tokens_today": int(s[4]),
        "agents_today": [{"agent": a.removeprefix("vk-"), "calls": int(n), "tokens": int(t), "spend": float(sp)} for a, n, t, sp in agents],
        "timers": timers, "failed": failed, "services": services,
        "backup": next((r for r in reversed(bk) if r.get("kind") == "backup"), None),
        "drill": next((r for r in reversed(bk) if r.get("kind") == "restore-drill"), None),
        "boot": (jsonl("/srv/ai/state/boots.jsonl") or [None])[-1],       # PLT-30: how the last start of the PC went
        "memory": {"facts": int(hs[0]), "observations": int(hs[1])} if len(hs) == 2 and hs[0].isdigit() else None,
        "pending_memory": pending, "email_ready": X.email_ready(), **stack_info()})
    return _sys["data"]


_stack = {"t": 0, "data": {}}
STACK_REPO = Path.home() / "ai-stack"


def guide_facts():
    """For the app's guide: pinned component versions (versions.env) and the stack's recent changes (git log)."""
    versions = []
    for ln in (STACK_REPO / "versions.env").read_text().splitlines() if (STACK_REPO / "versions.env").exists() else []:
        m = re.match(r"^([A-Z_]+)_(?:IMAGE|VERSION|MODEL)=([^@\s]+)", ln)
        if m:
            versions.append({"name": m[1].lower().replace("_", " "), "version": m[2].rsplit(":", 1)[-1] if ":" in m[2] else m[2]})
    log = sh("git", "-C", str(STACK_REPO), "log", "-30", "--no-merges", "--format=%h%x09%cI%x09%s")
    changes = [dict(zip(("sha", "ts", "subject"), x.split("\t", 2))) for x in log.splitlines() if x.count("\t") == 2]
    return {"versions": versions, "changes": changes}


def stack_info():
    """Skills, code repos and CI status for the app (every 5 minutes)."""
    if time.time() - _stack["t"] < 300:
        return _stack["data"]
    skills = sorted(p.split("/skills/")[1].rsplit("/SKILL.md", 1)[0] for p in
                    sh("docker", "exec", HERMES, "sh", "-c", "find /opt/data/skills -name SKILL.md 2>/dev/null").split())
    code = Path.home() / "code"
    repos = []
    for d in sorted(code.iterdir()) if code.exists() else []:
        if d.is_dir() and not d.name.startswith("."):
            repos.append({"name": d.name, "graph": (d / "graphify-out").exists() or (code / ".graphify").exists(),
                          "map": (Path("/srv/ai/code-docs") / f"{d.name}.md").exists()})
    ci = []
    tok = os.environ.get("FORGEJO_TOKEN") or os.environ.get("FORGEJO_STATUS_TOKEN", "")      # one token is enough
    for repo in ("ai-stack", "TestRepo", "vault", "hermes-skills"):
        try:
            req = urllib.request.Request(f"http://192.168.1.10:3000/api/v1/repos/regenzeus/{repo}/actions/tasks?limit=1",
                                         headers={"Authorization": f"token {tok}"})
            runs = json.load(urllib.request.urlopen(req, timeout=10)).get("workflow_runs") or []
            ci.append({"repo": repo, "status": runs[0]["status"] if runs else "none", "sha": runs[0]["head_sha"][:7] if runs else ""})
        except Exception:
            ci.append({"repo": repo, "status": "unknown", "sha": ""})
    _stack.update(t=time.time(), data={"skills": skills, "repos": repos, "ci": ci, **guide_facts()})
    return _stack["data"]


def recent_calls():
    rows = sh("docker", "exec", "aistack-postgres-1", "psql", "-U", "litellm", "-d", "litellm", "-tAF", "|", "-c",
              'select to_char(s."startTime" at time zone \'UTC\', \'YYYY-MM-DD"T"HH24:MI:SS"Z"\'), coalesce(k.key_alias,\'?\'), '
              's.model_group, s.total_tokens, s.spend from "LiteLLM_SpendLogs" s '
              'left join "LiteLLM_VerificationToken" k on k.token = s.api_key where s.model_group <> \'\' '
              'order by s."startTime" desc limit 25').splitlines()  # cap: list (the 25 newest model calls; LiteLLM keeps every one)
    out = []
    for r in rows:
        p = r.split("|")
        if len(p) == 5:
            out.append({"ts": p[0], "agent": p[1].removeprefix("vk-"), "model": p[2], "tokens": int(p[3] or 0), "spend": float(p[4] or 0)})
    return out


def tail(path, n=14):
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
        return [ln for ln in lines if ln.strip() and "install out of sync" not in ln][-n:]
    except FileNotFoundError:
        return []


def write_state(c, missions):
    t = now()
    out = []
    month_ago = (t - dt.timedelta(days=30)).isoformat()
    for m in missions.values():
        runs = [dict(r) for r in c.execute("select id, trigger, status, started, ended, seconds, calls, tokens, spend, models, "
                                           "summary, output, event, steps, mode from runs where slug=? order by id desc limit 20", (m["slug"],))]  # cap: list (the 20 newest runs; the run record has all)
        for r in runs:
            r["event"] = json.loads(r["event"]) if r["event"] else None
            r["steps"] = json.loads(r["steps"]) if r["steps"] else None
        st = c.execute("select count(*), sum(status='ok'), sum(status='failed'), coalesce(sum(calls),0), coalesce(sum(tokens),0), "
                       "coalesce(sum(spend),0), avg(case when status='ok' then seconds end) from runs where slug=? and started > ?",
                       (m["slug"], month_ago)).fetchone()
        allr = c.execute("select count(*), coalesce(sum(tokens),0), coalesce(sum(spend),0) from runs where slug=? and status in ('ok','failed')",
                         (m["slug"],)).fetchone()
        nd = next_due(m.get("schedule"), t) if m.get("status") == "active" else None
        item = {k: m.get(k) for k in ("slug", "title", "type", "status", "schedule", "budget_usd_month", "deliver", "created", "goal",
                                      "topic", "depth", "needs", "task", "once", "files_asked")}
        item.update(schedule_text=schedule_text(m.get("schedule")), next_run=nd.isoformat() if nd else None, runs=runs,
                    triggers=[{**tr, "text": X.trigger_text(tr)} for tr in m.get("triggers") or []], wiki=X.wiki_root(m),
                    stats={"runs": st[0], "ok": st[1] or 0, "failed": st[2] or 0, "calls": st[3], "tokens": st[4],
                           "spend": round(st[5], 5), "avg_seconds": round(st[6] or 0), "runs_all": allr[0],
                           "tokens_all": allr[1], "spend_all": round(allr[2], 5)})
        root = VAULT / item["wiki"]
        item["wiki_pages"] = len([p for p in root.rglob("*.md") if p.name != "index.md"]) if root.exists() else 0
        if m.get("type") == "briefing":
            (meta, body), _ = topic_of(m)
            src = meta.get("sources") or {}
            item["brief"] = {"mission": meta.get("mission"), "key_questions": meta.get("key_questions", []),
                             "watchlist": meta.get("watchlist", []), "search": src.get("search", []),
                             "feeds": src.get("feeds", []), "filings": src.get("filings", []), "notes": body}
            tdir = VAULT / "topics" / m.get("topic", m["slug"])
            outs = sorted([*(tdir / "reports").rglob("*.md"), *(tdir / "alerts").rglob("*.md")], key=lambda p: p.name)
            item["outputs"] = [str(p.relative_to(VAULT)) for p in outs[-40:]][::-1]  # cap: list
            item["mail"], item["mail_total"] = topic_mail(tdir)
        else:
            logs = sorted((MISSIONS / m["slug"] / "log").rglob("*.md"))
            item["outputs"] = [str(p.relative_to(VAULT)) for p in logs[-30:]][::-1]  # cap: list (the 30 newest results; the vault has all)
            item["notes"] = J.state_text(f"mission:{m['slug']}") or (read_notes(m) if (MISSIONS / m["slug"] / "NOTES.md").exists() else "")
        out.append(item)
    order = {"active": 0, "paused": 1, "archived": 2}
    out.sort(key=lambda x: (order.get(x["status"], 3), x["title"].lower()))
    with lock:
        run = dict(running)
    if run:
        lp = run["log"] if run.get("type") == "task" or run.get("mode") in ("alert", "deep") else \
            f"/srv/ai/desk/{missions.get(run['slug'], {}).get('topic', run['slug'])}/last.log"
        run["tail"] = tail(lp)          # cap: list: the live view's last lines; the run page has the whole log
        r = c.execute("select steps from runs where id=?", (run["id"],)).fetchone()
        run["steps"] = json.loads(r["steps"]) if r and r["steps"] else None
    queue = [dict(r) for r in c.execute("select slug, trigger, started, status, retry_at from runs where status in ('queued','waiting') order by id")]
    with lock:                                     # parked runs: started, waiting for something slow, slot given away
        queue += [{"slug": p.get("slug"), "trigger": p.get("trigger"), "started": p.get("started"), "status": "parked",
                   "waiting_for": p.get("waiting_for"), "since": p.get("since")} for p in parked.values()]
    _queue_cache[:] = queue
    try:
        health = CR.health(c, out)                 # the Agent health board (ops/crew.py, ops/observe.py)
    except Exception as e:
        log(f"health: {type(e).__name__}: {e}")
        health = {}
    try:
        since = (now() - dt.timedelta(days=EVENT_DAYS)).isoformat(timespec="seconds")
        ev = [e for e in (json.loads(ln) for ln in (PUBLIC / "events.jsonl").read_text().splitlines()[-EVENTS:]) if e.get("ts", "") >= since][::-1]  # cap: list (Home's feed: three days, at most EVENTS)
    except FileNotFoundError:
        ev = []
    state = {"generated": t.isoformat(timespec="seconds"), "missions": out, "running": run or None, "queue": queue,
             "activity": ev, "calls": recent_calls(), "system": system_info(), "resources": RES, **B.state(c), **I.state(c), **R.state(), **CT.state(c), **CR.state(), **SH.state(), **H.state(), **SW.state(), **MEM.state(CR.status()), **N.state(), **TK.state(c), **EV.state(c), **ST.state(c), **FL.state(), "health": health,
             "prices": PR.load().get("models", {}), **A2.state()}                  # TSK-27: the app prices tokens with the same table
    try:
        state.update(DQ.state(state))
    except Exception as e:
        log(f"decisions: {type(e).__name__}: {e}")
    tmp = PUBLIC / "state.json.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False, default=str))
    tmp.replace(PUBLIC / "state.json")


RES = {}
_queue_cache = []


def _cpu_times():
    v = [int(x) for x in open("/proc/stat").readline().split()[1:]]
    return sum(v), v[3] + v[4]


def resmon():
    """Resource use every 20 s: per stack service (docker stats), the WSL VM, and Windows (written by host-probe.ps1)."""
    last = _cpu_times()
    while not stop.is_set():
        try:
            svcs = []
            for line in sh("docker", "stats", "--no-stream", "--format", "{{json .}}", timeout=60).splitlines():
                d = json.loads(line)
                if not d["Name"].startswith("aistack-"):
                    continue
                used, lim = (x.strip() for x in d["MemUsage"].split("/"))
                svcs.append({"name": d["Name"].removeprefix("aistack-").removesuffix("-1"), "cpu": float(d["CPUPerc"].rstrip("%") or 0),
                             "mem_mb": _mb(used), "limit_mb": _mb(lim)})
            mi = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if l.split(":")[0] in ("MemTotal", "MemAvailable")}
            t = _cpu_times()
            busy = 1 - (t[1] - last[1]) / max(t[0] - last[0], 1)
            last = t
            disk = os.statvfs("/")
            host = None
            hp = Path("/srv/win-exports/.host/host.json")
            if hp.exists() and time.time() - hp.stat().st_mtime < 180:
                host = json.loads(hp.read_text(encoding="utf-8-sig"))
            RES.update(services=sorted(svcs, key=lambda x: -x["mem_mb"]), ts=now().isoformat(timespec="seconds"), host=host,
                       wsl={"mem_total_gb": round(mi["MemTotal"] / 1048576, 2), "mem_used_gb": round((mi["MemTotal"] - mi["MemAvailable"]) / 1048576, 2),
                            "cpu_pct": round(busy * 100), "cores": os.cpu_count(),
                            "disk_free_gb": round(disk.f_bavail * disk.f_frsize / 1e9), "disk_total_gb": round(disk.f_blocks * disk.f_frsize / 1e9)})
        except Exception:
            log(traceback.format_exc())
        stop.wait(20)


def _mb(v):
    m = re.match(r"([\d.]+)\s*([KMGT]?i?B)", v)
    if not m:
        return 0
    return round(float(m[1]) * {"B": 1 / 1048576, "KiB": 1 / 1024, "MiB": 1, "GiB": 1024, "TiB": 1048576, "kB": 1 / 1000,
                                "MB": 1, "GB": 1000}.get(m[2], 1))


PHONE_PENDING, PHONE_DONE = Path("/srv/ai/phone/pending"), Path("/srv/ai/phone/done")
CONN_PENDING = Path("/srv/ai/connections/pending")        # app connections (images/mail): first-Trash approvals
CONN_SCOPES = {"gmail:read", "gmail:organize", "gmail:trash"}


def phone_watch():
    """The AI phone's approval requests also go to Telegram: a browser can silently drop the app's push (Chrome
    revokes it as "spam"), and an unseen request just expires after 3 minutes."""
    seen = set()
    while not stop.is_set():
        try:
            for f in PHONE_PENDING.glob("*.json") if PHONE_PENDING.exists() else []:
                if f.stem not in seen:
                    seen.add(f.stem)
                    p = json.loads(f.read_text())
                    go = f"{X.APP}/#/phone?id={p['id']}&do="       # one tap: the app opens and records the answer
                    first = [("✅ Allow this job" if p.get("tool") == "phone_task" else "✅ Allow", go + "allow")]      # such an OK opens no time window
                    X.telegram(f"📱 <b>AI phone: OK?</b>\n{html.escape(p.get('text', ''))}\n<i>{html.escape(p.get('why', ''))}</i>\n"
                               f"(waits 15 min)", [first, [("❌ Decline", go + "deny"), ("🔍 Look first", f"{X.APP}/#/phone")]], category="approval")
            for f in CONN_PENDING.glob("*.json") if CONN_PENDING.exists() else []:
                if f.stem not in seen:
                    seen.add(f.stem)
                    p = json.loads(f.read_text())
                    sample = "\n".join("· " + html.escape(x) for x in p.get("sample", [])[:8])  # cap: top
                    X.telegram(f"📧 <b>Gmail: move {p.get('count')} mails to Trash?</b>\n<i>{html.escape(p.get('reason', ''))}</i>\n{sample}\n"
                               "(Trash only, undo possible; waits 15 min)", [[("🔍 Review", f"{X.APP}/#/system?conn=1")]], category="approval")
            for f in sorted(PHONE_DONE.glob("*.json")) if PHONE_DONE.exists() else []:     # a finished phone task
                d = json.loads(f.read_text())
                X.telegram(f"📱 <b>AI phone: done</b>\n{html.escape(d.get('summary', ''))}", [[("Phone page", f"{X.APP}/#/phone")]], category="result")
                f.unlink(missing_ok=True)
        except Exception:
            log(traceback.format_exc())
        stop.wait(2)


def watcher():
    c = db()
    while not stop.is_set():
        try:
            X.check_events(load_missions(), c)
        except Exception:
            log(traceback.format_exc())
        try:
            O.tick()                       # BLD-26: an onboarding job that should run and does not goes on where it stopped
        except Exception:
            log(traceback.format_exc())
        try:
            SH.tick(c)                     # shopping: price readings of waiting proposals, following bought orders
        except Exception:
            log(traceback.format_exc())
        stop.wait(60)


def main():
    X.M = B.M = I.M = R.M = SH.M = CL.M = T.M = CT.M = CR.M = J.M = W.M = H.M = TK.M = CD.M = EV.M = ST.M = PV.M = HI.M = A2.M = PN.M = FL.M = WD.M = sys.modules[__name__]
    CT.B = B
    CR.I = I
    I.B = R.B = B
    os.umask(0)                         # vault convention: folders 777, files 666, so every agent container can write
    for d in (INBOX, PUBLIC, RUNLOGS, MISSIONS):
        d.mkdir(parents=True, exist_ok=True)
    INBOX.chmod(0o777)                  # the app container (another uid) drops requests here; only this runner reads them
    c = db()
    requeue_interrupted(c)
    if "--once" in sys.argv:
        write_state(c, load_missions())
        return
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    log("mission runner: waiting for the stack")
    if not G.wait(G.START_WAIT_S, stop=stop):       # PLT-28: nothing starts against a stack that is still coming up
        log(f"mission runner: starting without the stack: {G.why_down()}")
    threading.Thread(target=stack_watch, daemon=True, name="stack-watch").start()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()
    threading.Thread(target=W.worker, daemon=True, name="wiki-summaries").start()
    threading.Thread(target=H.worker, daemon=True, name="house").start()           # Home Assistant status + the Echo bridge
    threading.Thread(target=phone_watch, daemon=True).start()
    threading.Thread(target=resmon, daemon=True).start()
    threading.Thread(target=B.worker, daemon=True).start()
    threading.Thread(target=CT.worker, daemon=True).start()
    threading.Thread(target=WD.worker, daemon=True).start()
    threading.Thread(target=RTM.forwarder, args=(stop,), daemon=True).start()     # the sandboxes' runtime spools
    threading.Thread(target=T.worker, daemon=True).start()
    threading.Thread(target=I.worker, daemon=True).start()
    threading.Thread(target=TK.worker, daemon=True, name="task-intake").start()   # tasks given in a sentence (TSK-03)
    threading.Thread(target=CD.worker, daemon=True, name="conductor").start()      # plan graphs, step by step (TSK-05)
    threading.Thread(target=EV.worker, daemon=True, name="event-bus").start()      # events, rules, breaking news (TSK-10)
    HI.start()                                                                      # the telemetry history, hourly (TSK-25)
    PN.start()                                                                      # growing files pruned, daily (PLT-21)
    FL.start()                                                                      # mission files: retention and quota, daily (MIS-26)
    threading.Thread(target=ST.worker, daemon=True, name="staffing").start()       # judged tasks, measured agents (TSK-17)
    log("mission runner started")
    last_state = last_cost = 0
    while not stop.is_set():
        try:
            process_inbox()
            missions = load_missions()
            check_schedules(missions, c)
            if time.time() - last_cost > 30:
                refresh_costs(c, missions)
                N.flush()                          # after quiet hours: what was held goes out as one message
                TK.sync(c, missions)               # every door's work is a task; each task follows its door
                last_cost = time.time()
            if time.time() - last_state > 4:
                write_state(c, missions)
                last_state = time.time()
        except Exception:
            log(traceback.format_exc())
        stop.wait(2)


if __name__ == "__main__":
    main()
