"""Boot check: make sure Hermes sees its tools after a restart of the PC or WSL.

Hermes discovers MCP tools (vault search, code graph, research) once, when its gateway starts. After a boot it
usually starts before qmd/graphify/research are ready behind LiteLLM, and then runs without them until restarted.
This waits until LiteLLM lists every expected tool for vk-main, and restarts Hermes once if it started earlier.
Runs from stack-ready.timer (2 min after boot). Needs agent-keys in the environment (VK_MAIN).
"""
import json, os, subprocess, sys, time, urllib.request

EXPECTED = {"qmd-query", "graphify-query_graph", "research-research"}
URL = "http://127.0.0.1:4000/mcp/"


def call(method, params, sid=None):
    h = {"Authorization": "Bearer " + os.environ["VK_MAIN"], "Content-Type": "application/json",
         "Accept": "application/json, text/event-stream"}
    if sid:
        h["mcp-session-id"] = sid
    req = urllib.request.Request(URL, data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                       "params": params}).encode(), headers=h)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.headers.get("mcp-session-id"), r.read().decode()


def tools():
    try:
        sid, _ = call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "stack-ready", "version": "1"}})
        _, body = call("tools/list", {}, sid)
        return {t for t in EXPECTED if f'"{t}"' in body}
    except Exception:
        return set()


def started_at(container):
    out = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", container],
                         capture_output=True, text=True).stdout.strip()
    return out[:19]


def main():
    t0 = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    for _ in range(60):                     # up to 10 minutes
        have = tools()
        if have == EXPECTED:
            break
        time.sleep(10)
    else:
        sys.exit(f"tools still missing after 10 min: {sorted(EXPECTED - have)}")
    ready = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    hermes = started_at("aistack-hermes-1")
    if hermes and hermes < ready and hermes <= t0:
        subprocess.run(["docker", "restart", "aistack-hermes-1"], capture_output=True)
        subprocess.run(["docker", "restart", "aistack-hermes-dashboard-1", "aistack-gate-hermes-dashboard-1"], capture_output=True)   # they share Hermes' network namespace
        print(f"tools ready at {ready}Z; Hermes had started at {hermes}Z without them, restarted it")
    else:
        print(f"tools ready at {ready}Z; Hermes started after that, nothing to do")


if __name__ == "__main__":
    main()
