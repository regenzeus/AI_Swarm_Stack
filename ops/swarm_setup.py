#!/usr/bin/env python3
"""Prepare the Swarm service's data folder and the runner's token (idempotent; values never printed).

  sops exec-env secrets/secrets.enc.yaml "sops exec-env secrets/agent-keys.enc.yaml 'python3 ops/swarm_setup.py'"
  ... 'python3 ops/swarm_setup.py agents'   the Hermes agents' swarm identities in the gateway (deploy runs it)

- /srv/ai/swarm (the service's /data; world-writable with the sticky bit: the container's user is another uid under
  rootless Docker, as /srv/ai/missions/inbox) and /srv/ai/swarm-outbox (the runner's outbox and sync state, 0700).
- The runner's token SWARM_RUNNER: created once, stored only in secrets/agent-keys.enc.yaml (sops), and its SHA-256 in
  /srv/ai/swarm/tokens.json, which is all the service ever sees. Agents' own swarm tokens (gateway BYOK credentials,
  SWM-89) are added here when the first agent calls the swarm through the gateway.
"""
import hashlib
import textcap as TC                              # visible caps (AGENTS.md, truncation)
import json
import os
import secrets
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEYS = ROOT / "secrets/agent-keys.enc.yaml"
DATA = Path(os.environ.get("SWARM_DATA_HOST", "/srv/ai/swarm"))
OUTBOX = Path(os.environ.get("SWARM_STATE", "/srv/ai/swarm-outbox"))


def store(name, value):
    """Append NAME: value to the sops-encrypted agent keys (as ops/keys.sh does), through a 0600 file in /dev/shm."""
    plain = subprocess.run(["sops", "-d", str(KEYS)], capture_output=True, text=True, check=True).stdout
    with tempfile.NamedTemporaryFile("w", dir="/dev/shm", suffix=".yaml", delete=False) as f:
        os.chmod(f.name, 0o600)
        f.write(plain.rstrip("\n") + f"\n{name}: {value}\n")
    try:
        enc = subprocess.run(["sops", "-e", "--filename-override", str(KEYS.relative_to(ROOT)), "--input-type", "yaml",
                              "--output-type", "yaml", f.name], capture_output=True, text=True, check=True, cwd=ROOT).stdout
        KEYS.write_text(enc)
    finally:
        os.unlink(f.name)


API = os.environ.get("LITELLM_API", "http://127.0.0.1:4000")
SERVER = {"server_name": "swarm", "alias": "swarm", "url": "http://swarm:8000/mcp", "transport": "http", "auth_type": "api_key",
          "is_byok": True, "description": "The agent swarm: the shared Ledger of artifacts and the Board (messages between agents)."}


def litellm(method, path, body=None, key=None):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key or os.environ['LITELLM_MASTER_KEY']}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw.strip().startswith(("{", "[")) else raw
    except urllib.error.HTTPError as e:
        return e.code, TC.cut(e.read().decode(), 300)  # cap: untrusted


def server_id():
    """The swarm's MCP server in the gateway (registered through the API: per-user credentials need a DB server,
    docs/SWARM-PHASE0.md). -> its id, registering it the first time."""
    st, body = litellm("GET", "/v1/mcp/server")
    rows = body if isinstance(body, list) else (body or {}).get("data") or [] if isinstance(body, dict) else []
    for s in rows:
        if s.get("server_name") == "swarm" or s.get("alias") == "swarm":
            return s["server_id"]
    st, body = litellm("POST", "/v1/mcp/server", SERVER)
    if st >= 300 or not isinstance(body, dict):
        raise SystemExit(f"could not register the swarm MCP server in LiteLLM (HTTP {st})")
    print("registered the swarm MCP server in LiteLLM")
    return body["server_id"]


def agents():
    """SWM-23, SWM-89: every card whose key grants the swarm gets its own swarm token, stored only as that key's user
    credential in the gateway (never in the agent's environment); the service keeps its SHA-256. Idempotent: an agent
    that has a token keeps it. Needs LITELLM_MASTER_KEY and the agents' keys (VK_*) in the environment."""
    sys_path = str(ROOT / "ops")
    import sys
    sys.path.insert(0, sys_path)
    import registry
    import time
    sid = server_id()
    tf = DATA / "tokens.json"
    cur = json.loads(tf.read_text()) if tf.exists() else {"agents": {}}
    cur.setdefault("agents", {})
    for attempt in range(4):              # right after a gateway restart the new server is not loaded yet (deploy, 2026-10-30)
        left = [c for c in registry.load().get("agents") or [] if "swarm" in (c.get("tools") or []) and c["id"] not in cur["agents"]]
        if not left:
            break
        if attempt:
            time.sleep(10)
        store_identities(left, sid, cur)
    tmp = tf.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1, sort_keys=True))
    tmp.chmod(0o644)
    tmp.replace(tf)
    print(f"{tf}: {len(cur['agents'])} agent token hashes")


def store_identities(cards, sid, cur):
    for card in cards:
        key = os.environ.get(str(card.get("key") or "").replace("-", "_").upper())
        if not key:
            print(f"skip {card['id']}: its key {card.get('key')} is not in the environment")
            continue
        uid = f"agent-{card['id']}"
        litellm("POST", "/user/new", {"user_id": uid, "user_role": "internal_user"})            # 400 when it exists: fine
        st, _ = litellm("POST", "/key/update", {"key": key, "user_id": uid})
        if st >= 300:
            print(f"skip {card['id']}: its key could not be tied to user {uid} (HTTP {st})")
            continue
        token = "swarm-" + secrets.token_urlsafe(24)
        st, _ = litellm("POST", f"/v1/mcp/server/{sid}/user-credential", {"credential": token, "save": True}, key=key)
        if st >= 300:
            print(f"skip {card['id']}: the gateway did not store its credential (HTTP {st})")
            continue
        cur["agents"][card["id"]] = hashlib.sha256(token.encode()).hexdigest()
        print(f"{card['id']}: swarm identity stored in the gateway")


def main():
    import sys
    if sys.argv[1:] == ["agents"]:
        return agents()
    DATA.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o1777)
    OUTBOX.mkdir(parents=True, exist_ok=True)
    OUTBOX.chmod(0o700)
    token = os.environ.get("SWARM_RUNNER", "")
    if not token:
        token = secrets.token_urlsafe(32)
        store("SWARM_RUNNER", token)
        print("created the runner's swarm token (stored in secrets/agent-keys.enc.yaml)")
    else:
        print("kept the runner's swarm token")
    app = os.environ.get("SWARM_APP_TOKEN", "")
    if not app:
        app = secrets.token_urlsafe(32)
        p = subprocess.run(["sops", "set", "--value-stdin", "secrets/secrets.enc.yaml", '["SWARM_APP_TOKEN"]'], cwd=ROOT,
                           input=json.dumps(app), capture_output=True, text=True)
        if p.returncode:
            raise SystemExit("could not store SWARM_APP_TOKEN in secrets/secrets.enc.yaml")
        print("created the app's swarm token (stored in secrets/secrets.enc.yaml)")
    tf = DATA / "tokens.json"
    cur = json.loads(tf.read_text()) if tf.exists() else {"agents": {}}
    cur["runner"] = hashlib.sha256(token.encode()).hexdigest()
    cur["app"] = hashlib.sha256(app.encode()).hexdigest()
    tmp = tf.with_suffix(".tmp")
    tmp.write_text(json.dumps(cur, indent=1, sort_keys=True))
    tmp.chmod(0o644)
    tmp.replace(tf)
    print(f"{tf}: runner and {len(cur.get('agents') or {})} agent token hashes")


if __name__ == "__main__":
    main()
