"""WFL-05: the step service's runner side. n8n decides when work starts and in what order; the stack does the work.

An n8n workflow posts a step to Mission Control's step service (port 8099, reachable from n8n's network only), which
drops it here as /srv/ai/missions/flows/pending/<id>.json and answers at once. This worker runs it the way the
Conductor runs a plan's step, through CD.run_step on a row of its own: the same adapters, routing, headroom, slots, two
attempts, budget, trace and record (TSK-23). A crew job runs as its own unit, as "Run now" starts it. When the step has
settled, the result goes to done/<id>.json and to the waiting n8n execution's resume URL. A request stays pending until
n8n has its answer, so after a restart of the runner the step is looked at again (a finished row answers at once) and
the answer is delivered then.

A task on a schedule (a briefing, a price watch, a mission's task) runs from its own n8n workflow, the one scheduler
(WFL-09): one run per request, a plan task's as one occurrence of its plan (CD.start), a mission's as one run of the
mission, answered when that run has finished. A task that is not waiting for a run (running, cancelled) is not started.
The runner makes a task's workflow when the task gets its schedule and switches it off when the task is over
(ops/n8n_jobs.py reconcile, every minute in this worker).

A question (WFL-07, ASK-19) is an Ask of the store (ops/asks.py): the Ask block's type, question, choices, words allowed,
default, deadline, role, gate and sensitivity; it waits in Needs you until a person who holds its role answers (a chip,
or words the interpreter reads), dismisses it, or its deadline applies its default; the step's answer is {status,
outcome, values, words, person, role, via, interpreted_as}, so the workflow branches with n8n's If and Switch. A
tracker step's transition to a status a pack gates waits for that gate's Ask (ASK-20).

Every step is kept in the run register (ops/runreg.py, WFL-23): its request, its whole answer, its files and its
times, by its n8n run. In a customer-class deployment n8n gets a lean answer (WFL-22: status, ids and a short summary);
the whole text stays in the register and the task's record. The deployment may relax it (data.yaml n8n_answers: full).

The other blocks of the palette (WFL-06), each through the stack's own code:
    build     a coding change: the Conductor's build step (run_build, a builder assignment in the sandbox), waited for
              through its checks and the owner's review; the answer names the build, its state, branch, pull request
              and checks
    recall    a search of the stack's memory (the memory tool's search, MEM-28); the answer is its hits
    remember  a note through the memory tool's write gate (MEM-28, MEM-35): it enters memory only after its check
    command   a job kind at a place (ops/domain/places.py: wsl, wsl-host, windows), only when the owner approved that
              kind there by its fingerprint (Needs you); submitted once per request, waited for. A file parameter's
              value may be an artifact id (artifact:<sha>, an item's attachment or an earlier command's file): the file
              goes into the request's own folder under its name, and the worker checks it as any file of a request
    plan      an improvised plan: its steps are rows of one task, run in waves through the same path as an agent step;
              a step waits for the steps it names in "after", and the answer carries every step's output
    An agent step that names a tracker item (tracker and key, from_item: true, WFL-25) reads it: the item's title,
    text and comments as its tracker holds them when the step starts (trackers.item_text) follow its brief, the stack's
    own comments marked as its own; read by the step service, so the text never passes through n8n. An item that cannot
    be read fails the step with the reason. from_item: false names the item without reading it.
    item      reads the item through its tracker's adapter (WFL-28): title, text, status, labels, its comments (author,
              time, text, the stack's own marked) and its attachments; attach_to: <place> also fetches its attachments
              (all, or those named in attachments) into the artifact store, recorded with the deployment's data class,
              and answers their artifact ids, which a command at that place takes as the value of a file parameter.
              At most ATTACH_COUNT files of at most ATTACH_MB each. In a customer deployment n8n gets the ids and a
              summary that names no text
    wait_item the run waits on its tracker item (WFL-20): the answer is done with outcome reply (and the new comments
              from others, with their texts) or outcome timeout after timeout_hours (0: no timeout); a timeout is no
              failure, so the workflow branches to a reminder and waits again, and reminded says how often this wait
              timed out before (WFL-33). on: item (the default), pr or any says whose comments answer it (WFL-32). The
              item's events reach it through ops/runreg.py
    tracker   one write to the item through trackers.write (WFL-21): comment, summary, attach, link, transition or
              label, in shadow until the owner lets its kind go live; the answer names the shadow or live reference.
              from_step adds an earlier step's whole answer from the run register, so a customer deployment's n8n,
              which holds only summaries, never carries the text it writes
    A coding change for a tracker item (build with item, base and target, GEN-26) starts its branch at the base ref or
    tag and, in a deployment with FORGE_PUSH, goes out as a draft pull request into the target branch; never merged.

Request: {"kind": one of KINDS, "agent": <card id>, "brief": <text>, "title": <text>, "job": <crew id>,
          "task": <plan task id>, "question": <text>, "why": <text>, "answers": [<label>, ...], "message": <text>,
          "repo": <repository>, "query": <words>, "scope": <collection>, "note": lesson|fact|failure|skill,
          "text": <note>, "evidence": <where it comes from>, "place": wsl|wsl-host|windows, "command": <job kind>,
          "values": {<parameter>: <value>}, "steps": [{"agent", "brief", "title", "after": [<step number>, ...]}, ...],
          "tracker": <tracker>, "key": <item key>, "timeout_hours": <hours>, "on": item|pr|any, "write": <kind of write>,
          "body": <text>, "from_step": <an earlier node's name>, "from_item": <bool>, "attach_to": <place>,
          "attachments": [<name>, ...],
          "item": <tracker>/<key>, "base": <ref or tag>, "target": <branch>, "forge": <the repository's address there>,
          "role": <role>, "workflow": <n8n workflow id>, "workflow_name": <its name>, "node": <the node's name>,
          "execution": <n8n execution id>, "resume_url": <$execution.resumeUrl>}

    python3 ops/flows.py             what is pending, running and done
"""
import json
import re
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import statefile as SF
import textcap as TC
from textcap import tail

ROOT = Path("/srv/ai/missions/flows")
PENDING, DONE = ROOT / "pending", ROOT / "done"
N8N = "http://127.0.0.1:5678"                        # n8n's port on this machine (compose/core.yaml); the runner is on the host
RESUME_PATH = re.compile(r"^/webhook-waiting/[A-Za-z0-9_-]{1,64}(/[A-Za-z0-9_-]{1,64})?$")
RESUME_QUERY = re.compile(r"^(signature=[0-9a-f]{16,128})?$")   # n8n 2.x signs its resume URLs; nothing else may ride along
KINDS = ("agent", "crew", "task", "ask", "notify", "build", "recall", "remember", "command", "plan", "wait_item", "tracker", "item")
NOTE_MAX = 2000                                      # limit: refuses, a message from a workflow is a note, not a report
ASKS = ROOT / "asks"
JOBS = ROOT / "jobs"                                 # a command's job at its place, per request: submitted once, also after a restart
BRIEF_MAX = 20000                                    # limit: refuses, a step's brief is instructions, not a document
QUERY_MAX = 500                                      # limit: refuses, a memory search is words, as the memory tool's search takes them
MEMO_MAX = 2000                                      # limit: refuses, a note to memory is kept whole or not at all (the gate reads it whole, as the memory tool's note)
EVIDENCE_MAX = 500                                   # limit: refuses, the evidence names where a note comes from, as the memory tool's
NOTES = ("lesson", "fact", "failure", "skill")       # what a workflow may write to memory; the owner's facts are the owner's to give
COMMAND = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}")   # a job kind's name, as a pack names it (<pack>.<kind>)
HIT_CHARS = 400                                      # of one memory hit in the answer; memory open gives the entry whole
WAIT_AGAIN_S = 30                                    # limit: paces, a step that waits (its work elsewhere, no headroom) is looked at again after 30 s
POLL_S = 2                                           # limit: paces, a command's job is looked at every 2 s, as places.run_job does
DELIVER_EVERY_S = 60                                 # limit: paces, an undelivered answer is sent again every minute
DELIVER_FOR_S = 86400                                # limit: stops, after a day without n8n taking it the answer stays in done/ and the owner is told
SCAN_S = 2
SETTLED = ("done", "skipped", "failed", "cancelled")
BUILDS = ROOT / "builds"                             # a coding change for an item, per request: its build, branch and pull request
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")   # a tracker's or a role's name
ITEM_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.#-]{0,99}")   # an item's key on its tracker (DEMO-12, 42)
GIT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}")   # a branch or a tag
STEP_NAME = re.compile(r"[^\x00-\x1f]{1,128}")       # a node's name in its workflow, as n8n shows it
SUMMARY_CHARS = 300                                  # of a step's text in a lean answer; the whole is in the run register and the task's record
ATTACH_COUNT = 10                                    # limit: refuses, an item step fetches at most 10 attachments; more are named one by one in attachments
ATTACH_MB = 50                                       # limit: refuses, an attachment over 50 MB is not fetched (the place's worker copies back as much, localworker ARTIFACTS_MB)
ARTIFACT = re.compile(r"artifact:[0-9a-f]{64}")

M = None                                             # ops/missions.py, set by start()
_busy = set()
_lock = threading.Lock()


def _brief(req):
    brief = req.get("brief")
    if not isinstance(brief, str) or not brief.strip():
        return "the step needs a brief"
    if len(brief) > BRIEF_MAX:                       # limit: refuses, BRIEF_MAX above
        return f"the brief is {len(brief):,} characters; the limit is {BRIEF_MAX:,}"
    return ""


def validate(req, cards, crew, repos=None):
    """-> the problem with a request in words, or "" (SEC-11: the runner checks every request it acts on). repos: the
    repositories the builder may change (asked of ops/builds.py when None)."""
    if not isinstance(req, dict):
        return "the request is not an object"
    kind = req.get("kind")
    if kind not in KINDS:
        return f"kind must be one of {', '.join(KINDS)}"
    if kind == "agent":
        if req.get("agent") not in cards:
            return f"no agent {req.get('agent')!r}"
        if _brief(req):
            return _brief(req).replace("the step", "an agent step")
    if kind == "crew" and (req.get("job") not in crew or not crew[req["job"]].get("unit")):
        return f"no crew job {req.get('job')!r}"
    if kind == "task" and not isinstance(req.get("task"), int):
        return "a task step names its plan task by number"
    if kind == "notify":
        m = req.get("message")
        if not isinstance(m, str) or not m.strip() or len(m) > NOTE_MAX:   # limit: refuses, NOTE_MAX above
            return f"a message needs its text, at most {NOTE_MAX:,} characters"
    if kind == "ask":
        why = ask_problem(req)
        if why:
            return why
    if kind == "build":
        if _brief(req):
            return _brief(req).replace("the step", "a coding change")
        if repos is None:
            import builds as B
            repos = B.repos()
        if req.get("repo") not in repos:
            return f"no repository {req.get('repo')!r} the builder may change (there: {', '.join(repos) or 'none'})"
    if kind == "recall":
        q = req.get("query")
        if not isinstance(q, str) or not q.strip() or len(q) > QUERY_MAX:   # limit: refuses, QUERY_MAX above
            return f"a search needs its words, at most {QUERY_MAX} characters"
        if not isinstance(req.get("scope") or "", str):
            return "a search's scope is a collection's name"
    if kind == "remember":
        t, ev = req.get("text"), req.get("evidence") or ""
        if req.get("note") not in NOTES:
            return f"a note is one of {', '.join(NOTES)}"
        if not isinstance(t, str) or not t.strip() or len(t) > MEMO_MAX:   # limit: refuses, MEMO_MAX above
            return f"a note needs its text, at most {MEMO_MAX:,} characters"
        if not isinstance(ev, str) or len(ev) > EVIDENCE_MAX:              # limit: refuses, EVIDENCE_MAX above
            return f"the evidence is at most {EVIDENCE_MAX} characters"
        if req.get("agent") and req["agent"] not in cards:
            return f"no agent {req.get('agent')!r}"
    if kind == "command":
        from domain import places as PL
        if req.get("place") not in PL.PLACES:
            return f"place must be one of {', '.join(PL.PLACES)}"
        if not isinstance(req.get("command"), str) or not COMMAND.fullmatch(req["command"]):
            return "a command is a job kind's name"
        if not isinstance(req.get("values") if req.get("values") is not None else {}, dict):
            return "a command's values are an object of its parameters"
    if kind == "plan":
        why = plan_problem(req.get("steps"), cards)
        if why:
            return why
    why = item_problem(req)
    if why:
        return why
    if req.get("resume_url") and not resume_target(req["resume_url"]):
        return "resume_url must be n8n's own resume URL"
    return ""


def _tracker_named(name):
    from domain import trackers as TR
    return TR.find(name) is not None


def item_problem(req):
    """-> what is wrong with the item fields of a request (wait_item, tracker, an agent step that reads its item, a build
    for an item, a question's role), or ""."""
    kind = req.get("kind")
    if kind in ("wait_item", "tracker", "item") or (kind == "agent" and req.get("tracker") not in (None, "")):
        if not isinstance(req.get("tracker"), str) or not NAME.fullmatch(req["tracker"]) or not _tracker_named(req["tracker"]):
            return f"no tracker {req.get('tracker')!r} in this deployment's trackers.yaml"
        if not isinstance(req.get("key"), str) or not ITEM_KEY.fullmatch(req["key"]):
            return "an item step names its item's key"
    if kind == "agent" and req.get("from_item") not in (None, True, False):
        return "from_item is true or false"
    if kind == "wait_item":
        import runreg as RR
        h = req.get("timeout_hours", 0)
        if isinstance(h, bool) or not isinstance(h, (int, float)) or h < 0:
            return "timeout_hours is a number of hours, 0 for no timeout"
        if req.get("on", "item") not in RR.SOURCES:
            return f"a wait is on {', '.join(RR.SOURCES)}: the item's comments, its pull request's, or both"
    if kind == "item":
        from domain import places as PL
        if req.get("attach_to") not in (None, "") and req["attach_to"] not in PL.PLACES:
            return f"attach_to is a place, one of {', '.join(PL.PLACES)}"
        names = req.get("attachments") or []
        if not isinstance(names, list) or not all(isinstance(n, str) and n.strip() for n in names):
            return "attachments are the names of the item's attachments"
        if len(names) > ATTACH_COUNT:                                   # limit: refuses, ATTACH_COUNT above
            return f"an item step fetches at most {ATTACH_COUNT} attachments"
    if kind == "tracker":
        from domain import trackers as TR
        if req.get("write") not in TR.KINDS:
            return f"a tracker write is one of {', '.join(TR.KINDS)}"
        b, src = req.get("body", ""), req.get("from_step")
        if src is not None and (not isinstance(src, str) or not STEP_NAME.fullmatch(src)):
            return "from_step names an earlier step of the run, as the workflow names its node"
        if not isinstance(b, str) or not (b.strip() or src) or len(b) > TR.BODY_CHARS:   # limit: refuses, one write's text as trackers.write keeps it
            return f"a tracker write needs its text (or a step to take it from), at most {TR.BODY_CHARS:,} characters"
    if kind == "build" and any(req.get(k) for k in ("item", "base", "target")):
        t, _, k = str(req.get("item") or "").partition("/")
        if not NAME.fullmatch(t) or not ITEM_KEY.fullmatch(k) or not _tracker_named(t):
            return "a coding change for an item names it as <tracker>/<key>, of a tracker in trackers.yaml"
        for f in ("base", "target"):
            v = req.get(f)
            if not isinstance(v, str) or not GIT_REF.fullmatch(v) or ".." in v:
                return f"a coding change for an item names its {f} ({'the ref or tag it starts at' if f == 'base' else 'the branch its pull request goes into'})"
        if req.get("forge") is not None and not isinstance(req["forge"], str):
            return "forge is the repository's address on the forge"
    if kind == "ask" and req.get("role") and (not isinstance(req["role"], str) or not NAME.fullmatch(req["role"])):
        return "a question's role is a name of the deployment's roles"
    return ""


def plan_problem(steps, cards):
    """-> what is wrong with a plan's steps, or "": each names an agent and a brief, waits only for other steps, and
    the plan has no cycle and at most the Conductor's number of steps."""
    import conductor as CD
    if not isinstance(steps, list) or not 1 <= len(steps) <= CD.MAX_STEPS:   # limit: refuses, a plan holds at most the Conductor's MAX_STEPS
        return f"a plan has 1 to {CD.MAX_STEPS} steps"
    for i, s in enumerate(steps, 1):
        if not isinstance(s, dict):
            return f"step {i} is not an object"
        if s.get("agent") not in cards:
            return f"step {i}: no agent {s.get('agent')!r}"
        if _brief(s):
            return f"step {i}: {_brief(s).replace('the step ', 'it ')}"
        after = s.get("after") or []
        if not isinstance(after, list) or not all(isinstance(a, int) and 1 <= a <= len(steps) and a != i for a in after):
            return f"step {i} waits for a step that is not another step of the plan"
    try:
        waves([s.get("after") or [] for s in steps])
    except ValueError as e:
        return str(e)
    return ""


def waves(afters):
    """afters: each step's steps it waits for (1-based) -> the steps in waves, each wave the steps whose steps before
    are all in earlier waves; ValueError for a cycle."""
    placed, out = set(), []
    while len(placed) < len(afters):
        wave = [i for i, a in enumerate(afters, 1) if i not in placed and set(a) <= placed]
        if not wave:
            raise ValueError("the plan has a cycle: " + ", ".join(f"step {i}" for i in range(1, len(afters) + 1) if i not in placed))
        out.append(wave)
        placed |= set(wave)
    return out


def resume_target(url):
    """n8n's resume URL, re-aimed at n8n's port on this machine: only its path is used, so a request can never make the
    runner call anywhere else. -> the URL, or "" when it is not a resume URL."""
    try:
        p = urllib.parse.urlsplit(str(url))
    except ValueError:
        return ""
    if p.scheme not in ("http", "https") or not RESUME_PATH.match(p.path) or not RESUME_QUERY.match(p.query) or p.fragment:
        return ""
    return N8N + p.path + (f"?{p.query}" if p.query else "")


def harness_of(card):
    return card["step_kind"] if card.get("step_kind") else card.get("harness") or "hermes"


def row_of(card, agent, brief, title="", after=(), harness=None):
    """One step row: its title is the step as the agent reads it ("Your step: ..."), its why the card's own prompt and
    the brief."""
    return {"agent": agent, "title": f"{title}: {brief}" if title else brief, "after": list(after), "harness": harness or harness_of(card),
            "model": card.get("model") or "", "why": (f"As the agent {agent}: {card['prompt']}\n\n" if card.get("prompt") else "") + brief}


def open_task(c, rid, req, rows, text, spec=None):
    """The task and its step rows of a request, made once (keyed by the request id). -> the task id."""
    import conductor as CD
    c.execute("create table if not exists flow_steps (id text primary key, task integer, created text)")
    r = c.execute("select task from flow_steps where id=?", (rid,)).fetchone()
    if r:
        return r["task"]
    now = CD.now()
    title = TC.cut(req.get("title") or text.strip().splitlines()[0], 120)   # cap: preview, the whole brief is the task's text
    ref = f"n8n:{req.get('workflow', '')}/{req.get('execution', '')}"
    cur = c.execute("insert into tasks (text, title, goal, kind, door, ref, done, effort, autonomy, rhythm, spec, questions, answers, status, "
                    "source, created, updated) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (text, title, title, "workflow", "workflow", ref, "[]", "standard", "auto", json.dumps({"type": "once"}),
                     json.dumps({"workflow": req.get("workflow"), "execution": req.get("execution"), **(spec or {})}), "[]", "[]",
                     "running", "crew:n8n", now, now))
    tid = cur.lastrowid
    for i, s in enumerate(rows, 1):
        c.execute("insert into task_steps (task, occ, idx, title, item, agent, harness, model, after, why, status, attempts) "
                  "values (?,?,?,?,?,?,?,?,?,?,?,0)", (tid, 1, i, s["title"], "", s["agent"], s["harness"], s["model"],
                                                      json.dumps(s["after"]), s["why"], "pending"))
    c.execute("insert or replace into task_occ (task, occ, trigger, started, status) values (?,?,?,?,?)", (tid, 1, "n8n", now, "running"))
    c.execute("insert into flow_steps (id, task, created) values (?,?,?)", (rid, tid, now))
    c.commit()
    return tid


def opened(c, rid):
    """Whether the request's task was made already (a step looked at again after a restart)."""
    c.execute("create table if not exists flow_steps (id text primary key, task integer, created text)")
    return c.execute("select task from flow_steps where id=?", (rid,)).fetchone() is not None


def with_item(req):
    """WFL-25: an agent step that names its item (from_item, true unless it says false) gets the item's title, text and
    comments after its brief, read once by the step service when its task is made, so the text never passes through
    n8n. -> the request to run, or an answer when the item cannot be read."""
    import runreg as RR
    from domain import trackers as TR
    RR.learn(req)
    try:
        said = TR.item_text(req["tracker"], str(req["key"]))
    except Exception as e:                           # the tracker away or the item gone: the step fails with the reason
        return None, {"status": "failed", "error": f"the item {req['tracker']}/{req['key']} could not be read: {type(e).__name__}: {e}"}
    return {**req, "brief": f"{req['brief']}\n\n{said}"}, None


def data_class():
    """The class files from outside get in the artifact store: the deployment's (the data guard's data.yaml)."""
    try:
        import dataguard as DG
    except SystemExit:                               # no data.yaml: home's rules
        return "personal"
    return "customer" if DG.customer() else str(DG.DATA.get("class") or "personal")


def item_read(rid, req, ad=None):
    """WFL-28: the item through its tracker's adapter. With attach_to, its attachments (all, or those named) are
    fetched into the artifact store with the deployment's data class and answered by artifact id, for a command at
    that place; ATTACH_COUNT and ATTACH_MB refuse more. -> the answer."""
    import runreg as RR
    from domain import artifacts as AR
    from domain import trackers as TR
    RR.learn(req)
    t, k = req["tracker"], str(req["key"])
    try:
        it = TR.read_item(t, k, ad=ad)
    except Exception as e:                           # the tracker away or the item gone: the step fails with the reason
        return {"status": "failed", "error": f"the item {t}/{k} could not be read: {type(e).__name__}: {e}"}
    out = {"status": "done", "tracker": t, "key": k, "title": it["title"], "body": it["body"], "item_status": it["status"], "labels": it["labels"],
           "thread": it["comments"], "attachments": it["attachments"], "output": TR.as_text(it),
           "summary": f"{len(it['comments'])} comments, {len(it['attachments'])} attachments"}
    if not req.get("attach_to"):
        return out
    want = req.get("attachments") or [a["name"] for a in it["attachments"]]
    missing = [n for n in want if n not in {a["name"] for a in it["attachments"]}]
    if missing:
        return {**out, "status": "failed", "error": f"the item has no attachment {missing[0]!r}"}
    files = [a for a in it["attachments"] if a["name"] in want]
    if len(files) > ATTACH_COUNT:                    # limit: refuses, ATTACH_COUNT above
        return {**out, "status": "refused", "error": f"the item has {len(files)} attachments; name at most {ATTACH_COUNT} in attachments"}
    big = next((a for a in files if a["size"] > ATTACH_MB * 1024 * 1024), None)   # limit: refuses, ATTACH_MB above
    if big:
        return {**out, "status": "refused", "error": f"{big['name']} is {big['size'] // (1024 * 1024)} MB; an attachment is fetched up to {ATTACH_MB} MB"}
    import tempfile
    ids, cls = [], data_class()
    with tempfile.TemporaryDirectory() as d:
        for a in files:
            p = Path(d) / (re.sub(r"[^A-Za-z0-9._-]", "_", Path(a["name"]).name).lstrip("._-") or "attachment")
            try:
                p.write_bytes(TR.fetch(t, k, a, ad=ad))
            except Exception as e:                   # the step fails with the reason; a retry fetches again
                return {**out, "status": "failed", "error": f"{a['name']} could not be fetched: {type(e).__name__}: {e}"}
            ids.append(AR.put(p, task=f"{t}/{k}", step=rid, run=str(req.get("execution") or ""), data_class=cls)["id"])
    return {**out, "attach_to": req["attach_to"], "artifact_ids": ids, "data_class": cls}


def job_files(values, spec):
    """A command's values whose file parameters name an artifact (artifact:<sha>): each file goes into the request's
    folder under its own name, the value becomes that name. -> (values, {name: bytes}) or raises ValueError."""
    from domain import artifacts as AR
    params = (spec or {}).get("params") or {}
    out, files = dict(values), {}
    for name, v in values.items():
        if not (isinstance(v, str) and ARTIFACT.fullmatch(v) and (params.get(name) or {}).get("type") == "file"):
            continue
        p = AR.path_of(v)
        if p is None:
            raise ValueError(f"{name}: no saved file {v}")
        recs = AR.records(v)
        fname = re.sub(r"[^A-Za-z0-9._-]", "_", recs[-1]["name"] if recs else name).lstrip("._-")[:100] or name   # cap: id, a worker's file name
        files[fname], out[name] = p.read_bytes(), fname
    return out, files


def open_step(c, rid, req, cards):
    """The task and the one step row of an agent step. -> (task id, step row)."""
    import conductor as CD
    tid = open_task(c, rid, req, [row_of(cards[req["agent"]], req["agent"], req["brief"], req.get("title") or "")], req["brief"])
    return tid, CD.steps(c, tid, 1)[0]


def settle(c, task, idx=1, stop=None, sleep=time.sleep):
    """Runs one step of the task until it has settled, as the Conductor's tick would: headroom, one of its slots, two
    attempts, a step whose work runs elsewhere looked at again. -> the row (unsettled when the runner is stopping)."""
    import conductor as CD
    import tasks as TK
    agents = CD.cards()

    def row():
        return next(x for x in CD.steps(c, task, 1) if x["idx"] == idx)
    for _ in range(100000):                          # limit: stops, a step looked at this often has hung; it fails
        s = row()
        if s["status"] in SETTLED:
            return s
        if stop is not None and stop.is_set():
            return s
        rest = CD.resting.get(s["id"], 0) - time.time()
        if rest > 0 or (s["status"] == "waiting" and s["harness"] not in CD.WAITS):
            sleep(max(rest, WAIT_AGAIN_S))
            continue
        if s["attempts"] >= CD.ATTEMPTS and s["status"] == "pending":
            CD.put(c, s["id"], status="failed", error=s["error"] or "two attempts failed")
            continue
        looks = s["status"] == "waiting"            # looking at work elsewhere takes no slot (TSK-08)
        if not looks:
            why = CD.headroom(s)
            if why:
                if s["waiting_for"] != why:
                    CD.put(c, s["id"], waiting_for=why)
                sleep(WAIT_AGAIN_S)
                continue
            if not CD.slots.acquire(blocking=False):  # as many steps at once as the Conductor runs (SLOTS), its own and n8n's
                sleep(WAIT_AGAIN_S)
                continue
        try:
            if not looks:                           # claimed, then started (an attempt); a look at waiting work is no attempt
                CD.put(c, s["id"], status="running")
                s = {**s, "status": "starting"}
            CD.run_step(c, TK.row(c, task), s, CD.steps(c, task, 1), agents)
        finally:
            if not looks:
                CD.slots.release()
        if row()["status"] == "waiting":
            sleep(WAIT_AGAIN_S)
    s = row()
    CD.put(c, s["id"], status="failed", error="the step did not settle")
    return row()


def drive(c, task, stop=None, sleep=time.sleep):
    """The task's one step, settled. -> its row."""
    return settle(c, task, 1, stop=stop, sleep=sleep)


def close(c, task, ok):
    import conductor as CD
    c.execute("update tasks set status=?, updated=? where id=?", ("done" if ok else "failed", CD.now(), task))
    c.execute("update task_occ set status=?, ended=? where task=? and occ=1", ("done" if ok else "failed", CD.now(), task))
    c.commit()


COVERED = "already running: this run is covered by the one in progress"


def run_crew(job, by_id, run=subprocess.run):
    """A crew job as "Run now" starts it, waited for; its own result file says how it went. A job whose unit is still
    running answers at once that this run is covered by that one: never two at once, as its timer kept it, and no
    n8n runs piling up behind a job that outlasts its schedule's spacing."""
    ag = by_id[job]
    q = run(["systemctl", "--user", "is-active", f"{ag['unit']}.service"], capture_output=True, text=True)
    if (q.stdout or "").strip() in ("active", "activating", "reloading"):
        return {"status": "done", "output": COVERED, "crew": {}}
    p = run(["systemctl", "--user", "start", "--wait", f"{ag['unit']}.service"], capture_output=True, text=True)
    res = Path(f"/srv/ai/missions/crew/{job}.json")
    try:
        last = json.loads(res.read_text())
    except (OSError, ValueError):
        last = {}
    return {"status": "done" if p.returncode == 0 else "failed", "output": last.get("result") or last.get("summary") or "",
            "error": tail((p.stderr or "").strip(), 2000) if p.returncode else "", "crew": last}   # cap: store, an error's tail in the answer; the journal has it all


WAITING = ("scheduled", "done", "failed")            # a task that may start a run (as Run again on its page)


def run_task(c, rid, tid, stop=None, sleep=time.sleep):
    """One run of a task, started once per request (kept in flow_steps), waited for until it has finished: an occurrence
    of a plan task, or a run of the mission that does the task. -> the answer, or None when the runner is stopping (the
    request is looked at again after its restart)."""
    import conductor as CD
    import tasks as TK
    c.execute("create table if not exists flow_steps (id text primary key, task integer, created text)")
    cols = [r[1] for r in c.execute("pragma table_info(flow_steps)")]
    for col in ("occ", "run"):
        if col not in cols:
            c.execute(f"alter table flow_steps add column {col} integer")
    try:
        t = TK.row(c, tid)
    except ValueError:
        t = None
    if not t or t["door"] not in ("plan", "mission"):
        return {"status": "refused", "error": f"no plan task #{tid}"}
    r = c.execute("select occ, run from flow_steps where id=?", (rid,)).fetchone()
    if t["door"] == "mission":
        return run_mission(c, rid, t, r["run"] if r else None, stop=stop, sleep=sleep)
    if r and r["occ"]:
        occ = r["occ"]
    else:
        if t["status"] not in WAITING:
            return {"status": "refused", "error": f"task #{tid} is {t['status']}, not waiting for a run"}
        CD.start(c, t, trigger="n8n")
        TK.put(c, tid, status="running")
        occ = CD.occ_of(c, tid)
        c.execute("insert or replace into flow_steps (id, task, created, occ) values (?,?,?,?)", (rid, tid, CD.now(), occ))
        c.commit()
        CD.M.event("task", "", f"Task #{tid} run {occ} started by n8n: {t['title']}", title="Tasks")
    for _ in range(100000):                          # limit: stops, an occurrence looked at this often has hung
        o = c.execute("select status, result, verdict from task_occ where task=? and occ=?", (tid, occ)).fetchone()
        if o and o["status"] not in ("running", None):
            return {"status": "done" if o["status"] in ("done", "ok") else o["status"], "task": tid, "occ": occ,
                    "output": o["result"] or "", "verdict": o["verdict"] or ""}
        if stop is not None and stop.is_set():
            return None
        sleep(WAIT_AGAIN_S)
    return {"status": "failed", "task": tid, "occ": occ, "error": "the occurrence did not finish"}


def run_mission(c, rid, t, run_id=None, stop=None, sleep=time.sleep):
    """One run of the mission that does a task (its door), queued as the mission's own runs are and waited for. A run
    already queued or running for it is the one waited for, never a second. -> the answer, or None when stopping."""
    if not run_id:
        if t["status"] != "scheduled":
            return {"status": "refused", "error": f"task #{t['id']} is {t['status']}, not waiting for a run"}
        M.enqueue(c, t["ref"], "n8n")
        got = c.execute("select max(id) from runs where slug=? and status in ('queued', 'running', 'waiting')", (t["ref"],)).fetchone()
        if not got or not got[0]:
            return {"status": "refused", "error": f"the mission {t['ref']} took no run"}
        run_id = got[0]
        c.execute("insert or replace into flow_steps (id, task, created, run) values (?,?,?,?)", (rid, t["id"], time.strftime("%Y-%m-%dT%H:%M:%S"), run_id))
        c.commit()
        M.event("task", t["ref"], f"Task #{t['id']}: its mission's run started by n8n: {t['title']}", title="Tasks")
    for _ in range(100000):                          # limit: stops, a run looked at this often has hung
        o = c.execute("select status, summary from runs where id=?", (run_id,)).fetchone()
        if not o or o["status"] not in ("queued", "running", "waiting"):
            st = o["status"] if o else "failed"
            return {"status": "done" if st == "ok" else st, "task": t["id"], "run": run_id, "output": (o["summary"] if o else "") or ""}
        if stop is not None and stop.is_set():
            return None
        sleep(WAIT_AGAIN_S)
    return {"status": "failed", "task": t["id"], "run": run_id, "error": "the mission's run did not finish"}


def run_build(c, rid, req, cards, stop=None, sleep=time.sleep):
    """A coding change: one build step on the task's repository, as the Conductor runs it (run_build: a builder
    assignment, its checks, the owner's review). -> the answer, or None when the runner is stopping."""
    import conductor as CD
    card = cards.get(CD.BUILDER) or {}
    tid = open_task(c, rid, req, [row_of(card, CD.BUILDER, req["brief"], req.get("title") or "", harness="build")], req["brief"],
                    spec={"repo": req["repo"]})
    s = settle(c, tid, 1, stop=stop, sleep=sleep)
    if s["status"] not in SETTLED:
        return None
    close(c, tid, s["status"] in CD.FINISHED)
    r = c.execute("select ref from step_refs where kind='build' and task=? order by cast(ref as integer) desc", (tid,)).fetchone()
    b = c.execute("select * from builds where id=?", (int(r["ref"]),)).fetchone() if r else None
    return {**answer_of(tid, s), "build": int(r["ref"]) if r else None, "state": b["status"] if b else "",
            "branch": (b["branch"] or "") if b else "", "pr": (b["pr"] or "") if b else "", "ci": (b["ci"] or "") if b else "",
            "checks": tail(b["checks"] or "", 4000, "the build keeps the whole log") if b else ""}   # cap: preview, the checks' end; the build's page has them all


BUILD_FAILED = ("failed", "rejected", "rolled_back", "reverted")


def item_build(c, rid, req, B=None, forge=None, values=None, stop=None, sleep=time.sleep):
    """GEN-26: a coding change for a tracker item. Its branch ai/<item>-<slug> starts at the base ref or tag (pushed to
    the build's own origin), the builder works on it as a build onto that branch (as a change's step does), and in a
    deployment with FORGE_PUSH the change is pushed and opened as a draft pull request into the target branch, directly
    (DEC-54); its reviewers' comments reach the item's run through the run register (ops/runreg.py). Without FORGE_PUSH
    the build waits in the app for the owner, as today. The stack never merges. -> the answer, or None when stopping."""
    import runreg as RR
    from domain import forgework as FWK
    from domain import trackers as TR
    if B is None:
        import builds as B
    if forge is None:
        import forge as F
        forge = F.FORGE
    values = values if values is not None else B.DEPLOY.VALUES
    tracker, key = req["item"].split("/", 1)
    title = req.get("title") or req["brief"].strip().splitlines()[0]
    BUILDS.mkdir(parents=True, exist_ok=True)
    mine = BUILDS / f"{rid}.json"
    st = SF.load(mine) or {}
    if not st.get("build"):                          # once per request, also after a restart
        branch = FWK.branch_name(key, title)
        clone = B.clone(req["repo"])
        sha = FWK.base_commit(clone, req["base"])
        B.git(clone, "push", "-q", "-f", "origin", f"{sha}:refs/heads/{branch}", timeout=300)
        bid = B.handle({"action": "build_assign", "repo": req["repo"], "title": TC.cut(title, 120), "description": req["brief"],   # cap: id, the brief is whole
                        "onto": branch, "source": f"n8n:{req.get('workflow', '')}/{req.get('execution', '')}"}, c)["id"]
        st = {"build": bid, "branch": branch, "base": sha}
        SF.save(mine, st)
        RR.learn({"tracker": tracker, "key": key, "execution": req.get("execution")})
    bid = st["build"]
    while True:
        b = c.execute("select * from builds where id=?", (bid,)).fetchone()
        state = b["status"] if b else "failed"
        if state in ("review", "merged"):
            break
        if state in BUILD_FAILED:
            return {"status": "failed", "build": bid, "state": state, "branch": st["branch"], "error": (b["error"] if b else "") or f"build #{bid} {state}"}
        if stop is not None and stop.is_set():
            return None
        sleep(WAIT_AGAIN_S)
    said = {"status": "done", "build": bid, "state": state, "branch": st["branch"], "base": st["base"], "tracker": tracker, "key": key,
            "output": b["summary"] or ""}
    if state == "merged":                            # a build onto a branch with nothing to commit: no change was needed
        return {**said, "changed": False, "pr": ""}
    push = str(values.get("FORGE_PUSH") or "")
    if not push:
        return {**said, "changed": True, "pr": "", "note": "no FORGE_PUSH in this deployment: the change waits for the owner in the app"}
    if not st.get("pr"):
        clone = B.clone(req["repo"])
        B.git(clone, "fetch", "-q", "origin", f"+refs/heads/{b['branch']}:refs/heads/{st['branch']}", timeout=300)
        t = TR.find(tracker) or {"name": tracker}
        pr = FWK.publish(clone, st["branch"], push.format(repo=req["repo"]), forge, req.get("forge") or B.origin(req["repo"]), req["target"],
                         f"{key}: {title}", f"{b['summary'] or ''}\n\n---\nA draft from the AI Stack for {tracker}/{key}; the stack never merges it.",
                         TR.run_id(t, key), f"{tracker}/{key}")
        if not pr:
            return {**said, "status": "failed", "error": "the forge opened no pull request (no token, or the repository is not on it)"}
        st["pr"] = {"url": pr.get("url") or "", "number": pr.get("number")}
        SF.save(mine, st)
        B.put(c, bid, pr=st["pr"]["url"], pr_number=st["pr"]["number"])
    return {**said, "changed": True, "pr": st["pr"]["url"], "pr_number": st["pr"]["number"], "draft": True}


def run_plan(c, rid, req, cards, stop=None, sleep=time.sleep, db=None):
    """An improvised plan as one task: its steps are rows, run in waves (every step whose steps before have finished,
    together), each through the same path as an agent step. A step after one that failed does not run. -> the answer
    with every step's output, or None when the runner is stopping."""
    import conductor as CD
    steps = req["steps"]
    rows = [row_of(cards[s["agent"]], s["agent"], s["brief"], s.get("title") or "", after=s.get("after") or []) for s in steps]
    tid = open_task(c, rid, req, rows, req.get("title") or "\n".join(s["brief"].strip().splitlines()[0] for s in steps))
    for _ in range(CD.MAX_STEPS + 1):                # a wave per round: never more rounds than steps
        ss = CD.steps(c, tid, 1)
        state = {s["idx"]: s["status"] for s in ss}
        for s in ss:
            gone = [a for a in s["after"] if state.get(a) in ("failed", "cancelled")]
            if s["status"] == "pending" and gone:
                CD.put(c, s["id"], status="cancelled", error=f"step {gone[0]} did not finish", ended=CD.now())
                state[s["idx"]] = "cancelled"
        wave = [s["idx"] for s in ss if state[s["idx"]] not in SETTLED and all(state.get(a) in CD.FINISHED for a in s["after"])]
        if not wave:
            break
        if stop is not None and stop.is_set():
            return None
        threads = [threading.Thread(target=_settle_in, args=(db or M.db, tid, i, stop, sleep), daemon=True, name=f"flow-{rid}-{i}")
                   for i in wave]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    ss = CD.steps(c, tid, 1)
    if any(s["status"] not in SETTLED for s in ss):
        return None                                  # the runner is stopping: the plan goes on after its restart
    ok = all(s["status"] in CD.FINISHED for s in ss)
    close(c, tid, ok)
    last = [s for s in ss if not any(s["idx"] in x["after"] for x in ss)]
    out = last[0]["output"] or "" if len(last) == 1 else "\n\n".join(f"### Step {s['idx']}: {s['title']}\n{s['output'] or ''}" for s in last)
    bad = next((s for s in ss if s["status"] not in CD.FINISHED), None)
    return {"status": "done" if ok else "failed", "task": tid, "output": out,
            "error": f"step {bad['idx']}: {bad['error'] or bad['status']}" if bad else "",
            "steps": [{"step": s["idx"], **answer_of(tid, s)} for s in ss]}


def _settle_in(db, task, idx, stop, sleep):
    c = db()
    try:
        settle(c, task, idx, stop=stop, sleep=sleep)
    except Exception as e:                          # an adapter bug fails the step, not the plan's worker; it is logged
        import conductor as CD
        s = next(x for x in CD.steps(c, task, 1) if x["idx"] == idx)
        CD.put(c, s["id"], status="failed", error=f"{type(e).__name__}: {e}")
        if M:
            M.log(f"flows: task {task} step {idx}: {type(e).__name__}: {e}")
    finally:
        c.close()


def recall(req):
    """The memory tool's search (MEM-28), as the owner's: every collection. -> its hits, each with its collection."""
    import memstack as MS
    text = MS.handle({"action": "mem_search", "query": req["query"], "scope": req.get("scope") or "", "access": "all",
                      "agent": req.get("agent") or ""})["text"]
    hits, coll = [], ""
    for line in text.splitlines():
        if line.startswith("### "):
            coll = line[4:].strip()
        elif line.startswith("- ") and coll:
            hits.append({"collection": coll, "hit": TC.cut(line[2:], HIT_CHARS, "memory open gives the entry whole")})   # cap: preview, a hit names its ref to open
    return {"status": "done", "hits": hits, **({} if hits else {"said": text})}


KEPT = ("Kept", "Already known", "Already held", "Queued")   # memwrite.candidate's words for a note memory holds or will


def remember(req):
    """A note through the memory tool's write gate (MEM-28, MEM-35): it enters memory only after its check."""
    import memstack as MS
    said = MS.handle({"action": "mem_note", "kind": req["note"], "text": req["text"], "evidence": req.get("evidence") or "",
                      "agent": req.get("agent") or "n8n", "repo": req.get("repo") or "", "access": "all"})["text"]
    return {"status": "done", "kept": said.startswith(KEPT), "said": said}


def _job_spec(kind):
    """The job kind's typed parameters from the running packs, so a value outside its type is refused before the
    request; the worker checks again."""
    try:
        from domain import packs as PK
        return next((j["spec"] for p in PK.load()["packs"] for j in p["jobs"] if j["kind"] == kind), None)
    except Exception as e:                           # the worker still checks every value against its own copy; logged
        if M:
            M.log(f"flows: packs for {kind}: {type(e).__name__}: {e}")
        return None


def _place_worker(name):
    """The wsl place's worker is a thread of the runner, started by the step service (Temporal and its bridge are gone,
    DEC-52)."""
    if name != "wsl" or M is None or any(t.name == "place-wsl" and t.is_alive() for t in threading.enumerate()):
        return
    from domain import places as PL
    threading.Thread(target=PL.worker_loop, args=(M.stop,), daemon=True, name="place-wsl").start()


def command(rid, req, stop=None, sleep=time.sleep):
    """A job kind at a place (GEN-22): only a kind the owner approved there by its fingerprint runs; the approval waits
    in Needs you and the step is refused with that reason meanwhile. -> the answer, or None when the runner is stopping."""
    from domain import places as PL
    JOBS.mkdir(parents=True, exist_ok=True)
    mine = JOBS / f"{rid}.json"
    try:
        p = PL.place(req["place"])
        job = SF.load(mine)
        if job is None:
            if mine.exists():
                _say(f"flows: {rid}: its job file was empty or unreadable; the command is submitted again")
            _place_worker(req["place"])
            spec = _job_spec(req["command"])
            values, files = job_files(req.get("values") or {}, spec)
            job = {"rid": p.submit(req["command"], values, files, spec=spec), "at": time.time()}
            SF.save(mine, job)
    except (PL.Refused, ValueError) as e:
        return {"status": "refused", "error": str(e)}
    while True:
        st = p.state(job["rid"], submitted=job["at"])
        if st["status"] in ("done", "failed", "refused", "lost", "not picked up"):
            log = p.answers / job["rid"] / "artifacts" / "log.txt"
            files = p.artifacts(job["rid"])
            return {"status": st["status"] if st["status"] in ("done", "refused") else "failed", "place": req["place"],
                    "command": req["command"], "job": f"{req['place']}/{job['rid']}", "error": st.get("error") or "",
                    "steps": st.get("steps") or [], "artifacts": [a.name for a in files], "artifact_ids": saved(files, rid, req),
                    "log": tail(log.read_text(errors="replace"), 4000, f"the whole log is {log}") if log.is_file() else ""}   # cap: preview, the log's end; the job keeps it whole
        if stop is not None and stop.is_set():
            return None
        sleep(POLL_S)


def saved(files, rid, req):
    """A command's files into the artifact store (GEN-29), kept by their hash with the run that made them. -> their ids."""
    from domain import artifacts as AR
    ids = []
    for f in files:
        try:
            ids.append(AR.put(f, task=str(req.get("title") or req.get("command") or ""), step=rid, run=str(req.get("execution") or ""))["id"])
        except OSError as e:                         # the file stays in its place's answer folder; logged
            if M:
                M.log(f"flows: {rid}: {f.name} not saved: {e}")
    return ids


def people_of(role):
    """Who may answer a question: its role's people (ops/domain/roles.py); no role, or no map: the owner."""
    from domain import roles as RL
    return RL.people(role) if role else [RL.OWNER]


ASK_INPUTS = ("type", "question", "why", "choices", "answers", "allow_words", "default", "deadline", "deadline_hours", "role", "gate",
              "sensitivity", "facts")


def _chip_id(label):
    """A chip's id from its label, as ops/asks.py makes it for a workflow's own chips."""
    return re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")


def ask_spec(rid, req):
    """ASK-19: the Ask block's inputs as an Ask of the store (ops/asks.py): its kind (a registered type, else a workflow's
    own), its question and why, its chips (choices, or the older answers), words allowed or not, its default and
    deadline, its role, gate and sensitivity."""
    import asks as AK
    AK.register_workflow_kinds()
    kind = req.get("type") if req.get("type") in AK.TYPES else "workflow"
    labels = req.get("choices") or req.get("answers") or ["Yes", "No"]
    chips = [c if isinstance(c, dict) else {"label": str(c)} for c in labels] if kind == "workflow" else req.get("choices")
    dl = req.get("deadline")
    if dl in (None, "") and req.get("deadline_hours"):
        dl = time.time() + float(req["deadline_hours"]) * 3600
    default = req.get("default")
    if isinstance(default, str) and default:
        default = {"outcome": default if kind != "workflow" else _chip_id(default)}
    return {"kind": kind, "source": f"flow:{rid}", "question": str(req.get("question") or ""), "why": str(req.get("why") or ""),
            "choices": chips, "allow_words": req.get("allow_words", True) is not False, "default": default or None,
            "deadline": dl, "role": req.get("role") or None, "gate": bool(req.get("gate")), "sensitivity": req.get("sensitivity") or "normal",
            "facts": req.get("facts") or {}, "href": "#/workflows", "task": f"n8n:{req.get('workflow') or ''}/{req.get('execution') or rid}"}


def ask_problem(req):
    """The Ask block's inputs in words, or "" (SEC-11): checked as the store will check them, before anything waits."""
    import asks as AK
    if not isinstance(req.get("question"), str) or not req["question"].strip():
        return "a question needs its text"
    if req.get("type") not in (None, "", "workflow"):
        AK.register_workflow_kinds()
        if req["type"] not in AK.TYPES:
            return f"no kind of question {req['type']!r} is registered"
    for k in ("choices", "answers"):
        if req.get(k) is not None and not isinstance(req[k], list):
            return f"{k} is a list of answers"
    if req.get("sensitivity") not in (None, "", *AK.SENSITIVITY):
        return f"sensitivity is one of {', '.join(AK.SENSITIVITY)}"
    if req.get("role") and not NAME.fullmatch(str(req["role"])):
        return "a role is a name"
    try:
        spec = ask_spec("check", req)
        AK.check_spec(spec)
    except ValueError as e:
        return str(e)
    return ""


def ask(rid, req, notify=None):
    """WFL-07, ASK-19: the question is an Ask in the store, in Needs you until it is answered, dismissed, expired or
    answered by its default. -> the answer the workflow branches on, or None while it waits. A question asked before the
    Ask store (its answer file under asks/) keeps its answer."""
    import asks as AK
    got = SF.load(ASKS / f"{rid}.answer.json")
    if got is not None:
        return {"status": "done", "outcome": _chip_id(got["answer"]), "answer": got["answer"], "answered": got.get("at", ""),
                "by": got.get("who") or "", "person": got.get("who") or "", "via": "app", **({"role": req["role"]} if req.get("role") else {})}
    new = AK.by_source(f"flow:{rid}") is None
    try:
        a = AK.open_ask(ask_spec(rid, req))
    except ValueError as e:
        return {"status": "refused", "error": str(e)}
    if new and notify and a["status"] in AK.SHOWN and "telegram" in AK.channels():
        people = AK.public(a)["people"]
        notify(f"A workflow asks {'you' if people in (['owner'], []) or a['role'] == 'owner' else ', '.join(people)}: {AK.outward(a)}")
    return answer_out(a)


def answer_out(a):
    """An Ask's end as the workflow's answer: {status, outcome, values, words, person, role, via, interpreted_as}; None
    while it waits (an answer held for its undo still waits)."""
    if a["status"] in ("open", "escalated", "snoozed") or (a.get("pending") or {}).get("state") == "held":
        return None
    ans = a.get("answer") or {}
    base = {"words": ans.get("words") or "", "person": ans.get("person") or "", "role": ans.get("role") or a.get("role"),
            "via": ans.get("via") or "", "answered": ans.get("at")}
    if a["status"] == "dismissed":
        return {"status": "dismissed", "outcome": None, **base}
    if a["status"] == "expired":
        return {"status": "expired", "outcome": None, **base}
    label = next((c["label"] for c in a.get("choices") or [] if c["id"] == ans.get("outcome")), ans.get("outcome"))
    return {"status": "done", "outcome": ans.get("outcome"), "answer": label, "values": ans.get("values") or {},
            "interpreted_as": ans.get("interpreted_as"), "by": ans.get("person") or "", **base}


def answer(req):
    """A tap in Needs you (action flow_answer): the answer of one waiting question, from one who may give it (the
    app's signed-in person, "who"; at home, with no map of roles, that is the owner). The answer records who gave it."""
    rid, a = str(req.get("id") or ""), req.get("answer")
    q = ASKS / f"{rid}.json"
    qd = SF.load(q) if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid) else None
    if qd is None:
        return {"ok": False, "error": "that question is not waiting any more"}
    if a not in qd["answers"]:
        return {"ok": False, "error": "that is not one of the question's answers"}
    who, people = str(req.get("who") or "owner"), qd.get("people") or ["owner"]
    if people != ["owner"] and who not in people:
        return {"ok": False, "error": f"only {', '.join(people)} may answer this ({qd.get('role') or 'its role'})"}
    got = ASKS / f"{rid}.answer.json"
    if SF.load(got) is not None:
        return {"ok": False, "error": "it was answered already"}
    SF.save(got, {"answer": a, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "who": who})
    return {"ok": True, "answer": a, "who": who}


def waiting():
    """The questions without an answer, for Needs you."""
    if not ASKS.is_dir():
        return []
    qs = (SF.load(p) for p in sorted(ASKS.glob("*.json"))
          if not p.name.endswith(".answer.json") and SF.load(ASKS / f"{p.stem}.answer.json") is None)
    return [q for q in qs if q is not None]


def answer_of(task, s):
    return {"status": "done" if s["status"] in ("done", "skipped") else s["status"], "task": task, "step": s["id"],
            "output": s.get("output") or "", "error": s.get("error") or "", "agent": s.get("agent"), "harness": s.get("harness")}


WHAT = {"crew": lambda r: r["job"], "task": lambda r: f"Task #{r['task']}", "build": lambda r: f"A coding change in {r['repo']}",
        "recall": lambda r: "A memory search", "remember": lambda r: f"A {r['note']} for memory",
        "command": lambda r: f"{r['command']} at {r['place']}", "plan": lambda r: f"A plan of {len(r['steps'])} steps",
        "wait_item": lambda r: f"A wait on {r['tracker']}/{r['key']}", "tracker": lambda r: f"A {r['write']} on {r['tracker']}/{r['key']}",
        "item": lambda r: f"A read of {r['tracker']}/{r['key']}"}


def step_name(req, crew=None):
    """What a step is called where you read it: its crew job's own name, its title without the workflow's "Crew: "."""
    if req.get("kind") == "crew" and req.get("job"):
        import crew as CR
        named = ((crew if crew is not None else CR.BY_ID).get(req["job"]) or {}).get("name")
        if named:
            return named
    try:
        return str(req.get("title") or WHAT[req["kind"]](req)).removeprefix("Crew: ")
    except (KeyError, TypeError):
        return req.get("agent") or "A step"


def step_area(req, crew=None):
    """The step's area (ops/areas.py): its crew job's, else its workflow's; "" when neither says."""
    if req.get("kind") == "crew" and req.get("job"):
        import crew as CR
        area = ((crew if crew is not None else CR.BY_ID).get(req["job"]) or {}).get("area")
        if area:
            return area
    if req.get("workflow"):
        import flow_tasks as FT
        try:
            wf = FT.workflow_of_run(f"n8n:{req['workflow']}/")
        except (OSError, ValueError):
            wf = None
        return FT.area_of_workflow(wf) if wf else ""
    return ""


def report(req, answer, crew=None, now=None):
    """WFL-10, OBS-19, OBS-20: Activity hears how each step of a workflow ended, in plain words, under its area; the raw
    reason and the n8n run are the line's detail. A failure is pushed, unless the stack is being updated or restarted:
    then it waits for the step's next good run (one quiet line) or is told once it has waited (ops/notices.py)."""
    ev = getattr(M, "event", None)
    if not ev or req.get("kind") == "ask":
        return
    import areas as AR
    import notices as NT
    name, area = step_name(req, crew), step_area(req, crew)
    st = answer.get("status")
    where = f"n8n run {req['execution']}" if req.get("execution") else ""
    line = {"title": AR.AREAS.get(area, "Workflows"), "area": area, "task": answer.get("task"), "by": req.get("job") or req.get("agent") or ""}
    key = f"flow:{req.get('workflow') or ''}:{req.get('job') or req.get('node') or name}"
    if st in ("done", "skipped"):
        quiet = NT.settled(key, now)
        if quiet:
            return ev("workflow", "", quiet["text"], quiet=True, detail=quiet.get("detail") or where, **line)
        return ev("workflow", "", f"{name} ran fine.", detail=where, **line)
    if st == "cancelled":
        return ev("workflow", "", f"{name} was stopped.", detail=where, **line)
    f = NT.failure(name, answer.get("error") or st, state=st)
    detail = "; ".join(x for x in (f["detail"], where) if x)
    ch = NT.change(now)
    if ch:
        return NT.hold(key, {**line, "name": name, "head": f["head"], "tail": f["tail"], "text": f["text"], "detail": detail}, ch, now)
    ev("workflow", "", f["text"], push=True, detail=detail, **line)


def told_late(n):
    """notices.due's emit: a failure held during an update that did not settle, told now as it would have been."""
    M.event("workflow", "", n["text"], push=True, title=n.get("title") or "Workflows", area=n.get("area") or "",
            detail=n.get("detail") or "", task=n.get("task"), by=n.get("by") or "")


LEAN = ("status", "outcome", "values", "words", "person", "via", "interpreted_as", "task", "step", "occ", "run", "build", "state", "branch", "base", "changed", "pr", "pr_number", "draft",
        "ci", "job", "place", "command", "artifacts", "artifact_ids", "comments", "ref", "shadow", "again", "answer", "answered", "by",
        "role", "kept", "sent", "tracker", "key", "write", "waited_hours", "agent", "harness", "verdict", "source", "reminded", "attach_to",
        "data_class")


def lean_answers(data=None):
    """WFL-22: a customer-class deployment answers n8n with status, ids and a short summary, unless its data.yaml says
    n8n_answers: full. Read from the data guard's own file (ops/dataguard.py); none: not a customer deployment."""
    try:
        import dataguard as DG
    except SystemExit:                               # the deployment has no data.yaml: home's rules
        return False
    data = DG.DATA if data is None else data
    return DG.customer(data) and str(data.get("n8n_answers") or "summaries") != "full"


def lean(answer):
    """What n8n keeps of an answer in a customer-class deployment: status, outcome, ids, references and a short summary;
    the whole text is in the run register (ops/runreg.py) and the task's record. A step whose text is people's words
    from outside (an item, its replies) says its own summary, which names no text."""
    out = {k: answer[k] for k in LEAN if k in answer}
    text = str(answer.get("output") or answer.get("said") or "")
    if answer.get("summary"):
        out["summary"] = TC.cut(str(answer["summary"]), SUMMARY_CHARS)   # cap: preview, the step's own summary is short already
    elif text:
        out["summary"] = TC.cut(text, SUMMARY_CHARS, "the whole text is in the task's record")   # cap: preview, the run register and the task keep it whole
    if answer.get("error"):
        out["error"] = TC.cut(str(answer["error"]), SUMMARY_CHARS, "the whole reason is in the run register")   # cap: preview, kept whole in the register
    if isinstance(answer.get("steps"), list):
        out["steps"] = [lean(x) if isinstance(x, dict) else x for x in answer["steps"]]
    if "hits" in answer:
        out["hits"] = len(answer["hits"])
    out["lean"] = True
    return out


def n8n_ready(get=None):
    """WFL-34: whether n8n has finished starting. /healthz answers as soon as its port opens, before its migrations, its
    workflows' activation and its start-up recovery; an answer posted then was dropped or crashed its run (the upgrade
    test of 10 Nov 2026, docs/N8N-MIGRATION.md §11.1). /healthz/readiness answers 200 only after all three."""
    try:
        with (get or urllib.request.urlopen)(urllib.request.Request(f"{N8N}/healthz/readiness"), timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def deliver(url, answer, post=None, ready=None):
    """POSTs the answer to n8n's resume URL, only while n8n is ready (WFL-34). -> True when n8n took it. A caller that
    gives its own opener (post) gives its own readiness too, or none."""
    target = resume_target(url)
    if not target:
        return False
    if not (ready or (n8n_ready if post is None else (lambda: True)))():
        return False                                 # n8n is starting: sent again on the next round (DELIVER_EVERY_S)
    data = json.dumps(answer, ensure_ascii=False).encode()
    req = urllib.request.Request(target, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with (post or urllib.request.urlopen)(req, timeout=30) as r:
            return 200 <= r.status < 300
    except OSError:
        return False


def all_cards():
    """The agents a step may name: the stack's cards and each running pack's (<pack>:<agent>)."""
    import conductor as CD
    try:
        from domain import packs as PK
        return {**CD.cards(), **PK.cards()}
    except Exception as e:                           # the stack's own agents still run; the pack's wait for its fix
        if M:
            M.log(f"flows: packs: {type(e).__name__}: {e}")
        return CD.cards()


def tracker_write(rid, req):
    """WFL-21: one write to the item through trackers.write, in shadow until the owner lets its kind go live; its write
    id is the request's, so the runner's own retry writes nothing twice."""
    import runreg as RR
    from domain import trackers as TR
    RR.learn(req)
    body = str(req.get("body") or "").strip()
    if req.get("from_step"):                         # an earlier step's whole text, from the register: n8n may hold only its summary
        said = RR.output_of(req.get("execution"), req["from_step"])
        if said is None:
            return {"status": "refused", "error": f"no step {req['from_step']!r} with an answer in this run"}
        body = f"{body}\n\n{said}" if body else said
    r = TR.write({"tracker": req["tracker"], "kind": req["write"], "key": req["key"], "body": body, "write_id": f"n8n/{rid}",
                  "run": str(req.get("execution") or ""), "node": req.get("node") or req.get("title") or ""})
    if r.get("refused") and r.get("gate"):              # ASK-20: a gated status waits for its gate's Ask; a no refuses
        import asks as AK
        st = AK.record_gate(r["gate"])
        if st.get("state") == "waiting":
            return None
        return {"status": "refused", "error": r["why"], "gate": st.get("ask")}
    if r.get("refused"):
        return {"status": "refused", "error": r["why"]}
    return {"status": "done", "tracker": req["tracker"], "key": req["key"], "write": req["write"], "shadow": bool(r.get("shadow")),
            "ref": r["ref"], **({"again": True} if r.get("again") else {})}


def _say(line):
    if M:
        M.log(line)


def _register(fn, *a):
    """The run register keeps every step; a register that cannot write never stops the step (logged)."""
    import runreg as RR
    try:
        getattr(RR, fn)(*a)
    except Exception as e:                           # logged; the step and its answer go on
        if M:
            M.log(f"flows: run register {fn}: {type(e).__name__}: {e}")


def work(rid, req, cards, crew, sleep):
    """The request's work, by its kind. -> the answer, or None while it waits (looked at again on the next scan, or after
    the runner's restart)."""
    k = req["kind"]
    if k == "crew":
        return run_crew(req["job"], crew)
    if k == "notify":                                # the stack's own notification path: quiet hours, the data guard (OBS-16, GEN-14)
        M.notify(req["message"])
        return {"status": "done", "sent": True}
    if k == "ask":
        return ask(rid, req, notify=M.notify if M else None)
    if k == "task":
        return run_task(M.db(), rid, req["task"], stop=M.stop, sleep=sleep)
    if k == "recall":
        return recall(req)
    if k == "remember":
        return remember(req)
    if k == "command":
        return command(rid, req, stop=M.stop, sleep=sleep)
    if k == "build" and req.get("item"):
        return item_build(M.db(), rid, req, stop=M.stop, sleep=sleep)
    if k == "build":
        return run_build(M.db(), rid, req, cards, stop=M.stop, sleep=sleep)
    if k == "wait_item":
        import runreg as RR
        return RR.wait(rid, req)
    if k == "tracker":
        return tracker_write(rid, req)
    if k == "item":
        return item_read(rid, req)
    if k == "plan":
        return run_plan(M.db(), rid, req, cards, stop=M.stop, sleep=sleep)
    c = M.db()
    if req.get("tracker") and req.get("from_item") is not False and not opened(c, rid):
        req, failed = with_item(req)
        if failed:
            return failed
    task, _ = open_step(c, rid, req, cards)
    s = drive(c, task, stop=M.stop, sleep=sleep)
    if s["status"] not in SETTLED:
        return None                                  # the runner is stopping: looked at again after its restart
    import conductor as CD
    close(c, task, s["status"] in CD.FINISHED)
    return answer_of(task, s)


def handle(rid, path, cards=None, crew=None, post=None, sleep=time.sleep, repos=None):
    """One request, from validation to the answer n8n gets."""
    import crew as CR
    cards = cards if cards is not None else all_cards()
    crew = crew if crew is not None else CR.BY_ID
    req = json.loads(path.read_text())
    DONE.mkdir(parents=True, exist_ok=True)
    out = DONE / f"{rid}.json"
    answer = SF.load(out)
    if answer is None and out.exists():              # a write cut short before writes were atomic: no answer yet
        _say(f"flows: {rid}: its answer file was empty or unreadable; removed, the step is handled again")
        out.unlink(missing_ok=True)
    if answer is None:
        _register("step_begin", rid, req)
        why = validate(req, cards, crew, repos=repos)
        answer = {"status": "refused", "error": why} if why else work(rid, req, cards, crew, sleep)
        if answer is None:
            return
        SF.save(out, answer)
        _register("step_end", rid, req, answer)
        report(req, answer)
    if not req.get("resume_url"):
        path.unlink(missing_ok=True)
        return
    sent = lean(answer) if lean_answers() else answer
    first = time.time()
    while time.time() - first < DELIVER_FOR_S:
        if deliver(req["resume_url"], sent, post):
            path.unlink(missing_ok=True)
            return
        if M and M.stop.is_set():
            return
        sleep(DELIVER_EVERY_S)
    path.unlink(missing_ok=True)
    M.notify(f"n8n did not take the answer of step {rid} for a day; it is kept in {out}.")


def _run(rid, path):
    try:
        handle(rid, path)
    except Exception as e:                              # logged; the request stays pending and is looked at after a restart
        M.log(f"flows: {rid}: {type(e).__name__}: {e}")
    finally:
        with _lock:
            _busy.discard(rid)


REPO_WORKFLOWS = Path(__file__).resolve().parent.parent / "n8n/workflows"
CATALOG_EVERY_S = 60
PLACE_NAMES = {"wsl": "WSL (the stack's own user)", "wsl-host": "WSL host (the owner's tools and repositories)", "windows": "Windows"}


def catalog(repo=REPO_WORKFLOWS, made=None):
    """WFL-11: which crew job and task has which n8n workflow, and whether n8n runs it now, for the app's pages (the
    repository's workflows and those the runner made since the last export, ops/n8n_jobs.py).
    -> {"jobs": {"crew:<job>" | "task:<id>": {"id", "name", "active"}}}"""
    import n8n_jobs as NJ
    idx = NJ.index(repo, made or NJ.MADE)
    return {"jobs": {f"{k}:{key}": {"id": w["id"], "name": w["name"], "active": w["active"]} for (k, key), w in sorted(idx.items(), key=str)}}


STEP_HARNESSES = ("hermes", "claude-code", "python", "opencode")   # the harnesses a step can run on (TSK-07)
CARD_STEPS = ("build", "check")                   # TRL-07, TRL-08: a card's steps are builds in its lane, or the judge's checks


def runs_steps(card):
    """Can this agent do a step? Its steps are builds or checks, or its harness has an adapter and a python agent has its
    own key."""
    if card.get("step_kind") in CARD_STEPS:
        return True
    return card.get("harness") in STEP_HARNESSES and (card["harness"] != "python" or card.get("key") not in (None, "none"))


def step_agents(packs=()):
    """The agents a step may name: the stack's (config/agents.yaml, those that can do a step) and each running pack's
    (<pack>:<agent>), with their harness and purpose."""
    import yaml
    try:
        reg = yaml.safe_load((Path(__file__).resolve().parent.parent / "config/agents.yaml").read_text())
    except OSError:
        reg = {}
    core = [{"id": a["id"], "name": a.get("name") or a["id"], "harness": a.get("harness", ""), "purpose": a.get("purpose", "")}
            for a in reg.get("agents") or [] if runs_steps(a)]
    return core + [{k: a.get(k, "") for k in ("id", "name", "harness", "purpose", "pack")} for p in packs or () for a in p["agents"]]


def step_catalog(packs=None, repos=None, places=None):
    """WFL-06: what the node's pickers offer, live: the agents that can do a step (the stack's and each running pack's),
    the crew jobs, the places with the commands approved at each, the repositories the builder may change, the
    deployment's trackers and roles, and the kinds.
    A part that cannot be read is empty, with its reason under "problems"."""
    import crew as CR
    out = {"kinds": list(KINDS), "agents": [], "crew": [], "places": [], "repos": [], "trackers": [], "roles": [], "problems": []}

    def part(name, f):
        try:
            out[name] = f()
        except Exception as e:                      # one part missing leaves the others
            out["problems"].append(f"{name}: {type(e).__name__}: {e}")

    def agents():
        from domain import packs as PK
        return step_agents(packs if packs is not None else PK.load()["packs"])

    def where():
        from domain import places as PL
        names = places if places is not None else [n for n in PL.PLACES if n in PL.config() or n == "windows"]
        got = []
        for n in names:
            st = PL.place(n).status() or {}
            got.append({"id": n, "name": PLACE_NAMES.get(n, n), "answering": bool(st),
                        "commands": sorted(k for k, v in (st.get("kinds") or {}).items() if v.get("approved"))})
        return got

    def code():
        import builds as B
        return [{"id": r, "name": r} for r in (repos if repos is not None else B.repos())]
    part("agents", agents)
    part("crew", lambda: [{"id": j, "name": a.get("name") or j} for j, a in sorted(CR.BY_ID.items()) if a.get("unit")])
    part("places", where)
    part("repos", code)

    def trackers():
        from domain import trackers as TR
        return [{"id": t["name"], "name": t["name"], "purpose": f"{t.get('kind')}, starts {t.get('workflow') or 'no workflow'}"}
                for t in TR.config()["trackers"]]

    def roles():
        from domain import roles as RL
        return [{"id": r, "name": r, "purpose": "may answer: " + ", ".join(ps)} for r, ps in sorted(RL.load()[0].items())]
    part("trackers", trackers)
    part("roles", roles)
    return out


def write_catalog(public):
    """public/workflows.json for the app's pages (WFL-11), public/step-catalog.json for the node's pickers (WFL-06)."""
    SF.save(Path(public) / "workflows.json", catalog())
    SF.save(Path(public) / "step-catalog.json", step_catalog())


def worker():
    PENDING.mkdir(parents=True, exist_ok=True)
    PENDING.chmod(0o777)                                # the app container (another uid) drops requests here
    shown = 0.0
    while not M.stop.is_set():
        if time.time() - shown > CATALOG_EVERY_S:
            shown = time.time()
            try:                                        # WFL-09: a task that got a schedule gets its workflow
                import n8n_jobs as NJ
                for said in NJ.reconcile(M.db(), say=M.log):
                    M.event("task", "", said[:1].upper() + said[1:], title="Tasks")
            except Exception as e:                      # logged; tried again on the next pass
                M.log(f"flows: workflows of tasks: {type(e).__name__}: {e}")
            try:
                write_catalog(M.PUBLIC)
            except Exception as e:                      # logged; the pages show no link meanwhile
                M.log(f"flows: catalog: {type(e).__name__}: {e}")
        import asks as AK
        for f in ([] if AK.stopped() else sorted(PENDING.glob("*.json"))):   # ASK-08: the stop switch: steps wait in the queue
            rid = f.stem
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid):
                continue
            with _lock:
                if rid in _busy:
                    continue
                _busy.add(rid)
            threading.Thread(target=_run, args=(rid, f), daemon=True, name=f"flow-{rid}").start()
        M.stop.wait(SCAN_S)


def start(m):
    global M
    M = m
    threading.Thread(target=worker, daemon=True, name="flows").start()


if __name__ == "__main__":
    for d in (PENDING, DONE):
        print(d, sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else "none")
