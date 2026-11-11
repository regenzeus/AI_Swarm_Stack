# part of server.py (WAY-01 to WAY-08, docs/CLI.md): the ways in for a site's agents. It runs in server.py's namespace
# where it stood (_part); not a module of its own.
#
# The `stack` command line (ops/stack_cli.py, on the site's own machine) talks to this app's API through its published
# port, as the owner's browser does: the same routes, policy, roles and record. It names itself with the header
# X-Aistack-Via: cli, and /api/request then takes only its actions (CLI_ACTIONS: start a run, answer an Ask that is no
# gate, ask for a pack's approval): no approval, deploy, purchase or standing rule. Its answers reach the runner as via
# cli, and a gate refuses them (ops/asks.py): a gate is a tap in the app. The person is the sign-in, as for the app: the
# site's operator login the command line sends, or the local gate's owner. The header only takes rights away; a program
# on this PC that leaves it out is the accepted local-spoofing risk of docs/SECURITY.md.
#
# The same reads and actions are the tools of the MCP server "stack" (port 8100: only LiteLLM with its token, SEC-26;
# granted per key in ops/keys.sh). Their requests reach the runner as via mcp, by the agents' login AGENT_LOGIN, which the
# deployment's roles may or may not name: roles decide, as for a person.
#
# Reads (GET /api/stack/...): the workflows, their newest runs, one run with its steps and Asks, the agents with the
# workflows they are used in, the open Asks. A private Ask shows no figure here (ASK-07: an agent is no channel for it).
STACK_VIA = "x-aistack-via"
FLOWS_VIEW = M / "public/workflows-runs.json"           # the runner's view of the workflows and their runs (ops/flows_view.py)
CLI_ACTIONS = ("workflow_run", "ask_answer", "pack_ask")
AGENT_LOGIN = "stack-agents"                     # who an agent's stack tool acts as; the roles file decides what it may answer
ASK_SHOWN = ("open", "escalated")
RUN_STATES = ("running", "waiting", "done", "failed")
GATE_NO = ("a gate is answered only by a tap in the app by a person in its role ({role}); the command line and the agents' "
           "tools never answer one")
PRIVATE_NO = "a private question is answered in the app: its figures never leave it"


def _flows():
    try:
        return json.loads(FLOWS_VIEW.read_text()).get("workflows") or []
    except (OSError, ValueError, AttributeError):
        return []


def _same(a, b):
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def view_workflows():
    """Every workflow of the site with its trigger, switch, agents and last run (public/workflows-runs.json)."""
    out = []
    for w in _flows():
        r = (w.get("runs") or [None])[0]
        out.append({"id": str(w.get("id") or ""), "name": w.get("name") or "", "active": bool(w.get("active")), "trigger": w.get("schedule") or "",
                    "agents": w.get("agents") or [], "jobs": w.get("crew") or [], "runs_total": w.get("runs_total") or 0,
                    "last_run": None if not r else {"id": str(r.get("execution")), "state": r.get("state"), "started": r.get("started"), "ended": r.get("ended")}})
    return out


def view_runs(workflow="", status=""):
    """The newest runs of every workflow (or one), newest first; a workflow or a state that is not there is refused."""
    flows = _flows()
    if workflow and not any(_same(workflow, w.get("id")) or _same(workflow, w.get("name")) for w in flows):
        raise LookupError(f"no workflow {workflow!r} on this site (stack workflows lists them)")
    if status and status.strip().lower() not in RUN_STATES:
        raise ValueError(f"a run's state is one of {', '.join(RUN_STATES)}, not {status!r}")
    out = []
    for w in flows:
        if workflow and not (_same(workflow, w.get("id")) or _same(workflow, w.get("name"))):
            continue
        for r in w.get("runs") or []:
            if not status or _same(status, r.get("state")):
                out.append({"id": str(r.get("execution")), "workflow": w.get("name") or "", "workflow_id": str(w.get("id") or ""),
                            "state": r.get("state"), "on": r.get("on"), "started": r.get("started"), "ended": r.get("ended")})
    return sorted(out, key=lambda r: str(r["started"] or ""), reverse=True)


def ask_row(a):
    """An Ask as the command line and the agents get it: its chips without the links, and no figure of a private one."""
    private = a.get("sensitivity") == "private"
    return {"id": a.get("id"), "question": "A private question waits in the app." if private else a.get("question") or "",
            "kind": a.get("title") or a.get("kind") or "", "status": a.get("status"), "gate": bool(a.get("gate")),
            "role": a.get("role") or "owner", "people": a.get("people") or [], "private": private,
            "why": "" if private else a.get("why") or "", "facts": [] if private else a.get("facts") or [],
            "choices": [{"id": c.get("id"), "label": c.get("label")} for c in a.get("choices") or [] if not c.get("href")],
            "words": bool(a.get("allow_words")) and not a.get("gate"), "deadline": a.get("deadline"), "task": a.get("task") or ""}


def view_run(rid):
    """One run with its steps, the Asks it waits on and its place in n8n."""
    rid = str(rid or "").strip()
    for w in _flows():
        for r in w.get("runs") or []:
            if str(r.get("execution")) == rid:
                wid = str(w.get("id") or "")
                asks = [ask_row(a) for a in state().get("asks") or [] if str(a.get("task") or "") == f"n8n:{wid}/{rid}"
                        and a.get("status") in ASK_SHOWN + ("snoozed",)]
                return {"id": rid, "workflow": w.get("name") or "", "workflow_id": wid, "state": r.get("state"), "on": r.get("on"),
                        "started": r.get("started"), "ended": r.get("ended"),
                        "steps": [{k: s.get(k) for k in ("title", "kind", "agent", "job", "state", "started", "ended") if s.get(k) is not None}
                                  for s in r.get("steps") or []],
                        "asks": asks, "links": {"n8n": f"/n8n/workflow/{wid}/executions/{rid}"}}
    raise LookupError(f"no run {rid!r} among the newest runs of this site's workflows (stack runs lists them; n8n keeps the older ones)")


def view_agents():
    """The agents a step may name (the runner's step catalog) with every workflow that has a step with each."""
    try:
        cat = json.loads(STEP_CATALOG.read_text())
    except (OSError, ValueError):
        cat = {}
    used = {}
    for w in _flows():
        for a in w.get("agents") or []:
            used.setdefault(str(a), set()).add(w.get("name") or "")
    out = [{"id": str(a.get("id")), "name": a.get("name") or a.get("id"), "harness": a.get("harness") or "", "purpose": a.get("purpose") or "",
            "pack": a.get("pack") or "", "used_in": sorted(used.get(str(a.get("id")), ()))} for a in cat.get("agents") or [] if a.get("id")]
    known = {a["id"] for a in out}
    out += [{"id": a, "name": a, "harness": "", "purpose": "", "pack": "", "used_in": sorted(ws)} for a, ws in sorted(used.items()) if a not in known]
    return out


def view_asks(every=False):
    sts = ASK_SHOWN + (("snoozed",) if every else ())
    return [ask_row(a) for a in state().get("asks") or [] if a.get("status") in sts]


def find_ask(ref):
    """An open Ask by its id or its first characters (four or more, one Ask only)."""
    ref = str(ref or "").strip().lower()
    asks = [a for a in state().get("asks") or [] if a.get("status") in ASK_SHOWN + ("snoozed",)]
    hits = [a for a in asks if a.get("id") == ref] or ([a for a in asks if str(a.get("id")).startswith(ref)] if len(ref) >= 4 else [])
    if len(hits) == 1:
        return hits[0]
    if hits:
        raise LookupError(f"{ref!r} starts {len(hits)} Asks' ids; give more of it")
    raise LookupError(f"no open Ask {ref!r} (stack asks lists them)")


def answer_body(a, reply, via):
    """The ask_answer request for a reply to an Ask: one of its chips by id or label, else the words, for the interpreter.
    A gate and a private Ask are refused with the reason."""
    if a.get("gate"):
        raise PermissionError(GATE_NO.format(role=a.get("role") or "owner"))
    if a.get("sensitivity") == "private":
        raise PermissionError(PRIVATE_NO)
    reply = str(reply or "").strip()
    chips = [c for c in a.get("choices") or [] if not c.get("href")]
    if not reply:
        raise ValueError("say the answer: one of its choices (" + ", ".join(c["label"] for c in chips) + ") or a few words")
    body = {"action": "ask_answer", "id": a["id"], "answer_id": f"{via}-{uuid.uuid4().hex}"}
    hit = next((c for c in chips if reply.lower() in (str(c.get("id")).lower(), str(c.get("label")).lower())), None)
    if hit:
        body["outcome"] = hit["id"]
    elif a.get("allow_words"):
        body["words"] = reply
    else:
        raise ValueError("this question takes one of its choices: " + ", ".join(c["label"] for c in chips))
    return body


def stack_via(request, body):
    """WAY-03: who speaks through /api/request: the app, or the command line by its header (it only takes rights away).
    -> None, or (status, the refusal); the body gets its source, and the command line's its via."""
    body.pop("via", None)                              # never the page's word
    via = request.headers.get(STACK_VIA, "").strip().lower()
    if not via:
        body["source"] = "app"
        return None
    if via != "cli":
        return 400, f"unknown way in {via!r}: the app, or the command line (cli)"
    a = body.get("action")
    if a not in CLI_ACTIONS:
        return 403, (f"the command line does not do {a}: it starts runs, answers Asks that are no gate and asks for a pack's "
                     "approval; everything else is a tap in the app")
    if a == "ask_answer":
        for k in ("outcome", "words", "values", "always", "group", "answer_id"):
            body.pop(k, None)                          # the reply decides; a standing rule is the owner's, in the app
        try:
            body.update(answer_body(find_ask(body.get("id")), body.pop("reply", ""), "cli"))
        except PermissionError as e:
            return 403, str(e)
        except (LookupError, ValueError) as e:
            return 400, str(e)
    body["source"] = body["via"] = "cli"
    return None


def _err(e, status=400):
    return JSONResponse({"error": str(e)}, status_code=404 if isinstance(e, LookupError) else status)


async def api_stack_workflows(request):
    """WAY-01: the site's workflows for the command line: id, name, trigger, on or off, agents, last run."""
    return JSONResponse({"workflows": view_workflows()})


async def api_stack_runs(request):
    """WAY-01: the newest runs of the site's workflows, newest first (?workflow=<id or name>, ?status=running|waiting|done|failed)."""
    try:
        return JSONResponse({"runs": view_runs(request.query_params.get("workflow", ""), request.query_params.get("status", ""))})
    except (LookupError, ValueError) as e:
        return _err(e)


async def api_stack_run(request):
    """WAY-01: one run: its workflow, state, steps, the Asks it waits on and its place in n8n."""
    try:
        return JSONResponse(view_run(request.path_params["rid"]))
    except LookupError as e:
        return _err(e)


async def api_stack_agents(request):
    """WAY-01: the agents, each with what it does and every workflow that has a step with it."""
    return JSONResponse({"agents": view_agents()})


async def api_stack_asks(request):
    """WAY-02: the open Asks for the command line (?all=1: the put-off ones too); a private one shows no figure."""
    return JSONResponse({"asks": view_asks(request.query_params.get("all") in ("1", "true"))})


# ---------- MCP server "stack" (port 8100): the same, for agents (WAY-06) ----------
stack_mcp = MCPServer("stack")


def _out(x):
    return json.dumps(x, ensure_ascii=False, indent=1)


async def _act(req, wait=10.0):
    r = await submit({**req, "source": "mcp", "via": "mcp", "who": AGENT_LOGIN}, wait=wait)
    if r.get("pending"):
        return f"The runner has not answered yet (request {r['id']}); it does it as soon as it can. Do not send it again."
    return _out({k: v for k, v in r.items() if k != "ok"}) if r.get("ok") else f"Refused: {r.get('error') or 'unknown'}"


@stack_mcp.tool()
async def stack_workflows() -> str:
    """Every workflow on this site: its id, name, trigger (its schedule in words, "when called" or "on an event"), whether
    it is switched on, the agents its steps use and its last run. Use its id or name with stack_run and stack_runs."""
    return _out(view_workflows())


@stack_mcp.tool()
async def stack_agents() -> str:
    """The agents, the building blocks of workflows: id, harness, what each does, and every workflow that has a step with
    it (used_in). An agent runs only as a step of a workflow's run."""
    return _out(view_agents())


@stack_mcp.tool()
async def stack_runs(workflow: str = "", status: str = "") -> str:
    """The newest runs of this site's workflows, newest first: run id, workflow, state (running, waiting, done, failed),
    the step it is on and its times. workflow: an id or name to see one workflow's runs; status: one state."""
    try:
        return _out(view_runs(workflow, status))
    except (LookupError, ValueError) as e:
        return f"Refused: {e}"


@stack_mcp.tool()
async def stack_run_show(run: str) -> str:
    """One run by its id (from stack_runs): its workflow, state, each step (kind, agent, state, times), the Asks it waits
    on and its place in n8n's editor."""
    try:
        return _out(view_run(run))
    except LookupError as e:
        return f"Refused: {e}"


@stack_mcp.tool()
async def stack_run(workflow: str, inputs: dict[str, str] | None = None) -> str:
    """Start one run of a workflow now, through its Run now trigger, as the app's Run now does. workflow: its id or name
    (stack_workflows). inputs: name -> value pairs the run gets as its input. Refused while the stop switch is on, when
    the workflow is switched off or has no Run now trigger. It returns at once; the run shows in stack_runs when its
    first step reports."""
    return await _act({"action": "workflow_run", "workflow": workflow, "input": inputs or {}}, wait=20)


@stack_mcp.tool()
async def stack_asks() -> str:
    """The open Asks: the questions that wait for a person (Needs you in the app). Each with its id, question, choices,
    whether it is a gate and its role. A private Ask shows no figures: the owner answers it in the app."""
    return _out(view_asks())


@stack_mcp.tool()
async def stack_answer(ask: str, answer: str) -> str:
    """Answer one open Ask that is no gate, only with what the owner told you in this chat. ask: its id (or its first
    characters) from stack_asks. answer: one of its choices (id or label), or the owner's words, which the stack reads
    as with any answer in words. A gate is a tap in the app by a person in its role: it is always refused here, and so is
    a private Ask. The answer is held 15 s for the owner's undo in the app, then the stack acts on it."""
    try:
        body = answer_body(find_ask(ask), answer, "mcp")
    except (LookupError, ValueError, PermissionError) as e:
        return f"Refused: {e}"
    return await _act(body)


@stack_mcp.tool()
async def stack_pack_approve(pack: str, commit: str) -> str:
    """Ask for the approval of one commit of a pack this site names (its packs.txt): it opens a gate Ask in Needs you,
    which only a person in its role approves, by a tap in the app. You never approve a pack yourself. Says so when the
    commit is approved already, refused, or waiting."""
    return await _act({"action": "pack_ask", "name": pack, "commit": commit}, wait=60)


@stack_mcp.tool()
async def stack_doctor() -> str:
    """The site's doctor: what keeps this site from running as its deployment says (missing or unapproved packs,
    workflows no factory owns or not imported, a dead runner), each named. It changes nothing."""
    return await _act({"action": "stack_doctor"}, wait=120)
