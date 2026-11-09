"""The stack's side of the Windows worker (GEN-11, DEC-45, docs/PLATFORM.md §6): it asks for a declared job by its kind and
values, and reads the answer. WSL cannot start anything on Windows (DEC-43): a request is a folder the broker fetches, and
the answers come back through C:\\AI\\exports, read-only here.

    import winworker as WW
    rid = WW.submit("maven.build", {"repo": "click", "commit": "...", "patch": "patch.diff", "goal": "verify"},
                    files={"patch.diff": diff_text})
    state = WW.wait(rid, timeout=1800)       # {status: done|failed|refused|lost|not picked up, error, steps, artifacts}

A step kind with "where": "windows" names its job kind; step_kind() makes its adapter (ops/stepkinds.py)."""
import json
import os
import re
import time
import uuid
from pathlib import Path

REQUESTS = Path(os.environ.get("WINWORKER_REQUESTS", "/srv/ai/state/winworker/requests"))
ANSWERS = Path(os.environ.get("WINWORKER_ANSWERS", "/srv/win-exports/.host/worker"))
ALIVE_S = 60          # the worker writes its status every 10 s
LEASE_S = 60          # a claim whose heartbeat is older than this was lost with its worker
PICKUP_S = 300        # the broker looks every few seconds; a request still waiting after this is not picked up
KIND = re.compile(r"[a-z][a-z0-9.-]{0,63}")
FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
# limit: refuses, a request's files (a patch) stay small: a patch past this is no change a person reviews
FILES_KB = 1024


class Refused(Exception):
    pass


def read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def status():
    """The worker's status, or None when it is not running (no status, or one older than ALIVE_S)."""
    st = read(ANSWERS / "status.json")
    return st if st and time.time() - st.get("ts", 0) < ALIVE_S else None


def submit(kind, values, files=None):
    """-> the request's id. Refused at once, with the reason, when the worker is not running or the kind is not approved
    there; the worker checks every value and the patch again (it trusts nothing that comes from WSL)."""
    import deployment as DEPLOY
    if not DEPLOY.has("windows-worker"):
        raise Refused("not configured: the feature windows-worker is off in this deployment")
    if not KIND.fullmatch(str(kind)):
        raise Refused(f"{kind!r} is no job kind's name")
    if not all(isinstance(v, (str, int, bool)) for v in values.values()):
        raise Refused("a job's values are strings, numbers or true/false")
    st = status()
    if not st:
        raise Refused("the Windows worker is not answering: the PC may be asleep, or the worker is not installed (ops/windows/worker-setup.ps1)")
    k = (st.get("kinds") or {}).get(kind)
    if not k:
        raise Refused(f"no job kind {kind} is declared on Windows (declared: {', '.join(sorted(st.get('kinds') or {})) or 'none'})")
    if not k.get("approved"):
        raise Refused(k.get("why") or f"the job kind {kind} is not approved on Windows")
    files = files or {}
    for name, text in files.items():
        if not FILE.fullmatch(name) or name == "request.json":
            raise Refused(f"{name!r} is no file name a request may carry")
        if len(text.encode()) > FILES_KB * 1024:
            raise Refused(f"{name} is {len(text.encode()) // 1024} KB; {FILES_KB} KB at most")
    rid = uuid.uuid4().hex[:12]                             # cap: id
    tmp = REQUESTS / f".tmp-{rid}"
    tmp.mkdir(parents=True)
    for name, text in files.items():
        (tmp / name).write_text(text, encoding="utf-8")
    (tmp / "request.json").write_text(json.dumps({"id": rid, "kind": kind, "values": values, "at": int(time.time())}), encoding="utf-8")
    os.replace(tmp, REQUESTS / rid)                        # the broker sees the whole request or none of it
    return rid


def state(rid, submitted=None, now=None):
    """Where a request stands: done, failed or refused (the worker's result), lost (its heartbeat stopped), running,
    queued, or not picked up."""
    now = now or time.time()
    res = read(ANSWERS / rid / "result.json")
    if res:
        return res
    claim = read(ANSWERS / rid / "claimed.json")
    if claim:
        if now - float(claim.get("beat") or 0) > LEASE_S:
            return {"id": rid, "status": "lost", "error": "the Windows worker stopped answering while it ran the job (its heartbeat is older than a minute)"}
        return {"id": rid, "status": "running"}
    waiting = (REQUESTS / rid).exists()
    if submitted and now - submitted > PICKUP_S:
        return {"id": rid, "status": "not picked up", "error": "the request was not picked up within 5 minutes: the PC may be asleep"}
    return {"id": rid, "status": "queued" if waiting else "taken"}


def wait(rid, timeout, poll=3, retry_kind=None, values=None, files=None, sleep=time.sleep):
    """The request's final state; a lost job whose kind may retry runs once more (a new request)."""
    t0, retried = time.time(), False
    while True:
        st = state(rid, submitted=t0)
        if st["status"] in ("done", "failed", "refused", "not picked up"):
            return st
        if st["status"] == "lost":
            k = ((status() or {}).get("kinds") or {}).get(retry_kind or "", {})
            if retry_kind and k.get("retry") and not retried:
                rid, t0, retried = submit(retry_kind, values or {}, files), time.time(), True
                continue
            return st
        if time.time() - t0 > timeout:
            return {"id": rid, "status": "failed", "error": f"no result within {timeout // 60} minutes"}
        sleep(poll)


def step_kind(job_kind, values_of, files_of=None, minutes=60):
    """A step kind's adapter that runs one job on Windows: values_of(t, s) and files_of(t, s) give the request's values and
    files; the answer is the job's result, with its artifacts named as evidence. Build output is untrusted text."""
    def run(c, t, s, prompt, card):
        values = values_of(t, s)
        files = files_of(t, s) if files_of else {}
        rid = submit(job_kind, values, files)
        st = wait(rid, timeout=minutes * 60, retry_kind=job_kind, values=values, files=files)
        if st["status"] != "done":
            raise RuntimeError(f"Windows job {job_kind} ({rid}): {st['status']}: {st.get('error') or ''}")
        arts = ", ".join(st.get("artifacts") or [])
        return f"The Windows job {job_kind} ({rid}) passed its {len(st.get('steps') or [])} steps. Evidence (untrusted output): {arts}"
    return run
