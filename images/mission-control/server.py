"""Mission Control: the web app (phone + desktop, installable as an app) and the mission tools for Hermes.

Port 8090: the app and its API, published to 127.0.0.1 only; reached from your devices through `tailscale serve`
(https://<pc>.ts.net:8447). Every /api call must carry Tailscale's identity header, which only tailscale serve sets.
Port 8091: MCP tools (missions_overview, mission_create, mission_update, ...) for Hermes, reached only by LiteLLM on
the internal "mcnet" network (granted per key in ops/keys.sh).
This container never starts anything itself: it reads the runner's state (/missions/public/state.json) and drops
requests into /missions/inbox; ops/missions.py on the host validates and executes them. Chats are kept in
/missions/app/chats (one JSON file each), so every device sees the same history. The wiki views read the vault.
"""
import asyncio, base64, datetime as dt, hashlib, hmac, html, json, os, re, shutil, threading, time, urllib.parse, urllib.request, uuid
from pathlib import Path

import httpx
import runrecord as RT
import teamroom as TR
import interactions as IX
import uvicorn
import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from textcap import cut, tail                    # visible caps and input limits (AGENTS.md, truncation)
import textcap as TC

M = Path("/missions")
STATE, EVENTS = M / "public/state.json", M / "public/events.jsonl"
INBOX, RESULTS, RUNS, DATA = M / "inbox", M / "public/results", M / "runs", M / "app"
CHATS = DATA / "chats"
VAULT = Path("/vault")
WEB = Path(__file__).parent / "web"
HERMES = "http://hermes:8642/v1/chat/completions"
PHOENIX = os.environ.get("PHOENIX_URL", "http://phoenix:6006")
PHOENIX_PORT = 8443                                       # tailscale serve: https://<pc>.ts.net:8443 (tailnet only)
HERMES_KEY = os.environ.get("API_SERVER_KEY", "")
ACTIONS = {"claude_task", "claude_cancel", "windows_ask", "forgejo_connect", "create", "run", "pause", "resume", "archive", "update", "memory", "email", "vault_add", "understand", "card_edit",
           "forget", "memory_search", "memory_browse", "memory_move", "build_assign", "build_revise", "build_approve", "build_approve_all", "build_reject", "build_revert",
           "improve_scan", "proposal_accept", "proposal_dismiss", "build_recheck", "build_switch_engine", "codemap", "repo_create", "repo_buildable", "repo_remove", "crew_run", "crew_memory_forget", "crew_memory_undo", "crew_schedule",
           "journal_note", "journal_edit", "health_ack", "swarm_pause", "swarm_confirm", "swarm_reopen", "swarm_autonomy", "swarm_post", "swarm_help_verdict", "swarm_agent_change", "phone_cleanup_do", "phone_cleanup_do_all", "phone_cleanup_undo", "phone_cleanup_dismiss",
           "shop_decide", "shop_limits",           # shop_*: only through /api/shop/* (the owner, never the AI phone or an agent)
           "house_connect", "house_switch", "house_alexa", "house_say", "house_settings", "house_status",   # house_*: /api/house* and the house MCP tools
           "notify_prefs", "chat_ready",           # notify_*: the owner's notification preferences; chat_ready: from the app itself
           "task_create", "task_answer", "task_approve", "task_cancel", "task_retry", "task_run", "task_conduct",   # task_*: the task kernel (TSK-01 to TSK-04, TSK-21, TSK-22)
           "change_request", "change_go", "change_resume", "change_leave", "change_rule",   # change_*: change requests (CHG-01, ops/changes.py)
           "decision_test_answer",                 # GEN-03: the tap on the nightly journey's test item; it changes only that item (ops/decisions.py)
           "rule_save", "rule_toggle", "rule_delete", "event_rate", "calendar_set", "calendar_clear",
           "a2a_settings", "a2a_token", "a2a_revoke",
           "wiki_delete",
           "file_save", "file_delete", "file_restore", "file_pin", "files_cleanup", "files_asked",
           "mem_search", "mem_open", "mem_subscribe", "mem_note", "mem_undo", "mem_chat"}   # mem_*: the memory MCP servers (MEM-28), the app's Undo (MEM-35) and a chat turn's memory (MEM-46)   # MIS-23 to MIS-26: mission files (ops/files.py)                                  # ops/wikis.py: from the app only (refused from the AI phone above)                                    # TSK-19: outside agents (A2A)                      # the event bus's rules and ratings (TSK-10 to TSK-12)
BUILDS = M / "builds"
MAPS = M / "public/maps"                          # TSK-24: each task run's swarm map (ops/provenance.py)
TASK_PAGES = M / "public/tasks"                        # APP-35: each task page's data, written by the runner (ops/tasks.py publish)
TELEMETRY = M / "public/telemetry.json"           # TSK-25: the daily history (ops/history.py)


def state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {"missions": [], "activity": [], "calls": [], "system": {}, "running": None, "queue": []}


def mission(slug):
    return next((x for x in state()["missions"] if x["slug"] == slug), None)


async def submit(req, wait=8.0):
    """Drop a request for the runner; wait briefly for its answer."""
    if req.get("action") not in ACTIONS:
        return {"ok": False, "error": "unknown action"}
    rid = uuid.uuid4().hex[:16]
    tmp = INBOX / f".{rid}.tmp"
    tmp.write_text(json.dumps(req, ensure_ascii=False))
    tmp.rename(INBOX / f"{rid}.json")
    end = time.time() + wait
    while time.time() < end:
        f = RESULTS / f"{rid}.json"
        if f.exists():
            return json.loads(f.read_text())
        await asyncio.sleep(0.4)
    return {"ok": True, "pending": True, "id": rid}



def _part(name):
    """PLT-25: a part of this file kept in its own file (<this file's stem>.<part>.py), run here, in this module's namespace,
    where it stood: one namespace as before, so names, patches and tracebacks hold. Not a module of its own."""
    p = Path(__file__).with_name(name)
    exec(compile(p.read_text(), str(p), "exec"), globals())   # nosemgrep: python-eval-exec -- this module's own part file beside it (PLT-25), never data


# ---------- app API ----------
class TailnetOnly(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith(("/api/", "/share")) and not request.headers.get("tailscale-user-login"):
            return JSONResponse({"error": "only reachable through Tailscale"}, status_code=403)
        # SEC-20: tailscale serve adds the owner's login to whatever his browser sends, a page of another site included;
        # a browser names where a request comes from (Sec-Fetch-Site), so a write from anywhere but this app is refused.
        # /share is the phone's share sheet (its own reasoning, APP share inbox); programs send no Sec-Fetch-Site.
        if (request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/")
                and request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none")):
            return JSONResponse({"error": "refused: a write request from another site (SEC-20)"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/static/") and "/vendor/" not in request.url.path:
            response.headers["Cache-Control"] = "no-cache"          # always revalidate: updates show up at once
        elif request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-cache"          # timelines/histories are files: browsers cached them stale
        return response


def display_name(name, login):
    """The owner's name for the greeting (U3): Tailscale's display name, never an e-mail address or its local part."""
    name = (name or "").strip()
    local = (login or "").split("@")[0].lower()
    return "" if not name or "@" in name or name.lower() == local or name.split(" ")[0].lower() == local else name


def owner_decisions(s):
    """AUT-05, GEN-02: the waits only the server sees (the AI phone's approval requests, Gmail's first-Trash batch, a
    mission whose access is not granted), in the shape of ops/decisions.py, before the runner's ranked list: floor classes,
    never licensed. This is the one list: Home and #/decide both draw what this returns."""
    out, ph, cs = [], s.get("phone") or {}, s.get("connections") or {}
    if ph.get("pending"):
        n = ph["pending"]
        out.append({"id": "phone-ask", "cls": "phone", "what": f"The AI phone asks for {n} approval{'s' if n > 1 else ''}", "why": "it waits for your tap",
                    "href": "#/phone", "recommend": None, "unanswered": "the phone's step does not run", "expires": None,
                    "answers": [{"label": "Look", "href": "#/phone"}], "created": None, "weight": 2, "routine": False})
    if cs.get("pending"):
        out.append({"id": "gmail-trash", "cls": "delete", "what": "Gmail: a Trash batch waits for your OK", "why": "nothing is moved without it",
                    "href": "#/system?conn=1", "recommend": None, "unanswered": "the mail stays where it is", "expires": None,
                    "answers": [{"label": "Look", "href": "#/system?conn=1"}], "created": None, "weight": 1, "routine": False})
    for m in s.get("missions") or []:
        missing = [n for n in m.get("needs") or [] if not ((cs.get(n.split(":")[0]) or {}).get("grants") or {}).get(n.partition(":")[2])]
        if m.get("status") == "active" and missing:
            out.append({"id": f"access:{m['slug']}", "cls": "access", "what": f"{m.get('title') or m['slug']} needs access", "why": f"grant {', '.join(missing)} on its page",
                        "href": f"#/mission/{m['slug']}", "recommend": None, "unanswered": "its tools refuse until you grant it", "expires": None,
                        "answers": [{"label": "Grant on its page", "href": f"#/mission/{m['slug']}"}], "created": None, "weight": 1, "routine": False})
    return out + list(s.get("decisions") or [])


async def api_state(request):
    """The runner's whole state (missions, runs, builds, crew, health, system …) plus the phone, the connections and who is viewing."""
    s = state()
    s["phone"] = phone_summary()
    s["connections"] = conn_summary()
    s["viewer"] = request.headers.get("tailscale-user-name") or request.headers.get("tailscale-user-login", "")
    s["viewer_name"] = display_name(request.headers.get("tailscale-user-name", ""), request.headers.get("tailscale-user-login", ""))
    s["decisions"] = owner_decisions(s)
    s["from_chat"] = MADE_IDX["v"]                       # APP-39: an item made in a chat links back to it
    return JSONResponse(s)


async def api_stream(request):
    """Server-sent events: a new state whenever the runner writes one, so screens update without polling (APP-17)."""
    async def gen():
        last = 0
        yield "retry: 3000\n\n"
        while not await request.is_disconnected():
            try:
                mt = STATE.stat().st_mtime
            except FileNotFoundError:
                mt = 0
            ph = phone_summary()                      # the AI phone changes on its own clock: part of the stream too
            cs = conn_summary()                       # and so do the app connections (grants, approvals)
            sig = (mt, json.dumps(ph, sort_keys=True, default=str), json.dumps(cs, sort_keys=True, default=str))
            if sig != last:
                last = sig
                full = {**state(), 'phone': ph, 'connections': cs}
                full["decisions"] = owner_decisions(full)
                full["from_chat"] = MADE_IDX["v"]
                yield f"data: {json.dumps(full, ensure_ascii=False)}\n\n"
            else:
                yield ": ping\n\n"
            await asyncio.sleep(1.5)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def api_request(request):
    """Drops an owner's action into the runner's inbox (the only way the app acts, SEC-12); the runner validates and answers under /api/result."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "no JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "invalid: the request must be a JSON object"}, status_code=400)
    if (n := len(json.dumps(body))) > 20000:              # limit: refuses, a request is an action and its fields, not a document
        return JSONResponse({"ok": False, "error": f"the request is {n:,} characters; the limit is 20,000"}, status_code=400)
    if from_ai_phone(request):                            # PHN-07: the AI phone may only press Stop (/api/phone/control)
        return JSONResponse({"ok": False, "error": "not from the AI phone: it may only press Stop"}, status_code=403)
    if str(body.get("action", "")).startswith("shop_"):
        return JSONResponse({"ok": False, "error": "purchases are decided at /api/shop/decide"}, status_code=403)
    if str(body.get("action", "")).startswith("house_"):
        return JSONResponse({"ok": False, "error": "the House is controlled through /api/house"}, status_code=403)
    if body.get("action") == "a2a_token":                                   # the token is made at /api/a2a/token, shown once
        return JSONResponse({"ok": False, "error": "outside agents are added at /api/a2a/token"}, status_code=403)
    if body.get("action") == "file_save":                                  # files are made by missions (the file_save tool)
        return JSONResponse({"ok": False, "error": "a mission saves its files itself (file_save)"}, status_code=403)
    if str(body.get("action", "")).startswith("windows_"):                 # PLT-31: only a tool in your own chat asks Windows
        return JSONResponse({"ok": False, "error": "asked in a chat, through the assistant's tool"}, status_code=403)
    if body.get("action") == "chat_ready":                                 # sent by the app itself when a waiting chat is answered
        return JSONResponse({"ok": False, "error": "not a request the app's screens make"}, status_code=403)
    body["source"] = "app"
    note_owner(str(body.get("action", "")))
    return JSONResponse(await submit(body))


def note_owner(action, text=""):
    """SWM-112: an owner's decision that no other record names, for the map (interactions.py OWNER_ACTS)."""
    if action in IX.OWNER_ACTS:
        try:
            with open(M / "app/actions.jsonl", "a") as f:
                f.write(json.dumps({"ts": time.time(), "action": action, "text": text}, ensure_ascii=False) + "\n")
        except OSError as e:
            print(f"actions: {type(e).__name__}", flush=True)


async def api_result(request):
    """The runner's answer to one request, or {pending: true} while it works."""
    rid = request.path_params["rid"]
    f = RESULTS / f"{rid}.json"
    if not re.fullmatch(r"[a-f0-9]{16}", rid):
        return JSONResponse({"error": "invalid"}, status_code=400)
    return JSONResponse(json.loads(f.read_text()) if f.exists() else {"pending": True})


def vault_file(rel):
    p = (VAULT / rel).resolve()
    if not (rel.endswith(".md") and p.is_relative_to(VAULT.resolve()) and p.is_file()):
        return None
    parts = p.relative_to(VAULT.resolve()).parts               # the resolved path, so wiki/../.trash is caught (review APP-R18)
    return None if parts[0].startswith(".") or parts[:2] == ("raw", "_files") else p


async def api_file(request):
    """A vault file as text, for the reading view; only paths inside the vault."""
    p = vault_file(request.query_params.get("path", ""))
    return PlainTextResponse(p.read_text(errors="replace")) if p else JSONResponse({"error": "not allowed"}, status_code=404)


MFILES = M / "files"                                   # MIS-23: each mission's files (ops/files.py writes them)
FILE_TYPES = {".md": "text/markdown", ".csv": "text/csv", ".json": "application/json", ".txt": "text/plain"}   # = ops/files.py TYPES
FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")                                                     # = ops/files.py NAME


def mission_file(slug, name, version=""):
    """The path of a mission's file (or one of its earlier versions), only inside its folder; None otherwise."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", slug or "") or not FILE_NAME.fullmatch(name or "") \
            or Path(name).suffix.lower() not in FILE_TYPES or (version and not re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{8}", version)):
        return None
    p = MFILES / slug / ".versions" / name / version if version else MFILES / slug / name
    return p if p.is_file() and p.resolve().is_relative_to(MFILES.resolve()) else None


async def api_change_file(request):
    """CHG-14: what the Prober kept of trying a change for real: a log or a screenshot."""
    name = request.path_params["name"]
    p = M / "public/changes" / str(request.path_params["tid"]) / name
    if not FILE_NAME.match(name) or not p.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    types = {".png": "image/png", ".jpg": "image/jpeg", ".log": "text/plain", ".txt": "text/plain", ".json": "application/json"}
    return FileResponse(p, media_type=types.get(p.suffix.lower(), "text/plain"))


async def api_mission_file(request):
    """MIS-23: a mission's file: as text for the reader, or with ?download=1 as the file itself (its own name)."""
    q = request.query_params
    p = mission_file(request.path_params["slug"], request.path_params["name"], q.get("v", ""))
    if not p:
        return JSONResponse({"error": "no such file"}, status_code=404)
    name = request.path_params["name"]
    if q.get("download"):
        return FileResponse(p, media_type=FILE_TYPES[Path(name).suffix.lower()], filename=name if not q.get("v") else f"{Path(name).stem}-{q['v'][:15]}{Path(name).suffix}")
    return PlainTextResponse(p.read_text(errors="replace"))


async def api_mission_drafts(request):
    """MIS-23: the Ledger reports a mission's runs wrote (drafts the agent kept there), newest first, from the run record."""
    slug = request.path_params["slug"]
    return JSONResponse(RT.ledger_drafts(f"mission:{slug}") if re.fullmatch(r"[a-z0-9-]{1,80}", slug) else [])


async def api_build_file(request):
    """One file of a build (diff, log, steps, files or context) as text."""
    bid, kind = request.path_params["bid"], request.path_params["kind"]
    p = BUILDS / (f"{bid}.context.json" if kind == "context" else f"{bid}.{kind}")     # context: the blast radius (SWM-94)
    if not bid.isdigit() or kind not in ("diff", "log", "steps", "files", "context") or not p.exists():
        return PlainTextResponse("", status_code=404)
    text = p.read_text(errors="replace")
    if kind == "log":
        text = tail("\n".join(ln for ln in text.splitlines() if "install out of sync" not in ln), 200000)  # cap: store
    return PlainTextResponse(text)


CLAUDE = M / "claude"


async def api_claude_task(request):
    """A Claude task (ops/claude_tasks.py): question, answer, status and its steps (with Claude's thinking)."""
    tid = request.path_params["tid"]
    p = CLAUDE / f"{tid}.json"
    if not tid.isdigit() or not p.exists():
        return JSONResponse({"error": "no such task"}, status_code=404)
    return FileResponse(p, media_type="application/json")


SWARM_APP = os.environ.get("SWARM_APP_URL", "http://swarm:8096/v1/app")
SWARM_TOKEN = os.environ.get("SWARM_APP_TOKEN", "")
SWARM_READ = {"conversations", "thread", "graph", "history", "feed", "who", "owner_inbox", "tasks", "leases", "flow", "runs", "unfinished", "agent_card",
              "agent_changes", "experiments", "replays"}


def _swarm_app(op, args):
    """One read through the Swarm service's app door -> its {ok, result} answer."""
    req = urllib.request.Request(SWARM_APP, data=json.dumps({"op": op, "args": args}).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {SWARM_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


async def api_swarm(request):
    """The Swarm page reads through the Swarm service's read-only door (the owner sees every thread); his posts go to the
    runner as action swarm_post."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "no JSON"}, status_code=400)
    if body.get("op") not in SWARM_READ:
        return JSONResponse({"ok": False, "error": "read-only"}, status_code=403)
    try:
        return JSONResponse(await asyncio.to_thread(_swarm_app, body["op"], body.get("args") or {}))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"the swarm is not reachable ({type(e).__name__})"}, status_code=502)


async def api_swarm_now(request):
    """SWM-97: who is working right now, from the runtime record's live runs: agent, what, since when, tokens so far."""
    return JSONResponse(await asyncio.to_thread(RT.live_now))


def _hours(request, default, most=168):
    try:
        return min(max(float(request.query_params.get("hours") or default), 1), most)
    except ValueError:
        return default


_picture = {}


def swarm_picture(hours, tests, private):
    """SWM-110: the window's interactions (interactions.py), kept 15 seconds: a page polls, and each look reads several records."""
    key, now = (hours, tests, private), time.time()
    hit = _picture.get(key)
    if hit and now - hit[0] < 15:
        return hit[1]
    err = ""
    try:
        feed = _swarm_app("feed", {"since": now - hours * 3600}).get("result") or {}
    except Exception as e:
        feed, err = {}, f"the swarm is not reachable ({type(e).__name__}): its events and messages are missing"
    out = IX.build(RT, TR, feed, hours, now, M, tests=tests, private=private, feed_error=err)
    _picture.clear() if len(_picture) > 16 else None
    _picture[key] = (now, out)
    return out


def _picture_of(request, default):
    return swarm_picture(_hours(request, default), request.query_params.get("tests") == "1", not from_ai_phone(request))


async def api_swarm_timeline(request):
    """SWM-103: every agent's runs in the window (at most 7 days), as bars of its lane, with what started each. One piece of
    work is one bar and tests stay out unless tests=1 (SWM-112)."""
    p = await asyncio.to_thread(_picture_of, request, 24)
    tests = request.query_params.get("tests") == "1"
    return JSONResponse({"since": p["since"], "now": p["now"], "runs": [r for r in p["runs"] if not r.get("half") and (tests or r.get("world") != "test")]})


async def api_swarm_interactions(request):
    """SWM-110: the map's dots and lines in the window, counted from the same rows Activity shows, with how much of it has a known cause."""
    try:
        p = await asyncio.to_thread(_picture_of, request, 168)
    except Exception as e:                                # a fresh install has no run record yet: said in words, not as an HTTP 500
        print(f"swarm interactions: {type(e).__name__}: {e}", flush=True)
        return JSONResponse({"error": "its run record cannot be read yet"}, status_code=503)
    return JSONResponse({k: p[k] for k in ("since", "now", "nodes", "edges", "coverage", "sources")})


async def api_swarm_delegations(request):
    """SWM-105: what agents ask each other through their tools, as exchanges for the Chatroom (pair=a+b: two agents)."""
    return JSONResponse(await asyncio.to_thread(RT.delegations, _hours(request, 168), request.query_params.get("pair") or None))


async def api_swarm_room(request):
    """SWM-107, SWM-110: one timeline of what the agents do together and with you, at most 7 days, the rows the map counts:
    the Ledger's events and the Board's messages (Swarm service), asks and tool use between agents, hand-overs, what you
    said and what you were told. A record that can't be read is named instead of showing nothing (SWM-115)."""
    p = await asyncio.to_thread(_picture_of, request, 24)
    return JSONResponse({"since": p["since"], "now": p["now"], "lines": p["lines"], "coverage": p["coverage"], "sources": p["sources"],
                         "error": "; ".join(f"{k}: {v}" for k, v in p["sources"].items())})


async def api_swarm_tokens(request):
    """Tokens per agent in the last 30 days from the runtime record (with the Claude runs under a crew job), for the
    scorecards' cost per proved idea (SWM-17)."""
    return JSONResponse(await asyncio.to_thread(RT.tokens_by_agent, 30))


async def api_crew_one(request):
    """A crew agent's history (ops/crew.py writes it every 5 minutes): runs, logs, stats, payoff, health."""
    cid = request.path_params["cid"]
    p = M / "crew" / f"{cid}.history.json"
    if not re.fullmatch(r"[a-z0-9-]{2,40}", cid) or not p.exists():
        return JSONResponse({"error": "no history yet"}, status_code=404)
    return FileResponse(p, media_type="application/json")


def health_issues():
    """Open health issues, one per agent and kind, with the run that shows them (state.json's health board)."""
    out = []
    for it in (state().get("health") or {}).get("items", []):
        href = (f"#/mission/{it['slug']}" if it["kind"] == "mission" else f"#/crew/{it['id']}" if it["kind"] == "crew" else
                f"#/live/{it['run']}" if it.get("run") else "#/missions")
        for i in it.get("issues", []):
            out.append({"agent": it["name"], "agent_kind": it["kind"], "agent_id": it.get("slug") or it.get("id"), "issue": i["kind"],
                        "severity": i.get("severity", "note"), "text": i["text"], "since": i.get("at"), "run": i.get("run") or it.get("run"),
                        "run_view": f"#/live/{i.get('run') or it.get('run')}" if i.get("run") or it.get("run") else None, "agent_page": href, "key": i.get("key")})
    return out


async def api_health_issues(request):
    """The open health-board issues, each with the run that shows it (OBS-13)."""
    return JSONResponse(health_issues())


async def api_run_timeline(request):
    """A run's timeline (ops/telemetry.py writes it: model calls, tool calls, results, thinking, tokens)."""
    rid = request.path_params["rid"]
    p = RUNS / f"{rid}.timeline.json"
    if not rid.isdigit() or not p.exists():
        return JSONResponse({"error": "no timeline yet"}, status_code=404)
    return FileResponse(p, media_type="application/json")


# ---------- the agent runtime's record (runrecord.py): one event stream for every agent, live ----------
def _ingest_ok(request):
    return bool(HERMES_KEY) and request.headers.get("authorization", "") == f"Bearer {HERMES_KEY}"


async def rt_ingest(request):
    """Events from the Hermes plugin (mcnet) and the runner's forwarder (127.0.0.1): API_SERVER_KEY as bearer."""
    if not _ingest_ok(request):
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    try:
        batch = json.loads((await request.body())[:4_000_000])
    except ValueError:
        return JSONResponse({"error": "not JSON"}, status_code=400)
    return JSONResponse({"stored": await asyncio.to_thread(RT.ingest, batch)})


async def rt_view(request):
    """One run's view for the runner (ops/journal.py condenses it into the agent's journal at the run's end)."""
    if not _ingest_ok(request):
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    v = await asyncio.to_thread(RT.view, request.path_params["run"])
    return JSONResponse(v or {"error": "no such run"}, status_code=200 if v else 404)


async def rt_problems(request):
    """The run record's open problems (by=agent: rolled up per owning agent) for the runner's health board; ingest key only."""
    if not _ingest_ok(request):
        return JSONResponse({"error": "unauthorised"}, status_code=401)
    if request.query_params.get("by") == "agent":
        return JSONResponse(await asyncio.to_thread(RT.agent_issues, int(request.query_params.get("hours", 48))))
    return JSONResponse(await asyncio.to_thread(RT.open_problems, int(request.query_params.get("hours", 24))))


async def api_rt_runs(request):
    """Runs from the run record, newest first (filter: live, agent, ref; limit)."""
    q = request.query_params
    live = {"1": True, "0": False}.get(q.get("live", ""))
    num = lambda k: float(q[k]) if q.get(k) else None
    try:
        since, until = num("since"), num("until")
    except ValueError:
        return JSONResponse({"error": "since and until are seconds"}, status_code=400)
    return JSONResponse(await asyncio.to_thread(RT.runs, live, q.get("agent"), q.get("ref"), min(int(q.get("limit", 60)), 500), since, until))


async def api_rt_run(request):
    """One run from the run record: its events, problems, statistics and manifest."""
    v = await asyncio.to_thread(RT.view, request.path_params["run"])
    return JSONResponse(v) if v else JSONResponse({"error": "no such run"}, status_code=404)


async def api_rt_stream(request):
    """New events of a run (and its children) as they arrive; ends when the run has ended."""
    run, after = request.path_params["run"], int(request.query_params.get("after", 0))

    async def gen():
        nonlocal after
        yield "retry: 3000\n\n"
        quiet = 0
        while not await request.is_disconnected():
            ev = await asyncio.to_thread(RT.events_of, run, after)
            if ev:
                after = ev[-1]["id"]
                quiet = 0
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            else:
                quiet += 1
                yield ": ping\n\n"
                if quiet % 10 == 0:
                    r = RT.db().execute("select ended from runs where run=?", (run,)).fetchone()
                    if r and r["ended"]:
                        yield "event: end\ndata: {}\n\n"
                        return
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def prune_uploads(now=None, folders=None):
    """PLT-21: files people added (chat files, phone uploads) older than 90 days; what was filed into the vault stays there.
    -> files removed."""
    now, n = now or time.time(), 0
    for d in folders or (UPLOADS, FILES):
        for f in (d.rglob("*") if d.is_dir() else []):
            if f.is_file() and now - f.stat().st_mtime > 90 * 86400:
                f.unlink()
                n += 1
    if n:
        print(f"pruned {n} uploads older than 90 days", flush=True)
    return n


async def rt_housekeeping():
    """The runtime's watchdog (every run ends once) and the 90-day event retention."""
    last_prune = 0
    while True:
        await asyncio.sleep(30)
        try:
            closed = await asyncio.to_thread(RT.watchdog_once)
            if closed:
                print("runtime watchdog closed:", ", ".join(closed), flush=True)
            if time.time() - last_prune > 86400:
                last_prune = time.time()
                await asyncio.to_thread(RT.prune)
                await asyncio.to_thread(prune_uploads)
        except Exception as ex:
            print("runtime housekeeping:", ex, flush=True)


rt_app = Starlette(routes=[Route("/ingest", rt_ingest, methods=["POST"]), Route("/problems", rt_problems), Route("/view/{run:path}", rt_view),
                           Route("/healthz", lambda r: PlainTextResponse("ok"))])


async def api_runlog(request):
    """The last 300 lines of a mission run's log (an earlier-lines marker says how many more there are)."""
    rid = request.path_params["rid"]
    p = RUNS / f"{rid}.log"
    if not rid.isdigit() or not p.exists():
        return PlainTextResponse("", status_code=404)
    lines = [ln for ln in p.read_text(errors="replace").splitlines() if "install out of sync" not in ln]
    return PlainTextResponse((f"({len(lines) - 300} earlier lines: open the full log)\n" if len(lines) > 300 else "") + "\n".join(lines[-300:]))  # cap: list


_part("server.chat.py")   # chats with their history, and what a chat made (PLT-25)


_part("server.share.py")   # the phone's Share menu (PLT-25)


_part("server.wiki.py")   # the wiki views (PLT-25)


_part("server.a2a.py")   # outside agents over A2A (PLT-25)


_part("server.devices.py")   # push notifications, the AI phone, app connections and the House (PLT-25)


# ---------- static ----------
def app_version():
    """Changes whenever the front end changes (a new image): open apps compare it and reload themselves."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted([*(WEB / "static").glob("*.*"), WEB / "index.html", WEB / "sw.js"]):
        h.update(f.name.encode() + f.read_bytes())
    return h.hexdigest()[:12]


APP_VERSION = app_version()


async def api_version(request):
    """The deployed app version; the app reloads itself when it changes (APP-03)."""
    return JSONResponse({"version": APP_VERSION}, headers={"Cache-Control": "no-store"})


async def api_mail(request):
    """The mail copy on the NAS and the sender report from its headers (CNX-07, CNX-08): no message text."""
    d = M / "mail"
    def read(name):
        try:
            return json.loads((d / name).read_text())
        except (OSError, ValueError):
            return None
    crew = read_crew_file("postmaster")
    return JSONResponse({"status": read("status.json"), "census": read("census.json"), "postmaster": {k: crew.get(k) for k in ("result", "last", "total_filed", "since")}})


def read_crew_file(aid):
    try:
        return json.loads((M / "crew" / f"{aid}.json").read_text())
    except (OSError, ValueError):
        return {}


# This deployment's addresses for the front end: compose hands them over (deployments/<name>/deployment.env), the page carries them.
DEPLOY = {k: ("" if os.environ.get(k, "").endswith(".invalid") else os.environ.get(k, ""))   # *.invalid: a placeholder, no host
          for k in ("PC_TAILNET_HOST", "NAS_HOST", "HA_URL", "ROUTER_URL", "FORGEJO_URL", "FORGEJO_OWNER", "DEPLOY_USER", "STACK_DIR", "APP_NAME")}
DEPLOY["APP_NAME"] = DEPLOY.get("APP_NAME", "").strip() or "AI Stack"   # APP-61: the app's name, the deployment's to choose


def app_name():
    """APP-61: the deployment's name for the app."""
    return str(DEPLOY.get("APP_NAME") or "").strip() or "AI Stack"


async def index(request):
    """The app's page (index.html) with this deployment's addresses in it, always revalidated."""
    # the page carries the version it was served with, so an app opened from the offline cache knows it is old (review APP-R15)
    page = (WEB / "index.html").read_text().replace("{{APP_NAME}}", html.escape(app_name())).replace("{/*DEPLOY*/};", json.dumps(DEPLOY).replace("<", "\\u003c") + "; "
                                                    f"window.APP_VERSION = {json.dumps(APP_VERSION)};", 1)
    return HTMLResponse(page, headers={"Cache-Control": "no-cache"})


async def sw(request):
    """The service worker (offline shell, push, self-update), always revalidated."""
    return FileResponse(WEB / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


async def manifest(request):
    """The PWA manifest that makes the app installable."""
    m = json.loads((WEB / "manifest.webmanifest").read_text())   # APP-61: installed under the deployment's name
    m["name"] = m["short_name"] = app_name()
    return JSONResponse(m, media_type="application/manifest+json")


# ---------- code: graphs and overviews of the repos for the Code tab (read-only mounts /code, /code-docs) ----------
CODE, CODE_DOCS = Path("/code"), Path("/code-docs")
REPO_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
_graph_cache = {}


def repo_dir(name):
    return CODE / name if REPO_NAME.match(name or "") and (CODE / name).is_dir() else None


async def api_repo_graph(request):
    """The repo's Graphify graph, reduced for drawing: the best-connected nodes (max 200, so phones keep up), their links, communities."""
    d = repo_dir(request.path_params["name"])
    f = d / "graphify-out" / "graph.json" if d else None
    if not f or not f.exists():
        return JSONResponse({"error": "no graph yet"}, status_code=404)
    key = (str(f), f.stat().st_mtime)
    if key not in _graph_cache:
        g = json.loads(f.read_text())
        own = [n for n in g.get("nodes", []) if n.get("source_file") and not TEST_PATH.search(str(n["source_file"]))]   # defined in the repository, not a test helper
        known = {n["id"] for n in own} or {n["id"] for n in g.get("nodes", [])}
        deg = {}
        for ln in g.get("links", []):                           # DEC-48: what holds the repository's own code together, not a type mention
            if ln.get("relation") in GRAPH_STRUCTURAL and ln["source"] in known and ln["target"] in known:
                for k in ("source", "target"):
                    deg[ln[k]] = deg.get(ln[k], 0) + 1
        by_comm = {}
        for n in own:
            by_comm.setdefault(str(n.get("community_name") or n.get("community") or ""), []).append(n["id"])
        keep = set()
        for ids in sorted(by_comm.values(), key=lambda ids: -sum(deg.get(i, 0) for i in ids))[:GRAPH_GROUPS]:   # cap: top (every big group is seen)
            keep |= set(sorted(ids, key=lambda i: (-deg.get(i, 0), i))[:GRAPH_PER_GROUP])   # cap: top (a group's best-connected few; the rest fills by degree)
        for i in sorted(known, key=lambda i: (-deg.get(i, 0), i)):          # the same 200 every time (ties by id)
            if len(keep) >= GRAPH_NODES:                         # limit: paces, the graph view draws this many nodes (GRAPH_NODES)
                break
            keep.add(i)
        nodes = [{"id": n["id"], "title": n.get("label", n["id"]), "folder": str(n.get("community_name") or n.get("community") or ""),
                  "summary": f"{n.get('source_file', '')} {n.get('source_location', '')}".strip(), "degree": deg.get(n["id"], 0),
                  "file": n.get("source_file", "")} for n in g.get("nodes", []) if n["id"] in keep]
        nodes.sort(key=lambda n: -n["degree"])                   # best connected first
        links = [{"source": ln["source"], "target": ln["target"], "relation": ln.get("relation", "")}
                 for ln in g.get("links", []) if ln["source"] in keep and ln["target"] in keep]
        comm = {}
        for n in nodes:
            comm[n["folder"]] = comm.get(n["folder"], 0) + 1
        _graph_cache.clear()
        _graph_cache[key] = {"nodes": nodes, "links": links, "total": len(known), "shown": len(nodes),
                             "communities": sorted(comm.items(), key=lambda x: -x[1])[:12]}  # cap: top
    return JSONResponse(_graph_cache[key])


GRAPH_STRUCTURAL = {"calls", "inherits", "implements", "contains", "imports", "imports_from", "method", "defines", "uses"}
GRAPH_NODES = 200            # limit: paces, nodes the graph view draws (phones keep up); the node panel walks to every neighbour, the viewer has all
GRAPH_GROUPS, GRAPH_PER_GROUP = 12, 3   # limit: paces, the biggest groups each show their best-connected few before the rest fills up
TEST_PATH = re.compile(r"(^|/)(tests?|spec|specs|__tests__|testdata|test_[^/]*|[^/]*_test\.[a-z]+|[^/]*\.(test|spec)\.[a-z]+)(/|$)")
_full_graph = {}


def full_graph(name):
    """The whole Graphify graph of a repo, indexed: nodes by id, and each node's outgoing and incoming links."""
    d = repo_dir(name)
    f = d / "graphify-out" / "graph.json" if d else None
    if not f or not f.exists():
        return None
    key = (str(f), f.stat().st_mtime)
    if _full_graph.get("key") != key:
        g = json.loads(f.read_text())
        nodes = {n["id"]: n for n in g.get("nodes", [])}
        out, inc = {}, {}
        for ln in g.get("links", []):
            out.setdefault(ln["source"], []).append(ln)
            inc.setdefault(ln["target"], []).append(ln)
        _full_graph.update(key=key, nodes=nodes, out=out, inc=inc)
    return _full_graph


def code_map(name):
    """The repo's Understand Anything knowledge graph (.ua/knowledge-graph.json), or None."""
    d = repo_dir(name)
    f = d / ".ua" / "knowledge-graph.json" if d else None
    try:
        return json.loads(f.read_text()) if f and f.exists() else None
    except ValueError:
        return None


def snippet(name, rel, line, before=3, after=28):
    """Source lines around a location, read-only from the repo; None for paths outside it or big/binary files."""
    d = repo_dir(name)
    try:
        f = (d / rel).resolve()
        if not d or not f.is_relative_to(d.resolve()) or not f.is_file() or f.stat().st_size > 400_000:
            return None
        lines = f.read_text(errors="replace").splitlines()
    except (OSError, ValueError):
        return None
    start, end = max(1, line - before), min(len(lines), line + after)
    return {"start": start, "end": end, "total": len(lines), "text": "\n".join(lines[start - 1:end])}   # cap: preview (the pane says lines X to Y of N; the whole file is one tap away)


async def api_repo_file(request):
    """One file of a repository, read-only, whole: for the source pane's "whole file" (DEC-48). Over 400 kB it stops and says so."""
    name, rel = request.path_params["name"], request.query_params.get("path", "")
    d = repo_dir(name)
    try:
        f = (d / rel).resolve()
        if not d or not f.is_relative_to(d.resolve()) or not f.is_file():
            return JSONResponse({"error": "no such file in this repository"}, status_code=404)
        text = f.read_text(errors="replace")
    except (OSError, ValueError):
        return JSONResponse({"error": "the file could not be read"}, status_code=404)
    total = text.count("\n") + 1
    return JSONResponse({"path": rel, "total": total, "text": TC.cut(text, 400_000)})  # cap: store (a file over 400 kB shows its start and says how much follows)


async def api_repo_node(request):
    """Everything about one code graph node: what it is, where it lives, its source, what it calls and what calls it,
    and what the code map (Understand Anything) says about it and its file."""
    name = request.path_params["name"]
    g = full_graph(name)
    n = g and g["nodes"].get(request.query_params.get("id", ""))
    if not n:
        return JSONResponse({"error": "no such node"}, status_code=404)
    m = re.match(r"L(\d+)", str(n.get("source_location", "")))
    line = int(m[1]) if m else 0

    def peer(ln, other):
        o = g["nodes"].get(ln[other], {})
        out = {"id": ln[other], "label": o.get("label", ln[other]), "relation": ln.get("relation", ""), "file": o.get("source_file", ""),
               "inferred": ln.get("confidence") not in (None, "EXTRACTED")}
        if o.get("file_type") == "rationale":            # the graph keeps a docstring cut with "...": the file has it whole
            whole = docstring_at(name, o.get("source_file", ""), o.get("source_location", ""))
            if whole:
                out["text"] = whole
        return out
    outs = [peer(ln, "target") for ln in g["out"].get(n["id"], [])]
    ins = [peer(ln, "source") for ln in g["inc"].get(n["id"], [])]
    ua, about, about_file = code_map(name), None, None
    if ua:
        plain = str(n.get("label", "")).rstrip("()")
        for u in ua.get("nodes", []):
            if u.get("filePath") == n.get("source_file"):
                if u.get("type") in ("file", "document", "config"):
                    about_file = {k: u.get(k) for k in ("summary", "tags", "complexity")}
                elif u.get("name") == plain:
                    about = {k: u.get(k) for k in ("summary", "tags", "complexity", "type")}
    kind = "class" if n.get("_callable_class") else "function" if n.get("_callable") else n.get("node_kind") or n.get("file_type") or "node"
    return JSONResponse({
        "id": n["id"], "label": n.get("label"), "kind": kind, "group": n.get("community_name"), "file": n.get("source_file"),
        "note": file_note(name, n.get("source_file") or ""),
        "line": line, "external": bool(n.get("external")), "outgoing": outs[:60], "incoming": ins[:60],  # cap: list
        "counts": {"out": len(outs), "in": len(ins)}, "code": snippet(name, n.get("source_file", ""), line) if line else None,
        "about": about, "about_file": about_file})


async def api_repo_map(request):
    """The code map (Understand Anything) in full: project, guided tour, layers, and every file and symbol with its
    summary, tags and complexity."""
    ua = code_map(request.path_params["name"])
    if not ua:
        return JSONResponse({"error": "no code map yet"}, status_code=404)
    keep = ("id", "type", "name", "filePath", "summary", "tags", "complexity", "lineRange")
    return JSONResponse({"project": ua.get("project", {}), "tour": ua.get("tour", []), "layers": ua.get("layers", []),
                         "nodes": [{k: u.get(k) for k in keep} for u in ua.get("nodes", [])]})


async def api_repo_overview(request):
    """What the repo is: the code map digest (Understand Anything) if there is one, else its README; and the written analysis of its onboarding."""
    name = request.path_params["name"]
    d = repo_dir(name)
    if not d:
        return JSONResponse({"error": "no such repo"}, status_code=404)
    digest, written = CODE_DOCS / f"{name}.md", CODE_DOCS / f"{name}.analysis.md"
    analysis = cut(written.read_text(errors="replace"), 200000) if written.exists() else ""  # cap: store
    if digest.exists():
        return JSONResponse({"source": "code map digest", "markdown": cut(digest.read_text(errors="replace"), 200000), "analysis": analysis})  # cap: store
    for readme in ("README.md", "readme.md", "README.rst", "README"):
        if (d / readme).exists():
            return JSONResponse({"source": readme, "markdown": cut((d / readme).read_text(errors="replace"), 200000), "analysis": analysis})  # cap: store
    return JSONResponse({"source": None, "markdown": "", "analysis": analysis})


async def api_repo_card(request):
    """DEC-49: the repository card as onboarding made it (ops/repocard.py), the owner's pins, strikes and added lines, and what
    else agents can reach: the guide, the wiki's pages (how many to check), the file map, the facts."""
    name = request.path_params["name"]
    if not repo_dir(name):
        return JSONResponse({"error": "no such repo"}, status_code=404)
    base = VAULT / "repos" / name

    def read(p, empty):
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return empty
    card, edits = read(base / "card.json", None), read(base / "card-edits.json", {})
    pages = sorted((base / "wiki").glob("*.md")) if (base / "wiki").is_dir() else []
    stale = [p.stem for p in pages if re.search(r"^reverify:", p.read_text(errors="replace")[:3000], re.M)]  # cap: parse (the front matter)
    return JSONResponse({"repo": name, "card": card, "edits": {k: edits.get(k) or [] for k in ("pinned", "struck", "added")},
                         "reach": {"guide": (CODE_DOCS / f"{name}.analysis.md").exists(), "wiki": len(pages), "stale": stale,
                                   "files": (repo_dir(name) / ".ua" / "knowledge-graph.json").exists(), "facts": (CODE_DOCS / f"{name}.facts.json").exists(),
                                   "notes": (CODE_DOCS / f"{name}.notes.json").exists()}})


def docstring_at(name, rel, loc):
    """The whole docstring that starts at a line of a repository's file (the code graph shows a docstring cut), or None."""
    m = re.match(r"L(\d+)", str(loc or ""))
    d = repo_dir(name)
    if not m or not d or not rel:
        return None
    try:
        f = (d / rel).resolve()
        if not f.is_relative_to(d.resolve()) or not f.is_file():
            return None
        lines = f.read_text(errors="replace").splitlines()
    except (OSError, ValueError):
        return None
    rest = "\n".join(lines[int(m[1]) - 1:int(m[1]) + 400])  # cap: parse (a docstring past 400 lines is shown cut by the graph)
    q = re.match(r'\s*[rbuRBU]*("""|\'\'\')(.*?)\1', rest, re.S)
    return re.sub(r"\s+", " ", q.group(2)).strip() if q else None


def file_note(name, path):
    """What a coding agent is told the first time it reads this file (MEM-32, DEC-49), as onboarding saved it, or None."""
    try:
        return json.loads((CODE_DOCS / f"{name}.notes.json").read_text()).get(path)
    except (OSError, ValueError, AttributeError):
        return None


async def api_repo_facts(request):
    """A repository's measured facts (ops/repofacts.py): what changes often and is complex, what changes together, who knows it, how old it is, and repowise's health sections. Always the same keys; available false when there are none yet; errors says what could not be found out."""
    name = request.path_params["name"]
    if not repo_dir(name):
        return JSONResponse({"error": "no such repo"}, status_code=404)
    empty = {"repo": name, "available": False, "at": None, "commit": None, "commits": None, "hotspots": [], "coupling": [], "ownership": [], "code_age": [],
             "health": {"sections": []}, "left_out": {"coupling": 0}, "errors": []}
    f = CODE_DOCS / f"{name}.facts.json"
    if not f.exists():
        return JSONResponse(empty)
    try:
        return JSONResponse({**empty, **json.loads(f.read_text()), "repo": name, "available": True})
    except (OSError, ValueError, TypeError) as e:
        return JSONResponse({**empty, "errors": [{"tool": "facts", "analysis": "", "error": f"the facts file cannot be read: {type(e).__name__}"}]})


# ---------- guide (chapters in guide/*.md; live parts come from the state and the tool list) ----------
GUIDE = Path(__file__).parent / "guide"
_guide = {"key": None, "chapters": []}


def guide_chapters():
    """Parsed chapters, ordered by file name (NN-id.md): front matter + body + its section headings and examples."""
    files = sorted(GUIDE.glob("[0-9][0-9]-*.md"))
    key = tuple((f.name, f.stat().st_mtime) for f in files)
    if _guide["key"] != key:
        out = []
        for f in files:
            text = f.read_text()
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            meta = yaml.safe_load(m[1]) if m else {}
            body = text[m.end():] if m else text
            body = body.replace("{{APP_NAME}}", app_name())          # APP-61: the guide says the app's name
            out.append({"id": f.stem.split("-", 1)[1], "title": meta.get("title", f.stem), "kicker": meta.get("kicker", ""),
                        "part": meta.get("part", ""), "icon": meta.get("icon", "doc"), "summary": meta.get("summary", ""),
                        "minutes": meta.get("minutes", 3), "views": meta.get("views", []), "body": body,
                        "sections": re.findall(r"^## (.+)$", body, re.M), "tries": len(re.findall(r"^```try$", body, re.M)),
                        "updated": int(f.stat().st_mtime)})
        _guide.update(key=key, chapters=out)
    return _guide["chapters"]


async def api_guide(request):
    """The guide's chapters (with their text when full=1)."""
    full = request.query_params.get("full") == "1"
    return JSONResponse([c if full else {k: v for k, v in c.items() if k != "body"} for c in guide_chapters()])


async def api_guide_one(request):
    """One guide chapter with its text and live blocks."""
    c = next((x for x in guide_chapters() if x["id"] == request.path_params["gid"]), None)
    return JSONResponse(c) if c else JSONResponse({"error": "no such chapter"}, status_code=404)


async def api_guide_live(request):
    """What the guide shows live besides the state: the tools Hermes has here, the chat models."""
    def about(d):
        s = re.split(r"(?<=[.:;])\s|\s\(", (d or "").strip(), maxsplit=1)[0].rstrip(".:;")
        return s if len(s) <= 140 else s[:140].rsplit(" ", 1)[0] + "…"  # cap: preview
    tools = [{"name": t.name, "about": about(t.description)} for t in await mcp.list_tools()]
    return JSONResponse({"tools": tools, "models": MODELS, "efforts": EFFORTS})


# ---------- Phoenix: the trace (full prompt and response) of a model call ----------
def phoenix_pick(spans, ts, ms=0, model=""):
    """The LiteLLM request span closest to a model call seen at ts (its start or its end, whichever the source
    recorded) with about ms duration; the model name only breaks ties. None if nothing is within 20 s."""
    from datetime import datetime
    best, best_d = None, 20.0
    for s in spans:
        if s.get("name") != "litellm_request":
            continue
        try:
            a = datetime.fromisoformat(s["start_time"]).timestamp()
            b = datetime.fromisoformat(s["end_time"]).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        d = min(abs(a - ts), abs(b - ts))
        if ms:
            d += abs((b - a) * 1000 - ms) / 4000          # a call of the same length is more likely the one
        at = s.get("attributes") or {}
        if model and model not in (at.get("litellm.model_group"), at.get("llm.model_name"), at.get("gen_ai.request.model"), at.get("gen_ai.response.model")):
            d += 1.5
        if d < best_d:
            best, best_d = s, d
    return best


async def api_phoenix(request):
    """Open in Phoenix: ?ts=<epoch>&ms=<duration>&model=<name> -> that call's trace; ?from=&to= -> the project's traces."""
    q = request.query_params
    host = (request.headers.get("host") or "localhost").split(":")[0]
    base = f"https://{host}:{PHOENIX_PORT}" if host.endswith(".ts.net") else f"http://{host}:6006"
    try:
        async with httpx.AsyncClient(timeout=10) as h:
            proj = (await h.get(f"{PHOENIX}/v1/projects")).json()["data"]
            pid = next((p["id"] for p in proj if p["name"] == "default"), proj[0]["id"])
            if not q.get("ts"):
                return RedirectResponse(f"{base}/projects/{pid}", status_code=302)
            from datetime import datetime, timezone
            ts, ms = float(q["ts"]), float(q.get("ms") or 0)
            iso = lambda x: datetime.fromtimestamp(x, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            r = await h.get(f"{PHOENIX}/v1/projects/default/spans", params={"start_time": iso(ts - ms / 1000 - 30), "end_time": iso(ts + 30), "limit": 500})
            span = phoenix_pick(r.json().get("data") or [], ts, ms, q.get("model") or "")
    except Exception as e:
        return PlainTextResponse(f"Phoenix is not reachable: {type(e).__name__}", status_code=502)
    if not span:
        return RedirectResponse(f"{base}/projects/{pid}", status_code=302)
    return RedirectResponse(f"{base}/projects/{pid}/traces/{span['context']['trace_id']}", status_code=302)


async def health(request):
    """Liveness for the deploy's smoke test: whether the runner's state file exists and how old it is."""
    return JSONResponse({"ok": STATE.exists(), "age": round(time.time() - STATE.stat().st_mtime) if STATE.exists() else None})


app = Starlette(routes=[
    Route("/", index), Route("/sw.js", sw), Route("/manifest.webmanifest", manifest), Route("/healthz", health),
    Route("/api/state", api_state), Route("/api/stream", api_stream), Route("/api/version", api_version),
    Route("/api/request", api_request, methods=["POST"]), Route("/api/result/{rid}", api_result),
    Route("/api/file", api_file), Route("/api/runlog/{rid}", api_runlog), Route("/api/run/{rid}/timeline", api_run_timeline), Route("/api/rt/runs", api_rt_runs), Route("/api/task/{tid:int}", api_task),
    Route("/api/agent/{aid}/tasks", api_agent_tasks), Route("/api/trials", api_trials), Route("/api/usage", api_usage), Route("/api/rt/run/{run}", api_rt_run),
    Route("/api/rt/run/{run}/stream", api_rt_stream), Route("/api/crew/{cid}", api_crew_one), Route("/api/swarm", api_swarm, methods=["POST"]), Route("/api/swarm/tokens", api_swarm_tokens), Route("/api/swarm/now", api_swarm_now), Route("/api/swarm/timeline", api_swarm_timeline), Route("/api/swarm/interactions", api_swarm_interactions), Route("/api/swarm/delegations", api_swarm_delegations), Route("/api/swarm/room", api_swarm_room), Route("/api/health/issues", api_health_issues), Route("/api/claude/{tid}", api_claude_task), Route("/api/phoenix", api_phoenix), Route("/api/build/{bid}/{kind}", api_build_file),
    Route("/api/change/{tid:int}/{name}", api_change_file), Route("/api/files/{slug}/{name}", api_mission_file), Route("/api/mission/{slug}/drafts", api_mission_drafts),   # MIS-23
    Route("/api/chat", api_chat, methods=["POST"]), Route("/api/chats", api_chats),
    Route("/api/chats/{cid}", api_chat_one, methods=["GET", "DELETE", "PATCH"]), Route("/api/chats/{cid}/stream", api_chat_stream),
    Route("/api/chats/{cid}/stop", api_chat_stop, methods=["POST"]), Route("/api/chats/{cid}/retry", api_chat_retry, methods=["POST"]),
    Route("/api/chat/upload", api_chat_upload, methods=["POST"]),
    Route("/api/chat/files/{fid}", api_chat_file), Route("/api/models", api_models),
    Route("/api/upload", api_upload, methods=["POST"]),
    Route("/share", share, methods=["POST"]),
    Route("/api/connections", api_connections), Route("/api/connections/grant", api_connections_grant, methods=["POST"]),
    Route("/api/connections/decide", api_connections_decide, methods=["POST"]),
    Route("/api/phone", api_phone), Route("/api/whoami", api_whoami), Route("/api/forgejo/connect", api_forgejo_connect, methods=["POST"]),
    Route("/api/house/connect", api_house_connect), Route("/api/house/callback", api_house_callback), Route("/api/house", api_house, methods=["POST"]),
    Route("/api/shop/decide", api_shop_decide, methods=["POST"]), Route("/api/shop/limits", api_shop_limits, methods=["POST"]), Route("/api/clienterror", api_clienterror, methods=["POST"]), Route("/api/view", api_view, methods=["POST"]), Route("/api/views", api_views), Route("/api/phone/decide", api_phone_decide, methods=["POST"]),
    Route("/api/phone/control", api_phone_control, methods=["POST"]), Route("/api/phone/shot/{sid}", api_phone_shot), Route("/api/share/{sid}", api_share),
    Route("/api/share/{sid}/save", api_share_save, methods=["POST"]),
    Route("/api/mail", api_mail),
    Route("/api/repo/{name}/graph", api_repo_graph), Route("/api/repo/{name}/overview", api_repo_overview),
    Route("/api/repo/{name}/node", api_repo_node), Route("/api/repo/{name}/file", api_repo_file), Route("/api/repo/{name}/card", api_repo_card), Route("/api/repo/{name}/map", api_repo_map), Route("/api/repo/{name}/facts", api_repo_facts),
    Route("/api/guide", api_guide), Route("/api/guide/live", api_guide_live), Route("/api/guide/{gid}", api_guide_one),
    Route("/api/memory/catalogue", api_memory_catalogue), Route("/api/memory/lessons", api_memory_lessons), Route("/api/memory/run", api_memory_run),
    Route("/api/journals", api_journals), Route("/api/sources", api_sources), Route("/api/skills", api_skills), Route("/api/skills/one", api_skill), Route("/api/wiki/roots", api_wiki_roots), Route("/api/wiki/graph", api_wiki_graph), Route("/api/wiki/map", api_wiki_map), Route("/api/task/map", api_task_map), Route("/api/tasks/network", api_task_network), Route("/api/ideas/origins", api_idea_origins), Route("/api/a2a/token", api_a2a_token, methods=["POST"]),
    Route("/.well-known/agent-card.json", a2a_card), Route("/a2a", api_a2a, methods=["POST"]), Route("/api/telemetry", api_telemetry), Route("/api/wiki/access", api_wiki_access),
    Route("/api/wiki/page", api_wiki_page), Route("/api/wiki/search", api_wiki_search), Route("/api/wiki/search_all", api_wiki_search_all),
    Route("/api/push/key", api_push_key), Route("/api/push/subscribe", api_push_sub, methods=["POST"]),
    Route("/api/push/unsubscribe", api_push_sub, methods=["POST"]), Route("/api/push/test", api_push_test, methods=["POST"]),
    Mount("/static", StaticFiles(directory=WEB / "static")),
], middleware=[Middleware(TailnetOnly)])


_part("server.mcp.py")   # the MCP servers Hermes calls (PLT-25)


# ---------- the voice gateway: Home Assistant's Ollama integration talks to Hermes (docs/HOME-VOICE.md, VOI-03 to VOI-05) ----------
# Its own server (8095 in the container, 127.0.0.1:11435 on the PC), only these routes, guarded by a key instead of
# Tailscale: the NAS is not on the tailnet. Each room is one "model" (hermes:kitchen); every spoken turn joins the one
# running Voice chat (the same Hermes session in every room and in the app) and the answer streams back as Ollama's
# one JSON object per line, while the app shows it live.
PROMPTS = Path(os.environ.get("PROMPTS_DIR", "/prompts"))     # prompts/ of the repository, mounted read-only (MEM-13)
SECTION = re.compile(r"^<!-- prompt: ([A-Z][A-Z0-9_]*)\b([^\n]*)-->\n(.*?)\n<!-- end -->$", re.M | re.S)   # = ops/prompts.py SECTION
VOICE_KEY = os.environ.get("VOICE_KEY", "")
VOICE_CHAT = "voicechat"
VOICE_ROOMS = ("home", "living-room", "kitchen", "office", "bedroom", "bathroom", "hallway", "guest-bath")
VOICE_MODEL = "gpt-sub-fast"          # V0: the first word in 1.3 to 1.6 s
VOICE_CHECK = "Let me check. "        # said when Hermes reaches for a tool before a word (V0: a tool answer starts after 5.5 to 6.8 s)
NEW_TOPIC = re.compile(r"^\W*(?:let'?s start over|start over|new topic|new conversation|forget that)\W*$", re.I)


def prompt(owner, name):
    """(text, ref) of one prompt, read at each call so a deployed change applies at once; ref = owner/NAME@sha."""
    t = {m.group(1): m.group(3) for m in SECTION.finditer((PROMPTS / f"{owner}.md").read_text())}[name]
    return t, f"{owner}/{name}@{hashlib.sha256(t.encode()).hexdigest()[:12]}"


def voice_ok(request):
    return bool(VOICE_KEY) and hmac.compare_digest(request.headers.get("authorization", ""), f"Bearer {VOICE_KEY}")


def room_of(model):
    r = str(model or "").removeprefix("hermes:").split(":")[0]
    return r if r in VOICE_ROOMS else "home"


def ollama_line(model, content="", done=False, **extra):
    return json.dumps({"model": model, "created_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                       "message": {"role": "assistant", "content": content}, "done": done, **extra}) + "\n"


async def voice_tags(request):
    """The models Home Assistant can pick: one per room (hermes:kitchen)."""
    if not voice_ok(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"models": [{"name": f"hermes:{r}", "model": f"hermes:{r}", "modified_at": "2026-11-01T00:00:00Z", "size": 0,
                                     "digest": hashlib.sha256(r.encode()).hexdigest(),
                                     "details": {"format": "hermes", "family": "hermes", "parameter_size": "", "quantization_level": ""}}
                                    for r in VOICE_ROOMS]})


async def voice_show(request):
    """A model's details: it completes text; no tools of Home Assistant's (Hermes has its own)."""
    if not voice_ok(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({"modelfile": "", "parameters": "", "template": "", "model_info": {}, "capabilities": ["completion"],
                         "details": {"format": "hermes", "family": "hermes", "parameter_size": "", "quantization_level": ""}})


async def voice_version(request):
    """The Ollama version the gateway answers as (the one Home Assistant's client was built against)."""
    return JSONResponse({"version": "0.6.2"})


def voice_turn(text, room):
    """Add a spoken turn to the Voice chat. -> (chat, payload, headers), or (chat, None, reply) for "new topic"."""
    c = load_chat(VOICE_CHAT) or {"id": VOICE_CHAT, "created": time.time(), "messages": [], "title": "Voice", "origin": "voice"}
    if NEW_TOPIC.match(text):
        c["hrev"] = c.get("hrev", 0) + 1                  # Hermes starts a fresh session; the chat keeps what was said
        c.pop("hsid", None)
        reply = "Sure. What's on your mind?"
        c["messages"] += [{"role": "user", "content": text, "ts": time.time(), "room": room, "attachments": []},
                          {"role": "assistant", "content": reply, "ts": time.time(), "voice": {"room": room, "new_topic": True}}]
        save_chat(c)
        return c, None, reply
    c["messages"].append({"role": "user", "content": text, "ts": time.time(), "room": room, "attachments": []})
    c["pending"] = True
    payload, headers = build_request(c, VOICE_MODEL, "low")
    frame, ref = prompt("main", "VOICE")                # the chat keeps the plain words; Hermes gets them framed
    payload["messages"][-1]["content"] = frame.format(room=room.replace("-", " "), question=text)
    c["prompt"] = ref
    save_chat(c)
    return c, payload, headers


async def voice_chat(request):
    """Ollama's /api/chat: the newest user message is the spoken turn; Home Assistant's own history and tools are not
    used (Hermes keeps the conversation and its tools)."""
    if not voice_ok(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body = await request.json()
    model = str(body.get("model") or "hermes:home")
    text = next((str(m.get("content") or "").strip() for m in reversed(body.get("messages") or []) if m.get("role") == "user"), "")
    if not text:
        return JSONResponse({"error": "no spoken text"}, status_code=400)
    text, room = cut(text, 4000, "a spoken turn"), room_of(model)  # cap: untrusted
    old = RUNNING.get(VOICE_CHAT)
    if old and not old.done():                            # a new question replaces the one still being answered
        old.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(old), 5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    try:
        c, payload, headers = voice_turn(text, room)
    except (OSError, KeyError) as e:          # the voice prompt is missing: say so, never answer without it
        payload, headers = None, f"My voice instructions could not be read ({type(e).__name__}), so I can't answer by voice right now."
    if payload is None:
        reply = headers
        if not body.get("stream", True):
            return JSONResponse(json.loads(ollama_line(model, reply, True, done_reason="stop")))
        return StreamingResponse(iter([ollama_line(model, reply), ollama_line(model, "", True, done_reason="stop")]),
                                 media_type="application/x-ndjson")
    stale = LIVE.pop(VOICE_CHAT, None)
    t0 = time.time()
    task = asyncio.get_running_loop().create_task(run_chat(c, payload, headers))
    RUNNING[VOICE_CHAT] = task
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)

    async def chunks():
        live = None
        while live is None or live is stale:              # run_chat puts its own record in LIVE at its first step
            live = LIVE.get(VOICE_CHAT)
            if task.done() and (live is None or live is stale):
                return
            await asyncio.sleep(0.02)
        sent, first, checked = 0, None, False
        while True:
            if live["tools"] and not sent and not checked:
                checked = True
                first = first or time.time()
                yield VOICE_CHECK
            new = live["text"][sent:]
            if new:
                sent += len(new)
                first = first or time.time()
                yield new
            if live["done"]:
                break
            await asyncio.sleep(0.03)
        voice_meta(room, t0, first, checked)

    if not body.get("stream", True):
        text_out = "".join([x async for x in chunks()])
        return JSONResponse(json.loads(ollama_line(model, text_out, True, done_reason="stop")))

    async def gen():
        async for piece in chunks():
            yield ollama_line(model, piece)
        yield ollama_line(model, "", True, done_reason="stop", total_duration=int((time.time() - t0) * 1e9))
    return StreamingResponse(gen(), media_type="application/x-ndjson")


def voice_meta(room, t0, first, checked):
    """The voice part of the turn's record, on the answer in the Voice chat: the room, the time to the first word, and
    whether "let me check" was said (VOI-05; the run record keeps the rest)."""
    c = load_chat(VOICE_CHAT)
    if c and c["messages"] and c["messages"][-1]["role"] == "assistant":
        c["messages"][-1]["voice"] = {"room": room, "first_ms": round((first - t0) * 1000) if first else None, "checked": checked,
                                      "ms": round((time.time() - t0) * 1000)}
        save_chat(c)


voice_app = Starlette(routes=[Route("/api/tags", voice_tags), Route("/api/show", voice_show, methods=["POST"]),
                              Route("/api/version", voice_version), Route("/api/chat", voice_chat, methods=["POST"])])


async def main():
    close_interrupted_chats()
    await asyncio.gather(
        uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8090, log_level="warning", proxy_headers=False)).serve(),
        uvicorn.Server(uvicorn.Config(mcp.streamable_http_app(transport_security=TransportSecuritySettings(
            allowed_hosts=["mission-control:8091"], allowed_origins=[])),          # only LiteLLM, by service name
            host="0.0.0.0", port=8091, log_level="warning")).serve(),
        uvicorn.Server(uvicorn.Config(claude_mcp.streamable_http_app(transport_security=TransportSecuritySettings(
            allowed_hosts=["mission-control:8092"], allowed_origins=[])), host="0.0.0.0", port=8092, log_level="warning")).serve(),
        uvicorn.Server(uvicorn.Config(house_mcp.streamable_http_app(transport_security=TransportSecuritySettings(
            allowed_hosts=["mission-control:8094"], allowed_origins=[])), host="0.0.0.0", port=8094, log_level="warning")).serve(),
        uvicorn.Server(uvicorn.Config(files_mcp.streamable_http_app(transport_security=TransportSecuritySettings(
            allowed_hosts=["mission-control:8096"], allowed_origins=[])), host="0.0.0.0", port=8096, log_level="warning")).serve(),   # MIS-24
        uvicorn.Server(uvicorn.Config(memory_mcp.streamable_http_app(transport_security=TransportSecuritySettings(
            allowed_hosts=["mission-control:8097"], allowed_origins=[])), host="0.0.0.0", port=8097, log_level="warning")).serve(),   # MEM-28
        uvicorn.Server(uvicorn.Config(memory_public_mcp.streamable_http_app(transport_security=TransportSecuritySettings(
            allowed_hosts=["mission-control:8098"], allowed_origins=[])), host="0.0.0.0", port=8098, log_level="warning")).serve(),   # MEM-30
        uvicorn.Server(uvicorn.Config(rt_app, host="0.0.0.0", port=8093, log_level="warning")).serve(),   # runtime ingest
        uvicorn.Server(uvicorn.Config(voice_app, host="0.0.0.0", port=8095, log_level="warning")).serve(),  # the voice gateway (VOI-03)
        push_events(), push_phone(), push_conn(), rt_housekeeping(), limit_retrier(), made_watcher())


if __name__ == "__main__":
    asyncio.run(main())
