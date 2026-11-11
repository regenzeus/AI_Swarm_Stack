"""Apply the KEYS table in ops/keys.sh (models + daily budget) to keys that already exist.
Run via: sops exec-env secrets/secrets.enc.yaml 'sops exec-env secrets/agent-keys.enc.yaml "python3 ops/update-keys.py"'
Key values come from the environment and are never printed. An MCP grant names a server of config.yaml, or one
registered through the API (the swarm, ops/swarm_setup.py): those are granted by their server id. A server of a feature
that is off is not granted (GEN-13, PHN-28: vk-main loses the AI phone while FEATURES has no phone, and gets it back with it)."""
import json, os, re, sys, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deployment as DEPLOY  # noqa: E402
import modelpolicy as MP  # noqa: E402

API = "http://127.0.0.1:4000"
KEYS = Path(__file__).resolve().parent / "keys.sh"


def spec(text=None):
    """(alias, models, budget, mcp) of each row of ops/keys.sh."""
    return re.findall(r'"(vk-[a-z-]+)\|([^|]+)\|([0-9.]+)\|([^"]*)"', KEYS.read_text() if text is None else text)


def granted(mcp, on=None):
    """The servers of a key's grant whose feature is on (a server outside ops/modelpolicy.py SERVER_FEATURE, the swarm's, is core)."""
    on = DEPLOY.ON if on is None else on
    return [x for x in mcp.split(",") if x and MP.SERVER_FEATURE.get(x, "core") in on]


def db_servers(master):
    """{server name: id} of the MCP servers registered through the API."""
    req = urllib.request.Request(f"{API}/v1/mcp/server", headers={"Authorization": f"Bearer {master}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read().decode() or "[]")
    except Exception:
        return {}
    rows = body if isinstance(body, list) else body.get("data") or []
    return {s.get("server_name") or s.get("alias"): s["server_id"] for s in rows if s.get("server_id")}


def main():
    master = os.environ["LITELLM_MASTER_KEY"]
    ids = db_servers(master)
    for alias, models, budget, mcp in spec():
        key = os.environ.get(alias.replace("-", "_").upper())
        if not key:
            print(f"skip {alias}: not in agent-keys")
            continue
        mine = granted(mcp)
        body = json.dumps({"key": key, "models": models.split(","), "max_budget": float(budget),
                           "budget_duration": "1d",
                           "object_permission": {"mcp_servers": [ids.get(x, x) for x in mine]}}).encode()
        req = urllib.request.Request(f"{API}/key/update", data=body, method="POST",
                                     headers={"Authorization": f"Bearer {master}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            off = sorted(set(x for x in mcp.split(",") if x) - set(mine))
            print(f"updated {alias}: {models} ${budget}/day, mcp [{','.join(mine)}]"
                  + (f", not {','.join(off)}: its feature is off" if off else "") + f" (HTTP {r.status})")


if __name__ == "__main__":
    main()
