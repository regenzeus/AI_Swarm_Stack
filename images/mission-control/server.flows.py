# part of server.py (WFL-05, docs/N8N-MIGRATION.md §3.2): the step service n8n calls. Port 8099, never published and
# reached only on the stepnet network, which n8n and this app alone share. A step is dropped for the runner as
# /missions/flows/pending/<id>.json, as the owner's actions go through the inbox (SEC-12); the runner checks it, runs it
# (ops/flows.py) and posts the answer to the n8n execution that waits for it. GET /steps/<id> answers what is known.
# GET /catalog gives the node's pickers their lists (WFL-06): agents, crew jobs, places, repositories and the kinds, as
# the runner writes them every minute (public/step-catalog.json; only the runner reads the packs and the places' workers).
from starlette.middleware.trustedhost import TrustedHostMiddleware

FLOWS = M / "flows"
STEP_CATALOG = M / "public/step-catalog.json"
STEP_MAX = 30000                                      # limit: refuses, a step request is its fields and a brief, not a document


async def steps_post(request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "no JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "the step must be a JSON object"}, status_code=400)
    if (n := len(json.dumps(body))) > STEP_MAX:
        return JSONResponse({"ok": False, "error": f"the step is {n:,} characters; the limit is {STEP_MAX:,}"}, status_code=400)
    rid = uuid.uuid4().hex[:16]
    pend = FLOWS / "pending"
    pend.mkdir(parents=True, exist_ok=True)
    tmp = pend / f".{rid}.tmp"
    tmp.write_text(json.dumps(body, ensure_ascii=False))
    tmp.rename(pend / f"{rid}.json")
    return JSONResponse({"ok": True, "id": rid, "status": "pending"})


async def steps_get(request):
    rid = request.path_params["rid"]
    if not re.fullmatch(r"[0-9a-f]{16}", rid):
        return JSONResponse({"ok": False, "error": "no such step"}, status_code=404)
    done = FLOWS / "done" / f"{rid}.json"
    try:
        return JSONResponse({"ok": True, "id": rid, **json.loads(done.read_text())})
    except (OSError, ValueError):                    # none yet, or one cut short: the runner handles the step again
        pass
    if (FLOWS / "pending" / f"{rid}.json").exists():
        return JSONResponse({"ok": True, "id": rid, "status": "pending"})
    return JSONResponse({"ok": False, "error": "no such step"}, status_code=404)


async def catalog_get(request):
    try:
        return JSONResponse({"ok": True, **json.loads(STEP_CATALOG.read_text())})
    except (OSError, ValueError):
        return JSONResponse({"ok": False, "error": "the runner has not written the lists yet (it does every minute)",
                             "kinds": [], "agents": [], "crew": [], "places": [], "repos": []})


flows_app = Starlette(routes=[Route("/steps", steps_post, methods=["POST"]), Route("/steps/{rid}", steps_get), Route("/catalog", catalog_get)],
                      middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=["mission-control"])])   # only by service name
