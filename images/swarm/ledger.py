"""The Ledger: every agent-produced artifact, its append-only history and its generic lifecycle (requirements SWM-03 to
SWM-09, SWM-30 to SWM-39, SWM-41, SWM-60, SWM-61, SWM-66 to SWM-68). Pure: SQLite and the standard library, no HTTP.

One write = one transaction: the event(s) are appended and the current state (the `artifacts` row) is updated by the
same `apply()` that `rebuild()` replays, so the state is always what the events say (SWM-30). Every write carries an
idempotency key (SWM-31); an update names the version it read (SWM-32). Actors are {"id", "cls"} with cls agent,
owner, checker or system; the service sets them from the caller's identity, never from arguments (SWM-23).
"""
import json
import math
import re
import sqlite3
import time
from collections import Counter
from textcap import bounded_json, cut
import textcap as TC                    # visible caps and input limits (AGENTS.md, truncation)

MAIN = ("draft", "open", "ready", "active", "checking", "done")
SIDE = ("blocked", "snoozed", "declined", "merged", "gone")
STATES = MAIN + SIDE
CLOSED = {"done", "declined", "merged", "gone"}           # not "open" for the ranking
SETTLED = {"done", "merged", "gone"}                      # not compared by the duplicate guard: a declined idea is (the owner said no)
LABELS = ("public", "internal", "private")
WAY_OUT = {"fetch", "browser", "phone"}                   # tools that can send data to a third party (SWM-67)
PRIVATE_TOOLS = {"memory", "mail", "files", "house"}     # tools that read the owner's private data (review SWM-R2)
CHECKS = {"health_issue_absent", "log_count", "test_passes", "metric", "ci_green", "smoke_ok", "owner_confirms"}
SIMILAR = 0.20          # TF-IDF cosine that catches every known duplicate of 2026-10-29 (docs/SWARM-PHASE0.md)
PACK_CHARS = 12000      # SWM-60
OPEN_STATES = ("draft", "open", "ready", "active", "checking", "blocked")
# limit: refuses, an agent's steps into other agents' lanes per day unless its card's budgets say otherwise (SWM-109)
HELPS_PER_DAY = 3
# limit: refuses, evidence this close (TF-IDF cosine) to what the artifact already holds repeats it (SWM-109)
HELP_SAME = 0.6
# limit: refuses, a step into another agent's lane says in this many characters why its owner would not see it (SWM-109)
UNSEEN_MIN = 20
TEAM_RULE = ("Each agent is responsible for its own lane first, and for the team's goals too. Get involved in another "
             "agent's lane only when you see a clear, valuable contribution its owner would not see or has missed before; "
             "staying out is often the responsible choice. swarm_context(agent=<id>) shows any agent's role and work.")   # SWM-108
LESSON_DAYS = 90        # SWM-61
LINKS = {"duplicates", "relates", "blocks", "caused_by", "fixes", "supersedes", "implements", "different_from", "merged_into",
         "depends_on", "part_of"}                         # a task depends_on another task and is part_of its idea (SWM-91)
LEASE_H = 4                                               # SWM-92: a lease nobody refreshes ends after this many hours
# limit: refuses, a plan's tasks on the Ledger, with the limit
TASKS_MAX = 8
WATCH_DAYS = 14                                           # SWM-18: a shipped agent change is watched this long
# limit: refuses, an experiment's verdict needs at least this many settled replay examples (it says how many it had)
MIN_EXAMPLES = 4
RUN_LABELS = ("failed", "declined", "duplicate", "pending", "proven", "gone", "no_output")   # worst first (SWM-82)
METRICS = ("valid", "keeps_proven", "avoids_declined", "avoids_duplicates", "no_noise")      # replay scores (SWM-18)
CHANGES = ("instructions", "tools", "model", "harness")   # what an agent change may change (SWM-70)
REQ_STATE = {"proposed": "draft", "planned": "ready", "partial": "open", "violated": "open", "implemented": "done", "deprecated": "gone"}
DUP_RE = re.compile(r"(?i)duplicate|merged into|same as|copy of")
CLAIM_OUT = re.compile(r"(?i)\b(proposed|created|opened|filed|added|wrote)\b")
NONE_RE = re.compile(r"(?i)\b(no|nothing|none|zero|0)\b")
# MAST (Cemri et al., arXiv 2503.13657): 3 categories, 14 failure modes (SWM-84)
MAST = {"FM-1.1": ("FC1", "disobey task specification"), "FM-1.2": ("FC1", "disobey role specification"),
        "FM-1.3": ("FC1", "step repetition"), "FM-1.4": ("FC1", "loss of conversation history"),
        "FM-1.5": ("FC1", "unaware of termination conditions"), "FM-2.1": ("FC2", "conversation reset"),
        "FM-2.2": ("FC2", "fail to ask for clarification"), "FM-2.3": ("FC2", "task derailment"),
        "FM-2.4": ("FC2", "information withholding"), "FM-2.5": ("FC2", "ignored other agent's input"),
        "FM-2.6": ("FC2", "reasoning-action mismatch"), "FM-3.1": ("FC3", "premature termination"),
        "FM-3.2": ("FC3", "no or incomplete verification"), "FM-3.3": ("FC3", "incorrect verification")}
MAST_RULES = [(m, re.compile(p, re.I)) for m, p in (           # first match wins; matched against the label's reason
    ("harness", r"usage limit|hit your limit|timed? ?out|not reachable|connection (refused|reset)|traceback|\b\w+(error|exception)\b:"),
    ("FM-1.1", r"evidence is empty|is incomplete|needs (a|an|at least|one|two)\b|is required|SWM-38|SWM-44"),
    ("FM-1.2", r"contact policy|SWM-51|SWM-06|not (your|its|his) (job|role|area)|not mine|wrong agent|another agent'?s"),
    ("FM-1.3", r"duplicate|merged into|same as|copy of|already (proposed|exists|open|known|there)|in new words|near-identical|repeat"),
    ("FM-2.6", r"said it .* but|claims? .* but|wrote nothing|did nothing it said"),
    ("FM-1.5", r"never finished|no swarm_finish|without a finish"),
    ("FM-2.5", r"unanswered|expired|ignored (the|a|its) (request|answer|input)|did not answer"),
    ("FM-3.3", r"reopened|still broken|did(n't| not) work|does(n't| not) work|not fixed|came back|check failed|wrong fix|incorrect|is wrong|not true|false (positive|alarm)"),
    ("FM-3.2", r"no evidence|unverified|not verified|untested|without (a )?test|guess|speculat|unproven|not checked|no proof"),
    ("FM-2.2", r"unclear|vague|ambiguous|what do you mean|not specific|too general|clarif"),
    ("FM-2.3", r"off.?topic|out of scope|unrelated|not what (i|he) asked|derail|irrelevant|not relevant|not needed|no need|nobody needs"),
    ("FM-3.1", r"half[- ]done|unfinished|stopped (early|half)|partial|missing (part|step)s?|gave up"),
    ("FM-1.1", r"low value|not worth|no (bug or )?real cost|costs nothing|too (big|large|much)|overkill|working,? rarely broken|only;"))]

A, O, C, S, R = "agent", "owner", "checker", "system", "rule"   # R: an autonomy rule the owner enabled (SWM-42)
WIP = {"idea": 2}                                         # SWM-40: at most this many active at once, per kind
RULE_KINDS = {"idea"}                                     # a rule may start ideas (a build still needs the owner's tap to deploy)
RULE_FORBIDDEN = ("purchase", "buy", "pay", "money", "password", "delete", "phone setting", "nas", "deploy")
# (from, to) -> actor classes allowed (SWM-04, SWM-06, SWM-37). Not listed = refused.
T = {}
for _f, _t, _who in (
        ("draft", "open", {A, O}), ("open", "ready", {A, O, R}), ("ready", "open", {A, O}), ("open", "draft", {A, O}),
        ("ready", "active", {O, R}), ("active", "checking", {S, O}), ("active", "open", {A, S, O}),
        ("checking", "done", {C}), ("checking", "open", {C, O}), ("done", "open", {A, C, O}),
        ("blocked", "open", {A, O}), ("snoozed", "open", {A, O, S}), ("declined", "open", {A, O}), ("gone", "open", {A, C, O})):
    T[(_f, _t)] = _who
for _f in ("draft", "open", "ready", "active", "checking"):
    T[(_f, "blocked")] = {A, O}
T[("done", "open")] = {A, C, O}                           # a regression reopens (SWM-47)
for _f in ("open", "ready", "blocked"):
    T[(_f, "snoozed")] = {O}
for _f in ("draft", "open", "ready", "blocked"):
    T[(_f, "declined")] = {O}
    T[(_f, "merged")] = {A, O}
for _f in ("draft", "open", "ready", "blocked", "snoozed"):
    T[(_f, "gone")] = {A, C, O}              # the owner too: "already done by hand" is gone, not declined

# definition of ready per kind (SWM-38); kinds not listed need a title and a body
READY = {
    "idea": ("problem statement (body of 40+ characters)", "two evidence entries or one health alert",
             "a plan naming files and a test", "a success check of a known type", "confidence medium or high"),
    "finding": ("problem statement (body of 40+ characters)", "one evidence entry"),
    "agent_change": ("the agent it changes (plan.agent)", "what changes (plan.change: instructions, tools, model or harness)",
                     f"a target score (plan.target.score: one of {', '.join(METRICS)})", "one evidence entry"),
}
IMPACT = {"low": 1, "medium": 2, "high": 3}
CONF = {"low": 0.3, "medium": 0.6, "high": 0.9}
EFFORT = {"small": 1, "medium": 2, "large": 3}

SCHEMA = [  # numbered, forward-only migrations (SWM-76)
    """
    create table meta(k text primary key, v text);
    create table artifacts(id integer primary key, kind text not null, key text not null, title text, body text,
      plan text, state text not null, version integer not null, owner text, label text not null, origin text,
      impact text, confidence text, effort text, recurrence integer default 0, pinned integer default 0, "check" text,
      snooze_until real, created real, updated real, unique(kind, key));
    create table versions(artifact_id integer, version integer, title text, body text, plan text, actor text, ts real,
      primary key(artifact_id, version));
    create table events(seq integer primary key autoincrement, artifact_id integer, actor text, cls text, via text,
      run text, kind text not null, payload text, reason text, ts real);
    create index events_artifact on events(artifact_id, seq);
    create trigger events_append_only_u before update on events begin select raise(abort, 'events are append-only'); end;
    create trigger events_append_only_d before delete on events begin select raise(abort, 'events are append-only'); end;
    create table evidence(id integer primary key, artifact_id integer, seq integer, actor text, run text, text text,
      ref text, origin text, label text, alert integer default 0, ts real);
    create table links(src integer, dst integer, rel text, reason text, actor text, ts real, primary key(src, dst, rel));
    create table refs(artifact_id integer, system text, ref text, primary key(artifact_id, system, ref));
    create table watchers(artifact_id integer, agent text, primary key(artifact_id, agent));
    create table writes(idem text primary key, actor text, result text, ts real);
    create table cursors(agent text primary key, seq integer);
    create table paused(agent text primary key, by text, ts real);
    """,
    """
    create table rules(id integer primary key, kind text, owner_agent text, conditions text, title text, created_by text,
      ts real, withdrawn real);
    create table refusals(id integer primary key, ts real, actor text, op text, reason text);
    create index refusals_actor on refusals(actor, ts);
    """,
    """
    create table messages(id integer primary key, mid text unique, sender text, sender_cls text, recipients text, context text,
      reply_to text, act text, text text, artifact_id integer, priority text, expires real, hops integer, label text,
      origin text, state text, state_reason text, ts real, updated real);
    create index messages_context on messages(context, id);
    create index messages_sender on messages(sender, ts);
    create table receipts(mid text, agent text, ts real, primary key(mid, agent));
    """,
    """
    create table leases(id integer primary key, repo text, path text, holder text, task integer, ts real, expires real, released real);
    create index leases_open on leases(repo, released, expires);
    create table runs(run text primary key, agent text, started real, finished real, summary text, ops integer, state text);
    alter table messages add column proposal text;
    """,
    """
    alter table runs add column card text;
    alter table runs add column inputs text;
    alter table runs add column output text;
    alter table runs add column artifacts text;
    alter table runs add column label text;
    alter table runs add column label_reason text;
    alter table runs add column failure text;
    alter table runs add column labelled real;
    create index runs_agent on runs(agent, started);
    create table experiments(id integer primary key, artifact_id integer, version integer, agent text, target text, examples integer,
      baseline text, candidate text, passed integer, why text, detail text, phoenix text, ts real);
    create index experiments_artifact on experiments(artifact_id, id);
    """,
    """
    alter table evidence add column help text;
    create table help_verdicts(seq integer, artifact_id integer, by text, cls text, useful integer, reason text, ts real);
    create index help_verdicts_seq on help_verdicts(seq);
    """,
]
# per-kind transitions that replace the generic ones (a task is moved by the runner as its build goes, SWM-91)
TK = {"task": {("draft", "open"): {A, S}, ("open", "ready"): {S, O}, ("ready", "open"): {S}, ("ready", "active"): {S},
               ("active", "ready"): {S, O}, ("active", "done"): {S}, ("done", "ready"): {S, O},
               **{(f, "gone"): {S, O} for f in ("draft", "open", "ready", "active", "blocked")},
               **{(f, "blocked"): {S, O} for f in ("open", "ready", "active")}, ("blocked", "open"): {S, O}},
      # SWM-18: ready -> active is the owner's Build it, and only after a passed experiment; checking -> done after the watch
      "agent_change": {("draft", "open"): {A, O}, ("open", "draft"): {A, O}, ("open", "ready"): {A, O}, ("ready", "open"): {A, O, S},
                       ("ready", "active"): {O}, ("active", "open"): {S, O}, ("active", "checking"): {S, O}, ("checking", "done"): {C},
                       ("checking", "open"): {C, O}, ("done", "open"): {C, O}, ("declined", "open"): {A, O},
                       **{(f, "declined"): {O} for f in ("draft", "open", "ready")}, **{(f, "gone"): {A, O} for f in ("draft", "open", "ready")}},
      # MEM-17: a memory issue (a dispute on a wiki page) is moved by the Memory Keeper as system; the owner may decide one
      "memory_issue": {("draft", "open"): {S}, ("open", "active"): {S}, ("active", "done"): {S}, ("open", "done"): {S}, ("blocked", "done"): {S, O},
                       ("active", "blocked"): {S}, ("blocked", "active"): {S, O}, ("active", "open"): {S},
                       **{(f, "declined"): {O} for f in ("open", "active", "blocked")}},
      # SWM-20: a requirement's state follows requirements/*.yaml, synced by the runner
      "requirement": {(f, t): {S} for f in set(REQ_STATE.values()) for t in set(REQ_STATE.values()) if f != t}}
PROPOSABLE = {"update", "evidence", "link", "transition"}   # what a propose may carry (SWM-49)
ACTS = ("inform", "request", "propose", "handoff", "ack")
REQ_STATES = ("submitted", "working", "input-required", "completed", "failed", "rejected", "canceled")   # A2A v1.0 task states
# limit: refuses, an agent-only reply chain stops here until the owner or an artifact change joins it (SWM-14)
HOPS = 4
# limit: refuses, messages per sender and per room in an hour (SWM-14: two agents must not flood a room)
PER_HOUR = 20
# limit: refuses, messages in one thread a day (SWM-14)
PER_THREAD_DAY = 50
EXPIRY_H = 24
# limit: refuses, a request or proposal expires within a week at most (review SWM-R16: it was clamped silently)
EXPIRY_MAX_H = 7 * 24
CLAIM_RE = re.compile(r"(?i)\b(owner|the owner|owner)\b.{0,40}\b(approved|agreed|said yes|allowed|wants)\b|\b(urgent|immediately|right now)\b")



def _part(name):
    """PLT-25: a part of this file kept in its own file (<this file's stem>.<part>.py), run here, in this module's namespace,
    where it stood: one namespace as before, so names, patches and tracebacks hold. Not a module of its own."""
    from pathlib import Path
    p = Path(__file__).with_name(name)
    exec(compile(p.read_text(), str(p), "exec"), globals())   # nosemgrep: python-eval-exec -- this module's own part file beside it (PLT-25), never data


class Refused(Exception):
    """A write the rules do not allow; the message says which rule, so the agent can fix and retry."""


# ---------------------------------------------------------------- redaction (SWM-68)
SECRET_RES = [re.compile(p) for p in (
    r"\bsk-[A-Za-z0-9_-]{16,}", r"\bgh[pousr]_[A-Za-z0-9]{20,}", r"\bglpat-[A-Za-z0-9_-]{16,}", r"\bAKIA[0-9A-Z]{16}\b",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}",
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*\S{6,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----")]
# a card is written as one run of digits or in groups of 3 to 6 (4-4-4-4, 4-6-5); a stamp like 20261031-140852 in a
# file name is neither, though its 14 digits pass the Luhn check (FND-93)
CARD_RE = re.compile(r"\b(?:\d{13,19}|\d{3,6}(?:[ -]\d{3,6}){1,5})\b")


def luhn(digits):
    d = [int(x) for x in digits][::-1]
    return sum(x if i % 2 == 0 else (x * 2 - 9 if x * 2 > 9 else x * 2) for i, x in enumerate(d)) % 10 == 0


def redact(text):
    """Blank keys and tokens; refuse a payment card number (it is never stored, not even blanked)."""
    t = str(text or "")
    for m in CARD_RE.finditer(t):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and luhn(digits) and len(set(digits)) > 1:
            raise Refused("a payment card number is never stored in the swarm (SWM-68)")
    for r in SECRET_RES:
        t = r.sub("[redacted]", t)
    return t


# ---------------------------------------------------------------- similarity (SWM-33)
STOP = set("the a an and or of to in for on is are be it its this that with as by not no from at when only one".split())


def toks(s):
    return [w for w in re.findall(r"[a-z0-9]+", str(s or "").lower()) if w not in STOP and len(w) > 2]


def tfidf(docs):
    """{id: text} -> {id: unit vector}: the same weighting phase 0 calibrated (ops/swarm-probes/dupes.py)."""
    tok = {i: toks(t) for i, t in docs.items()}
    df = Counter(w for t in tok.values() for w in set(t))
    n = len(tok)
    out = {}
    for i, t in tok.items():
        v = {w: (1 + math.log(c)) * math.log((n + 1) / df[w]) for w, c in Counter(t).items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        out[i] = {w: x / norm for w, x in v.items()}
    return out


def cosine(a, b):
    return sum(x * b.get(w, 0) for w, x in a.items())


def check_shape(c):
    """What each check type needs (SWM-44); the Checker also makes sure what it names exists (SWM-45)."""
    t = c.get("type")
    if t == "health_issue_absent" and not (c.get("keys") or c.get("key") or c.get("kind")):
        return "health_issue_absent needs keys, key or kind"
    if t == "log_count" and not (c.get("container") and c.get("pattern")):
        return "log_count needs container and pattern"
    if t == "test_passes" and not c.get("nodeid"):
        return "test_passes needs nodeid"
    if t == "metric" and not (c.get("name") and c.get("op")):
        return "metric needs name and op"
    if t == "owner_confirms" and not str(c.get("why") or "").strip():
        return "owner_confirms needs why no other type can check it"
    return None


def max_label(*labels):
    return max((x for x in labels if x in LABELS), key=LABELS.index, default="internal")


def card_hash(card):
    """The same hash as ops/registry.py card_hash (SWM-25): a run records the card it ran with."""
    import hashlib
    return hashlib.sha256(json.dumps(card, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def classify(label, reason):
    """SWM-84: a failed, declined or duplicate run -> its MAST failure mode, from the reason its label carries (the
    owner's decline reason, the refusal, the reopen). A harness error (usage limit, crash) is not an agent failure."""
    if label not in ("failed", "declined", "duplicate"):
        return None
    if label == "duplicate":
        return {"mode": "FM-1.3", "category": "FC1", "name": MAST["FM-1.3"][1], "why": str(reason or "")}
    for mode, rx in MAST_RULES:
        if rx.search(str(reason or "")):
            if mode == "harness":
                return {"mode": "harness", "category": "harness", "name": "harness error (not an agent failure)", "why": str(reason)}
            return {"mode": mode, "category": MAST[mode][0], "name": MAST[mode][1], "why": str(reason)}
    return {"mode": "unclassified", "category": "unclassified", "name": "unclassified", "why": str(reason or "")}


def gate(baseline, candidate, target):
    """SWM-18: an agent change ships only when no replay score drops and its target score rises. -> (passed, why)."""
    drops = [f"{m} {baseline[m]:.2f} -> {candidate[m]:.2f}" for m in METRICS
             if baseline.get(m) is not None and candidate.get(m) is not None and candidate[m] < baseline[m]]
    if target is None:                                 # TSK-28: the owner's own change (a model, tools): nothing may get worse
        return (False, "a score dropped: " + "; ".join(drops)) if drops else (True, "no replay score dropped")
    b, c = baseline.get(target), candidate.get(target)
    if b is None or c is None:
        return False, f"the target score {target} has no replay examples to measure it"
    if drops:
        return False, "a score dropped: " + "; ".join(drops)
    if c <= b:
        return False, f"the target score {target} did not rise ({b:.2f} -> {c:.2f})"
    return True, f"{target} rose {b:.2f} -> {c:.2f} and no score dropped"


_part("ledger.work.py")   # the task graph to the scorecards, a mixin (PLT-25)


class Ledger(_LedgerWork):
    def __init__(self, path, cards=None, now=time.time, registry=None):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self.db.execute("pragma foreign_keys=on")
        self.now = now
        self.cards = {c["id"]: c for c in (cards or [])}
        self.registry = registry or {}
        self.migrate()

    # ------------------------------------------------------------ schema
    def migrate(self):
        have = 0
        if self.db.execute("select 1 from sqlite_master where name='meta'").fetchone():
            have = int(self.db.execute("select v from meta where k='schema'").fetchone()[0])
        for n, sql in enumerate(SCHEMA[have:], start=have + 1):
            self.db.executescript("begin;" + sql + f"; insert or replace into meta values('schema', '{n}'); commit;")
        return len(SCHEMA)

    def tx(self):
        return _Tx(self.db)

    # ------------------------------------------------------------ identity and rights
    def check_actor(self, actor):
        if actor.get("cls") not in (A, O, C, S, R):
            raise Refused("unknown actor class")
        if actor["cls"] == A:
            if actor["id"] not in self.cards:
                raise Refused(f"agent {actor['id']} has no card in config/agents.yaml")
            if self.db.execute("select 1 from paused where agent in (?, '*')", (actor["id"],)).fetchone():
                raise Refused(f"agent {actor['id']} is paused by the owner (SWM-26)")

    def sees(self, agent_id, row):
        """SWM-67: private content never reaches an agent whose card holds a way out."""
        if agent_id is None or row["label"] != "private":
            return True
        card = self.cards.get(agent_id) or {}
        return not (WAY_OUT & set(card.get("tools") or []))

    # ------------------------------------------------------------ events
    def _event(self, artifact_id, actor, kind, payload, reason=""):
        cur = self.db.execute("insert into events(artifact_id, actor, cls, via, run, kind, payload, reason, ts) values(?,?,?,?,?,?,?,?,?)",
                              (artifact_id, actor["id"], actor["cls"], actor.get("via", ""), actor.get("run", ""), kind,
                               json.dumps(payload, ensure_ascii=False, sort_keys=True), reason, self.now()))
        seq = cur.lastrowid
        apply(self.db, {"seq": seq, "artifact_id": artifact_id, "actor": actor["id"], "cls": actor["cls"], "run": actor.get("run", ""),
                        "kind": kind, "payload": payload, "reason": reason, "ts": self.now()})
        return seq

    def _close_requests(self, actor, aid, what):
        """A request about an artifact is completed when its receiver works on that artifact (SWM-12)."""
        if actor.get("cls") != A or not aid:
            return
        self.db.execute("update messages set state='completed', state_reason=?, updated=? where artifact_id=? and state in "
                        "('submitted','working','input-required') and recipients like ?", (f"{actor['id']} {what}", self.now(), aid, f'%"{actor["id"]}"%'))

    @staticmethod
    def _key(idem, actor):
        """A key is its author's own (review SWM-R3): the scout's "upsert-1" never answers with main's write, and no agent can
        take a key the runner will use."""
        return f"{actor['id']}\x1f{idem}"

    def _seen(self, idem, actor):
        """The result this author's key already has: its own row, or one written before keys were scoped (the same author)."""
        r = (self.db.execute("select result from writes where idem=?", (self._key(idem, actor),)).fetchone()
             or self.db.execute("select result from writes where idem=? and actor=?", (idem, actor["id"])).fetchone())
        return json.loads(r[0]) if r else None

    def _idem(self, idem, actor):
        if not idem:
            raise Refused("every write needs an idempotency key (idem)")
        return self._seen(idem, actor)

    def _done(self, idem, actor, result):
        self.db.execute("insert into writes values(?,?,?,?)", (self._key(idem, actor), actor["id"], json.dumps(result), self.now()))
        return result

    # ------------------------------------------------------------ writes
    def upsert(self, actor, idem, kind, key, title, body="", plan=None, evidence=(), impact=None, confidence=None,
               effort=None, check=None, label="internal", origin=None, base_version=None, different_from=(), refs=(),
               owner=None, guard=True, unseen=None):
        """Create by (kind, key) or update it (SWM-03, SWM-05, SWM-33). Returns {id, version, created, similar}.
        owner and guard=False are for the system's one-way migration of old records only (SWM-35)."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        if (owner is not None or not guard) and actor["cls"] != S:
            raise Refused("owner and guard are for the system's migration only")
        if not re.match(r"^[a-z_]+$", kind or "") or not key or not str(title or "").strip():
            raise Refused("kind, key and title are required")
        if label not in LABELS:
            raise Refused(f"label must be one of {list(LABELS)}")
        if check is not None and (not isinstance(check, dict) or check.get("type") not in CHECKS):
            raise Refused(f"check.type must be one of {sorted(CHECKS)}")
        if check is not None and (bad := check_shape(check)):
            raise Refused(f"the success check is incomplete (SWM-44): {bad}")
        for v, ok in ((impact, IMPACT), (confidence, CONF), (effort, EFFORT)):
            if v is not None and v not in ok:
                raise Refused(f"{v!r} is not one of {list(ok)}")
        title, body = redact(title), redact(body)
        plan = json.loads(redact(json.dumps(plan))) if plan is not None else None
        origin = origin or f"agent:{actor['id']}" if actor["cls"] == A else (origin or actor["cls"])
        with self.tx():
            row = self.db.execute("select * from artifacts where kind=? and key=?", (kind, key)).fetchone()
            self._guard_kind(actor, kind, plan, row)
            similar = []
            if row is None:
                similar = self.similar(kind, f"{title} {body}")
                excused = {int(d["id"]) for d in different_from if str(d.get("reason") or "").strip()}
                blocking = [s for s in similar if s["id"] not in excused]
                if blocking and guard:
                    # SWM-67 (review SWM-R2): the refusal names only what the writer may see; a private one still blocks, unnamed
                    me = actor["id"] if actor["cls"] == A else None
                    shown = [b for b in blocking if self.sees(me, self._get_row(b["id"]))]
                    hidden = len(blocking) - len(shown)
                    raise Refused("similar open artifacts exist: update, merge or link them as different with a reason: "
                                  + json.dumps(shown) + (f" (and {hidden} you may not read: ask the owner, or link it as different "
                                                         "by its id if you know it)" if hidden else ""))
                aid = self.db.execute("insert into artifacts(kind, key, state, version, label, created) values(?,?,?,?,?,?)",
                                      (kind, key, "draft", 0, label, self.now())).lastrowid
                self._event(aid, actor, "create", {"kind": kind, "key": key, "title": title, "body": body, "plan": plan,
                                                   "impact": impact, "confidence": confidence, "effort": effort, "check": check,
                                                   "label": label, "origin": origin, "owner": owner or actor["id"]})
                for d in different_from:
                    self._link(actor, aid, int(d["id"]), "different_from", d.get("reason", ""))
                created = True
            else:
                aid = row["id"]
                if base_version is not None and int(base_version) != row["version"]:
                    raise Refused(f"artifact {aid} is at version {row['version']}, not {base_version}: read it, merge, retry")
                changes = {k: v for k, v in (("title", title), ("body", body), ("plan", plan), ("impact", impact),
                                             ("confidence", confidence), ("effort", effort), ("check", check)) if v not in (None, "")}
                if (("plan" in changes or "check" in changes) and row["state"] in ("active", "checking", "done")
                        and actor["cls"] not in (O, S)):           # review SWM-R7: an easier check would "prove" it
                    raise Refused("the owner approved this plan and its check: reopen it (or ask the owner) to change them")
                changes["label"] = max_label(row["label"], label)
                help = self._help(actor, row, unseen, body or "")
                self._event(aid, actor, "update", {**changes, **({"help": help} if help else {})})
                created = False
            for e in evidence:
                self._evidence(actor, aid, e)
            for sysname, ref in refs:
                self._event(aid, actor, "ref", {"system": sysname, "ref": ref})
            v = self.db.execute("select version from artifacts where id=?", (aid,)).fetchone()[0]
            if not created:
                self._close_requests(actor, aid, f"refined it to version {v}")
            return self._done(idem, actor, {"id": aid, "version": v, "created": created, "similar": similar})

    def _guard_kind(self, actor, kind, plan, row):
        """SWM-70: no agent writes an agent change about itself; SWM-20: requirements come from requirements/*.yaml."""
        if kind == "requirement" and actor["cls"] != S:
            raise Refused("requirements come from requirements/*.yaml, synced by the runner (SWM-20): add evidence to one, "
                          "or link the idea that fixes it")
        if kind != "agent_change":
            return
        old = json.loads(row["plan"]) if row is not None and row["plan"] else {}
        p = plan if isinstance(plan, dict) else {}
        agent = p.get("agent") or old.get("agent")
        if row is None and agent not in self.cards:
            raise Refused(f"an agent change names the agent it changes (plan.agent: one of {', '.join(sorted(self.cards))})")
        if actor["cls"] == A and actor["id"] in (agent, old.get("agent")):
            raise Refused(f"{actor['id']} may not change its own card, instructions, tools or model (SWM-70): the Coach or the "
                          "owner writes that agent change, and it ships only after its experiment")
        bad = sorted(set((p.get("change") or {}).keys()) - set(CHANGES)) if isinstance(p.get("change"), dict) else []
        if bad:
            raise Refused(f"plan.change may change only {', '.join(CHANGES)}, not {', '.join(bad)}")
        t = (p.get("target") or {}).get("score") if isinstance(p.get("target"), dict) else None
        if t is not None and t not in METRICS:
            raise Refused(f"plan.target.score must be one of {', '.join(METRICS)}")

    def add_evidence(self, actor, idem, artifact_id, text, ref="", origin=None, label="internal", alert=False, unseen=None):
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        with self.tx():
            help = self._help(actor, self._get_row(artifact_id), unseen, text)
            self._evidence(actor, artifact_id, {"text": text, "ref": ref, "origin": origin, "label": label, "alert": alert, "help": help})
            self._close_requests(actor, artifact_id, "added evidence")
            return self._done(idem, actor, {"id": artifact_id})

    def _evidence(self, actor, aid, e):
        e = e if isinstance(e, dict) else {"text": str(e)}
        if not str(e.get("text") or "").strip():
            raise Refused("an evidence entry needs text")
        label = e.get("label") or "internal"
        if label not in LABELS:
            raise Refused(f"label must be one of {list(LABELS)}")
        origin = e.get("origin") or (f"agent:{actor['id']}" if actor["cls"] == A else actor["cls"])
        self._event(aid, actor, "evidence", {"text": cut(redact(e["text"]), 4000), "ref": TC.cut(redact(e.get("ref") or ""), 400),  # cap: untrusted
                                             "origin": origin, "label": label, "alert": bool(e.get("alert")),
                                             **({"help": e["help"]} if e.get("help") else {})})

    def _help(self, actor, row, unseen, text=""):
        """SWM-109, lane discipline: an agent's own tool call (MCP) on another agent's artifact is a help. It names why the
        artifact's owner would not see it (unseen), it does not repeat what the artifact already holds, and it fits the
        agent's day (budgets.helps_per_day on its card, else HELPS_PER_DAY). -> the help record its event carries, or None
        when the write is no help: its own work, or a write by the system, the checker, the owner, or the stack's code for
        a host agent (the runner), whose reason is in the code."""
        owner = row["owner"] or ""
        if actor["cls"] != A or actor.get("via") != "mcp" or owner in ("", "system", actor["id"]):
            return None
        if len(str(unseen or "").strip()) < UNSEEN_MIN:
            raise Refused(f"#{row['id']} is {owner}'s work: say in unseen why {owner} would not see this (at least {UNSEEN_MIN} "
                          "characters), or stay out of its lane (SWM-109)")
        held = [r[0] for r in self.db.execute("select text from evidence where artifact_id=?", (row["id"],))]
        if text and held:
            docs = {i + 1: t for i, t in enumerate(held)}
            docs[0] = text
            vec = tfidf(docs)
            best = max(cosine(vec[0], vec[i]) for i in docs if i)
            if best >= HELP_SAME:  # limit: refuses, as HELP_SAME above
                raise Refused(f"#{row['id']} already holds this (similarity {best:.2f}): a help brings something new (SWM-109)")
        per_day = int(((self.cards.get(actor["id"]) or {}).get("budgets") or {}).get("helps_per_day", HELPS_PER_DAY))
        used = self.db.execute("select count(*) from events where actor=? and ts>? and json_extract(payload, '$.help') is not null",
                               (actor["id"], self.now() - 86400)).fetchone()[0]
        if used >= per_day:
            raise Refused(f"{actor['id']} has used its {per_day} steps into other agents' lanes today: keep it for your own work, "
                          "or tell the owner (SWM-109)")
        return {"owner": owner, "unseen": cut(redact(str(unseen).strip()), 2000)}  # cap: untrusted

    def help_verdict(self, actor, idem, seq, useful, reason=""):
        """SWM-109: the agent whose work was helped, or the owner, says whether a help was useful (the owner's word stands
        over the agent's)."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        e = self.db.execute("select artifact_id, actor, payload from events where seq=?", (int(seq),)).fetchone()
        if e is None or not json.loads(e["payload"] or "{}").get("help"):
            raise Refused(f"event {seq} is not a help (a step into another agent's lane)")
        row = self._get_row(e["artifact_id"])
        if actor["cls"] != O and not (actor["cls"] == A and actor["id"] == row["owner"]):
            raise Refused(f"only {row['owner']} (whose work it helped) or the owner judges this help")
        with self.tx():
            self._event(row["id"], actor, "help_verdict", {"seq": int(seq), "useful": bool(useful), "helper": e["actor"]},
                        cut(redact(str(reason or "")), 2000))  # cap: untrusted: the owner's reason is limited before (swarm_client)
            return self._done(idem, actor, {"seq": int(seq), "useful": bool(useful)})

    def helps(self, days=30, helper=None, owner=None):
        """SWM-109: the steps into other agents' lanes in the window, each with its verdict (the owner's over the owner
        agent's) and, without one, what became of the work after it: moved on (ready, active, shipped, proved) counts as
        useful, dropped (declined, gone) as not useful, else it is pending."""
        out = []
        for e in self.db.execute("select seq, artifact_id, actor, kind, payload, reason, ts from events where ts>? and "
                                 "json_extract(payload, '$.help') is not null order by seq", (self.now() - days * 86400,)):
            p = json.loads(e["payload"])
            if (helper and e["actor"] != helper) or (owner and p["help"].get("owner") != owner):
                continue
            v = self.db.execute("select by, cls, useful, reason from help_verdicts where seq=? order by (cls='owner') desc, ts desc limit 1",
                                (e["seq"],)).fetchone()
            moved = self.db.execute("select json_extract(payload, '$.to') from events where artifact_id=? and kind='transition' and seq>? "
                                    "order by seq", (e["artifact_id"], e["seq"])).fetchall()
            tos = [m[0] for m in moved]
            outcome = "moved on" if set(tos) & {"ready", "active", "checking", "done"} else "dropped" if set(tos) & {"declined", "gone"} else None
            useful = bool(v["useful"]) if v else True if outcome == "moved on" else False if outcome == "dropped" else None
            art = self.db.execute("select label from artifacts where id=?", (e["artifact_id"],)).fetchone()
            label = "private" if "private" in (p.get("label"), art["label"] if art else None) else (p.get("label") or "")
            out.append({"seq": e["seq"], "artifact_id": e["artifact_id"], "helper": e["actor"], "owner": p["help"].get("owner"), "kind": e["kind"],
                        "label": label,                  # review 10 Nov (REST2-R1): the help's text keeps its label to the reader
                        "text": p.get("text") or e["reason"] or "", "unseen": p["help"].get("unseen", ""), "ts": e["ts"],
                        "verdict": None if not v else ("useful" if v["useful"] else "not useful"), "verdict_by": v["by"] if v else None,
                        "outcome": outcome, "useful": useful})
        return out

    def transition(self, actor, idem, artifact_id, to, reason, evidence=(), target=None, snooze_until=None):
        """Move a state (SWM-04, SWM-06, SWM-37 to SWM-39); every refusal names its rule."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        if not str(reason or "").strip():
            raise Refused("every transition needs a reason")
        with self.tx():
            row = self._get_row(artifact_id)
            frm = row["state"]
            allowed = TK[row["kind"]].get((frm, to)) if row["kind"] in TK else T.get((frm, to))
            if allowed is None:
                raise Refused(f"no transition from {frm} to {to} (states: {', '.join(STATES)})")
            if actor["cls"] not in allowed:
                raise Refused(f"{frm} -> {to} is for {', '.join(sorted(allowed))}, not {actor['cls']} (SWM-06)")
            if actor["cls"] == R:
                self.rule_covers(actor.get("rule"), row)
            if row["kind"] == "agent_change":
                self._guard_kind(actor, "agent_change", None, row)
                if to == "active":
                    self._passed(row)
            if to == "active" and row["kind"] in WIP:
                n = self.db.execute("select count(*) from artifacts where kind=? and state='active'", (row["kind"],)).fetchone()[0]
                # limit: waits, work in progress per kind: it stays ready at its rank (SWM-40)
                if n >= WIP[row["kind"]]:
                    raise Refused(f"{n} {row['kind']}s are being built already (work-in-progress limit {WIP[row['kind']]}, SWM-40): "
                                  "it stays ready at its rank")
            for e in evidence:
                self._evidence(actor, artifact_id, e)
            if to == "ready" and actor["cls"] != O:          # the definition gates an agent's claim; the owner decides himself
                missing = self.not_ready(artifact_id)
                if missing:
                    raise Refused("not ready (SWM-38): missing " + "; ".join(missing))
            if frm == "declined" and to == "open" and actor["cls"] == A:
                declined_at = self.db.execute("select max(ts) from events where artifact_id=? and kind='transition' and "
                                              "json_extract(payload, '$.to')='declined'", (artifact_id,)).fetchone()[0] or 0
                if not self.db.execute("select 1 from evidence where artifact_id=? and ts>?", (artifact_id, declined_at)).fetchone():
                    raise Refused("a declined artifact reopens only with evidence newer than the decline (SWM-39)")
            if to == "merged":
                if target is None:
                    raise Refused("merged needs the target artifact")
                self._get_row(target)
                self._link(actor, artifact_id, int(target), "merged_into", reason)
            self._event(artifact_id, actor, "transition", {"from": frm, "to": to, "snooze_until": snooze_until,
                                                          "reopen": to == "open" and frm in ("done", "gone", "declined", "snoozed")}, reason)
            if to == "merged":
                for e in self.db.execute("select text, ref, origin, label, alert from evidence where artifact_id=?", (artifact_id,)).fetchall():
                    self._evidence(actor, int(target), {**dict(e), "text": f"(from {artifact_id}) {e['text']}"})
            self._close_requests(actor, artifact_id, f"moved it to {to}")
            return self._done(idem, actor, {"id": artifact_id, "from": frm, "to": to})

    def _passed(self, row):
        """SWM-18: an agent change leaves ready for active only with a passed experiment on its current version."""
        ex = self.db.execute("select version, passed, why from experiments where artifact_id=? order by id desc limit 1", (row["id"],)).fetchone()
        if ex is None:
            raise Refused("an agent change ships only after its experiment on the agent's replay set (SWM-18): none has run yet")
        if ex["version"] != row["version"]:
            raise Refused(f"the agent change changed since its experiment (version {ex['version']}, now {row['version']}): "
                          "the experiment runs again first (SWM-18)")
        if not ex["passed"]:
            raise Refused(f"its experiment did not pass (SWM-18): {ex['why']}")

    def link(self, actor, idem, src, dst, rel, reason=""):
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        if rel not in LINKS:
            raise Refused(f"rel must be one of {sorted(LINKS)}")
        with self.tx():
            help = self._help(actor, self._get_row(src), reason)
            self._get_row(dst)
            self._link(actor, src, dst, rel, reason, help)
            return self._done(idem, actor, {"src": src, "dst": dst, "rel": rel})

    def _link(self, actor, src, dst, rel, reason, help=None):
        if rel == "different_from" and not str(reason or "").strip():
            raise Refused("different_from needs a reason")
        self._event(src, actor, "link", {"dst": dst, "rel": rel, "reason": reason, **({"help": help} if help else {})})

    def add_ref(self, actor, idem, artifact_id, system, ref):
        """Link an outside record (a build, a Forgejo PR, a Kanban task) to an artifact."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        with self.tx():
            self._get_row(artifact_id)
            self._event(artifact_id, actor, "ref", {"system": str(system)[:40], "ref": str(ref)[:200]})  # cap: id
            return self._done(idem, actor, {"id": artifact_id})

    def by_ref(self, system, ref):
        r = self.db.execute("select artifact_id from refs where system=? and ref=?", (system, str(ref))).fetchone()
        return r[0] if r else None

    def covered(self, owner=None):
        """What the open ideas are the fix for (plan.covers: health issue keys, "kind:<detector>"): [{id, state, covers}]."""
        q = "select id, state, plan, updated from artifacts where kind='idea' and state in ('draft','open','ready','active','checking','blocked')"
        args = []
        if owner:
            q += " and owner=?"
            args.append(owner)
        out = []
        for r in self.db.execute(q, args):
            covers = (json.loads(r["plan"]) or {}).get("covers") if r["plan"] else None
            if covers:
                out.append({"id": r["id"], "state": r["state"], "covers": covers, "updated": r["updated"]})   # a key per cycle (SWM-R4)
        return out

    def board(self, kind="idea", agent=None, open_limit=50, recent_limit=12):
        """The owner's list: open and ready artifacts ranked with what he needs to decide, and the latest decided ones."""
        def detail(r):
            ev = self.db.execute("select text, ref, alert from evidence where artifact_id=? order by id", (r["id"],)).fetchall()
            plan = json.loads(r["plan"]) if r["plan"] else {}
            last = self.db.execute("select cls, reason, json_extract(payload, '$.to') to_state, ts from events where artifact_id=? "
                                   "and kind='transition' order by seq desc limit 1", (r["id"],)).fetchone()
            return {**self.summary(r), "body": r["body"], "effort": r["effort"], "impact": r["impact"], "confidence": r["confidence"],
                    "recurrence": r["recurrence"], "created": r["created"], "updated": r["updated"], "evidence": len(ev),
                    "signal": ev[0]["text"] if ev else "", "files": plan.get("files") or [], "test": plan.get("test"),
                    "check": json.loads(r["check"]) if r["check"] else None,
                    "refs": [dict(x) for x in self.db.execute("select system, ref from refs where artifact_id=?", (r["id"],))],
                    "decision": dict(last) if last else None, "merged_from": self.db.execute(
                        "select count(*) from links where dst=? and rel='merged_into'", (r["id"],)).fetchone()[0]}
        rows = [r for r in self.db.execute("select * from artifacts where kind=? and state in ('open','ready')", (kind,)) if self.sees(agent, r)]
        opened = sorted((dict(detail(r), priority=self.priority(r)) for r in rows), key=lambda x: (-x["pinned"], -x["priority"], x["id"]))
        rec = [detail(r) for r in self.db.execute("select * from artifacts where kind=? and state not in ('open','ready','draft') "
                                                   "order by updated desc limit ?", (kind, recent_limit)) if self.sees(agent, r)]  # cap: list (the newest done ones; the board pages further)
        return {"open": opened[:open_limit], "recent": rec}

    def events_since(self, seq, limit=200):
        """For the activity feed (SWM-78): events after seq with their artifact's kind and title."""
        return [dict(r) for r in self.db.execute(
            "select e.seq, e.artifact_id, e.actor, e.cls, e.run, e.kind, e.payload, e.reason, e.ts, a.kind as akind, a.title, a.label "
            "from events e left join artifacts a on a.id=e.artifact_id where e.seq>? order by e.seq limit ?", (int(seq), int(limit)))]  # cap: list (a page of events; the next call goes on after the last seq)

    def watch(self, actor, idem, artifact_id, on=True):
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        with self.tx():
            self._get_row(artifact_id)
            self._event(artifact_id, actor, "watch", {"agent": actor["id"], "on": bool(on)})
            return self._done(idem, actor, {"id": artifact_id, "watching": bool(on)})

    def pin(self, actor, idem, artifact_id, on=True):
        if actor["cls"] != O:
            raise Refused("only the owner pins (SWM-08)")
        if (r := self._idem(idem, actor)) is not None:
            return r
        with self.tx():
            self._get_row(artifact_id)
            self._event(artifact_id, actor, "pin", {"on": bool(on)})
            return self._done(idem, actor, {"id": artifact_id, "pinned": bool(on)})

    def pause(self, actor, agent, on=True):
        if actor["cls"] != O and not (actor["cls"] == S and on):      # the system may pause a failing agent (SWM-71), never resume
            raise Refused("only the owner pauses and resumes agents (SWM-26)")
        with self.tx():
            if on:
                self.db.execute("insert or replace into paused values(?,?,?)", (agent, actor["id"], self.now()))
            else:
                self.db.execute("delete from paused where agent=?", (agent,))
            self._event(None, actor, "pause", {"agent": agent, "on": bool(on)})
        return {"agent": agent, "paused": bool(on)}

    # ------------------------------------------------------------ the Board (SWM-10 to SWM-15, SWM-48 to SWM-56)
    def rooms(self):
        return list((self.registry or {}).get("rooms") or ["all"])

    def recipients(self, sender, to):
        """Addresses -> agent ids (+ "owner"). agent:<id>, role:<tag>, room:<name> (everyone who reads it), artifact:<id>
        (owner, contributors, watchers), owner."""
        out, context = set(), None
        for addr in to:
            kind, _, val = str(addr).partition(":")
            if addr == "owner":
                out.add("owner")
            elif kind == "agent" and val in self.cards:
                out.add(val)
            elif kind == "role":
                hit = {c for c, card in self.cards.items() if val in (card.get("roles") or [])}
                if not hit:
                    raise Refused(f"no agent has the role {val}")
                out |= hit
            elif kind == "room":
                if val not in self.rooms():
                    raise Refused(f"no room {val}; rooms are {', '.join(self.rooms())} (a new room is the owner's, SWM-56)")
                out |= {c for c, card in self.cards.items() if val in (card.get("rooms") or [])}
                out.add("owner")
                context = context or f"room:{val}"
            elif kind == "artifact" and val.isdigit():
                row = self._get_row(int(val))
                out |= {row["owner"]} | {r[0] for r in self.db.execute("select agent from watchers where artifact_id=?", (row["id"],))}
                out |= {r[0] for r in self.db.execute("select distinct actor from events where artifact_id=? and cls='agent'", (row["id"],))}
                out.add("owner")
                context = context or f"artifact:{row['id']}"
            else:
                raise Refused(f"unknown address {addr!r}: agent:<id>, role:<tag>, room:<name>, artifact:<id> or owner")
        out.discard(sender)
        return out, context

    def send(self, actor, idem, to, act, text, artifact_id=None, reply_to=None, expires_h=None, label="internal", origin=None, priority="normal",
             proposal=None):
        """One message. Code guards it (SWM-14, SWM-15, SWM-51, SWM-67); the sender is the caller (SWM-23). A propose may
        carry one Ledger operation ({op: update|evidence|link|transition, args}) on its artifact; it is applied only when
        the artifact's owner accepts it (reply completed, SWM-49)."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        if act not in ACTS:
            raise Refused(f"act must be one of {', '.join(ACTS)}")
        if proposal is not None:
            if act != "propose" or not artifact_id:
                raise Refused("a proposal goes in a propose that names its artifact")
            if not isinstance(proposal, dict) or proposal.get("op") not in PROPOSABLE or not isinstance(proposal.get("args") or {}, dict):
                raise Refused(f"proposal must be {{op: {'|'.join(sorted(PROPOSABLE))}, args: {{...}}}}")
        if label not in LABELS:
            raise Refused(f"label must be one of {list(LABELS)}")
        text = redact(text)
        # limit: refuses, a Board message; the detail belongs in an artifact
        if len(text) > 4000:
            raise Refused(f"a message holds at most 4,000 characters (this one has {len(text):,}): shorten it, or put the detail in an artifact and link it")
        if not text.strip():
            raise Refused("a message needs text")
        me = actor["id"] if actor["cls"] == A else "owner" if actor["cls"] == O else actor["id"]
        to = [to] if isinstance(to, str) else list(to or [])
        parent = self.db.execute("select * from messages where mid=?", (reply_to,)).fetchone() if reply_to else None
        if reply_to and not parent:
            raise Refused(f"no message {reply_to}")
        if parent and not to:
            to = [f"agent:{parent['sender']}" if parent["sender"] in self.cards else "owner"]
        rcpt, ctx = self.recipients(me, to)
        if parent:
            ctx = parent["context"]
        elif not ctx:
            pair = sorted([me] + [r for r in rcpt])[:2] if len(rcpt) == 1 else None  # cap: parse
            ctx = f"dm:{'+'.join(pair)}" if pair else f"group:{'+'.join(sorted([me] + list(rcpt)))[:200]}"  # cap: id
        if artifact_id:
            a = self._get_row(int(artifact_id))
            label = max_label(label, a["label"])
            ctx = ctx if ctx.startswith(("room:", "artifact:")) or parent else f"artifact:{a['id']}"
        if actor["cls"] == A:
            card = self.cards.get(me) or {}
            allowed = set(card.get("contact") or [])
            direct = {x for x in rcpt if x != "owner"}
            if "*" not in allowed and direct - allowed and not ctx.startswith(("room:", "artifact:")):
                raise Refused(f"{me} may not message {', '.join(sorted(direct - allowed))} (its contact policy, SWM-51)")
            if ctx == "room:all" and (act != "inform" or not artifact_id):
                raise Refused("room:all takes only informs that link an artifact; discuss in the artifact's thread (SWM-14)")
            hops = (parent["hops"] + 1) if parent and parent["sender_cls"] == A else 0
            if hops > HOPS:  # limit: refuses, as HOPS above
                raise Refused(f"this reply chain between agents reached {HOPS} hops without the owner or an artifact change (SWM-14)")
            now = self.now()
            # limit: refuses, as PER_HOUR above (per sender; the room's check follows)
            if self.db.execute("select count(*) from messages where sender=? and ts>?", (me, now - 3600)).fetchone()[0] >= PER_HOUR:
                raise Refused(f"{me} sent {PER_HOUR} messages in the last hour (rate limit, SWM-14)")
            if ctx.startswith("room:") and self.db.execute("select count(*) from messages where context=? and sender_cls='agent' and ts>?",
                                                           (ctx, now - 3600)).fetchone()[0] >= PER_HOUR:
                raise Refused(f"{ctx} had {PER_HOUR} agent messages in the last hour (rate limit, SWM-14)")
            # limit: refuses, as PER_THREAD_DAY above
            if self.db.execute("select count(*) from messages where context=? and ts>?", (ctx, now - 86400)).fetchone()[0] >= PER_THREAD_DAY:
                raise Refused(f"{ctx} had {PER_THREAD_DAY} messages today (SWM-14)")
            recent = {r[0]: r[1] for r in self.db.execute("select id, text from messages where sender=? and context=? and ts>?", (me, ctx, now - 86400))}
            if recent:
                vec = tfidf({**{k: v for k, v in recent.items()}, 0: text})
                if any(cosine(vec[0], vec[k]) >= 0.9 for k in recent):
                    raise Refused("a near-identical message is already in this thread today (SWM-14)")
        else:
            hops = 0
        if actor["cls"] == A:                                   # SWM-67: private content never reaches an agent with a way out
            blocked = {r for r in rcpt if r in self.cards and not self.sees(r, {"label": label})}
            if blocked and label == "private":
                rcpt -= blocked
                if not rcpt:
                    raise Refused("private content cannot go to an agent whose card holds a way out (SWM-67)")
        exp = None
        if act in ("request", "propose"):
            h = float(expires_h or EXPIRY_H)
            if h > EXPIRY_MAX_H:  # limit: refuses, as EXPIRY_MAX_H above
                raise Refused(f"a {act} expires within {EXPIRY_MAX_H} hours at most; ask for {EXPIRY_MAX_H} or less and ask again later")
            exp = self.now() + h * 3600
        if act == "handoff":
            if not artifact_id:
                raise Refused("a handoff names the artifact it hands over")
            row = self._get_row(int(artifact_id))
            if actor["cls"] == A and row["owner"] != me:
                raise Refused(f"only the artifact's owner ({row['owner']}) hands it over")
            new_owner = next((r for r in rcpt if r in self.cards), None)
            if not new_owner:
                raise Refused("a handoff goes to one agent")
        mid = f"m{self.now():.6f}{len(text)}".replace(".", "")
        with self.tx():
            self.db.execute("insert into messages(mid, sender, sender_cls, recipients, context, reply_to, act, text, artifact_id, priority, "
                            "expires, hops, label, origin, state, ts, updated, proposal) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (mid, me, actor["cls"], json.dumps(sorted(rcpt)), ctx, reply_to, act, text, artifact_id, priority, exp, hops, label,
                             origin or (f"agent:{me}" if actor["cls"] == A else actor["cls"]),
                             "submitted" if exp else None, self.now(), self.now(),
                             json.dumps(json.loads(redact(json.dumps(proposal))), sort_keys=True) if proposal else None))
            if parent is not None and actor["cls"] == O and parent["state"] in ("submitted", "working", "input-required") \
                    and "owner" in json.loads(parent["recipients"] or "[]"):          # SWM-98: the owner's answer closes his request
                self.db.execute("update messages set state='completed', state_reason='the owner answered', updated=? where mid=?",
                                (self.now(), parent["mid"]))
            if act == "handoff":
                self._event(int(artifact_id), actor, "handoff", {"from": me, "to": new_owner}, f"handed over in {mid}")
                self.db.execute("update artifacts set owner=? where id=?", (new_owner, int(artifact_id)))
            self._event(int(artifact_id) if artifact_id else None, actor, "message", {"mid": mid, "act": act, "context": ctx, "to": sorted(rcpt)},
                        TC.cut(text, 200))  # cap: preview
            return self._done(idem, actor, {"mid": mid, "context": ctx, "recipients": sorted(rcpt), "hops": hops})

    def reply_state(self, actor, idem, mid, state, reason=""):
        """A request's receiver sets its A2A state (SWM-12); the sender may cancel it."""
        self.check_actor(actor)
        if (r := self._idem(idem, actor)) is not None:
            return r
        if state not in REQ_STATES:
            raise Refused(f"state must be one of {', '.join(REQ_STATES)}")
        m = self.db.execute("select * from messages where mid=?", (mid,)).fetchone()
        if not m or not m["state"]:
            raise Refused(f"no request {mid}")
        me = actor["id"] if actor["cls"] == A else "owner" if actor["cls"] == O else actor["id"]
        if me not in json.loads(m["recipients"]) and me != m["sender"] and actor["cls"] not in (S, C):
            raise Refused("only its receivers or its sender change a request")
        if state == "completed" and m["act"] == "propose" and m["proposal"]:
            reason = self._apply_proposal(actor, idem, m, me) + (f": {reason}" if reason else "")
        with self.tx():
            self.db.execute("update messages set state=?, state_reason=?, updated=? where mid=?", (state, cut(str(reason), 2000), self.now(), mid))  # cap: untrusted
            self._event(m["artifact_id"], actor, "request", {"mid": mid, "state": state}, cut(str(reason), 2000))  # cap: untrusted
        return self._done(idem, actor, {"mid": mid, "state": state})

    def _apply_proposal(self, actor, idem, m, me):
        """SWM-49: a propose becomes a Ledger operation only when its artifact's owner accepts it; the owner of the stack
        may accept too. The operation is the acceptor's, with the proposer named in its reason or evidence."""
        row = self._get_row(m["artifact_id"])
        if actor["cls"] != O and row["owner"] != me:
            raise Refused(f"only the artifact's owner ({row['owner']}) accepts a proposal on it; reject it or hand it on")
        p = json.loads(m["proposal"])
        a, op, tag = p.get("args") or {}, p["op"], f"{idem}:apply"
        by = f"proposed by {m['sender']} in {m['mid']}"
        if op == "update":
            self.upsert(actor, tag, row["kind"], row["key"], a.get("title") or row["title"], a.get("body") or "", plan=a.get("plan"),
                        evidence=a.get("evidence") or (), impact=a.get("impact"), confidence=a.get("confidence"), effort=a.get("effort"),
                        check=a.get("check"), base_version=row["version"])
        elif op == "evidence":
            self.add_evidence(actor, tag, row["id"], f"{a.get('text', '')} ({by})", a.get("ref", ""), a.get("origin"), a.get("label", "internal"))
        elif op == "link":
            self.link(actor, tag, row["id"], int(a.get("dst") or 0), a.get("rel"), f"{a.get('reason', '')} ({by})".strip())
        else:
            self.transition(actor, tag, row["id"], a.get("to"), f"{a.get('reason') or 'accepted'} ({by})", target=a.get("target"))
        return f"accepted: {op} applied"

    def expire(self):
        """SWM-50: requests past their expiry are canceled with the reason expired. -> how many."""
        rows = self.db.execute("select mid from messages where state in ('submitted','working','input-required') and expires<?", (self.now(),)).fetchall()
        for (mid,) in rows:
            self.db.execute("update messages set state='canceled', state_reason='expired', updated=? where mid=?", (self.now(), mid))
        return len(rows)

    def waiting(self):
        """Every open request, for the runner's wakes (SWM-13)."""
        self.expire()
        return [dict(r) for r in self.db.execute("select mid, sender, recipients, artifact_id from messages "
                                                 "where state in ('submitted','working','input-required') order by id")]

    def inbox(self, agent, mark=True, limit=50):
        """Unread messages for an agent (the owner's first, SWM-54) and its open requests (SWM-12)."""
        self.expire()
        who = "owner" if agent is None else agent
        rows = [dict(r) for r in self.db.execute("select * from messages where recipients like ? order by id desc limit 500", (f'%"{who}"%',))  # cap: list (the 500 newest messages to one reader)
                if not self.db.execute("select 1 from receipts where mid=? and agent=?", (r["mid"], who)).fetchone()]
        rows = [r for r in rows if agent is None or self.sees(agent, r)]
        rows.sort(key=lambda r: (r["sender_cls"] != O, -r["id"]))
        for r in rows:
            r["claim"] = bool(r["sender_cls"] == A and CLAIM_RE.search(r["text"] or ""))   # SWM-58: an agent's claim, marked
        if mark:
            for r in rows[:limit]:
                self.db.execute("insert or ignore into receipts values(?,?,?)", (r["mid"], who, self.now()))
        open_req = [dict(r) for r in self.db.execute(
            "select mid, sender, recipients, context, text, state, expires, artifact_id from messages where state in ('submitted','working','input-required') "
            "and (recipients like ? or sender=?) order by id", (f'%"{who}"%', who))]
        expired = [dict(r) for r in self.db.execute("select mid, text, state_reason, context from messages where sender=? and state='canceled' "
                                                     "and state_reason='expired' and updated>?", (who, self.now() - 86400))]
        return {"messages": rows[:limit], "open_requests": open_req, "expired": expired}

    def thread(self, agent, context, limit=200):
        rows = [dict(r) for r in self.db.execute("select * from messages where context=? order by id desc limit ?", (context, limit))]  # cap: list (the caller's limit)
        rows = [r for r in rows if agent is None or self.sees(agent, r)]
        for r in rows:
            r["claim"] = bool(r["sender_cls"] == A and CLAIM_RE.search(r["text"] or ""))
        return list(reversed(rows))

    def conversations(self, limit=100):
        """For the Chatroom: every thread with its last message and count (the owner reads everything, SWM-11)."""
        return [dict(r) for r in self.db.execute(
            "with g as (select context, count(*) n, max(id) last_id, max(ts) last_ts, "
            "sum(case when state in ('submitted','working','input-required') then 1 else 0 end) open from messages group by context) "
            "select g.*, m.text last_text, m.sender last_sender from g join messages m on m.id=g.last_id order by g.last_ts desc limit ?", (limit,))]  # cap: list (the caller's limit)

    def feed(self, since):
        """SWM-107, the team room: every event on the shared work and every Board message after `since`, oldest first,
        whole, with each artifact's kind, title and owner (so the app tells a step into another agent's lane from work in
        one's own). The requirements' own events are left out: they mirror requirements/*.yaml, nobody's work."""
        ev = [dict(r) for r in self.db.execute(
            "select e.seq, e.artifact_id, e.actor, e.cls, e.kind, e.payload, e.reason, e.ts, a.kind as akind, a.title, a.owner "
            "from events e left join artifacts a on a.id=e.artifact_id where e.ts>? and coalesce(a.kind, '') <> 'requirement' "
            "order by e.seq", (since,))]
        for e in ev:
            e["payload"] = json.loads(e["payload"]) if e["payload"] else {}
        msgs = [dict(r) for r in self.db.execute(
            "select id, mid, sender, sender_cls, recipients, context, reply_to, act, text, artifact_id, state, state_reason, label, ts "
            "from messages where ts>? order by id", (since,))]
        return {"events": ev, "messages": msgs}

    def origins(self, kind="idea"):
        """Where each artifact of a kind came from (AI Change Requests, step 1): the run and agent that first gave evidence
        for it, how many runs saw it and when first and last. -> [{id, title, state, owner, runs, first_at, last_at,
        first_run, first_actor}]."""
        out = []
        for r in self.db.execute("select a.id, a.title, a.state, a.owner, count(distinct e.run) runs, min(e.ts) first_at, max(e.ts) last_at "
                                 "from artifacts a left join evidence e on e.artifact_id=a.id where a.kind=? group by a.id order by a.id", (kind,)):
            f = self.db.execute("select run, actor from evidence where artifact_id=? and coalesce(run, '') != '' order by ts, id limit 1", (r["id"],)).fetchone()
            out.append({**dict(r), "first_run": f["run"] if f else None, "first_actor": f["actor"] if f else None})
        return out

    def graph(self, days=30):
        """Who works on what and who talks to whom (the Swarm page): agents, artifacts, agent-artifact edges, agent-agent edges."""
        since = self.now() - days * 86400
        who = lambda actor, cls: "owner" if cls == O else actor                    # owner:owner, owner:old-path -> owner
        cnt = {}
        for r in self.db.execute("select actor, cls, artifact_id, count(*) n from events where artifact_id is not null and ts>? "
                                 "and cls in ('agent','rule','checker','owner') group by actor, cls, artifact_id", (since,)):
            k = (who(r["actor"], r["cls"]), r["artifact_id"])
            cnt[k] = cnt.get(k, 0) + r["n"]
        for r in self.db.execute("select a.id, a.owner from artifacts a where a.owner not in ('', 'system') and exists "
                                 "(select 1 from events e where e.artifact_id=a.id and e.ts>?)", (since,)):
            cnt.setdefault((r["owner"], r["id"]), 1)                                  # the agent that proposed it (imported ideas too)
        aa = [{"agent": a, "artifact": x, "n": n} for (a, x), n in sorted(cnt.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))]
        arts = {r["artifact"] for r in aa}
        shared = {}
        for r in aa:
            shared.setdefault(r["artifact"], set()).add(r["agent"])
        talk = {}
        for m in self.db.execute("select sender, recipients from messages where ts>?", (since,)):
            for rc in json.loads(m["recipients"]):
                key = tuple(sorted((m["sender"], rc)))
                talk[key] = talk.get(key, 0) + 1
        art_rows = [self.summary(r) for r in self.db.execute("select * from artifacts where id in (%s)" % ",".join("?" * len(arts)), list(arts))] if arts else []
        return {"agents": sorted({r["agent"] for r in aa} | {x for k in talk for x in k}), "artifacts": art_rows, "touches": aa,
                "shared": {str(k): sorted(v) for k, v in shared.items() if len(v) > 1},
                "talk": [{"a": k[0], "b": k[1], "n": n} for k, n in talk.items()]}

    def history(self, aid, limit=200):
        """An artifact's full timeline: its events and its thread's messages, merged by time (the artifact page)."""
        ev = [dict(r) for r in self.db.execute("select seq, actor, cls, kind, payload, reason, ts from events where artifact_id=? order by seq", (aid,))]
        return {"artifact": self.get(None, aid), "events": ev[-limit:], "thread": self.thread(None, f"artifact:{aid}")}

    # ------------------------------------------------------------ reads
    def _get_row(self, aid):
        row = self.db.execute("select * from artifacts where id=?", (int(aid),)).fetchone()
        if row is None:
            raise Refused(f"no artifact {aid}")
        return row

    def not_ready(self, aid):
        row = self._get_row(aid)
        ev = self.db.execute("select count(*), coalesce(max(alert), 0) from evidence where artifact_id=?", (aid,)).fetchone()
        plan = json.loads(row["plan"]) if row["plan"] else {}
        miss = []
        if not str(row["title"] or "").strip() or len(str(row["body"] or "")) < (40 if row["kind"] in READY else 1):
            miss.append("problem statement (body of 40+ characters)" if row["kind"] in READY else "a body")
        if row["kind"] == "idea":
            if not (ev[0] >= 2 or ev[1]):
                miss.append("two evidence entries or one health alert")
            if not (isinstance(plan, dict) and plan.get("files") and plan.get("test")):
                miss.append("a plan naming files and a test")
            if not row["check"]:
                miss.append("a success check of a known type")
            if row["confidence"] not in ("medium", "high"):
                miss.append("confidence medium or high")
            if self.db.execute("select 1 from artifacts where kind='requirement' limit 1").fetchone():     # SWM-20, once synced
                reqs = [str(x) for x in (plan.get("requirements") or [])] if isinstance(plan, dict) else []
                known = {r[0] for r in self.db.execute("select key from artifacts where kind='requirement' and key in (%s)"
                                                       % ",".join("?" * len(reqs)), reqs)} if reqs else set()
                unknown = [x for x in reqs if x not in known and x != "new"]
                if not reqs or unknown:
                    miss.append("the requirements it serves (plan.requirements: ids like SWM-18, or [\"new\"] for a need no "
                                "requirement covers yet)" + (f"; unknown: {', '.join(unknown)}" if unknown else ""))
        elif row["kind"] == "finding" and ev[0] < 1:
            miss.append("one evidence entry")
        elif row["kind"] == "agent_change":
            ch = plan.get("change") if isinstance(plan, dict) else None
            if not (isinstance(plan, dict) and plan.get("agent") in self.cards):
                miss.append("the agent it changes (plan.agent)")
            if not (isinstance(ch, dict) and any(ch.get(k) for k in CHANGES)):
                miss.append("what changes (plan.change: instructions, tools, model or harness)")
            if not (isinstance(plan, dict) and isinstance(plan.get("target"), dict) and plan["target"].get("score") in METRICS):
                miss.append(f"a target score (plan.target.score: one of {', '.join(METRICS)})")
            if ev[0] < 1:
                miss.append("one evidence entry")
        return miss

    def similar(self, kind, text, limit=5):
        rows = self.db.execute("select id, title, body, state from artifacts where kind=? and state not in (%s)" % ",".join("?" * len(SETTLED)),
                               (kind, *SETTLED)).fetchall()
        if not rows:
            return []
        docs = {r["id"]: f"{r['title']} {r['body']}" for r in rows}
        docs[0] = text
        vec = tfidf(docs)
        scored = sorted(((cosine(vec[0], vec[i]), i) for i in docs if i), reverse=True)
        info = {r["id"]: r for r in rows}
        return [{"id": i, "title": info[i]["title"], "state": info[i]["state"], "similarity": round(s, 3)} for s, i in scored[:limit] if s >= SIMILAR]

    def priority(self, row):
        """SWM-08: impact x confidence x (1 + log2(1 + recurrences in 30 days)) / effort. A recurrence is a reopen, a
        health alert as evidence, or a duplicate merged into it."""
        rec = self.db.execute("select count(*) from events where artifact_id=? and kind in ('transition', 'evidence') and ts>? and "
                              "(json_extract(payload, '$.reopen') = 1 or json_extract(payload, '$.alert') = 1)",
                              (row["id"], self.now() - 30 * 86400)).fetchone()[0]
        rec += self.db.execute("select count(*) from links where dst=? and rel='merged_into' and ts>?",   # a duplicate is a recurrence
                               (row["id"], self.now() - 30 * 86400)).fetchone()[0]
        p = IMPACT.get(row["impact"], 2) * CONF.get(row["confidence"], 0.6) * (1 + math.log2(1 + rec)) / EFFORT.get(row["effort"], 2)
        return round(p, 4)

    def ranked(self, kind=None, states=("open", "ready"), agent=None, limit=50):
        q = "select * from artifacts where state in (%s)" % ",".join("?" * len(states))
        args = list(states)
        if kind:
            q += " and kind=?"
            args.append(kind)
        rows = [r for r in self.db.execute(q, args).fetchall() if self.sees(agent, r)]
        out = [{**self.summary(r), "priority": self.priority(r)} for r in rows]
        out.sort(key=lambda x: (-x["pinned"], -x["priority"], x["id"]))
        return out[:limit]

    def summary(self, r):
        return {"id": r["id"], "kind": r["kind"], "key": r["key"], "title": r["title"], "state": r["state"], "version": r["version"],
                "owner": r["owner"], "label": r["label"], "pinned": r["pinned"], "created": r["created"], "updated": r["updated"]}

    def find(self, agent, text="", kind=None, state=None, key=None, limit=20):
        q, args = "select * from artifacts where 1=1", []
        for col, v in (("kind", kind), ("state", state), ("key", key)):
            if v:
                q += f" and {col}=?"
                args.append(v)
        rows = [r for r in self.db.execute(q, args).fetchall() if self.sees(agent, r)]
        if text:
            docs = {r["id"]: f"{r['title']} {r['body']}" for r in rows}
            docs[0] = text
            vec = tfidf(docs)
            rows = sorted((r for r in rows if cosine(vec[0], vec[r["id"]]) > 0), key=lambda r: -cosine(vec[0], vec[r["id"]]))
        return [self.summary(r) for r in rows[:limit]]

    def get(self, agent, aid):
        r = self._get_row(aid)
        if not self.sees(agent, r):
            raise Refused(f"artifact {aid} is private and your card holds a way out (SWM-67)")
        ev = [dict(e) for e in self.db.execute("select actor, run, text, ref, origin, label, alert, ts from evidence where artifact_id=? order by id", (aid,))]
        for e in ev:
            if str(e["origin"]).startswith("external"):
                inner = str(e["text"]).replace("</untrusted", "<\\/untrusted")   # the text cannot end its own label (review SEC-R9)
                e["text"] = f"<untrusted origin=\"{e['origin']}\">{inner}</untrusted>"
        since = self.db.execute("select max(ts) from events where artifact_id=? and kind='transition' and json_extract(payload, '$.to')=?",
                                (aid, r["state"])).fetchone()[0] or r["created"]
        return {**dict(r), "plan": json.loads(r["plan"]) if r["plan"] else None, "check": json.loads(r["check"]) if r["check"] else None,
                "evidence": ev, "priority": self.priority(r), "state_since": since,
                "links": [dict(x) for x in self.db.execute("select dst, rel, reason from links where src=? union all "
                                                           "select src, rel || ' (from)', reason from links where dst=?", (aid, aid))],
                "refs": [dict(x) for x in self.db.execute("select system, ref from refs where artifact_id=?", (aid,))],
                "watchers": [x[0] for x in self.db.execute("select agent from watchers where artifact_id=?", (aid,))],
                "history": [dict(x) for x in self.db.execute("select seq, actor, cls, kind, reason, ts from events where artifact_id=? "
                                                             "order by seq desc limit 30", (aid,))]}  # cap: list (an artifact's 30 newest events; the Ledger keeps every one)

    def context(self, agent, advance=True):
        """SWM-16, SWM-34, SWM-60, SWM-61: the start-of-run pack, in a fixed order, within PACK_CHARS."""
        last = (self.db.execute("select seq from cursors where agent=?", (agent,)).fetchone() or [0])[0]
        own = [x for x in self.ranked(states=("draft", "open", "ready", "active", "checking", "blocked"), agent=agent, limit=200)
               if x["owner"] == agent]
        watched = [{k: r[k] for k in ("seq", "artifact_id", "actor", "kind", "reason")} for r in self.db.execute(
            "select e.seq, e.artifact_id, e.actor, e.kind, e.reason, a.label from events e join watchers w on w.artifact_id=e.artifact_id "
            "join artifacts a on a.id=e.artifact_id where w.agent=? and e.seq>? and e.actor<>? order by e.seq", (agent, last, agent))
            if self.sees(agent, r)]                      # review SWM-R2: a private change's reason holds its text
        lessons = [dict(r) for r in self.db.execute(
            "select e.artifact_id, a.title, json_extract(e.payload, '$.to') as decision, e.reason, e.ts from events e "
            "join artifacts a on a.id=e.artifact_id where a.owner=? and e.cls='owner' and e.kind='transition' and e.ts>? "
            "order by e.seq desc", (agent, self.now() - LESSON_DAYS * 86400))]
        box = self.inbox(agent, mark=False)               # marked below, only what the pack keeps (review SWM-R14)
        judged = {r[0] for r in self.db.execute("select seq from help_verdicts where by=?", (agent,))}
        received = [{k: h[k] for k in ("seq", "artifact_id", "helper", "kind", "text", "unseen", "outcome")}
                    for h in self.helps(14, owner=agent) if h["seq"] not in judged and h["useful"] is None    # SWM-109: not judged, not settled
                    and self.sees(agent, h)]               # SWM-67: private help never reaches a card with a way out (REST2-R1)
        sections = [("owner_messages", [m for m in box["messages"] if m["sender_cls"] == O]),
                    ("open_requests", box["open_requests"] + [dict(m, expired=True) for m in box["expired"]]),
                    ("messages", [m for m in box["messages"] if m["sender_cls"] != O]),
                    ("own_artifacts", own), ("watched_changes", watched), ("help_received", received),
                    ("lessons", lessons)]
        pack, used, cut = {}, 0, []
        for name, items in sections:
            keep = []
            for it in items:
                n = len(json.dumps(it, ensure_ascii=False))
                # limit: drops, context pack items past the pack's size (SWM-60); the pack lists what it left out
                if used + n > PACK_CHARS:
                    cut.append(f"{name}:{it.get('id') or it.get('artifact_id') or it.get('seq')}")
                    continue
                keep.append(it)
                used += n
            pack[name] = keep
        pack["cut"] = cut
        pack["team"], pack["team_rule"] = self.roster(agent), TEAM_RULE   # SWM-108: small and fixed, outside the budget
        if (self.cards.get(agent) or {}).get("instructions"):          # SWM-18: the card's standing instructions come first
            pack = {"instructions": TC.first([str(x) for x in self.cards[agent]["instructions"]], 20, "standing instructions of a card"), **pack}  # cap: untrusted
        top = self.db.execute("select coalesce(max(seq), 0) from events").fetchone()[0]
        if advance:
            who = "owner" if agent is None else agent
            for m in pack.get("owner_messages", []) + pack.get("messages", []):    # read: what the pack holds; a cut one stays unread
                self.db.execute("insert or ignore into receipts values(?,?,?)", (m["mid"], who, self.now()))
            self.db.execute("insert or replace into cursors values(?, ?)", (agent, top))
            run = self.db.execute("select run, inputs from runs where agent=? and finished is null order by started desc limit 1", (agent,)).fetchone()
            if run:                                                     # SWM-82: the pack this run really read is its replay input
                inputs = json.loads(run["inputs"] or "{}")
                inputs["pack"] = pack
                self.db.execute("update runs set inputs=? where run=?", (bounded_json(inputs, 40000), run["run"]))  # cap: prompt
        return pack

    def rebuild(self):
        """Replay every event into fresh projection tables and return them (SWM-30: state = what the events say)."""
        mem = sqlite3.connect(":memory:")
        mem.row_factory = sqlite3.Row
        mem.executescript(SCHEMA[0].split("create table events")[0] + "create table evidence(id integer primary key, artifact_id integer, "
                          "seq integer, actor text, run text, text text, ref text, origin text, label text, alert integer default 0, ts real, help text);"
                          "create table help_verdicts(seq integer, artifact_id integer, by text, cls text, useful integer, reason text, ts real);"
                          "create table links(src integer, dst integer, rel text, reason text, actor text, ts real, primary key(src, dst, rel));"
                          "create table refs(artifact_id integer, system text, ref text, primary key(artifact_id, system, ref));"
                          "create table watchers(artifact_id integer, agent text, primary key(artifact_id, agent));")
        for e in self.db.execute("select * from events where artifact_id is not null order by seq"):
            if e["kind"] == "create":
                mem.execute("insert into artifacts(id, kind, key, state, version, label, created) values(?,?,?,?,?,?,?)",
                            (e["artifact_id"], *(lambda p: (p["kind"], p["key"]))(json.loads(e["payload"])), "draft", 0, "internal", e["ts"]))
            apply(mem, {**dict(e), "payload": json.loads(e["payload"])})
        return mem


class _Tx:
    """A transaction; inside another one a savepoint, so a whole finish rolls back when one of its operations is refused
    (review SWM-R6)."""
    _n = 0

    def __init__(self, db):
        self.db = db
        self.sp = None

    def __enter__(self):
        if self.db.in_transaction:
            _Tx._n += 1
            self.sp = f"sp{_Tx._n}"
            self.db.execute(f"savepoint {self.sp}")
        else:
            self.db.execute("begin immediate")

    def __exit__(self, et, ev, tb):
        if self.sp:
            if et:
                self.db.execute(f"rollback to {self.sp}")
            self.db.execute(f"release {self.sp}")
        else:
            self.db.execute("rollback" if et else "commit")


def apply(db, e):
    """One event onto the projection (artifacts, versions, evidence, links, refs, watchers). Shared by writes and rebuild()."""
    aid, p, k, ts = e["artifact_id"], e["payload"], e["kind"], e["ts"]
    if k in ("create", "update"):
        row = db.execute("select * from artifacts where id=?", (aid,)).fetchone()
        f = {"title": row["title"], "body": row["body"], "plan": row["plan"], "impact": row["impact"], "confidence": row["confidence"],
             "effort": row["effort"], "check": row["check"], "label": row["label"]}
        for key in ("title", "body", "impact", "confidence", "effort", "label"):
            if p.get(key) is not None:
                f[key] = p[key]
        for key in ("plan", "check"):
            if p.get(key) is not None:
                f[key] = json.dumps(p[key], sort_keys=True)
        v = row["version"] + 1
        sets = {**f, "version": v, "updated": ts}
        if k == "create":
            sets.update(owner=p.get("owner"), origin=p.get("origin"), state="draft", created=ts)
        db.execute("update artifacts set " + ", ".join(f'"{c}"=?' for c in sets) + " where id=?", (*sets.values(), aid))
        db.execute("insert into versions values(?,?,?,?,?,?,?)", (aid, v, f["title"], f["body"], f["plan"], e["actor"], ts))
    elif k == "evidence":
        db.execute("insert into evidence(artifact_id, seq, actor, run, text, ref, origin, label, alert, ts, help) values(?,?,?,?,?,?,?,?,?,?,?)",
                   (aid, e["seq"], e["actor"], e.get("run", ""), p["text"], p.get("ref", ""), p.get("origin"), p.get("label"),
                    1 if p.get("alert") else 0, ts, json.dumps(p["help"]) if p.get("help") else None))
        row = db.execute("select label from artifacts where id=?", (aid,)).fetchone()
        db.execute("update artifacts set label=?, updated=? where id=?", (max_label(row["label"], p.get("label")), ts, aid))
    elif k == "help_verdict":                                           # SWM-109
        db.execute("insert into help_verdicts(seq, artifact_id, by, cls, useful, reason, ts) values(?,?,?,?,?,?,?)",
                   (p["seq"], aid, e["actor"], e["cls"], 1 if p.get("useful") else 0, e.get("reason") or "", ts))
    elif k == "transition":
        db.execute("update artifacts set state=?, snooze_until=?, updated=?, recurrence=recurrence+? where id=?",
                   (p["to"], p.get("snooze_until"), ts, 1 if p.get("reopen") else 0, aid))
    elif k == "link":
        db.execute("insert or replace into links values(?,?,?,?,?,?)", (aid, p["dst"], p["rel"], p.get("reason", ""), e["actor"], ts))
    elif k == "ref":
        db.execute("insert or ignore into refs values(?,?,?)", (aid, p["system"], p["ref"]))
    elif k == "watch":
        if p.get("on"):
            db.execute("insert or ignore into watchers values(?,?)", (aid, p["agent"]))
        else:
            db.execute("delete from watchers where artifact_id=? and agent=?", (aid, p["agent"]))
    elif k == "pin":
        db.execute("update artifacts set pinned=? where id=?", (1 if p.get("on") else 0, aid))
    elif k == "handoff":
        db.execute("update artifacts set owner=? where id=?", (p["to"], aid))
