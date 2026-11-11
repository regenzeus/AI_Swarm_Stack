# part of server.py (WFL-14, APP-66): the stack's tools inside the app. A tool whose web UI can live under a sub-path is
# served under the app's own address, behind the app's front door (TailnetOnly: the owner's Tailscale login, or this PC
# without a tailnet (WFL-16), and no write from another site), so the app's pages show it in a frame instead of a tab of its own:
#   /n8n/     n8n (N8N_PATH=/n8n/, compose/core.yaml): the Workflows page, a task's Where it runs
#   /phoenix/ Phoenix (PHOENIX_HOST_ROOT_PATH=/phoenix): the Traces page, a step log's "Open in Phoenix"
# Each tool answers at its root and only names the prefix in its pages, so the prefix is taken off on the way in.
# Everything streams both ways (n8n's live updates are one long answer, Phoenix's bundles are large). The tool's own
# framing rule gives way to the app's: only the app's own pages may frame it. A tool's own login stays (n8n's).
# The others in tools.json open in their own tab: their pages ask for /assets/... at the root and none takes a sub-path.
from starlette.background import BackgroundTask

FRAMES = {"n8n": os.environ.get("N8N_URL", "http://n8n:5678"),          # on the stepnet network, which only n8n and this app share
          "phoenix": PHOENIX}                                         # on the obs network
FRAME_HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "te", "trailer", "upgrade", "host", "content-length"}
FRAME_SET_IN = {"x-forwarded-host", "x-forwarded-proto"}   # the app says these itself
FRAME_DROP_OUT = FRAME_HOP | {"x-frame-options", "content-security-policy"}   # framing: the app's own pages only (set below)
FRAME_RULE = "frame-ancestors 'self'"
# Pages a workflow writes itself (a webhook's answer, a form) run in a sandbox: on this origin they would otherwise have the
# app's whole API (review 10 Nov, SEC2-R4/APP2-R2). n8n's own form and webhook port (8450) is not this origin.
FRAME_SANDBOXED = ("/webhook", "/form")


def frame_csp(tool_csp, path):
    """The tool's own Content-Security-Policy stays, all but its framing rule, which becomes the app's; a page a workflow
    wrote is sandboxed too. Dropping the tool's policy whole took its own protection away."""
    kept = [d.strip() for d in (tool_csp or "").split(";") if d.strip() and not d.strip().lower().startswith("frame-ancestors")]
    if path.startswith(FRAME_SANDBOXED):
        kept.append("sandbox allow-forms")
    return "; ".join(kept + [FRAME_RULE])
FRAME_CONNECT_TIMEOUT = 10                            # limit: stops, a tool that does not take the connection within 10 s is reported as not reachable
_frame_transport = None                               # tests put a fake tool here


def _frame_client(name):
    # no read limit: a request the tool accepted takes as long as it needs; n8n's live updates are one answer that never ends
    return httpx.AsyncClient(base_url=FRAMES[name], timeout=httpx.Timeout(None, connect=FRAME_CONNECT_TIMEOUT), transport=_frame_transport, follow_redirects=False)


def frame_headers_in(request):
    """What the browser sent, for the tool: its cookies, the tool's own headers (n8n's browser-id, push-ref), the body's
    type and encoding; never the Tailscale identity headers. The address the browser used goes along, so a tool checks a
    live update's origin against it."""
    out = [(k, v) for k, v in request.headers.items()
           if k.lower() not in FRAME_HOP | FRAME_SET_IN and not k.lower().startswith("tailscale-")]
    if "accept-encoding" not in request.headers:       # httpx would ask for gzip itself; the browser gets what it asked for
        out.append(("accept-encoding", "identity"))
    host = request.headers.get("host", "")
    if host:
        out += [("host", host), ("x-forwarded-host", host)]
    return out + [("x-forwarded-proto", "http" if APP_GATE == "local" else "https")]   # tailscale serve speaks https; this PC, http


def frame_headers_out(r, prefix, path="/"):
    """The tool's answer headers for the browser: all of them (every Set-Cookie) but the hop ones and the framing rule,
    which becomes the app's own; a redirect to one of the tool's root paths stays under its prefix."""
    out = []
    csp = ", ".join(v for k, v in r.headers.multi_items() if k.lower() == "content-security-policy")
    for k, v in r.headers.multi_items():
        lk = k.lower()
        if lk in FRAME_DROP_OUT:
            continue
        if lk == "location" and v.startswith("/") and not v.startswith((f"{prefix}/", "//")):
            v = prefix + v
        out.append((lk.encode("latin-1"), v.encode("latin-1")))
    return out + [(b"content-security-policy", frame_csp(csp, path).encode("latin-1"))]


async def frame_proxy(request):
    """/<tool>/... -> the tool's /...: the method, the query, the body, the cookies, and the answer as it comes."""
    name = request.url.path.split("/")[1]
    prefix = f"/{name}"
    if from_ai_phone(request):                            # PHN-07: n8n starts work and Phoenix holds every trace (SEC2-R2)
        return PlainTextResponse("Not from the AI phone: it may only press Stop.", status_code=403)
    if request.url.path == prefix:
        return RedirectResponse(f"{prefix}/", status_code=307)
    c = _frame_client(name)
    body = request.stream() if request.method not in ("GET", "HEAD", "OPTIONS") else None
    try:
        req = c.build_request(request.method, request.url.path[len(prefix):], params=request.query_params,
                              headers=frame_headers_in(request), content=body)
        r = await c.send(req, stream=True)
    except httpx.HTTPError as e:
        await c.aclose()
        return PlainTextResponse(f"{name} is not reachable ({type(e).__name__}); it starts with the stack.", status_code=502)

    async def close():
        await r.aclose()
        await c.aclose()
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(close))
    resp.raw_headers = frame_headers_out(r, prefix, request.url.path[len(prefix):])
    return resp


FRAME_ROUTES = [r for n in FRAMES for r in (Route(f"/{n}", frame_proxy), Route(f"/{n}/{{path:path}}", frame_proxy,
                                                                                  methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]))]
