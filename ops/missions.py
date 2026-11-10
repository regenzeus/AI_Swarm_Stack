"""Mission Control runner (host side): the one place that starts mission runs.

Missions are files in the vault, missions/<slug>/MISSION.md (YAML front matter + goal text):
  type      briefing (Topic Desk, topics/<slug>/TOPIC.md) | task (a long-term agent mission, Hermes profile "mission")
  status    active | paused | archived
  schedule  daily HH:MM | weekdays HH:MM | weekly mon,thu HH:MM | every Nh | manual (on demand only); the mission's task
            gets an n8n workflow with that schedule, and n8n starts its runs (WFL-09, ops/n8n_jobs.py)
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
import datetime as dt, fcntl, html, json, os, re, signal, sqlite3, subprocess, sys, threading, time, traceback, unicodedata
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
import diskguard as DG                             # PLT-36: C: low, the build cache goes and the owner hears
import prices as PR                               # TSK-27: tokens at list price
import deployment as DEPLOY                        # this deployment's hosts and paths (deployments/<name>/deployment.env)
import a2a as A2                                  # TSK-19: outside agents over A2A, off until the owner switches it on
from textcap import limit, limit_items, tail as tailcut                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md
import windows_desk as WD                         # PLT-31: asking Windows, through a folder it fetches from
import changes as CHG                             # CHG-01: change requests
import repowiki as RW                             # CHG-08: one wiki per repository
import onboard as O                        # onboarding a repository: the whole package (BLD-26)
import files as FL                                # MIS-23: the files a mission was asked to make (docs/DELIVERABLES.md)
import decisions as DQ                            # AUT-05: everything that waits for the owner, one ranked list, and its shadow
import memstack as MS                             # MEM-22 to MEM-34: the memory stack (catalogue, openings, the memory tools)
import memwrite as MW                             # MEM-35 to MEM-37: what enters memory, and how
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
# limit: stops, one mission run past this counts as failed
TASK_TIMEOUT = 40 * 60
RETRY_MIN, MAX_WAITS = 30, 16           # subscription only: a paused run retries every 30 min, for up to 8 hours
DOWN_RETRY_MIN = 5                      # a run the stack went away under (PLT-28): it holds the queue until the stack is back
STACK_GONE = re.compile(r"Cannot connect to the Docker daemon|Container \S+ is (?:paused|restarting|not running)|No such container", re.I)
# A usage limit as the gateway and the engines report it (review RUN-R3: "quota", "cooldown" or "usage limit" in what a run
# wrote made a finished build wait and run again up to 12 times, and missions retry a real failure for 8 hours).
PAUSED = re.compile(r"usage_limit_reached|the usage limit has been reached|RateLimitError|rate_limit_error|insufficient_quota|"
                    r"\b(?:HTTP|Error|status)(?: Error| code)?:? ?429\b|\b429 Too Many Requests|No deployments available for selected model|"
                    r"deployments for selected model are in cooldown|Claude AI usage limit reached|you'?ve hit your (?:usage )?limit", re.I)


def paused(text):
    """True when a run failed because ChatGPT paused the stack (usage limit), not because of a real error."""
    return bool(PAUSED.search(text or ""))
os.environ.setdefault("DOCKER_HOST", DEPLOY.DOCKER_SOCKET)

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


LOCKS_SEEN = []                  # when this runner's writes failed on a lock (the last few)
LOCK_BURST = 3                   # this many failures within LOCK_WINDOW_S: the runner writes down who holds what
LOCK_WINDOW_S = 600
STACKS_EVERY_S = 3600            # limit: drops, at most one stack dump an hour (a diagnosis, never a stop)
_stacks_at = [0.0]
_conns = None                    # every open Robust connection: which thread opened it, and where


class Robust(sqlite3.Connection):
    """A connection that gives up its transaction when a write fails on a lock. Overnight 8 Nov 2026: a commit that failed
    with "database is locked" (a reader had held the file) left its write transaction open; the thread went on with the
    same connection, so every other writer in the runner failed for 40 minutes, until a restart. The caller still gets the
    error; the half-done unit is dropped instead of holding the lock. Overnight 9 Nov 2026 the lock came back from inside
    the runner, holder unknown: a burst of failures now writes every thread's stack and every connection that is in a
    transaction, with where it was opened, once an hour at most (lock_stacks)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        global _conns
        if _conns is None:
            import weakref
            _conns = weakref.WeakSet()
        self.opened_by = threading.current_thread().name
        self.opened_at = "".join(traceback.format_stack(limit=8)[:-1])
        _conns.add(self)

    def _give_up(self, e):
        if "locked" in str(e) or "busy" in str(e):
            try:
                self.rollback()
            except sqlite3.Error:
                pass
            try:
                lock_seen()
            except Exception as d:               # a diagnosis never breaks the write's own error
                log(f"the lock diagnosis failed: {type(d).__name__}: {d}")

    def execute(self, *a, **k):
        try:
            return super().execute(*a, **k)
        except sqlite3.OperationalError as e:
            self._give_up(e)
            raise

    def executemany(self, *a, **k):
        try:
            return super().executemany(*a, **k)
        except sqlite3.OperationalError as e:
            self._give_up(e)
            raise

    def commit(self):
        try:
            return super().commit()
        except sqlite3.OperationalError as e:
            self._give_up(e)
            raise


def lock_seen(now=None):
    """One write failed on a lock; a burst of them writes lock_stacks() once (at most once an hour)."""
    now = now or time.time()
    LOCKS_SEEN.append(now)
    del LOCKS_SEEN[:-LOCK_BURST]  # cap: rotate (the last few failures are enough to see a burst)
    if len(LOCKS_SEEN) >= LOCK_BURST and now - LOCKS_SEEN[0] <= LOCK_WINDOW_S and now - _stacks_at[0] >= STACKS_EVERY_S:
        _stacks_at[0] = now
        f = lock_stacks()
        log(f"database locked {LOCK_BURST} times in {LOCK_WINDOW_S // 60} min: who held what is in {f}")


def lock_stacks(folder=None):
    """Every thread's stack, and every open connection in a transaction with the thread and code that opened it, to a file.
    -> its path."""
    import faulthandler
    folder = Path(folder or Path(DB).parent / "lock-stacks")
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{time.strftime('%Y%m%d-%H%M%S')}.txt"
    with f.open("w") as out:
        out.write("Connections in a transaction:\n")
        for c in list(_conns or []):
            try:
                busy = c.in_transaction
            except sqlite3.ProgrammingError:     # closed
                continue
            if busy:
                out.write(f"\n- opened by thread {c.opened_by}, at:\n{c.opened_at}")
        out.write("\nEvery thread:\n")
        out.flush()
        faulthandler.dump_traceback(file=out, all_threads=True)
    return f


def db():
    c = sqlite3.connect(DB, timeout=30, factory=Robust)
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



def _part(name):
    """PLT-25: a part of this file kept in its own file (<this file's stem>.<part>.py), run here, in this module's namespace,
    where it stood: one namespace as before, so names, patches and tracebacks hold. Not a module of its own."""
    p = Path(__file__).with_name(name)
    exec(compile(p.read_text(), str(p), "exec"), globals())   # nosemgrep: python-eval-exec -- this module's own part file beside it (PLT-25), never data


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


def move_old_notes():
    """MEM-05's move, finished: each old NOTES.md left (its mission never ran again: archived, or on demand) goes into its
    journal's working state now, in the journal's own commit. A journal that has a working state already keeps it, and
    the old file stays, said in the log. -> [slugs moved]."""
    moved = []
    for p in sorted(MISSIONS.glob("*/NOTES.md")):
        agent = f"mission:{p.parent.name}"
        try:
            if J.state_text(agent):
                log(f"notes: {p.parent.name} has a working state in its journal already; its old NOTES.md stays")
                continue
            text = p.read_text(errors="replace")
            p.unlink()
            J.set_state(agent, text, p.parent.name, [f"missions/{p.parent.name}/NOTES.md"])
            moved.append(p.parent.name)
        except Exception as e:                     # one that fails stays where it is and says why; the runner goes on
            log(f"notes: {p.parent.name}: not moved ({type(e).__name__}: {e})")
    if moved:
        log(f"notes: moved into their journals: {', '.join(moved)}")
    return moved


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
        err = TC.tail((p.stderr or "").strip(), 2000) if p.returncode else ""   # cap: store (the whole is in Hermes' own log)
        RTM.stage("Hermes (mission profile) finished", f"{len(p.stdout)} characters back" + (f", exit {p.returncode}: {err}" if p.returncode else ""),
                  int((time.time() - t0) * 1000), status="failure" if p.returncode else None)
        if not p.returncode:
            P.case(src, p.stdout)                        # a replay case for a later change of this prompt
        if p.returncode and not p.stdout.strip():        # review RUN-R25: a restart that cut the run off said why only on stderr,
            return f"(no answer: Hermes exited {p.returncode}) {err}"   # so it was "failed: no answer" instead of waiting for the stack
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


_bad = set()


def bad_mission(m, e):
    """A mission whose file cannot be read as a mission: logged, and said to the owner once per mission and error."""
    key = (m.get("slug"), f"{type(e).__name__}: {e}")
    log(f"mission {m.get('slug')}: its MISSION.md cannot be used: {key[1]}")
    if key not in _bad:
        _bad.add(key)
        try:
            event("mission", m.get("slug") or "", f"{m.get('slug')}: its MISSION.md cannot be used ({key[1]}); fix the file, the other missions go on",
                  push=True, title="Missions")
        except Exception:
            pass


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
def stop_briefing(p, topic, f):
    """The briefing's deadline (TASK_TIMEOUT): its pipeline, and the desk container it started, are stopped."""
    try:
        f.write(f"stopped: the briefing pipeline ran past {TASK_TIMEOUT // 60} minutes\n")
        f.flush()
        os.killpg(p.pid, 9)
    except (OSError, ValueError):
        pass
    try:
        ids = subprocess.run(["docker", "ps", "-q", "--filter", f"name=^desk-{topic}-"], capture_output=True, text=True, timeout=30).stdout.split()
        if ids:
            subprocess.run(["docker", "kill", *ids], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        log(f"briefing {topic}: its desk container could not be stopped ({type(e).__name__}: {e})")
    log(f"briefing {topic}: stopped at its deadline of {TASK_TIMEOUT // 60} minutes")


def run_briefing(m, logf):
    topic = m.get("topic", m["slug"])
    env = dict(os.environ, DESK_TELEGRAM="0")          # delivery (with buttons) happens below
    RTM.stage("Briefing pipeline starts", f"desk.sh {topic}: feeds, prices and filings, then the model writes the briefing")
    t0, n = time.time(), 0
    with open(logf, "w") as f:
        p = subprocess.Popen(["bash", str(OPS / "desk.sh"), topic], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
                             start_new_session=True)
        late = threading.Timer(TASK_TIMEOUT, stop_briefing, args=(p, topic, f))   # review RUN-R16: `for ln in p.stdout` waits for
        late.daemon = True                                                         # the end of a pipeline that may never end
        late.start()
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
        finally:
            late.cancel()
    RTM.stage("Briefing pipeline finished", f"exit {p.returncode}", int((time.time() - t0) * 1000), status="failure" if p.returncode else None)
    out = Path(logf).read_text()
    # desk.sh says "... NOT filed: <path>" when the vault refused the report and exits 0 (review RUN-R5): that is no briefing
    refused = re.search(r"NOT filed: \S+", out)
    filed = re.search(r"(?<!NOT )filed: (\S+)", out)
    if p.returncode or refused or not filed or not (VAULT / filed.group(1)).is_file():
        if refused:
            return "failed", f"the briefing was written but could not be filed into the vault ({refused.group(0)})", ""
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
    event("run_started", m["slug"], {"n8n": "Scheduled run started (its n8n workflow)", "event": f"Event run started: {(ev or {}).get('trigger', '')}"}
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
                q = ("select * from runs where (status='queued' or (status='waiting' and julianday(retry_at) <= julianday(?)))"  # a time, not a string (RUN-R29)
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


_part("missions.requests.py")   # the requests from the app and the chat (PLT-25)


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
STACK_REPO = Path(DEPLOY.STACK_DIR)


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
    code = Path(DEPLOY.CODE_DIR)
    repos = []
    for d in sorted(code.iterdir()) if code.exists() else []:
        if d.is_dir() and not d.name.startswith("."):
            repos.append({"name": d.name, "graph": (d / "graphify-out").exists() or (code / ".graphify").exists(),
                          "map": (Path("/srv/ai/code-docs") / f"{d.name}.md").exists()})
    ci = []
    tok = os.environ.get("FORGEJO_TOKEN") or os.environ.get("FORGEJO_STATUS_TOKEN", "")      # one token is enough
    for repo in ("ai-stack", "TestRepo", "vault", "hermes-skills"):
        try:
            req = urllib.request.Request(f"{B.FORGEJO}/repos/{DEPLOY.FORGEJO_OWNER}/{repo}/actions/tasks?limit=1",
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
    import n8n_jobs as NJ
    t = now()
    out = []
    month_ago = (t - dt.timedelta(days=30)).isoformat()
    TK.table(c)
    tasks_of = {r[0]: r[1] for r in c.execute("select ref, id from tasks where door='mission'")}
    when = NJ.index()                                  # WFL-09: a mission's runs on a schedule come from its task's workflow
    for m in missions.values():
        try:
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
            tid = tasks_of.get(m["slug"]) or m.get("task")       # a moved briefing's or price watch's: its task's
            nd = NJ.next_run("task", tid, now=t, idx=when) if tid and m.get("status") == "active" else None
            said = NJ.schedule("task", tid, idx=when) if tid else None
            item = {k: m.get(k) for k in ("slug", "title", "type", "status", "schedule", "budget_usd_month", "deliver", "created", "goal",
                                          "topic", "depth", "needs", "task", "once", "files_asked")}
            item.update(schedule_text=said[:1].upper() + said[1:] if said else schedule_text(m.get("schedule")), next_run=nd, runs=runs,
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
        except Exception as e:                 # RUN-R15: it is left out of the app's state, said once; the others are shown
            bad_mission(m, e)
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
                DG.check(host, sh, notify)              # PLT-36: C: holds WSL's disk; low, the build cache goes
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


def single_runner(path):
    """The runner's lock, held while it runs (review RUN-R26: a second runner would run every queued run and build twice).
    -> the open lock file; another runner holding it ends this one."""
    f = open(path, "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log(f"mission runner: another runner holds {path.name}; this one stops")
        sys.exit(1)
    return f


def main():
    CHG.M = RW.M = MS.M = MW.M = sys.modules[__name__]
    X.M = B.M = I.M = R.M = SH.M = CL.M = T.M = CT.M = CR.M = J.M = W.M = H.M = TK.M = CD.M = EV.M = ST.M = PV.M = HI.M = A2.M = PN.M = FL.M = WD.M = sys.modules[__name__]
    for domain in CD.DOMAINS:                      # TSK-36: the modules whose steps the Conductor runs
        domain.M = sys.modules[__name__]
    CT.B = B
    CR.I = I
    I.B = R.B = B
    os.umask(0)                         # vault convention: folders 777, files 666, so every agent container can write
    for d in (INBOX, PUBLIC, RUNLOGS, MISSIONS):
        d.mkdir(parents=True, exist_ok=True)
    INBOX.chmod(0o777)                  # the app container (another uid) drops requests here; only this runner reads them
    c = db()
    if "--once" in sys.argv:                       # review RUN-R26: before, it requeued the live service's running runs as cut off
        write_state(c, load_missions())
        return
    global _single
    _single = single_runner(HOME / "runner.lock")
    requeue_interrupted(c)
    move_old_notes()
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
    import flows as FW                                                             # WFL-05: the steps n8n starts
    FW.start(sys.modules[__name__])
    import flows_view as FV                                                        # WFL-11: each workflow's runs, for the app's pages
    FV.start(sys.modules[__name__])
    threading.Thread(target=CD.worker, daemon=True, name="conductor").start()      # plan graphs, step by step (TSK-05)
    threading.Thread(target=EV.worker, daemon=True, name="event-bus").start()      # events, rules, breaking news (TSK-10)
    HI.start()                                                                      # the telemetry history, hourly (TSK-25)
    PN.start()                                                                      # growing files pruned, daily (PLT-21)
    FL.start()                                                                      # mission files: retention and quota, daily (MIS-26)
    threading.Thread(target=ST.worker, daemon=True, name="staffing").start()       # judged tasks, measured agents (TSK-17)
    log("mission runner started")
    last_state = last_cost = 0
    while not stop.is_set():
        missions = {}
        for part in ("inbox", "costs", "state"):   # RUN-R15: one part that fails stops none of the others
            try:
                if part == "inbox":
                    process_inbox()
                    missions = load_missions()
                elif part == "costs" and time.time() - last_cost > 30:
                    last_cost = time.time()
                    refresh_costs(c, missions)
                    N.flush()                          # after quiet hours: what was held goes out as one message
                    TK.sync(c, missions)               # every door's work is a task; each task follows its door
                    TK.conduct_all(c, missions)        # TSK-21: one engine for repeating tasks
                    if TK.alerts_to_tasks(c, missions):   # ... and for a briefing's alerts
                        missions = load_missions()
                elif part == "state" and time.time() - last_state > 4:
                    last_state = time.time()
                    write_state(c, missions)
            except Exception:
                log(traceback.format_exc())
        stop.wait(2)


if __name__ == "__main__":
    main()
