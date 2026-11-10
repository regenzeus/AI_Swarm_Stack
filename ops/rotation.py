"""TRL-14: the trials as a weekly rotation, one a night at 01:00 (its n8n workflow), never two at once and never while the
stack works (the same idle test as the nightly restart, ops/recycle.py: a mission, a task, a build, a trial, a
landing, a backup or a crew job). Busy at 01:00, it looks again every 10 minutes for two hours, then skips the night.
Each night's pick, start or skip goes to /srv/ai/state/rotation.jsonl; each run's score is the trial's own record
(#/trials). Sunday rests. The exams the plan names that do not exist yet (review catch, offer picking, the phone
routine, the voice test) join the week when they do.

  python3 ops/rotation.py          tonight's trial, when the stack is idle
  python3 ops/rotation.py week     the week's rotation
"""
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

import recycle as RC

ROOT = Path(__file__).resolve().parent.parent
LOG = Path("/srv/ai/state/rotation.jsonl")
WEEK = {1: "research-accuracy", 2: "stack-trace", 3: "semver", 4: "research-accuracy", 5: "mqtt-trace", 6: "mustache"}   # ISO weekday
WAIT_S, EVERY_S = 7200, 600


def pick(now=None):
    """Tonight's trial, or None (Sunday rests). The night belongs to the day it starts in: 01:00 Monday is Monday's."""
    d = dt.datetime.fromtimestamp(now or time.time())
    return WEEK.get(d.isoweekday())


def _sh(*cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout


def run(sh=_sh, state=RC.STATE, log=LOG, sleep=time.sleep, now=time.time, wait=WAIT_S, root=ROOT):
    """Start tonight's trial once the stack is idle, or skip the night. -> the logged row."""
    name = pick(now())
    row = {"ts": round(now()), "trial": name}
    if not name:
        row["rest"] = True
    elif not (root / "eval/trials" / f"{name}.yaml").exists():
        row["skipped"] = f"no trial called {name}"
    else:
        end = now() + wait
        while True:
            why = RC.busy(json.loads(state.read_text()) if state.exists() else {}, RC.units(sh), now())
            if not why or now() >= end:
                break
            sleep(EVERY_S)
        if why:
            row["skipped"] = why
        else:
            sh("make", "-C", str(root), "trial", f"NAME={name}", timeout=60)      # a transient unit trial-<name>-HHMM runs it
            row["started"] = round(now())
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass
    return row


if __name__ == "__main__":
    if sys.argv[1:] == ["week"]:
        for d, n in sorted(WEEK.items()):
            print(f"{['', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d]}  {n}")
    else:
        print(json.dumps(run()))
