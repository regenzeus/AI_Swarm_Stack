"""Mission Control: the web app (phone + desktop, installable as an app) and the mission tools for Hermes.

Port 8090: the app and its API, published to 127.0.0.1 only; reached from your devices through `tailscale serve`
(https://<pc>.ts.net:8447). Every /api call must carry Tailscale's identity header, which only tailscale serve sets.
Port 8091: MCP tools (missions_overview, mission_create, mission_update, ...) for Hermes, reached only by LiteLLM on
the internal "mcnet" network (granted per key in ops/keys.sh).
This container never starts anything itself: it reads the runner's state (/missions/public/state.json) and drops
requests into /missions/inbox; ops/missions.py on the host validates and executes them. Chats are kept in
/missions/app/chats (one JSON file each), so every device sees the same history. The wiki views read the vault.
"""
import asyncio, base64, datetime as dt, hashlib, hmac, json, os, re, shutil, time, urllib.parse, urllib.request, uuid
from pathlib import Path

import httpx
import runrecord as RT
import teamroom as TR
import uvicorn
import yaml
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
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
ACTIONS = {"claude_task", "forgejo_connect", "create", "run", "pause", "resume", "archive", "update", "memory", "email", "vault_add", "understand",
           "forget", "memory_search", "build_assign", "build_revise", "build_approve", "build_approve_all", "build_reject", "build_revert",
           "improve_scan", "proposal_accept", "proposal_dismiss", "build_recheck", "build_switch_engine", "codemap", "repo_create", "repo_buildable", "repo_remove", "crew_run", "crew_memory_forget", "crew_memory_undo", "crew_schedule",
           "journal_note", "journal_edit", "health_ack", "swarm_pause", "swarm_confirm", "swarm_reopen", "swarm_autonomy", "swarm_post", "swarm_help_verdict", "swarm_agent_change", "phone_cleanup_do", "phone_cleanup_do_all", "phone_cleanup_dismiss",
           "shop_decide", "shop_limits",           # shop_*: only through /api/shop/* (the owner, never the AI phone or an agent)
           "house_connect", "house_switch", "house_alexa", "house_say", "house_settings", "house_status",   # house_*: /api/house* and the house MCP tools
           "notify_prefs", "chat_ready",           # notify_*: the owner's notification preferences; chat_ready: from the app itself
           "task_create", "task_answer", "task_approve", "task_cancel", "task_retry", "task_run", "task_conduct",   # task_*: the task kernel (TSK-01 to TSK-04, TSK-21, TSK-22)
           "rule_save", "rule_toggle", "rule_delete", "event_rate", "calendar_set", "calendar_clear",
           "a2a_settings", "a2a_token", "a2a_revoke",
           "wiki_delete"}                                  # ops/wikis.py: from the app only (refused from the AI phone above)                                    # TSK-19: outside agents (A2A)                      # the event bus's rules and ratings (TSK-10 to TSK-12)
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


# ---------- app API ----------
class TailnetOnly(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path.startswith(("/api/", "/share")) and not request.headers.get("tailscale-user-login"):
            return JSONResponse({"error": "only reachable through Tailscale"}, status_code=403)
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


async def api_state(request):
    """The runner's whole state (missions, runs, builds, crew, health, system …) plus the phone, the connections and who is viewing."""
    s = state()
    s["phone"] = phone_summary()
    s["connections"] = conn_summary()
    s["viewer"] = request.headers.get("tailscale-user-name") or request.headers.get("tailscale-user-login", "")
    s["viewer_name"] = display_name(request.headers.get("tailscale-user-name", ""), request.headers.get("tailscale-user-login", ""))
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
                yield f"data: {json.dumps({**state(), 'phone': ph, 'connections': cs}, ensure_ascii=False)}\n\n"
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
    if not isinstance(body, dict) or len(json.dumps(body)) > 20000:
        return JSONResponse({"ok": False, "error": "invalid"}, status_code=400)
    if str(body.get("action", "")).startswith("shop_"):
        return JSONResponse({"ok": False, "error": "purchases are decided at /api/shop/decide"}, status_code=403)
    if str(body.get("action", "")).startswith("house_"):
        return JSONResponse({"ok": False, "error": "the House is controlled through /api/house"}, status_code=403)
    if body.get("action") == "a2a_token":                                   # the token is made at /api/a2a/token, shown once
        return JSONResponse({"ok": False, "error": "outside agents are added at /api/a2a/token"}, status_code=403)
    if body.get("action") in ("wiki_delete", "calendar_set", "calendar_clear", "a2a_settings", "a2a_revoke") and from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    if str(body.get("action", "")).startswith("swarm_") and from_ai_phone(request):   # pausing, confirming, autonomy: the owner's devices only
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    if body.get("action") in ("phone_cleanup_do", "phone_cleanup_do_all") and from_ai_phone(request):   # the AI phone never approves its own cleanup
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    if str(body.get("action", "")).startswith(("task_", "rule_", "event_")) and from_ai_phone(request):   # the AI phone gives the stack no work of its own
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    if body.get("action") == "notify_prefs" and from_ai_phone(request):   # the AI phone cannot silence what the owner is told
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    if body.get("action") == "chat_ready":                                 # sent by the app itself when a waiting chat is answered
        return JSONResponse({"ok": False, "error": "not a request the app's screens make"}, status_code=403)
    body["source"] = "app"
    return JSONResponse(await submit(body))


async def api_result(request):
    """The runner's answer to one request, or {pending: true} while it works."""
    rid = request.path_params["rid"]
    f = RESULTS / f"{rid}.json"
    if not re.fullmatch(r"[a-f0-9]{16}", rid):
        return JSONResponse({"error": "invalid"}, status_code=400)
    return JSONResponse(json.loads(f.read_text()) if f.exists() else {"pending": True})


def vault_file(rel):
    p = (VAULT / rel).resolve()
    ok = rel.endswith(".md") and p.is_relative_to(VAULT.resolve()) and p.is_file() and not rel.startswith((".", "raw/_files"))
    return p if ok else None


async def api_file(request):
    """A vault file as text, for the reading view; only paths inside the vault."""
    p = vault_file(request.query_params.get("path", ""))
    return PlainTextResponse(p.read_text(errors="replace")) if p else JSONResponse({"error": "not allowed"}, status_code=404)


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


async def api_swarm_timeline(request):
    """SWM-103: every agent's runs in the window (at most 7 days), as bars of its lane, with what started each."""
    return JSONResponse(await asyncio.to_thread(RT.timeline, _hours(request, 24)))


async def api_swarm_interactions(request):
    """SWM-104: who starts whom, from the runtime record (the Board's messages come from the Swarm service's graph)."""
    return JSONResponse(await asyncio.to_thread(RT.interactions, _hours(request, 168)))


async def api_swarm_delegations(request):
    """SWM-105: what agents ask each other through their tools, as exchanges for the Chatroom (pair=a+b: two agents)."""
    return JSONResponse(await asyncio.to_thread(RT.delegations, _hours(request, 168), request.query_params.get("pair") or None))


async def api_swarm_room(request):
    """SWM-107: the team room, one timeline of what the agents do together (teamroom.py), at most 7 days: the Ledger's
    events and the Board's messages (Swarm service), the tool calls between agents and the runs no one asked for (runtime
    record). If the Swarm service is down, the runtime record's lines still come, with the error named."""
    hours = _hours(request, 24)

    def go():
        now, err = time.time(), ""
        try:
            feed = _swarm_app("feed", {"since": now - hours * 3600}).get("result") or {}
        except Exception as e:
            feed, err = {}, f"the swarm is not reachable ({type(e).__name__}): its events and messages are missing"
        return {"since": now - hours * 3600, "now": now, "error": err,
                "lines": TR.lines(feed, RT.delegations(hours, None, now), RT.timeline(hours, now)["runs"])}
    return JSONResponse(await asyncio.to_thread(go))


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


# ---------- chats (server-side history) ----------
def chat_path(cid):
    return CHATS / f"{cid}.json" if re.fullmatch(r"[a-z0-9]{6,24}", cid or "") else None


def load_chat(cid):
    p = chat_path(cid)
    try:
        return json.loads(p.read_text()) if p else None
    except FileNotFoundError:
        return None


RT.CHAT_TITLE = lambda cid: (load_chat(cid) or {}).get("title")      # run names: "Chat · <title>"


def save_chat(c):
    CHATS.mkdir(parents=True, exist_ok=True)
    c["updated"] = time.time()
    tmp = CHATS / f".{c['id']}.tmp"
    tmp.write_text(json.dumps(c, ensure_ascii=False))
    tmp.rename(chat_path(c["id"]))


MODELS = [{"id": "gpt-sub", "name": "GPT-6.1 Sol", "note": "strongest, ChatGPT subscription"},
          {"id": "gpt-sub-fast", "name": "GPT-6 Luna", "note": "fast, ChatGPT subscription"}]
EFFORTS = ["low", "medium", "high", "xhigh"]
FILES = CHATS / "files"
DOC_EXT = (".pdf", ".docx", ".xlsx", ".csv", ".txt", ".md", ".json", ".html", ".py", ".js", ".ts", ".yaml", ".yml", ".log")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif")


async def api_models(request):
    """The chat's model choices and reasoning efforts, with the default."""
    return JSONResponse({"models": MODELS, "efforts": EFFORTS, "default": {"model": "gpt-sub", "effort": "medium"}})


def chat_summary(c):
    return {k: c.get(k) for k in ("id", "title", "mission", "updated", "pinned", "pending", "origin")} | {"count": len(c.get("messages", []))}


def origin_of(request):
    """Who started a chat: "owner" from your own devices (through tailscale serve, which adds your login and the
    device's address), "ai-phone", or "automation" (the stack's own checks and helper agents call the app directly)."""
    ip = client_ip(request)
    if ip == AI_PHONE_IP:
        return "ai-phone"
    return "owner" if ip and request.headers.get("tailscale-user-login") else "automation"


async def api_chats(request):
    """The owner's chats, newest first, optionally filtered by a search text."""
    q = request.query_params.get("q", "").strip().lower()
    out = []
    for p in CHATS.glob("*.json") if CHATS.exists() else []:
        try:
            c = json.loads(p.read_text())
        except Exception:
            continue
        if q and q not in (c.get("title") or "").lower() and not any(q in m.get("content", "").lower() for m in c.get("messages", [])):
            continue
        out.append(chat_summary(c))
    return JSONResponse(sorted(out, key=lambda c: (not c.get("pinned"), -c["updated"])))


async def api_chat_one(request):
    """One chat: GET reads it, PATCH renames or pins it, DELETE removes it with its attached files."""
    cid = request.path_params["cid"]
    c = load_chat(cid)
    if request.method == "DELETE":
        p = chat_path(cid)
        if p and p.exists():
            for a in (c or {}).get("files", []):
                for f in FILES.glob(f"{a}*"):
                    f.unlink(missing_ok=True)
            p.unlink()
        return JSONResponse({"ok": True})
    if not c:
        return JSONResponse({"error": "not found"}, status_code=404)
    if request.method == "PATCH":
        body = await request.json()
        if "title" in body:
            t = re.sub(r"\s+", " ", str(body["title"])).strip()
            if len(t) > 200:
                return JSONResponse({"ok": False, "error": f"the title is {len(t)} characters; the limit is 200"}, status_code=400)
            c["title"] = t or c.get("title")
        if "pinned" in body:
            c["pinned"] = bool(body["pinned"])
        updated = c.get("updated")
        save_chat(c)
        c["updated"] = updated
        return JSONResponse(chat_summary(c))
    return JSONResponse(c)


def mission_context(slug):
    m = mission(slug)
    if not m:
        return ""
    d = {k: m.get(k) for k in ("title", "type", "status", "schedule_text", "goal", "depth", "triggers", "brief", "notes")}
    d["last_runs"] = [{k: r.get(k) for k in ("started", "status", "summary")} for r in (m.get("runs") or [])[:3]]
    return (f"This conversation is about the mission '{m['title']}' (slug '{slug}'). Help the owner tune its focus: discuss what "
            "it should track, then apply agreed changes with mission_update (briefings: key_questions, searches, watchlist, "
            "notes; tasks: goal) or mission_set_triggers, using this slug, and say exactly what you changed. To answer "
            "questions about its results, search the vault (its reports, alerts and wiki).\nCurrent mission:\n"
            + TC.cut(json.dumps(d, ensure_ascii=False), 6000))  # cap: prompt


def doc_text(path, name):
    """Readable text of an attached document (Hermes' API takes images, not files)."""
    n = name.lower()
    try:
        if n.endswith(".pdf"):
            from pypdf import PdfReader
            r = PdfReader(str(path))
            return "\n\n".join(f"--- page {i} ---\n{(pg.extract_text() or '').strip()}" for i, pg in enumerate(r.pages[:300], 1)) + (f"\n\n(only the first 300 of {len(r.pages)} pages)" if len(r.pages) > 300 else "")  # cap: prompt
        if n.endswith(".docx"):
            import docx
            d = docx.Document(str(path))
            parts = [para.text for para in d.paragraphs]
            for t in d.tables:
                parts += [" | ".join(cell.text for cell in row.cells) for row in t.rows]
            return "\n".join(parts)
        if n.endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets[:10]:
                out.append(f"--- sheet {ws.title} ---")
                for row in ws.iter_rows(max_row=2000, values_only=True):
                    out.append(" | ".join("" if v is None else str(v) for v in row))
            return "\n".join(out)
        return path.read_text(errors="replace")
    except Exception as e:
        return f"(could not read {name}: {type(e).__name__})"


async def api_chat_upload(request):
    """An attachment for the next chat message: images go to Hermes as images, documents as extracted text."""
    info, err = await store_attachment(request.headers.get("x-filename", "file"), await request.body())
    return JSONResponse({"error": err}, status_code=400) if err else JSONResponse(info)


async def store_attachment(name, data):
    """Keep a file for a chat message (also what the phone shares); returns (info, None) or (None, error)."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name or "file")[-80:].lstrip(".-") or "file"  # cap: id
    low = name.lower()
    kind = "image" if low.endswith(IMG_EXT) else "doc" if low.endswith(DOC_EXT) else None
    if not kind:
        return None, "supported: images, PDF, Word, Excel, CSV, text and code files"
    if len(data) > (15 if kind == "image" else 30) * 1024 * 1024:
        return None, "file too large"
    FILES.mkdir(parents=True, exist_ok=True)
    fid = uuid.uuid4().hex[:16]
    path = FILES / f"{fid}-{name}"
    path.write_bytes(data)
    info = {"id": fid, "name": name, "kind": kind, "size": len(data)}
    if kind == "doc":
        text = await asyncio.to_thread(doc_text, path, name)
        (FILES / f"{fid}.txt").write_text(text)
        info["chars"] = len(text)
    return info, None


# ---------- share target: the phone's Share menu -> Mission Control (manifest share_target) ----------
# Whatever is shared (a link, text, pictures, documents) is only kept here; the app then asks what to do with it.
# Nothing runs by itself, so a forged POST from another site can at most leave an item in this list.
SHARES = DATA / "shares"
URL_IN_TEXT = re.compile(r"https?://[^\s<>\"]+")


async def share(request):
    """The PWA share target: keeps what was shared (link, text, pictures, files) for 14 days and opens it in the app (APP-15)."""
    form = await request.form(max_files=6, max_fields=10)
    rec = {"id": uuid.uuid4().hex[:16], "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "title": TC.cut(str(form.get("title") or ""), 300).strip(),  # cap: untrusted
           "text": cut(str(form.get("text") or "").strip(), 200000), "url": str(form.get("url") or "")[:2000].strip(),  # cap: api (a URL; a marker would break it)
           "files": [], "errors": []}
    if not rec["url"] and (m := URL_IN_TEXT.search(rec["text"])):     # Android apps usually put the link in the text
        rec["url"] = m.group(0).rstrip(").,;")
    if rec["url"] and not rec["url"].startswith(("http://", "https://")):
        rec["url"] = ""
    for f in form.getlist("files"):
        if hasattr(f, "read"):
            info, err = await store_attachment(f.filename or "shared", await f.read())
            rec["files"].append(info) if info else rec["errors"].append(f"{f.filename}: {err}")
    SHARES.mkdir(parents=True, exist_ok=True)
    for old in SHARES.glob("*.json"):                                   # keep two weeks
        if time.time() - old.stat().st_mtime > 14 * 86400:
            old.unlink(missing_ok=True)
    (SHARES / f"{rec['id']}.json").write_text(json.dumps(rec, ensure_ascii=False))
    return RedirectResponse(f"/#/share/{rec['id']}", status_code=303)


def share_rec(sid):
    p = SHARES / f"{sid}.json"
    return json.loads(p.read_text()) if re.fullmatch(r"[a-f0-9]{16}", sid or "") and p.exists() else None


async def api_share(request):
    """One shared item, for its page with the one-tap choices."""
    rec = share_rec(request.path_params["sid"])
    return JSONResponse(rec) if rec else JSONResponse({"error": "not found"}, status_code=404)


async def api_share_save(request):
    """Save a shared item into the knowledge base: the link's page, the text, and every document or picture."""
    rec = share_rec(request.path_params["sid"])
    if not rec:
        return JSONResponse({"error": "not found"}, status_code=404)
    done = []
    if rec["url"]:
        done.append(await submit({"action": "vault_add", "title": rec["title"], "url": rec["url"], "source": "app"}, wait=20))
    elif rec["text"]:
        done.append(await submit({"action": "vault_add", "title": rec["title"] or rec["text"][:60], "text": rec["text"], "source": "app"}, wait=20))  # cap: id
    UPLOADS.mkdir(parents=True, exist_ok=True)
    for f in rec["files"]:
        src = file_of(f["id"])
        if src and f["name"].lower().endswith((".pdf", ".docx", ".md", ".txt", ".html", ".xlsx", ".csv", ".png", ".jpg")):
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{f['name']}"
            shutil.copyfile(src, UPLOADS / name)
            (UPLOADS / name).chmod(0o644)
            done.append(await submit({"action": "vault_add", "upload": name, "title": rec["title"], "source": "app"}, wait=20))
    ok = [d for d in done if d.get("ok", True) and not d.get("error")]
    return JSONResponse({"saved": len(ok), "of": len(done), "errors": [d.get("error") for d in done if d.get("error")]})


def file_of(fid):
    if not re.fullmatch(r"[a-f0-9]{16}", fid or ""):
        return None
    return next(iter(FILES.glob(f"{fid}-*")), None)


async def api_chat_file(request):
    """A file attached to a chat."""
    f = file_of(request.path_params["fid"])
    return FileResponse(f) if f else JSONResponse({"error": "not found"}, status_code=404)


def to_hermes(m, current):
    """One stored message as Hermes input: documents as text (recent turns), images only on the current turn."""
    if m["role"] != "user" or not m.get("attachments"):
        return {"role": m["role"], "content": m["content"]}
    text, images = m["content"], []
    for a in m["attachments"]:
        if a["kind"] == "doc":
            t = FILES / f"{a['id']}.txt"
            body = cut(t.read_text(), 120000, "the model reads the start of the document") if t.exists() else "(not readable)"  # cap: prompt
            text += f"\n\n[Attached document: {a['name']}]\n{body}\n[End of {a['name']}]"
        elif current and (f := file_of(a["id"])):
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(f.suffix.lstrip(".").lower(), "png")
            images.append({"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{base64.b64encode(f.read_bytes()).decode()}"}})
        else:
            text += f"\n\n[Image attached earlier: {a['name']}]"
    return {"role": "user", "content": [{"type": "text", "text": text}] + images if images else text}


def build_request(c, model, effort):
    """Hermes request for the newest turn. Hermes keeps the conversation server-side (X-Hermes-Session-Id: its history,
    tool calls included, comes from Hermes' state.db, which also compresses long chats), so only the new message is
    sent: no re-sending of earlier turns, documents or pictures. A chat without a Hermes session yet (older chats) or
    one that was cut back (edit / regenerate) starts a new session, seeded once with the earlier turns as context."""
    system = [f"chat mission-control-{c['id']}"]
    if c.get("mission"):
        system.append(mission_context(c["mission"]))
    msgs = c["messages"]
    if not c.get("hsid"):
        c["hsid"] = f"mc-{c['id']}-{c.get('hrev', 0)}"
        earlier = msgs[:-1][-12:]
        if earlier:
            system.append("Earlier in this conversation (context; these turns are already answered):\n\n" +
                          "\n\n".join(f"{m['role']}: {TC.cut(m['content'], 4000)}" for m in earlier))  # cap: prompt
    payload = {"model": model, "provider": "custom", "model_options": {"reasoning_effort": effort}, "stream": True,
               "messages": [{"role": "system", "content": "\n\n".join(system)}, to_hermes(msgs[-1], True)]}
    return payload, {"X-Hermes-Session-Id": c["hsid"]}


LIVE = {}            # chat id -> answer in progress: text, reasoning, tools, done; the Hermes call is a background task
RUNNING = {}         # chat id -> asyncio task (for stop)
LIMITED = {}         # chat id -> when its message is tried again (AST-12: the subscription's usage limit)
LIMIT = re.compile(r"usage.?limit|rate.?limit|ratelimit|\b429\b|too many requests|hit your limit", re.I)
LIMIT_RETRY = 15 * 60                    # no reset time in the error: try again every 15 minutes
LIMIT_GIVE_UP = 24 * 3600                # still limited after a day: stop and say so


def reset_in(text):
    """Seconds until the usage limit resets, from the provider's error (ChatGPT sends resets_at), or None."""
    m = re.search(r'resets?_in_seconds\W{0,3}(\d+)', text)
    if m:
        return int(m[1])
    m = re.search(r'resets?_at\W{0,3}(\d{10})', text)
    if m:
        return max(0, int(m[1]) - int(time.time()))
    m = re.search(r"(?:try again|resets?) in (?:about )?(\d+(?:\.\d+)?)\s*(s|sec|seconds?|m|min|minutes?|h|hours?)\b", text, re.I)
    return int(float(m[1]) * {"s": 1, "m": 60, "h": 3600}[m[2][0].lower()]) if m else None


def limit_of(status, text, tools=()):
    """AST-12: did the answer fail on the subscription's usage limit (not a real error)? -> (bool, seconds to reset).
    A normal answer that talks about rate limits is not one: it has to be a short error without any tool work."""
    t = text or ""
    hit = status == 429 or (status not in (None, 200) and LIMIT.search(t)) or (
        not tools and len(t) < 2000 and re.search(r"RateLimitError|usage_limit_reached|usage limit (?:has been |was )?reached|hit your limit", t, re.I))
    return (True, reset_in(t)) if hit else (False, None)


def tool_label(d):
    name = str(d.get("tool") or d.get("name") or d.get("tool_name") or "tool")
    name = re.sub(r"^mcp__\w+?__", "", name)
    return {"name": name, "status": str(d.get("status") or d.get("event") or d.get("phase") or ""),
            "detail": str(d.get("preview") or d.get("summary") or d.get("args_preview") or d.get("message") or "")}


async def run_chat(c, payload, headers=None, retry=False):
    """Talk to Hermes in the background: the answer is saved even if the phone drops the connection or sleeps. On the
    usage limit the message is kept and answered by itself after the reset (AST-12, limit_retrier)."""
    live = LIVE[c["id"]] = {"text": "", "reasoning": "", "tools": [], "done": False, "stopped": False, "status": None}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1800, connect=10)) as h:
            async with h.stream("POST", HERMES, json=payload,
                                headers={"Authorization": f"Bearer {HERMES_KEY}", **(headers or {})}) as r:
                live["status"] = r.status_code
                if r.status_code != 200:
                    live["text"] = f"⚠ Hermes answered HTTP {r.status_code}: {cut((await r.aread()).decode(errors='replace'), 4000)}"  # cap: untrusted
                else:
                    ev = ""
                    async for line in r.aiter_lines():
                        if line.startswith("event:"):
                            ev = line[6:].strip()
                            continue
                        if not line.startswith("data: ") or line == "data: [DONE]":
                            if not line:
                                ev = ""
                            continue
                        try:
                            j = json.loads(line[6:])
                        except Exception:
                            continue
                        if ev == "hermes.tool.progress":
                            t = tool_label(j)
                            same = next((x for x in live["tools"] if x["name"] == t["name"] and x["status"] != "completed"), None)
                            if same and t["status"] in ("completed", "done", "finished", "error", "failed"):
                                same.update(status="completed" if t["status"] in ("completed", "done", "finished") else "failed")
                            elif not same or t["detail"] != same["detail"]:
                                live["tools"].append(t)
                            continue
                        ch = (j.get("choices") or [{}])[0]
                        delta = ch.get("delta", {})
                        live["text"] += delta.get("content") or ""
                        if ch.get("finish_reason") in ("length", "max_tokens"):
                            live["cut"] = True                # the model stopped at its output limit: said under the answer
                        live["reasoning"] += delta.get("reasoning_content") or delta.get("reasoning") or ""
    except asyncio.CancelledError:
        live["stopped"] = True
    except Exception as e:
        live["text"] += f"\n\n⚠ Hermes not reachable ({type(e).__name__})"
    finally:
        c = load_chat(c["id"]) or c
        limited, reset = (False, None) if live["stopped"] else limit_of(live["status"], live["text"], live["tools"])
        effort = (payload.get("model_options") or {}).get("reasoning_effort")
        if limited:
            now, prev = time.time(), c.get("limit") or {}
            at = now + (reset + 60 if reset is not None else LIMIT_RETRY)
            c["limit"] = {"retry_at": at, "since": prev.get("since", now), "tries": prev.get("tries", 0) + 1,
                          "model": payload.get("model"), "effort": effort, "reset_known": reset is not None}
            c["messages"].append({"role": "assistant", "ts": now, "limit": {"retry_at": at, "reset_known": reset is not None},
                                  "detail": live["text"], "model": payload.get("model"),
                                  "content": "⏳ **The ChatGPT subscription's usage limit is reached.** Your message is kept and is answered "
                                             "here by itself " + ("when the limit resets." if reset is not None else
                                                                  "as soon as the limit is over (it tries every 15 minutes).")
                                             + " You get a notification when the answer is ready."})
            LIMITED[c["id"]] = at
        else:
            c["messages"].append({"role": "assistant", "ts": time.time(),
                                  "content": (live["text"] or ("_(stopped)_" if live["stopped"] else "(no answer)")) + ("\n\n_(stopped)_" if live["stopped"] and live["text"] else "")
                                  + ("\n\n_(The answer stopped at the model's output limit. Ask it to go on.)_" if live.get("cut") else ""),
                                  "reasoning": tail(live["reasoning"], 200000), "tools": live["tools"][-400:],  # cap: list (the newest 400 tool calls; the run record keeps every one)
                                  "model": payload.get("model"), "effort": effort})
            if c.pop("limit", None) is not None:
                LIMITED.pop(c["id"], None)
                if retry and live["text"]:                # the owner may have left: tell them through the one path (OBS-16)
                    await submit({"action": "chat_ready", "chat": c["id"], "title": c.get("title", "")}, wait=0)
        c["pending"] = False
        save_chat(c)
        live["done"] = True
        RUNNING.pop(c["id"], None)
    await asyncio.sleep(120)
    LIVE.pop(c["id"], None)


async def api_chat(request):
    """Start a chat turn: stored at once, answered in the background; follow it with /api/chats/<id>/stream.
    Body: message, chat?, mission?, model?, effort?, attachments? [ids from /api/chat/upload], truncate? (edit/regenerate:
    drop messages from this index first)."""
    body = await request.json()
    text = str(body.get("message", "")).strip()
    if len(text) > 100000:
        return JSONResponse({"ok": False, "error": f"the message is {len(text):,} characters; the limit is 100,000: attach it as a document"}, status_code=400)
    atts = []
    for a in body.get("attachments") or []:
        f = file_of(a.get("id"))
        if f:
            atts.append({"id": a["id"], "name": f.name.split("-", 1)[1], "kind": "image" if f.name.lower().endswith(IMG_EXT) else "doc"})
    if not text and not atts:
        return JSONResponse({"error": "empty"}, status_code=400)
    c = load_chat(body.get("chat")) or {"id": uuid.uuid4().hex[:12], "created": time.time(), "messages": [],
                                        "mission": body.get("mission") if mission(body.get("mission") or "") else None,
                                        "origin": origin_of(request)}
    if c.get("pending") and c["id"] in LIVE and not LIVE[c["id"]]["done"]:
        return JSONResponse({"error": "still answering the last message"}, status_code=409)
    if isinstance(body.get("truncate"), int) and 0 <= body["truncate"] <= len(c["messages"]):
        c["messages"] = c["messages"][:body["truncate"]]
        c["hrev"] = c.get("hrev", 0) + 1          # Hermes' copy can't be cut back: continue in a fresh session
        c.pop("hsid", None)
    if not c["messages"]:
        c["title"] = (f"{mission(c['mission'])['title']}: " if c.get("mission") else "") + re.sub(r"\s+", " ", text or atts[0]["name"])[:60]  # cap: id
    model = body.get("model") if body.get("model") in {m["id"] for m in MODELS} else "gpt-sub"
    effort = body.get("effort") if body.get("effort") in EFFORTS else "medium"
    c["messages"].append({"role": "user", "content": text or "(see attachment)", "ts": time.time(), "attachments": atts})
    if c.pop("limit", None) is not None:          # a new message replaces the one that waited for the usage limit
        LIMITED.pop(c["id"], None)
    c["files"] = sorted(set(c.get("files", []) + [a["id"] for a in atts]))
    c["pending"] = True
    payload, headers = build_request(c, model, effort)
    save_chat(c)
    t = asyncio.get_running_loop().create_task(run_chat(c, payload, headers))
    RUNNING[c["id"]] = t
    TASKS.add(t)
    t.add_done_callback(TASKS.discard)
    return JSONResponse({"chat": c["id"], "title": c["title"]})


async def api_chat_retry(request):
    """Try a message that waits for the usage limit now, instead of at its next try (AST-12)."""
    cid = request.path_params["cid"]
    c = load_chat(cid)
    if not c or not c.get("limit"):
        return JSONResponse({"ok": False, "error": "nothing waits for the usage limit in this chat"})
    LIMITED[cid] = time.time()
    return JSONResponse({"ok": True})


async def limit_retrier():
    """AST-12: a chat message that hit the usage limit is sent again at its retry time; after a day it stops and says so."""
    for p in CHATS.glob("*.json") if CHATS.exists() else []:        # waiting messages survive a restart of the app
        try:
            c = json.loads(p.read_text())
            if c.get("limit"):
                LIMITED[c["id"]] = c["limit"]["retry_at"]
        except (OSError, ValueError, KeyError) as e:
            print(f"chat {p.name}: its usage-limit wait was not read: {type(e).__name__}", flush=True)
    while True:
        await asyncio.sleep(20)
        retry_due()


def retry_due():
    """One pass: every waiting chat message whose time has come is sent to Hermes again."""
    for cid, at in list(LIMITED.items()):
        if at > time.time() or cid in RUNNING:
            continue
        LIMITED.pop(cid, None)
        c = load_chat(cid)
        if not c or not c.get("limit") or c.get("pending"):
            continue
        lim = c["limit"]
        while c["messages"] and c["messages"][-1].get("limit"):
            c["messages"].pop()                           # the waiting notice gives way to the answer
        if time.time() - lim["since"] > LIMIT_GIVE_UP or not c["messages"] or c["messages"][-1]["role"] != "user":
            c.pop("limit")
            c["messages"].append({"role": "assistant", "ts": time.time(), "content": "⚠ The usage limit did not end within a day, "
                                  "so this message was not answered. Send it again when the subscription works again."})
            save_chat(c)
            continue
        c["pending"] = True
        payload, headers = build_request(c, lim.get("model") or "gpt-sub", lim.get("effort") or "medium")
        save_chat(c)
        t = asyncio.get_running_loop().create_task(run_chat(c, payload, headers, retry=True))
        RUNNING[cid] = t
        TASKS.add(t)
        t.add_done_callback(TASKS.discard)


async def api_chat_stop(request):
    """Stops the answer that is being written in a chat."""
    t = RUNNING.get(request.path_params["cid"])
    if t and not t.done():
        t.cancel()
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "nothing running"})


TASKS = set()


async def api_chat_stream(request):
    """SSE of the answer in progress: {text, reasoning, tools, done}; keep-alive pings; reconnectable."""
    cid = request.path_params["cid"]

    async def gen():
        yield "retry: 2000\n\n"
        last, t0 = None, time.time()
        while not await request.is_disconnected():
            live = LIVE.get(cid)
            if live:
                cur = {k: live[k] for k in ("text", "reasoning", "tools", "done", "stopped")}
            else:
                c = load_chat(cid) or {}
                done = not c.get("pending")
                m = (c.get("messages") or [{}])[-1] if done else {}
                cur = {"text": m.get("content", ""), "reasoning": m.get("reasoning", ""), "tools": m.get("tools", []), "done": done, "stopped": False}
            sig = json.dumps(cur, sort_keys=True)
            if sig != last:
                last = sig
                yield f"data: {sig}\n\n"
            if cur["done"]:
                return
            if time.time() - t0 > 10:
                yield ": ping\n\n"
                t0 = time.time()
            await asyncio.sleep(0.5)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


UPLOADS = DATA / "uploads"


async def api_upload(request):
    """A file from the phone for the vault inbox (PDF, Word, text, markdown); the runner files it."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", request.headers.get("x-filename", "upload"))[-80:].lstrip(".-") or "upload"  # cap: id
    if not name.lower().endswith((".pdf", ".docx", ".md", ".txt", ".html", ".pptx", ".xlsx", ".csv", ".png", ".jpg")):
        return JSONResponse({"ok": False, "error": "file type not supported"}, status_code=400)
    data = await request.body()
    if len(data) > 25 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "file too large (25 MB max)"}, status_code=400)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
    (UPLOADS / name).write_bytes(data)
    (UPLOADS / name).chmod(0o644)
    return JSONResponse(await submit({"action": "vault_add", "upload": name, "title": request.headers.get("x-title", ""), "source": "app"}, wait=20))


# ---------- wiki (Obsidian-style views of the vault wiki and the mission wikis) ----------
LINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")


def wiki_roots():
    """Every wiki: the vault's, then each mission's, an archived mission's last (its files stay; FND-61)."""
    roots = [{"root": "wiki", "title": "Vault wiki", "mission": None, "archived": False}]
    st = state()
    for m in st["missions"]:
        if m.get("wiki") and (VAULT / m["wiki"]).exists():
            roots.append({"root": m["wiki"], "title": m["title"], "mission": m["slug"], "archived": m.get("status") == "archived"})
    for t in st.get("tasks") or []:                      # a briefing task's topic without a mission of its own (TSK-22)
        r = f"topics/{t['topic']}/wiki" if t.get("topic") else None
        if r and (VAULT / r).exists() and r not in {x["root"] for x in roots}:
            roots.append({"root": r, "title": t["title"], "mission": None, "task": t["id"], "archived": t.get("status") == "cancelled"})
    return sorted(roots, key=lambda r: r["archived"])


def front(text):
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return {}, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except Exception:
        return {}, m.group(2)


_wiki_cache = {}


def wiki(root):
    """Pages, a resolver for [[links]], forward links and backlinks of one wiki root (cached by mtime)."""
    base = VAULT / root
    files = sorted(base.rglob("*.md"))
    sig = (len(files), max((f.stat().st_mtime for f in files), default=0))
    if _wiki_cache.get(root, {}).get("sig") == sig:
        return _wiki_cache[root]
    pages = {}
    for f in files:
        with f.open(encoding="utf-8", errors="replace", newline="") as source:
            markdown = source.read()
        # Keep the copy source intact; parsing/rendering still uses normalized newlines.
        meta, body = front(markdown.replace("\r\n", "\n").replace("\r", "\n"))
        pid = str(f.relative_to(base))[:-3]
        pages[pid] = {"id": pid, "title": str(meta.get("title") or f.stem.replace("-", " ").title()), "type": meta.get("type", ""),
                      "summary": str(meta.get("summary", "")), "folder": pid.split("/")[0] if "/" in pid else "",
                      "aliases": meta.get("aliases") or [], "body": body, "meta": meta, "markdown": markdown}
    names = {}
    for p in pages.values():
        for n in [p["id"], p["id"].split("/")[-1], p["title"], *p["aliases"]]:
            names.setdefault(str(n).lower(), p["id"])

    def resolve(target):
        t = target.strip().lower().removesuffix(".md")
        for cand in (t, t.removeprefix(root.lower() + "/"), t.split("/")[-1]):
            if cand in names:
                return ("page", names[cand])
        if (VAULT / f"{target.strip()}.md").is_file():
            return ("file", f"{target.strip()}.md")
        return (None, None)
    links, back = {}, {}
    for p in pages.values():
        out = set()
        for mm in LINK.finditer(p["body"]):
            kind, ref = resolve(mm.group(1))
            if kind == "page" and ref != p["id"]:
                out.add(ref)
                back.setdefault(ref, set()).add(p["id"])
        links[p["id"]] = out
    w = {"sig": sig, "pages": pages, "resolve": resolve, "links": links, "back": back}
    _wiki_cache[root] = w
    return w


def root_ok(root):
    return root in {r["root"] for r in wiki_roots()}


async def api_wiki_roots(request):
    """Every wiki (the vault's and each mission's) with pages, links, summary and whether its mission is archived."""
    out = []
    try:
        summaries = json.loads((M / "public/wiki-summaries.json").read_text())     # ops/wikis.py
    except Exception:
        summaries = {}
    for r in wiki_roots():
        w = wiki(r["root"])
        out.append(r | {"summary": (summaries.get(r["root"]) or {}).get("summary", ""), "pages": len([p for p in w["pages"] if p != "index"]), "links": sum(len(v) for v in w["links"].values())})
    return JSONResponse(out)


SUBJECT_STOP = {"index", "overview", "sources", "log", "summary"}


def subject(title):
    """A page title as a subject two wikis can share: lower case, without a parenthesis or punctuation."""
    t = re.sub(r"\([^)]*\)", " ", str(title).lower())
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t if len(t) >= 4 and t not in SUBJECT_STOP else ""


async def api_telemetry(request):
    """TSK-25: the daily telemetry history per agent, model, harness and kind (a year), and the price table (ops/history.py)."""
    f = TELEMETRY
    if not f.exists():
        return JSONResponse({"rows": [], "prices": {}, "error": "No history yet: the runner writes it within the hour."})
    return PlainTextResponse(f.read_text(), media_type="application/json")


# ---------- TSK-19: outside agents over A2A (ops/a2a.py), on the tailnet, off until the owner switches it on ----------
A2A_STATE = {"submitted": "submitted", "intake": "submitted", "planning": "working", "after": "submitted", "needs_answer": "input-required",
             "waiting_approval": "input-required", "running": "working", "scheduled": "working", "waiting_owner": "input-required",
             "done": "completed", "failed": "failed", "cancelled": "canceled"}
A2A_PER_HOUR = 10                                  # tasks one outside agent may give in an hour


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
        text = TC.fit(" ".join(str(p.get("text") or "") for p in parts if p.get("kind", p.get("type", "text")) == "text").strip(), 4000)  # cap: api
        if len(text) < 8:
            return err(-32602, "send the task as a text part of at least a few words")
        hour_ago = (dt.datetime.now().astimezone() - dt.timedelta(hours=1)).isoformat()
        if sum(1 for t in mine if (t.get("created") or "") >= hour_ago) >= A2A_PER_HOUR:
            return err(-32002, f"at most {A2A_PER_HOUR} tasks an hour from one outside agent")
        r = await submit({"action": "task_create", "text": text, "autonomy": "ask", "source": f"a2a:{name}"}, wait=10)
        tid = (r.get("result") or {}).get("task") if r.get("ok") else None
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
    return JSONResponse({"ok": True, "name": r["result"]["name"], "token": tok, "card": f"https://{request.headers.get('host', '')}/.well-known/agent-card.json"})


def task_page(tid):
    f = TASK_PAGES / f"{tid}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    d["activity"] = RT.task_activity(tid)
    res = VAULT / (d.get("result") or "")
    d["answer"] = res.read_text(errors="replace") if d.get("result") and res.is_file() else None
    return d


async def api_task(request):
    """APP-35: one task's page: the task, its runs and their steps (the runner's file), the agents that worked on it, their
    actions and what they read from and kept in memory (the run record), and its answer."""
    try:
        tid = int(request.path_params["tid"])
    except ValueError:
        return JSONResponse({"error": "no such task"}, status_code=400)
    d = await asyncio.to_thread(task_page, tid)
    if d is None:
        return JSONResponse({"error": f"There is no task #{tid}."}, status_code=404)
    return JSONResponse(d)


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
        if r["archived"]:
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
    nodes = [{k: p[k] for k in ("id", "title", "type", "summary", "folder")} | {"degree": len(w["links"][p["id"]]) + len(w["back"].get(p["id"], ()))}
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


# ---------- push notifications (Web Push, VAPID keys made once) ----------
SUBS = DATA / "push-subscriptions.json"


def vapid():
    import base64
    from py_vapid import Vapid01
    from cryptography.hazmat.primitives import serialization
    pem = DATA / "vapid.pem"
    if not pem.exists():
        v = Vapid01(); v.generate_keys(); v.save_key(str(pem))
    v = Vapid01.from_file(str(pem))
    raw = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return v, base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def subs():
    try:
        return json.loads(SUBS.read_text())
    except Exception:
        return []


async def api_push_key(request):
    """The public key devices need to subscribe to push."""
    return JSONResponse({"key": vapid()[1]})


async def api_push_sub(request):
    """Subscribes or (on /unsubscribe) unsubscribes a device for push."""
    sub = await request.json()
    if not isinstance(sub, dict) or not str(sub.get("endpoint", "")).startswith("https://"):
        return JSONResponse({"ok": False}, status_code=400)
    cur = [s for s in subs() if s.get("endpoint") != sub["endpoint"]]
    if not request.url.path.endswith("unsubscribe"):
        cur.append({k: sub[k] for k in ("endpoint", "keys") if k in sub})
    SUBS.write_text(json.dumps(cur))
    return JSONResponse({"ok": True, "devices": len(cur)})


def send_push(title, body, url="/"):
    from pywebpush import WebPushException, webpush
    vapid()
    keep = []
    for s in subs():
        try:
            webpush(s, json.dumps({"title": title, "body": body, "url": url}), vapid_private_key=str(DATA / "vapid.pem"),
                    vapid_claims={"sub": "mailto:mission-control@localhost"}, ttl=3600 * 12)
            keep.append(s)
        except WebPushException as e:
            code = getattr(e.response, "status_code", 0)
            if code not in (404, 410):          # gone: the device unsubscribed
                keep.append(s)
            print("push failed:", code, str(e), flush=True)
        except Exception as e:
            keep.append(s)
            print("push failed:", str(e), flush=True)
    SUBS.write_text(json.dumps(keep))


async def api_push_test(request):
    """Sends a test push to every subscribed device."""
    await asyncio.to_thread(send_push, "Mission Control", "Notifications work.", "/#/system")
    return JSONResponse({"ok": True, "devices": len(subs())})


async def push_events():
    pos = EVENTS.stat().st_size if EVENTS.exists() else 0
    while True:
        await asyncio.sleep(3)
        try:
            size = EVENTS.stat().st_size
            if size < pos:
                pos = 0
            if size > pos:
                with EVENTS.open() as f:
                    f.seek(pos)
                    new = f.read()
                    pos = f.tell()
                for line in new.splitlines():
                    e = json.loads(line)
                    if e.get("push") and subs():
                        await asyncio.to_thread(send_push, e.get("title") or "Mission Control", e.get("text", ""),
                                                f"/#/mission/{e['slug']}" if e.get("slug") else "/")
        except Exception as ex:
            print("event watcher:", ex, flush=True)


# ---------- the AI phone (images/phone): approvals, Stop, pairing, log ----------
# The phone container keeps its state in /phone (state.json, pending/, log.jsonl, shots/); the app writes the owner's
# decisions (decisions/), requests (control/) and the Stop switch (STOP). Every approval request is pushed.
PHONE = Path(os.environ.get("PHONE_DIR", "/phone"))


def phone_state():
    try:
        return json.loads((PHONE / "state.json").read_text())
    except Exception:
        return None


def phone_pending():
    out = []
    for f in sorted((PHONE / "pending").glob("*.json")) if (PHONE / "pending").exists() else []:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return out


def phone_summary():
    st = phone_state()
    return {"on": bool(st), "connected": bool(st and st.get("connected")), "stopped": (PHONE / "STOP").exists(),
            "pending": len(phone_pending()), "model": st.get("model", ""), "foreground": st.get("foreground", ""),
            "trust_until": st.get("trust_until", 0), "voice": st.get("voice") or {}} if st else None


# ---------- app connections (images/mail and later others): time-limited grants the owner gives in the app ----------
# grants.json = {"gmail": {"read": {"until": epoch, "at": id, "by": login, "mission": slug|None}, ...}}; the connector
# reads it before every action. Its status, log, the first-Trash approvals (pending/) live next to it.
CONN = Path(os.environ.get("CONN_DIR", "/connections"))
SCOPES = {"gmail": {"read": "search and read mail", "organize": "label, archive, mark read",
                    "trash": "move mail to Trash (undo possible; never deleted for good)"}}


def conn_json(name, default):
    try:
        return json.loads((CONN / name).read_text())
    except Exception:
        return default


def conn_pending():
    out = []
    for f in sorted((CONN / "pending").glob("*.json")) if (CONN / "pending").exists() else []:
        try:
            out.append(json.loads(f.read_text()))
        except Exception:
            pass
    return out


def live_grants():
    t = time.time()
    return {c: {s: g for s, g in gs.items() if g.get("until", 0) > t} for c, gs in conn_json("grants.json", {}).items()}


def conn_summary():
    st = conn_json("status.json", {})
    if not st:
        return None
    g = live_grants()
    return {"pending": len(conn_pending()),
            **{c: {"ok": bool(v.get("ok")), "grants": {s: x["until"] for s, x in g.get(c, {}).items()}} for c, v in st.items()}}


async def api_connections(request):
    """The app connections (Gmail …): their status, scopes, live grants, waiting approvals and the recent log."""
    log = []
    if (CONN / "log.jsonl").exists():
        log = [json.loads(x) for x in (CONN / "log.jsonl").read_text().splitlines()[-60:] if x.strip()][::-1]  # cap: list
    st, g = conn_json("status.json", {}), live_grants()
    return JSONResponse({"connections": [{"id": c, "status": st.get(c, {}), "scopes": SCOPES[c], "grants": g.get(c, {})} for c in SCOPES],
                         "pending": conn_pending(), "log": log})


async def api_connections_grant(request):
    """Grant a scope for minutes (-1 = until revoked, 0 = revoke now). Refused from the AI phone."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    b = await request.json()
    c, s, m = str(b.get("conn", "")), str(b.get("scope", "")), int(b.get("minutes") or 0)
    if s not in SCOPES.get(c, {}):
        return JSONResponse({"ok": False, "error": "unknown connection or scope"}, status_code=400)
    g = conn_json("grants.json", {})
    if m == 0:
        g.get(c, {}).pop(s, None)
    else:
        until = time.time() + (10 * 365 * 86400 if m < 0 else 60 * min(m, 7 * 24 * 60))
        g.setdefault(c, {})[s] = {"until": until, "at": f"{time.time():.0f}-{uuid.uuid4().hex[:6]}",
                                  "by": request.headers.get("tailscale-user-login", ""), "mission": b.get("mission") or None}
    tmp = CONN / "grants.tmp"
    tmp.write_text(json.dumps(g))
    tmp.chmod(0o644)
    tmp.replace(CONN / "grants.json")
    with open(CONN / "log.jsonl", "a") as f:
        f.write(json.dumps({"ts": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "conn": c, "action": "grant" if m else "revoke",
                            "scope": s, "minutes": m, "mission": b.get("mission") or None, "by": request.headers.get("tailscale-user-login", "")}) + "\n")
    try:
        (CONN / "log.jsonl").chmod(0o666)            # shared with the mail service (another user): it appends its actions
    except OSError:
        pass
    return JSONResponse({"ok": True})


async def api_connections_decide(request):
    """The owner's answer to a connection's approval card, written to its decisions folder (a documented exception, SEC-12); never from the AI phone."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    b = await request.json()
    aid = str(b.get("id", ""))
    if not re.fullmatch(r"[a-f0-9]{16}", aid) or not (CONN / "pending" / f"{aid}.json").exists():
        return JSONResponse({"ok": False, "error": "this request is gone (answered or timed out)"}, status_code=404)
    (CONN / "decisions" / f"{aid}.json").write_text(json.dumps({"allow": bool(b.get("allow")), "by": request.headers.get("tailscale-user-login", "")}))
    return JSONResponse({"ok": True})


async def push_conn():
    seen = set()
    while True:
        await asyncio.sleep(2)
        try:
            for p in conn_pending():
                if p["id"] not in seen:
                    seen.add(p["id"])
                    if subs():
                        await asyncio.to_thread(send_push, "Gmail: OK to move to Trash?", TC.fit(f"{p.get('count')} mails · {p.get('reason', '')}", 180), "/#/system?conn=1")  # cap: api
        except Exception as ex:
            print("connections watcher:", ex, flush=True)


def phone_seen(request, what):
    print(f"phone {what}: {request.headers.get('tailscale-user-login', '?')} {TC.cut(request.headers.get('user-agent', ''), 80)}", flush=True)  # cap: untrusted


AI_PHONE_IP = os.environ.get("PHONE_HOST", "100.64.0.10")


def client_ip(request):
    """The device's Tailscale IP: tailscale serve passes it in X-Forwarded-For."""
    return (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()


def from_ai_phone(request):
    """The AI phone must never approve its own actions (it could open this app in its own browser)."""
    return client_ip(request) == AI_PHONE_IP


async def api_forgejo_connect(request):
    """The owner pastes his Forgejo token in the app: it goes to the runner (checked, stored encrypted), never to Hermes.
    Not an MCP tool, so no AI can relay or set it; refused from the AI phone."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    b = await request.json()
    tok = str(b.get("token", "")).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", tok):
        return JSONResponse({"ok": False, "error": "That doesn't look like a Forgejo token (40 characters, 0-9 and a-f)."}, status_code=400)
    return JSONResponse(await submit({"action": "forgejo_connect", "token": tok}, wait=30))


# ---------- House: Home Assistant on the NAS (ops/house.py) ----------
HA_BROWSER = os.environ.get("HA_BROWSER_URL", "http://192.168.1.80:8123")   # where the owner's browser reaches it (home Wi-Fi)
_house_states = {}                                       # OAuth state → (client_id, expiry)


def app_base(request):
    """This app's own address as the owner's browser sees it (tailscale serve keeps the name, maybe not the port)."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    name = host.split(":")[0]
    return f"https://{name}:8447" if name.endswith(".ts.net") else f"https://{host}"


async def api_house_connect(request):
    """Connect Home Assistant: off to its own sign-in page (OAuth, IndieAuth: this app's URL is the client id). The owner
    signs in there; Home Assistant sends him back to /api/house/callback with a one-time code."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    base = app_base(request)
    st = uuid.uuid4().hex
    now = time.time()
    for k in [k for k, (_, exp) in _house_states.items() if exp < now]:
        del _house_states[k]
    _house_states[st] = (base + "/", now + 600)
    q = {"client_id": base + "/", "redirect_uri": base + "/api/house/callback", "state": st, "response_type": "code"}
    return RedirectResponse(f"{HA_BROWSER}/auth/authorize?" + urllib.parse.urlencode(q))


async def api_house_callback(request):
    """Home Assistant's answer: the code goes to the runner, which trades it for a long-lived token (stored encrypted)."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    st, code = request.query_params.get("state", ""), request.query_params.get("code", "")
    cid = _house_states.pop(st, (None, 0))
    if not cid[0] or cid[1] < time.time():
        return RedirectResponse("/#/house?" + urllib.parse.urlencode({"err": "That sign-in is too old. Tap Connect again."}))
    r = await submit({"action": "house_connect", "code": code, "client_id": cid[0]}, wait=45)
    if r.get("ok") and not r.get("pending"):
        return RedirectResponse("/#/house?connected=1")
    return RedirectResponse("/#/house?" + urllib.parse.urlencode({"err": r.get("error", "Still working: look again in a minute.")}))


async def api_house(request):
    """The House page's buttons: switch a light/plug/shutter, an Alexa command, speak on an Echo, settings. The owner's own
    taps count as the owner (protected plugs included); from the AI phone they count as an agent."""
    b = await request.json()
    do = str(b.get("do", ""))
    acts = {"switch": "house_switch", "alexa": "house_alexa", "say": "house_say", "settings": "house_settings", "status": "house_status"}
    if do not in acts:
        return JSONResponse({"ok": False, "error": "unknown"}, status_code=400)
    if do == "settings" and from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    req = {k: b[k] for k in ("entity", "op", "value", "command", "echo", "message", "announce", "voice", "fresh") if k in b}
    return JSONResponse(await submit({"action": acts[do], **req, "by": "ai-phone" if from_ai_phone(request) else "owner"}, wait=20))


async def api_shop_decide(request):
    """The owner's answer to a purchase proposal: approve, not_now or change (with a note). Only from his own device in this
    app: refused from the AI phone, and not an MCP tool, so no agent can approve a purchase (ops/shopping.py)."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "the AI phone cannot approve purchases"}, status_code=403)
    b = await request.json()
    pid, d = str(b.get("id", "")), str(b.get("decision", ""))
    if not re.fullmatch(r"p-[a-f0-9]{8}", pid) or d not in ("approve", "not_now", "change"):
        return JSONResponse({"ok": False, "error": "invalid"}, status_code=400)
    if len(str(b.get("note") or "")) > 2000:
        return JSONResponse({"ok": False, "error": "the note is longer than 2,000 characters"}, status_code=400)
    phone_seen(request, f"shop {pid} {d} from {client_ip(request) or '?'}")
    return JSONResponse(await submit({"action": "shop_decide", "id": pid, "decision": d, "note": str(b.get("note") or ""),
                                      "source": "owner", "by": request.headers.get("tailscale-user-login", "")}, wait=10))


async def api_shop_limits(request):
    """The shopping limits (per purchase, per month, shops, the address check): the owner only, never the AI phone."""
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    b = await request.json()
    req = {k: b[k] for k in ("per_purchase_eur", "per_month_eur", "shops", "address_words") if k in b}
    return JSONResponse(await submit({"action": "shop_limits", **req, "source": "owner",
                                      "by": request.headers.get("tailscale-user-login", "")}, wait=10))


async def api_whoami(request):
    """Who is calling: the Tailscale login, the client address and whether it is the AI phone."""
    return JSONResponse({"login": request.headers.get("tailscale-user-login", ""), "ip": client_ip(request),
                         "ai_phone": from_ai_phone(request)})


async def api_clienterror(request):
    """An error the app hit in the browser: logged and kept (newest 500) for the health board (APP-24)."""
    raw = await request.body()
    if len(raw) > 4000:                                   # a report this long is not one the app sends: refused, not cut
        return JSONResponse({"error": f"the report is {len(raw):,} bytes; the limit is 4,000"}, status_code=413)
    try:
        b = json.loads(raw or b"{}")
    except Exception:
        b = {}
    print(f"client error ({request.headers.get('tailscale-user-login', '?')}): {TC.cut(str(b.get('msg')), 300)} at {TC.cut(str(b.get('where')), 200)} "  # cap: untrusted
          f"[{TC.cut(str(b.get('url')), 60)}] {TC.cut(str(b.get('ua')), 100)}", flush=True)  # cap: untrusted
    keep_client_error({"ts": time.time(), "msg": TC.cut(str(b.get("msg")), 300), "where": TC.cut(str(b.get("where")), 200), "url": TC.cut(str(b.get("url")), 120),  # cap: untrusted
                       "ua": TC.cut(str(b.get("ua")), 120)})  # cap: untrusted
    return JSONResponse({"ok": True})


CLIENT_ERRORS = DATA / "client-errors.jsonl"
CLIENT_ERRORS_KEEP = 500                         # the newest app errors kept (the container's log is gone at every deploy)  # cap: store


def keep_client_error(e):
    """APP-24: an error the app hit, kept where the health board reads it (FND-53: they were only printed)."""
    try:
        rows = CLIENT_ERRORS.read_text().splitlines() if CLIENT_ERRORS.exists() else []
        rows.append(json.dumps(e, ensure_ascii=False))
        CLIENT_ERRORS.write_text("\n".join(rows[-CLIENT_ERRORS_KEEP:]) + "\n")  # cap: rotate (the newest for the health board; the app's log has every one)
    except OSError:
        pass


async def api_phone(request):
    """The AI phone's state, its waiting requests and recent log."""
    st = phone_state()
    if phone_pending():
        phone_seen(request, "page with a waiting request")
    if not st:
        return JSONResponse({"installed": False})
    log = []
    if (PHONE / "log.jsonl").exists():
        log = [json.loads(x) for x in (PHONE / "log.jsonl").read_text().splitlines()[-60:] if x.strip()][::-1]  # cap: list
    block = [x.strip() for x in (PHONE / "blocklist.txt").read_text().splitlines() if x.strip() and not x.startswith("#")] \
        if (PHONE / "blocklist.txt").exists() else []
    return JSONResponse({"installed": True, "state": st, "stopped": (PHONE / "STOP").exists(), "pending": phone_pending(),
                         "push_devices": len(subs()),
                         "log": log, "blocklist": block})


DECIDE_WAIT = 6


async def api_phone_decide(request):
    """The owner's answer to the AI phone's approval card (a documented exception, SEC-12); never from the AI phone itself."""
    b = await request.json()
    aid = str(b.get("id", ""))
    phone_seen(request, f"decision {aid} allow={b.get('allow')} from {client_ip(request) or '?'}")
    if from_ai_phone(request):
        return JSONResponse({"ok": False, "error": "the AI phone cannot approve its own actions"}, status_code=403)
    if not re.fullmatch(r"[a-f0-9]{16}", aid) or not (PHONE / "pending" / f"{aid}.json").exists():
        return JSONResponse({"ok": False, "error": "this request is gone (answered or timed out)"}, status_code=404)
    (PHONE / "decisions").mkdir(exist_ok=True)
    dec = {"allow": bool(b.get("allow")), "minutes": max(0, min(30, int(b.get("minutes") or 0))) if b.get("allow") else 0,
           "by": request.headers.get("tailscale-user-login", ""), "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    f = PHONE / "decisions" / f"{aid}.json"
    f.write_text(json.dumps(dec))
    for _ in range(int(DECIDE_WAIT * 4)):                # the phone takes an answer within a second: say so on the card
        await asyncio.sleep(0.25)
        if not f.exists():
            return JSONResponse({"ok": True, "taken": True})
    return JSONResponse({"ok": True, "taken": False})


async def api_phone_control(request):
    """Stop, resume, open the free mode, end a task or keep the screen on for the AI phone (a documented exception,
    SEC-12); the phone may only stop itself."""
    b = await request.json()
    if from_ai_phone(request) and b.get("do") != "stop":                # it may switch itself off, nothing else
        return JSONResponse({"ok": False, "error": "not from the AI phone"}, status_code=403)
    do = b.get("do")
    if do == "stop":
        (PHONE / "STOP").write_text(time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    elif do == "resume":
        (PHONE / "STOP").unlink(missing_ok=True)
    elif do in ("pair", "connect", "trust", "boot_setup", "voice_setup", "screen", "end_task"):
        req = {"do": do}
        if do == "pair":
            if not re.fullmatch(r"\d{4,5}", str(b.get("port", ""))) or not re.fullmatch(r"\d{6}", str(b.get("code", ""))):
                return JSONResponse({"ok": False, "error": "port: the 5 digits after the colon; code: the 6 digits"}, status_code=400)
            req.update(port=int(b["port"]), code=str(b["code"]))
        if do == "trust":
            m = int(b.get("minutes") or 0)
            req["minutes"] = -1 if m < 0 else min(7 * 24 * 60, m)            # -1 = until the owner stops it
        if do == "screen":                                                  # PHN-17: keep it on to watch, or off now
            req["minutes"] = max(0, min(60, int(b.get("minutes") or 0)))
        (PHONE / "control").mkdir(exist_ok=True)
        (PHONE / "control" / f"{time.time_ns()}.json").write_text(json.dumps(req))
    else:
        return JSONResponse({"ok": False, "error": "unknown"}, status_code=400)
    return JSONResponse({"ok": True})


async def api_phone_shot(request):
    """A screenshot the AI phone took, for the owner."""
    sid = request.path_params["sid"]
    p = PHONE / "shots" / f"{sid}.jpg"
    if not re.fullmatch(r"[a-f0-9]{16}", sid) or not p.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="image/jpeg")


async def push_phone():
    """Every new approval request from the AI phone goes to the owner's devices at once."""
    seen = set()
    while True:
        await asyncio.sleep(2)
        try:
            for p in phone_pending():
                if p["id"] not in seen:
                    seen.add(p["id"])
                    if subs():
                        await asyncio.to_thread(send_push, "AI phone: OK?", TC.fit(f"{p.get('text', '')} · {p.get('why', '')}", 180), "/#/phone")  # cap: api
        except Exception as ex:
            print("phone watcher:", ex, flush=True)


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


async def index(request):
    """The app's page (index.html), always revalidated."""
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


async def sw(request):
    """The service worker (offline shell, push, self-update), always revalidated."""
    return FileResponse(WEB / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


async def manifest(request):
    """The PWA manifest that makes the app installable."""
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")


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
        deg = {}
        for ln in g.get("links", []):
            for k in ("source", "target"):
                deg[ln[k]] = deg.get(ln[k], 0) + 1
        known = {n["id"] for n in g.get("nodes", [])}
        top = sorted(known, key=lambda i: -deg.get(i, 0))[:200]  # cap: list
        keep = set(top)
        nodes = [{"id": n["id"], "title": n.get("label", n["id"]), "folder": str(n.get("community_name") or n.get("community") or ""),
                  "summary": f"{n.get('source_file', '')} {n.get('source_location', '')}".strip(), "degree": deg.get(n["id"], 0),
                  "file": n.get("source_file", "")} for n in g.get("nodes", []) if n["id"] in keep]
        links = [{"source": ln["source"], "target": ln["target"], "relation": ln.get("relation", "")}
                 for ln in g.get("links", []) if ln["source"] in keep and ln["target"] in keep]
        comm = {}
        for n in nodes:
            comm[n["folder"]] = comm.get(n["folder"], 0) + 1
        _graph_cache.clear()
        _graph_cache[key] = {"nodes": nodes, "links": links, "total": len(known), "shown": len(nodes),
                             "communities": sorted(comm.items(), key=lambda x: -x[1])[:12]}
    return JSONResponse(_graph_cache[key])


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
    start = max(1, line - before)
    return {"start": start, "text": "\n".join(lines[start - 1:line + after])}


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
        return {"id": ln[other], "label": o.get("label", ln[other]), "relation": ln.get("relation", ""), "file": o.get("source_file", ""),
                "inferred": ln.get("confidence") not in (None, "EXTRACTED")}
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
    """What the repo is: the code map digest (Understand Anything) if there is one, else its README."""
    name = request.path_params["name"]
    d = repo_dir(name)
    if not d:
        return JSONResponse({"error": "no such repo"}, status_code=404)
    digest = CODE_DOCS / f"{name}.md"
    if digest.exists():
        return JSONResponse({"source": "code map digest", "markdown": cut(digest.read_text(errors="replace"), 200000)})  # cap: store
    for readme in ("README.md", "readme.md", "README.rst", "README"):
        if (d / readme).exists():
            return JSONResponse({"source": readme, "markdown": cut((d / readme).read_text(errors="replace"), 200000)})  # cap: store
    return JSONResponse({"source": None, "markdown": ""})


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
    Route("/api/shop/decide", api_shop_decide, methods=["POST"]), Route("/api/shop/limits", api_shop_limits, methods=["POST"]), Route("/api/clienterror", api_clienterror, methods=["POST"]), Route("/api/phone/decide", api_phone_decide, methods=["POST"]),
    Route("/api/phone/control", api_phone_control, methods=["POST"]), Route("/api/phone/shot/{sid}", api_phone_shot), Route("/api/share/{sid}", api_share),
    Route("/api/share/{sid}/save", api_share_save, methods=["POST"]),
    Route("/api/repo/{name}/graph", api_repo_graph), Route("/api/repo/{name}/overview", api_repo_overview),
    Route("/api/repo/{name}/node", api_repo_node), Route("/api/repo/{name}/map", api_repo_map),
    Route("/api/guide", api_guide), Route("/api/guide/live", api_guide_live), Route("/api/guide/{gid}", api_guide_one),
    Route("/api/wiki/roots", api_wiki_roots), Route("/api/wiki/graph", api_wiki_graph), Route("/api/wiki/map", api_wiki_map), Route("/api/task/map", api_task_map), Route("/api/a2a/token", api_a2a_token, methods=["POST"]),
    Route("/.well-known/agent-card.json", a2a_card), Route("/a2a", api_a2a, methods=["POST"]), Route("/api/telemetry", api_telemetry), Route("/api/wiki/access", api_wiki_access),
    Route("/api/wiki/page", api_wiki_page), Route("/api/wiki/search", api_wiki_search),
    Route("/api/push/key", api_push_key), Route("/api/push/subscribe", api_push_sub, methods=["POST"]),
    Route("/api/push/unsubscribe", api_push_sub, methods=["POST"]), Route("/api/push/test", api_push_test, methods=["POST"]),
    Mount("/static", StaticFiles(directory=WEB / "static")),
], middleware=[Middleware(TailnetOnly)])


# ---------- MCP server "house": Hermes' hands in the flat (ops/house.py), port 8094, granted to vk-main only ----------
house_mcp = MCPServer("house")


async def house_req(req, wait=25):
    r = await submit({**req, "by": "ai"}, wait=wait)
    if r.get("pending"):
        return "Still working on it (Home Assistant is slow to answer); look with house_status in a moment."
    return r.get("done", "Done.") if r.get("ok") else f"Error: {r.get('error', 'unknown')}"


@house_mcp.tool()
async def house_status() -> str:
    """The owner's flat through Home Assistant: every light, plug, switch and shutter with its room and state (on/off,
    brightness, position, power), which ones are protected, and the Echo speakers. Call it first to learn the names."""
    r = await submit({"action": "house_status", "fresh": True}, wait=25)
    h = r.get("house") or {}
    if not h.get("connected"):
        return "The House is not connected yet: the owner sets it up in Mission Control → House. " + (h.get("error") or "")
    lines = [f"- {t['name']} [{t['entity_id']}] {t['area'] or 'no room'}: {t['state']}" + (f", {t['brightness']} %" if t.get("brightness") is not None else "")
             + (f", position {t['position']}" if t.get("position") is not None else "") + (f", {t['power_w']} W" if t.get("power_w") is not None else "")
             + (" (protected: only the owner switches it)" if t["protected"] else "") for t in h.get("things", [])]
    echos = ", ".join(f"{e['name']}{' (' + e['area'] + ')' if e['area'] else ''}" for e in h.get("echos", [])) or "none yet"
    return ("Things Home Assistant controls directly:\n" + ("\n".join(lines) or "- none yet") + f"\nEcho speakers: {echos}\n"
            "Lights and devices that only live in the Alexa app are not listed: use house_alexa for them.")


@house_mcp.tool()
async def house_switch(entity: str, action: str, value: int | None = None) -> str:
    """Switch one light, plug, switch or shutter that Home Assistant controls (names from house_status).
    entity: its name, 'room name' or entity id. action: on | off | toggle | dim (value = brightness 1-100) for lights,
    plugs and switches; open | close | stop | position (value = 0-100) for shutters. Protected things (fridge, router,
    NAS, PC …) are refused."""
    return await house_req({"action": "house_switch", "entity": entity, "op": action, "value": value})


@house_mcp.tool()
async def house_alexa(command: str, echo: str = "") -> str:
    """Tell Alexa to do something, as if the owner said it to an Echo: for the lights, plugs and routines that live in the
    Alexa app (e.g. 'turn off the living room light', 'set the bedroom light to 30 percent', 'start the good night
    routine'). Write the command in the language the Echo is set to (Echos bought in Germany usually understand only
    German: 'schalte das Licht im Wohnzimmer aus'). echo: which Echo runs it (name or room; empty = the first one); the result is the same from any Echo.
    Never for shopping and never for protected devices."""
    return await house_req({"action": "house_alexa", "command": command, "echo": echo})


@house_mcp.tool()
async def house_say(message: str, echo: str = "", announce: bool = False) -> str:
    """Speak a short message on an Echo (echo: its name or room, or 'all'). announce=True plays the announcement chime
    first (good for 'dinner is ready'-style messages to every room). Keep it to one or two sentences."""
    return await house_req({"action": "house_say", "message": message, "echo": echo, "announce": announce})


# ---------- MCP server "claude": Hermes delegates to Claude Code (ops/claude_tasks.py) ----------
# Its own server (port 8092) so the mission agent can get it without the mission-management tools.
claude_mcp = MCPServer("claude")


@claude_mcp.tool()
async def claude_task(question: str, repo: str = "", mode: str = "ask", context: str = "", evidence: str = "") -> str:
    """Delegate work to Claude Code (Anthropic's coding agent, on the owner's Claude subscription). Use it for code
    questions ("how does X work in repo Y", "where is Z handled", "is this design sound"), reviewing or analysing code
    or long documents, and hard reasoning. Not for quick lookups or web research (use your own tools for those).
    repo: one of the owner's repositories (e.g. 'ai-stack', 'TestRepo', or a studied one like 'nanoGPT'); Claude reads a
    copy of its main branch. Leave it empty to work on `context` instead (paste the document or text there).
    mode: 'ask' (read-only: reads and searches the code) or 'analyse' (also runs commands such as tests and linters
    in the copy). It never changes anything: for changes use build_assign.
    evidence: for "why did X fail / what went wrong" questions, the logs Claude should read (read-only, secrets
    redacted), comma-separated: 'mission:<slug>' (its latest run's timeline and logs), 'run:<ref>' (a runtime run, as
    health_issues or the run view names it), 'crew:<agent id>' (e.g. crew:doctor), 'minutes:<N>' (the whole stack's
    error lines of the last N minutes). Use it with repo='ai-stack' so Claude can match log lines to the code.
    Returns a task number at once; Claude takes minutes: then call claude_task_result(id, wait_seconds=45) until it is
    done and pass the answer on."""
    r = await submit({"action": "claude_task", "question": question, "repo": repo, "mode": mode, "context": context, "evidence": evidence,
                      "source": "chat"})
    return (f"Claude task #{r['id']} started ({mode}{', ' + repo if repo else ''}). Call claude_task_result({r['id']}, wait_seconds=45) "
            "for the answer; it usually takes 1-5 minutes. The owner can watch it in Mission Control → Code → Claude tasks."
            if r.get("ok") else f"Error: {r.get('error')}")


HEALTH_DOC = """The stack's open health issues, one per agent and kind: agent, severity (alert: needs a human; note: seen in
    a run), what happened, since when, and the run that shows it (open its run view or read it with the runtime). For
    proposing fixes: issues clear themselves with the agent's next good run, or when the owner acknowledges them."""


def health_text():
    xs = health_issues()
    return "\n".join(f"- [{x['severity']}] {x['agent']} ({x['agent_kind']}): {x['text']} · issue {x['issue']} · run {x['run'] or '-'}" for x in xs) or "No open health issues."


@claude_mcp.tool(name="health_issues", description=HEALTH_DOC)
async def health_issues_worker() -> str:
    return health_text()


@claude_mcp.tool()
async def agent_note(agent: str, text: str) -> str:
    """Keep a standing note in your own memory (your journal, agents/<agent>/MEMORY.md in the vault): one short line
    that every future run of yours reads first, e.g. "check the board manual before searching shops". agent: your agent
    id, as your memory block names it (e.g. 'mission-ram-upgrade'). Only lasting lessons, never secrets or personal data."""
    r = await submit({"action": "journal_note", "agent": TC.cut(agent, 140), "text": TC.cut(text, 300), "by": "agent"}, wait=20)  # cap: untrusted
    if r.get("pending"):
        return "Saving..."
    return f"Noted ({r.get('notes')} standing notes)." if r.get("ok") else f"Error: {r.get('error')}"


@claude_mcp.tool()
async def claude_task_result(id: int, wait_seconds: int = 45) -> str:
    """The status or answer of a Claude task (from claude_task). wait_seconds (0-50): how long to wait for it to
    finish before answering. Call again while it is still running."""
    end = time.time() + max(0, min(50, int(wait_seconds)))
    while True:
        p = CLAUDE / f"{int(id)}.json"
        t = json.loads(p.read_text()) if p.exists() else None
        if not t:
            return f"No Claude task #{id}."
        if t["status"] in ("done", "failed") or time.time() >= end:
            break
        await asyncio.sleep(3)
    if t["status"] == "done":
        return f"Claude's answer (task #{id}, {t.get('turns') or 0} steps):\n\n{t['answer']}"
    if t["status"] == "failed":
        return f"Claude task #{id} failed: {t.get('error')}"
    if t["status"] == "waiting":
        return f"Claude task #{id} waits for the Claude usage limit; it continues by itself at {str(t.get('retry_at'))[11:16]}. Tell the owner."
    calls = sum(s["kind"] == "call" for s in t.get("steps", []))
    return f"Claude task #{id} is {t['status']} ({calls} tool calls so far). Call claude_task_result again."


# ---------- MCP tools for Hermes ----------
mcp = MCPServer("missions")
SCHEDULES = ("Schedule format: 'daily HH:MM', 'weekdays HH:MM', 'weekly mon,thu HH:MM' (mon tue wed thu fri sat sun), "
             "'every Nh' (1-24 hours) or 'manual' (on demand only).")
TRIGGERS = ("Triggers (list of objects): {'type': 'sec_filing', 'tickers': ['ASPI'], 'forms': optional e.g. ['8-K','10-Q']}, "
            "{'type': 'price_move', 'symbol': 'ASPI' (Yahoo symbol), 'pct': 8}, {'type': 'news', 'query': 'ASP Isotopes'}. "
            "Checked every 10 minutes; each new event starts a run (briefings write a short alert).")


def line(m):
    st = m.get("stats", {})
    last = (m.get("runs") or [{}])[0]
    return (f"- {m['title']} [{m['slug']}] · {'briefing' if m['type'] == 'briefing' else 'task'} · {m['status']} · "
            f"{m.get('schedule_text')}" + (f" · triggers: {'; '.join(t['text'] for t in m['triggers'])}" if m.get("triggers") else "")
            + f" · next run {m.get('next_run') or '-'} · runs 30 d: {st.get('runs', 0)} ({st.get('failed', 0)} failed), "
            f"{st.get('tokens', 0)} tokens, ${st.get('spend', 0):.4f} · last run: {last.get('status', '-')} {last.get('started', '')} "
            f"{TC.cut(str(last.get('summary') or ''), 120)}")  # cap: prompt


@mcp.tool(name="health_issues", description=HEALTH_DOC)
async def health_issues_tool() -> str:
    return health_text()


@mcp.tool()
async def missions_overview() -> str:
    """List all of the owner's missions (daily briefings and long-term agent tasks) with status, schedule, event triggers,
    next run, runs and costs of the last 30 days, and what is running right now."""
    s = state()
    out = [line(m) for m in s["missions"]] or ["(no missions)"]
    if s.get("running"):
        out.append(f"Running now: {s['running']['title']} since {s['running']['started']}")
    return "\n".join(out)


@mcp.tool()
async def mission_details(slug: str) -> str:
    """Details of one mission: goal, schedule, triggers, brief (key questions, searches, watchlist, notes) or working
    notes, last runs, and the vault paths of its latest outputs and its wiki (readable with the vault search tools)."""
    m = mission(slug)
    if not m:
        return f"No mission '{slug}'."
    d = {k: m.get(k) for k in ("title", "type", "status", "schedule_text", "triggers", "depth", "next_run", "budget_usd_month",
                               "deliver", "goal", "brief", "notes", "stats", "wiki")}
    d["runs"] = [{k: r.get(k) for k in ("started", "status", "seconds", "calls", "tokens", "spend", "summary")} for r in m["runs"][:5]]
    d["outputs"] = m.get("outputs", [])[:5]
    return json.dumps(d, ensure_ascii=False, indent=1)


@mcp.tool(description=(
    "Start a new mission for the owner. kind='briefing': a daily news briefing on a focus topic (the desk drafts the brief: "
    "key questions, companies to watch, searches; then reports every day). kind='task': a long-term mission the agent "
    "works on in repeated runs, keeping notes between runs, e.g. 'watch X', 'research Y over the next weeks'; deep=True "
    "makes each run a multi-step research (plan, several research steps, synthesis). kind='shopping': a shopping agent for a wish "
    "(it works out what fits from the PC's own facts, compares several shops incl. shipping and delivery, decides buy now "
    "or wait, and sends the owner a purchase proposal he approves himself in Mission Control; it never buys without that "
    "approval; put his budget and deadline in the description); watch_price=True re-checks daily and only reports a price drop of 5 % or more. kind='cleanup': where the space "
    "goes and what could go, on the AI phone (target='phone': storage, folders, unused apps, caches) or the PC "
    "(target='pc': a TreeSize-like scan of the Windows drives, safe/caution/never labels); it NEVER deletes. description: everything the owner said "
    "about what he wants. Default schedule: briefing 'daily 06:30', task 'manual'. " + SCHEDULES + " " + TRIGGERS +
    " once=True makes a one-off job: it runs now, delivers its result and then archives itself (use it for 'research X "
    "and send me the result'). deliver: any of 'telegram', 'app', 'email' (default telegram+app; add 'email' when the owner "
    "wants it by e-mail). This returns at once; the mission appears within about a minute. Call it ONCE per request, "
    "never again for the same mission (it would be refused as a duplicate). needs: app access the mission requires, e.g. ['gmail:read', 'gmail:trash'] for a mail clean-up (scopes gmail:read, gmail:organize, gmail:trash): the owner grants "
    "them on the mission page; until then the mail tools refuse."))
async def mission_create(kind: str, title: str, description: str, schedule: str = "", run_now: bool = True,
                         triggers: list[dict] = [], deep: bool = False, once: bool = False,
                         deliver: list[str] = ["telegram", "app"], watch_price: bool = False, needs: list[str] = [],
                         target: str = "") -> str:
    req = {"action": "create", "type": kind, "title": title, "description": description, "run_now": run_now or once, "target": target,
           "source": "chat", "triggers": triggers, "depth": "deep" if deep else None, "once": once, "deliver": deliver,
           "watch_pct": 5 if watch_price and kind == "shopping" else 0, "needs": needs}
    if watch_price and kind == "shopping" and not schedule:
        schedule = "daily 08:00"
    if schedule:
        req["schedule"] = schedule
    r = await submit(req, wait=6)
    if r.get("pending"):
        return (f"Creating '{title}' now. It appears in Mission Control within about a minute and the owner gets a notification. "
                "Do not call mission_create again for it.")
    if not r.get("ok"):
        return f"Error: {r.get('error')}"
    return f"{'Already exists' if r.get('duplicate') else 'Created'}: [{r['slug']}] {r.get('detail', '')}"


@mcp.tool()
async def mission_control(slug: str, action: str) -> str:
    """Control a mission: action 'run' (run it now, on demand), 'deep_run' (run a task now as multi-step deep research),
    'pause', 'resume' or 'archive' (stops it for good; its files stay in the vault). Use missions_overview for the slug."""
    if action not in ("run", "deep_run", "pause", "resume", "archive"):
        return "action must be run, deep_run, pause, resume or archive."
    req = {"action": "run", "slug": slug, "deep": True} if action == "deep_run" else {"action": action, "slug": slug}
    r = await submit(req | {"source": "chat"})
    return "OK" if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool(description=(
    "Change a mission. Lists REPLACE the current ones (read mission_details first, then send the full new list): "
    "key_questions, searches (Google News queries), watchlist ([{'name': ..., 'symbol': Yahoo symbol or ''}]) and "
    "notes (instructions for the desk) for briefings; goal for tasks. add_key_questions / add_searches append instead. "
    "Also schedule, title, depth ('deep' or 'standard', tasks). Everything runs on the ChatGPT subscription ($0). " + SCHEDULES))
async def mission_update(slug: str, schedule: str = "", title: str = "", goal: str = "", notes: str = "",
                         key_questions: list[str] = [], searches: list[str] = [], watchlist: list[dict] = [],
                         add_key_questions: list[str] = [], add_searches: list[str] = [],
                         budget_usd_month: float = -1, depth: str = "") -> str:
    m = mission(slug)
    if not m:
        return f"No mission '{slug}'."
    b = m.get("brief") or {}
    f = {k: v for k, v in (("schedule", schedule), ("title", title), ("goal", goal), ("notes", notes), ("depth", depth)) if v}
    if budget_usd_month >= 0:
        f["budget_usd_month"] = budget_usd_month
    if key_questions or add_key_questions:
        f["key_questions"] = (key_questions or b.get("key_questions", [])) + add_key_questions
    if searches or add_searches:
        f["search"] = (searches or b.get("search", [])) + add_searches
    if watchlist:
        old = {w["name"]: w for w in b.get("watchlist", [])}
        f["watchlist"] = [old.get(w.get("name"), {}) | {k: v for k, v in w.items() if v} for w in watchlist if w.get("name")]
    if not f:
        return "Nothing to change."
    r = await submit({"action": "update", "slug": slug, "fields": f, "source": "chat"})
    return f"Changed: {', '.join(r.get('changed', []))}" if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool(description="Set the event triggers of a mission (replaces the current list; [] removes all). " + TRIGGERS)
async def mission_set_triggers(slug: str, triggers: list[dict]) -> str:
    r = await submit({"action": "update", "slug": slug, "fields": {"triggers": triggers}, "source": "chat"})
    return "Triggers set." if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool()
async def send_email(subject: str, markdown: str) -> str:
    """Send the owner an e-mail (to his own address only) in the designed report layout. markdown: the full content, starting
    with '# Headline'; use headings, bullets, tables and source links. Use it when he asks to get something by e-mail."""
    r = await submit({"action": "email", "subject": TC.fit(subject, 150), "markdown": TC.cut(markdown, 100000), "source": "chat"}, wait=60)  # cap: untrusted
    if r.get("pending"):
        return "Sending..."
    return "E-mail sent." if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool()
async def vault_add(title: str, text: str = "", url: str = "") -> str:
    """Add knowledge to the owner's vault: either text (a note, findings, a summary) or a public web page URL (its text is
    fetched). It goes to raw/_inbox; the curator turns it into linked wiki pages within minutes."""
    r = await submit({"action": "vault_add", "title": title, "text": text, "url": url, "source": "chat"}, wait=60)
    if r.get("pending"):
        return "Adding..."
    return f"Added: {r.get('path')}" if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool()
async def build_assign(repo: str, title: str, description: str, engine: str = "") -> str:
    """Give the builder (a sandboxed coding agent) an assignment to implement in one of the owner's repos: 'ai-stack' (this
    AI stack itself: Mission Control, missions, configs, scripts) or a repo in ~/code that lives on Forgejo (e.g.
    'TestRepo'). description: exactly what to build or fix, with acceptance criteria. The builder works on a branch,
    runs the checks, CI runs; the owner reviews the diff in Mission Control (Build) and taps Approve, which merges and
    deploys with a smoke test and automatic rollback. Nothing goes live without his tap. Returns the build number.
    engine: leave empty (Claude Code when it is connected: better at code, and it spares the ChatGPT limit), 'claude'
    or 'hermes' (the builder on the ChatGPT subscription) when the owner asks for one."""
    r = await submit({"action": "build_assign", "repo": repo, "title": title, "description": description, "engine": engine,
                      "source": "chat"})
    return (f"Build #{r['id']} queued. The owner can follow and review it in Mission Control → Code." if r.get("ok")
            else f"Error: {r.get('error')}")


VERDICTS = {"approve": "fine to deploy", "changes": "improve first", "block": "do not deploy"}


def review_line(x):
    r = x.get("ai_review") or {}
    return VERDICTS.get(r.get("verdict"), "reviewing" if r.get("pending") else "-")


@mcp.tool()
async def builds_overview() -> str:
    """The builder's assignments: number, repo, title, status (queued, working, review, deployed, ...), checks, CI and
    the AI review's verdict."""
    b = state().get("builds") or []
    return "\n".join(f"#{x['id']} [{x['status']}] {x['repo']}: {x['title']} · checks {'ok' if x['checks_ok'] else '-'} · CI {x['ci'] or '-'}"
                      f" · AI review {review_line(x)} · {tokens_line(x)}" for x in b[:20]) + (f"\n(… and {len(b) - 20} older builds)" if len(b) > 20 else "") or "(no builds yet)"  # cap: prompt


def tokens_line(x):
    """Tokens of a build, the same count for both engines: all input (with the cached share) and output."""
    t, cached = x.get("tokens") or 0, x.get("cached") or 0
    return f"{t:,} tokens" + (f" ({round(100 * cached / t)} % cached)" if t and cached else "") if t else "tokens not counted yet"


@mcp.tool()
async def build_details(id: int, diff: bool = False) -> str:
    """One build in full, to discuss it with the owner: the assignment, status, the builder's summary, files changed, checks,
    CI, the AI review (verdict and every finding) and, with diff=true, the diff itself (up to 30,000 characters)."""
    x = next((b for b in state().get("builds") or [] if b["id"] == int(id)), None)
    if not x:
        return f"No build #{id}."
    r = x.get("ai_review") or {}
    out = [f"Build #{x['id']} [{x['status']}] in {x['repo']} ({'Claude Code' if x.get('engine') == 'claude' else 'ChatGPT'}): {x['title']}",
           TC.cut(f"Assignment: {x.get('description') or ''}", 3000),  # cap: prompt
           f"Checks: {'passed' if x['checks_ok'] else 'not passed' if x.get('checks') else 'not run'} · CI: {x.get('ci') or '-'}",
           f"Files: {', '.join(f[-1] if isinstance(f, list) else str(f) for f in (x.get('files') or [])) or '-'}",
           TC.cut(f"Builder's summary: {x.get('summary') or '-'}", 3000),  # cap: prompt
           f"AI review ({'Claude Code' if r.get('engine') == 'claude' else 'ChatGPT'}): {review_line(x)}. {r.get('summary') or r.get('error') or ''}"]
    out += [f"  [{f.get('severity')}] {f.get('file')}:{f.get('line')} {f.get('issue')} Fix: {f.get('fix') or '-'}" for f in r.get("findings") or []]
    if x.get("feedback"):
        out.append(f"Changes the owner requested last time: {x['feedback']}")
    if diff and (BUILDS / f"{x['id']}.diff").exists():
        out.append("Diff:\n" + TC.cut((BUILDS / f"{x['id']}.diff").read_text(errors="replace"), 30000))  # cap: prompt
    return "\n".join(out)


@mcp.tool()
async def build_request_changes(id: int, feedback: str) -> str:
    """Send a build in review (or failed) back to the builder with what to change, exactly as the owner's 'Request changes'
    button does. Only when the owner asks for it in this chat; write his points as clear, numbered instructions. You can
    never approve or deploy a build: that is the owner's tap in Mission Control."""
    r = await submit({"action": "build_revise", "id": int(id), "feedback": feedback, "source": "chat"})
    return f"Build #{id} goes back to the builder with your feedback." if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool()
async def build_recheck(id: int) -> str:
    """Re-run a build's checks and AI review on today's main (e.g. after other changes landed), without the builder."""
    r = await submit({"action": "build_recheck", "id": int(id), "source": "chat"})
    return f"Build #{id}: checks and review re-run started." if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool()
async def build_switch_engine(id: int, engine: str) -> str:
    """Move a build to the other engine: 'hermes' (ChatGPT) or 'claude' (Claude Code). Use it when the owner asks, or when a
    build waits for a usage limit and the owner agrees to switch. A waiting build starts right away; a build in review or
    failed gets a second attempt that continues from its branch. Not possible while it is working, deploying or merged."""
    r = await submit({"action": "build_switch_engine", "id": int(id), "engine": engine, "source": "chat"})
    return f"Build #{id} now runs with {'Claude Code' if engine == 'claude' else 'ChatGPT'} and is queued." if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool()
async def improvement_proposals(scan_now: bool = False) -> str:
    """The stack's own improvement ideas (the swarm's Ledger: from the crew and the weekly self-review): id, state (open,
    ready, active = being built, checking = shipped, declined, merged, gone), the agent that proposed it, title, and the
    owner's reason when he decided. The owner decides in Mission Control (Code) whether an idea becomes a build.
    scan_now=True starts a new self-review now (takes a minute or two)."""
    if scan_now:
        await submit({"action": "improve_scan", "source": "hermes"}, wait=1)
    s = state()
    b = (s.get("swarm") or {}).get("board") or {}
    ps = (b.get("open") or []) + (b.get("recent") or [])
    head = f"Last self-review: {(s.get('improve') or {}).get('last', 'never')[:16]} · {(s.get('improve') or {}).get('result', '')}"
    rows = TC.more([f"#{p['id']} [{p['state']}, {p['owner']}] {p['title']}" + (f" ({p['decision']['reason']})" if (p.get('decision') or {}).get('reason') else "")  # cap: prompt
                    for p in ps], 20, "more")
    return head + "\n" + ("\n".join(rows) or "(no ideas yet)") + \
        ("\nA new self-review has started; ask again in a few minutes." if scan_now else "")


@mcp.tool()
async def understand_repo(repo: str) -> str:
    """Analyse a code repository: clone it (GitHub URL like https://github.com/owner/name, or the name of a repo in
    ~/code), build its code graph and its Understand Anything code map. Takes several minutes; the owner gets a message."""
    r = await submit({"action": "understand", "repo": repo, "source": "chat"})
    return "Started; the owner gets a message when the code map is ready." if r.get("ok") else f"Error: {r.get('error')}"


@mcp.tool()
async def repos_overview() -> str:
    """The owner's code repositories: whether the builder may change each one (on Forgejo) or it is only studied, its code
    graph size, whether it has a code map, and its last commit. Use the names with build_assign and understand_repo."""
    rs = (state().get("code") or {}).get("repos") or []
    return "\n".join(f"- {r['name']}: {'buildable' if r['buildable'] else 'studied only'}"
                     f"{f' · graph {r['graph']['nodes']} nodes' if r.get('graph') else ' · no graph yet'}"
                     f"{' · code map' if r.get('codemap') else ''}"
                     f"{f' · last commit {r['last']['ts'][:10]}: {r['last']['subject']}' if r.get('last') else ''}" for r in rs) or "(none)"


@mcp.tool()
async def repo_create(name: str, description: str = "") -> str:
    """Create a new private repository on the owner's Forgejo (lowercase name: letters, digits, . _ -), cloned to ~/code with a
    README and an AGENTS.md, so the builder can work on it right away (then use build_assign). Needs the Forgejo token."""
    r = await submit({"action": "repo_create", "name": name, "description": description, "source": "chat"}, wait=60)
    return f"Created {r.get('repo')}." if r.get("ok") and not r.get("pending") else f"Error: {r.get('error', 'still working')}"


@mcp.tool()
async def repo_make_buildable(repo: str) -> str:
    """Move a studied repository (cloned from GitHub into ~/code) to the owner's Forgejo so the builder can change it; the
    original stays as the 'upstream' remote. Needs the Forgejo token."""
    r = await submit({"action": "repo_buildable", "repo": repo, "source": "chat"}, wait=120)
    return f"{r.get('repo')} is on Forgejo now: the builder can work on it." if r.get("ok") and not r.get("pending") \
        else f"Error: {r.get('error', 'still working')}"


def close_interrupted_chats():
    """An answer in progress dies with the app (restart, update): say so instead of 'working on it' forever."""
    for p in CHATS.glob("*.json") if CHATS.exists() else []:
        try:
            c = json.loads(p.read_text())
            if c.get("pending"):
                c["messages"].append({"role": "assistant", "ts": time.time(),
                                      "content": "⚠ This answer was interrupted (Mission Control restarted). Please send the message again."})
                c["pending"] = False
                save_chat(c)
        except Exception as e:                           # a chat that cannot be closed stays as it was: say so (FND-68)
            print(f"chat {p.name} not closed after the restart: {type(e).__name__}: {e}", flush=True)


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
        uvicorn.Server(uvicorn.Config(rt_app, host="0.0.0.0", port=8093, log_level="warning")).serve(),   # runtime ingest
        uvicorn.Server(uvicorn.Config(voice_app, host="0.0.0.0", port=8095, log_level="warning")).serve(),  # the voice gateway (VOI-03)
        push_events(), push_phone(), push_conn(), rt_housekeeping(), limit_retrier())


if __name__ == "__main__":
    asyncio.run(main())
