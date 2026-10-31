"""Observability for every kind of agent run: missions, crew jobs, builds and Claude tasks (docs/OBSERVABILITY.md).

The pure helpers (files_of, stats_of, ledger, problems, judge, notify, …) live in images/mission-control/obs_core.py so
Mission Control's live run view uses the very same code; this module adds what needs the host: a crew job's history
from journald and the config hashes for a run manifest.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "images" / "mission-control"))
from obs_core import *  # noqa: F401,F403,E402  (re-exported: callers use observe.files_of etc.)
from obs_core import _args, _streak  # noqa: F401,E402


# ---------- a crew job's history (journald) ----------
def crew_history(unit, days=30, limit=40):
    """Past runs of a systemd user service: start, end, seconds, ok/failed, its log lines (grouped by invocation)."""
    p = subprocess.run(["journalctl", "--user", "-u", f"{unit}.service", "--since", f"-{days}d", "-o", "json", "--no-pager", "-n", "4000"],
                       capture_output=True, text=True, timeout=30)
    runs = {}
    for ln in p.stdout.splitlines():
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        inv = e.get("_SYSTEMD_INVOCATION_ID") or e.get("USER_INVOCATION_ID") or e.get("INVOCATION_ID")
        if not inv:
            continue
        t = int(e.get("__REALTIME_TIMESTAMP", 0)) / 1e6
        msg = e.get("MESSAGE") if isinstance(e.get("MESSAGE"), str) else ""
        r = runs.setdefault(inv, {"start": t, "end": t, "state": "running", "log": []})
        r["start"], r["end"] = min(r["start"], t), max(r["end"], t)
        if "Failed with result" in msg or "Main process exited, code=exited, status=" in msg and "status=0/" not in msg:
            r["state"] = "failed"
        elif ("Deactivated successfully" in msg or msg.startswith("Finished ")) and r["state"] != "failed":
            r["state"] = "ok"
        if msg and not msg.startswith(("Started ", "Starting ", "Finished ", "Consumed ")) and "install out of sync" not in msg \
                and f"{unit}.service" not in msg:
            r["log"].append(msg)
    out = sorted(runs.values(), key=lambda r: -r["start"])[:limit]
    for r in out:
        r["seconds"] = round(r["end"] - r["start"], 1)
        r["log"] = r["log"][-60:]  # cap: store
    return out


CONFIG_FILES = ("config/hermes/configure.sh", "config/hermes/configure-mission.sh", "config/hermes/configure-scout.sh",
                "config/litellm/config.yaml", "versions.env", "ops/keys.sh")


def config_hashes(repo):
    """git blob hash of every file that shapes an agent's behaviour, plus the stack's commit."""
    p = subprocess.run(["git", "-C", str(repo), "ls-tree", "HEAD", "--", *CONFIG_FILES], capture_output=True, text=True, timeout=20)
    out = {ln.split("\t")[1]: ln.split()[2][:12] for ln in p.stdout.splitlines() if "\t" in ln}
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=20).stdout.strip()
    return {"stack": head, **out}


