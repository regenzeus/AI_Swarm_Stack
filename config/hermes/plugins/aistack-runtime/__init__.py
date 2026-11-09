"""aistack-runtime: this Hermes profile's activity, live, in Mission Control (images/mission-control/runrecord.py).

Observer only. Every hook returns None, never raises, and never waits on the network: events go into a queue that a
background thread sends to RUNTIME_INGEST (Mission Control on mcnet) in small batches. When Mission Control can't
be reached, or no URL is set (the builder sandbox), events are appended to RUNTIME_SPOOL as JSONL; the sender retries
its own spool, and the runner forwards the builder's spool from /work/.runtime.

One run = one turn of one session: it opens with the first event of a turn and closes on on_session_end with an
honest state (done, failed, stopped, limit). AISTACK_REF (set by the runner on `docker exec`) ties a run to a mission
run or build; Mission Control chat sessions (mc-<chat>-<rev>) are tied to their chat.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

INGEST = os.environ.get("RUNTIME_INGEST", "http://mission-control:8093/ingest")
KEY = os.environ.get("API_SERVER_KEY", "")
# limit: drops, a tool result's detail past this in the run record, which marks the cut
MAX = 20000

def _cut(s):
    """The run record's cap (MAX), marked like textcap.cut (this file runs where ops/textcap.py is not)."""
    s = str(s)
    return s if len(s) <= MAX else s[:MAX] + f" [… {len(s) - MAX:,} more characters cut]"  # cap: store
_q: "queue.Queue[dict]" = queue.Queue(maxsize=20000)
_runs: dict[str, str] = {}                 # session id → current run id
_started: dict[str, float] = {}
_tool_t: dict[str, float] = {}
_lock = threading.Lock()
_thread = None
LIMIT = re.compile(r"usage.?limit|rate.?limit|ratelimit|\b429\b|usage_limit_reached", re.I)


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME", "/opt/data"))


def _agent() -> str:
    """The profile: /opt/data → main, /opt/data/profiles/<p> → p, the builder's home → builder."""
    h = str(_home())
    m = re.search(r"/profiles/([^/]+)", h)
    return m.group(1) if m else ("builder" if h.startswith("/builder") else "main")


def _spool() -> Path:
    return Path(os.environ.get("RUNTIME_SPOOL") or (_home() / "runtime-spool"))


def _ref(session_id: str) -> str | None:
    if os.environ.get("AISTACK_REF"):
        return os.environ["AISTACK_REF"]
    m = re.match(r"mc-([a-z0-9]{6,24})-", session_id or "")
    return f"chat:{m.group(1)}" if m else None


def _run(session_id: str, title: str = "") -> str:
    """The current run of a session; opens a new one (with its start event) after the previous turn ended."""
    sid = session_id or "default"
    with _lock:
        run = _runs.get(sid)
        new = run is None
        if new:
            run = f"hermes:{_agent()}:{sid[-16:]}:{uuid.uuid4().hex[:6]}"
            _runs[sid] = run
            _started[run] = time.time()
    if new:
        _emit(run, "run", title="started", run_title=title[:200], ref=_ref(sid), data={"manifest": _manifest(), "session": sid})  # cap: id (the run's title; the message is whole in its chat)
    return run


def _manifest() -> dict:
    man = {"agent": _agent(), "profile_home": str(_home()), "pid": os.getpid()}
    try:
        from tools.mcp_tool_discovery import mcp_servers_ready
        man["mcp"] = sorted(mcp_servers_ready() or [])
    except Exception:
        pass
    return man


def _emit(run: str, kind: str, **kw: Any) -> None:
    e = {"run": run, "agent": _agent(), "source": "hermes", "ts": time.time(), "kind": kind}
    for k, v in kw.items():
        if v is not None and v != "":
            e[k] = v
    if isinstance(e.get("detail"), (dict, list)):
        e["detail"] = json.dumps(e["detail"], ensure_ascii=False, default=str)
    if isinstance(e.get("detail"), str):
        e["detail"] = _cut(e["detail"])  # cap: store
    try:
        _q.put_nowait(e)
    except queue.Full:
        pass
    _ensure_sender()


def _post(batch: list[dict]) -> bool:
    if not INGEST or not KEY:
        return False
    try:
        req = urllib.request.Request(INGEST, data=json.dumps(batch, default=str).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _to_spool(batch: list[dict]) -> None:
    try:
        d = _spool()
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(d, 0o777)                    # the builder's spool is claimed and deleted by the runner (another user)
            except OSError:
                pass
        with open(d / f"hermes-{_agent()}-{time.strftime('%Y%m%d')}.jsonl", "a") as f:
            for e in batch:
                f.write(json.dumps(e, default=str) + "\n")
    except Exception:
        pass


def _flush_spool() -> None:
    """Resend spooled events once Mission Control answers again (only where a URL is set)."""
    if not INGEST:
        return
    d = _spool()
    for f in sorted(d.glob("hermes-*.jsonl")) if d.exists() else []:
        try:
            lines = [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
        except Exception:
            continue
        for i in range(0, len(lines), 200):
            if not _post(lines[i:i + 200]):
                return
        f.unlink(missing_ok=True)


def _sender() -> None:
    last_flush = 0.0
    while True:
        batch = [_q.get()]
        t0 = time.time()
        while len(batch) < 100 and time.time() - t0 < 0.5:
            try:
                batch.append(_q.get(timeout=0.1))
            except queue.Empty:
                pass
        if not _post(batch):
            _to_spool(batch)
        elif time.time() - last_flush > 30:
            last_flush = time.time()
            _flush_spool()


def _ensure_sender() -> None:
    global _thread
    if _thread is None or not _thread.is_alive():
        with _lock:
            if _thread is None or not _thread.is_alive():
                _thread = threading.Thread(target=_sender, name="aistack-runtime", daemon=True)
                _thread.start()


# ---------- hooks: observers only ----------
def _on_pre_llm_call(session_id: str = "", user_message: str = "", is_first_turn: bool = False, model: str = "", **_: Any) -> None:
    try:
        _run(session_id, str(user_message or "")[:200])  # cap: id (the run's title; the message is whole in its chat)
    except Exception:
        pass


def _on_post_api_request(session_id: str = "", model: str = "", usage: Any = None, api_duration: float = 0.0,
                         finish_reason: str = "", assistant_message: Any = None, response_model: str = "", **_: Any) -> None:
    try:
        run = _run(session_id)
        u = usage if isinstance(usage, dict) else {}       # CanonicalUsage as a dict: prompt_tokens = input incl. cache
        tin = u.get("prompt_tokens") or u.get("input_tokens") or 0
        tout = u.get("output_tokens") or 0
        cached = u.get("cache_read_tokens") or 0
        reasoning = u.get("reasoning_tokens") or 0
        _emit(run, "llm", title=response_model or model, ms=int((api_duration or 0) * 1000), status="success",
              tokens={"in": int(tin or 0), "out": int(tout or 0), "cached": int(cached or 0), "reasoning": int(reasoning or 0)},
              data={"finish": finish_reason})
        content = getattr(assistant_message, "content", None) if assistant_message is not None else None
        if isinstance(content, str) and content.strip():
            _emit(run, "say", title="Says", detail=content)
        think = getattr(assistant_message, "reasoning_content", None) or getattr(assistant_message, "reasoning", None)
        if isinstance(think, str) and think.strip():
            _emit(run, "think", title="Thinking", detail=think)
    except Exception:
        pass


def _on_api_request_error(session_id: str = "", model: str = "", error: Any = None, status_code: Any = None, reason: str = "",
                          api_duration: float = 0.0, **_: Any) -> None:
    try:
        e = error if isinstance(error, dict) else {"message": str(error or "")}
        msg = " ".join(str(x) for x in (status_code or "", e.get("type") or "", e.get("message") or "", reason or "") if x)   # an error is kept whole (AGENTS.md); the event's own cap marks it
        _emit(_run(session_id), "llm", title=model, status="failure", detail=msg, ms=int((api_duration or 0) * 1000),
              tokens={"in": 0, "out": 0, "cached": 0, "reasoning": 0},
              data={"limit": bool(LIMIT.search(msg))})
    except Exception:
        pass


def _on_pre_tool_call(tool_name: str = "", args: Any = None, session_id: str = "", tool_call_id: str = "", **_: Any) -> None:
    try:
        run = _run(session_id)
        _tool_t[tool_call_id or tool_name] = time.time()
        _emit(run, "call", title=tool_name, detail=args if isinstance(args, (dict, list)) else str(args or ""),
              data={"call_id": tool_call_id})
    except Exception:
        pass
    return None                                   # never veto: this plugin only records


def _on_post_tool_call(tool_name: str = "", args: Any = None, result: Any = None, session_id: str = "", tool_call_id: str = "",
                       duration_ms: int = 0, status: str = "", error_type: str = "", error_message: str = "", **_: Any) -> None:
    try:
        run = _run(session_id)
        _tool_t.pop(tool_call_id or tool_name, None)
        err = (status or "").lower() in ("error", "failed", "failure") or bool(error_message)
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        _emit(run, "error" if err else "result", title=tool_name, ms=int(duration_ms or 0), status="failure" if err else "success",
              detail=(f"{error_type}: {error_message}\n" if err and error_message else "") + _cut(text or ""),  # cap: store
              data={"call_id": tool_call_id, "chars": len(text or "")})
    except Exception:
        pass


def _on_subagent_start(session_id: str = "", child_session_id: str = "", **kw: Any) -> None:
    try:
        _emit(_run(session_id), "stage", title="sub-agent started", detail=str(child_session_id or kw.get("subagent_id") or ""))
    except Exception:
        pass


def _on_session_end(session_id: str = "", completed: bool = True, failed: bool = False, interrupted: bool = False,
                    turn_exit_reason: str = "", **_: Any) -> None:
    """Close this turn's run with an honest state; the next turn opens a new run."""
    try:
        sid = session_id or "default"
        with _lock:
            run = _runs.pop(sid, None)
        if not run:
            return
        reason = str(turn_exit_reason or "")
        state = ("limit" if LIMIT.search(reason) else "stopped" if interrupted else "failed" if failed or not completed else "done")
        _emit(run, "end", title=state, status=state, detail=reason, ms=int((time.time() - _started.pop(run, time.time())) * 1000))
    except Exception:
        pass


def register(ctx) -> None:
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("post_api_request", _on_post_api_request)
    ctx.register_hook("api_request_error", _on_api_request_error)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("subagent_start", _on_subagent_start)
    ctx.register_hook("on_session_end", _on_session_end)
