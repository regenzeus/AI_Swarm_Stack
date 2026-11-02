"""PLT-27: the services that grow while idle (qmd, Phoenix, Open WebUI) are restarted each night while the stack is idle,
so their memory does not pile up in swap (on 2 Nov they held 1.6 GB of the 3 GB swap; Open WebUI was back at 655 MB an
hour after a restart). Their data is on volumes; a restart takes seconds. Each night's memory before and after goes to
/srv/ai/state/recycle.jsonl.

  python3 ops/recycle.py          restart them when the stack is idle (recycle.timer, 03:50; waits up to an hour)
"""
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

SERVICES = ("qmd", "phoenix", "openwebui")
STATE = Path("/srv/ai/missions/public/state.json")
LOG = Path("/srv/ai/state/recycle.jsonl")
LIVE = ("running", "planning", "intake")
BUSY_UNITS = ("trial-", "land-", "backup.service", "restore-drill.service", "vault-ingest.service", "crew-")
STALE_H = 6                                          # a task "running" untouched this long is a leftover, not work
WAIT_S, EVERY_S = 3600, 600                          # busy at 03:50: look again every 10 min for an hour, then skip the night


def _ts(iso):
    try:
        return dt.datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0


def busy(state, units, now=None):
    """Why the stack is not idle now, or "": a mission or task running, a build, a trial, a landing, a backup, a crew job."""
    now = now or time.time()
    if state.get("running"):
        return "a mission is running"
    t = [x for x in state.get("tasks") or [] if x.get("status") in LIVE and _ts(x.get("updated")) > now - STALE_H * 3600]
    if t:
        return f"task #{t[0]['id']} is {t[0]['status']}"
    b = [x for x in state.get("builds") or [] if x.get("status") in ("working", "checking", "deploying", "queued")]
    if b:
        return f"build #{b[0]['id']} is {b[0]['status']}"
    u = [x for x in units if x.startswith(BUSY_UNITS)]
    return f"{u[0]} is running" if u else ""


def _sh(*cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout


def units(sh=_sh):
    """The user services active now (recycle's own excluded)."""
    out = sh("systemctl", "--user", "list-units", "--type=service", "--state=active,activating", "--no-legend", "--plain")
    return [ln.split()[0] for ln in out.splitlines() if ln.strip() and not ln.startswith("recycle")]


def memory(sh=_sh, meminfo=Path("/proc/meminfo")):
    """{service: MB in use, "swap": MB of swap used}."""
    out = {}
    for ln in sh("docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}").splitlines():
        name, use = ln.split("\t")
        s = name.removeprefix("aistack-").removesuffix("-1")
        if s in SERVICES:
            v, unit = use.split("/")[0].strip()[:-3], use.split("/")[0].strip()[-3:]
            out[s] = round(float(v) * {"KiB": 1 / 1024, "MiB": 1, "GiB": 1024}.get(unit, 1))
    m = {ln.split(":")[0]: int(ln.split()[1]) for ln in meminfo.read_text().splitlines() if ln.split()[1:]}
    out["swap"] = (m.get("SwapTotal", 0) - m.get("SwapFree", 0)) // 1024
    return out


def run(sh=_sh, state=STATE, log=LOG, sleep=time.sleep, now=time.time, wait=WAIT_S):
    """Restart the services once the stack is idle (or skip the night); log before and after. -> the logged row."""
    end = now() + wait
    while True:
        why = busy(json.loads(state.read_text()) if state.exists() else {}, units(sh), now())
        if not why or now() >= end:
            break
        sleep(EVERY_S)
    row = {"ts": now(), "before": memory(sh)}
    if why:
        row["skipped"] = why
    else:
        for s in SERVICES:
            sh("docker", "restart", "-t", "20", f"aistack-{s}-1", timeout=180)
        sleep(30)
        row["after"] = memory(sh)
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)
    return row


if __name__ == "__main__":
    run()
