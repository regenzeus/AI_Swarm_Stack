"""Who works with whom (SWM-110 to SWM-115): one list of interactions, from which the map, the Activity feed and the
timeline are drawn, so a line's number is always what its tap opens. Read from the records that exist when the page asks;
a second log would drift from them. Only three facts are recorded for it: a crew run's cause (ops/crew.py), a message's
sender (ops/notify.py, public/told.jsonl) and a hand-over through a file (ops/runtime.py link, public/links.jsonl).

Each run gets one cause (you, agent, clock, rule, alert, test, unknown, or "unrecorded" for a crew run from before its
cause was kept), and a world (real or test); the second record of one piece of work (a Claude task's runner and its
Claude run) is a half and counts once.

A line (teamroom.py) adds `to` (who it reaches: the map's lines and the pair filter), `world` and `certainty`
(recorded, or matched: worked out from timing). The kinds this module adds:
  you   you asked (a chat turn, Run now, a typed task) or decided
  tell  an agent or the stack told you (Telegram, push, e-mail)
  use   an agent used a tool that acts through another (Main on the AI phone, Inbox on Gmail)
  hand  a hand-over through a file or an output (a plan's next step, a mail filed for the curator, an idea to the builder)
"""
import json
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

TEST_SOURCES = ("trial:", "probe:", "gate")
# every tool server of config/litellm/config.yaml, and what a call to it means here (tests/test_interactions.py checks it):
# use: the map's line to that dot; ask: a run of its own, already an ask; memory: the Memory layer; own: the agent's own hands
TOOL_SERVERS = {"phone": ("use", "phone"), "mail": ("use", "gmail"), "house": ("use", "house"), "missions": ("use", "mission"),
                "research": ("ask", "scout"), "claude": ("ask", "claude"),
                "qmd": ("memory", ""), "memory": ("memory", ""), "memorypublic": ("memory", ""), "jobs": ("own", ""), "fetch": ("own", ""), "files": ("own", ""), "browser": ("own", ""), "graphify": ("own", "")}
ONLY_CHANGES = {"missions": re.compile(r"create|update|run|pause|resume|archive")}   # looking at the list of missions is no use of one
YOURS = (None, "owner", "voice")                                         # a chat's origin (server.py origin_of): yours, or the stack's own checks and the AI phone
DRAWN = ("ask", "use", "hand", "talk", "you", "tell", "help")            # what the map draws; work and status have no one at the other end
UPKEEP = {"connect", "session ended"}                                    # an AI phone session that only reconnected: nobody asked
# the owner's taps at the app's door that no other record names: action -> (what the line says, whom it reaches)
OWNER_ACTS = {"build_approve": ("approved a build of", "builder"), "build_approve_all": ("approved the builds of", "builder"), "build_reject": ("turned down a build of", "builder"),
              "build_revise": ("asked for changes from", "builder"), "build_assign": ("gave a build to", "builder"), "phone_cleanup_do": ("approved a step of", "phone-cleanup"),
              "phone_cleanup_do_all": ("approved the steps of", "phone-cleanup"), "phone_cleanup_undo": ("undid a step of", "phone-cleanup"), "phone_cleanup_dismiss": ("set aside a step of", "phone-cleanup"),
              "task_answer": ("answered", "conductor"), "task_approve": ("approved a plan of", "conductor"), "task_cancel": ("cancelled a task of", "conductor"), "task_retry": ("retried a task of", "conductor"),
              "health_ack": ("acknowledged a finding of", "doctor"), "pause": ("paused", "mission"), "resume": ("resumed", "mission"), "shop_decide": ("decided on a purchase of", "mission"), "phone_decide": ("decided on a request of", "phone"),
              "mailsort_go": ("chose the senders to sort out for", "postmaster"), "mailsort_keep": ("kept a sender from", "postmaster"), "mailsort_undo": ("undid a sort of", "postmaster")}
STACK_TITLES = {"Agent health", "Crew", "Trials", "Triggers", "System", "Swarm", "Autonomy"}
SENDERS = {"Health doctor": "doctor", "Inbox digest": "inbox", "Postmaster": "postmaster", "Mail sorter": "postmaster", "Checker": "checker", "Coach": "coach", "Librarian": "memory", "Memory Keeper": "memory",
           "Test agent": "tests", "Phone cleanup": "phone-cleanup", "Phone check": "phone-check", "Journey checks": "journeys", "Maintainability review": "maintainability"}


def _task_id(x):
    m = re.match(r"^(?:task:|task-intake:)(\d+)", x or "")
    return int(m[1]) if m else None


def _cause(kind, who="", why="", certainty="recorded"):
    return {"kind": kind, "who": who, "why": why, "certainty": certainty}


def _is_test(r, t, parent, prompts=(), automated=()):
    run, ref = r["run"], r.get("ref") or ""
    return bool(ref[5:] in automated or (r.get("title") or "")[:60] in prompts or (t and str(t.get("source")).startswith(TEST_SOURCES)) or run.startswith(("eval:", "check:")) or ref.startswith(("eval:", "bench:"))   # cap: id (the same head mark_test keeps)
                or r["lane"] == "evals" or ":nch-" in run or str(r.get("repo") or "").startswith("trial-") or (parent and parent.get("world") == "test"))


def _nearest_call(calls, ts):
    """The newest ask made shortly before a run started -> its caller's lane."""
    best = None
    for at, lane in calls or []:
        if ts - 7200 <= at <= ts + 2 and (best is None or at > best[0]):
            best = (at, lane)
    return best[1] if best else None


def classify(runs, tasks=None, ctasks=None, builds=None, service=None, claude_calls=None, test_prompts=(), automated=()):
    """Give every run of a window its cause, world and half, and settle `by` to a real agent (never the lump "hermes")."""
    tasks, ctasks, builds, service = tasks or {}, ctasks or {}, builds or {}, service or {}
    seen = {}
    for r in sorted(runs, key=lambda x: x["started"]):
        run, ref, lane = r["run"], r.get("ref") or "", r["lane"]
        t = tasks.get(_task_id(run) or _task_id(ref) or _task_id(r.get("parent")))
        parent = seen.get(r.get("parent"))
        by = r.get("by")
        certainty = "recorded"
        ct = ctasks.get(int(run.split(":")[1])) if re.fullmatch(r"claude-task:\d+", run) else None
        if by == "hermes" or (ct and ct.get("source") == "chat" and not by):       # Hermes' claude tool: Main or a mission's agent
            by, certainty = _nearest_call(claude_calls, r["started"]), "matched"
        if ct and not by and str(ct.get("source")).startswith("crew:"):
            by = ct["source"][5:]
        r["by"] = by
        r["half"] = bool(by and by == lane)
        r["world"] = "test" if _is_test(r, t, parent, test_prompts, automated) else "real"
        rec = r.get("recorded")
        if r["world"] == "test":
            c = _cause("test", why=str((t or {}).get("source") or "a replay"))
        elif rec:
            c = _cause(rec.get("kind") or "unknown", rec.get("who") or "", rec.get("why") or "")
        elif ref.startswith("chat:"):
            c = _cause("you", why="a chat turn")
        elif (r.get("title") or "").startswith("[Spoken") or run.startswith("house-voice:"):
            c = _cause("you", why="spoken", certainty="matched")
        elif r.get("trigger") in ("manual", "schedule", "event"):
            c = _cause({"manual": "you", "schedule": "clock", "event": "rule"}[r["trigger"]], why=f"the mission's {r['trigger']}")
        elif by and by != lane:
            c = _cause("agent", by, certainty=certainty)
        elif t and str(t.get("source")).startswith("rule:"):
            c = _cause("rule", why=str(t["source"]))
        elif t and t.get("source") in ("app", "chat"):
            c = _cause("you", why="a task you gave")
        elif t and t.get("source") == "door":
            c = _cause("agent", str(t.get("door") or ""), why="its door's work", certainty="matched")
        elif ct and ct.get("source") == "app":
            c = _cause("you", why="a question from the app")
        elif run in service:
            who = service[run]
            c = _cause("clock", why="its own upkeep", certainty="matched") if who == "self" else _cause("agent", who, certainty="matched") if who else _cause("unknown")
            r["by"] = who if who and who != "self" else None
        elif run.startswith("crew:"):
            c = _cause("unrecorded", why="clock, Run now or an alert: not recorded for this run")
        elif run.startswith(("hermes:curator:", "house")) or (r.get("title") or "").startswith("You are running as Hermes' background"):
            c = _cause("clock", why="its timer", certainty="matched")
        elif run.startswith("build:"):
            b = builds.get(int(run.split(":")[1])) or {}
            c = _cause("you", why="your OK on a build", certainty="matched") if b else _cause("unknown")
        elif r["half"]:
            c = _cause("agent", by)
        else:
            c = _cause("unknown")
        r["cause"] = c
        seen[run] = r
    return runs


def coverage(runs):
    """How much of the window has a known cause: shown on screen, so what is unknown is never hidden."""
    one = [r for r in runs if not r.get("half")]
    kinds = {}
    for r in one:
        kinds[r["cause"]["kind"]] = kinds.get(r["cause"]["kind"], 0) + 1
    unknown, unrecorded = kinds.get("unknown", 0), kinds.get("unrecorded", 0)
    return {"runs": len(one), "known": len(one) - unknown - unrecorded, "unknown": unknown, "unrecorded": unrecorded,
            "tests": kinds.get("test", 0), "kinds": kinds}


def nodes(runs, edge_list, tests=False):
    """One dot per agent: its work counted once, tests out unless asked for; `failing` when its newest run failed (a failure
    from days ago that has been followed by good runs no longer rings the dot)."""
    out, newest = {}, {}
    for r in sorted(runs, key=lambda x: x["started"]):
        if r.get("half") or (r.get("world") == "test" and not tests):
            continue
        n = out.setdefault(r["lane"], {"id": r["lane"], "runs": 0, "live": 0, "failed": 0, "failing": False, "last": 0, "causes": {}})
        n["runs"] += 1
        n["live"] += r["state"] == "running"
        n["failed"] += r["state"] in ("failed", "stalled")
        n["last"] = max(n["last"], r.get("last") or r["started"])
        k = r["cause"]["kind"]
        n["causes"][k] = n["causes"].get(k, 0) + 1
        if r["state"] != "running":
            newest[r["lane"]] = r["state"]
    for k, st in newest.items():
        out[k]["failing"] = st in ("failed", "stalled")
    for e in edge_list:
        for a in (e["from"], e["to"]):
            out.setdefault(a, {"id": a, "runs": 0, "live": 0, "failed": 0, "failing": False, "last": 0, "causes": {}})
    return sorted(out.values(), key=lambda x: -x["runs"])


def edges(lines):
    """The map's lines, counted from the feed's rows: per direction and kind, so a line's number is what its tap opens."""
    out = {}
    for x in lines:
        if x["type"] not in DRAWN:
            continue
        for to in x.get("to") or []:
            if to == x["actor"]:
                continue
            e = out.setdefault((x["actor"], to, x["type"]), {"from": x["actor"], "to": to, "kind": x["type"], "n": 0, "live": 0, "last": 0})
            e["n"] += 1
            e["live"] += x.get("state") == "running"
            e["last"] = max(e["last"], x["ts"])
    return sorted(out.values(), key=lambda e: -e["n"])


def between(line, picked):
    """The pair filter (swarm.js swBetween is the same rule): one of the picked did it, and it reached another of them."""
    return line["actor"] in picked and any(t in picked and t != line["actor"] for t in line.get("to") or [])


def service_callers(calls, sessions, open_runs):
    """Who an AI phone or Gmail session worked for: the agent whose calls fall in it (recorded), or the only other run open
    when it started (matched), "self" when it only reconnected, or None."""
    out = {}
    for s in sessions:
        node = "phone" if s["run"].startswith("phone:") else "gmail"
        hit = {c["lane"] for c in calls if c["node"] == node and s["started"] - 60 <= c["ts"] <= (s["ended"] or s["started"]) + 60}
        if hit:
            out[s["run"]] = sorted(hit)[0]
        elif set(s.get("titles") or []) <= UPKEEP:
            out[s["run"]] = "self"
        else:
            near = {r["lane"] for r in open_runs if r["started"] <= s["started"] + 2 and (r["ended"] or s["started"]) >= s["started"] - 2
                    and r["lane"] not in ("checker", "scout", "phone", "gmail", "doctor")}
            out[s["run"]] = near.pop() if len(near) == 1 else None
    return out


def tool_calls(rows):
    """The runtime record's call events -> the ones that act through another: [{run, lane, node, tool, ts, world?}]."""
    out = []
    for r in rows:
        tool = (r["title"] or "").split("__")[-1]
        if "_windows_" in tool and r["lane"] != "windows":   # PLT-31: on the missions server, but a line of its own
            out.append({"run": r["run"], "lane": r["lane"], "node": "windows", "tool": tool, "ts": r["ts"]})
            continue
        kind, node = TOOL_SERVERS.get(tool.split("_")[0], ("", ""))
        if kind != "use" or r["lane"] == node:
            continue
        only = ONLY_CHANGES.get(tool.split("_")[0])
        if only and not only.search(tool):
            continue
        out.append({"run": r["run"], "lane": r["lane"], "node": node, "tool": tool, "ts": r["ts"]})
    return out


def use_lines(calls, sessions, service, worlds):
    """One line per agent run per tool (Main drove the AI phone: 84 calls in that run), and one per session with no calls of
    its caller in the record (Inbox's Gmail sessions before it recorded them)."""
    grouped = {}
    for c in calls:
        g = grouped.setdefault((c["run"], c["node"]), {"lane": c["lane"], "ts": c["ts"], "tools": {}})
        g["tools"][c["tool"]] = g["tools"].get(c["tool"], 0) + 1
    out = []
    for (run, node), g in grouped.items():
        n = sum(g["tools"].values())
        text = f"{n} call{'s' if n != 1 else ''}: " + ", ".join(f"{k} {v}" for k, v in sorted(g["tools"].items(), key=lambda x: -x[1]))
        out.append({"ts": g["ts"], "type": "use", "actor": g["lane"], "to": [node], "target": node, "verb": "used", "title": "", "text": text, "detail": "", "state": "",
                    "ref": {"run": run}, "world": worlds.get(run, "real"), "certainty": "recorded"})
    used = {(c["lane"], c["node"]) for c in calls}
    for s in sessions:
        who, node = service.get(s["run"]), "phone" if s["run"].startswith("phone:") else "gmail"
        if who and who != "self" and (who, node) not in used:
            out.append({"ts": s["started"], "type": "use", "actor": who, "to": [node], "target": node, "verb": "used", "title": "", "text": "One session, matched by its timing", "detail": "", "state": "",
                        "ref": {"run": s["run"]}, "world": "real", "certainty": "matched"})
    return out


def prompt_lines(chats, since, runs=()):
    """Your chat and spoken turns, each with its answer. Chats started by the stack's own checks or the AI phone aren't yours."""
    by_chat = {}
    for r in runs:
        if (r.get("ref") or "").startswith("chat:"):
            by_chat.setdefault(r["ref"][5:], []).append(r["started"])
    out = []
    for c in chats:
        if c.get("origin") not in YOURS:
            continue
        ms = c.get("messages") or []
        for i, m in enumerate(ms):
            if m.get("role") != "user" or not isinstance(m.get("ts"), (int, float)) or m["ts"] < since:
                continue
            answer = next((x.get("content") for x in ms[i + 1:i + 2] if x.get("role") == "assistant"), "")
            spoken = bool(m.get("room"))
            out.append({"ts": m["ts"], "type": "you", "actor": "you", "to": ["main"], "target": "main", "verb": "said to" if spoken else "asked",
                        "title": "", "text": m.get("content") or "", "detail": answer or "", "detail_label": "The answer", "state": "",
                        "ref": {"chat": c.get("id")}, "world": "real", "certainty": "recorded"})
    return out


def run_lines(runs):
    """What a run's cause says that no other record draws: you ran it, a spoken request, an alert woke it."""
    out = []
    for r in runs:
        c = r.get("cause") or {}
        if r.get("half") or r.get("world") == "test":
            continue
        if c.get("kind") == "you" and not (r.get("ref") or "").startswith("chat:") and not r["run"].startswith(("task", "claude-task:", "build:", "house-voice:")):
            spoken = (r.get("title") or "").startswith("[Spoken")
            out.append({"ts": r["started"], "type": "you", "actor": "you", "to": [r["lane"]], "target": r["lane"], "verb": "said to" if spoken else "ran",
                        "title": "" if spoken else r.get("name") or "", "text": r.get("title") or "" if spoken else "", "detail": "", "state": r["state"],
                        "ref": {"run": r["run"]}, "world": "real", "certainty": c.get("certainty") or "recorded"})
        elif c.get("kind") == "alert":
            out.append({"ts": r["started"], "type": "hand", "actor": c.get("who") or "stack", "to": [r["lane"]], "target": r["lane"], "verb": "alerted",
                        "title": "", "text": c.get("why") or "", "detail": "", "state": r["state"], "ref": {"run": r["run"]}, "world": "real", "certainty": "recorded"})
    return out


def task_lines(tasks, ctasks, since):
    """A task you typed, and a question you gave Claude from the app."""
    out = []
    for t in tasks.values():
        if t.get("source") == "app" and (t.get("ts") or 0) >= since:
            out.append({"ts": t["ts"], "type": "you", "actor": "you", "to": ["intake"], "target": "intake", "verb": "gave a task to", "title": "", "text": t.get("text") or "",
                        "detail": "", "state": "", "ref": {"task": t["id"]}, "world": "real", "certainty": "recorded"})
    for i, t in ctasks.items():
        if t.get("source") == "app" and (t.get("ts") or 0) >= since:
            out.append({"ts": t["ts"], "type": "you", "actor": "you", "to": ["claude"], "target": "claude", "verb": "asked", "title": "", "text": t.get("question") or "",
                        "detail": t.get("answer") or "", "detail_label": "The answer", "state": "", "ref": {"run": f"claude-task:{i}"}, "world": "real", "certainty": "recorded"})
    return out


def plan_lines(steps, tasks, since):
    """A plan's hand-overs: a step that starts from another agent's finished step."""
    at = {(s["task"], s.get("occ"), s["idx"]): s for s in steps}
    out = []
    for s in steps:
        ts = s.get("ts") or 0
        if ts < since:
            continue
        try:
            after = json.loads(s.get("after") or "[]")
        except ValueError:
            after = []
        for a in after if isinstance(after, list) else []:
            f = at.get((s["task"], s.get("occ"), a))
            if not f or f["agent"] == s["agent"]:
                continue
            t = tasks.get(s["task"]) or {}
            out.append({"ts": ts, "type": "hand", "actor": f["agent"], "to": [s["agent"]], "target": s["agent"], "verb": "handed over to", "title": s.get("title") or "",
                        "text": "", "detail": "", "state": "", "via": f"task #{s['task']}, step {s['idx']}", "ref": {"task": s["task"]},
                        "world": "test" if str(t.get("source")).startswith(TEST_SOURCES) else "real", "certainty": "recorded"})
    return out


def idea_lines(builds, proposals, owners, since):
    """The idea pipeline: whoever proposed it hands it to the builder once you have approved it."""
    props = {p["build_id"]: p for p in proposals if p.get("build_id")}
    out = []
    for b in builds:
        if (b.get("ts") or 0) < since:
            continue
        p = props.get(b["id"])
        who = (p or {}).get("source") or owners.get(b.get("idea"))
        if not who or who == "builder":
            continue
        via = f"proposal #{p['id']}" if p else f"idea #{b['idea']}"
        out.append({"ts": b["ts"], "type": "hand", "actor": who, "to": ["builder"], "target": "builder", "verb": "handed over to", "title": b.get("title") or "", "text": "", "detail": "",
                    "state": "", "via": via, "ref": {"build": b["id"], **({"artifact": b["idea"]} if b.get("idea") else {})},
                    "world": "test" if str(b.get("repo") or "").startswith("trial-") else "real", "certainty": "recorded"})
    return out


def link_lines(rows, since):
    """The hand-overs recorded where they happen (ops/runtime.py link): a mail filed for the curator or for a topic's report."""
    out = []
    for r in rows:
        if (r.get("ts") or 0) < since:
            continue
        out.append({"ts": r["ts"], "type": "hand", "actor": r["from"], "to": [r["to"]], "target": r["to"], "verb": r.get("verb") or "handed over to", "title": r.get("text") or "", "text": "", "detail": "",
                    "state": "", "via": r.get("via") or "", "ref": {"run": r["run"]} if r.get("run") else {}, "world": "real", "certainty": r.get("certainty") or "recorded"})
    return out


def owner_lines(rows, since):
    """Your taps at the app's door (OWNER_ACTS)."""
    out = []
    for r in rows:
        act = OWNER_ACTS.get(r.get("action"))
        if act and (r.get("ts") or 0) >= since:
            out.append({"ts": r["ts"], "type": "you", "actor": "you", "to": [act[1]], "target": act[1], "verb": act[0], "title": "", "text": r.get("text") or "", "detail": "", "state": "",
                        "ref": {}, "world": "real", "certainty": "recorded"})
    return out


def sender_of(r):
    """Who sent a message to the owner: its record since it was kept, before that its words."""
    if r.get("by"):
        return r["by"]
    text, title, cat = str(r.get("text") or ""), str(r.get("title") or ""), r.get("category")
    for name, who in SENDERS.items():
        if text.startswith(name):
            return who
    if title == "Tasks" or text.startswith("Task #"):
        return "conductor"
    if title == "Chat":
        return "main"
    if title == "House":
        return "house"
    if cat == "build":
        return "builder"
    if "AI phone" in text[:12]:
        return "phone"
    if text.startswith(("Vault", "Weekly curator")):
        return "curator"
    if text.startswith(("🛒", "⏳")):
        return "mission"
    if title and title not in STACK_TITLES and not title.startswith("Trigger proof"):
        return "mission"                                  # a mission's run tells under the mission's name
    if cat == "result" and not text.startswith("Good morning"):
        return "mission"
    return "stack"


def tell_lines(rows, since):
    """What the stack told you. One message on Telegram and as a push is one line; a message switched off never reached you."""
    out, last = [], {}
    for r in rows:
        ts = r.get("ts") or 0
        if ts < since or r.get("decision") in ("off", "duplicate"):
            continue
        key = (r.get("title"), r.get("text"))
        prev = last.get(key)
        if prev is not None and ts - prev["ts"] < 30:
            prev["ref"]["channels"] = sorted({*prev["ref"]["channels"], r.get("channel")})
            continue
        who = sender_of(r)
        x = {"ts": ts, "type": "tell", "actor": who, "to": ["you"], "target": "you", "verb": "told", "title": r.get("title") or "", "text": r.get("text") or "", "detail": "",
             "state": "failed" if r.get("decision") == "failed" else "", "ref": {"channels": [r.get("channel")]}, "world": "real", "certainty": "recorded" if r.get("by") else "matched"}
        last[key] = x
        out.append(x)
    return out


# ---------- reading the records ----------
def _iso(s):
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except ValueError:
        return 0


def _jsonl(path):
    out = []
    try:
        with open(path, errors="replace") as f:
            for ln in f:
                try:
                    out.append(json.loads(ln))
                except ValueError:
                    pass                                    # a torn line
    except OSError:
        return None
    return out


def _store(root):
    """The runner's records, read only -> (tasks, claude tasks, builds, proposals, steps), or empties when it can't be read."""
    tasks, ctasks, builds, props, steps = {}, {}, [], [], []
    db = sqlite3.connect(f"file:{root / 'missions.sqlite'}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        for r in db.execute("select id, text, source, door, created from tasks"):
            tasks[r["id"]] = {**dict(r), "ts": _iso(r["created"])}
        for r in db.execute("select id, question, source, answer, created from claude_tasks"):
            ctasks[r["id"]] = {**dict(r), "ts": _iso(r["created"])}
        for r in db.execute("select id, title, repo, idea, created from builds"):
            builds.append({**dict(r), "ts": _iso(r["created"])})
        props = [dict(r) for r in db.execute("select id, source, build_id from proposals")]
        for r in db.execute("select task, idx, title, agent, after, occ, started from task_steps where started is not null"):
            steps.append({**dict(r), "ts": _iso(r["started"])})
    finally:
        db.close()
    return tasks, ctasks, builds, props, steps


def _chats(root):
    out = []
    for f in (root / "app/chats").glob("*.json"):
        try:
            out.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            continue
    return out


def build(RT, TR, feed, hours=168, now=None, root="/missions", tests=False, private=True, feed_error=""):
    """The whole picture of a window: {lines, edges, nodes, runs, coverage, sources}. private=False (the AI phone) leaves out
    what you said and what you were told. A source that can't be read is named in `sources`, so nothing silently shows 0."""
    root, now = Path(root), now or time.time()
    since = now - float(hours) * 3600
    tl = RT.timeline(hours, now)
    runs = tl["runs"]
    sources = {"swarm": feed_error}
    try:
        tasks, ctasks, builds, props, steps = _store(root)
        sources["tasks"] = ""
    except sqlite3.Error as e:
        tasks, ctasks, builds, props, steps = {}, {}, [], [], []
        sources["tasks"] = f"{type(e).__name__}"
    c = RT.db()
    calls = tool_calls([{"run": r["run"], "lane": RT.lane_of(r["agent"]), "title": r["title"], "ts": r["ts"]} for r in c.execute(
        "select e.run, r.agent, e.title, e.ts from events e join runs r on r.run=e.run where e.kind='call' and e.ts>=? "
        "and (e.title like '%phone%' or e.title like '%mail%' or e.title like '%house%' or e.title like '%mission%')", (since,))])
    claude_calls = [(r["ts"], RT.lane_of(r["agent"])) for r in c.execute(
        "select e.ts, r.agent from events e join runs r on r.run=e.run where e.kind='call' and e.ts>=? and e.title like '%claude_claude_task'", (since - 7200,))]
    sessions = [dict(r) for r in runs if r["run"].startswith(("phone:", "mail:"))]
    for s in sessions:
        s["titles"] = [x["title"] for x in c.execute("select distinct title from events where run=? and kind<>'run'", (s["run"],))]
    service = service_callers(calls, sessions, [r for r in runs if not r["run"].startswith(("phone:", "mail:"))])
    prompts = {str(x.get("prompt")) for x in _jsonl(root / "public/test-prompts.jsonl") or []}
    chats = _chats(root)
    classify(runs, tasks, ctasks, {b["id"]: b for b in builds}, service, claude_calls, prompts, {c.get("id") for c in chats if c.get("origin") not in YOURS})
    worlds = {r["run"]: r["world"] for r in runs}
    told = _jsonl(root / "public/told.jsonl")
    links = _jsonl(root / "public/links.jsonl")
    sources["messages"] = "" if told is not None else "no record yet"
    sources["hand-overs"] = "" if links is not None else "no record yet"
    owners = {e.get("artifact_id"): e.get("owner") for e in (feed or {}).get("events") or [] if e.get("owner") not in (None, "", "system")}
    extra = [*use_lines(calls, sessions, service, worlds), *run_lines(runs), *prompt_lines(chats, since, runs), *task_lines(tasks, ctasks, since),
             *plan_lines(steps, tasks, since), *idea_lines(builds, props, owners, since), *link_lines(links or [], since), *tell_lines(told or [], since),
             *owner_lines(_jsonl(root / "app/actions.jsonl") or [], since)]
    asks = [a for a in RT.delegations(hours, None, now, runs=runs) if not a["run"].startswith(("phone:", "mail:"))]    # a tool session is a use, drawn once
    lines = TR.lines(feed, asks, [r for r in runs if not r.get("half")], extra)
    if not tests:
        lines = [x for x in lines if x.get("world") != "test"]
    if not private:
        lines = [x for x in lines if x["type"] != "tell" and x["actor"] != "you"]         # what you said and were told isn't the AI phone's to read
    e = edges(lines)
    return {"since": tl["since"], "now": tl["now"], "lines": lines, "edges": e, "nodes": nodes(runs, e, tests), "runs": runs,
            "coverage": coverage(runs), "sources": {k: v for k, v in sources.items() if v}}
