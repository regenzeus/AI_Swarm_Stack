"""Runs of Claude Code agents as OpenTelemetry traces in Phoenix (SWM-79, FND-25), with no OpenTelemetry library.

Claude Code runs on the Claude subscription outside the gateway, so LiteLLM never traces them. Their runtime-record
events (the hooks in config/hermes/claude-hooks: llm with tokens, call/result per tool, end) become, when the run ends:
  invoke_agent <agent>      the run (gen_ai.agent.name, aistack.run.id, the ref it belongs to, token totals)
    chat <model>            one per model call, with gen_ai.usage.* and OpenInference's llm.token_count.*
    execute_tool <tool>     one per tool call, from its call to its result, input and output truncated
The names follow the OpenTelemetry GenAI conventions (development status) and Phoenix's OpenInference span kinds.
Phoenix takes OTLP over HTTP as protobuf only; this module writes the few messages a trace needs by hand.
Never raises: tracing must not break a run.
"""
import os
import struct
import threading
import urllib.request

PHOENIX = os.environ.get("PHOENIX_URL", "http://phoenix:6006")
MAX = 4000


# ---------------------------------------------------------------- protobuf, the minimum
def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _field(num, wire, payload):
    tag = _varint((num << 3) | wire)
    if wire == 2:
        return tag + _varint(len(payload)) + payload
    return tag + payload


def _str(num, s):
    return _field(num, 2, str(s).encode())


def _bytes(num, b):
    return _field(num, 2, b)


def _msg(num, body):
    return _field(num, 2, body)


def _fixed64(num, n):
    return _field(num, 1, struct.pack("<Q", int(n)))


def _anyvalue(v):
    if isinstance(v, bool):
        return _field(2, 0, _varint(int(v)))
    if isinstance(v, int):
        return _field(3, 0, _varint(v & 0xFFFFFFFFFFFFFFFF))
    if isinstance(v, float):
        return _field(4, 1, struct.pack("<d", v))
    return _str(1, v)


def _kv(key, value):
    return _str(1, key) + _msg(2, _anyvalue(value))


def encode(spans, service="aistack"):
    """[{trace_id, span_id, parent_id?, name, kind, start, end (s), attrs, error?}] -> ExportTraceServiceRequest bytes."""
    body = b""
    for s in spans:
        sp = (_bytes(1, bytes.fromhex(s["trace_id"])) + _bytes(2, bytes.fromhex(s["span_id"]))
              + (_bytes(4, bytes.fromhex(s["parent_id"])) if s.get("parent_id") else b"")
              + _str(5, s["name"]) + _field(6, 0, _varint(s.get("kind", 1)))
              + _fixed64(7, s["start"] * 1e9) + _fixed64(8, max(s["end"], s["start"]) * 1e9)
              + b"".join(_msg(9, _kv(k, v)) for k, v in s.get("attrs", {}).items() if v not in (None, "")))
        if s.get("error"):
            sp += _msg(15, _str(2, s["error"][:500]) + _field(3, 0, _varint(2)))   # STATUS_CODE_ERROR  # cap: api
        body += _msg(2, sp)
    scope = _msg(1, _str(1, "aistack.runtime"))
    resource = _msg(1, _msg(1, _kv("service.name", service)))
    return _msg(1, resource + _msg(2, scope + body))


# ---------------------------------------------------------------- a run's events -> spans
def _id(seed, n):
    import hashlib
    return hashlib.sha256(seed.encode()).hexdigest()[:n * 2]


def spans_of(run, agent, events, title="", ref=None):
    """The runtime record's events of one run -> spans of one trace (ids derived from the run: re-export is idempotent)."""
    ev = sorted(events, key=lambda e: e.get("ts") or 0)
    if not ev:
        return []
    tid, root = _id(run, 16), _id(run + ":root", 8)
    t0, t1 = ev[0]["ts"], ev[-1]["ts"]
    tin = sum((e.get("tokens") or {}).get("in", 0) for e in ev if e.get("kind") == "llm")
    tout = sum((e.get("tokens") or {}).get("out", 0) for e in ev if e.get("kind") == "llm")
    end = next((e for e in reversed(ev) if e.get("kind") == "end"), {})
    out = [{"trace_id": tid, "span_id": root, "name": f"invoke_agent {agent}", "kind": 1, "start": t0, "end": t1,
            "attrs": {"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": agent, "gen_ai.system": "anthropic",
                      "openinference.span.kind": "AGENT", "aistack.run.id": run, "aistack.ref": ref or "", "input.value": title[:MAX],
                      "gen_ai.usage.input_tokens": tin, "gen_ai.usage.output_tokens": tout,
                      "llm.token_count.prompt": tin, "llm.token_count.completion": tout, "llm.token_count.total": tin + tout},
            "error": end.get("detail") if end.get("status") in ("failed", "failure") else None}]
    last = t0
    pending = []                                       # tool calls waiting for their result, in order
    for n, e in enumerate(ev):
        k = e.get("kind")
        if k == "llm":
            tok = e.get("tokens") or {}
            out.append({"trace_id": tid, "span_id": _id(f"{run}:{n}", 8), "parent_id": root, "name": f"chat {e.get('title') or 'claude'}",
                        "kind": 3, "start": last, "end": e["ts"],
                        "attrs": {"gen_ai.operation.name": "chat", "gen_ai.request.model": e.get("title") or "", "openinference.span.kind": "LLM",
                                  "llm.model_name": e.get("title") or "", "gen_ai.usage.input_tokens": tok.get("in", 0),
                                  "gen_ai.usage.output_tokens": tok.get("out", 0), "llm.token_count.prompt": tok.get("in", 0),
                                  "llm.token_count.completion": tok.get("out", 0), "llm.token_count.prompt_details.cache_read": tok.get("cached", 0)}})
        elif k == "call":
            pending.append((n, e))
        elif k in ("result", "error"):
            i = next((j for j, (_, c) in enumerate(pending) if c.get("title") == e.get("title")), 0 if pending else None)
            if i is None:
                continue
            cn, c = pending.pop(i)
            out.append({"trace_id": tid, "span_id": _id(f"{run}:{cn}", 8), "parent_id": root, "name": f"execute_tool {c.get('title') or 'tool'}",
                        "kind": 1, "start": c["ts"], "end": e["ts"],
                        "attrs": {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": c.get("title") or "", "openinference.span.kind": "TOOL",
                                  "tool.name": c.get("title") or "", "input.value": (c.get("detail") or "")[:MAX], "output.value": (e.get("detail") or "")[:MAX]},
                        "error": (e.get("detail") or "error")[:500] if k == "error" else None})  # cap: api
        if e.get("ts"):
            last = e["ts"]
    return out


def export(spans, url=None, timeout=10):
    """POST the spans to Phoenix. -> True when Phoenix took them."""
    if not spans:
        return False
    try:
        req = urllib.request.Request((url or PHOENIX).rstrip("/") + "/v1/traces", data=encode(spans), method="POST",
                                     headers={"Content-Type": "application/x-protobuf"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 300
    except Exception:
        return False


def export_later(spans):
    threading.Thread(target=export, args=(spans,), daemon=True).start()
