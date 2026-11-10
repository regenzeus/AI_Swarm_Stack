# part of server.py (WFL-14, docs/N8N-MIGRATION.md §4.1): n8n inside the app. n8n's editor is served under the app's own
# address at /n8n/, behind the app's front door (TailnetOnly: the owner's Tailscale login, and no write from another
# site), so the app's pages can show it in a frame. n8n runs with N8N_PATH=/n8n/ (compose/core.yaml): its pages ask for
# /n8n/...; n8n itself answers at its root, so the prefix is taken off on the way in. Everything streams both ways: its
# live updates (N8N_PUSH_BACKEND=sse, one long answer), its large bundles and uploads. The app frames it, nobody else.
# GET /api/workflows is the runner's view of every workflow and its recent runs (ops/flows_view.py) for the app's pages.
from starlette.background import BackgroundTask

N8N_URL = os.environ.get("N8N_URL", "http://n8n:5678")   # n8n on the stepnet network, which only n8n and this app share
N8N_HOP = {"connection", "keep-alive", "proxy-connection", "transfer-encoding", "te", "trailer", "upgrade", "host", "content-length"}
N8N_SET_IN = {"x-forwarded-host", "x-forwarded-proto"}   # the app says these itself
N8N_DROP_OUT = N8N_HOP | {"x-frame-options", "content-security-policy"}   # framing: the app's own pages only (set below)
N8N_FRAME = "frame-ancestors 'self'"
N8N_CONNECT_TIMEOUT = 10                              # limit: stops, n8n that does not take the connection within 10 s is reported as not reachable
_n8n_transport = None                                 # tests put a fake n8n here


def _n8n_client():
    # no read limit: a request n8n accepted takes as long as it needs; its live updates are one answer that never ends
    return httpx.AsyncClient(base_url=N8N_URL, timeout=httpx.Timeout(None, connect=N8N_CONNECT_TIMEOUT), transport=_n8n_transport, follow_redirects=False)


def n8n_headers_in(request):
    """What the browser sent, for n8n: its cookies, n8n's own headers (browser-id, push-ref), the body's type and
    encoding; never the Tailscale identity headers. The address the browser used goes along, so n8n checks a live
    update's origin against it."""
    out = [(k, v) for k, v in request.headers.items()
           if k.lower() not in N8N_HOP | N8N_SET_IN and not k.lower().startswith("tailscale-")]
    if "accept-encoding" not in request.headers:       # httpx would ask for gzip itself; the browser gets what it asked for
        out.append(("accept-encoding", "identity"))
    host = request.headers.get("host", "")
    if host:
        out += [("host", host), ("x-forwarded-host", host)]
    return out + [("x-forwarded-proto", "https")]      # tailscale serve speaks https to the browser


def n8n_headers_out(r):
    """n8n's answer headers for the browser: all of them (every Set-Cookie) but the hop ones and the framing rule, which
    becomes the app's own; a redirect to one of n8n's root paths stays under /n8n/."""
    out = []
    for k, v in r.headers.multi_items():
        lk = k.lower()
        if lk in N8N_DROP_OUT:
            continue
        if lk == "location" and v.startswith("/") and not v.startswith(("/n8n/", "//")):
            v = "/n8n" + v
        out.append((lk.encode("latin-1"), v.encode("latin-1")))
    return out + [(b"content-security-policy", N8N_FRAME.encode())]


async def n8n_proxy(request):
    """/n8n/... -> n8n's /...: the method, the query, the body, the cookies, and the answer as it comes, chunk by chunk."""
    if request.url.path == "/n8n":
        return RedirectResponse("/n8n/", status_code=307)
    c = _n8n_client()
    body = request.stream() if request.method not in ("GET", "HEAD", "OPTIONS") else None
    try:
        req = c.build_request(request.method, request.url.path[len("/n8n"):], params=request.query_params,
                              headers=n8n_headers_in(request), content=body)
        r = await c.send(req, stream=True)
    except httpx.HTTPError as e:
        await c.aclose()
        return PlainTextResponse(f"n8n is not reachable ({type(e).__name__}); it starts with the stack.", status_code=502)

    async def close():
        await r.aclose()
        await c.aclose()
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(close))
    resp.raw_headers = n8n_headers_out(r)
    return resp


async def api_workflows(request):
    """WFL-14: every workflow in git with its schedule, its steps and its recent runs (public/workflows-runs.json)."""
    try:
        return JSONResponse(json.loads((M / "public/workflows-runs.json").read_text()))
    except (OSError, ValueError):
        return JSONResponse({"workflows": [], "generated": None})
