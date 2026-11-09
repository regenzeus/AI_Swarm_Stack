"""images/mission-control/otlp.py: Claude Code runs as OTLP traces for Phoenix, protobuf written by hand (SWM-79)."""
import struct

import otlp

EVENTS = [{"ts": 100.0, "kind": "run", "title": "Claude Code started"},
          {"ts": 101.0, "kind": "llm", "title": "claude-opus-5-5", "tokens": {"in": 1200, "out": 80, "cached": 900}},
          {"ts": 101.5, "kind": "call", "title": "Read", "detail": '{"file_path": "ops/doctor.py"}'},
          {"ts": 102.0, "kind": "result", "title": "Read", "detail": "def doctor(c): ..."},
          {"ts": 103.0, "kind": "call", "title": "Grep", "detail": '{"pattern": "covers"}'},
          {"ts": 103.2, "kind": "error", "title": "Grep", "detail": "no such file"},
          {"ts": 104.0, "kind": "llm", "title": "claude-opus-5-5", "tokens": {"in": 1500, "out": 300, "cached": 1200}},
          {"ts": 105.0, "kind": "end", "status": "done", "title": "Claude Code finished"}]


def decode(buf):
    """A minimal protobuf reader for the test: -> [(field, wire, value)] (value: int, bytes or nested bytes)."""
    out, i = [], 0
    while i < len(buf):
        tag, i = _uvarint(buf, i)
        num, wire = tag >> 3, tag & 7
        if wire == 0:
            v, i = _uvarint(buf, i)
        elif wire == 1:
            v, i = struct.unpack("<Q", buf[i:i + 8])[0], i + 8
        elif wire == 2:
            n, i = _uvarint(buf, i)
            v, i = buf[i:i + n], i + n
        else:
            raise ValueError(wire)
        out.append((num, wire, v))
    return out


def _uvarint(b, i):
    n = shift = 0
    while True:
        x = b[i]
        i += 1
        n |= (x & 0x7F) << shift
        shift += 7
        if not x & 0x80:
            return n, i


def test_a_claude_run_becomes_one_trace_with_model_and_tool_spans():
    spans = otlp.spans_of("claude:doctor:abc", "doctor", EVENTS, "Health doctor run", "crew:doctor:1")
    names = [s["name"] for s in spans]
    assert names == ["invoke_agent doctor", "chat claude-opus-5-5", "execute_tool Read", "execute_tool Grep", "chat claude-opus-5-5"]
    root, chat1, read, grep, chat2 = spans
    assert {s["trace_id"] for s in spans} == {root["trace_id"]} and all(s.get("parent_id") == root["span_id"] for s in spans[1:])
    assert root["attrs"]["gen_ai.usage.input_tokens"] == 2700 and root["attrs"]["gen_ai.usage.output_tokens"] == 380
    assert root["attrs"]["aistack.ref"] == "crew:doctor:1" and root["attrs"]["openinference.span.kind"] == "AGENT"
    assert (read["start"], read["end"]) == (101.5, 102.0) and read["attrs"]["input.value"].startswith('{"file_path"')
    assert grep["error"] == "no such file" and chat2["attrs"]["llm.token_count.prompt_details.cache_read"] == 1200
    assert otlp.spans_of("claude:doctor:abc", "doctor", EVENTS)[0]["span_id"] == root["span_id"]   # re-export: the same ids


def test_the_protobuf_is_an_otlp_export_request():
    spans = otlp.spans_of("claude:x:1", "builder", EVENTS[:4])
    req = decode(otlp.encode(spans))
    assert [f for f, _, _ in req] == [1]                                  # ExportTraceServiceRequest.resource_spans
    rs = decode(req[0][2])
    resource, scope_spans = rs[0][2], rs[1][2]
    kv = decode(decode(resource)[0][2])
    assert kv[0][2] == b"service.name" and decode(kv[1][2])[0][2] == b"aistack"
    ss = decode(scope_spans)
    span_msgs = [v for f, _, v in ss if f == 2]
    assert len(span_msgs) == 3
    root = {f: v for f, _, v in decode(span_msgs[0])}
    assert root[1] == bytes.fromhex(spans[0]["trace_id"]) and len(root[1]) == 16 and len(root[2]) == 8
    assert root[5] == b"invoke_agent builder" and root[7] == 100 * 10**9 and root[8] == 102 * 10**9
    attrs = {decode(v)[0][2]: decode(decode(v)[1][2])[0] for f, _, v in decode(span_msgs[0]) if f == 9}
    assert attrs[b"gen_ai.usage.input_tokens"] == (3, 0, 1200)            # an int64 AnyValue
    child = {f: v for f, _, v in decode(span_msgs[1])}
    assert child[4] == bytes.fromhex(spans[0]["span_id"])                 # parent_span_id


def test_only_claude_runs_are_traced_when_they_end(tmp_path, monkeypatch):
    import runrecord as RR
    monkeypatch.setattr(RR, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RR, "_db", None)
    sent = []
    monkeypatch.setattr(otlp, "export_later", lambda spans: sent.append(spans))
    base = {"run": "claude:claude-task:s1", "agent": "claude-task", "source": "claude"}
    RR.ingest([{**base, **e} for e in EVENTS])
    assert len(sent) == 1 and sent[0][0]["name"] == "invoke_agent claude-task"
    RR.ingest([{"run": "hermes:main:x", "agent": "main", "source": "hermes", "ts": 1, "kind": "run"},
               {"run": "hermes:main:x", "agent": "main", "source": "hermes", "ts": 2, "kind": "end", "status": "done"}])
    assert len(sent) == 1                                                 # gateway runs are traced by LiteLLM already


def test_a_task_run_is_one_trace_from_the_run_to_every_model_and_tool_call():
    """TSK-26: the run is the root, each step under it, the agent runs a step started under the step, their calls under them."""
    runs = [{"run": "task:5", "ref": "task-intake:5-0", "agent": "conductor", "title": "Task #5", "started": 100, "ended": 200},
            {"run": "task:5:step:1", "ref": "task:5", "agent": "scout", "title": "Step 1", "started": 101, "ended": 150},
            {"run": "hermes:scout:a", "ref": "task:5:step:1", "agent": "scout", "title": "", "started": 102, "ended": 149},
            {"run": "task:5:step:2", "ref": "task:5", "agent": "desk", "title": "Step 2", "started": 151, "ended": 199}]
    events = {"hermes:scout:a": [{"ts": 103, "kind": "call", "title": "web_search", "detail": "{}"}, {"ts": 104, "kind": "result", "title": "web_search", "detail": "[]"},
                                 {"ts": 110, "kind": "llm", "title": "gpt-sub-fast", "tokens": {"in": 10, "out": 2}}],
              "task:5:step:2": [{"ts": 160, "kind": "llm", "title": "gpt-sub", "tokens": {"in": 5, "out": 1}}]}
    spans = otlp.tree_spans("task:5", runs, events)
    assert len({s["trace_id"] for s in spans}) == 1
    by = {s["span_id"]: s for s in spans}
    roots = [s for s in spans if not s.get("parent_id")]
    assert [s["name"] for s in roots] == ["invoke_agent conductor"]
    def path(s):
        out = [s["name"]]
        while s.get("parent_id"):
            s = by[s["parent_id"]]
            out.append(s["name"])
        return out
    tool = next(s for s in spans if s["name"] == "execute_tool web_search")
    assert path(tool) == ["execute_tool web_search", "invoke_agent scout", "invoke_agent scout", "invoke_agent conductor"]
    chat = next(s for s in spans if s["name"] == "chat gpt-sub")
    assert path(chat) == ["chat gpt-sub", "invoke_agent desk", "invoke_agent conductor"]
    assert otlp.encode(spans)                                                        # the protobuf takes the tree

