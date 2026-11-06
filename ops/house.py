"""House: Home Assistant on the NAS as the stack's hands in the flat (Echo/Alexa, lights, Tapo plugs, later shutters).

connect   The owner taps Connect on the House page → Home Assistant's own sign-in (OAuth; the app's URL is the client)
          → the app hands the one-time code to the runner (house_connect). The runner trades it for a long-lived token
          (websocket auth/long_lived_access_token), stores it encrypted as HA_TOKEN (sops) and restarts to load it.
          The token never reaches an agent, the app or a log.
status    every 30 s: Home Assistant up / set up / connected, its integrations, the Echos, every light, plug, switch and
          cover with its room and state → state.json "house" for the app.
control   house_switch / house_alexa / house_say, from the app (by the owner) or from Hermes' house tools (Mission
          Control's MCP server "house"). Things whose name says they power the fridge, router, NAS, PC and the like are
          protected: agents see them but never switch them, also not through an Alexa text command.
voice     the Echo bridge: Alexa Devices records each voice request on the Echo's event entity. One that starts with
          "Hermes" ("Alexa, Hermes …", "Alexa, frag Hermes …", "Alexa, ask Hermes …") goes to Hermes and the answer is
          spoken on that Echo. Every other request is ignored and never stored. Off switch on the House page.
Every action is logged: /srv/ai/house/log.jsonl, the activity feed, the runtime record (run "house", "house-voice:<ts>").
"""
import base64
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import json
import os
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import runtime as RTM
import prompts as P                               # MEM-11: the agent prompts live in prompts/<owner>.md

M = None                                          # ops/missions.py (set by missions.main)
ACTIONS = {"house_connect", "house_switch", "house_alexa", "house_say", "house_settings", "house_status"}
HA = os.environ.get("HA_URL", "http://192.168.1.10:8123")
TOKEN = os.environ.get("HA_TOKEN", "")
HOME = Path("/srv/ai/house")
LOG, SETTINGS = HOME / "log.jsonl", HOME / "settings.json"
HERMES_API = "http://127.0.0.1:8642/v1/chat/completions"
CONTROL = ("light", "switch", "cover", "fan")
PROTECT = re.compile(r"fridge|freezer|k[uü]hl|gefrier|router|fritz|modem|repeater|\bnas\b|synology|diskstation|server|\bpc\b|"
                     r"computer|desktop|wlan|wi-?fi|port ?forward|internet ?(?:access|zugang)|"
                     r"aquarium|medic|cpap|heater pump|boiler|security|alarm", re.I)
# the network and the NAS: whatever these integrations offer is the owner's alone, whatever it is called (a router
# client's internet switch carries the client's name, not the router's)
INFRA = {"fritz", "synology_dsm"}
TRIGGER = re.compile(r"^\s*(?:alexa[\s,]+)?(?:(?:frag(?:e)?|ask|tell|sag(?:e)?)\s+)?hermes\b[\s,:.!?-]*(.*)$", re.I)
# limit: drops, spoken requests past 30 an hour (HSE-07)
VOICE_MAX_PER_HOUR = 30
ACK_WAIT = 3          # s: Alexa first gives her own reply ("Ich weiß nicht ..."); then the Echo says Hermes heard it
ACK = {"de": "Einen Moment, Hermes kümmert sich darum.", "en": "One moment, Hermes is on it."}
ENGLISH = re.compile(r"(what|how|who|when|where|why|which|is|are|can|could|please|tell|write|turn|switch|send)\b", re.I)
SPOKEN = P.text("main", "SPOKEN")

_status = {"t": 0, "data": {"configured": True}}
_voice = {"last": {}, "times": [], "busy": False}
_lock = threading.Lock()


# ---------- Home Assistant API ----------
def rest(method, path, body=None, token=None, timeout=15, form=False):
    token = token if token is not None else TOKEN
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    req = urllib.request.Request(HA + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return json.loads(raw) if raw else None
    except ValueError:
        return raw.decode(errors="replace")


class WS:
    """Just enough of a websocket client for Home Assistant's API (stdlib only: the runner has no websocket library)."""

    def __init__(self, token, timeout=20):
        u = urllib.parse.urlparse(HA)
        self.s = socket.create_connection((u.hostname, u.port or 80), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f"GET /api/websocket HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.s.recv(1024)
            if not chunk:
                raise OSError("websocket handshake failed")
            head += chunk
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise OSError("websocket refused")
        self.buf = head.split(b"\r\n\r\n", 1)[1]
        self.n = 0
        if self.recv().get("type") != "auth_required":
            raise OSError("unexpected websocket greeting")
        self.send({"type": "auth", "access_token": token})
        if self.recv().get("type") != "auth_ok":
            raise PermissionError("Home Assistant refused the token")

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise OSError("websocket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, obj):
        data = json.dumps(obj).encode()
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536
                                 else bytes([0x80 | 127]) + struct.pack(">Q", n))
        mask = os.urandom(4)
        self.s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        msg = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            op = b0 & 0x0F
            if op == 0x9:                        # ping: answer, keep reading
                self.s.sendall(bytes([0x8A, 0x80]) + os.urandom(4))
                continue
            if op == 0x8:
                raise OSError("websocket closed by Home Assistant")
            msg += payload
            if b0 & 0x80:
                return json.loads(msg)

    def call(self, **cmd):
        self.n += 1
        self.send({"id": self.n, **cmd})
        while True:
            r = self.recv()
            if r.get("id") == self.n and r.get("type") == "result":
                if not r.get("success"):
                    raise ValueError((r.get("error") or {}).get("message", "Home Assistant refused"))
                return r.get("result")

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


# ---------- connect ----------
def connect(req):
    """The one-time code from Home Assistant's sign-in → a long-lived token, stored encrypted as HA_TOKEN."""
    code, client_id = str(req.get("code", "")), str(req.get("client_id", ""))
    if not re.fullmatch(r"[0-9a-f]{16,64}", code) or not client_id.startswith("https://"):
        raise ValueError("that is not a Home Assistant sign-in code")
    try:
        t = rest("POST", "/auth/token", {"grant_type": "authorization_code", "code": code, "client_id": client_id}, token="", form=True)
    except urllib.error.HTTPError:
        raise ValueError("Home Assistant did not accept the sign-in (it is valid for 10 minutes): tap Connect again") from None
    except OSError:
        raise ValueError("Home Assistant is not reachable from the PC (is the NAS on?)") from None
    ws = WS(t["access_token"])
    try:
        user = ws.call(type="auth/current_user")
        token = ws.call(type="auth/long_lived_access_token", client_name="AI stack (Mission Control)", lifespan=3650)
    finally:
        ws.close()
    M.store_secret("HA_TOKEN", token, f"secrets: Home Assistant token for {user.get('name', 'the owner')} (encrypted, set from Mission Control)")
    log_action("connect", f"connected as {user.get('name')}", by="owner")
    M.event("house", "", f"Home Assistant connected as {user.get('name')}", push=True, title="House")
    subprocess.Popen(["systemd-run", "--user", "--on-active=3", "--quiet", "systemctl", "--user", "restart", "missions.service"])
    return {"user": user.get("name"), "admin": user.get("is_admin")}


# ---------- status ----------
def _onboarded():
    try:
        steps = rest("GET", "/api/onboarding", token="", timeout=5)
        return all(s.get("done") for s in steps) if isinstance(steps, list) else True
    except urllib.error.HTTPError:
        return True                               # answers 404 once onboarding is finished
    except OSError:
        return None


def snapshot():
    """Everything the app and the agents need, from one websocket session."""
    up = _onboarded()
    out = {"configured": True, "url": HA, "reachable": up is not None, "onboarded": bool(up), "connected": False,
           "echos": [], "things": [], "integrations": [], "voice": settings().get("voice", True), "error": ""}
    if up is None or not TOKEN:
        return out
    try:
        ws = WS(TOKEN)
    except PermissionError:
        out["error"] = "Home Assistant no longer accepts the stack's token: connect again"
        return out
    except OSError as e:
        out["error"] = f"Home Assistant: {e}"
        return out
    try:
        ents = ws.call(type="config/entity_registry/list")
        devs = {d["id"]: d for d in ws.call(type="config/device_registry/list")}
        areas = {a["area_id"]: a["name"] for a in ws.call(type="config/area_registry/list")}
        states = {s["entity_id"]: s for s in ws.call(type="get_states")}
        entries = ws.call(type="config_entries/get")
        try:                                      # VOI-08: the AI phone's voice steps (who can log in, the pipelines)
            people = [u["name"] for u in ws.call(type="config/auth/list") or []      # the logins: a user need not be a person
                      if u.get("is_active") and not u.get("system_generated")]
            pipes = [p["name"] for p in (ws.call(type="assist_pipeline/pipeline/list") or {}).get("pipelines", [])]
        except (RuntimeError, ValueError, KeyError, OSError):
            people, pipes = [], []
    finally:
        ws.close()
    out["connected"], out["people"], out["pipelines"] = True, people, pipes
    out["integrations"] = sorted({(e["domain"], e.get("title", ""), e.get("state", "")) for e in entries
                                  if e.get("source") not in ("system", "ignore")})
    out["integrations"] = [{"domain": d, "title": t, "state": s} for d, t, s in out["integrations"]]
    by_dev = {}
    for e in ents:
        by_dev.setdefault(e.get("device_id"), []).append(e)

    def area_of(e):
        d = devs.get(e.get("device_id")) or {}
        return areas.get(e.get("area_id") or d.get("area_id"), "")

    for dev_id, es in by_dev.items():
        if not dev_id or not any(e["platform"] == "alexa_devices" for e in es):
            continue
        ids = [e["entity_id"] for e in es]
        speak = next((i for i in ids if i.startswith("notify.") and i.endswith("_speak")), None)
        if not speak:
            continue                              # the Amazon account itself, not an Echo
        d = devs.get(dev_id, {})
        out["echos"].append({"id": dev_id, "name": d.get("name_by_user") or d.get("name") or speak[7:-6], "area": area_of(es[0]),
                             "speak": speak, "announce": next((i for i in ids if i.startswith("notify.") and i.endswith("_announce")), None),
                             "event": next((i for i in ids if i.startswith("event.")), None), "model": d.get("model") or ""})
    for e in ents:
        dom = e["entity_id"].split(".")[0]
        if dom not in CONTROL or e.get("entity_category") or e.get("disabled_by") or e.get("hidden_by") or e["platform"] == "alexa_devices":
            continue
        s = states.get(e["entity_id"]) or {}
        a = s.get("attributes") or {}
        d = devs.get(e.get("device_id")) or {}
        name = e.get("name") or a.get("friendly_name") or e.get("original_name") or e["entity_id"]
        item = {"entity_id": e["entity_id"], "name": name, "domain": dom, "area": area_of(e), "state": s.get("state", "unknown"),
                "platform": e["platform"],
                "protected": e["platform"] in INFRA or bool(PROTECT.search(" ".join([name, e["entity_id"], d.get("name") or ""])))}
        if dom == "light" and a.get("brightness") is not None:
            item["brightness"] = round(a["brightness"] * 100 / 255)
        if dom == "cover" and a.get("current_position") is not None:
            item["position"] = a["current_position"]
        if a.get("current_power_w") is not None:
            item["power_w"] = a["current_power_w"]
        out["things"].append(item)
    out["things"].sort(key=lambda x: (x["area"] or "~", x["domain"], x["name"].lower()))
    return out


def status(max_age=30):
    with _lock:
        if time.time() - _status["t"] > max_age:
            try:
                _status["data"] = snapshot()
            except Exception as e:                # observability must not break the runner
                _status["data"] = {**_status["data"], "error": f"{type(e).__name__}: {e}"}
            _status["t"] = time.time()
        return _status["data"]


def state():
    d = dict(_status["data"])                     # the worker refreshes it; the state writer never waits for HA
    try:
        d["log"] = [json.loads(ln) for ln in LOG.read_text().splitlines()[-30:]][::-1]  # cap: list (the 30 newest actions; the log file has every one)
    except (OSError, ValueError):
        d["log"] = []
    return {"house": d}


# ---------- control ----------
def settings():
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


def log_action(what, text, by="ai", ok=True):
    HOME.mkdir(parents=True, exist_ok=True)
    e = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "what": what, "text": text, "by": by, "ok": ok}
    with open(LOG, "a") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    RTM.emit("house", "call" if ok else "error", agent="house", title=what, detail=f"{text} (by {by})", status="success" if ok else "failure",
             run_title="House (Home Assistant)")


def _need():
    if not TOKEN:
        raise ValueError("the House is not connected yet: the owner connects Home Assistant on the House page first")


def find(name):
    """An entity by id or by (part of) its name / room; a clear error when it is unknown or ambiguous."""
    things = status(max_age=10).get("things", [])
    n = name.strip().lower()
    hit = [t for t in things if t["entity_id"] == n] or [t for t in things if t["name"].lower() == n] or \
        [t for t in things if n in f"{t['area']} {t['name']}".lower()]
    if not hit:
        raise ValueError(f"no light, plug or shutter called {name!r} (house_status lists them)")
    if len(hit) > 1:
        raise ValueError(f"{name!r} matches {len(hit)}: " + ", ".join(f"{t['name']} ({t['entity_id']})" for t in hit[:8]))
    return hit[0]


def switch(req):
    _need()
    by = req.get("by", "ai")
    t = find(str(req.get("entity", "")))
    op, val = str(req.get("op", "toggle")).lower(), req.get("value")
    if (t["protected"] or t.get("platform") in INFRA) and by != "owner":
        raise ValueError(f"{t['name']} is protected (it may power something important): only the owner switches it, in the app")
    dom = t["domain"]
    data = {"entity_id": t["entity_id"]}
    if dom == "cover":
        svc = {"open": "open_cover", "up": "open_cover", "close": "close_cover", "down": "close_cover", "stop": "stop_cover",
               "position": "set_cover_position"}.get(op)
        if svc == "set_cover_position":
            data["position"] = max(0, min(100, int(val)))
    else:
        svc = {"on": "turn_on", "off": "turn_off", "toggle": "toggle", "dim": "turn_on"}.get(op)
        if op == "dim":
            if dom != "light":
                raise ValueError("only lights can be dimmed")
            data["brightness_pct"] = max(1, min(100, int(val)))
    if not svc:
        raise ValueError(f"unknown action {op!r} for a {dom}")
    rest("POST", f"/api/services/{dom}/{svc}", data)
    _status["t"] = 0
    text = f"{t['name']}: {op}{f' {val}' if val not in (None, '') else ''}"
    log_action("switch", text, by=by)
    return {"done": text}


def echo_of(name):
    echos = status(max_age=60).get("echos", [])
    if not echos:
        raise ValueError("no Echo is known yet: the owner adds the Alexa Devices integration on the House page")
    n = (name or "").strip().lower()
    if not n:
        return echos[0]
    hit = [e for e in echos if n in (e["name"] + " " + e["area"]).lower() or e["id"] == n]
    if not hit:
        raise ValueError(f"no Echo called {name!r}; there are: " + ", ".join(e["name"] for e in echos))
    return hit[0]


def alexa(req):
    """A text command through an Echo, as if spoken: for the lights and devices that live in the Alexa app."""
    _need()
    by, text = req.get("by", "ai"), TC.limit(str(req.get("command", "")).strip(), 300, "an Alexa command")   # a command is refused, never cut
    if not text:
        raise ValueError("say what Alexa should do")
    if by != "owner" and PROTECT.search(text):
        raise ValueError("that names something protected (fridge, router, NAS, PC …): only the owner does that")
    if by != "owner" and re.search(r"\b(kauf|bestell|buy|order|purchase|pay|bezahl)", text, re.I):
        raise ValueError("no shopping through Alexa")
    e = echo_of(str(req.get("echo", "")))
    rest("POST", "/api/services/alexa_devices/send_text_command", {"device_id": e["id"], "text_command": text})
    log_action("alexa", f"{e['name']}: “{text}”", by=by)
    return {"done": f"Alexa ({e['name']}) was told: {text}"}


def say(req):
    _need()
    by, msg = req.get("by", "ai"), TC.limit(str(req.get("message", "")).strip(), 600, "a message to say aloud")   # spoken whole or not at all
    if not msg:
        raise ValueError("nothing to say")
    where = str(req.get("echo", "")).strip()
    announce = bool(req.get("announce"))
    echos = status(max_age=60).get("echos", []) if where.lower() in ("all", "everywhere", "alle") else [echo_of(where)]
    targets = [e["announce" if announce else "speak"] or e["speak"] for e in echos]
    rest("POST", "/api/services/notify/send_message", {"entity_id": targets, "message": msg})
    log_action("say", f"{', '.join(e['name'] for e in echos)}: “{msg}”", by=by)
    return {"done": f"said on {', '.join(e['name'] for e in echos)}"}


def handle(req):
    a = req.get("action")
    if a == "house_connect":
        return connect(req)
    if a == "house_status":
        return {"house": status(max_age=0 if req.get("fresh") else 30)}
    if a == "house_settings":
        if req.get("by") != "owner":
            raise ValueError("only the owner changes House settings")
        s = settings()
        if "voice" in req:
            s["voice"] = bool(req["voice"])
        HOME.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(s))
        _status["t"] = 0
        return {"settings": s}
    return {"house_switch": switch, "house_alexa": alexa, "house_say": say}[a](req)


# ---------- voice bridge ----------
def ask_hermes(question, echo):
    prompt = SPOKEN.format(echo=echo["name"], room=f" in the {echo['area']}" if echo["area"] else "", question=question)
    P.record(prompt)                                      # MEM-11: the run records the prompt's version
    body = {"model": "gpt-sub-fast", "provider": "custom", "model_options": {"reasoning_effort": "low"},
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(HERMES_API, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('API_SERVER_KEY', '')}",
                                          "X-Hermes-Session-Id": f"alexa-{echo['id'][:8]}-{time.strftime('%Y%m%d')}"})
    with urllib.request.urlopen(req, timeout=150) as r:
        text = TC.answer(json.load(r), "Hermes")
    text = re.sub(r"[*_`#>\[\]]", "", text)
    return TC.fit(re.sub(r"\(https?://\S+\)|https?://\S+", "", text).strip(), 600)  # cap: api


def answer(question, echo):
    run = f"house-voice:{int(time.time())}"
    t0 = time.time()
    RTM.start(run, "house", f"Echo {echo['name']}: {question[:80]}")  # cap: id
    RTM.set_ref(run, "house")
    try:
        RTM.stage("Question from the Echo", question)
        time.sleep(ACK_WAIT)                              # an answer takes up to a minute: say at once that it was heard
        rest("POST", "/api/services/notify/send_message", {"entity_id": echo["speak"], "message": ACK["en" if ENGLISH.match(question) else "de"]})
        text = ask_hermes(question, echo)
        RTM.stage("Hermes answered", text, ms=int((time.time() - t0) * 1000), kind="say")
        rest("POST", "/api/services/notify/send_message", {"entity_id": echo["speak"], "message": text or "Sorry, I have no answer."})
        log_action("voice", f"{echo['name']}: “{question}” → “{text}”", by="echo")
        RTM.end(run, "house", "done", seconds=time.time() - t0)
    except Exception as e:
        log_action("voice", f"{echo['name']}: “{question}” failed: {type(e).__name__}: {e}", by="echo", ok=False)
        RTM.end(run, "house", "failed", detail=str(e), seconds=time.time() - t0)
        try:
            rest("POST", "/api/services/notify/send_message", {"entity_id": echo["speak"], "message": "Hermes is not reachable right now."})
        except Exception:
            pass
    finally:
        RTM.set_ref(None)
        _voice["busy"] = False


def voice_once():
    if not TOKEN or not settings().get("voice", True):
        return
    for e in status(max_age=60).get("echos", []):
        if not e.get("event"):
            continue
        s = rest("GET", f"/api/states/{e['event']}", timeout=5) or {}
        stamp, first = s.get("state"), e["event"] not in _voice["last"]
        if stamp == _voice["last"].get(e["event"]):
            continue
        _voice["last"][e["event"]] = stamp
        if first:                                 # what was said before the runner started is not a new question
            continue
        m = TRIGGER.match(str((s.get("attributes") or {}).get("voice_command") or ""))
        if not m or not m.group(1).strip():
            continue                              # an ordinary Alexa request: not ours, not stored
        now = time.time()
        _voice["times"] = [x for x in _voice["times"] if now - x < 3600]
        # limit: drops, as VOICE_MAX_PER_HOUR, and one at a time (HSE-07)
        if _voice["busy"] or len(_voice["times"]) >= VOICE_MAX_PER_HOUR:
            continue
        _voice["busy"] = True
        _voice["times"].append(now)
        threading.Thread(target=answer, args=(m.group(1).strip(), e), daemon=True, name="house-voice").start()


def worker():
    """Status every 30 s; the Echo bridge every 2 s while it is on."""
    while True:
        try:
            status()
            voice_once()
        except Exception as e:
            M.log(f"house: {type(e).__name__}: {e}")
            time.sleep(20)
        time.sleep(2)
