#!/usr/bin/env python3
"""Claude Code hook → the AI stack runtime record (images/mission-control/runrecord.py). Builder sandbox only.

Registered for SessionStart, PreToolUse, PostToolUse and Stop (claude-runtime-settings.json, passed with --settings by
ops/builds.py and ops/claude_tasks.py). Reads the hook's JSON on stdin and appends events to
/work/.runtime/claude-<session>.jsonl; the runner forwards them (the sandbox can't reach Mission Control). On every call
it also reads the new lines of Claude's own transcript, which carry what the hooks don't: model calls with tokens
and cache, what Claude says, and its thinking when sent. Never blocks, never prints, always exits 0.
"""
import json
import os
import sys
import time
from pathlib import Path

SPOOL = Path(os.environ.get("RUNTIME_SPOOL", "/work/.runtime"))
MAX = 20000


def main():
    try:
        h = json.load(sys.stdin)
    except Exception:
        return
    sid = str(h.get("session_id") or "nosession")
    run = f"claude:{os.environ.get('AISTACK_AGENT', 'claude')}:{sid[:16]}"
    base = {"run": run, "agent": os.environ.get("AISTACK_AGENT", "claude"), "source": "claude", "ref": os.environ.get("AISTACK_REF") or None}
    ev = h.get("hook_event_name")
    if ev == "Stop":
        time.sleep(1.5)                               # Claude writes its final message to the transcript just after Stop
    out = transcript_events(h, base, sid)
    now = time.time()
    if ev == "SessionStart":
        out.append({**base, "ts": now, "kind": "run", "title": "Claude Code started", "run_title": os.environ.get("AISTACK_TITLE", "")[:200],
                    "data": {"manifest": {"agent": base["agent"], "engine": "claude-code", "model": h.get("model") or os.environ.get("ANTHROPIC_MODEL", ""),
                                          "cwd": h.get("cwd"), "source": h.get("source")},
                             "box": json.loads(os.environ["AISTACK_BOX"]) if os.environ.get("AISTACK_BOX") else None}})
    elif ev == "PreToolUse":
        out.append({**base, "ts": now, "kind": "call", "title": h.get("tool_name"), "detail": json.dumps(h.get("tool_input") or {}, ensure_ascii=False)[:MAX]})
    elif ev == "PostToolUse":
        resp = h.get("tool_response")
        text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False, default=str)
        err = isinstance(resp, dict) and (resp.get("is_error") or resp.get("error") or resp.get("interrupted"))
        out.append({**base, "ts": now, "kind": "error" if err else "result", "title": h.get("tool_name"), "detail": (text or "")[:MAX],
                    "status": "failure" if err else "success"})
    elif ev == "Stop":
        out.append({**base, "ts": now, "kind": "end", "status": "done", "title": "Claude Code finished"})
    if out:
        _mkspool()
        with open(SPOOL / f"claude-{sid[:16]}.jsonl", "a") as f:
            for e in out:
                f.write(json.dumps({k: v for k, v in e.items() if v is not None}, default=str) + "\n")


def transcript_events(h, base, sid):
    """New assistant messages in Claude's transcript since the last hook call: llm (usage), say, think."""
    path = h.get("transcript_path")
    if not path or not os.path.exists(path):
        return []
    mark = SPOOL / f"claude-{sid[:16]}.offset"
    try:
        start, last_id = (mark.read_text().split() + [""])[:2]
        start = int(start)
    except Exception:
        start, last_id = 0, ""
    out = []
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read()
        end = start + len(data.rsplit(b"\n", 1)[0]) + 1 if b"\n" in data else start
    for line in data[:end - start].splitlines():
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("type") != "assistant":
            continue
        msg, ts = m.get("message") or {}, _ts(m.get("timestamp"))
        u = msg.get("usage") or {}
        if u and msg.get("id") and msg["id"] == last_id:
            u = {}                                    # one model call is written as one line per content block: count it once
        last_id = msg.get("id") or last_id
        if u:
            tin = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
            out.append({**base, "ts": ts, "kind": "llm", "title": msg.get("model") or "claude", "status": "success",
                        "tokens": {"in": tin, "out": u.get("output_tokens") or 0, "cached": u.get("cache_read_input_tokens") or 0, "reasoning": 0}})
        for b in msg.get("content") or []:
            if b.get("type") == "text" and (b.get("text") or "").strip():
                out.append({**base, "ts": ts, "kind": "say", "title": "Says", "detail": b["text"][:MAX]})
            elif b.get("type") == "thinking" and (b.get("thinking") or "").strip():
                out.append({**base, "ts": ts, "kind": "think", "title": "Thinking", "detail": b["thinking"][:MAX]})
    try:
        _mkspool()
        mark.write_text(f"{end} {last_id}")
    except Exception:
        pass
    return out


def _mkspool():
    """The runner (another user on the host) claims and deletes files here, so the folder is writable for it."""
    if not SPOOL.exists():
        SPOOL.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(SPOOL, 0o777)
        except OSError:
            pass


def _ts(v):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
