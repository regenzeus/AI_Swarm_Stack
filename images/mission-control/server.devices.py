# A part of server.py (PLT-25): push notifications, the AI phone, app connections and the House. It runs in server.py's namespace where it stood (_part); not a module of its own.
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


SUBS_LOCK = threading.Lock()         # the push watchers' threads and the subscribe route change one file (review APP-R10)


def write_atomic(path, text):
    """A file another service or thread reads: a temp file, then rename, so nobody reads half of it (review APP-R19, CNX-R12;
    images/mission-control/AGENTS.md). The temp name ends in .tmp, so a reader's *.json never takes it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def subs(strict=False):
    """The subscribed devices; strict: raise when the file cannot be read (a write after a failed read would wipe them)."""
    try:
        return json.loads(SUBS.read_text()) if SUBS.exists() or strict else []
    except Exception:
        if strict:
            raise
        return []


async def api_push_key(request):
    """The public key devices need to subscribe to push."""
    return JSONResponse({"key": vapid()[1]})


async def api_push_sub(request):
    """Subscribes or (on /unsubscribe) unsubscribes a device for push."""
    sub = await request.json()
    if not isinstance(sub, dict) or not str(sub.get("endpoint", "")).startswith("https://"):
        return JSONResponse({"ok": False}, status_code=400)
    with SUBS_LOCK:
        try:
            cur = [s for s in (subs(strict=True) if SUBS.exists() else []) if s.get("endpoint") != sub["endpoint"]]
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"the device list could not be read ({type(e).__name__}); nothing changed"}, status_code=500)
        if not request.url.path.endswith("unsubscribe"):
            cur.append({k: sub[k] for k in ("endpoint", "keys") if k in sub})
        write_atomic(SUBS, json.dumps(cur))
    return JSONResponse({"ok": True, "devices": len(cur)})


def send_push(title, body, url="/"):
    from pywebpush import WebPushException, webpush
    vapid()
    gone = set()
    for s in subs():
        try:
            webpush(s, json.dumps({"title": title, "body": body, "url": url}), vapid_private_key=str(DATA / "vapid.pem"),
                    vapid_claims={"sub": "mailto:mission-control@localhost"}, ttl=3600 * 12)
        except WebPushException as e:
            code = getattr(e.response, "status_code", 0)
            if code in (404, 410):              # gone: the device unsubscribed
                gone.add(s.get("endpoint"))
            print("push failed:", code, str(e), flush=True)
        except Exception as e:
            print("push failed:", str(e), flush=True)
    if gone:                                    # only the gone devices leave, read again under the lock: a device that subscribed
        with SUBS_LOCK:                         # while this sent stays, and a list that cannot be read is never written over
            try:
                write_atomic(SUBS, json.dumps([s for s in subs(strict=True) if s.get("endpoint") not in gone]))
            except Exception as e:
                print(f"push: the device list was not updated ({type(e).__name__}: {e})", flush=True)


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
    write_atomic(CONN / "decisions" / f"{aid}.json", json.dumps({"allow": bool(b.get("allow")), "by": request.headers.get("tailscale-user-login", "")}))
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
                        await asyncio.to_thread(send_push, "Gmail: OK to move to Trash?", TC.fit(f"{p.get('count')} mails · {p.get('reason', '')}", 180), "/#/system?tab=connections")  # cap: api
        except Exception as ex:
            print("connections watcher:", ex, flush=True)


def phone_seen(request, what):
    print(f"phone {what}: {request.headers.get('tailscale-user-login', '?')} {TC.cut(request.headers.get('user-agent', ''), 80)}", flush=True)  # cap: untrusted


AI_PHONE_IP = os.environ.get("PHONE_HOST") or "no-phone-host"   # compose always sets it (deployments/<name>/deployment.env); never a client's address


def client_ip(request):
    """The device's Tailscale IP: tailscale serve passes it in X-Forwarded-For. The last entry is the one the proxy wrote; an
    earlier one is whatever the device sent itself (review SEC-R13: the AI phone could name another address first)."""
    return (request.headers.get("x-forwarded-for") or "").split(",")[-1].strip()


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
HA_BROWSER = os.environ.get("HA_BROWSER_URL", os.environ.get("HA_URL", ""))   # where the owner's browser reaches it (home Wi-Fi)
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
    note_owner("shop_decide", d.replace("_", " "))
    return JSONResponse(await submit({"action": "shop_decide", "id": pid, "decision": d, "note": str(b.get("note") or ""),
                                      "seen": str(b.get("seen") or "")[:40], "source": "owner",  # cap: id (a timestamp)
                                      "by": request.headers.get("tailscale-user-login", "")}, wait=10))


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
    # limit: refuses, an error report longer than the app sends, with its size
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


SCREEN_VIEWS = DATA / "screen-views.json"
VIEWS_DAYS = 120                                     # cap: rotate (the unused report reads 30 days; four months show a trend)
VIEW_NAME = re.compile(r"[a-z][a-z-]{0,23}")


def count_view(name, tab="", day=None, path=None):
    """PLT-26: one opened screen, counted per day by its route name and tab (no address, no ids): {day: {name[:tab]: n}}."""
    f, day = path or SCREEN_VIEWS, day or dt.date.today().isoformat()
    key = f"{name}:{tab}" if tab else name
    d = json.loads(f.read_text()) if f.exists() else {}
    d.setdefault(day, {})[key] = d.get(day, {}).get(key, 0) + 1
    for old in sorted(d)[:-VIEWS_DAYS]:                   # cap: rotate (the newest VIEWS_DAYS days)
        del d[old]
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, sort_keys=True))
    tmp.replace(f)
    return d


def screen_views(days=30, path=None, today=None):
    """The screens opened in the last `days` days: {name[:tab]: n} (PLT-26's monthly report reads it)."""
    f = path or SCREEN_VIEWS
    d = json.loads(f.read_text()) if f.exists() else {}
    since = ((today or dt.date.today()) - dt.timedelta(days=days - 1)).isoformat()
    out = {}
    for day, counts in d.items():
        if day >= since:
            for k, n in counts.items():
                out[k] = out.get(k, 0) + n
    return dict(sorted(out.items(), key=lambda x: -x[1]))


async def api_view(request):
    """PLT-26: the app says a screen was opened (its route name and tab only)."""
    raw = await request.body()
    # limit: refuses, a page-view report longer than the app sends, with its size
    if len(raw) > 200:                                    # the app sends a name and a tab: anything longer is refused, not cut
        return JSONResponse({"error": f"the report is {len(raw):,} bytes; the limit is 200"}, status_code=413)
    try:
        b = json.loads(raw or b"{}")
    except ValueError:
        b = {}
    name, tab = str(b.get("name") or ""), str(b.get("tab") or "")
    if not VIEW_NAME.fullmatch(name) or (tab and not VIEW_NAME.fullmatch(tab)):
        return JSONResponse({"error": "not a screen of the app"}, status_code=400)
    if from_ai_phone(request) or (getattr(request, "headers", None) or {}).get("tailscale-user-login", "").endswith("@stack.local"):
        return JSONResponse({"ok": True, "counted": False})   # the AI phone's visits are its work; the nightly checks and previews (*@stack.local) are the stack's own
    async with VIEWS_LOCK:
        await asyncio.to_thread(count_view, name, tab)
    return JSONResponse({"ok": True})


async def api_views(request):
    """PLT-26: the screens opened in the last 30 days (or ?days=), most opened first."""
    try:
        days = max(1, min(VIEWS_DAYS, int(request.query_params.get("days") or 30)))
    except ValueError:
        return JSONResponse({"error": "days must be a number"}, status_code=400)
    return JSONResponse({"days": days, "views": await asyncio.to_thread(screen_views, days)})


VIEWS_LOCK = asyncio.Lock()
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
    write_atomic(f, json.dumps(dec))
    note_owner("phone_decide", "allowed" if dec["allow"] else "refused")
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
        write_atomic(PHONE / "STOP", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
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
        write_atomic(PHONE / "control" / f"{time.time_ns()}.json", json.dumps(req))
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
