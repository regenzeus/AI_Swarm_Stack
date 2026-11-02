"""The decision queue and its shadow (AUT-05, AUT-07, docs/NEXT-PHASE.md Part 1).

Everything that waits for the owner is one ranked list, `decisions` in state.json (#/decide, Home's "Needs you"),
each with what, why, the stack's recommendation, what happens without an answer and when, and its answers. The
runner's sources are gathered here; the Mission Control server adds the two only it sees (the AI phone's approval
requests and Gmail's Trash batch) with the same shape.

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
import statistics
import sys
import time
from pathlib import Path

import yaml

import textcap as TC                              # visible caps (AGENTS.md, truncation)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/autonomy.yaml"
LOG = Path(os.environ.get("AUTONOMY_LOG", "/srv/ai/state/autonomy.jsonl"))
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
        rv = (b.get("ai_review") or {}).get("verdict")
        ok = b.get("checks_ok") and rv == "approve" and str(b.get("ci") or "").lower() in ("passed", "success", "green")
        cls = "coding" if b.get("sensitive") else "coding-low-risk"
        yield _d(f"build:{b['id']}", cls, f"Deploy build #{b['id']}: {b.get('title') or ''}",
                 f"checks {'passed' if b.get('checks_ok') else 'failed' if b.get('checks') else 'not run'}, CI {b.get('ci') or 'not pushed'}, "
                 f"AI review {rv or 'not done'}", f"#/build/{b['id']}", would="yes" if ok else "no",
                 because="its checks, CI and AI review all passed" if ok else "not every check passed",
                 unanswered="it waits; nothing deploys without you", created=b.get("updated") or b.get("created"),
                 answers=[{"label": "Review", "href": f"#/build/{b['id']}"}], weight=2)


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
        yield _d(f"memory:{m['id']}", "memory", "Remember this?", m.get("text") or "", "#/system", would="yes",
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


def _swarm(st):
    sw = st.get("swarm") or {}
    for m in sw.get("owner_requests") or []:
        yield _d(f"ask:{m.get('id') or m.get('context')}", "agent-request", f"{m.get('sender')} asks you", m.get("text") or "",
                 f"#/swarm?tab=chat&ctx={m.get('context') or ''}", unanswered="the agent waits", created=m.get("ts"),
                 answers=[{"label": "Answer", "href": f"#/swarm?tab=chat&ctx={m.get('context') or ''}"}])
    for i in (sw.get("board") or {}).get("open") or []:
        dispute = i.get("kind") == "dispute"
        good = (i.get("priority") or 0) >= 4 and i.get("effort") in ("small", None)
        yield _d(f"idea:{i['id']}", "memory" if dispute else "ideas", ("Which is true? " if dispute else "Take this idea? ") + (i.get("title") or ""),
                 (i.get("signal") or i.get("owner") or ""), "#/swarm?tab=improve", would=None if dispute else "yes" if good else "no",
                 because="" if dispute else "high priority and small" if good else "low priority or not small",
                 unanswered="it stays on the board", created=i.get("created"), answers=[{"label": "Decide", "href": "#/swarm?tab=improve"}], weight=0)
    for a in sw.get("changes") or []:
        if a.get("state") == "ready" and (a.get("experiment") or {}).get("passed") and a["experiment"].get("version") == a.get("version"):
            yield _d(f"change:{a.get('id')}:{a.get('version')}", "agent-change", f"Take the change to {a.get('agent') or a.get('id')}?",
                     a.get("summary") or a.get("why") or "its experiment passed", "#/swarm?tab=improve", would="yes", because="its experiment passed",
                     unanswered="the agent stays as it is", created=a.get("updated"), answers=[{"label": "Decide", "href": "#/swarm?tab=improve"}], weight=0)


SOURCES = (_builds, _purchases, _phone_steps, _memory, _tasks, _swarm)


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
            out.append(_d(f"error:{f.__name__}", "agent-request", "A source of decisions could not be read", f"{f.__name__}: {type(e).__name__}: {e}", "#/decide"))
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
        if d["id"] not in _seen and not d["id"].startswith("error:"):
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


def state(st, now=None):
    """For state.json: the queue, its numbers, and each class's level (AUT-05, AUT-07)."""
    items = gather(st, now)
    try:
        shadow(items, st, now)
    except Exception as e:
        print(f"decisions: shadow not recorded: {type(e).__name__}: {e}", file=sys.stderr)
    cs = classes()
    return {"decisions": items, "decide": {**stats(now), "classes": {k: {"title": v.get("title"), "level": level(k, cs), "floor": v.get("floor"),
                                                                      "exam": v.get("exam"), "what": v.get("what")} for k, v in cs.items()}}}


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["list"])[0]
    st = json.loads(Path("/srv/ai/missions/public/state.json").read_text())
    if cmd == "stats":
        print(json.dumps(stats(), indent=1))
    else:
        for d in gather(st):
            r = d.get("recommend") or {}
            print(f"{d['cls']:16} {TC.cut(d['what'], 90)}  -> would {r.get('answer') or '-'}")  # cap: preview (a terminal line)
