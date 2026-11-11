#!/usr/bin/env python3
"""What the stack tells you about a failure, in plain words, and the quiet hold of a failure while the stack is being
updated or restarted (OBS-19, OBS-20; the owner's interaction design, 11 Nov 2026: "Not great information coming there.
Barely readable.").

A failure says what stopped, why in plain words, and whether you need to do anything (failure()). The raw reason and
where the run is (its n8n run) stay with the notice as its detail, one tap away in Activity, never in the push.

A failure during a change of the stack is not pushed (change(): a deploy or a landing holds its lock, a deploy ended,
the runner or the nightly restart started, less than AFTER_S ago). It is held under its source's key (hold()). The
source's next good run within SETTLE_S settles it as one quiet line in Activity ("Repository facts couldn't run during
the update at 06:20. It ran fine at 06:23.", settled()); a failure with no good run after SETTLE_S is told then, as it
would have been, with the update named (due(), from the runner's loop). The health board's alerts wait the same way
(ops/crew.py quiet).

    python3 ops/notices.py            what is held now
Never sends anything itself: the caller's emit (missions.event) does, through the one notification path (ops/notify.py).
"""
import fcntl
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import statefile as SF

STATE = Path("/srv/ai/state")
HELD = STATE / "notices-held.json"                   # the failures held while the stack changed, by their source's key
DEPLOYS = STATE / "deploys.jsonl"                    # one line per deploy, written when it ends (ops/deploy.py record)
RECYCLE = STATE / "recycle.jsonl"                    # the nightly restart of the services that grow (ops/recycle.py)
DEPLOY_LOCK = Path.home() / ".aistack-deploy.lock"   # held for the whole of a deploy (ops/deploy.py, PLT-10)
LAND_LOCK = Path.home() / ".aistack-land.lock"       # held around a landing's merge and deploy (ops/land.sh)
# limit: waits, a deploy or a restart counts as going on for this long after it ended: services come back one by one
AFTER_S = 5 * 60
# limit: waits, a failure held during a change waits this long for its source's good run before it is told after all
SETTLE_S = 15 * 60

# a raw reason -> (why in plain words, passing: True when it goes away by itself, like a service that was restarting)
REASONS = [
    (r"Job for \S+ failed|control process exited|systemctl", "its job stopped with an error", False),
    (r"timed? ?out|timeout|took too long", "it took too long and was stopped", True),
    (r"connection refused|not reachable|did not answer|unreachable|name or service not known|temporary failure in name"
     r"|\b50(?:2|3|4)\b|bad gateway|service unavailable|connection reset|remote end closed", "a service it needs did not answer", True),
    (r"usage limit|rate.?limit|\b429\b|too many requests", "the AI subscription's usage limit was reached", True),
    (r"is restarting|was restarted|runner restart|interrupted by a restart|stack is (?:down|starting)", "the stack was restarting", True),
    (r"budget", "its monthly budget is used up", False),
    (r"no space left|disk (?:is )?full", "the disk is full", False),
    (r"permission denied|not allowed|forbidden|\b403\b|\b401\b|unauthori[sz]ed", "it was not allowed to do what it tried", False),
    (r"cancel+ed|stopped by", "it was stopped", False),
]
TECHNICAL = re.compile(r"Traceback|Error:|Exception|errno|exit (?:code|status)|/\w+/\w+|\{|\}|\.service\b|\.py\b|::")


def plain(error):
    """A raw reason in plain words -> (why, passing). A short reason that is already words stays as it is."""
    raw = " ".join(str(error or "").split())
    for pat, why, passing in REASONS:
        if re.search(pat, raw, re.I):
            return why, passing
    if raw.lower() not in ("", "failed", "refused", "error") and len(raw) <= 160 and not TECHNICAL.search(raw):
        return raw.rstrip("."), False
    return "it stopped with an error", False


def failure(name, error="", state="failed"):
    """One failure in plain words -> {text, head, tail, detail}: what stopped (head), why and whether you need to do
    anything (tail); the raw reason is the detail."""
    why, passing = plain(error)
    head = f"{name} was not started" if state == "refused" else f"{name} couldn't run"
    act = "Nothing to do: it tries again on its next run." if passing else "It needs a look: open it to see what went wrong."
    tail = f"{why}. {act}"
    return {"text": f"{head}: {tail}", "head": head, "tail": tail, "detail": " ".join(str(error or "").split())}


def _clock(ts):
    return time.strftime("%H:%M", time.localtime(ts))


def _held_lock(path):
    """True while another process holds this lock file (a deploy, a landing). Taken and given back at once, shared,
    so it never stands in a deploy's way for longer than that."""
    if not path.exists():
        return False
    with open(path) as f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def _last_ts(path):
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return 0
    for ln in reversed(lines):
        try:
            return float(json.loads(ln).get("ts") or 0)
        except (ValueError, AttributeError):
            continue
    return 0


def runner_started():
    """When the runner (missions.service) last started, from systemd -> epoch seconds, or 0 when it cannot say."""
    try:
        out = subprocess.run(["systemctl", "--user", "show", "missions.service", "-p", "ActiveEnterTimestampMonotonic", "--value"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        mono = int(out) / 1e6
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0
    return time.time() - (time.monotonic() - mono) if mono else 0


def change(now=None, within=AFTER_S, locks=None, deploys=None, recycle=None, started=None):
    """Whether the stack is being changed now -> {"what": "update" | "restart", "at": epoch seconds} or None: a deploy or
    a landing holds its lock, or a deploy ended, the nightly restart ran or the runner started less than `within` ago."""
    now = now or time.time()
    for lock in (DEPLOY_LOCK, LAND_LOCK) if locks is None else locks:
        if _held_lock(Path(lock)):
            return {"what": "update", "at": now}
    for what, ts in (("update", _last_ts(Path(deploys or DEPLOYS))), ("restart", _last_ts(Path(recycle or RECYCLE))),
                     ("restart", runner_started() if started is None else started)):
        if ts and 0 <= now - ts < within:
            return {"what": what, "at": ts}
    return None


def hold(key, notice, ch, now=None, path=None):
    """Keep a failure that happened during a change instead of pushing it. notice: the event's fields (text, title,
    area, detail, ...), the source's name and failure()'s head and tail. A key's first failure is the one kept."""
    path, now = Path(path or HELD), now or time.time()
    held = SF.load(path, {}) or {}
    held.setdefault(key, {**notice, "failed_at": now, "change": ch})
    SF.save(path, held)


def settled(key, now=None, path=None):
    """The source of a held failure ran fine -> the quiet line that says so, or None when nothing was held for it."""
    path, now = Path(path or HELD), now or time.time()
    held = SF.load(path, {}) or {}
    n = held.pop(key, None)
    if not n:
        return None
    SF.save(path, held)
    return {**n, "text": f"{n['name']} couldn't run during the {n['change']['what']} at {_clock(n['change']['at'])}. It ran fine at {_clock(now)}."}


def due(emit, now=None, path=None, wait=SETTLE_S):
    """Tell the held failures whose source did not run fine within `wait`, as they would have been told, with the
    change named. emit(notice) sends one (missions.event). -> how many were told."""
    path, now = Path(path or HELD), now or time.time()
    held = SF.load(path, {}) or {}
    late = {k: n for k, n in held.items() if now - n["failed_at"] >= wait}
    if not late:
        return 0
    for k, n in late.items():
        emit({**n, "text": f"{n['head']} during the {n['change']['what']} at {_clock(n['change']['at'])}, and it has not run fine since: {n['tail']}"})
        held.pop(k)
    SF.save(path, held)
    return len(late)


if __name__ == "__main__":
    held = SF.load(HELD, {}) or {}
    print(json.dumps({"change": change(), "held": held}, indent=1, ensure_ascii=False))
    sys.exit(0)
