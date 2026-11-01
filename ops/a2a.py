"""Agents outside the stack through A2A (TSK-19; docs/SWARM-DESIGN.md "Reach").

Off until the owner switches it on. Then an agent on the tailnet reads the stack's agent card
(/.well-known/agent-card.json) and sends A2A JSON-RPC requests to /a2a (images/mission-control/server.py) with its own
bearer token; each request becomes a task that waits for the owner's OK (autonomy "ask", source a2a:<name>), and the
outside agent reads its state and answer back. Nothing from outside the tailnet reaches it (CST-04).

The owner names each outside agent in the app (Stack → Outside agents); the web server makes its token and shows it
once, and this file keeps only its hash (/srv/ai/missions/app/a2a.json, mode 600). Revoking an agent removes it.
"""
import datetime as dt
import json
import re

M = None                                          # ops/missions.py, set by its main()
ACTIONS = {"a2a_settings", "a2a_token", "a2a_revoke"}


def path():
    return M.HOME / "app" / "a2a.json"


def load():
    try:
        d = json.loads(path().read_text())
    except (OSError, ValueError):
        d = {}
    return {"enabled": bool(d.get("enabled")), "agents": d.get("agents") or {}}


def save(d):
    tmp = path().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=1))
    tmp.chmod(0o600)
    tmp.replace(path())


def handle(req):
    a, d = req["action"], load()
    if a == "a2a_settings":
        d["enabled"] = bool(req.get("on"))
        save(d)
        M.event("a2a", "", f"A2A for outside agents switched {'on' if d['enabled'] else 'off'}", title="Outside agents")
        return {"enabled": d["enabled"]}
    name = str(req.get("name") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,30}", name):
        raise ValueError("name the outside agent with 2 to 31 letters, digits or dashes")
    if a == "a2a_token":
        h = str(req.get("hash") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", h):
            raise ValueError("the token's hash is missing (the app makes the token)")
        d["agents"][name] = {"hash": h, "created": dt.datetime.now().astimezone().isoformat(timespec="seconds")}
        save(d)
        M.event("a2a", "", f"Outside agent “{name}” may send tasks over A2A (each waits for your OK)", title="Outside agents")
        return {"name": name}
    if a == "a2a_revoke":
        d["agents"].pop(name, None)
        save(d)
        M.event("a2a", "", f"Outside agent “{name}” revoked", title="Outside agents")
        return {"revoked": name}
    raise ValueError("unknown A2A action")


def state():
    d = load()
    return {"a2a": {"enabled": d["enabled"], "agents": [{"name": n, "created": a.get("created")} for n, a in sorted(d["agents"].items())]}}
