"""Asks: everything that waits for a person, one durable kind of question (ASK-01..ASK-08, docs/ASKS.md).

The stack acts within its policy and asks by exception: a human on the loop, not in it. Every kind of Ask is registered
once by its source (register(): its outcomes and values, the action kind its tier comes from, gate, role, default,
wording), and every Ask lives in its own SQLite store under /srv/ai/asks (asks.db, WAL, each write committed whole), so
an Ask and its answer survive the runner, the app and n8n restarting. The runner owns the store; the app reads what the
runner publishes (state.json "asks") and drops answers into the runner's inbox, where they wait while the runner is
down and are applied once: an answer is kept by its answer id, and the same id again changes nothing.

Tiers (config/policy.yaml, a deployment's policy.yaml, the owner's standing rules in rules.json): do and tell act with an
undo record, ask asks, never refuses. A gate (gate: true) always asks, and only an explicit tap on a chip by a person
who holds its role resolves it: no tier, standing rule, default, interpreter, group answer or deadline ever does. Words
at a gate are kept as a comment.

An answer is held for HOLD_S with a one-tap undo before the stack acts on it (tick()); the card shows it at once.
A default applies at its deadline and is recorded as such; a gate's deadline reminds, then escalates to the next in its
role's escalation order and the owner last, and never proceeds. Dismiss and Later work on every Ask.

    register(kind, ...)              a source's kind of Ask, once
    open_ask(spec) -> ask            idempotent by its source key; refused by the data rule or a never tier
    answer / dismiss / later / undo / group_answer       the answer paths, each idempotent by answer id
    tick(now, apply, notify)         held answers applied, snoozes woken, defaults, gate reminders and escalation
    rules / rule_save / rule_delete  the owner's standing rules (never for a gate)
    stop_set / stopped               the stop switch: every agent, workflow and crew job holds
    published()                      what state.json carries for the app

    python3 ops/asks.py list | rules | stop
"""
import calendar
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

import yaml

import statefile as SF
import textcap as TC

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config/policy.yaml"
TIERS = ("do", "tell", "ask", "never")
STATUSES = ("open", "answered", "dismissed", "snoozed", "expired", "escalated")
WAITING = ("open", "escalated", "snoozed")             # an Ask a person may still answer
SHOWN = ("open", "escalated")                          # what Needs you shows
VIAS = ("app", "telegram", "ticket", "mail", "cli", "mcp")   # a person's channels, the command line and the agents' stack tools
NOT_GATE_VIAS = ("cli", "mcp")                         # WAY-07: they never answer, dismiss or put off a gate
CHANNELS = ("app", "ticket", "telegram", "mail")
GATE_VIAS = ("app", "transition")                      # a gate's chip: in the app, or the tracker's own mapped transition
SENSITIVITY = ("normal", "private")
HOLD_S = 15             # limit: waits, an answer waits 15 s for its one-tap undo before the stack acts on it
QUESTION_MAX = 500      # limit: refuses, a question is one sentence that fits a card
WHY_MAX = 1000          # limit: refuses, why it matters is a short line
WORDS_MAX = 4000        # limit: refuses, an answer in words is a few sentences
FACTS_MAX = 12          # limit: refuses, an Ask carries its key facts; the rest stays on its source
CHOICES_MAX = 6         # limit: refuses, chips that fit a phone's card
LABEL_MAX = 60          # limit: refuses, a chip's label
ESCALATE_H = 24         # limit: waits, a gate reminded at its deadline goes to the next person in its role 24 h later
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")
ANSWER_ID = re.compile(r"[A-Za-z0-9_-]{8,64}")
STACK = "the stack"     # who answered when the policy, a standing rule or a default did
_lock = threading.RLock()
TYPES = {}
APPLY = {}              # kind -> fn(ask, answer) -> a sentence: what the answer did (the default runs the chip's act)
DISPATCH = [None]       # fn(request) -> result: the runner's own request handler (ops/missions.requests.py dispatch)


# ---------------------------------------------------------------- where it lives
def home():
    return Path(os.environ.get("ASKS_DIR", "/srv/ai/asks"))


def db_path():
    return home() / "asks.db"


SCHEMA = """
  create table if not exists asks(id text primary key, source text unique not null, kind text not null, status text not null,
    created real, updated real, deadline real, wake real, doc text not null);
  create table if not exists answers(answer_id text primary key, ask_id text not null, at real, state text not null, doc text not null);
  create table if not exists history(n integer primary key autoincrement, ask_id text not null, at real, event text, doc text);
  create table if not exists undo(id text primary key, at real, until real, state text not null, doc text not null);
  create index if not exists asks_status on asks(status);
  create index if not exists answers_ask on answers(ask_id);
"""
_local = threading.local()                             # this thread's connection per store (ASK-21)
_made = set()                                          # the stores whose file, WAL mode and tables are set up
_init = threading.Lock()


def connect():
    """This thread's one connection to the store (ASK-21): a connection is never shared between threads (sqlite3's own
    check stays on) and never made per call. On 11 Nov 2026 the runner died twice with SIGSEGV during the first sync,
    while several threads each opened a fresh connection per call, every one switching the journal mode and running the
    schema on a database that was still being made; now the file, its WAL mode and its tables are set up once per
    process, under a lock, and each thread keeps one plain connection. Writes run under the module's lock as before."""
    p = str(db_path())
    conns = getattr(_local, "conns", None)
    if conns is None:
        conns = _local.conns = {}
    c = conns.get(p)
    if c is not None:
        return c
    with _init:
        if p not in _made or not Path(p).exists():
            home().mkdir(parents=True, exist_ok=True)
            s = sqlite3.connect(p, timeout=10, isolation_level=None)   # limit: waits, a write waits up to 10 s for another
            try:
                s.execute("pragma journal_mode=wal")
                s.executescript(SCHEMA)
            finally:
                s.close()
            _made.add(p)
    c = sqlite3.connect(p, timeout=10, isolation_level=None)       # limit: waits, a write waits up to 10 s for another
    c.row_factory = sqlite3.Row
    c.execute("pragma synchronous=full")                          # a commit survives the runner being killed
    conns[p] = c
    return c


def now_():
    return time.time()


def ask_id(source):
    """An Ask's id from its source key, so the app and the runner name the same Ask without asking each other."""
    return hashlib.sha1(str(source).encode()).hexdigest()[:16]   # cap: id


# ---------------------------------------------------------------- types
def register(kind, title, *, action, outcomes=(("yes", "Yes"), ("no", "No")), values=None, gate=False, role="owner",
             default=None, words=True, own_choices=False, does=None, group=True, template=""):
    """A source's kind of Ask, once: its outcomes (id, label), the values an answer may carry ({name: number|text|date|
    yes-no}), the action kind its tier comes from (config/policy.yaml), whether it is a gate, its role, its default
    ({outcome, after_h} or None), whether words are taken, whether an Ask may bring its own chips, which outcome is the
    "do it" one a do or tell tier takes, whether Asks of it fold into one card, and its wording template."""
    if not ID.fullmatch(kind):
        raise ValueError(f"an Ask's kind is a short name, not {kind!r}")
    if gate and default:
        raise ValueError(f"{kind}: a gate has no default; at its deadline it reminds and escalates")
    outs = [{"id": o, "label": label} for o, label in outcomes]
    if default and default.get("outcome") not in {o["id"] for o in outs}:
        raise ValueError(f"{kind}: its default must be one of its outcomes")
    TYPES[kind] = {"kind": kind, "title": title, "action": action, "outcomes": outs, "values": dict(values or {}), "gate": bool(gate),
                   "role": role or "owner", "default": default, "words": bool(words) and not gate, "own_choices": own_choices,
                   "does": does if does is not None else (outs[0]["id"] if outs else None), "group": bool(group) and not gate,
                   "template": template}
    return TYPES[kind]


def register_workflow_kinds():
    """A workflow's question with its own chips, and a record's gated status (ASK-19, ASK-20)."""
    if "workflow" not in TYPES:
        register("workflow", "A workflow asks", action="workflow", outcomes=(), own_choices=True)
    if "record-gate" not in TYPES:
        register("record-gate", "A record's status", action="tracker-write", outcomes=(("approve", "Approve"), ("reject", "Not now")), gate=True)


def type_of(kind):
    t = TYPES.get(kind)
    if not t:
        raise ValueError(f"no kind of Ask {kind!r} is registered")
    return t


# ---------------------------------------------------------------- policy, channels, the data rule
def _deployment_folder():
    try:
        import deployment as DEPLOY
        return DEPLOY.chosen()
    except (ImportError, SystemExit, OSError):
        return None


def _yaml(p):
    try:
        return yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
    except OSError:
        return {}


def policy(folder=None):
    """The stack's policy with the deployment's on top: tiers and the data rule merge key by key, channels and tickets
    are the deployment's when it names them."""
    base = _yaml(POLICY)
    folder = folder or _deployment_folder()
    mine = _yaml(Path(folder) / "policy.yaml") if folder else {}
    out = {"tiers": {**(base.get("tiers") or {}), **(mine.get("tiers") or {})},
           "channels": list(mine.get("channels") or base.get("channels") or ["app"]),
           "data": {**(base.get("data") or {}), **(mine.get("data") or {})},
           "tickets": dict(mine.get("tickets") or base.get("tickets") or {})}
    bad = {k: v for k, v in out["tiers"].items() if v not in TIERS}
    if bad:
        raise ValueError(f"policy: a tier is one of {', '.join(TIERS)}: {bad}")
    if "app" not in out["channels"]:
        out["channels"].insert(0, "app")
    return out


def channels(pol=None, has=None):
    """The channels that are on: the policy names them, and a channel's feature must be on too (GEN-13)."""
    pol = pol or policy()
    if has is None:
        try:
            import deployment as DEPLOY
            has = DEPLOY.has
        except (ImportError, SystemExit, OSError):
            has = lambda f: False                   # noqa: E731 - no deployment: only the app
    return [c for c in pol["channels"] if c in CHANNELS and (c != "telegram" or has("telegram"))]


def guard(text, what, pol=None):
    """The data rule (ASK-07): a text over the cap is refused with the cap named (never cut), a text naming a path of
    extracted content is refused (content goes by reference to a local path). -> (text, private): private when it
    carries a private marker, which makes its Ask private."""
    data = (pol or policy())["data"]
    s = TC.limit(str(text or ""), int(data.get("text_max") or 2000), what)
    for p in data.get("extract_paths") or []:
        if re.search(p, s):
            raise ValueError(f"{what} names extracted content ({p}); attach it by reference to its local path instead (refs)")
    private = any(re.search(p, s, re.I) for p in data.get("private_markers") or [])
    return s, private


def tier(kind, pol=None):
    """-> (tier, why). A gate always asks; otherwise the policy's tier of the kind's action, ask when it names none."""
    t = type_of(kind)
    if t["gate"]:
        return "ask", "a gate: only a person in its role answers it"
    tr = (pol or policy())["tiers"].get(t["action"], "ask")
    return tr, f"the policy's tier for {t['action']}"


# ---------------------------------------------------------------- standing rules
def rules_path():
    return home() / "rules.json"


def rules():
    return SF.load(rules_path(), []) or []


def rule_save(rule, person, now=None):
    """The owner's standing rule: {kind, effect: allow | default, outcome, under: {fact, max} (allow only), note}.
    allow: "always allow this kind [under a limit]"; default: "never ask me this kind again, use this answer". A gate
    never takes one."""
    kind = str(rule.get("kind") or "")
    t = type_of(kind)
    if t["gate"]:
        raise ValueError("a gate never takes a standing rule: only a person in its role answers it, one by one")
    if rule.get("effect") not in ("allow", "default"):
        raise ValueError("a rule allows a kind, or answers it with a default")
    outcome = rule.get("outcome") or t["does"]
    if outcome not in {o["id"] for o in t["outcomes"]} and not (t["own_choices"] and ID.fullmatch(str(outcome or ""))):
        raise ValueError(f"{outcome!r} is not an answer of {t['title']}")
    under = rule.get("under") or None
    if under is not None and not (isinstance(under, dict) and ID.fullmatch(str(under.get("fact") or "")) and isinstance(under.get("max"), (int, float))):
        raise ValueError("a rule's limit names a fact and its highest number")
    note = TC.limit(str(rule.get("note") or ""), 500, "the rule's note")   # limit: refuses, a note is a line
    with _lock:
        rs = rules()
        rid = str(rule.get("id") or "") or f"r{int((now or now_()) * 1000):x}"
        made = {"id": rid, "kind": kind, "effect": rule["effect"], "outcome": outcome, "under": under, "note": note,
                "by": str(person or ""), "at": now or now_()}
        rs = [r for r in rs if r["id"] != rid] + [made]
        SF.save(rules_path(), rs, indent=1)
    return made


def rule_delete(rid, person):
    with _lock:
        rs = rules()
        if not any(r["id"] == rid for r in rs):
            raise ValueError("no such rule")
        SF.save(rules_path(), [r for r in rs if r["id"] != rid], indent=1)
    return {"deleted": rid, "by": str(person or "")}


def _fact(a, name):
    for f in a.get("facts") or []:
        if f["k"] == name:
            try:
                return float(str(f["v"]).split()[0].replace(",", ""))
            except (ValueError, IndexError):
                return None
    return None


def rule_for(a):
    """The standing rule that answers this Ask, or None. A gate: always None."""
    if a.get("gate") or TYPES.get(a["kind"], {}).get("gate"):
        return None
    for r in reversed(rules()):
        if r.get("kind") != a["kind"]:
            continue
        if r.get("outcome") not in {o["id"] for o in a.get("choices") or [] if not o.get("href")}:
            continue
        u = r.get("under")
        if u:
            v = _fact(a, u["fact"])
            if v is None or v > u["max"]:
                continue
        return r
    return None


# ---------------------------------------------------------------- the stop switch
def stop_path():
    return home() / "stop.json"


def stop_state():
    return SF.load(stop_path(), {"on": False}) or {"on": False}


def stopped():
    return bool(stop_state().get("on"))


def stop_set(on, person, paused=None, now=None):
    """The one stop switch: on holds every workflow step, crew job and agent run the runner would start; off resumes.
    It records who switched it, when, and what it paused."""
    rec = {"on": bool(on), "by": str(person or ""), "at": now or now_(), "paused": paused or {}}
    SF.save(stop_path(), rec)
    return rec


# ---------------------------------------------------------------- the store
def _row(r):
    return None if r is None else {**json.loads(r["doc"]), "id": r["id"], "status": r["status"]}


def get(aid, c=None):
    c = c or connect()
    return _row(c.execute("select * from asks where id=?", (aid,)).fetchone())


def by_source(source, c=None):
    c = c or connect()
    return _row(c.execute("select * from asks where source=?", (source,)).fetchone())


def listing(statuses=WAITING, c=None):
    c = c or connect()
    q = ",".join("?" * len(statuses))
    return [_row(r) for r in c.execute(f"select * from asks where status in ({q}) order by created", tuple(statuses))]  # nosec - placeholders only


def _put(c, a, now):
    a["updated"] = now
    doc = {k: v for k, v in a.items() if k not in ("id", "status")}
    c.execute("insert into asks(id, source, kind, status, created, updated, deadline, wake, doc) values(?,?,?,?,?,?,?,?,?) "
              "on conflict(id) do update set status=excluded.status, updated=excluded.updated, deadline=excluded.deadline, "
              "wake=excluded.wake, doc=excluded.doc",
              (a["id"], a["source"], a["kind"], a["status"], a.get("created") or now, now, a.get("deadline"), a.get("wake"),
               json.dumps(doc, ensure_ascii=False)))


def _history(c, aid, event, now, **doc):
    c.execute("insert into history(ask_id, at, event, doc) values(?,?,?,?)", (aid, now, event, json.dumps(doc, ensure_ascii=False)))


def history(aid, c=None):
    c = c or connect()
    return [{"at": r["at"], "event": r["event"], **json.loads(r["doc"] or "{}")}
            for r in c.execute("select * from history where ask_id=? order by n", (aid,))]


def _when(x):
    if x in (None, ""):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
    except ValueError:
        raise ValueError(f"a deadline is a time, not {x!r}") from None


def _facts(f):
    items = list(f.items()) if isinstance(f, dict) else [(x.get("k"), x.get("v")) if isinstance(x, dict) else tuple(x) for x in f or []]
    TC.limit_items(items, FACTS_MAX, "facts")
    return [{"k": str(k), "v": str(v)} for k, v in items]


def _choices(spec, t):
    raw = spec.get("choices")
    if raw is None or not t["own_choices"] and not raw:
        return [dict(o) for o in t["outcomes"]]
    if not t["own_choices"]:
        known = {o["id"]: o for o in t["outcomes"]}
        out = []
        for ch in raw:
            o = known.get(ch.get("id"))
            if not o and not ch.get("href"):
                raise ValueError(f"{ch.get('id')!r} is not an answer of {t['title']}")
            out.append({**(o or {}), **{k: v for k, v in ch.items() if k in ("id", "label", "href")}})
        return TC.limit_items(out, CHOICES_MAX, "chips")
    out = []
    for i, ch in enumerate(TC.limit_items(raw, CHOICES_MAX, "chips")):
        ch = {"label": ch} if isinstance(ch, str) else dict(ch)
        label = TC.limit(str(ch.get("label") or "").strip(), LABEL_MAX, "a chip's label")
        if not label:
            raise ValueError("a chip needs its label")
        cid = str(ch.get("id") or re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or f"c{i + 1}")
        if not ID.fullmatch(cid):
            raise ValueError(f"a chip's id is a short name, not {cid!r}")
        out.append({"id": cid, "label": label, **({"href": ch["href"]} if ch.get("href") else {}),
                    **({"words": TC.limit(str(ch["words"]), QUESTION_MAX, "a chip's question")} if ch.get("words") else {})})
    if len({o["id"] for o in out}) != len(out):
        raise ValueError("two chips have the same id")
    return out


EXTRA = ("rank", "recommend", "routine", "expires", "cls", "since")   # a source's own display fields, passed through
FRESH = ("title", "question", "why", "facts", "choices", "acts", "undo", "allow_words", "default", "href", "sensitivity", "refs",
         "unanswered", "weight", "group", "values", "task", "test", *EXTRA)    # what a source's newer listing of a waiting Ask updates


def check_spec(spec, pol=None):
    """The checks open_ask makes, without storing anything: a workflow's question is refused before it waits."""
    pol = pol or policy()
    t = type_of(str(spec.get("kind") or ""))
    guard(TC.limit(str(spec.get("question") or "").strip(), QUESTION_MAX, "the question"), "the question", pol)
    guard(TC.limit(str(spec.get("why") or ""), WHY_MAX, "why it matters"), "why it matters", pol)
    choices = _choices(spec, t)
    if spec.get("gate") or t["gate"]:
        if spec.get("default"):
            raise ValueError("a gate has no default; at its deadline it reminds and escalates")
    elif spec.get("default") and spec["default"].get("outcome") not in {o["id"] for o in choices}:
        raise ValueError("the default must be one of the Ask's chips")
    _when(spec.get("deadline"))
    return True


def record_gate(need):
    """ASK-20, REC-08: the records' gate hook (records.set_gate). A transition to a status a pack gates opens one gate Ask
    for its role; -> {state: waiting} while it waits, {state: approved, person, role, chip, ask, at} once a person who
    holds the role tapped Approve and it was applied, {state: refused, why} for Not now or a dismissal."""
    register_workflow_kinds()
    a = by_source(str(need["id"]))
    if a is None or a.get("gone"):
        a = open_ask({"kind": "record-gate", "source": str(need["id"]), "question": need.get("question") or f"May {need['key']} move to {need['to']}?",
                      "why": f"{need.get('type') or 'A record'} moving to {need['to']} needs the approval of the role {need.get('role') or 'owner'}.",
                      "facts": {"Record": f"{need['tracker']}/{need['key']}", "To": need["to"]}, "role": need.get("role") or "owner",
                      "task": f"record:{need['tracker']}/{need['key']}"})
    ans = a.get("answer") or {}
    if a["status"] == "answered" and not a.get("pending") and ans.get("outcome") == "approve":
        return {"state": "approved", "person": ans.get("person"), "role": ans.get("role"), "chip": bool(ans.get("confirmed")),
                "ask": a["id"], "at": dt.datetime.fromtimestamp(ans.get("at") or now_()).astimezone().isoformat(timespec="seconds"),
                **({"interpreted_as": ans["interpreted_as"]} if ans.get("interpreted_as") else {})}
    if a["status"] == "dismissed" or (a["status"] == "answered" and not a.get("pending") and ans.get("outcome")):
        return {"state": "refused", "ask": a["id"], "why": f"{ans.get('person') or 'it'} said no" if ans.get("outcome") else "the question was dismissed"}
    return {"state": "waiting", "ask": a["id"]}


def open_ask(spec, now=None, pol=None, c=None):
    """One Ask, idempotent by its source key: the same source again updates a waiting Ask's text and facts and returns
    it; an Ask its source dropped and lists again opens a new round. A never tier refuses; a do or tell tier, or a
    standing rule, answers it at once (never a gate). -> the Ask."""
    now = now or now_()
    pol = pol or policy()
    t = type_of(str(spec.get("kind") or ""))
    source = str(spec.get("source") or "")
    if not source:
        raise ValueError("an Ask names its source (workflow/run/node, a crew job, a build ...)")
    question, p1 = guard(TC.limit(str(spec.get("question") or "").strip(), QUESTION_MAX, "the question"), "the question", pol)
    if not question:
        raise ValueError("an Ask needs its question")
    why, p2 = guard(TC.limit(str(spec.get("why") or ""), WHY_MAX, "why it matters"), "why it matters", pol)
    facts = _facts(spec.get("facts"))
    p3 = any(guard(f["v"], f"the fact {f['k']}", pol)[1] for f in facts)
    gate = t["gate"] or bool(spec.get("gate"))
    choices = _choices(spec, t)
    default = None if gate else (spec.get("default") or t["default"])
    if spec.get("default") and gate:
        raise ValueError("a gate has no default; at its deadline it reminds and escalates")
    if default and default.get("outcome") not in {o["id"] for o in choices}:
        raise ValueError("the default must be one of the Ask's chips")
    sens = spec.get("sensitivity") or "normal"
    if sens not in SENSITIVITY:
        raise ValueError(f"sensitivity is one of {', '.join(SENSITIVITY)}")
    if p1 or p2 or p3:
        sens = "private"
    refs = [str(r) for r in spec.get("refs") or []]
    if any(not r.startswith("/") for r in refs):
        raise ValueError("a reference is a local path")
    deadline = _when(spec.get("deadline"))
    if default and deadline is None and default.get("after_h"):
        deadline = now + float(default["after_h"]) * 3600
    tr, why_tier = tier(t["kind"], pol)
    if tr == "never" and not gate:
        raise ValueError(f"the policy says the stack never does this ({t['action']})")
    aid = ask_id(source)
    a = {"id": aid, "source": source, "kind": t["kind"], "title": t["title"], "question": question, "why": why, "facts": facts,
         "choices": choices, "acts": dict(spec.get("acts") or {}), "undo": dict(spec.get("undo") or {}),
         "allow_words": t["words"] and not gate and spec.get("allow_words", True) is not False, "default": default,
         "deadline": deadline, "role": str(spec.get("role") or t["role"]), "gate": gate, "task": spec.get("task"),
         "ticket": spec.get("ticket"), "href": spec.get("href") or "", "sensitivity": sens, "refs": refs,
         "unanswered": str(spec.get("unanswered") or ""), "weight": spec.get("weight", 1), "group": t["group"] and not gate,
         "values": t["values"], "status": "open", "answer": None, "pending": None, "created": now, "wake": None,
         "test": bool(spec.get("test")), **{k: spec.get(k) for k in EXTRA}}
    with _lock:
        c = c or connect()
        old = get(aid, c)
        if old and (old["status"] in WAITING or not old.get("gone")):
            new = dict(old, gone=False)
            if old["status"] in SHOWN:                   # the source's newest words and facts; the answer state stays
                new.update({k: a[k] for k in FRESH})
                new["deadline"] = old.get("deadline") or a["deadline"]
            if new != old:
                _put(c, new, now)
            return new
        c.execute("begin immediate")
        try:
            if old:
                _history(c, aid, "again", now, note="its source asks again")
            _put(c, a, now)
            _history(c, aid, "opened", now, kind=t["kind"], tier=tr)
            c.execute("commit")
        except BaseException:
            c.execute("rollback")
            raise
        if gate:
            return a
        r = rule_for(a)
        if r:
            return _settle(aid, r["outcome"], f"rule:{r['id']}", now, why=f"your standing rule ({r['effect']})", c=c)
        if tr in ("do", "tell") and t["does"]:
            return _settle(aid, t["does"], "policy", now, why=why_tier, tell=tr == "tell", c=c)
        return a


def sync_gone(prefix, present, now=None, c=None):
    """The Asks of a source (its keys start with prefix) that it no longer lists: settled where they live (answered on
    their own page, or over), so they leave Needs you; listed again, they open a new round. -> how many."""
    now = now or now_()
    n = 0
    with _lock:
        c = c or connect()
        for r in c.execute("select * from asks where source like ? and coalesce(json_extract(doc, '$.gone'), 0) = 0",
                           (prefix.replace("%", "") + "%",)).fetchall():
            if r["source"] in present:
                continue
            a = _row(r)
            a["gone"] = True
            if a["status"] in WAITING:
                a["status"], a["pending"] = "answered", None
                a["answer"] = {"via": "elsewhere", "outcome": None, "at": now, "said": "settled where it lives"}
                _history(c, a["id"], "settled", now, where="its source")
            _put(c, a, now)
            n += 1
    return n


def close_off(prefix, words, now=None, c=None):
    """GEN-13, PHN-28: the waiting Asks of a source whose feature was switched off (their keys start with prefix):
    dismissed by the stack with its words ("the AI phone is switched off"), their history kept, nothing deleted. Marked
    gone, so the feature on again and its source listing one again opens a new round. -> how many."""
    now = now or now_()
    n = 0
    with _lock:
        c = c or connect()
        for r in c.execute("select * from asks where source like ?", (prefix.replace("%", "") + "%",)).fetchall():
            if r["status"] not in WAITING:
                continue
            a = _row(r)
            a["status"], a["pending"], a["gone"] = "dismissed", None, True
            a["answer"] = {"via": "stack", "outcome": None, "words": words, "person": STACK, "at": now, "dismissed": True}
            _put(c, a, now)
            _history(c, a["id"], "dismissed", now, person=STACK, words=words)
            n += 1
    return n


def _settle(aid, outcome, by, now, why="", tell=False, c=None):
    """An Ask answered by the stack itself (a do or tell tier, a standing rule, a default): applied at once, with an undo
    record when its source knows how. Never a gate."""
    c = c or connect()
    a = get(aid, c)
    if a["gate"]:
        raise ValueError("a gate is answered only by a person in its role")
    ans = {"answer_id": f"{by.split(':')[0]}-{aid}-{int(now)}", "outcome": outcome, "values": {}, "words": "", "person": STACK,
           "role": a["role"], "via": by, "at": now, "interpreted_as": None, "confirmed": True, "why": why, "apply_at": now,
           "tell": tell}
    _record(c, a, ans, "held", now)
    return get(aid, c)


def _record(c, a, ans, state, now):
    c.execute("begin immediate")
    try:
        c.execute("insert or replace into answers(answer_id, ask_id, at, state, doc) values(?,?,?,?,?)",
                  (ans["answer_id"], a["id"], now, state, json.dumps(ans, ensure_ascii=False)))
        if state in ("held", "applied"):
            a["status"], a["answer"], a["pending"] = "answered", ans, {"answer_id": ans["answer_id"], "state": "held",
                                                                        "undo_until": ans["apply_at"]}
        _put(c, a, now)
        _history(c, a["id"], "answered" if state == "held" else state, now, outcome=ans.get("outcome"), via=ans.get("via"),
                 person=ans.get("person"), words=ans.get("words") or "")
        c.execute("commit")
    except BaseException:
        c.execute("rollback")
        raise


def _seen(c, answer_id):
    r = c.execute("select * from answers where answer_id=?", (answer_id,)).fetchone()
    return None if r is None else {"state": r["state"], **json.loads(r["doc"])}


def _check_person(a, person):
    from domain import roles as RL
    if not RL.holds(a["role"], person):
        ps = [x for p in RL.people(a["role"]) for x in ((RL.owners() or [p]) if p == RL.OWNER else [p])]
        who = "the owner" if ps == [RL.OWNER] else ", ".join(ps)
        raise ValueError(f"only {who} may answer this ({a['role']}); you are signed in as {person or 'nobody'}")


def _not_gate(a, via):
    """WAY-07: a gate is a tap in the app by a person in its role; the command line and the agents' stack tools are
    refused at it whole (an answer, words, a dismissal, a later), with the reason."""
    if a.get("gate") and via in NOT_GATE_VIAS:
        raise ValueError(f"a gate is answered only by a tap in the app by a person in its role ({a.get('role') or 'owner'}); "
                         "the command line and the agents' tools never answer one")


def _open_one(aid, c):
    a = get(aid, c)
    if not a:
        raise ValueError("that question is not here any more")
    return a


def answer(aid, *, answer_id, person, via, outcome=None, values=None, words="", chip=False, always=False, group=False,
           interpreted_as=None, now=None, c=None):
    """A person's answer. A chip (outcome, chip=True) is held for its undo, then applied. Words without an outcome wait
    for the interpreter ("reading"); at a gate they are a comment. Idempotent by answer_id."""
    now = now or now_()
    if not ANSWER_ID.fullmatch(str(answer_id or "")):
        raise ValueError("an answer needs its answer id")
    if via not in VIAS and via not in GATE_VIAS:
        raise ValueError(f"an answer comes by one of {', '.join(VIAS)}")
    with _lock:
        c = c or connect()
        seen = _seen(c, answer_id)
        if seen and seen["state"] == "undone" and seen.get("early"):
            return {"again": True, "ask": aid, "message": "Undone before it arrived"}
        if seen:
            return {"again": True, **_result(get(seen.get("ask_id") or aid, c) or {}, seen)}
        a = _open_one(aid, c)
        if a["status"] not in WAITING:
            raise ValueError(f"it was {a['status']} already")
        _not_gate(a, via)
        _check_person(a, person)
        words = TC.limit(str(words or "").strip(), WORDS_MAX, "your answer")
        if words:
            words, _ = guard(words, "your answer")
        base = {"answer_id": answer_id, "ask_id": aid, "values": dict(values or {}), "words": words, "person": str(person), "role": a["role"],
                "via": via, "at": now, "interpreted_as": interpreted_as, "group": group}
        if a["gate"]:
            if always:
                raise ValueError("a gate never takes a standing rule: only a person in its role answers it, one by one")
            if group:
                raise ValueError("a gate is answered one by one, never with a group")
            if outcome is None or not chip or interpreted_as:
                if not words:
                    raise ValueError("a gate is answered by a tap on one of its chips")
                ans = {**base, "outcome": None, "comment": True}
                _comment(c, a, ans, now)
                return {"comment": True, "ask": aid, "message": "Kept as a comment: a gate is answered by a tap on its chips"}
            if via not in GATE_VIAS:
                raise ValueError("a gate is answered in the app, by a tap on its chip")
        if outcome is None:
            if not words:
                raise ValueError("say what you answer: a chip, or a few words")
            if not a["allow_words"]:
                raise ValueError("this question takes one of its chips")
            ans = {**base, "outcome": None}
            _pending(c, a, ans, "reading", now)
            return {"reading": True, "ask": aid, "message": "Reading your answer"}
        chosen = next((o for o in a["choices"] if o["id"] == outcome and not o.get("href")), None)
        if not chosen:
            raise ValueError("that is not one of its answers")
        if chosen.get("words") and not words and not values:
            raise ValueError(chosen["words"])
        ans = {**base, "outcome": outcome, "confirmed": bool(chip), "apply_at": now + HOLD_S}
        if always:
            r = rule_save({"kind": a["kind"], "effect": "allow", "outcome": outcome, "note": "from an answer: always for this kind"}, person, now)
            ans["rule"] = r["id"]
        _record(c, a, ans, "held", now)
        return _result(get(aid, c), {**ans, "state": "held"})


def _result(a, ans):
    label = next((o["label"] for o in a.get("choices") or [] if o["id"] == ans.get("outcome")), ans.get("outcome"))
    return {"ask": a.get("id"), "state": ans.get("state"), "outcome": ans.get("outcome"), "label": label,
            "undo_until": ans.get("apply_at"), "interpreted_as": ans.get("interpreted_as"),
            "message": f"Answered: {label}" if ans.get("outcome") else ans.get("message") or ""}


def _pending(c, a, ans, state, now, **more):
    c.execute("begin immediate")
    try:
        c.execute("insert or replace into answers(answer_id, ask_id, at, state, doc) values(?,?,?,?,?)",
                  (ans["answer_id"], a["id"], now, state, json.dumps(ans, ensure_ascii=False)))
        a["pending"] = {"answer_id": ans["answer_id"], "state": state, "words": ans.get("words") or "", **more}
        _put(c, a, now)
        _history(c, a["id"], state, now, person=ans.get("person"), via=ans.get("via"), words=ans.get("words") or "")
        c.execute("commit")
    except BaseException:
        c.execute("rollback")
        raise


def _comment(c, a, ans, now):
    a.setdefault("comments", []).append({"person": ans["person"], "via": ans["via"], "at": now, "words": ans["words"]})
    _pending(c, a, ans, "comment", now, suggest=None)


def reading(c=None):
    """Answers in words waiting for the interpreter (and gate comments waiting for a suggested chip)."""
    c = c or connect()
    return [{"state": r["state"], **json.loads(r["doc"])} for r in c.execute("select * from answers where state in ('reading','comment') order by at")]


def understood(aid, answer_id, result, now=None, c=None):
    """The interpreter's reading of an answer in words: an outcome with values (held for its undo, the card shows
    "Understood as ..."), a question back (asked in the card), or for a gate only a suggested chip the person still taps.
    An instruction in the words becomes a snooze, a standing rule (never for a gate) or a note to the asking task."""
    now = now or now_()
    with _lock:
        c = c or connect()
        ans = _seen(c, answer_id)
        if not ans or ans["state"] not in ("reading", "comment"):
            return None
        a = get(aid, c)
        ins = result.get("instruction") or {}
        if a["gate"] or ans["state"] == "comment":
            sug = result.get("outcome") if result.get("outcome") in {o["id"] for o in a["choices"]} else None
            _pending(c, a, {**ans, "suggest": sug}, "suggested", now, suggest=sug)
            return get(aid, c)
        if ins.get("kind") == "snooze" and ins.get("until"):
            _pending(c, a, ans, "understood", now)
            return later(aid, answer_id=f"{answer_id}-later", person=ans["person"], until=ins["until"], via=ans["via"], now=now, c=c)
        if ins.get("kind") == "note":
            note = TC.limit(str(ins.get("text") or ans["words"]), WORDS_MAX, "the note")
            a.setdefault("notes", []).append({"person": ans["person"], "at": now, "text": note})
            _put(c, a, now)
        if result.get("ask_back") or not result.get("outcome"):
            _pending(c, a, ans, "asked_back", now, ask_back=str(result.get("ask_back") or "Could you say that another way?"),
                     understood=result.get("understood") or "")
            return get(aid, c)
        if result["outcome"] not in {o["id"] for o in a["choices"] if not o.get("href")}:
            _pending(c, a, ans, "asked_back", now, ask_back="Which of its answers do you mean?")
            return get(aid, c)
        label = next(o["label"] for o in a["choices"] if o["id"] == result["outcome"])
        values = {k: v for k, v in (result.get("values") or {}).items() if k in a.get("values", {})}
        held = {**ans, "outcome": result["outcome"], "values": values, "confirmed": False, "apply_at": now + HOLD_S,
                "interpreted_as": result.get("understood") or label}
        if ins.get("kind") == "rule" and not a["gate"]:
            held["rule"] = rule_save({"kind": a["kind"], "effect": "default", "outcome": result["outcome"],
                                      "note": f"from your words: {ans['words']}"}, ans["person"], now)["id"]
        _record(c, a, held, "held", now)
        return get(aid, c)


def undo(aid, *, answer_id, person, now=None, c=None):
    """The one-tap undo of an answer that has not been applied yet: the Ask waits again, and a rule the answer made goes."""
    now = now or now_()
    with _lock:
        c = c or connect()
        a = _open_one(aid, c)
        cur = (a.get("pending") or {}).get("answer_id")
        ans = _seen(c, answer_id) or {}
        if not ans and ANSWER_ID.fullmatch(str(answer_id or "")):   # the undo came first (the inbox has no order): its answer, when it comes, does nothing
            _check_person(a, person)
            c.execute("insert into answers(answer_id, ask_id, at, state, doc) values(?,?,?,?,?)",
                      (answer_id, aid, now, "undone", json.dumps({"answer_id": answer_id, "ask_id": aid, "person": person, "early": True})))
            return a
        if ans.get("state") == "applied":
            raise ValueError("it was done already; undo it where it was done")
        if cur != answer_id or not ans:
            raise ValueError("that answer is not the one waiting")
        _check_person(a, person)
        if ans.get("rule"):
            try:
                rule_delete(ans["rule"], person)
            except ValueError:
                pass
        c.execute("begin immediate")
        try:
            c.execute("update answers set state='undone' where answer_id=?", (answer_id,))
            a["status"], a["answer"], a["pending"] = "open" if not a.get("escalated_to") else "escalated", None, None
            _put(c, a, now)
            _history(c, aid, "undone", now, person=person)
            c.execute("commit")
        except BaseException:
            c.execute("rollback")
            raise
        return get(aid, c)


def dismiss(aid, *, answer_id, person, via="app", words="", source=None, now=None, c=None):
    """Dismiss: the Ask leaves Needs you, with the person's words kept; nothing is done. At a gate this is no approval:
    what waits on it does not proceed."""
    now = now or now_()
    with _lock:
        c = c or connect()
        if _seen(c, answer_id):
            return get(aid, c)
        a = get(aid, c) or _stub(aid, source, now, c)
        if a["status"] not in WAITING:
            raise ValueError(f"it was {a['status']} already")
        _not_gate(a, via)
        _check_person(a, person)
        words = TC.limit(str(words or ""), WORDS_MAX, "your reason")
        ans = {"answer_id": answer_id, "ask_id": aid, "outcome": None, "words": words, "person": person, "role": a["role"], "via": via, "at": now}
        c.execute("begin immediate")
        try:
            c.execute("insert into answers(answer_id, ask_id, at, state, doc) values(?,?,?,?,?)", (answer_id, aid, now, "dismissed", json.dumps(ans)))
            a["status"], a["answer"], a["pending"] = "dismissed", {**ans, "dismissed": True}, None
            _put(c, a, now)
            _history(c, aid, "dismissed", now, person=person, words=words)
            c.execute("commit")
        except BaseException:
            c.execute("rollback")
            raise
        return get(aid, c)


def _stub(aid, source, now, c):
    """An Ask only the app sees (the AI phone's approvals, a Trash batch, a mission's access): recorded here when it is
    dismissed or put off, so the app hides it until then."""
    if not source or ask_id(source) != aid:
        raise ValueError("that question is not here any more")
    a = {"id": aid, "source": source, "kind": "app", "title": "", "question": "", "why": "", "facts": [], "choices": [], "acts": {},
         "undo": {}, "allow_words": False, "default": None, "deadline": None, "role": "owner", "gate": False, "status": "open",
         "answer": None, "pending": None, "created": now, "wake": None, "sensitivity": "normal", "app_only": True}
    _put(c, a, now)
    return a


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MORNING, EVENING = 8, 19


def when(words, now=None):
    """"tomorrow morning", "tonight", "in 3 hours", "next week", "friday", "2026-12-01" -> a time; None when it says no time."""
    now = now or now_()
    s = str(words or "").strip().lower()
    t = dt.datetime.fromtimestamp(now).astimezone()

    def at(day, hour):
        return day.replace(hour=hour, minute=0, second=0, microsecond=0).timestamp()
    m = re.fullmatch(r"in (\d{1,3}|an?|one) (minute|hour|day|week)s?", s)
    if m:
        n = 1 if m.group(1) in ("a", "an", "one") else int(m.group(1))
        return now + n * {"minute": 60, "hour": 3600, "day": 86400, "week": 7 * 86400}[m.group(2)]
    if s in ("tonight", "this evening", "evening"):
        x = at(t, EVENING)
        return x if x > now else at(t + dt.timedelta(days=1), EVENING)
    if s in ("tomorrow", "tomorrow morning", "morning"):
        return at(t + dt.timedelta(days=1), MORNING)
    if s in ("next week", "monday next week"):
        return at(t + dt.timedelta(days=7 - t.weekday()), MORNING)
    if s in ("later", "later today"):
        return now + 3 * 3600
    if s in WEEKDAYS:
        d = (WEEKDAYS.index(s) - t.weekday()) % 7 or 7
        return at(t + dt.timedelta(days=d), MORNING)
    months = tuple(m.lower() for m in calendar.month_name[1:])   # the English names (the C locale), january first
    m = re.fullmatch(r"(?:in |early |next )?(" + "|".join(months) + r")", s)
    if m:
        mo = months.index(m.group(1)) + 1
        day = t.replace(year=t.year + (mo <= t.month), month=mo, day=1)
        while day.weekday() > 4:
            day += dt.timedelta(days=1)
        return at(day, MORNING)
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[ t](\d{1,2}):(\d{2}))?", s)
    if m:
        day = dt.datetime.fromisoformat(m.group(1)).astimezone()
        return day.replace(hour=int(m.group(2) or MORNING), minute=int(m.group(3) or 0)).timestamp()
    return None


def later(aid, *, answer_id, person, until=None, words="", via="app", source=None, now=None, c=None):
    """Later: the Ask sleeps until a time ("tomorrow morning" works) and then waits again."""
    now = now or now_()
    if isinstance(until, (int, float)) or isinstance(until, str) and re.match(r"\d{4}-\d{2}-\d{2}T", until):
        t = _when(until)
    else:
        t = when(until or words, now)
    if t is None:
        raise ValueError("say when, for example tomorrow morning, tonight, in 3 hours or a date")
    if t <= now:
        raise ValueError("that time has passed")
    with _lock:
        c = c or connect()
        if _seen(c, answer_id):
            return get(aid, c)
        a = get(aid, c) or _stub(aid, source, now, c)
        if a["status"] not in WAITING:
            raise ValueError(f"it was {a['status']} already")
        _not_gate(a, via)
        _check_person(a, person)
        ans = {"answer_id": answer_id, "ask_id": aid, "outcome": None, "until": t, "person": person, "via": via, "at": now}
        c.execute("begin immediate")
        try:
            c.execute("insert into answers(answer_id, ask_id, at, state, doc) values(?,?,?,?,?)", (answer_id, aid, now, "later", json.dumps(ans)))
            a["was"] = a["status"] if a["status"] != "snoozed" else a.get("was", "open")
            a["status"], a["wake"], a["pending"] = "snoozed", t, None
            _put(c, a, now)
            _history(c, aid, "later", now, person=person, until=t)
            c.execute("commit")
        except BaseException:
            c.execute("rollback")
            raise
        return get(aid, c)


def group_answer(kind, *, answer_id, person, via="app", outcome, ids=None, overrides=None, now=None, c=None):
    """One answer for every waiting Ask of a kind (or those named), with a different answer for any named in overrides.
    A gate is never answered with a group: it is left, and said so."""
    now = now or now_()
    c = c or connect()
    asks = [a for a in listing(SHOWN, c) if a["kind"] == kind and (ids is None or a["id"] in ids)]
    done, left = [], []
    for i, a in enumerate(asks):
        if a["gate"]:
            left.append(a["id"])
            continue
        o = (overrides or {}).get(a["id"], outcome)
        answer(a["id"], answer_id=f"{answer_id}-{i}", person=person, via=via, outcome=o, chip=True, group=True, now=now, c=c)
        done.append(a["id"])
    return {"answered": done, "left": left,
            "message": f"Answered {len(done)}" + (f"; {len(left)} gate{'s' if len(left) != 1 else ''} wait for a tap each" if left else "")}


# ---------------------------------------------------------------- the clock
def _apply(a, ans):
    fn = APPLY.get(a["kind"])
    if fn:
        return fn(a, ans) or ""
    act = dict((a.get("acts") or {}).get(ans["outcome"]) or {})
    if not act:
        return ""
    into = act.pop("_into", None)
    if into:                                         # a chip that takes words: its value, else the words themselves
        act[into] = (ans.get("values") or {}).get(into, ans.get("words") or "")
    if not DISPATCH[0]:
        raise RuntimeError("the runner's request handler is not ready")
    res = DISPATCH[0]({**act, "who": ans.get("person") or "", "source": "ask", "ask": a["id"],
                       **({"answer_values": ans.get("values")} if ans.get("values") else {})})
    if isinstance(res, dict) and res.get("ok") is False:
        raise ValueError(res.get("error") or "it was refused")
    return (res or {}).get("message") if isinstance(res, dict) else ""


def tick(now=None, apply=None, notify=None, c=None):
    """One pass of the clock: held answers past their undo are applied (a failure reopens the Ask with the reason),
    snoozes wake, a default applies at its deadline, an Ask without one expires, and a gate's deadline reminds, then
    escalates; a gate never proceeds. -> what it did, one line each."""
    now = now or now_()
    apply = apply or _apply
    did = []
    with _lock:
        c = c or connect()
        for r in c.execute("select * from answers where state='held' and json_extract(doc, '$.apply_at') <= ?", (now,)).fetchall():
            ans = json.loads(r["doc"])
            a = get(r["ask_id"], c)
            if not a or (a.get("pending") or {}).get("answer_id") != ans["answer_id"]:
                c.execute("update answers set state='undone' where answer_id=?", (ans["answer_id"],))
                continue
            try:
                said = apply(a, ans)
                state, err = "applied", None
            except Exception as e:                       # the source refused or is away: the Ask waits again, with why
                said, state, err = "", "refused", f"{type(e).__name__}: {e}" if not isinstance(e, ValueError) else str(e)
            c.execute("begin immediate")
            try:
                c.execute("update answers set state=? where answer_id=?", (state, ans["answer_id"]))
                if err and a.get("gone"):                 # its source settled it meanwhile (on its own page)
                    a["status"], a["pending"], a["error"] = "answered", None, None
                    a["answer"] = {"via": "elsewhere", "outcome": None, "at": now, "said": f"settled where it lives ({err})"}
                elif err:
                    a["status"], a["answer"], a["pending"], a["error"] = "open", None, None, f"Your answer could not be applied: {err}"
                else:
                    a["answer"], a["pending"], a["error"], a["applied"] = {**ans, "said": said or ""}, None, None, now
                    if a.get("undo", {}).get(ans["outcome"]) and ans.get("person") == STACK:
                        _undo_record(c, a, ans, now)          # the stack acted on its own: the owner can take it back
                _put(c, a, now)
                _history(c, a["id"], state, now, error=err or "", said=said or "")
                c.execute("commit")
            except BaseException:
                c.execute("rollback")
                raise
            did.append(f"{a['id']} {state}" + (f": {err}" if err else ""))
            if ans.get("tell") and notify and not err:
                notify(f"Done for you: {a['question']} ({next((o['label'] for o in a['choices'] if o['id'] == ans['outcome']), ans['outcome'])})", "activity")
        for a in listing(("snoozed",), c):
            if a.get("wake") and a["wake"] <= now:
                a["status"], a["wake"] = a.get("was") or "open", None
                _put(c, a, now)
                _history(c, a["id"], "woke", now)
                did.append(f"{a['id']} woke")
        for a in listing(SHOWN, c):
            if a.get("app_only") or not a.get("deadline") or a["deadline"] > now or a.get("pending"):
                continue
            if a["gate"]:
                did += _gate_due(c, a, now, notify)
            elif a.get("default"):
                _settle(a["id"], a["default"]["outcome"], "default", now, why="applied by default at its deadline", c=c)
                did.append(f"{a['id']} default")
            else:
                a["status"] = "expired"
                _put(c, a, now)
                _history(c, a["id"], "expired", now)
                did.append(f"{a['id']} expired")
    return did


def _gate_due(c, a, now, notify):
    """A gate past its deadline: first a reminder to its role's people, ESCALATE_H later the next in its escalation
    order (the owner last). It never proceeds and never expires."""
    from domain import roles as RL
    if not a.get("reminded"):
        a["reminded"] = now
        _put(c, a, now)
        _history(c, a["id"], "reminded", now, role=a["role"])
        if notify:
            notify(f"Still waiting for {', '.join(RL.people(a['role']))}: {outward(a)}", "asks")
        return [f"{a['id']} reminded"]
    if now - a["reminded"] < ESCALATE_H * 3600:
        return []
    order = RL.escalation(a.get("escalated_to") or a["role"])
    if not order:
        return []
    nxt = order[0]
    a["escalated_to"], a["status"], a["reminded"] = nxt, "escalated", now
    a["role"] = nxt if nxt in RL.load()[0] or nxt == RL.OWNER else a["role"]
    if a["role"] != nxt:                               # a person, not a role: they hold it from now on
        a.setdefault("also", []).append(nxt)
    _put(c, a, now)
    _history(c, a["id"], "escalated", now, to=nxt)
    if notify:
        notify(f"Escalated to {nxt}: {outward(a)}", "asks")
    return [f"{a['id']} escalated to {nxt}"]


# ---------------------------------------------------------------- undo records (do and tell)
def _undo_record(c, a, ans, now):
    how = a["undo"][ans["outcome"]]
    rec = {"ask": a["id"], "what": a["question"], "outcome": ans["outcome"], "how": how, "by": ans["via"], "at": now}
    c.execute("insert or replace into undo(id, at, until, state, doc) values(?,?,?,?,?)",
              (ans["answer_id"], now, now + float(how.get("hours") or 24) * 3600, "open", json.dumps(rec)))


def undo_records(now=None, c=None):
    now = now or now_()
    c = c or connect()
    return [{"id": r["id"], "at": r["at"], "until": r["until"], "state": r["state"], **json.loads(r["doc"])}
            for r in c.execute("select * from undo where until > ? order by at desc", (now - 7 * 86400,))]


def undo_action(uid, person, now=None, c=None):
    """Undo what the stack did on its own (a do or tell tier, a rule), while its undo window is open."""
    now = now or now_()
    c = c or connect()
    with _lock:
        return _undo_action(c, uid, person, now)


def _undo_action(c, uid, person, now):
    r = c.execute("select * from undo where id=?", (uid,)).fetchone()
    if not r or r["state"] != "open":
        raise ValueError("there is nothing to undo there")
    if r["until"] < now:
        raise ValueError("its undo window has closed")
    rec = json.loads(r["doc"])
    act = {k: v for k, v in rec["how"].items() if k != "hours"}
    res = DISPATCH[0]({**act, "who": person, "source": "ask"}) if DISPATCH[0] else {"ok": False, "error": "the runner is not ready"}
    if isinstance(res, dict) and res.get("ok") is False:
        raise ValueError(res.get("error") or "the undo was refused")
    c.execute("update undo set state='undone' where id=?", (uid,))
    return {"undone": uid, "what": rec["what"]}


# ---------------------------------------------------------------- what leaves the store
def outward(a):
    """An Ask as a ticket, a push or a log line may carry it: a private one names no figure, only that it waits."""
    if a.get("sensitivity") == "private":
        return f"A private question waits for you in the app ({a.get('title') or a['kind']})."
    return a["question"]


def public(a):
    """An Ask as the app gets it: without the runner's own acts and undo actions."""
    from domain import roles as RL
    out = {k: v for k, v in a.items() if k not in ("acts", "undo", "source")}
    out["source"] = a["source"].split(":")[0]
    out["people"] = [x for p in RL.people(a["role"]) for x in ((RL.owners() or [p]) if p == RL.OWNER else [p])] + list(a.get("also") or [])
    return out


def published(now=None, c=None):
    """state.json's "asks": the Asks that wait (and those answered within their undo), the rules, the stop switch, the
    undo records and each kind's tier for the policy page."""
    now = now or now_()
    c = c or connect()
    pol = policy()
    asks = [public(a) for a in listing(("open", "escalated", "snoozed", "answered"), c)
            if a["status"] != "answered" or (a.get("pending") or {}).get("state") == "held"]
    hidden = [a["id"] for a in listing(("dismissed", "snoozed"), c) if a.get("app_only")]
    kinds = [{"kind": k, "title": t["title"], "action": t["action"], "tier": tier(k, pol)[0], "gate": t["gate"], "role": t["role"],
              "outcomes": t["outcomes"]} for k, t in sorted(TYPES.items())]
    return {"asks": [a for a in asks if not a.get("app_only")], "asks_hidden": hidden,
            "ask_policy": {"kinds": kinds, "tiers": pol["tiers"], "channels": channels(pol), "rules": rules(), "stop": stop_state(),
                           "undo": undo_records(now, c), "hold_s": HOLD_S}}


# ---------------------------------------------------------------- the app's requests (through the runner's inbox)
ACTIONS = {"ask_answer", "ask_undo", "ask_dismiss", "ask_later", "ask_group", "ask_rule_save", "ask_rule_delete", "ask_stop",
           "ask_undo_action"}


def handle(req, now=None):
    """The app's answers. The person is the app's signed-in person ("who", set by the server from the sign-in, never
    from the page); a request without one is refused."""
    a, person = req.get("action"), str(req.get("who") or "").strip()
    if not person:
        raise ValueError("an answer needs the signed-in person; none came with it")
    via = "app" if req.get("source") == "app" else str(req.get("via") or "")
    aid, answer_id = str(req.get("id") or ""), str(req.get("answer_id") or "")
    if a == "ask_answer":
        return answer(aid, answer_id=answer_id, person=person, via=via, outcome=req.get("outcome"), values=req.get("values"),
                      words=req.get("words") or "", chip=bool(req.get("outcome")), always=bool(req.get("always")), now=now)
    if a == "ask_undo":
        return {"ask": public(undo(aid, answer_id=answer_id, person=person, now=now)), "message": "Undone: it waits for your answer again"}
    if a == "ask_dismiss":
        dismiss(aid, answer_id=answer_id, person=person, via=via, words=req.get("words") or "", source=req.get("source_key"), now=now)
        return {"message": "Dismissed"}
    if a == "ask_later":
        x = later(aid, answer_id=answer_id, person=person, until=req.get("until"), words=req.get("words") or "", via=via,
                  source=req.get("source_key"), now=now)
        return {"message": f"Put off until {dt.datetime.fromtimestamp(x['wake']).astimezone().strftime('%a %d %b, %H:%M')}", "wake": x["wake"]}
    if a == "ask_group":
        return group_answer(str(req.get("kind") or ""), answer_id=answer_id, person=person, via=via, outcome=req.get("outcome"),
                            ids=req.get("ids"), overrides=req.get("overrides"), now=now)
    if a == "ask_rule_save":
        return {"rule": rule_save(req.get("rule") or {}, person, now), "message": "Rule kept: it applies from the next question of its kind"}
    if a == "ask_rule_delete":
        return {**rule_delete(str(req.get("rule_id") or ""), person), "message": "Rule removed: that kind asks you again"}
    if a == "ask_stop":
        return {"stop": STOP_HOOK[0](bool(req.get("on")), person) if STOP_HOOK[0] else stop_set(bool(req.get("on")), person)}
    if a == "ask_undo_action":
        return {**undo_action(str(req.get("undo_id") or ""), person, now), "message": "Undone"}
    raise ValueError(f"unknown action {a}")


STOP_HOOK = [None]      # fn(on, person) -> the stop record: the runner pauses and resumes what it holds (ops/missions.py)


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["list"])[0]
    if cmd == "rules":
        print(json.dumps(rules(), indent=1))
    elif cmd == "stop":
        print(json.dumps(stop_state(), indent=1))
    else:
        for x in listing(("open", "escalated", "snoozed")):
            print(f"{x['status']:9} {x['kind']:16} {TC.cut(x['question'], 100)}")   # cap: preview (a terminal line; the app has it whole)
