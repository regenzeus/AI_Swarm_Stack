"""The runner's side of the agent runtime record (images/mission-control/runrecord.py, docs/OBSERVABILITY.md).

  emit(run, kind, ...)  one event from the runner itself: a mission run, build, Claude task or Crew job starting,
                        reaching a stage, ending. Sent at once; spooled under ~/.local/share/aistack/runtime-spool
                        if Mission Control doesn't answer, and resent by the forwarder.
  forwarder()           a thread: sends the JSONL spools of the containers that can't reach Mission Control (the
                        builder sandbox's Hermes plugin and Claude Code hooks in /srv/ai/workbench/.runtime, the AI
                        phone in /srv/ai/phone/runtime, the mail connector in /srv/ai/connections/runtime) and its own spool.
  ref()                 the run the current thread works for (mission-run:15, build:7, claude-task:3): passed to Hermes
                        and Claude Code as AISTACK_REF so their runs show up under it.
Never raises into the caller; observability must not break a run.
"""
import re
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from textcap import STORE, cut                    # visible caps and input limits (AGENTS.md, truncation)

INGEST = os.environ.get("RUNTIME_INGEST_HOST", "http://127.0.0.1:8093/ingest")
KEY = os.environ.get("API_SERVER_KEY", "")
OWN = Path.home() / ".local/share/aistack/runtime-spool"
SPOOLS = [Path("/srv/ai/workbench/.runtime"), Path("/srv/ai/phone/runtime"), Path("/srv/ai/connections/runtime"), OWN]
_local = threading.local()


def ref():
    return getattr(_local, "ref", None)


def set_ref(value, agent=None):
    _local.ref = value
    _local.agent = agent


def stage(title, detail="", ms=None, kind="stage", status=None, tokens=None):
    """One step of the current run, for pipelines that work without an agent (cleanup, briefings, deep research,
    crew): what it starts, waits for, finds, and its errors. No-op outside a run."""
    r = ref()
    if r:
        emit(r, kind, agent=getattr(_local, "agent", None) or "runner", title=title, detail=cut(str(detail or ""), STORE), status=status, ms=ms,  # cap: store
             data={"tokens": tokens} if tokens else None)


def touched(path, changed=False, note=""):
    """A file the current run read or wrote itself (a report, the Windows scan), for "What it touches"."""
    tool = "write_file" if changed else "read_file"
    stage(tool, json.dumps({"path": str(path)}), kind="call")
    stage(tool, note or ("written" if changed else "read"), kind="result", status="success")


def model_call(model, ms, usage=None, error=""):
    """A direct model call of the runner (not through Hermes), with its tokens."""
    u = usage or {}
    stage(model, error, ms=ms, kind="llm", status="failure" if error else "success",
          tokens={"in": u.get("prompt_tokens") or 0, "out": u.get("completion_tokens") or 0,
                  "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                  "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0})


LINKS = Path("/srv/ai/missions/public/links.jsonl")


def link(to, via, text="", frm=None):
    """SWM-113: this run handed something to another agent through a file or a folder (a mail filed for the curator): one
    row of the map's hand-overs. Never raises into the caller."""
    who = frm or str(getattr(_local, "agent", None) or "runner")
    try:
        with LINKS.open("a") as f:
            f.write(json.dumps({"ts": time.time(), "from": who[5:] if who.startswith("crew:") else who, "to": to, "via": str(via), "text": str(text), "run": ref()}, ensure_ascii=False) + "\n")
    except OSError:
        pass


def env_args():
    """`-e` arguments for a `docker exec` so the agent inside reports under the current run."""
    r = ref()
    return ["-e", f"AISTACK_REF={r}"] if r else []


def _post(batch):
    """True when stored; "refused" when the app answers that the batch cannot be read (it never will be: set aside, never
    sent again); False when the app is away (sent again next round)."""
    if not KEY:
        return False
    try:
        req = urllib.request.Request(INGEST, data=json.dumps(batch, default=str).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return "refused" if e.code in (400, 413, 422) else False
    except Exception:
        return False


BATCH_BYTES = 1_000_000                                   # limit: paces (a batch of events sent at once; the app reads 4 MB)


def batches(evs):
    """At most 200 events and about BATCH_BYTES each (review RUN-R17: 200 large events passed the app's 4 MB, were cut and
    refused as "not JSON", and were sent again forever)."""
    out, cur, size = [], [], 0
    for e in evs:
        n = len(json.dumps(e, default=str))
        if cur and (len(cur) >= 200 or size + n > BATCH_BYTES):
            out.append(cur)
            cur, size = [], 0
        cur.append(e)
        size += n
    return out + ([cur] if cur else [])


def emit(run, kind, agent="runner", title="", detail="", status=None, data=None, ref_=None, run_title=None, ms=None):
    e = {"run": run, "kind": kind, "agent": agent, "source": "runner", "ts": time.time()}
    if data and "tokens" in data and len(data) == 1:
        e["tokens"], data = data["tokens"], None
    for k, v in (("title", title), ("detail", detail), ("status", status), ("data", data), ("ref", ref_), ("run_title", run_title), ("ms", ms)):
        if v not in (None, ""):
            e[k] = v
    if not _post([e]):
        try:
            OWN.mkdir(parents=True, exist_ok=True)
            with open(OWN / f"runner-{time.strftime('%Y%m%d')}.jsonl", "a") as f:
                f.write(json.dumps(e, default=str) + "\n")
        except OSError:
            pass


def start(run, agent, title, data=None, ref=None, detail=""):
    """ref: what started it (a run, or an agent like crew:doctor), so the Swarm page links them; detail: what it was asked."""
    emit(run, "run", agent=agent, title="started", run_title=title, data=data, ref_=ref, detail=detail)


def end(run, agent, state, detail="", seconds=None):
    """state: done | failed | stopped | stalled | limit (the runtime's end states). A run that was given memory has it measured
    (MEM-44: what it used, its outcome, the tallies of the lessons it was given), a few seconds later in its own thread so the
    run's last events have arrived."""
    emit(run, "end", agent=agent, title=state, status=state, detail=detail, ms=int(seconds * 1000) if seconds else None)
    if run and state in ("done", "failed"):
        import threading

        def measure():
            time.sleep(15)
            try:
                import memstack as MS
                MS.after_run(run, state)
            except Exception as e:
                print(f"runtime: the memory of {run} was not measured: {type(e).__name__}: {e}", flush=True)
        threading.Thread(target=measure, daemon=False).start()     # not a daemon: a crew job's own process waits for its measurement


def mission_state(status, summary=""):
    """The runner's run status → a runtime end state."""
    s = (summary or "").lower()
    if status == "ok":
        return "done"
    if status == "waiting" or "usage limit" in s or "rate limit" in s:
        return "limit"
    if "interrupted" in s:
        return "stopped"
    return "failed"


def problems(hours=24, by=""):
    """Problems of runs that ended in the last hours (no arguments, unknown tools, repeats, cut-off reads, limits,
    stalls, lost tools): for the Agent health board and its once-per-issue alerts."""
    if not KEY:
        return []
    try:
        req = urllib.request.Request(INGEST.rsplit("/", 1)[0] + f"/problems?hours={hours}" + (f"&by={by}" if by else ""), headers={"Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.load(r)
    except Exception:
        return []


def forward_once():
    """Send every spooled JSONL file (claimed by renaming first, so a writer appending meanwhile starts a new file)."""
    sent = 0
    for d in SPOOLS:
        if not d.exists():
            continue
        claimed = []
        for f in sorted(d.glob("*.jsonl")):
            if f.is_symlink() or not f.is_file():         # review RUN-R17: the sandbox writes this spool; a link is never followed
                continue
            c = f.with_name(f"{f.stem}.{time.time_ns()}.sending")
            try:
                f.rename(c)
                claimed.append(c)
            except OSError:
                continue
        if claimed:
            time.sleep(0.2)                                 # a writer that had the file open finishes its line
        for c in sorted(d.glob("*.sending")):               # this round's, and what a failed round left
            if c.is_symlink() or not c.is_file():
                continue
            try:
                lines = [x for x in c.read_text(errors="replace").splitlines() if x.strip()]
                evs = []
                for x in lines:
                    try:
                        evs.append(json.loads(x))
                    except ValueError:
                        pass                                # a torn line: dropped
            except OSError:
                continue
            parts = batches(evs)
            for k, part in enumerate(parts):
                ok = _post(part)
                if ok == "refused":                         # unreadable to the app: kept aside with the reason, the rest goes on
                    try:
                        with c.with_suffix(".refused").open("a") as f:
                            f.write("".join(json.dumps(e, default=str) + "\n" for e in part))
                    except OSError:
                        pass
                    print(f"runtime: {len(part)} events the app refused were set aside in {c.with_suffix('.refused').name}", flush=True)
                    continue
                if not ok:
                    try:                                    # keep only what wasn't sent; next round resends it
                        c.write_text("".join(json.dumps(e, default=str) + "\n" for p in parts[k:] for e in p))
                    except OSError:
                        pass
                    return sent
                sent += len(part)
            c.unlink(missing_ok=True)
    return sent


def prepare():
    """The builder sandbox can't create folders in /work (the host's workbench, owned by the runner's user): make its
    spool here, writable for the container's user, like .claude-tasks."""
    d = SPOOLS[0]
    try:
        d.mkdir(parents=True, exist_ok=True)
        d.chmod(0o777)
    except OSError:
        pass


def forwarder(stop):
    prepare()
    while not stop.is_set():
        try:
            forward_once()
        except Exception:
            pass
        stop.wait(2)



UNREACHABLE = re.compile(r"no route to host|network is unreachable|could not resolve host|name resolution|connection timed out|connection refused|connection reset", re.I)


def unreachable(text):
    """True when a run failed because the network or the NAS was away for a moment, not because of what it did (task 171)."""
    return bool(UNREACHABLE.search(text or ""))
