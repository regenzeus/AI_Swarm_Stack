#!/usr/bin/env python3
"""Phase 0, proof 1: does LiteLLM carry each agent's own swarm token to an MCP server (BYOK per-user credentials)?
Needs LITELLM_MASTER_KEY in the environment. Creates two throwaway users, keys and a DB-registered probe server,
calls the probe as each user, and removes everything again. Prints no key or token, only hashes and results."""
import hashlib, json, os, secrets, time, urllib.error, urllib.request

API = "http://127.0.0.1:4000"
M = os.environ["LITELLM_MASTER_KEY"]
made = {"keys": [], "users": [], "server": None}


def call(method, path, body=None, key=M, headers=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400], dict(e.headers)  # cap: untrusted


def mcp(key, tool, extra_headers=None):
    st, body, h = call("POST", "/mcp/", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "swarm-probe", "version": "0"}}}, key, extra_headers)
    sid = h.get("mcp-session-id") or h.get("Mcp-Session-Id")
    hh = {**(extra_headers or {}), **({"mcp-session-id": sid} if sid else {})}
    call("POST", "/mcp/", {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, key, hh)
    st, body, _ = call("POST", "/mcp/", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, key, hh)
    names = []
    for chunk in [l[5:] for l in body.splitlines() if l.startswith("data:")] or [body]:
        try:
            names += [t["name"] for t in (json.loads(chunk).get("result") or {}).get("tools", [])]
        except ValueError:
            pass
    target = next((n for n in names if n.endswith(tool)), None)
    if not target:
        return {"listed": names, "status": st, "raw": body[:400]}  # cap: untrusted
    st, body, _ = call("POST", "/mcp/", {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": target, "arguments": {}}}, key, hh)
    for line in body.splitlines():
        if line.startswith("data:"):
            body = line[5:]
    d = json.loads(body) if body.strip().startswith("{") else {"raw": body[:300]}  # cap: untrusted
    if "result" in d:
        txt = "".join(c.get("text", "") for c in d["result"].get("content", []))
        try:
            return {"status": st, "seen": json.loads(txt)}
        except ValueError:
            return {"status": st, "text": txt[:300], "isError": d["result"].get("isError")}  # cap: untrusted
    return {"status": st, "error": str(d.get("error", d))[:300]}  # cap: untrusted


def sha(token):
    return hashlib.sha256(f"Bearer {token}".encode()).hexdigest()[:16]


def raw(token):
    return hashlib.sha256(token.encode()).hexdigest()[:16]


out = {}
try:
    st, body, _ = call("POST", "/v1/mcp/server", {"server_name": "swarmprobe", "alias": "swarmprobe", "url": "http://swarmprobe:8000/mcp",
                                                  "transport": "http", "auth_type": "api_key", "is_byok": True,
                                                  "description": "phase 0 identity probe (temporary)"})
    out["server_create"] = st
    if st >= 300:
        out["server_create_body"] = body
        raise SystemExit
    made["server"] = json.loads(body)["server_id"]
    tokens = {}
    for who in ("a", "b"):
        uid = f"swarm-probe-{who}"
        st, body, _ = call("POST", "/user/new", {"user_id": uid, "user_role": "internal_user"})
        out[f"user_{who}"] = st
        made["users"].append(uid)
        st, body, _ = call("POST", "/key/generate", {"user_id": uid, "key_alias": f"vk-swarm-probe-{who}", "models": ["gpt-sub-fast"],
                                                     "max_budget": 0.001, "budget_duration": "1d",
                                                     "object_permission": {"mcp_servers": [made["server"]]}})
        out[f"key_{who}"] = st
        key = json.loads(body)["key"]
        made["keys"].append(key)
        tokens[who] = (key, "swarm-" + secrets.token_hex(16))
        st, body, _ = call("POST", f"/v1/mcp/server/{made['server']}/user-credential", {"credential": tokens[who][1], "save": True}, key)
        out[f"credential_{who}"] = (st, body[:200] if st >= 300 else "stored")  # cap: untrusted
    time.sleep(2)
    for who in ("a", "b"):
        key, tok = tokens[who]
        r = mcp(key, "whoami")
        seen = (r.get("seen") or {}).get("x_api_key_sha")
        other = tokens["b" if who == "a" else "a"][1]
        out[f"call_{who}"] = {"status": r.get("status"), "headers": (r.get("seen") or {}).get("headers"),
                              "carries_own_token": seen == raw(tok), "carries_other_token": seen == raw(other)}
    # five more calls each, interleaved: the worker cache must never hand one user's credential to the other
    mixups = 0
    for _ in range(5):
        for who in ("a", "b"):
            key, tok = tokens[who]
            mixups += (mcp(key, "whoami").get("seen") or {}).get("x_api_key_sha") != raw(tok)
    out["interleaved_calls_wrong_token"] = mixups
    # a client-supplied header: can agent a present a token of its choice instead of the stored one?
    key, _ = tokens["a"]
    forged = "swarm-" + secrets.token_hex(16)
    r = mcp(key, "whoami", {"x-mcp-swarmprobe-authorization": f"Bearer {forged}"})
    out["call_a_with_client_header"] = {**r, "client_header_won": (r.get("seen") or {}).get("auth_sha") == sha(forged)}
finally:
    for k in made["keys"]:
        out.setdefault("cleanup", []).append(("key", call("POST", "/key/delete", {"keys": [k]})[0]))
    for u in made["users"]:
        out.setdefault("cleanup", []).append(("user", call("POST", "/user/delete", {"user_ids": [u]})[0]))
    if made["server"]:
        out.setdefault("cleanup", []).append(("server", call("DELETE", f"/v1/mcp/server/{made['server']}")[0]))
    print(json.dumps(out, indent=1, default=str))
