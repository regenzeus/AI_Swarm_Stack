"""Boot check: the stack is online, Hermes sees its tools, and the jobs may start (PLT-06, PLT-28).

Hermes discovers MCP tools (vault search, code graph, research) once, when its gateway starts. After a boot it starts
before qmd/graphify/research are ready behind LiteLLM, and then runs without them until restarted. This waits for Docker
and for LiteLLM to list every expected tool for vk-main, restarts Hermes once, and only then opens the gate (stack_gate.py):
a mission started earlier would lose its Hermes to that restart. Each boot leaves one line in /srv/ai/state/boots.jsonl,
shown on the Stack page, and one message: online, or what is missing.

Runs from stack-ready.timer. Needs agent-keys in the environment (VK_MAIN). Again in the same boot (the timer restarted by
a deploy, by hand) it leaves Hermes alone and sends nothing.
"""
import json, os, subprocess, sys, time, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stack_gate as G

EXPECTED = {"memory-search", "research-research"}   # vk-main's late servers (ops/keys.sh); since MEM-28 the memory tools
                                                    # stand in for qmd and graphify, which the check waited for until 10 Nov 2026
ONE_SHOT = {"n8n-db"}                                          # set-up jobs that run once at start and exit 0: done, not down
URL = "http://127.0.0.1:4000/mcp/"
HERMES = "http://127.0.0.1:8642/health"
BOOTS = Path("/srv/ai/state/boots.jsonl")
WAIT_S = 1200                                        # Docker may need many tries on a cold PC; stack-ready.service allows more


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


def restart_hermes():
    subprocess.run(["docker", "restart", "aistack-hermes-1"], capture_output=True)
    subprocess.run(["docker", "restart", "aistack-hermes-dashboard-1", "aistack-gate-hermes-dashboard-1"], capture_output=True)   # they share Hermes' network namespace


def hermes_live():
    try:
        with urllib.request.urlopen(HERMES, timeout=5) as r:
            return r.status == 200
    except OSError:
        return False


def docker_tries():
    """How many times Docker had to start again this boot."""
    out = subprocess.run(["systemctl", "--user", "show", "docker", "-p", "NRestarts", "--value"], capture_output=True, text=True).stdout
    return int(out.strip() or 0)


def notify(text):
    subprocess.run(["sh", str(Path(__file__).resolve().parent / "notify.sh"), text], capture_output=True, timeout=120)


def until(ok, end, every=5, sleep=time.sleep):
    """Poll ok() until it is true or the clock passes end. -> its last value."""
    while True:
        v = ok()
        if v or time.time() >= end:
            return v
        sleep(every)


def wait_states():
    try:
        return G.states()
    except (OSError, ValueError):
        return None


def line(row):
    """The owner's one message about this start."""
    mins = max(1, round(row["ready_s"] / 60))
    head = f"AI stack online {mins} min after the start: {row['running']} of {row['total']} services running."
    if row["missing"]:
        head = f"⚠️ AI stack started, but Hermes is missing these tools: {', '.join(row['missing'])}. The jobs go ahead without them."
    elif row["running"] < row["total"]:
        head = f"⚠️ AI stack started {mins} min ago, with {row['total'] - row['running']} of {row['total']} services not running: {', '.join(row['down'])}."
    if row["docker_tries"]:
        head += f" Docker needed {row['docker_tries'] + 1} tries."
    return head


def main():
    first = not G.READY.exists()                     # the first run of this boot: the only one that restarts Hermes or reports
    end = time.time() + WAIT_S
    st = until(wait_states, end)
    docker_s = round(G.uptime())
    have = until(lambda: tools() == EXPECTED, end, every=10) and EXPECTED or tools()
    missing = sorted(EXPECTED - have)
    restarted = False
    if first and not missing and st:
        restart_hermes()                             # it started with the others, before its tools were listed
        restarted = True
        until(hermes_live, time.time() + 180)
    G.READY.write_text(str(time.time()))             # open the gate even when something is missing: the alert says what
    st = wait_states() or {}
    down = sorted(s for s, v in st.items() if v != "running" and s not in ONE_SHOT)
    row = {"ts": time.time(), "boot": G.booted(), "ready_s": round(G.uptime()), "docker_s": docker_s, "docker_tries": docker_tries(),
           "running": len(st) - len(down) - len(ONE_SHOT & set(st)), "total": len(st) - len(ONE_SHOT & set(st)), "down": down, "missing": missing, "hermes_restarted": restarted}
    print(json.dumps(row), flush=True)
    if first:
        BOOTS.parent.mkdir(parents=True, exist_ok=True)
        with open(BOOTS, "a") as f:
            f.write(json.dumps(row) + "\n")
        notify(line(row))
    if missing:
        sys.exit(f"tools still missing after {WAIT_S // 60} min: {missing}")


if __name__ == "__main__":
    main()
