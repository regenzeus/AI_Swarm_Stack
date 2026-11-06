"""The team room (SWM-107): what the agents do together, as one timeline of lines merged from the Swarm service's
Ledger (the events on the shared work and the Board's messages) and the runtime record (what agents ask each other
through their tools, and the runs nobody asked for). Nothing here asks an agent to post: the room is drawn from what
the agents do anyway, and an agent that stays in its lane simply has lines of its own work.

A line is {ts, type, actor, target, verb, title, text, detail, state, ref}; its type is one of
  ask     one agent asks another through a tool (a mission asks the scout), the answer in detail
  help    an agent works on another agent's artifact (evidence, a link, an update): a step into another's lane
  talk    a Board message between agents or to a room
  work    an agent's (or the checker's, or the stack's) work on the shared artifacts: proposes, readies, ships, proves
  you     your decisions and messages
  status  a run that ended with no one asking for it, and the stack's routine bookkeeping (off in the app at first)
interactions.py adds use, hand and tell, and your chat turns, and every line says in `to` who it reached: the map's
lines and the pair filter are counted from that (target is only what the line's head shows).
"""
import json

TYPES = ("ask", "help", "talk", "work", "you", "status")
KIND = {"idea": "idea", "agent_change": "agent change", "task": "task", "finding": "finding", "report": "report", "build": "build",
        "wiki": "wiki", "purchase": "purchase"}
STATE_VERB = {"open": "opened", "ready": "marked ready", "active": "started", "checking": "shipped, now checking", "done": "proved",
              "declined": "declined", "gone": "closed", "merged": "merged", "blocked": "blocked", "draft": "drafted"}
OWNER_VERB = {"active": "approved", "declined": "declined", "done": "confirmed", "open": "reopened", "gone": "closed", "checking": "shipped"}
ACT_VERB = {"request": "asks", "inform": "tells", "propose": "proposes to", "handoff": "hands over to", "ack": "answers"}


def who(actor, cls):
    """The name a line shows: you, the checker, the stack (the runner and its rules) or the agent."""
    return "you" if cls == "owner" else "checker" if cls == "checker" else "stack" if cls in ("system", "rule") else actor


def _payload(p):
    if isinstance(p, dict):
        return p
    try:
        return json.loads(p or "{}") or {}
    except ValueError:
        return {}


def event_line(e):
    """One Ledger event as a line, or None for the events the Board's messages already show."""
    if e["kind"] in ("message", "request"):
        return None
    p, cls, kind, aid = _payload(e.get("payload")), e["cls"], e["kind"], e.get("artifact_id")
    owner = e.get("owner") or ""
    thing = f'{KIND.get(e.get("akind"), e.get("akind") or "item")} #{aid}' if aid else ""
    others = bool(owner) and owner != "system" and cls == "agent" and e["actor"] != owner       # in another agent's lane
    mine = f"{owner}'s " if others else ""
    if kind == "create":
        verb = f"proposed {thing}"
    elif kind == "evidence":
        verb = f"added evidence to {mine}{thing}"
    elif kind == "transition":
        to = p.get("to", "")
        verb = f'{(OWNER_VERB if cls == "owner" else STATE_VERB).get(to, to)} {mine}{thing}'
    elif kind == "link":
        verb = f"linked {mine}{thing}" + (f' to #{p["dst"]}' if p.get("dst") else "")
    elif kind == "ref":
        verb = f'linked {p.get("system", "")} {p.get("ref", "")} to {thing}'.replace("  ", " ")
    elif kind == "update":
        verb = f"updated {mine}{thing}"
    elif kind == "help_verdict":
        verb = f'judged {p.get("helper", "")}\'s help on {thing}: {"useful" if p.get("useful") else "not useful"}'
    elif kind == "pause":
        verb = ("resumed " if p.get("on") is False else "paused ") + str(p.get("agent") or "agents")
    else:
        verb = f"{kind} {thing}".strip()
    typ = ("you" if cls == "owner" else "help" if others and kind in ("evidence", "link", "update", "create")
           else "status" if cls in ("system", "rule") and kind in ("ref", "update", "create") else "work")
    text = p.get("text") if kind == "evidence" else e.get("reason") or ""
    ref = {"artifact": aid} if aid else {}
    if p.get("help"):                                     # SWM-109: it named why the owner would not see it, and can be judged
        ref["help"] = e["seq"]
    if kind == "help_verdict":
        ref["judges"] = p.get("seq")
    to = [owner] if others or (cls == "owner" and owner and owner != "system") else [str(p["agent"])] if kind == "pause" and p.get("agent") else []
    return {"ts": e["ts"], "type": typ, "actor": who(e["actor"], cls), "target": owner if others else "", "to": to, "verb": verb,
            "title": e.get("title") or "", "text": text or "",
            "detail": f'Why {owner} would not see it, it says: {p["help"].get("unseen", "")}' if p.get("help") else "", "state": "", "ref": ref}


def message_line(m):
    """One Board message as a line (whole: the owner reads everything, SWM-11)."""
    rec = m.get("recipients")
    rec = json.loads(rec) if isinstance(rec, str) else rec or []
    rec = ["you" if str(r).startswith("owner") else r for r in rec if not str(r).startswith("room:")]
    ctx = m.get("context") or ""
    shown = rec + (["#" + ctx[5:]] if ctx.startswith("room:") else [])      # who it reached, and the room it went through
    mine = m.get("sender_cls") == "owner"
    return {"ts": m["ts"], "type": "you" if mine else "talk", "actor": "you" if mine else m["sender"], "target": ", ".join(shown), "to": rec,
            "verb": ACT_VERB.get(m.get("act") or "inform", m.get("act") or "tells"), "title": "", "text": m.get("text") or "",
            "detail": m.get("state_reason") or "", "state": m.get("state") or "",
            "ref": {"context": ctx, **({"artifact": m["artifact_id"]} if m.get("artifact_id") else {})}}


def ask_line(x):
    """A tool call between agents (runrecord.delegations): the question, and the answer whole in detail."""
    return {"ts": x["ts"], "type": "ask", "actor": x["from"], "target": x["to"], "to": [x["to"]], "verb": "asks", "title": "", "text": x.get("ask") or "",
            "detail": x.get("answer") or "", "state": x.get("state") or "", "ref": {"run": x["run"]}, "world": x.get("world") or "real", "certainty": x.get("certainty") or "recorded"}


def run_line(r):
    """A finished run no one asked for (a schedule, an event): status."""
    return {"ts": r.get("ended") or r["started"], "type": "status", "actor": r["lane"], "target": "", "to": [], "verb": f'ran {r.get("name") or r["run"]}',
            "title": "", "text": "", "detail": "", "state": r.get("state") or "", "ref": {"run": r["run"]}, "world": r.get("world") or "real"}


def lines(feed, asks, runs, extra=None):
    """Every line of the window, oldest first (extra: the lines interactions.py adds)."""
    out = [x for x in (event_line(e) for e in (feed or {}).get("events") or []) if x]
    out += [message_line(m) for m in (feed or {}).get("messages") or []]
    out += [ask_line(x) for x in asks or []]
    out += [run_line(r) for r in runs or [] if r.get("ended") and not r.get("by") and (r.get("cause") or {}).get("kind") != "you"]
    out += extra or []
    return sorted(out, key=lambda x: x["ts"])
