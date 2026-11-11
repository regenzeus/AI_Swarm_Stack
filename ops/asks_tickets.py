"""ASK-17, ASK-18: the ticket as the record of Asks (docs/ASKS.md).

One ticket per task or decision, never one per Ask, in the tracker the deployment names (policy.yaml tickets.tracker:
home's Forgejo inbox, a work deployment's tracker), through ops/domain/trackers.py, whose shadow and write modes apply to
every write here, the opening of a ticket included (its own kind of write, open):
- Asks of one task share its ticket: an Ask's task, else its kind's one ticket (TICKET_OF: the tax desk's questions
  are one "Your taxes", a build's are its build's, a task's its task's); a kind with none (ideas wait for the
  ideas-as-tickets step, the journey's test item, tracker and pack approvals that are about the tracker itself) has no
  ticket, and its Asks live in the app;
- what a pass adds to a ticket is one comment with every new Ask of it (the question, its answers, how to answer: in the
  app, or a reply on the ticket; a gate only in the app, by a tap), and each answer goes back once, with the person, the
  role, the channel and how the words were read;
- a private Ask's ticket gets a line that a private question waits in the app, never its question or figures;
- a reply on the ticket (the poller's events, ops/runreg.py hand) is an answer in words, read by the interpreter; at a gate
  it is a comment.
Only Asks created after tickets began (tickets.json "since", set by the first pass) get a ticket: a migration of what
already waits never opens tickets in bulk (11 Nov 2026: 89 issues opened at once). Where the deployment has no ticket
channel, the tracker is read-only, or a write is in shadow, nothing leaves: the shadow keeps it for the owner's
judgement, and the Ask's history says so.

    sync(now)        new Asks to their ticket, answers back
    replies(events)  a tracker's new comments on an Ask's ticket, as answers in words
"""
import hashlib
import json
import time

import asks as AK
import statefile as SF
import textcap as TC

APP_LINK = "#/decide?a="                             # the Ask in the app (the deployment's app address goes in front)
# a kind of Ask without a task of its own -> its one ticket: (key, title), "source" for one per source item, None for none
TICKET_OF = {"tax": ("taxes", "Your taxes"), "phone-routine": ("phone-cleanup", "AI phone cleanup"),
             "memory": ("memory", "Memory"), "memory-remember": ("memory", "Memory"), "memory-forget": ("memory", "Memory"),
             "memory-move": ("memory", "Memory"), "mail-sort": ("mail-sort", "Sorting out mail"), "setup": ("setup", "Setup"),
             "coding": "source", "coding-low-risk": "source", "task-start": "source", "research": "source",
             "task-questions": "source", "task-resume": "source", "shopping-buy": "source", "agent-request": "source"}


def _tr():
    from domain import trackers as TR
    return TR


def since_path():
    return AK.home() / "tickets.json"


def since(now=None):
    """When tickets began: the first pass sets it; an Ask created before it never gets a ticket."""
    s = SF.load(since_path(), None)
    if not s:
        s = {"since": now or time.time()}
        SF.save(since_path(), s)
    return float(s["since"])


def group(a):
    """-> (ticket key, title) of the Ask's one ticket, or None when its kind has none."""
    if a.get("task"):
        return str(a["task"]), a["question"]
    g = TICKET_OF.get(a["kind"])
    if g == "source":                                # a build's, a task's, a purchase's own: the item it is about
        src = str(a["source"]).removeprefix("dq:").split(":")
        return ":".join(src[:2]), a["question"]
    return g


def where(pol=None):
    """-> (tracker entry, "") when Asks go to tickets, else (None, why not)."""
    pol = pol or AK.policy()
    if "ticket" not in AK.channels(pol):
        return None, "this deployment has no ticket channel"
    name = (pol.get("tickets") or {}).get("tracker")
    if not name:
        return None, "this deployment names no tracker for tickets"
    TR = _tr()
    try:
        t = TR.find(name)
    except Exception as e:                           # no trackers.yaml readable: the Ask stays in the app
        return None, f"its trackers could not be read ({type(e).__name__})"
    if not t or TR.refused(t):
        return None, f"no usable tracker {name!r}"
    if TR.read_only(t):
        return None, f"{name} is read-only (write: off)"
    return t, ""


def body_of(a):
    """One Ask in its ticket's comment, in the product's words."""
    if a.get("sensitivity") == "private":
        return f"{AK.outward(a)} Answer it in the app: {APP_LINK}{a['id']}"
    chips = [c["label"] for c in a.get("choices") or [] if not c.get("href")]
    how = ("Answer it in the app with a tap: a reply here is kept as a comment." if a.get("gate")
           else "Answer it in the app, or reply here in your own words.")
    return "\n".join(x for x in (f"**{a['question']}**", a.get("why") or "", f"Answers: {', '.join(chips)}" if chips else "",
                                 how, f"{APP_LINK}{a['id']}") if x)


def answer_of(a):
    ans = a.get("answer") or {}
    label = next((c["label"] for c in a.get("choices") or [] if c["id"] == ans.get("outcome")), ans.get("outcome") or "")
    if ans.get("dismissed"):
        what = "Dismissed" + (f": {ans['words']}" if ans.get("words") else "")
    else:
        what = f"Answered: {label}" + (f" (understood from “{ans['words']}” as {ans['interpreted_as']})" if ans.get("interpreted_as") else "")
    if a.get("sensitivity") == "private":
        what = "Answered in the app." if not ans.get("dismissed") else "Dismissed in the app."
    who = ans.get("person") or AK.STACK
    return f"{a['question'] if a.get('sensitivity') != 'private' else AK.outward(a)}\n{what}\nBy {who} ({ans.get('role') or a.get('role')}), via {ans.get('via')}."


def _record(a, **kw):
    """Fields of the Ask's ticket record, and one history line when it is kept here and why."""
    c = AK.connect()
    with AK._lock:
        b = AK.get(a["id"], c)
        if not b:
            return None
        said = kw.get("ticket_local") and kw["ticket_local"] != b.get("ticket_local")
        b.update(kw)
        AK._put(c, b, time.time())
        if said:
            AK._history(c, a["id"], "ticket", time.time(), kept="here", why=kw["ticket_local"])
    return b


def _wid(*parts):
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:20]   # cap: id


def ticket_of(t, key, title, ad=None):
    """The ticket of a task: opened once (a write of kind open, so the shadow and write: off apply). -> its tracker/key,
    or ("", why) while it waits."""
    r = _tr().open_item(t["name"], TC.fit(title, 200, "the whole question is in the app"), f"Questions about {title}, asked in the app.",   # cap: api (a ticket's title)
                        f"ticket-{_wid(key)}", ad=ad)
    if r.get("refused"):
        return "", r.get("why") or "refused"
    if r.get("shadow"):
        return "", "its new ticket waits in shadow for your judgement"
    if r.get("off"):
        return "", f"{t['name']} is read-only (write: off)"
    if not r.get("key"):
        return "", "the tracker did not say which item it opened"
    return f"{t['name']}/{r['key']}", ""


def sync(now=None, ad=None, pol=None):
    """New Asks to their ticket (one comment per ticket and pass), answers back once. -> lines of what it did."""
    t, why = where(pol)
    start = since(now)
    did, fresh = [], {}
    for a in AK.listing(("open", "escalated", "answered", "dismissed")):
        if a.get("app_only") or a.get("test") or (a.get("created") or 0) < start:
            continue                                 # what waited before tickets began stays in the app (11 Nov 2026)
        g = group(a)
        if g is None:
            continue
        if not t:
            if a.get("ticket_local") != why:
                _record(a, ticket_local=why)
            continue
        if a["status"] in ("open", "escalated") and not a.get("ticket_said"):
            fresh.setdefault(g, []).append(a)
        elif a["status"] in ("answered", "dismissed") and a.get("ticket") and a.get("answer") and not a.get("ticket_answered") \
                and (a.get("pending") or {}).get("state") != "held":
            try:
                tracker, key = a["ticket"].split("/", 1)
                aid = (a["answer"] or {}).get("answer_id") or "x"
                r = _tr().write({"tracker": tracker, "kind": "comment", "key": key, "body": answer_of(a), "write_id": f"ans-{aid}"}, ad=ad)
                _record(a, ticket_answered=True, ticket_state="shadow" if r.get("shadow") else "written")
                did.append(f"{a['id']} answer to {a['ticket']}{' (in shadow)' if r.get('shadow') else ''}")
            except Exception as e:                   # the tracker away: tried again on the next pass
                did.append(f"{a['id']} answer not written: {type(e).__name__}: {e}")
    for (key, title), asks in fresh.items():
        try:
            ticket = next((x["ticket"] for x in AK.listing(AK.STATUSES) if x.get("ticket") and group(x) == (key, title)), "") \
                or next((x["ticket"] for x in AK.listing(AK.STATUSES) if x.get("ticket") and group(x) and group(x)[0] == key), "")
            if not ticket:
                ticket, wait = ticket_of(t, key, title, ad)
                if not ticket:
                    for a in asks:
                        if a.get("ticket_local") != wait:
                            _record(a, ticket_local=wait)
                    continue
            tracker, k = ticket.split("/", 1)
            body = "\n\n---\n\n".join(body_of(a) for a in asks)
            r = _tr().write({"tracker": tracker, "kind": "comment", "key": k, "body": body,
                             "write_id": f"asks-{_wid(*sorted(a['id'] for a in asks))}"}, ad=ad)
            for a in asks:
                _record(a, ticket=ticket, ticket_said=True, ticket_state="shadow" if r.get("shadow") else "written", ticket_local=None)
            did.append(f"{len(asks)} question{'s' if len(asks) != 1 else ''} to {ticket}{' (in shadow)' if r.get('shadow') else ''}")
        except Exception as e:                       # the tracker away: tried again on the next pass; the Asks live in the app
            did.append(f"{key} not written: {type(e).__name__}: {e}")
    return did


def replies(events, now=None, log=print):
    """A tracker's new comments (trackers.poll's events) on a waiting Ask's ticket: each an answer in words through the
    same path as the app's (a gate keeps it as a comment). The comment's author is the person; one comment answers once.
    A ticket that holds several waiting Asks takes a reply only when one Ask waits there (otherwise which one is meant
    is not clear, and the log says so)."""
    waiting = {}
    for a in AK.listing(AK.WAITING):
        if a.get("ticket"):
            waiting.setdefault(a["ticket"], []).append(a)
    n = 0
    for e in events or []:
        here = waiting.get(f"{e.get('tracker')}/{e.get('key')}", [])
        if len(here) > 1:
            log(f"asks: a reply on {e.get('tracker')}/{e.get('key')} is no answer: {len(here)} questions wait there; answer them in the app")
            continue
        for a in here:
            for s in e.get("said") or []:
                if not str(s.get("text") or "").strip():
                    continue
                aid = "tk" + _wid(a["id"], s.get("ref"))
                try:
                    AK.answer(a["id"], answer_id=aid, person=s.get("author") or "", via="ticket",
                              words=TC.limit(str(s["text"]), AK.WORDS_MAX, "the reply"), now=now)
                    n += 1
                except ValueError as x:              # someone outside the role, or answered already: said in the log
                    log(f"asks: a reply on {a['ticket']} is no answer: {x}")
    return n


if __name__ == "__main__":
    print(json.dumps(sync(), indent=1))
