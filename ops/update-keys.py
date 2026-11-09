"""Apply the KEYS table in ops/keys.sh (models + daily budget) to keys that already exist.
Run via: sops exec-env secrets/secrets.enc.yaml 'sops exec-env secrets/agent-keys.enc.yaml "python3 ops/update-keys.py"'
Key values come from the environment and are never printed. An MCP grant names a server of config.yaml, or one
registered through the API (the swarm, ops/swarm_setup.py): those are granted by their server id."""
import json, os, re, urllib.request

API = "http://127.0.0.1:4000"
master = os.environ["LITELLM_MASTER_KEY"]
spec = re.findall(r'"(vk-[a-z-]+)\|([^|]+)\|([0-9.]+)\|([^"]*)"', open("ops/keys.sh").read())


def db_servers():
    """{server name: id} of the MCP servers registered through the API."""
    req = urllib.request.Request(f"{API}/v1/mcp/server", headers={"Authorization": f"Bearer {master}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode() or "[]")
    except Exception:
        return {}
    rows = body if isinstance(body, list) else body.get("data") or []
    return {s.get("server_name") or s.get("alias"): s["server_id"] for s in rows if s.get("server_id")}


ids = db_servers()
for alias, models, budget, mcp in spec:
    key = os.environ.get(alias.replace("-", "_").upper())
    if not key:
        print(f"skip {alias}: not in agent-keys")
        continue
    grants = [ids.get(x, x) for x in mcp.split(",") if x]
    body = json.dumps({"key": key, "models": models.split(","), "max_budget": float(budget),
                       "budget_duration": "1d",
                       "object_permission": {"mcp_servers": grants}}).encode()
    req = urllib.request.Request(f"{API}/key/update", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {master}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        print(f"updated {alias}: {models} ${budget}/day, mcp [{mcp}] (HTTP {r.status})")
