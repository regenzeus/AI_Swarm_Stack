"""The decision queue and its shadow (AUT-05, AUT-07, docs/NEXT-PHASE.md Part 1).

Since 11 Nov 2026 every item of every source is an Ask (ops/asks.py, ASK-12, docs/ASKS.md): asks_sync() opens one Ask
per item (by its id), with its answers as chips (a tap runs the item's own request; a link stays a link), registers each
class as a kind of Ask once (a floor class is a gate: only the owner's tap), and settles the Ask of an item its source no
longer lists. What waits is then the Asks that are open: a dismissed, put-off or answered item leaves the list. This
module stays the sources' adapter; the list below is drawn from the Asks.

Everything that waits for the owner is one ranked list, `decisions` in state.json. #/decide and Home's "Needs you" both
draw that list and build none of their own, so they cannot disagree (GEN-02). Each item has what, why, the stack's
recommendation, what happens without an answer and when, and its answers: a tap, or a link to where the owner acts. The
runner's sources are gathered here; the Mission Control server adds the three only it sees (the AI phone's approval
requests, Gmail's Trash batch and a mission that needs access) with the same shape.

What is not here is what the owner cannot answer: the AI phone being down and health alerts are states, on the health
board and under Home's Stack upkeep.

The test item (GEN-03): the nightly journey (ops/journeys.py decide) makes one through the inbox, sees it in the queue,
answers it with the owner's tap and removes it. It is marked as a test, the shadow never records it, and answering it
changes only its own file: it touches no build, purchase, phone or mail.

The shadow: for each decision of a class that takes a yes or no, the stack records once what it *would* decide and
why (/srv/ai/state/autonomy.jsonl, "seen"). When the decision leaves the queue its outcome is looked up where the
source keeps it (a build deployed or rejected, a task started or cancelled, a purchase approved or declined, a phone
step done or dismissed, an idea taken or dismissed) and recorded ("answered"). Agreement per class over the owner's
last AGREE answers is the evidence a licence needs; nothing here acts or promotes: every class still asks.

  python3 ops/decisions.py list | stats
"""
import datetime as dt
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from urllib.parse import quote

import yaml

import textcap as TC                              # visible caps (AGENTS.md, truncation)
import asks as AK                                 # ASK-12: every item is an Ask

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/autonomy.yaml"
LOG = Path(os.environ.get("AUTONOMY_LOG", "/srv/ai/state/autonomy.jsonl"))
MOVE_LIST = Path(os.environ.get("MEMORY_MOVE", "/srv/ai/state/memory-move.json"))      # ops/missions.py memory_browse
TEST_ITEM = Path(os.environ.get("DECISION_TEST", "/srv/ai/missions/decision-test.json"))   # the journey's test item, one at a time
ACTIONS = {"decision_test_make", "decision_test_answer", "decision_test_remove"}           # only _answer is the app's (server.py ACTIONS)
NOT_THE_OWNERS = ("trial", "probe", "crew", "gate")   # a task the stack gave itself (= app.js NOT_YOURS): its stop waits for nobody
AGREE = 20                                     # the owner's last answers a class's agreement is measured on  # cap: list
DAYS = 14                                      # the queue's numbers look this far back
TARGET = {"per_day": 5, "answer_h": 12}        # AUT-07's target
_seen = {}                                     # decision id -> what the shadow recorded when it first saw it
_loaded = {"t": 0}


def classes():
    return (yaml.safe_load(CONFIG.read_text()) or {}).get("classes") or {}


def level(cls, cs=None):
    """A class's licence level now; a floor class is 0 by construction (AUT-04: the floor is never licensed)."""
    c = (cs or classes()).get(cls) or {}
    return 0 if c.get("floor") else min(int(c.get("level") or 0), int(c.get("highest") or 0))


def _ts(x):
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return dt.datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso(t):
    return dt.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds") if t else None


def _d(id, cls, what, why, href, *, would=None, because="", unanswered="", expires=None, answers=(), created=None,
       weight=1, routine=False):
    rec = {"answer": would, "why": because} if would in ("yes", "no") else None
    return {"id": id, "cls": cls, "what": what, "why": why, "href": href, "recommend": rec, "unanswered": unanswered,
            "expires": _iso(expires) if isinstance(expires, (int, float)) else expires, "answers": list(answers),
            "created": _iso(_ts(created)) if created is not None else None, "weight": weight, "routine": routine}


# ---------- the sources ----------
def _builds(st):
    for b in st.get("builds") or []:
        if b.get("status") != "review":
            continue
        rv, missing = (b.get("ai_review") or {}).get("verdict"), (b.get("ai_review") or {}).get("missing") or []
        ok = b.get("checks_ok") and rv == "approve" and not missing and str(b.get("ci") or "").lower() in ("passed", "success", "green")   # QA-26
        cls = "coding" if b.get("sensitive") else "coding-low-risk"
        summary = str((b.get("ai_review") or {}).get("summary") or "").strip()
        # APP-74: answered on its card (Deploy or Reject), the review's summary behind the card's (i); the build's page
        # stays one quiet link away, never the only way to answer
        yield _d(f"build:{b['id']}", cls, f"Deploy build #{b['id']}: {b.get('title') or ''}",
                 f"checks {'passed' if b.get('checks_ok') else 'failed' if b.get('checks') else 'not run'}, CI {b.get('ci') or 'not pushed'}, "
                 f"AI review {rv or 'not done'}" + (f", not done: {', '.join(missing)}" if missing else "") + (f". The review: {summary}" if summary else ""),
                 f"#/build/{b['id']}", would="yes" if ok else "no",
                 because="its checks, CI and AI review all passed" if ok else "not every check passed",
                 unanswered="it waits; nothing deploys without you", created=b.get("updated") or b.get("created"),
                 answers=[{"label": "Deploy", "act": {"action": "build_approve", "id": b["id"]}},
                          {"label": "Reject", "act": {"action": "build_reject", "id": b["id"]}}], weight=2)


def _purchases(st):
    for p in (st.get("shopping") or {}).get("proposals") or []:
        if p.get("status") not in ("proposed", "needs_owner"):
            continue
        over = p.get("over")
        yield _d(f"shop:{p['id']}", "shopping-buy", f"Buy {p.get('item')} for EUR {p.get('total_eur')} at {p.get('shop')}?",
                 p.get("why") or p.get("why_now") or p.get("stopped_reason") or "the shopping agent found it", f"#/mission/{p.get('slug')}?shop={p['id']}",
                 would="no" if over else "yes", because="over its budget" if over else "within its budget and the agent's pick",
                 unanswered="the offer may change or end", expires=p.get("deadline"), created=p.get("created"),
                 answers=[{"label": "Decide where the amount is shown", "href": f"#/mission/{p.get('slug')}?shop={p['id']}"}], weight=3)


def _phone_steps(st):
    if _off("phone"):                                # PHN-28: switched off, its steps ask nothing (their Asks are closed)
        return
    steps = [a for a in next((x.get("actions") or [] for x in st.get("crew") or [] if x.get("id") == "phone-cleanup"), []) if a.get("status") == "open"]
    for a in steps:
        app = a.get("kind") == "uninstall"            # removing an app is the owner's choice; caches and old files are the routine
        yield _d(f"phone-step:{a.get('id')}", "phone-routine", f"AI phone cleanup: {a.get('title') or a.get('what') or a.get('id')}",
                 f"frees {round((a.get('size') or 0) / 1e9, 2)} GB" if a.get("size") else "a cleanup step the scan found", "#/crew/phone-cleanup",
                 would="no" if app else "yes", because="removing an app is yours to choose" if app else "a listed routine: storage cleanup",
                 unanswered="the space stays used", created=a.get("created"),
                 answers=[{"label": "Approve", "act": {"action": "phone_cleanup_do_all", "ids": [a.get("id")]}},
                          {"label": "Keep it", "act": {"action": "phone_cleanup_dismiss", "id": a.get("id")}}], routine=not app)   # an app is decided on its own


def _memory(st):
    for m in (st.get("system") or {}).get("pending_memory") or []:
        yield _d(f"memory:{m['id']}", "memory", "Remember this?", m.get("text") or "", "#/decide", would="yes",
                 because="Hermes asked to remember it", unanswered="Hermes does not remember it",
                 answers=[{"label": "Remember", "act": {"action": "memory", "id": m["id"], "decision": "approve"}},
                          {"label": "Discard", "act": {"action": "memory", "id": m["id"], "decision": "reject"}}], routine=True)


def _tasks(st):
    for t in st.get("tasks") or []:
        if t.get("status") == "waiting_approval":
            cls = "research" if t.get("kind") == "research" else "task-start"
            yield _d(f"task:{t['id']}", cls, f"Start task #{t['id']}: {t.get('title')}", (t.get("plan") or {}).get("why") if isinstance(t.get("plan"), dict) else
                     f"planned as {t.get('kind') or 'a task'}", f"#/task/{t['id']}", would="yes" if cls == "research" else None,
                     because="research it can do within its budget" if cls == "research" else "", unanswered="it does not start",
                     expires=t.get("deadline"), created=t.get("updated") or t.get("created"),
                     answers=[{"label": "Start", "act": {"action": "task_approve", "id": t["id"]}}, {"label": "Look first", "href": f"#/task/{t['id']}"}])
        elif t.get("status") == "needs_answer":
            qs = t.get("questions") or []
            yield _d(f"task-q:{t['id']}", "task-questions", f"Task #{t['id']} asks you", "; ".join(str(q) for q in qs) or t.get("title") or "",
                     f"#/task/{t['id']}", unanswered="it waits for your answer", expires=t.get("deadline"), created=t.get("updated"),
                     answers=[{"label": "Answer", "href": f"#/task/{t['id']}"}])
        elif t.get("status") == "failed" and t.get("kind") == "change" and t.get("door") == "plan" and not str(t.get("source") or "").startswith(NOT_THE_OWNERS):
            yield _d(f"stopped:{t['id']}", "task-start", f"Change #{t['id']} stopped: go on? {t.get('title') or ''}", t.get("error") or "it stopped at its budget or a failed step",
                     f"#/task/{t['id']}", unanswered="it stays stopped", created=t.get("updated"),
                     answers=[{"label": "Go on, with its budget doubled", "act": {"action": "change_resume", "id": t["id"]}},
                              {"label": "Leave it stopped", "act": {"action": "change_leave", "id": t["id"]}},
                              {"label": "Look first", "href": f"#/task/{t['id']}"}])


def _swarm(st):
    sw = st.get("swarm") or {}
    for m in sw.get("owner_requests") or []:
        room = f"#/home?tab=activity&ctx={quote(str(m.get('context') or ''), safe='')}"     # a context holds ":" and "+": a link must keep them
        yield _d(f"ask:{m.get('id') or m.get('context')}", "agent-request", f"{m.get('sender')} asks you", m.get("text") or "",
                 room, unanswered="the agent waits", created=m.get("ts"), answers=[{"label": "Answer", "href": room}])
    for i in (sw.get("board") or {}).get("open") or []:
        dispute = i.get("kind") == "dispute"
        good = (i.get("priority") or 0) >= 4 and i.get("effort") in ("small", None)
        yield _d(f"idea:{i['id']}", "memory" if dispute else "ideas", ("Which is true? " if dispute else "Take this idea? ") + (i.get("title") or ""),
                 (i.get("signal") or i.get("owner") or ""), "#/ideas", would=None if dispute else "yes" if good else "no",
                 because="" if dispute else "high priority and small" if good else "low priority or not small",
                 unanswered="it stays on the board", created=i.get("created"), answers=[{"label": "Decide", "href": "#/ideas"}], weight=0)
    for a in sw.get("changes") or []:
        if a.get("state") == "ready" and (a.get("experiment") or {}).get("passed") and a["experiment"].get("version") == a.get("version"):
            yield _d(f"change:{a.get('id')}:{a.get('version')}", "agent-change", f"Take the change to {a.get('agent') or a.get('id')}?",
                     a.get("summary") or a.get("why") or "its experiment passed", "#/ideas", would="yes", because="its experiment passed",
                     unanswered="the agent stays as it is", created=a.get("updated"), answers=[{"label": "Decide", "href": "#/ideas"}], weight=0)
    for a in sw.get("to_confirm") or []:
        yield _d(f"confirm:{a['id']}", "owner-confirm", f"Does it work? {a.get('title') or ''}", (sw.get("checks") or {}).get(str(a["id"])) or "it shipped, and its check is your word",
                 f"#/swarm/artifact/{a['id']}", unanswered="it stays unproved: the Checker waits for your word", created=a.get("state_since"),
                 answers=[{"label": "It works", "act": {"action": "swarm_confirm", "id": a["id"]}},
                          {"label": "Still broken", "act": {"action": "swarm_reopen", "id": a["id"]}, "ask": "What is still broken?", "into": "reason"}])


def _memory_move(st):
    """APP-50: what long-term memory holds that does not concern the owner, for his eyes before anything moves."""
    try:
        n = len([m for m in json.loads(MOVE_LIST.read_text()) if not m.get("kept")])
    except (OSError, ValueError):
        return
    if n:
        yield _d("memory-move", "memory", f"{n} long-term facts are not about you: move them?", "Company news and what agents did. They go to the wikis or are retired, and each can be undone.",
                 "#/longterm?move=1", unanswered="they stay in long-term memory", answers=[{"label": "See them", "href": "#/longterm?move=1"}], routine=True)


def _keeper(st):
    """The Memory Keeper's suggestions: facts it would retire and leaves to the owner (MEM-21)."""
    for s in next((x.get("suggestions") or [] for x in st.get("crew") or [] if x.get("id") == "memory"), []):
        yield _d(f"keeper:{s['id']}", "memory", f"Forget this? {s.get('text') or ''}", s.get("why") or "", "#/crew/memory", would="yes", because="the Memory Keeper suggests it",
                 unanswered="Hermes keeps recalling it", answers=[{"label": "Forget", "act": {"action": "crew_memory_forget", "ids": [s["id"]]}},
                                                                  {"label": "Look first", "href": "#/crew/memory"}], routine=True)


def _house(st):
    """The next House setup step only the owner can do (the required steps of app.js houseSteps); a NAS that is off is no step."""
    h = st.get("house") or {}
    if not h.get("reachable"):
        return
    has = {x.get("domain") for x in h.get("integrations") or []}
    step = ("Create your Home Assistant account" if not h.get("onboarded") else "Connect it to the AI stack" if not h.get("connected")
            else "Sign in to Amazon (Alexa)" if "alexa_devices" not in has else None)
    if step:
        yield _d("house:setup", "setup", "Finish setting up the House", f"next: {step.lower()}", "#/house", unanswered="the House cannot be used from the stack yet",
                 answers=[{"label": "Open the House", "href": "#/house"}])


def _test_item(st):
    t = st.get("decision_test") or {}
    if t.get("state") == "open":
        yield {**_d(f"test:{t['token']}", "journey-test", "Test item: the nightly journey checks this list", "it removes itself; an answer changes nothing else", "#/decide",
                    unanswered="the journey removes it", created=t.get("created"), weight=0,
                    answers=[{"label": "Answer the test", "act": {"action": "decision_test_answer", "token": t["token"], "answer": "yes"}}]), "test": True}


def _packs(st):
    """A pack commit waiting for the owner (GEN-21): it always asks, and the old commit runs meanwhile."""
    from domain import packs as PK
    yield from PK.decisions(_d, st.get("packs"))          # the runner's state already holds them (ops/missions.py domain_state)


def _trackers(st):
    """A tracker write in shadow, to be judged, and a kind of write whose measure is met (GEN-25)."""
    from domain import trackers as TR
    yield from TR.decisions(_d)


def _commands(st):
    """A pack's command waiting for its approval at a place (GEN-22): by the hash of its file, always the owner's."""
    from domain import places as PL
    yield from PL.decisions(_d)


def _mail_sort(st):
    """CNX-11: senders whose mail could be deleted, new since the owner last chose, wait for a look on Your mail; nothing
    moves before the owner's tap there."""
    import mailsort as MSORT
    new = MSORT.pending()
    if new:
        n, mails, inbox = len(new), sum(s.get("movable") or 0 for s in new), sum(s.get("inbox") or 0 for s in new)
        yield _d("mail-sort", "mail-sort", f"{n} sender{'s' if n != 1 else ''} send mail you could delete: sort it out?",
                 f"{mails:,} mails, {inbox:,} of them in the inbox, from the headers alone. You choose per sender; nothing moves before your tap, and nothing is deleted.",
                 "#/mail", unanswered="the mail stays where it is", answers=[{"label": "Look and choose", "href": "#/mail"}])


def _tax(st):
    """The tax desk's open questions (TAX-07): what only the owner knows for a year's draft, a paper it could not sort, an
    expected paper that never came. Buttons, or a typed number; the text names no amount and no paper's content."""
    import tax as TX
    yield from TX.decisions(_d)


def _off(feature):
    try:
        import deployment as DEPLOY
        return not DEPLOY.has(feature)
    except (ImportError, SystemExit, OSError):       # no deployment (a bare test): every source as before
        return False


# GEN-13, PHN-28: the Asks of a source whose feature is off are closed with these words (dismissed, history kept)
OFF_ASKS = {"phone": ("dq:phone-step:", "the AI phone is switched off")}


SOURCES = (_builds, _purchases, _phone_steps, _memory, _tasks, _swarm, _keeper, _memory_move, _house, _test_item, _packs, _trackers, _commands,
           _mail_sort, _tax)   # a workflow's question is an Ask of its own (ops/flows.py ask, ASK-19)


def rank(items, now=None):
    """What expires first, then what costs most to delay (money, a build, then the rest; ideas last), then the oldest."""
    now = now or time.time()

    def key(d):
        e = _ts(d.get("expires")) if d.get("expires") else None
        return (0 if e is not None and e - now < 2 * 3600 else 1, e or 9e12, -d.get("weight", 1), _ts(d.get("created")) or now)
    return sorted(items, key=key)


def gather(st, now=None):
    out = []
    for f in SOURCES:
        try:
            out += list(f(st))
        except Exception as e:                       # one broken source does not hide the others
            out.append(_d(f"error:{f.__name__}", "agent-request", "A source of decisions could not be read", f"{f.__name__}: {type(e).__name__}: {e}", "#/missions?f=problems",
                          answers=[{"label": "Look at the health board", "href": "#/missions?f=problems"}]))
    return rank(out, now)


# ---------- the shadow ----------
def _log(rec):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _records():
    try:
        return [json.loads(x) for x in LOG.read_text().splitlines() if x.strip()]
    except (FileNotFoundError, ValueError):
        return []


def outcome(id, st):
    """Where the source keeps the owner's answer to a decision that left the queue: yes, no, expired or None (unknown)."""
    kind, _, ref = id.partition(":")
    if kind == "build":
        b = next((x for x in st.get("builds") or [] if str(x.get("id")) == ref), None)
        s = (b or {}).get("status")
        return "yes" if s in ("approved", "merging", "deploying", "deployed", "done", "merged") else "no" if s in ("rejected", "reverted", "cancelled") else None
    if kind == "shop":
        p = next((x for x in (st.get("shopping") or {}).get("proposals") or [] if str(x.get("id")) == ref), None)
        s = (p or {}).get("status")
        return "yes" if s in ("approved", "buying", "bought", "shipped", "delivered") else "no" if s in ("rejected", "declined", "dismissed") else "expired" if s == "expired" else None
    if kind in ("task", "task-q"):
        t = next((x for x in st.get("tasks") or [] if str(x.get("id")) == ref), None)
        s = (t or {}).get("status")
        return "no" if s == "cancelled" else "yes" if s in ("running", "planning", "done", "scheduled", "failed", "intake") else None
    if kind == "phone-step":
        a = next((x for c in st.get("crew") or [] if c.get("id") == "phone-cleanup" for x in c.get("actions") or [] if str(x.get("id")) == ref), None)
        s = (a or {}).get("status")
        return "yes" if s in ("done", "running", "approved") else "no" if s == "dismissed" else None
    if kind == "idea":
        i = next((x for x in ((st.get("swarm") or {}).get("board") or {}).get("recent") or [] if str(x.get("id")) == ref), None)
        s = (i or {}).get("state")
        return "no" if s in ("dismissed", "rejected", "gone") else "yes" if s in ("accepted", "planned", "building", "done") else None
    if kind == "stopped":
        s = next((x.get("status") for x in st.get("tasks") or [] if str(x.get("id")) == ref), None)
        return "no" if s == "cancelled" else "yes" if s in ("running", "done") else None
    return None


def shadow(items, st, now=None):
    """Record each new decision once with what the stack would decide, and each that left the queue with its outcome."""
    now = now or time.time()
    first = not _loaded["t"] and not _records()      # the very first pass: what waits already is a backlog, not today's
    if not _loaded["t"]:                             # after a restart: what is still open was seen before
        for r in _records():
            if r.get("event") == "seen":
                _seen[r["id"]] = r
            elif r.get("event") == "answered":
                _seen.pop(r["id"], None)
        _loaded["t"] = now
    ids = {d["id"] for d in items}
    for d in items:
        if d["id"] not in _seen and not d["id"].startswith(("error:", "test:")):   # a test is no decision: it never reaches the numbers
            r = {"t": round(now), "event": "seen", "id": d["id"], "cls": d["cls"], "what": TC.cut(d["what"], 200),  # cap: preview (the source keeps it whole)
                 "would": (d.get("recommend") or {}).get("answer"), "why": (d.get("recommend") or {}).get("why", ""), **({"backlog": True} if first else {})}
            _seen[d["id"]] = r
            _log(r)
    for id in [i for i in _seen if i not in ids]:
        s = _seen.pop(id)
        _log({"t": round(now), "event": "answered", "id": id, "cls": s.get("cls"), "would": s.get("would"),
              "owner": outcome(id, st), "secs": round(now - s.get("t", now))})


def stats(now=None, recs=None):
    """AUT-07: decisions a day, the median time to answer, how many expired, against the target; and per class the
    shadow's agreement over the owner's last AGREE yes-or-no answers, with any unsafe call (yes where the owner said no)."""
    now = now or time.time()
    recs = _records() if recs is None else recs
    since = now - DAYS * 86400
    seen = [r for r in recs if r.get("event") == "seen" and r.get("t", 0) >= since and not r.get("backlog")]
    ans = [r for r in recs if r.get("event") == "answered" and r.get("t", 0) >= since]
    days = max(1, min(DAYS, (now - min((r["t"] for r in seen), default=now)) / 86400))
    backlog = {r["id"] for r in recs if r.get("backlog")}
    secs = [r["secs"] for r in ans if r.get("owner") in ("yes", "no") and r["id"] not in backlog]   # a backlog's wait began before the record
    per = {}
    for r in [r for r in recs if r.get("event") == "answered" and r.get("would") in ("yes", "no") and r.get("owner") in ("yes", "no")]:
        per.setdefault(r["cls"], []).append(r)
    agree = {}
    for cls, rs in per.items():
        last = rs[-AGREE:]                           # cap: list (AUT-02 measures the last 20)
        agree[cls] = {"n": len(last), "agreed": sum(r["would"] == r["owner"] for r in last),
                      "unsafe": sum(r["would"] == "yes" and r["owner"] == "no" for r in last)}
    return {"per_day": round(len(seen) / days, 1), "answered": len(secs), "median_h": round(statistics.median(secs) / 3600, 1) if secs else None,
            "expired": sum(r.get("owner") == "expired" for r in ans), "target": TARGET, "agreement": agree, "days": round(days, 1)}


# ---------- every item an Ask (ASK-12) ----------
ACTION = {"coding": "deploy", "coding-low-risk": "deploy", "shopping-buy": "buy", "shopping-pick": "buy", "phone-routine": "phone-cleanup",
          "phone": "phone", "memory": "memory-forget", "wiki": "memory-forget", "research": "task-start", "task-start": "task-start",
          "task-questions": "answer", "briefing": "task-start", "agent-request": "answer", "ideas": "idea", "agent-change": "agent-change",
          "owner-confirm": "confirm", "mail-sort": "mail-sort", "delete": "delete", "access": "access", "tax": "answer", "setup": "setup",
          "command": "command", "pack-commit": "pack", "journey-test": "test", "coding-review": "deploy"}
KIND_OF = {"memory": "memory-remember", "keeper": "memory-forget", "memory-move": "memory-move", "stopped": "task-resume",
           "flow": "workflow", "error": "source-error", "build": None}   # an item's kind by its id's prefix, where its class is too wide
EXTRA_KINDS = {"memory-remember": ("Remember this", "memory-keep"), "memory-forget": ("Forget a fact", "memory-forget"),
               "memory-move": ("Move facts out of memory", "memory-move"), "task-resume": ("A change that stopped", "task-resume"),
               "workflow": ("A workflow asks", "workflow"), "source-error": ("A source of questions", "answer")}
PRIVATE = {"tax"}                                    # their figures stay in the app (TAX-11): a ticket gets a link only
VALUES = {"tax": {"answer": "number"}}               # what a typed answer to a kind may carry


def register_kinds(cs=None):
    """Each class of config/autonomy.yaml as a kind of Ask, once: a floor class is a gate (only the owner's tap; AUT-04:
    the floor is never licensed), the others take words, Dismiss, Later and standing rules."""
    cs = cs or classes()
    for k, v in cs.items():
        if k not in AK.TYPES:
            AK.register(k, v.get("title") or k, action=ACTION.get(k) or ("tracker-write" if k.startswith("tracker-") else "answer"),
                        outcomes=(), gate=bool(v.get("floor")), own_choices=True, values=VALUES.get(k))
    for k, (title, action) in EXTRA_KINDS.items():
        if k not in AK.TYPES:
            AK.register(k, title, action=action, outcomes=(), own_choices=True)


def kind_of(d):
    k = KIND_OF.get(d["id"].split(":")[0])
    return k if k and k in AK.TYPES else d["cls"] if d["cls"] in AK.TYPES else "source-error"


def _slug(label, taken):
    s = re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")[:40] or "answer"     # cap: id
    while s in taken:
        s += "-2"
    taken.add(s)
    return s


def ask_spec(d, rank):
    """One item as an Ask: its answers as chips (an act runs the item's own request when the chip is tapped; a link stays
    a link to its page), its why, what happens without an answer, its rank, the stack's recommendation."""
    chips, acts, taken = [], {}, set()
    for x in d.get("answers") or []:
        cid = _slug(x.get("label"), taken)
        if x.get("act"):
            acts[cid] = {**x["act"], **({"_into": x["into"]} if x.get("into") else {})}
            chips.append({"id": cid, "label": x["label"], **({"words": x["ask"]} if x.get("ask") else {})})
        elif x.get("href"):
            chips.append({"id": cid, "label": x["label"], "href": x["href"]})
    k = kind_of(d)
    return {"kind": k, "source": f"dq:{d['id']}", "question": d["what"], "why": d.get("why") or "", "choices": chips, "acts": acts,
            "href": d.get("href") or "", "unanswered": d.get("unanswered") or "", "weight": d.get("weight", 1), "rank": rank,
            "recommend": d.get("recommend"), "routine": bool(d.get("routine")), "expires": d.get("expires"), "cls": d["cls"],
            "since": d.get("created"), "test": bool(d.get("test")), "sensitivity": "private" if k in PRIVATE else "normal"}


def asks_sync(items, now=None, log=print):
    """ASK-12: each item opens (or refreshes) its Ask; an Ask whose item is gone is settled where it lives. -> the items
    still waiting, each with its Ask's id. An item the store cannot take stays in the list as it is (nothing is lost) and
    the log says why."""
    register_kinds()
    c = AK.connect()
    out, present = [], set()
    for i, d in enumerate(items):
        spec = ask_spec(d, i)
        present.add(spec["source"])
        try:
            a = AK.open_ask(spec, now=now, c=c)
        except Exception as e:                       # the item stays as it is, with no Ask
            log(f"decisions: {d['id']} is no Ask: {type(e).__name__}: {e}")
            out.append(d)
            continue
        if a["status"] in AK.SHOWN and not (a.get("pending") or {}).get("state") == "held":
            out.append({**d, "ask": a["id"]})
    for f, (prefix, words) in OFF_ASKS.items():
        if _off(f):
            AK.close_off(prefix, words, now=now, c=c)
    AK.sync_gone("dq:", present, now=now, c=c)
    return out


def state(st, now=None):
    """For state.json: the queue, its numbers, and each class's level (AUT-05, AUT-07). The queue is what waits as an Ask
    (ASK-12)."""
    test = test_record()
    items = gather({**st, "decision_test": test}, now)
    try:
        shadow(items, st, now)
    except Exception as e:
        print(f"decisions: shadow not recorded: {type(e).__name__}: {e}", file=sys.stderr)
    cs = classes()
    try:
        items = asks_sync(items, now)
    except Exception as e:                           # the store away: the list as the sources give it, nothing lost
        print(f"decisions: the Asks could not be synced: {type(e).__name__}: {e}", file=sys.stderr)
    return {"decisions": items, "decision_test": test, "decide": {**stats(now), "classes": {k: {"title": v.get("title"), "level": level(k, cs), "floor": v.get("floor"),
                                                                      "exam": v.get("exam"), "what": v.get("what")} for k, v in cs.items()}}}


# ---------- the journey's test item (GEN-03) ----------
def test_record():
    try:
        return json.loads(TEST_ITEM.read_text())
    except (FileNotFoundError, ValueError):
        return None


def _write_test(rec):
    TEST_ITEM.parent.mkdir(parents=True, exist_ok=True)
    tmp = TEST_ITEM.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec))
    tmp.replace(TEST_ITEM)


def make_test(req):
    token = str(req.get("token") or "")
    if not re.fullmatch(r"[a-f0-9]{8,32}", token):
        raise ValueError("a test item needs a token")
    _write_test({"token": token, "state": "open", "answer": None, "created": time.time()})   # one at a time: a leftover is replaced
    return {"token": token}


def answer_test(req):
    """What the owner's tap on the test item does: the same way in as any answer (app, server, inbox, runner), and only this file changes."""
    rec = test_record()
    if not rec or rec.get("token") != req.get("token") or rec.get("state") != "open":
        raise ValueError("this test item does not wait for an answer")
    if req.get("answer") not in ("yes", "no"):
        raise ValueError("a test item is answered yes or no")
    _write_test({**rec, "state": "answered", "answer": req["answer"], "answered": time.time()})
    return {"token": rec["token"], "answer": req["answer"]}


def remove_test(req):
    rec = test_record()
    if rec and rec.get("token") == req.get("token"):
        TEST_ITEM.unlink(missing_ok=True)
    return {"removed": True}


def handle(req):
    return {"decision_test_make": make_test, "decision_test_answer": answer_test, "decision_test_remove": remove_test}[req["action"]](req)


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["list"])[0]
    st = json.loads(Path("/srv/ai/missions/public/state.json").read_text())
    if cmd == "stats":
        print(json.dumps(stats(), indent=1))
    else:
        for d in gather(st):
            r = d.get("recommend") or {}
            print(f"{d['cls']:16} {TC.cut(d['what'], 90)}  -> would {r.get('answer') or '-'}")  # cap: preview (a terminal line)
