"""WFL-19 to WFL-21, WFL-23: the run register, the step service's record of every run n8n drives. It is the stack's
run truth next to the tasks table: n8n holds time and order only (DEC-51), the register holds what happened.

Under /srv/ai/missions/flows/register/ (files, so it survives a restart of the runner and of n8n):
    runs/<execution>.json          one run: its workflow, its item, and every step in order with its request, its whole
                                   answer, the files it made (artifact ids) and its times
    items/<tracker>/<key>.json     one tracker item: the runs it started (with their n8n executions once a step named
                                   them), the wait registered on it (wait_item), the comments no wait has taken yet
                                   (unread, each with its source and, in said, its author, time and text), and how often
                                   each of the run's waits timed out (reminded)
    events.json                    the event ledger: each tracker or pull-request event routed, by its identity
    outbox.json                    events the trackers handed on and routing has not placed yet; the trackers' cursors
                                   move only after their events are here
In a customer-class deployment n8n gets short answers (ops/flows.py lean) and the whole text lives here and in the
task's record. ops/domain/record.py export_run makes a run's one zip from it.

Routing (WFL-19): each event of trackers.poll() and forgework.poll_prs() is placed once, by (tracker, key, the change's
identity), also across a restart. A comment's source is the item (a tracker comment) or the pull request (a review
comment); a wait listens to one source (on: item, the default, pr, or any, WFL-32) and only that source answers it:
    - a run waits on the item (wait_item) and the event brings new comments of the wait's source: the wait is answered
      (outcome reply, with the comments' source, refs and texts); the other source's comments wait for a wait on them;
    - the item has no run yet: its workflow starts through n8n's webhook item/<pack>/<name> (the tracker's "workflow"),
      with {tracker, key, run, ref, comments}; the item is marked first, so an event never starts two runs;
    - otherwise the event is recorded; its new comments wait for the run's next wait_item, which takes them at once. A
      run that has ended is not started again, except that a new comment starts a new run when the tracker says
      restart: on_comment (default never). A run has ended when n8n's database says its execution finished.
An event without new comments (the stack's own write changes the item too) never wakes a wait for a reply. The
comments an event brings are others' only: the trackers leave out the stack's own, by their author or by the write mark
every write of the stack ends with (trackers.own, WFL-26), so the owner's reply wakes a run also where the stack writes
with the owner's account. A wait's answer carries reminded: how often a wait of that node in this run timed out before
(WFL-33), so a workflow reminds a set number of times and then ends.

    python3 ops/runreg.py poll                        one pass of the tracker poller (the crew job tracker-poll)
    python3 ops/runreg.py export <execution> <zip>    a run's one zip (ops/domain/record.py export_run)
    python3 ops/runreg.py                             the register's items and runs
"""
import contextlib
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import statefile as SF  # noqa: E402

ROOT = Path("/srv/ai/missions/flows/register")
N8N = "http://127.0.0.1:5678"                        # n8n's port on this machine; its webhooks are at its root, never under /n8n/
WORKFLOW = re.compile(r"[A-Za-z0-9_-]{1,64}/[A-Za-z0-9_.-]{1,80}")   # a pack's workflow, <pack>/<name>
EVENTS_KEPT = 20000                                  # limit: drops, the oldest event identities past 20,000 are forgotten; the trackers' cursors and seen comments already keep an old change from coming back
ENDED = ("success", "error", "crashed", "canceled")  # n8n's execution states of a run that is over
RESTART = ("never", "on_comment")
CREW_OUT = Path("/srv/ai/missions/crew")


def _now():
    return time.time()


def _iso(ts=None):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts or _now()))


def _read(p, default):
    return SF.load(p, default)


def _write(p, d):
    SF.save(p, d, indent=1)                          # whole or not at all: the ledger, the outbox, the runs and items


@contextlib.contextmanager
def locked():
    """One writer at a time: the runner's step threads and the poller's process share the register."""
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def safe(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(s)) or "_"


# ---------- runs: every step's request, answer, files and times ----------
def run_path(execution):
    return ROOT / "runs" / f"{safe(execution)}.json"


def step_begin(rid, req):
    """A step n8n handed over, kept once with its request (the resume URL is n8n's, not the run's)."""
    ex = str(req.get("execution") or "")
    if not ex:
        return
    with locked():
        r = _read(run_path(ex), {"execution": ex, "workflow": req.get("workflow") or "", "name": req.get("workflow_name") or "",
                                 "item": None, "steps": []})
        if any(s["rid"] == rid for s in r["steps"]):
            return
        r["steps"].append({"rid": rid, "kind": req.get("kind"), "node": req.get("node") or "", "title": req.get("title") or "",
                           "request": {k: v for k, v in req.items() if k != "resume_url"}, "started": _iso(), "ended": None,
                           "answer": None})
        if req.get("tracker") and req.get("key"):
            r["item"] = {"tracker": req["tracker"], "key": req["key"]}
        _write(run_path(ex), r)


def step_end(rid, req, answer):
    """The step's whole answer, the files it made (artifact ids) and when it ended."""
    ex = str(req.get("execution") or "")
    if not ex:
        return
    with locked():
        r = _read(run_path(ex), None)
        s = next((s for s in (r or {}).get("steps") or [] if s["rid"] == rid), None)
        if not s or s["answer"] is not None:
            return
        s["answer"], s["ended"] = answer, _iso()
        s["artifacts"] = list(answer.get("artifact_ids") or [])
        _write(run_path(ex), r)


def run(execution):
    return _read(run_path(execution), None)


def output_of(execution, node):
    """The whole text of the run's last answered step of that node (a tracker write's from_step). -> str, or None."""
    for s in reversed((run(execution) or {}).get("steps") or []):
        if s.get("node") == node and isinstance(s.get("answer"), dict):
            a = s["answer"]
            return str(a.get("output") or a.get("said") or "")
    return None


def runs():
    d = ROOT / "runs"
    return [_read(p, {}) for p in sorted(d.glob("*.json"))] if d.is_dir() else []


# ---------- items ----------
def item_path(tracker, key):
    return ROOT / "items" / safe(tracker) / f"{safe(key)}.json"


def _item(tracker, key, run_name=""):
    it = _read(item_path(tracker, key), {"tracker": tracker, "key": key, "run": run_name, "runs": [], "wait": None,
                                         "woke": {}, "unread": []})
    it.setdefault("said", {})                        # an item kept before WFL-28 and WFL-33 gets their parts on its next change
    it.setdefault("reminded", {})
    if not it["run"]:                                # the run named after the item (<workflow>:<tracker>/<key>)
        from domain import trackers as TR
        t = TR.find(tracker)
        it["run"] = run_name or (TR.run_id(t, key) if t else "")
    return it


def item(tracker, key):
    return _read(item_path(tracker, key), None)


def _learn(it, execution):
    """The item's current run is the one this execution belongs to: a run its event started learns its execution from
    its first step that names the item; another execution is another run of the item (started by hand, or again)."""
    if not execution:
        return
    last = it["runs"][-1] if it["runs"] else None
    if last and not last.get("execution"):
        last["execution"] = str(execution)
    elif not last or last["execution"] != str(execution):
        it["runs"].append({"event": "", "at": _iso(), "execution": str(execution), "by": "a step"})
        it["unread"], it["said"], it["reminded"] = [], {}, {}   # the comments and reminders before this run were the last run's


def learn(req):
    """A step that names its item (a tracker write, a coding change for it) tells the register which run is the item's."""
    t, k = req.get("tracker"), req.get("key")
    if not (t and k and req.get("execution")):
        return
    with locked():
        it = _item(t, k)
        _learn(it, req["execution"])
        _write(item_path(t, k), it)


SOURCES = ("item", "pr", "any")                     # WFL-32: what a wait listens to: the item's comments, its pull request's, or both


def source(ref):
    """A comment's source by its ref: pr-comment:<pr>/<id> is the pull request's, comment:<tracker>/<key>/<id> the item's."""
    return "pr" if str(ref).startswith("pr-comment:") else "item"


def _of(on, refs):
    return [r for r in refs if on == "any" or source(r) == on]


def _reply(it, w, refs, ref=""):
    """The answer of a wait its comments answer: their source, refs and whole texts (here and in n8n at home; a
    customer deployment's n8n gets the summary, which names no text, WFL-22), and how often the wait timed out first."""
    said = [it["said"].pop(r) for r in refs if r in it["said"]]
    srcs = sorted({source(r) for r in refs})
    where = {("item",): "the item", ("pr",): "its pull request"}.get(tuple(srcs), "the item and its pull request")
    n = len(refs)
    return {"status": "done", "outcome": "reply", "source": srcs[0] if len(srcs) == 1 else "any", "comments": refs, "replies": said,
            "tracker": it["tracker"], "key": it["key"], "reminded": it["reminded"].pop(w.get("node") or "", 0),
            "summary": f"{n} new comment{'' if n == 1 else 's'} on {where}",
            "output": "\n\n".join(f"{s['author'] or 'someone'}{', ' + s['at'] if s['at'] else ''}:\n{s['text']}" for s in said),
            **({"ref": ref} if ref else {})}


def wait(rid, req, now=None):
    """wait_item: the run waits on its item until a comment from someone else of the wait's source arrives (outcome
    reply, with the new comments and their texts) or its time is up (outcome timeout, reminded: how often a wait of this
    node timed out before in this run). Registered once; comments of its source that came while the run was busy
    elsewhere answer it at once. -> the answer, or None while it waits."""
    now = now or _now()
    t, k, on = req["tracker"], req["key"], req.get("on") or "item"
    with locked():
        it = _item(t, k)
        got = it["woke"].pop(rid, None)
        if got is None:
            w = it.get("wait")
            if not w or w["rid"] != rid:
                _learn(it, req.get("execution"))
                hours = float(req.get("timeout_hours") or 0)
                w = it["wait"] = {"rid": rid, "since": now, "deadline": now + hours * 3600 if hours > 0 else 0,
                                  "execution": str(req.get("execution") or ""), "on": on, "node": str(req.get("node") or "")}
            mine = _of(on, it["unread"])
            if mine:
                it["unread"] = [c for c in it["unread"] if c not in mine]
                got = _reply(it, w, mine)
            elif w["deadline"] and now >= w["deadline"]:
                node = w.get("node") or ""
                n = it["reminded"].get(node, 0)
                it["reminded"][node] = n + 1
                got = {"status": "done", "outcome": "timeout", "source": on, "comments": [], "tracker": t, "key": k, "reminded": n,
                       "waited_hours": round((now - w["since"]) / 3600, 2), "summary": f"no answer in {round((now - w['since']) / 3600, 2):g} hours"}
        if got is not None:
            it["wait"] = None
        _write(item_path(t, k), it)
        return got


# ---------- the event ledger and routing ----------
def event_id(ev):
    t, k = split(ev)
    return hashlib.sha1(json.dumps([t, k, ev.get("ref", ""), sorted(ev.get("comments") or [])]).encode()).hexdigest()[:20]   # cap: id, the identity's hash names it


def split(ev):
    """(tracker, key) of an event: a tracker's names both; a pull request's names its item as <tracker>/<key>."""
    if ev.get("tracker"):
        return str(ev["tracker"]), str(ev["key"])
    t, _, k = str(ev.get("key") or "").partition("/")
    return t, k


def hand(events):
    """trackers.poll and forgework.poll_prs hand their events here before their cursors move."""
    if not events:
        return
    with locked():
        box = _read(ROOT / "outbox.json", [])
        box += [e for e in events if e not in box]
        _write(ROOT / "outbox.json", box)


def n8n_status(execution, run=subprocess.run):
    """n8n's state of an execution, from its own table in the stack's Postgres (the runner reads it as it reads the
    gateway's): new, running, waiting, success, error, crashed, canceled; "" when it cannot be read."""
    if not str(execution).isdigit():
        return ""
    try:
        p = run(["docker", "exec", "aistack-postgres-1", "psql", "-U", "n8n", "-d", "n8n", "-tAc",
                 f"select status from execution_entity where id = {int(execution)}"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (p.stdout or "").strip() if p.returncode == 0 else ""


def start(workflow, payload, post=None):
    """Starts the item's workflow through its webhook (POST <n8n>/webhook/item/<pack>/<name>). -> (why not or "", the
    run's n8n execution when the trigger answers with it: its Response Data {{ JSON.stringify({execution: $execution.id}) }},
    shown on n8n 2.44.7 on 10 Nov 2026; else "", learnt from the run's first step that names its item)."""
    if not WORKFLOW.fullmatch(str(workflow or "")):
        return f"the tracker names no workflow <pack>/<name> to start (it says {workflow!r})", ""
    import n8n_gen as G
    if not os.environ.get("N8N_HOOK_TOKEN"):         # SEC-27: n8n refuses a webhook call without the runner's header
        return "the runner has no N8N_HOOK_TOKEN for n8n's webhooks (make trust-keys, then restart the runner)", ""
    req = urllib.request.Request(f"{N8N}/webhook/item/{workflow}", data=json.dumps(payload, ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json", G.HOOK_HEADER: os.environ["N8N_HOOK_TOKEN"]}, method="POST")
    try:
        with (post or urllib.request.urlopen)(req, timeout=30) as r:
            if not 200 <= r.status < 300:
                return f"n8n answered {r.status}", ""
            try:
                said = json.loads(r.read() or b"{}")
            except (ValueError, AttributeError):
                said = {}
            ex = str(said.get("execution") or "") if isinstance(said, dict) else ""
            return "", ex if ex.isdigit() else ""
    except OSError as e:                             # n8n down, or the workflow not published (404): the event is kept
        return f"n8n did not start {workflow}: {e}", ""


def route(ev, cfg=None, post=None, status=None):
    """Places one event (see the module's text). -> seen | woke | started | recorded | kept: <why>."""
    from domain import trackers as TR
    cfg = cfg or TR.config()
    t, k = split(ev)
    eid = event_id(ev)
    comments = list(ev.get("comments") or [])
    tr = TR.find(t, cfg) or {}
    with locked():
        ledger = _read(ROOT / "events.json", {})
        if eid in ledger:
            return "seen"
        it = _item(t, k, ev.get("run") or (TR.run_id(tr, k) if tr else ""))
        did = None
        w = it.get("wait")
        it["said"].update({s["ref"]: s for s in ev.get("said") or [] if s.get("ref") in comments})
        mine = _of(w.get("on") or "item", comments) if w else []
        if mine:                                     # comments of the wait's source wake it; the other source's wait for theirs
            took = _of(w.get("on") or "item", it["unread"]) + mine
            it["woke"][w["rid"]] = _reply(it, w, took, ev.get("ref", ""))
            it["wait"], did = None, "woke"
            it["unread"] = [c for c in it["unread"] + comments if c not in took]
        elif not it["runs"] or (comments and tr.get("restart") == "on_comment" and ended(it, status)):
            it["runs"].append({"event": eid, "at": _iso(), "execution": "", "by": "an event"})
            unread, said, it["unread"], it["said"] = it["unread"], it["said"], [], {}   # the new run gets its comments with its start
            _write(item_path(t, k), it)               # marked first: an event never starts two runs
            why, ex = start(tr.get("workflow"), {"tracker": t, "key": k, "run": it["run"], "ref": ev.get("ref", ""), "comments": comments}, post)
            it["runs"][-1]["execution"] = ex
            if why:
                it["runs"].pop()
                it["unread"], it["said"] = unread, said
                _write(item_path(t, k), it)
                return f"kept: {why}"
            it["reminded"] = {}
            did = "started"
        else:
            it["unread"] += [c for c in comments if c not in it["unread"]]
            did = "recorded"
        _write(item_path(t, k), it)
        ledger[eid] = {"at": _iso(), "tracker": t, "key": k, "ref": ev.get("ref", ""), "did": did}
        if len(ledger) > EVENTS_KEPT:                # limit: drops, EVENTS_KEPT above
            for old in sorted(ledger, key=lambda x: ledger[x]["at"])[:len(ledger) - EVENTS_KEPT]:   # cap: rotate, the oldest identities go
                ledger.pop(old)
        _write(ROOT / "events.json", ledger)
        return did


def ended(it, status=None):
    """The item's last run is over: n8n says its execution finished. A run whose execution no step has named yet is
    taken as still going."""
    ex = it["runs"][-1].get("execution") if it["runs"] else ""
    return bool(ex) and (status or n8n_status)(ex) in ENDED


def drain(cfg=None, post=None, status=None):
    """Routes every event in the outbox; one n8n could not take stays for the next pass. -> {what happened: count}."""
    with locked():
        box = _read(ROOT / "outbox.json", [])
    said, kept = {}, []
    for ev in box:
        did = route(ev, cfg, post, status)
        said[did.split(":")[0]] = said.get(did.split(":")[0], 0) + 1
        if did.startswith("kept"):
            kept.append(ev)
            print(f"tracker-poll: {split(ev)}: {did}", file=sys.stderr)
    with locked():
        now = _read(ROOT / "outbox.json", [])
        _write(ROOT / "outbox.json", kept + [e for e in now if e not in box])
    return said


def due(cfg, now=None):
    """The poller runs on n8n's minute; it asks the trackers every poll_minutes of the deployment (5 by default)."""
    now = now or _now()
    st = _read(ROOT / "poller.json", {})
    return now - float(st.get("last") or 0) >= cfg["poll_minutes"] * 60 - 5   # limit: paces, poll_minutes of trackers.yaml (5 by default); 5 s slack for n8n's tick


def poll(cfg=None, forge=None, post=None, status=None, now=None):
    """One pass of the poller: the trackers' and the watched pull requests' events into the outbox, then routed."""
    from domain import forgework as FWK
    from domain import trackers as TR
    cfg = cfg or TR.config()
    if not cfg["trackers"]:
        return {"result": "no trackers in this deployment"}
    if not due(cfg, now):
        return {"result": f"not due (every {cfg['poll_minutes']:g} minutes)"}
    TR.poll(cfg, hand=hand)
    problems = TR.problems(cfg)
    if forge is None:
        import forge as F
        forge = F.FORGE
    FWK.poll_prs(forge, hand=hand)
    said = drain(cfg, post, status)
    with locked():
        _write(ROOT / "poller.json", {"last": now or _now(), "at": _iso(now)})
    words = ", ".join(f"{n} {k}" for k, n in sorted(said.items())) or "no new events"
    return {"result": words + (f"; {len(problems)} trackers refused: " + "; ".join(problems) if problems else ""), "said": said,
            "problems": problems}


def main(argv):
    if argv[1:] == ["poll"]:
        res = poll()
        CREW_OUT.mkdir(parents=True, exist_ok=True)
        _write(CREW_OUT / "tracker-poll.json", {"result": res["result"], "last": _now()})
        print(res["result"])
        return 1 if res.get("problems") else 0
    if len(argv) == 4 and argv[1] == "export":
        from domain import record as RC
        print(RC.export_run(argv[2], argv[3]))
        return 0
    if len(argv) == 1:
        items = sorted(ROOT.glob("items/*/*.json"))
        print(json.dumps({"items": [_read(p, {}) for p in items], "runs": [{"execution": r.get("execution"), "steps": len(r.get("steps") or [])}
                                                                            for r in runs()]}, indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
