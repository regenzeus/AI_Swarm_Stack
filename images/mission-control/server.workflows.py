# part of server.py (PLT-25; APP-71 to APP-73, the factory design's phase A): everything the stack does as workflows and
# runs, read-only. It runs in server.py's namespace where it stood (_part); not a module of its own.
#
# Two sources make one model:
# - the n8n workflows (the runner's view, public/workflows-runs.json, ops/flows_view.py): each with its diagram (nodes
#   and connections), its trigger, its AI Stack steps and its newest runs (n8n's executions);
# - the old sources that have no n8n workflow yet (requests in a sentence, Claude questions, chat requests, builds,
#   briefings and research): each shows as a run of the standard workflow it becomes in phase B (Request, Change,
#   Briefing), drawn from that template's diagram. The runner's records keep their pages (#/task/<id>); a run here
#   links to them for the whole history.
# Each workflow belongs to a factory: today one, home, and the platform's own Upkeep (a file's "factory" tag, else its
# area: upkeep is the platform's). Open Asks count per workflow from each Ask's task.

FACTORIES = {"home": "Home", "platform": "Platform"}
AREA_NAMES = {"taxes": "Taxes", "mail": "Mail", "briefings": "Briefings", "shopping": "Shopping", "research": "Research",
              "errands": "Errands", "inbox": "Inbox", "phone": "Phone", "code": "Code", "memory": "Memory",
              "upkeep": "Upkeep", "standard": "Standard workflows"}   # ops/areas.py, and the templates' own group
# The standard workflows (the factory design, section 4): each a template's diagram, its steps in order with the agent
# that does each where one does. A node's "state_of" is the old record's states that mean the run is at that step.
TEMPLATES = {
    "request": {"name": "Request", "trigger": "A request from you, a trigger or an agent", "nodes": [
        ("Understand", "intake", ("intake", "needs_answer")), ("Work out the steps", "planner", ("planning", "waiting_approval")),
        ("Do", "", ("planned", "running", "after", "queued")), ("Check", "judge", ()), ("Deliver", "", ("waiting_owner",))]},
    "change": {"name": "Change", "trigger": "A ticket, a finding or a request", "nodes": [
        ("Triage", "intake", ("intake",)), ("Specification", "", ("needs_answer", "planning")), ("Implement", "builder", ("planned", "running", "queued", "working")),
        ("Review", "reviewer", ("checking",)), ("Verify", "tester", ()), ("Ship", "", ("waiting_owner", "waiting_approval", "review")),
        ("Watch", "checker", ())], "asks": ("Specification", "Ship")},
    "briefing": {"name": "Briefing", "trigger": "On its schedule", "nodes": [
        ("Collect", "desk", ("intake", "planning", "planned")), ("Research", "scout", ("running", "queued")), ("Write", "desk", ()),
        ("Deliver", "", ("waiting_owner",))]},
}
OPEN_RUN = ("running", "waiting")
RUNS_PAGE = 60                                   # limit: drops, a workflow's page lists its 60 newest runs; their total is said, every older one keeps its own page


def wf_factory(area, tag=""):
    """-> the factory a workflow belongs to: its file's tag, else upkeep is the platform's and the rest is home's."""
    return tag if tag in FACTORIES else "platform" if area == "upkeep" else "home"


def template_of(t, missions):
    """-> which standard workflow an old record becomes: builds and changes are Change, briefings Briefing, the rest
    Request (a sentence, a Claude question, a chat request, research)."""
    door, kind = t.get("door"), t.get("kind") or ""
    if door == "build" or kind in ("change", "coding"):
        return "change"
    if kind == "briefing" or (door == "mission" and (missions.get(t.get("ref")) or {}).get("type") == "briefing"):
        return "briefing"
    return "request"


def run_state(status):
    """An old record's status as a run's: running, waiting (for you), done, failed or cancelled."""
    if status in ("needs_answer", "waiting_approval", "waiting_owner"):
        return "waiting"
    if status in ("done", "failed", "cancelled"):
        return status
    if status == "scheduled":
        return "done"
    return "running"


def asks_by_task(asks):
    out = {}
    for a in asks or []:
        if a.get("status") in ("open", "escalated") and a.get("task") is not None and not a.get("test"):
            out.setdefault(str(a["task"]), []).append(a)
    return out


def template_graph(key):
    """A standard workflow's diagram: its trigger, then its steps one after another."""
    tp = TEMPLATES[key]
    nodes = [{"name": tp["trigger"], "type": "trigger", "trigger": tp["trigger"], "at": [0, 0]}]
    for i, (name, agent, _) in enumerate(tp["nodes"]):
        n = {"name": name, "type": "aistackStep", "kind": "ask" if name in tp.get("asks", ()) else "agent", "title": name, "at": [260 * (i + 1), 0]}
        if agent:
            n["agent"] = agent
        nodes.append(n)
    edges = [[nodes[i]["name"], nodes[i + 1]["name"], 0] for i in range(len(nodes) - 1)]
    return {"nodes": nodes, "edges": edges}


def template_path(key, status):
    """-> {step name: state} of a run of a standard workflow from its record's status: the steps before the one it is
    at are done, that one runs (or waits for you, or failed), the rest have not run."""
    steps = [n for n, _, _ in TEMPLATES[key]["nodes"]]
    st = run_state(status)
    if st == "done":
        return {n: "done" for n in steps}
    at = next((i for i, (_, _, sts) in enumerate(TEMPLATES[key]["nodes"]) if status in sts), None)
    if at is None:
        at = len(steps) - 2 if st in ("failed", "cancelled") else 0
    out = {n: "done" for n in steps[:at]}
    out[steps[at]] = {"waiting": "waiting", "failed": "failed", "cancelled": "cancelled"}.get(st, "running")
    return out


def old_run(t, key, occ_run=None, asks=()):
    """One run of a standard workflow from an old record (t), or from one of its own runs (occ_run) when it repeats."""
    r = occ_run or {}
    status = r.get("status") or t.get("status")
    if occ_run and status == "ok":
        status = "done"
    rid = f"t{t['id']}" + (f".{r['occ']}" if occ_run and r.get("occ") else "")
    lr = t.get("last_run") or {}
    return {"id": rid, "workflow": key, "title": t.get("title") or "", "state": run_state(status),
            "started": r.get("started") or lr.get("started") or t.get("created"), "ended": r.get("ended") or (lr.get("ended") if not occ_run else None),
            "asked": t.get("asked") or "", "trigger": r.get("trigger") or "", "asks": len(asks), "result": r.get("result") or lr.get("summary") or t.get("error") or "",
            "cost": r.get("cost") if occ_run else t.get("cost"), "tokens": r.get("tokens") if occ_run else t.get("tokens"),
            "path": template_path(key, status), "task": t["id"], "occ": r.get("occ"), "href": f"#/task/{t['id']}" + (f"?o={r['occ']}" if occ_run and r.get("occ") else ""),
            "verdict": r.get("verdict") or t.get("verdict")}


def n8n_task(w, tasks):
    """The runner's record a workflow's runs are kept in: a scheduled job's, a request's own workflow's, or the workflow's own."""
    kind, _, key = (w.get("for") or "").partition(":")
    for t in tasks:
        if (kind == "crew" and t.get("door") == "crew" and t.get("ref") == key) or (kind == "task" and str(t.get("id")) == key) \
                or (t.get("door") == "flow" and t.get("workflow") in (w.get("id"), w.get("file"))):
            return t
    return None


SAME_RUN_S = 1800                                 # limit: drops, a record's run that started within 30 min of an n8n run is that run, not a second one
SAME_JOB_S = 120                                  # limit: drops, a scheduled job's run that started within 2 min of a run already listed is that run


def _ts(x):
    """An ISO time or epoch seconds -> epoch seconds (None when neither)."""
    if isinstance(x, (int, float)):
        return float(x)
    try:
        return dt.datetime.fromisoformat(str(x)).timestamp()
    except (TypeError, ValueError):
        return None


def _iso(x):
    t = _ts(x)
    return dt.datetime.fromtimestamp(t).astimezone().isoformat(timespec="seconds") if t is not None else None


def step_names(g):
    """{an AI Stack step's own title: the node's name}: the step service's records name a step by its title."""
    return {n.get("step_title") or n.get("title") or n["name"]: n.get("title") or n["name"] for n in (g or {}).get("nodes") or [] if n.get("type") == "aistackStep"}


def n8n_runs(w, t, asks=(), hist=(), g=None):
    """APP-80: a workflow's whole history, newest first, from every record that holds one: n8n's executions the step
    service saw (each with its steps), the record's own runs (a request's occurrences with their results, a chain's runs
    with their execution) and a scheduled job's run history; one run once, matched by its execution or its start."""
    names, one = step_names(g), [n.get("title") or n["name"] for n in (g or {}).get("nodes") or [] if n.get("type") == "aistackStep"]
    own = [r for r in (t or {}).get("runs") or [] if r.get("occ") or r.get("execution")]
    used, out = set(), []

    def mine(r):                                     # the record's run that is this n8n run: by its execution, else by its start
        ex = next((i for i, o in enumerate(own) if i not in used and o.get("execution") and str(o["execution"]) == str(r.get("execution"))), None)
        if ex is None:
            at = _ts(r.get("started"))
            ex = next((i for i, o in enumerate(own) if i not in used and not o.get("execution") and at is not None and _ts(o.get("started")) is not None
                       and abs(_ts(o.get("started")) - at) <= SAME_RUN_S), None)
        if ex is None:
            return {}
        used.add(ex)
        return own[ex]
    href = lambda rec: (f"#/task/{t['id']}" + (f"?o={rec['occ']}" if rec.get("occ") else "")) if t else ""   # noqa: E731
    for r in w.get("runs") or []:
        rec = mine(r)
        path = {names.get(s.get("title") or "", s.get("title") or ""): s.get("state") for s in r.get("steps") or []}
        out.append({"id": str(r.get("execution")), "workflow": w["id"], "title": w.get("name") or "", "state": r.get("state"),
                    "started": r.get("started"), "ended": r.get("ended"), "on": r.get("on"), "steps": r.get("steps") or [],
                    "path": path, "result": rec.get("result") or "", "verdict": rec.get("verdict"), "trigger": rec.get("trigger") or "n8n",
                    "asked": (t or {}).get("asked") or "stack", "asks": len(asks) if r.get("state") in OPEN_RUN else 0,
                    "task": (t or {}).get("id"), "occ": rec.get("occ"), "execution": str(r.get("execution")), "href": href(rec)})
    for i, rec in enumerate(own):                    # the record's runs n8n's view never saw (older ones, or before the watcher)
        if i in used:
            continue
        st = run_state("done" if rec.get("status") == "ok" else rec.get("status") or "done")
        out.append({"id": str(rec.get("execution") or f"o{rec.get('occ')}"), "workflow": w["id"], "title": w.get("name") or "", "state": st,
                    "started": rec.get("started"), "ended": rec.get("ended"), "steps": [], "path": {s: st for s in one} if len(one) == 1 else {},
                    "result": rec.get("result") or "", "verdict": rec.get("verdict"), "trigger": rec.get("trigger") or "schedule",
                    "asked": (t or {}).get("asked") or "stack", "asks": len(asks) if st in OPEN_RUN else 0, "task": (t or {}).get("id"),
                    "occ": rec.get("occ"), "execution": str(rec.get("execution") or ""), "href": href(rec), "cost": rec.get("cost"), "tokens": rec.get("tokens")})
    seen = [_ts(r["started"]) for r in out if _ts(r.get("started")) is not None]
    for h in hist or []:                             # a scheduled job's own run history (ops/crew.py, every run of its unit)
        at = _ts(h.get("start"))
        if at is None or any(abs(at - s) <= SAME_JOB_S for s in seen):
            continue
        st = {"ok": "done", "failed": "failed", "running": "running"}.get(h.get("state"), "done")
        out.append({"id": f"j{int(at)}", "workflow": w["id"], "title": w.get("name") or "", "state": st, "started": _iso(at), "ended": _iso(h.get("end")),
                    "steps": [], "path": {s: st for s in one} if len(one) == 1 else {}, "result": "", "trigger": "schedule", "asked": "stack",
                    "asks": 0, "task": None, "occ": None, "execution": "", "href": f"#/crew/{(w.get('for') or '')[5:]}"})
    out.sort(key=lambda r: _ts(r.get("started")) or 0, reverse=True)
    return out


def tidy_graph(g, w, t):
    """The diagram in the owner's words: a trigger by what it is ("On its schedule", not its cron), a step that holds a
    request's own steps by what it does (its workflow's name, or "Research and write" for a request in a sentence)."""
    g = json.loads(json.dumps(g or {"nodes": [], "edges": []}))
    for n in g.get("nodes") or []:
        if n.get("trigger") or n.get("type") in ("scheduleTrigger", "webhook", "manualTrigger"):
            n["title"] = re.sub(r"\s*\([^)]*\)\s*$", "", n.get("title") or n["name"]).strip() or n["name"]
        elif n.get("type") == "aistackStep" and re.match(r"(Crew|Task #\d+): ", n.get("title") or n["name"]) and n.get("kind") != "task":
            n["step_title"] = n.get("title") or n["name"]
            n["title"] = re.sub(r"^(Crew|Task #\d+): ", "", n["step_title"])   # a scheduled job's step by its job's name
        elif n.get("type") == "aistackStep" and n.get("kind") == "task":
            n["step_title"] = n.get("title") or n["name"]
            n["title"] = "Research and write" if (t or {}).get("door") == "plan" else wf_title(w, t)
            n["inside"] = True                       # its own steps run inside it until phase B moves them onto n8n
    return g


def wf_title(w, t):
    return (t or {}).get("title") or re.sub(r"^(Crew|Task #\d+): ", "", w.get("name") or "") or w.get("file") or w.get("id")


def wf_name(w, t, crew):
    """A workflow's name as the owner knows its work: a scheduled job's name, a request's or a chain's title, else n8n's."""
    kind, _, key = (w.get("for") or "").partition(":")
    if t and (kind == "task" or t.get("door") == "flow") and t.get("title"):
        return t["title"]                            # a chain of steps (the tax desk's first step is a job) is its record's
    c = next((c for c in crew if kind == "crew" and c.get("id") == key), None)
    if c and c.get("name"):
        return c["name"]
    return re.sub(r"^(Crew|Task #\d+): ", "", w.get("name") or "") or w.get("file") or w.get("id")   # a scheduled job not in the state yet


def crew_next(w, crew):
    kind, _, key = (w.get("for") or "").partition(":")
    c = next((c for c in crew if (kind == "crew" and c.get("id") == key) or c.get("workflow") == w.get("id")), None)
    return (c or {}).get("next")


def factory_model(st, wfv, hist=None):
    """-> (workflows, runs by workflow id): every workflow of the site, the n8n ones and the standard ones, each with its
    card's facts, and every run the app can show. hist: {scheduled job: its run history (ops/crew.py)}."""
    tasks, crew, hist = st.get("tasks") or [], st.get("crew") or [], hist or {}
    missions = {m.get("slug"): m for m in st.get("missions") or []}
    open_asks = asks_by_task(st.get("asks"))
    wfs, runs, owned = [], {}, set()
    for w in (wfv or {}).get("workflows") or []:
        t = n8n_task(w, tasks)
        if t:
            owned.add(t.get("id"))
        a = open_asks.get(str((t or {}).get("id")), [])
        kind, _, key = (w.get("for") or "").partition(":")
        name, g = wf_name(w, t, crew), tidy_graph(w.get("graph"), w, t)
        rs = n8n_runs({**w, "name": name}, t, a, hist.get(key) if kind == "crew" and (t or {}).get("door") in (None, "crew") else (), g)
        runs[w["id"]] = rs
        area = w.get("area") or (t or {}).get("area") or "research"
        last = rs[0] if rs else None
        lr = (t or {}).get("last_run") or {}
        said = next((r["result"] for r in rs if r.get("result")), "") or lr.get("summary") or ""
        c = next((c for c in crew if kind == "crew" and c.get("id") == key), None)
        wfs.append({"id": w["id"], "name": name,
                    "file": w.get("file") or "", "factory": wf_factory(area, w.get("factory")), "area": area, "source": "n8n",
                    "trigger": w.get("schedule") or "", "active": bool(w.get("active")), "graph": g,
                    "agents": sorted(set(w.get("agents") or []) | {s.get("agent") for s in [*((t or {}).get("plan") or []), *((t or {}).get("steps") or [])]
                                                                   if s.get("agent") and (t or {}).get("door") in ("plan", "flow")}),   # APP-84: a request's own steps' agents too
                    "jobs": w.get("crew") or [], "steps": w.get("steps") or [],
                    "last_run": {k: last.get(k) for k in ("id", "state", "started", "ended")} if last else
                    ({"id": "", "state": run_state(lr.get("status") if lr.get("status") != "ok" else "done"), "started": lr.get("started"), "ended": lr.get("ended")} if lr else None),
                    "next_run": (t or {}).get("next_run") or crew_next(w, crew), "asks": len(a),
                    "result": said or (c or {}).get("payoff") or "", "runs_total": max(len(rs), w.get("runs_total") or 0),
                    "page": f"#/task/{t['id']}" if t and t.get("door") != "crew" else f"#/crew/{key}" if kind == "crew" else "",
                    "result_view": (t or {}).get("result_view") or ""})
    std = {k: [] for k in TEMPLATES}
    for t in tasks:
        if t.get("id") in owned or t.get("door") in ("crew", "flow"):
            continue
        key = template_of(t, missions)
        a = open_asks.get(str(t.get("id")), [])
        own = [r for r in t.get("runs") or [] if r.get("occ")]
        if len(own) > 1:
            std[key] += [old_run(t, key, r, a if i == 0 else ()) for i, r in enumerate(sorted(own, key=lambda r: r.get("occ") or 0, reverse=True))]
        else:
            std[key].append(old_run(t, key, None, a))
    for key, tp in TEMPLATES.items():
        rs = sorted(std[key], key=lambda r: str(r.get("ended") or r.get("started") or ""), reverse=True)
        rs.sort(key=lambda r: r["state"] not in OPEN_RUN)                   # what is open first, then the newest
        runs[key] = rs
        last = rs[0] if rs else None
        wfs.append({"id": key, "name": tp["name"], "file": "", "factory": "home", "area": "standard", "source": "standard",
                    "trigger": tp["trigger"], "active": True, "graph": template_graph(key),
                    "agents": sorted({a for _, a, _ in tp["nodes"] if a}), "jobs": [], "steps": [],
                    "last_run": {k: last.get(k) for k in ("id", "state", "started", "ended")} if last else None,
                    "next_run": None, "asks": sum(r["asks"] for r in rs), "result": (last or {}).get("result") or "",
                    "runs_total": len(rs), "running": sum(r["state"] in OPEN_RUN for r in rs), "page": "", "result_view": ""})
    return wfs, runs


def factory_inputs():
    try:
        wfv = json.loads((STATE.parent / "workflows-runs.json").read_text())      # the runner's public folder
    except (OSError, ValueError):
        wfv = {"workflows": []}
    hist = {}
    for p in (STATE.parent.parent / "crew").glob("*.history.json"):   # each scheduled job's run history (ops/crew.py writes it)
        try:
            hist[p.name.removesuffix(".history.json")] = [{k: r.get(k) for k in ("start", "end", "state")} for r in json.loads(p.read_text()).get("runs") or []]
        except (OSError, ValueError, AttributeError):
            continue
    return state(), wfv, hist


async def api_factory(request):
    """APP-71: every workflow of the site, grouped by factory and area on the page, each with its card's facts."""
    wfs, _ = factory_model(*factory_inputs())
    return JSONResponse({"factories": FACTORIES, "areas": AREA_NAMES, "workflows": wfs})


async def api_factory_workflow(request):
    """APP-72: one workflow's page: its card, its diagram, its runs (newest first) and its agents."""
    wid = request.path_params["wid"]
    wfs, runs = factory_model(*factory_inputs())
    w = next((x for x in wfs if x["id"] == wid or (x.get("file") and x["file"] == wid)), None)
    if not w:
        return JSONResponse({"error": "no such workflow"}, status_code=404)
    rs = runs.get(w["id"], [])
    return JSONResponse({"workflow": w, "runs": rs[:RUNS_PAGE], "runs_total": len(rs)})   # cap: list, RUNS_PAGE above; runs_total counts every one


async def api_factory_run(request):
    """APP-73: one run's page: its workflow with the diagram, the path it took, its steps, its Asks and its result."""
    wid, rid = request.path_params["wid"], request.path_params["rid"]
    st, wfv, hist = factory_inputs()
    wfs, runs = factory_model(st, wfv, hist)
    w = next((x for x in wfs if x["id"] == wid or (x.get("file") and x["file"] == wid)), None)
    r = next((x for x in runs.get((w or {}).get("id"), []) if x["id"] == rid), None) if w else None
    if not r:
        return JSONResponse({"error": "no such run"}, status_code=404)
    asks = [a for a in st.get("asks") or [] if r.get("task") is not None and str(a.get("task")) == str(r["task"]) and not a.get("test")]
    return JSONResponse({"workflow": w, "run": r, "asks": asks})


N8N_TRIGGERS = ("n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.webhook", "n8n-nodes-base.manualTrigger")


def canvas_of(d, schedule=""):
    """APP-86: what n8n's read-only canvas draws: the published version (what runs; the draft when none is published), its
    triggers named by what they are ("On its schedule · Mondays 08:00", never the cron), connections renamed with them."""
    pub = d.get("activeVersion") if d.get("activeVersionId") and isinstance(d.get("activeVersion"), dict) else None
    nodes = json.loads(json.dumps((pub or d).get("nodes") or []))
    conns = json.loads(json.dumps((pub or d).get("connections") or {}))
    taken, rename = {n.get("name") for n in nodes}, {}
    for n in nodes:
        t = str(n.get("type") or "")
        if t in N8N_TRIGGERS or t.lower().endswith("trigger"):
            new = re.sub(r"\s*\([^)]*\)\s*$", "", n["name"]).strip() or n["name"]
            if t == "n8n-nodes-base.scheduleTrigger" and schedule and schedule not in new:
                new = f"{new} · {schedule}"
            while new != n["name"] and new in taken:
                new += " ·"
            if new != n["name"]:
                taken.add(new)
                rename[n["name"]] = new
                n["name"] = new
    conns = {rename.get(a, a): {k: [[{**c, "node": rename.get(c.get("node"), c.get("node"))} for c in outs or []] for outs in v or []]
                                for k, v in (out or {}).items()} for a, out in conns.items()}
    return {"workflow": {"id": d.get("id"), "name": d.get("name"), "nodes": nodes, "connections": conns, "settings": d.get("settings") or {}},
            "published": bool(pub), "draft_differs": bool(pub) and d.get("versionId") != d.get("activeVersionId")}


async def api_factory_canvas(request):
    """APP-86: a workflow for n8n's read-only canvas, read from n8n with the app's own session (APP-85), the owner's only."""
    wid = request.path_params["wid"]
    if not n8n_owner(request) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", wid):
        return JSONResponse({"error": "n8n's canvas shows to you, signed in", "fallback": True}, status_code=403)
    if not await n8n_login():
        return JSONResponse({"error": "n8n needs its login once: run make n8n-login on the PC", "fallback": True, "login": True}, status_code=503)
    for attempt in (0, 1):
        c = _frame_client("n8n")
        try:
            r = await c.get(f"/rest/workflows/{wid}", headers=n8n_with_session([]))
        except httpx.HTTPError as e:
            return JSONResponse({"error": f"n8n is not reachable ({type(e).__name__})", "fallback": True}, status_code=502)
        finally:
            await c.aclose()
        if r.status_code == 401 and attempt == 0 and await n8n_login(force=True):
            continue
        break
    if r.status_code != 200:
        return JSONResponse({"error": f"n8n has no such workflow ({r.status_code})", "fallback": True}, status_code=404)
    wfs, _ = factory_model(*factory_inputs())
    w = next((x for x in wfs if x["id"] == wid), {})
    return JSONResponse(canvas_of(r.json().get("data") or {}, w.get("trigger") or ""), headers={"Cache-Control": "no-store"})


FACTORY_ROUTES = [Route("/api/factory", api_factory), Route("/api/factory/workflow/{wid}", api_factory_workflow),
                  Route("/api/factory/workflow/{wid}/canvas", api_factory_canvas), Route("/api/factory/run/{wid}/{rid}", api_factory_run)]
