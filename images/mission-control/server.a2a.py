# A part of server.py (PLT-25): outside agents over A2A. It runs in server.py's namespace where it stood (_part); not a module of its own.
# ---------- TSK-19: outside agents over A2A (ops/a2a.py), on the tailnet, off until the owner switches it on ----------
A2A_STATE = {"submitted": "submitted", "intake": "submitted", "planning": "working", "after": "submitted", "needs_answer": "input-required",
             "waiting_approval": "input-required", "running": "working", "scheduled": "working", "waiting_owner": "input-required",
             "done": "completed", "failed": "failed", "cancelled": "canceled"}
A2A_PER_HOUR = 10                                  # tasks one outside agent may give in an hour
A2A_CHARS = 4000                                   # limit: refuses (an outside agent's task text, whole or not at all; the runner's own limit)
NOTE_CHARS = 2000                                  # limit: refuses (a memory note from an agent; the write gate reads it whole)


def a2a_conf():
    try:
        d = json.loads((DATA / "a2a.json").read_text())
    except (OSError, ValueError):
        d = {}
    return {"enabled": bool(d.get("enabled")), "agents": d.get("agents") or {}}


def a2a_agent(request, conf):
    """The outside agent whose bearer token this is, or None."""
    import hashlib
    import hmac
    tok = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not tok:
        return None
    h = hashlib.sha256(tok.encode()).hexdigest()
    return next((n for n, a in conf["agents"].items() if hmac.compare_digest(str(a.get("hash", "")), h)), None)


def a2a_task(t):
    """A task on the board -> an A2A Task object (its answer as an artifact once it is done)."""
    st = A2A_STATE.get(t.get("status"), "working")
    note = "waits for the owner's OK" if st == "input-required" else t.get("error") or ""
    out = {"kind": "task", "id": f"task-{t['id']}", "contextId": f"task-{t['id']}",
           "status": {"state": st, "timestamp": t.get("updated"), **({"message": {"role": "agent", "parts": [{"kind": "text", "text": note}]}} if note else {})}}
    if st == "completed" and t.get("result"):
        try:
            text = TC.fit((VAULT / t["result"]).read_text(), 40000)   # cap: api (the answer; the vault keeps all of it)
            out["artifacts"] = [{"artifactId": "answer", "name": t.get("title") or "answer", "parts": [{"kind": "text", "text": text}]}]
        except OSError:
            pass
    return out


async def a2a_card(request):
    """The stack's A2A agent card, for agents on the tailnet, while A2A is on."""
    if not a2a_conf()["enabled"] or not request.headers.get("tailscale-user-login"):
        return JSONResponse({"error": "not found"}, status_code=404)
    base = f"https://{request.headers.get('host', '')}"
    return JSONResponse({"protocolVersion": "1.0", "name": "AI stack", "version": "1", "url": f"{base}/a2a", "preferredTransport": "JSONRPC",
                         "description": "Give the stack a task in a sentence. Every task from outside waits for its owner's OK, then the stack plans and does it.",
                         "capabilities": {"streaming": False, "pushNotifications": False}, "defaultInputModes": ["text/plain"], "defaultOutputModes": ["text/plain"],
                         "skills": [{"id": "task", "name": "A task for the stack", "description": "Research, a briefing, an analysis: one sentence.",
                                     "tags": ["research", "briefing", "analysis"], "examples": ["Find what changed in the newest Python release"]}],
                         "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}, "security": [{"bearer": []}]})


async def api_a2a(request):
    """TSK-19: A2A JSON-RPC (message/send, tasks/get, tasks/cancel; the 1.0 names too) from an outside agent on the tailnet
    with its token. A message becomes a task (source a2a:<name>) that waits for the owner's OK; an agent sees only its own."""
    conf = a2a_conf()
    if not conf["enabled"]:
        return JSONResponse({"error": "A2A is off"}, status_code=404)
    if not request.headers.get("tailscale-user-login"):
        return JSONResponse({"error": "only reachable through Tailscale"}, status_code=403)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, status_code=400)
    rid, method, params = body.get("id"), str(body.get("method") or ""), body.get("params") or {}
    err = lambda code, msg, status=200: JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}}, status_code=status)
    name = a2a_agent(request, conf)
    if not name:
        return err(-32001, "no valid token for an outside agent", 401)
    mine = [t for t in state().get("tasks") or [] if t.get("source") == f"a2a:{name}"]
    if method in ("message/send", "SendMessage"):
        parts = (params.get("message") or {}).get("parts") or []
        text = " ".join(str(p.get("text") or "") for p in parts if p.get("kind", p.get("type", "text")) == "text").strip()
        if len(text) > A2A_CHARS:                        # limit: refuses (never stored or acted on in part: DEC-27, review APP-R11)
            return err(-32602, f"the task is {len(text):,} characters; send it in at most {A2A_CHARS:,}, or put the rest in a file it names")
        if len(text) < 8:
            return err(-32602, "send the task as a text part of at least a few words")
        hour_ago = (dt.datetime.now().astimezone() - dt.timedelta(hours=1)).isoformat()
        if sum(1 for t in mine if (t.get("created") or "") >= hour_ago) >= A2A_PER_HOUR:
            return err(-32002, f"at most {A2A_PER_HOUR} tasks an hour from one outside agent")
        r = await submit({"action": "task_create", "text": text, "autonomy": "ask", "source": f"a2a:{name}"}, wait=10)
        tid = r.get("task") if r.get("ok") else None        # the runner answers {"ok": true, **result} (ops/missions.py)
        if not tid:
            return err(-32603, r.get("error") or "the stack did not take the task in time; send it again")
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"kind": "task", "id": f"task-{tid}", "contextId": f"task-{tid}",
                                                                      "status": {"state": "submitted", "message": {"role": "agent", "parts": [
                                                                          {"kind": "text", "text": "taken: it waits for the owner's OK"}]}}}})
    if method in ("tasks/get", "GetTask", "tasks/cancel", "CancelTask"):
        m = re.fullmatch(r"task-(\d+)", str(params.get("id") or ""))
        t = next((x for x in mine if m and x["id"] == int(m.group(1))), None)
        if not t:
            return err(-32001, "no such task of this agent")
        if method in ("tasks/cancel", "CancelTask"):
            r = await submit({"action": "task_cancel", "id": t["id"], "source": f"a2a:{name}"}, wait=8)
            if not r.get("ok"):
                return err(-32002, r.get("error") or "it cannot be cancelled now")
            t = {**t, "status": "cancelled"}
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": a2a_task(t)})
    return err(-32601, f"no method {method}")


async def api_a2a_token(request):
    """The owner adds an outside agent: its token is made here and shown once; the runner keeps only its hash."""
    import hashlib
    import secrets
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    body = await request.json()
    tok = secrets.token_urlsafe(32)
    r = await submit({"action": "a2a_token", "name": str(body.get("name") or ""), "hash": hashlib.sha256(tok.encode()).hexdigest(),
                      "source": "app", "by": request.headers.get("tailscale-user-login", "")})
    if not r.get("ok"):
        return JSONResponse({"ok": False, "error": r.get("error") or "the runner did not answer"}, status_code=400)
    return JSONResponse({"ok": True, "name": r.get("name") or str(body.get("name") or ""), "token": tok, "card": f"https://{request.headers.get('host', '')}/.well-known/agent-card.json"})


PROV_READ = ("page", "item", "job", "note", "memory", "search")    # what a step used (provenance.READ, and its searches)


def task_prov(tid, occ):
    """APP-36: one run's sources and what it made, from its swarm map (public/maps/<task>.<occ>.json, ops/provenance.py):
    {sources: [{id, kind, title, uri, site, cited, steps, agents}], made: [...], numbers, by_agent: {agent: {cost, models}}}."""
    f = MAPS / f"{tid}.{occ}.json"
    if not occ or not f.exists():
        return None
    m = json.loads(f.read_text())
    arts = {a["id"]: a for a in m.get("artifacts") or []}
    step_agent = {s["idx"]: s["agent"] for s in m.get("steps") or []}
    run_agent = {x["run"]: x["agent"] for x in m.get("lanes") or []}
    used, made, cited = {}, {}, set()
    for x in m.get("links") or []:
        a = arts.get(x["artifact"])
        if not a:
            continue
        if x["rel"] == "cited":
            cited.add(a["id"])
            continue
        if x["rel"] not in ("used", "generated") or (x["rel"] == "used" and a["kind"] not in PROV_READ):
            continue
        y = (used if x["rel"] == "used" else made).setdefault(a["id"], {**a, "steps": set(), "agents": set()})
        if x["step"]:
            y["steps"].add(x["step"])
        who = run_agent.get(x["run"]) or step_agent.get(x["step"])
        if who:
            y["agents"].add(who)
    by_agent = {}
    for x in m.get("lanes") or []:
        b = by_agent.setdefault(x["agent"], {"cost": 0.0, "models": set()})
        b["cost"] += x.get("cost") or 0
        b["models"] |= set(x.get("models") or [])
    flat = lambda d: [{**v, "steps": sorted(v["steps"]), "agents": sorted(v["agents"]), "cited": v["id"] in cited} for v in d.values()]
    return {"sources": flat(used), "made": flat(made), "numbers": m.get("numbers") or {},
            "by_agent": {k: {"cost": round(v["cost"], 6), "models": sorted(v["models"])} for k, v in by_agent.items()}}


def task_page(tid, occ=None):
    """The task's data (the runner's file) with one run's activity, answer, sources and what it made: the run asked for,
    else its newest (APP-36); a task with one run shows everything it did."""
    f = TASK_PAGES / f"{tid}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    runs = d.get("runs") or []
    occ = occ if any(r["occ"] == occ for r in runs) else (runs[0]["occ"] if runs else None)
    run = next((r for r in runs if r["occ"] == occ), None)
    try:
        since = dt.datetime.fromisoformat(d.get("created") or "").timestamp()
    except ValueError:
        since = None
    d["occ"] = occ
    if d.get("door") == "flow":                        # TAX-09: its agent steps ran as the step service's tasks of each run
        held = [x for r in runs if len(runs) == 1 or r["occ"] == occ for x in r.get("tasks") or []]
        d["activity"] = RT.task_activity(tid, door="flow", ref=held)
        return d
    d["activity"] = RT.task_activity(tid, door=d.get("door"), ref=d.get("ref"), since=since, occ=occ if len(runs) > 1 else None)
    d["prov"] = task_prov(tid, occ)
    result = (run or {}).get("result") if str((run or {}).get("result") or "").startswith("tasks/") else d.get("result")
    res = VAULT / (result or "")
    d["result"] = result
    d["answer"] = res.read_text(errors="replace") if result and res.is_file() else None
    return d


async def api_task(request):
    """APP-35: one task's page: the task, its runs and their steps (the runner's file), the agents that worked on it, their
    actions and what they read from and kept in memory (the run record), and its answer."""
    try:
        tid = int(request.path_params["tid"])
        occ = int(request.query_params.get("o") or 0) or None
    except ValueError:
        return JSONResponse({"error": "no such task"}, status_code=400)
    d = await asyncio.to_thread(task_page, tid, occ)
    if d is None:
        return JSONResponse({"error": f"There is no task #{tid}."}, status_code=404)
    return JSONResponse(d)


NET_DAYS = (1, 7, 30, 90)                              # the Network's periods (the run record keeps 90 days)


async def api_task_network(request):
    """TSK-43: who works on which task (the Tasks tab's Network and the agents on each task's row), from the run
    record and the board's tasks."""
    d = request.query_params.get("days", "7")
    days = int(d) if d.isdigit() and int(d) in NET_DAYS else 7
    try:
        tasks = json.loads(STATE.read_text()).get("tasks") or []
    except (OSError, ValueError):
        tasks = []
    return JSONResponse(await asyncio.to_thread(RT.network, tasks, days))


async def api_idea_origins(request):
    """AI Change Requests, step 1: where each idea came from: its first run and agent (the Ledger's evidence), how many
    runs saw it, and the task that run belongs to (the run record), for the idea, its task's page and the Network."""
    def go():
        rows = (_swarm_app("origins", {"kind": "idea"}) or {}).get("result") or []
        try:
            tasks = json.loads(STATE.read_text()).get("tasks") or []
        except (OSError, ValueError):
            tasks = []
        of = RT.tasks_of_runs([r["first_run"] for r in rows if r.get("first_run")], tasks)
        duty = {t.get("ref"): t["id"] for t in tasks if t.get("door") == "crew"}     # an idea no run recorded (the weekly self-review's): its writer's duty
        try:                                          # ACR-02: the Editor's sorting, on each idea
            ed = json.loads((M / "crew" / "editor.json").read_text())
        except (OSError, ValueError):
            ed = {}
        verdicts = ed.get("verdicts") or {}
        return {"ideas": [{**r, "task": of.get(r.get("first_run")) or duty.get(r.get("owner")), "by_duty": not of.get(r.get("first_run")),
                           "editor": verdicts.get(str(r["id"]))} for r in rows],
                "editor": {"at": ed.get("sorted_at"), "requests": ed.get("requests") or [], "missing": ed.get("missing") or [], "result": ed.get("result")}}
    try:
        return JSONResponse(await asyncio.to_thread(go))
    except Exception as e:                            # the swarm asleep: the pages show no origins, and say nothing wrong
        return JSONResponse({"ideas": [], "error": f"the swarm is not reachable ({type(e).__name__})"})


async def api_usage(request):
    """How much each subscription carried in the last 5 and 24 hours (runrecord.usage)."""
    return JSONResponse(await asyncio.to_thread(RT.usage))


async def api_trials(request):
    """TRL-09: the trial scoreboard as the runner wrote it (ops/trials.py publish)."""
    f = M / "public/trials.json"
    return PlainTextResponse(f.read_text(), media_type="application/json") if f.exists() else JSONResponse({"trials": {}, "runs": []})


async def api_agent_tasks(request):
    """APP-35: the tasks an agent worked on, newest first, with their titles and states."""
    rows = await asyncio.to_thread(RT.agent_tasks, request.path_params["aid"])
    out = []
    for r in rows:
        f = TASK_PAGES / f"{r['task']}.json"
        t = json.loads(f.read_text()) if f.exists() else {}
        out.append({**r, "title": t.get("title") or f"Task #{r['task']}", "status": t.get("status"), "verdict": t.get("verdict")})
    return JSONResponse(out)


async def api_task_map(request):
    """TSK-24: a task run's swarm map as the runner wrote it (public/maps/<task>.<occ>.json, ops/provenance.py); the
    task's newest run when no run is named."""
    try:
        t, o = int(request.query_params.get("t", "")), request.query_params.get("o")
        d = MAPS
        f = d / f"{t}.{int(o)}.json" if o else max(d.glob(f"{t}.*.json"), key=lambda p: int(p.name.split(".")[1]), default=None)
    except ValueError:
        return JSONResponse({"error": "no such task run"}, status_code=400)
    if not f or not f.exists():
        return JSONResponse({"error": "This run has no map yet: it is drawn from its first step on."}, status_code=404)
    return PlainTextResponse(f.read_text(), media_type="application/json")


async def api_wiki_map(request):
    """MEM-09: the top layer of the wikis: every wiki as a bubble (pages, links, pages changed in 7 days, who writes it)
    and the subjects two or more of them share (a page with the same title or alias), so you see how they connect."""
    week = time.time() - 7 * 86400
    nodes, where = [], {}
    for r in wiki_roots():
        if r["archived"] or r.get("repo"):
            continue                                     # an archived mission's wiki is in the list, not on the map (FND-61)
        w = wiki(r["root"])
        pages = [p for pid, p in w["pages"].items() if pid != "index"]
        changed = sum((VAULT / r["root"] / f"{p['id']}.md").stat().st_mtime > week for p in pages if (VAULT / r["root"] / f"{p['id']}.md").exists())
        nodes.append({**r, "pages": len(pages), "links": sum(len(v) for v in w["links"].values()), "changed_7d": changed,
                      "writer": f"mission:{r['mission']}" if r.get("mission") else "curator"})
        for p in pages:
            if p["meta"].get("librarian") or p["meta"].get("merged_into"):
                continue                                 # a hub joins the wikis and a merged page's stub points on: no subjects of their own
            for n in {subject(x) for x in [p["title"], *p["aliases"]]} - {""}:
                where.setdefault(n, {}).setdefault(r["root"], p["title"])
    shared = {n: v for n, v in where.items() if len(v) > 1}
    edges = {}
    for n, v in shared.items():
        rs = sorted(v)
        for i, a in enumerate(rs):
            for b in rs[i + 1:]:
                edges.setdefault((a, b), []).append(v[a])
    return JSONResponse({"nodes": nodes, "edges": [{"a": a, "b": b, "subjects": sorted(set(s))} for (a, b), s in sorted(edges.items())],
                         "shared": [dict(t) for t in dict.fromkeys(tuple({"subject": v[sorted(v)[0]], "wikis": tuple(sorted(v))}.items())
                                                                   for n, v in sorted(shared.items()))]})   # one row per title and wikis


async def api_wiki_access(request):
    """MEM-10: who read and wrote which wiki in the window (runrecord.wiki_access), at most 30 days."""
    return JSONResponse(await asyncio.to_thread(RT.wiki_access, _hours(request, 168, 720)))


async def api_wiki_graph(request):
    """One wiki's pages and links, for its graph."""
    root = request.query_params.get("root", "")
    if not root_ok(root):
        return JSONResponse({"error": "unknown wiki"}, status_code=404)
    w = wiki(root)
    nodes = [{k: p[k] for k in ("id", "title", "type", "summary", "folder")} | {"degree": len(w["links"][p["id"]]) + len(w["back"].get(p["id"], ())),
                                                                              "stale": bool(p["meta"].get("reverify"))}
             for p in w["pages"].values() if p["id"] != "index"]
    edges = [{"source": a, "target": b} for a, bs in w["links"].items() for b in bs if a != "index" and b != "index"]
    return JSONResponse({"nodes": nodes, "links": edges})


async def api_wiki_page(request):
    """One wiki page with its rendered text, links and backlinks."""
    root, pid = request.query_params.get("root", ""), request.query_params.get("id", "")
    if not root_ok(root):
        return JSONResponse({"error": "unknown wiki"}, status_code=404)
    w = wiki(root)
    p = w["pages"].get(pid)
    if not p:
        return JSONResponse({"error": "no such page"}, status_code=404)
    resolved = {}
    for mm in LINK.finditer(p["body"]):
        kind, ref = w["resolve"](mm.group(1))
        resolved[mm.group(1)] = {"kind": kind, "ref": ref}
    meta = {k: v for k, v in p["meta"].items() if isinstance(v, (str, int, float, list)) and k != "qmd"}
    back = [{"id": b, "title": w["pages"][b]["title"]} for b in sorted(w["back"].get(pid, ())) if b in w["pages"]]
    return JSONResponse({"id": pid, "title": p["title"], "type": p["type"], "meta": meta, "body": p["body"], "links": resolved,
                         "backlinks": back, "path": f"{root}/{pid}.md", "markdown": p["markdown"]})


async def api_wiki_search_all(request):
    """APP-48: pages of every wiki whose title or text contains the search text, the best first."""
    q = request.query_params.get("q", "").strip().lower()
    if len(q) < 2:
        return JSONResponse([])
    hits = []
    for r in wiki_roots():
        if r.get("archived"):
            continue
        for p in wiki(r["root"])["pages"].values():
            txt = f"{p['title']}\n{p['summary']}\n{p['body']}".lower()
            if q in txt:
                hits.append({"root": r["root"], "wiki": r.get("title") or r["root"], "id": p["id"], "title": p["title"], "score": (q in p["title"].lower()) * 10 + txt.count(q)})
    return JSONResponse(sorted(hits, key=lambda h: -h["score"])[:20])  # cap: list (the 20 best pages; a narrower search finds the rest)


async def api_wiki_search(request):
    """Pages of one wiki whose title, summary or text contains the search text."""
    root, q = request.query_params.get("root", ""), request.query_params.get("q", "").strip().lower()
    if not root_ok(root) or len(q) < 2:
        return JSONResponse([])
    hits = []
    for p in wiki(root)["pages"].values():
        txt = f"{p['title']}\n{p['summary']}\n{p['body']}".lower()
        if q in txt:
            i = txt.find(q)
            hits.append({"id": p["id"], "title": p["title"], "score": (q in p["title"].lower()) * 10 + txt.count(q),
                         "snippet": re.sub(r"\s+", " ", txt[max(0, i - 60):i + 100])})
    return JSONResponse(sorted(hits, key=lambda h: -h["score"])[:30])  # cap: list (the 30 best hits; a narrower search finds the rest)
