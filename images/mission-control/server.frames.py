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


# ---------- APP-85: the app holds n8n's session for the owner (the factory design v3, §4 B) ----------
# The owner stores n8n's login once (make n8n-login: N8N_LOGIN_EMAIL and N8N_LOGIN_PASSWORD in sops, compose hands them
# to this app). The app signs in to n8n itself (POST /rest/login) and keeps the session in memory: n8n 2.44.7's cookie
# n8n-auth and the browser id the session is bound to (n8n checks a hash of the browser-id header against its token).
# It adds both to the proxied requests of the owner's own signed-in session only: never the AI phone (refused above),
# never the stack's own checks and previews (*@stack.local), and never handed to the browser: an n8n-auth cookie the
# browser sends is replaced, one n8n sets is dropped. A 401 from n8n signs in again, once. Without the login stored,
# n8n's pages say in one line how to store it.
# What runs in production never changes from the app's frame: n8n keeps a saved draft apart from the published version
# (verified on 2.44.7: a save makes a new versionId, the activeVersionId and what the webhook answers stay), and the
# routes that publish, run, archive, share or retry are refused here. A change goes live through the factory (export
# to git as a change, its checks, the gate): APP_PROMOTE_HOOK below is where that path attaches (its own design first).
N8N_LOGIN = {"email": os.environ.get("N8N_LOGIN_EMAIL", ""), "password": os.environ.get("N8N_LOGIN_PASSWORD", "")}
N8N_SESSION = {"cookie": "", "browser": "", "at": 0.0}
N8N_RELOGIN_S = 60                                    # limit: waits, a login n8n refused is tried again after a minute, not on every request
_n8n_login_lock = asyncio.Lock()
N8N_REFUSED = re.compile(r"^/rest/(workflows/[^/]+/(activate|deactivate|run|archive|unarchive|share|transfer)|workflows/[^/]+$|executions/[^/]+/retry|executions/delete|executions/[^/]+$|logout)$")
N8N_REFUSED_WORDS = ("Publishing and running go through the factory: a change is a draft here, and it goes live as a change in "
                     "git with its checks and your approval. Nothing that runs changed.")
APP_PROMOTE_HOOK = None                                # the promote path's design (export draft -> PR -> replay -> gate -> publish) attaches here
N8N_ASSET = re.compile(r"^/(assets|static|types|icons|rest|webhook|form|favicon|schemas|healthz|sw|manifest)")


def n8n_owner(request):
    """The owner's own signed-in session: the gate checked the sign-in; not the stack's own checks and previews."""
    login = request.headers.get("tailscale-user-login", "")
    return bool(login) and not login.endswith("@stack.local") and not from_ai_phone(request)


def n8n_refused(method, path):
    """A request from the app's frame that would change what runs: a publish, a run, an archive, a delete, a share."""
    if method in ("GET", "HEAD", "OPTIONS"):
        return False
    m = N8N_REFUSED.match(path)
    return bool(m) and not (method in ("PATCH", "PUT") and path.count("/") == 3)   # a save of the draft (PATCH /rest/workflows/<id>) is a draft


async def n8n_login(force=False):
    """-> True when the app holds a session: signs in with the stored login (once at a time; again when force)."""
    async with _n8n_login_lock:
        if N8N_SESSION["cookie"] and not force:
            return True
        if not (N8N_LOGIN["email"] and N8N_LOGIN["password"]):
            return False
        if not N8N_SESSION["cookie"] and time.time() - N8N_SESSION["at"] < N8N_RELOGIN_S:
            return False                                 # refused a moment ago: not again on every page n8n loads
        browser = N8N_SESSION["browser"] or uuid.uuid4().hex
        c = _frame_client("n8n")
        try:
            r = await c.post("/rest/login", json={"emailOrLdapLoginId": N8N_LOGIN["email"], "password": N8N_LOGIN["password"]},
                             headers={"browser-id": browser})
        except httpx.HTTPError:
            return False
        finally:
            await c.aclose()
        cookie = r.cookies.get("n8n-auth") if r.status_code == 200 else None
        N8N_SESSION.update(cookie=cookie or "", browser=browser if cookie else "", at=time.time())
        if not cookie:
            print(f"n8n session: its login was refused ({r.status_code}); run make n8n-login again", flush=True)   # never the login itself
        return bool(cookie)


def n8n_with_session(headers):
    """The request's headers with the app's session: its own n8n-auth cookie for the browser's, its browser id."""
    out = []
    for k, v in headers:
        if k.lower() == "browser-id":
            continue
        if k.lower() == "cookie":
            kept = "; ".join(c.strip() for c in v.split(";") if c.strip() and not c.strip().startswith("n8n-auth="))
            if kept:
                out.append((k, kept))
            continue
        out.append((k, v))
    cookie = "; ".join(x for x in [next((v for k, v in out if k.lower() == "cookie"), ""), f"n8n-auth={N8N_SESSION['cookie']}"] if x)
    return [(k, v) for k, v in out if k.lower() != "cookie"] + [("cookie", cookie), ("browser-id", N8N_SESSION["browser"])]


def n8n_login_page():
    return HTMLResponse("<!doctype html><meta charset=utf-8><body style=\"font:15px system-ui;padding:24px\">n8n needs its login once: on the PC "
                        "run <b>make n8n-login</b>, then the next deploy (or a restart of the app) signs in for you.</body>", status_code=200)


async def frame_proxy(request):
    """/<tool>/... -> the tool's /...: the method, the query, the body, the cookies, and the answer as it comes."""
    name = request.url.path.split("/")[1]
    prefix = f"/{name}"
    if from_ai_phone(request):                            # PHN-07: n8n starts work and Phoenix holds every trace (SEC2-R2)
        return PlainTextResponse("Not from the AI phone: it may only press Stop.", status_code=403)
    if request.url.path == prefix:
        return RedirectResponse(f"{prefix}/", status_code=307)
    path = request.url.path[len(prefix):]
    held = False
    if name == "n8n":
        if n8n_refused(request.method, path):
            return JSONResponse({"code": 403, "message": N8N_REFUSED_WORDS}, status_code=403)
        if n8n_owner(request):
            held = await n8n_login()
            if not held and request.method == "GET" and not N8N_ASSET.match(path) and "text/html" in request.headers.get("accept", ""):
                return n8n_login_page()
    body = (await request.body() if held else request.stream()) if request.method not in ("GET", "HEAD", "OPTIONS") else None
    for attempt in (0, 1):
        c = _frame_client(name)
        headers = frame_headers_in(request)
        try:
            req = c.build_request(request.method, path, params=request.query_params,
                                  headers=n8n_with_session(headers) if held else headers, content=body)
            r = await c.send(req, stream=True)
        except httpx.HTTPError as e:
            await c.aclose()
            return PlainTextResponse(f"{name} is not reachable ({type(e).__name__}); it starts with the stack.", status_code=502)
        if held and r.status_code == 401 and attempt == 0:   # the session ran out or n8n restarted: sign in again, once
            await r.aclose()
            await c.aclose()
            held = await n8n_login(force=True)
            if held:
                continue
            c = _frame_client(name)
            r = await c.send(c.build_request(request.method, path, params=request.query_params, headers=headers, content=body), stream=True)
        break

    async def close():
        await r.aclose()
        await c.aclose()
    resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(close))
    resp.raw_headers = [(k, v) for k, v in frame_headers_out(r, prefix, path)
                        if not (name == "n8n" and k == b"set-cookie" and v.lstrip().lower().startswith(b"n8n-auth="))]   # never the browser's
    return resp


FRAME_ROUTES = [r for n in FRAMES for r in (Route(f"/{n}", frame_proxy), Route(f"/{n}/{{path:path}}", frame_proxy,
                                                                                  methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]))]
