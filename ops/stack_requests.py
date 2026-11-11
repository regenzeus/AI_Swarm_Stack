"""The runner's side of the ways in for a site's agents (WAY-04, WAY-05, WAY-08; docs/CLI.md): what the `stack` command
line (ops/stack_cli.py) and the stack MCP tools ask the runner to do, through the same inbox as the app.

    workflow_run   start a run of one workflow through its Run now webhook (WFL-13, with the runner's header X-Aistack-Hook,
                   SEC-27), with the caller's inputs as the webhook's body; refused while the stop switch is on (ASK-08)
    pack_ask       open the gate Ask that approves one commit of a pack (GEN-21): the command line and the agents never
                   approve anything themselves; only a tap in the app by a person in the gate's role does (ASK-05)
    stack_doctor   the site's doctor (ops/stack_cli.py doctor), for the agents' tool

Who asked and how (via cli or mcp) come with the request: the app sets them from its sign-in and the command line's
header, the MCP tools from their server (images/mission-control/server.stack.py), never from the caller's own words. This
module never answers an Ask; ops/asks.py refuses a gate's answer that comes by the command line or an agent's tool.

    handle(req, event)   one request; event is the runner's activity line (ops/missions.py event)
"""
import json
import os
import re
import urllib.error
import urllib.request

import asks as AK
import textcap as TC

ACTIONS = {"workflow_run", "pack_ask", "stack_doctor"}
KEY = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
RUN_POST_S = 15                                       # limit: stops, n8n answers a Run now webhook at once; a silent n8n is said so
RUN_NOW = "Run now"                                   # the Run now trigger's node name (ops/n8n_gen.py RUN_NOW)
WEBHOOK = "n8n-nodes-base.webhook"


# ---------------------------------------------------------------- a run, started
def _workflows():
    """This deployment's workflows (ops/n8n_jobs.py: the repository's it runs and the ones the runner made), then the
    running packs' workflows. -> [(file stem, workflow)]"""
    import n8n_jobs as NJ
    out = [(w["file"].removesuffix(".json"), w["wf"]) for w in NJ.workflows().values()]
    try:
        from domain import packs as PK
        for p in PK.load()["packs"]:
            for w in p["workflows"]:
                out.append((w["name"], json.loads(open(w["path"], encoding="utf-8").read())))
    except Exception as e:                            # a pack's repository away: the stack's own workflows still start
        print(f"stack: the packs' workflows were not read: {type(e).__name__}: {e}", flush=True)
    return out


def find(ref, flows=None):
    """One workflow by its file stem, its n8n id or its name (case does not matter). -> (stem, workflow); a name that is
    no workflow, or one that names two, is refused with the names that come close."""
    ref = str(ref or "").strip()
    if not ref:
        raise ValueError("name a workflow (stack workflows lists them)")
    flows = _workflows() if flows is None else flows
    low = ref.lower()
    hits = [(s, w) for s, w in flows if low in (s.lower(), str(w.get("id") or "").lower(), str(w.get("name") or "").lower())]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise ValueError(f"{ref!r} names {len(hits)} workflows: " + ", ".join(sorted(s for s, _ in hits)) + "; use the file name")
    near = sorted(s for s, w in flows if low in s.lower() or low in str(w.get("name") or "").lower())
    raise ValueError(f"no workflow {ref!r} on this site" + (f"; did you mean {', '.join(near)}?" if near else " (stack workflows lists them)"))


def hook_path(wf):
    """The workflow's Run now trigger: its Webhook named Run now, or one whose path starts with run/ (WFL-13). -> the
    path, or "" when it has none."""
    hooks = [n for n in wf.get("nodes") or [] if n.get("type") == WEBHOOK]
    for n in sorted(hooks, key=lambda n: n.get("name") != RUN_NOW):
        path = str((n.get("parameters") or {}).get("path") or "")
        if n.get("name") == RUN_NOW or path.startswith("run/"):
            return path
    return ""


def inputs_of(raw):
    """The caller's inputs as a flat {name: text}; a name is letters, digits, dots, dashes and underscores."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        raise ValueError("inputs are name=value pairs")
    out = {}
    for k, v in raw.items():
        if not KEY.fullmatch(str(k)):
            raise ValueError(f"an input's name is a short word (letters, digits, . _ -), not {k!r}")
        if not isinstance(v, (str, int, float, bool)):
            raise ValueError(f"the input {k} is a text, a number or yes/no")
        out[str(k)] = v
    return out


def _post(url, body):
    import n8n_gen as G
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode(), method="POST",
                                 headers={"Content-Type": "application/json", G.HOOK_HEADER: os.environ.get("N8N_HOOK_TOKEN", "")})
    with urllib.request.urlopen(req, timeout=RUN_POST_S) as r:  # nosemgrep: dynamic-urllib-use-detected -- n8n on this machine
        r.read()


def run_workflow(req, event=None, post=None, flows=None, now=None):
    """workflow_run: one run of a workflow through its Run now webhook, as the app's Run now and n8n's own would. The
    webhook's body carries the inputs and who started it. -> {workflow, name, id, started, message}"""
    import time
    if AK.stopped():
        raise ValueError("the stop switch is on: no workflow starts until it is switched off on Home")
    stem, wf = find(req.get("workflow"), flows)
    inputs = inputs_of(req.get("input"))
    name = str(wf.get("name") or stem)
    path = hook_path(wf)
    if not path:
        raise ValueError(f"{name} has no Run now trigger (a Webhook at run/{stem}); it starts {_how(wf)}")
    if not wf.get("active"):
        raise ValueError(f"{name} is switched off: switch it on in Workflows (its Active switch), then it can be started")
    if post is None and not os.environ.get("N8N_HOOK_TOKEN"):    # SEC-27: n8n refuses a webhook call without the runner's header
        raise ValueError("the runner has no N8N_HOOK_TOKEN for n8n's webhooks (make trust-keys, then restart the runner)")
    import flows as FW
    who, via = str(req.get("who") or ""), str(req.get("via") or req.get("source") or "app")
    started = time.time() if now is None else now
    try:
        (post or _post)(f"{FW.N8N}/webhook/{path}", {"input": inputs, "by": who, "via": via})
    except urllib.error.HTTPError as e:
        raise ValueError(f"n8n did not start {name} (HTTP {e.code}): is it published in n8n?") from None
    except OSError as e:
        raise ValueError(f"n8n did not answer ({type(e).__name__}): is it running?") from None
    if event:
        event("workflow", "", f"{name}: started by {who or 'someone'} through {_via_words(via)}", title="Workflows", by=who)
    return {"workflow": stem, "name": name, "id": str(wf.get("id") or ""), "started": started,
            "message": f"Started {name}: its run shows in its runs as soon as its first step reports"}


def _how(wf):
    import flows_view as FV
    return FV.schedule_of(wf)


def _via_words(via):
    return {"cli": "the command line", "mcp": "an agent's tool", "app": "the app"}.get(via, via or "the app")


# ---------------------------------------------------------------- a pack's commit, asked for
def pack_ask(req, packs=None):
    """pack_ask: the gate Ask that approves one commit of a pack the deployment names (packs.txt). Approved already,
    refused already, or its pinned commit's own Ask waiting: said so. Otherwise one gate Ask (kind pack-commit, a
    security floor) whose Approve chip runs pack_approve as the person who taps it. -> {ask, state, role, message}"""
    import decisions as DQ
    PK = packs
    if PK is None:
        from domain import packs as PK
    name, commit = str(req.get("name") or "").strip(), str(req.get("commit") or "").strip().lower()
    if not PK.NAME.fullmatch(name):
        raise ValueError(f"a pack's name is letters, digits and dashes, not {name!r}")
    if not PK.HEX.fullmatch(commit):
        raise ValueError(f"a commit is 7 to 40 hex digits, not {commit!r}")
    e = next((x for x in PK.entries() if x["name"] == name), None)
    if not e:
        raise ValueError(f"this deployment names no pack {name} (its packs.txt); a pack joins a deployment by a commit to it")
    full, folder = PK.checkout({**e, "commit": commit})
    rec = PK._approvals().get(name) or {}
    ok = [a for a in rec.get("approved") or [] if a["commit"] == full]
    if ok:
        return {"ask": None, "state": "approved", "message": f"{name} at {full[:12]} is approved already ({ok[0]['who']}, {ok[0]['at']})"}
    no = next((r for r in rec.get("refused") or [] if r["commit"] == full), None)
    if no:
        raise ValueError(f"{name} at {full[:12]} was refused by {no['who']}" + (f": {no['why']}" if no.get("why") else "")
                         + "; a refused commit stays refused, a new commit is asked for again")
    DQ.register_kinds()
    pinned = full == _full(PK, e)
    if pinned:                                         # its own Ask from the decision queue (packs.decisions): the same one
        a = AK.by_source(f"dq:pack:{name}@{full[:12]}")
        if a and a["status"] in AK.WAITING:
            return {"ask": a["id"], "state": a["status"], "role": a["role"], "gate": True,
                    "message": f"Waiting already: a person in the role {a['role']} approves it by a tap in the app"}
    a = AK.by_source(f"pack:{name}@{full}")
    if a and a["status"] in AK.WAITING:                # asked before: the same Ask
        return {"ask": a["id"], "state": a["status"], "role": a["role"], "gate": True,
                "message": f"Waiting already: a person in the role {a['role']} approves it by a tap in the app"}
    runs = (rec.get("approved") or [{}])[-1].get("commit", "")
    p = PK.read(name, full, folder)
    count = lambda xs, one: f"{len(xs)} {one}{'' if len(xs) == 1 else 's'}"   # noqa: E731
    brings = ", ".join(count(p[k], w) for k, w in (("agents", "agent"), ("jobs", "command"), ("workflows", "workflow"), ("skills", "skill")) if p[k])
    facts = {"Pack": name, "Commit": full[:12], "Runs now": runs[:12] or "nothing yet", "Brings": brings or "nothing"}
    if p["problems"]:
        facts["Problems"] = TC.fit("; ".join(p["problems"]), 1500)   # cap: api, the data rule's text limit; the Stack page lists each
    a = AK.open_ask({"kind": "pack-commit", "source": f"pack:{name}@{full}", "role": "owner",
                     "question": f"Approve pack {name} at {full[:12]}?" if not runs else f"Approve pack {name} at {full[:12]} (now {runs[:12]})?",
                     "why": f"Asked by {req.get('who') or 'someone'} through {_via_words(str(req.get('via') or ''))}. Nothing of it runs "
                            "until a person in this role approves it here; the deployment then runs it once its packs.txt names it.",
                     "facts": facts, "choices": [{"id": "approve", "label": "Approve"}, {"id": "not-now", "label": "Not now"},
                                                 {"id": "look", "label": "Look", "href": f"#/system?tab=connections&pack={name}"}],
                     "acts": {"approve": {"action": "pack_approve", "name": name, "commit": full}},
                     "href": f"#/system?tab=connections&pack={name}", "task": f"pack:{name}",
                     "unanswered": f"commit {runs[:12]} keeps running" if runs else "the pack does not run"})
    return {"ask": a["id"], "state": a["status"], "role": a["role"], "gate": True,
            "message": f"Asked: a person in the role {a['role']} approves it by a tap in the app; the command line never approves"}


def _full(PK, e):
    try:
        return PK.checkout(e)[0]
    except (ValueError, OSError):
        return ""


# ---------------------------------------------------------------- the requests
def handle(req, event=None):
    a = req.get("action")
    if a == "workflow_run":
        return run_workflow(req, event)
    if a == "pack_ask":
        return pack_ask(req)
    if a == "stack_doctor":
        import stack_cli as SC
        code, text = SC.doctor(app=False)
        return {"healthy": code == 0, "text": text}
    raise ValueError(f"unknown action {a}")
