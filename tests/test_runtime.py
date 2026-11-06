"""The agent runtime record: Mission Control's store (images/mission-control/runrecord.py), the Hermes plugin, the Claude
Code hook and the runner's forwarder (ops/runtime.py). No network: posts go to fakes, files to tmp_path."""
import importlib.util
import io
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def RT(tmp_path, monkeypatch):
    import runrecord as RT
    monkeypatch.setattr(RT, "DB", tmp_path / "runtime.db")
    monkeypatch.setattr(RT, "_db", None)
    return RT


def ev(run, kind, ts, **kw):
    return {"run": run, "kind": kind, "ts": ts, "agent": kw.pop("agent", "mission"), **kw}


def test_a_run_opens_on_first_event_and_stays_closed_after_its_end(RT):
    t = time.time() - 100
    RT.ingest([ev("r1", "run", t, run_title="Weekly RAM", data={"manifest": {"agent": "mission", "mcp": ["mail", "web"]}}),
               ev("r1", "llm", t + 1, title="gpt-5.5", tokens={"in": 1000, "out": 50, "cached": 800}, ms=900),
               ev("r1", "call", t + 2, title="read_file", detail=json.dumps({"path": "/work/ai-stack/ops/x.py"})),
               ev("r1", "result", t + 3, title="read_file", detail="ok", status="success"),
               ev("r1", "end", t + 4, status="limit", title="limit")])
    assert RT.ingest([ev("r1", "end", t + 5, status="done"), ev("r1", "say", t + 6, detail="late")]) == 0
    v = RT.view("r1")
    assert v["end_state"] == "limit" and not v["live"] and v["title"] == "Weekly RAM"
    assert [e["kind"] for e in v["events"]] == ["run", "llm", "call", "result", "end"]
    assert v["touches"]["files"][0]["path"] == "ops/x.py" and v["stats"]["model"]["cache_pct"] == 80
    s = RT.runs()[0]["summary"]
    assert s["end_state"] == "limit" and s["model_calls"] == 1 and s["tokens_in"] == 1000 and s["files_read"] == 1
    assert RT.otel_name({"kind": "call", "title": "read_file"}) == "execute_tool read_file" and RT.otel_name({"kind": "llm"}) == "chat"


def test_unknown_end_states_become_done_and_bad_events_are_skipped(RT):
    assert RT.ingest([{"kind": "say"}, {"run": "x"}, ev("x", "end", time.time(), status="weird")]) == 1
    assert RT.runs()[0]["end_state"] == "done"


def test_children_show_under_their_parent_and_keep_it_alive(RT):
    t = time.time() - 3000
    RT.ingest([ev("mission-run:5", "run", t, agent="runner")])
    RT.ingest([ev("hermes:mission:abc:1", "run", t + 2000, ref="mission-run:5"), ev("hermes:mission:abc:1", "say", t + 2001, detail="hi")])
    v = RT.view("mission-run:5")
    assert [c["run"] for c in v["children"]] == ["hermes:mission:abc:1"] and any(e["kind"] == "say" for e in v["events"])
    assert RT.watchdog_once(now=t + 2001 + RT.STALL_S - 10) == []          # the child's activity counts for the parent
    assert [r["run"] for r in RT.runs(live=True)] == ["mission-run:5"]       # the child isn't listed twice
    assert RT.view("mission-run")["run"] == "mission-run:5"                  # a short id opens the newest run
    RT.ingest([ev("hermes:main:x:1", "run", t + 5, ref="chat:abc123", agent="main", run_title="hi")])
    assert RT.view("chat:abc123")["run"] == "hermes:main:x:1"                # a chat opens its last turn
    RT.CHAT_TITLE = lambda cid: "RAM prices"
    assert RT.view("chat:abc123")["name"] == "Chat · RAM prices"
    RT.CHAT_TITLE = None
    assert RT.view("hermes:mission:abc:1")["name"] == "Hermes (mission) · in mission-run:5"   # under its parent's name


def test_a_hermes_run_without_a_ref_joins_the_live_step_of_its_agent(RT):
    t = time.time() - 100
    RT.ingest([ev("mission-run:7", "run", t, agent="runner"), ev("task:3", "run", t, agent="conductor"),
               ev("task:3:step:1", "run", t + 1, agent="scout", ref="task:3"), ev("task:3:step:2", "run", t + 2, agent="mission", ref="task:3")])
    RT.ingest([ev("hermes:scout:a:1", "run", t + 3, agent="scout"), ev("hermes:mission:b:1", "run", t + 4, agent="mission")])
    refs = {r["run"]: r["ref"] for r in RT.db().execute("select run, ref from runs")}
    assert refs["hermes:scout:a:1"] == "task:3:step:1" and refs["hermes:mission:b:1"] == "task:3:step:2"
    RT.ingest([ev("task:3:step:2", "end", t + 5, agent="mission", status="done"), ev("hermes:mission:c:1", "run", t + 6, agent="mission")])
    assert RT.db().execute("select ref from runs where run='hermes:mission:c:1'").fetchone()["ref"] == "mission-run:7"   # no live step: as before


def test_two_scout_steps_started_together_each_get_their_own_run_by_its_prompt_s_head(RT):
    """FND-114: the guess files a run under the live step most recently active; the step's run named at the head of its
    prompt (the run's title) is exact, and a head naming no known run falls back to the guess."""
    t = time.time() - 100
    RT.ingest([ev("task:3", "run", t, agent="conductor"), ev("task:4", "run", t, agent="conductor"),
               ev("task:3:step:1", "run", t + 1, agent="scout", ref="task:3"), ev("task:4:step:1", "run", t + 1, agent="scout", ref="task:4")])
    RT.ingest([ev("hermes:scout:a:1", "run", t + 2, agent="scout", run_title="[run: task:3:step:1]\nYou are scout in the owner's stack"),
               ev("hermes:scout:b:1", "run", t + 2, agent="scout", run_title="[run: task:4:step:1]\nYou are scout in the owner's stack"),
               ev("hermes:scout:c:1", "run", t + 3, agent="scout", run_title="[run: task:9:step:1]\nYou are scout")])
    refs = {r["run"]: r["ref"] for r in RT.db().execute("select run, ref from runs")}
    assert refs["hermes:scout:a:1"] == "task:3:step:1" and refs["hermes:scout:b:1"] == "task:4:step:1"
    assert refs["hermes:scout:c:1"] in ("task:3:step:1", "task:4:step:1")       # no such run: the live step, as before


def test_a_run_the_shutdown_cut_off_is_not_called_stuck(RT):
    """SWM-114: the doctor's run went quiet at 20:18, the PC was off, and the watchdog called it stuck at 08:38: a 12-hour bar and a false alert."""
    t = time.time()
    RT.ingest([ev("crew:doctor:1", "run", t - 43000, agent="crew:doctor"), ev("crew:doctor:1", "stage", t - 42999, agent="crew:doctor", title="Prompt")])
    assert RT.watchdog_once(now=t) == ["crew:doctor:1"]
    r = RT.runs(agent="crew:doctor")[0]
    assert r["end_state"] == "stopped" and r["ended"] <= t - 42990                       # its bar ends at its last activity
    assert not [p for p in RT.open_problems(hours=48) if p["run"] == "crew:doctor:1"]    # and no alert says it stopped answering
    assert "Cut off by a shutdown" in RT.view("crew:doctor:1")["events"][-1]["detail"]


def test_the_watchdog_closes_silent_runs_honestly(RT):
    t = time.time() - 5000
    RT.ingest([ev("m", "run", t), ev("phone:1", "run", t, agent="ai-phone", data={"manifest": {"agent": "ai-phone", "idle_end": True}})])
    assert sorted(RT.watchdog_once(now=t + RT.STALL_S + 1)) == ["m", "phone:1"]
    st = {r["run"]: (r["end_state"], r["ended"]) for r in RT.runs()}
    assert st["m"][0] == "stalled" and st["phone:1"] == ("done", t + 1)     # a quiet phone session simply ended
    assert {p["run"]: [i["kind"] for i in p["issues"]] for p in RT.open_problems(hours=48)} == {"m": ["stalled"]}
    RT.ingest([ev("m", "say", t + RT.STALL_S + 50, detail="scan done"), ev("m", "end", t + RT.STALL_S + 60, status="done")])
    assert RT.runs(agent="mission")[0]["end_state"] == "done"                 # the source's own end replaces the watchdog's guess
    assert RT.ingest([ev("m", "end", t + RT.STALL_S + 70, status="failed")]) == 0


def test_a_declared_wait_is_not_a_stall(RT):
    t = time.time() - 5000
    RT.ingest([ev("w", "run", t), ev("w", "wait", t + 1, title="the Windows disk scan", detail="parked")])
    assert RT.watchdog_once(now=t + RT.STALL_S + 60) == []
    assert RT.watchdog_once(now=t + RT.WAIT_S + 60) == ["w"]


def test_drift_against_the_previous_run_of_the_same_agent(RT):
    t = time.time()
    RT.ingest([ev("a", "run", t - 10, data={"manifest": {"model": "gpt-5.5", "tool_count": 30, "mcp": ["mail", "web"]}}), ev("a", "end", t - 9)])
    RT.ingest([ev("b", "run", t, data={"manifest": {"model": "gpt-5.4", "tool_count": 20, "mcp": ["web"]}})])
    d = RT.view("b")["drift"]
    assert d == ["model gpt-5.5 → gpt-5.4", "10 fewer tools than last time (20)", "tool servers not connected: mail"]


def test_touches_refusals_connections_and_retention(RT):
    t = time.time() - 91 * 86400
    RT.ingest([ev("p", "run", t), ev("p", "call", t + 1, title="mail_search", detail="{}"),
               ev("p", "result", t + 2, title="phone_tap", detail="Refused: banking apps are blocked"), ev("p", "end", t + 3)])
    v = RT.view("p")
    assert v["touches"]["connections"] == [{"tool": "mail_search", "calls": 1}] and v["touches"]["refused"][0]["tool"] == "phone_tap"
    assert RT.prune() == 4 and RT.view("p")["events"] == [] and RT.runs()[0]["summary"]["tool_calls"] == 1


# ---------- the Hermes plugin ----------
def load_plugin(monkeypatch, tmp_path, ingest=""):
    monkeypatch.setenv("RUNTIME_INGEST", ingest)
    monkeypatch.setenv("RUNTIME_SPOOL", str(tmp_path / "spool"))
    monkeypatch.setenv("HERMES_HOME", "/opt/data/profiles/scout")
    monkeypatch.setenv("AISTACK_REF", "mission-run:9")
    spec = importlib.util.spec_from_file_location("aistack_runtime", ROOT / "config/hermes/plugins/aistack-runtime/__init__.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_plugin_records_a_turn_and_spools_without_mission_control(monkeypatch, tmp_path):
    P = load_plugin(monkeypatch, tmp_path)
    hooks = {}
    P.register(type("Ctx", (), {"register_hook": lambda self, n, f: hooks.__setitem__(n, f)})())
    assert hooks["pre_tool_call"](tool_name="web_search", args={"q": "x"}, session_id="s1") is None   # never vetoes
    hooks["post_api_request"](session_id="s1", model="gpt", usage={"prompt_tokens": 100, "cache_read_tokens": 60, "output_tokens": 5},
                              api_duration=1.5, assistant_message=type("M", (), {"content": "Done.", "reasoning_content": None})())
    hooks["post_tool_call"](tool_name="web_search", result={"x": 1}, session_id="s1", status="error", error_message="boom")
    hooks["on_session_end"](session_id="s1", completed=False, turn_exit_reason="usage_limit_reached")
    hooks["on_session_end"](session_id="never-started")
    deadline = time.time() + 5
    while time.time() < deadline and not list((tmp_path / "spool").glob("*.jsonl")):
        time.sleep(0.05)
    time.sleep(0.8)
    lines = [json.loads(x) for f in (tmp_path / "spool").glob("hermes-scout-*.jsonl") for x in f.read_text().splitlines()]
    kinds = [e["kind"] for e in lines]
    assert kinds == ["run", "call", "llm", "say", "error", "end"]
    assert lines[0]["ref"] == "mission-run:9" and lines[0]["agent"] == "scout" and lines[2]["tokens"] == {"in": 100, "out": 5, "cached": 60, "reasoning": 0}
    assert lines[-1]["status"] == "limit" and len({e["run"] for e in lines}) == 1


def test_chat_sessions_are_tied_to_their_chat(monkeypatch, tmp_path):
    P = load_plugin(monkeypatch, tmp_path)
    monkeypatch.delenv("AISTACK_REF")
    assert P._ref("mc-abc123def-2") == "chat:abc123def" and P._ref("cli-session") is None


# ---------- the Claude Code hook ----------
def test_the_claude_hook_turns_hooks_and_transcript_into_events(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("runtime_hook", ROOT / "config/hermes/claude-hooks/runtime_hook.py")
    H = importlib.util.module_from_spec(spec)
    monkeypatch.setenv("RUNTIME_SPOOL", str(tmp_path / "rt"))
    monkeypatch.setenv("AISTACK_AGENT", "claude-task")
    monkeypatch.setenv("AISTACK_REF", "claude-task:3")
    monkeypatch.setenv("AISTACK_BOX", json.dumps({"where": "/work/.claude-tasks/3"}))
    spec.loader.exec_module(H)
    tr = tmp_path / "t.jsonl"
    tr.write_text(json.dumps({"type": "assistant", "timestamp": "2026-10-28T10:00:00Z", "message": {"model": "claude-opus-5-5", "id": "m1",
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 7},
        "content": [{"type": "thinking", "thinking": "hmm"}, {"type": "text", "text": "Reading it."}]}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"id": "m1", "usage": {"input_tokens": 10}, "content": [{"type": "tool_use"}]}}) + "\n"
        + '{"type": "user"')
    monkeypatch.setattr(H.time, "sleep", lambda s: None)
    for hook in ({"hook_event_name": "SessionStart"}, {"hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "a.py"}},
                 {"hook_event_name": "PostToolUse", "tool_name": "Read", "tool_response": {"is_error": True}}, {"hook_event_name": "Stop"}):
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "sess-1", "transcript_path": str(tr), **hook})))
        H.main()
    out = [json.loads(x) for x in (tmp_path / "rt" / "claude-sess-1.jsonl").read_text().splitlines()]
    assert [e["kind"] for e in out] == ["llm", "think", "say", "run", "call", "error", "end"]      # the transcript is read once
    assert out[0]["tokens"] == {"in": 100, "out": 7, "cached": 90, "reasoning": 0} and out[3]["data"]["box"]["where"] == "/work/.claude-tasks/3"
    assert {e["run"] for e in out} == {"claude:claude-task:sess-1"} and out[3]["ref"] == "claude-task:3"


# ---------- the runner ----------
def test_the_forwarder_sends_spools_and_keeps_what_failed(monkeypatch, tmp_path):

    spec = importlib.util.spec_from_file_location("ops_runtime", ROOT / "ops/runtime.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    d = tmp_path / "spool"
    d.mkdir()
    (d / "a.jsonl").write_text("".join(json.dumps({"run": "r", "kind": "say", "n": i}) + "\n" for i in range(250)) + "{torn")
    sent, up = [], [True, False]
    monkeypatch.setattr(R, "SPOOLS", [d])
    monkeypatch.setattr(R, "_post", lambda b: (sent.extend(b) or True) if up.pop(0) else False)
    assert R.forward_once() == 200
    left = [json.loads(x) for f in d.glob("*.sending") for x in f.read_text().splitlines()]
    assert [e["n"] for e in left] == list(range(200, 250))
    monkeypatch.setattr(R, "_post", lambda b: sent.extend(b) or True)
    assert R.forward_once() == 50 and not list(d.iterdir()) and len(sent) == 250
    assert [R.mission_state(*a) for a in (("ok",), ("waiting",), ("error", "interrupted by restart"), ("error", "boom"))] == ["done", "limit", "stopped", "failed"]
    monkeypatch.setattr(R, "SPOOLS", [tmp_path / "wb" / ".runtime"])
    R.prepare()
    assert (tmp_path / "wb" / ".runtime").stat().st_mode & 0o777 == 0o777
    R.set_ref("build:7")
    assert R.env_args() == ["-e", "AISTACK_REF=build:7"]


def test_pipeline_steps_reads_writes_and_model_calls_go_to_the_current_run(monkeypatch):
    spec = importlib.util.spec_from_file_location("ops_runtime2", ROOT / "ops/runtime.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    got = []
    monkeypatch.setattr(R, "_post", lambda b: got.extend(b) or True)
    R.stage("ignored outside a run")
    R.set_ref("mission-run:18", "mission:pc-disk-cleanup")
    R.stage("pc · scan requested", "waiting for the Windows disk scan")
    R.touched("missions/x/log/a.md", changed=True)
    R.model_call("gpt-sub-fast", 900, {"prompt_tokens": 500, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 400}})
    assert [(e["kind"], e["title"]) for e in got] == [("stage", "pc · scan requested"), ("call", "write_file"), ("result", "write_file"), ("llm", "gpt-sub-fast")]
    assert {e["run"] for e in got} == {"mission-run:18"} and got[0]["agent"] == "mission:pc-disk-cleanup"
    assert got[3]["tokens"] == {"in": 500, "out": 40, "cached": 400, "reasoning": 0} and "data" not in got[3]


def test_hermes_runs_without_a_ref_are_tied_to_the_live_mission(RT):
    t = time.time()
    RT.ingest([ev("mission-run:19", "run", t, agent="mission:ram")])
    RT.ingest([ev("hermes:mission:a:1", "run", t + 1, agent="mission")])
    RT.ingest([ev("hermes:scout:b:1", "run", t + 2, agent="scout"), ev("hermes:scout:b:1", "say", t + 3, agent="scout", detail="found it")])
    v = RT.view("mission-run:19")
    assert [c["run"] for c in v["children"]] == ["hermes:mission:a:1"]
    assert any(e["run"] == "hermes:scout:b:1" and e["kind"] == "say" for e in v["events"])    # the scout's work shows in the mission
    assert RT.view("hermes:scout:b:1")["ref"] == "hermes:mission:a:1"


def test_requests_that_come_together_each_read_their_own_runs(RT):
    """FND-88: one connection shared by the server's request threads mixed up the reads of requests that came together
    (an agent's page asks for its runs and its room at once): sqlite's "bad parameter or other API misuse", or a run
    read back as None. Each thread now reads on its own connection."""
    import threading
    t0 = time.time() - 3000
    for i in range(40):
        RT.ingest([ev(f"r{i}", "run", t0 + i * 60, run_title=f"Run {i}", ref=f"r{i - 1}" if i else None),
                   ev(f"r{i}", "llm", t0 + i * 60 + 1, title="gpt", tokens={"in": 10, "out": 2}),
                   ev(f"r{i}", "end", t0 + i * 60 + 5, status="done")])
    errors = []

    def read():
        try:
            for _ in range(15):
                assert len([r for r in RT.timeline(hours=2)["runs"] if r["run"].startswith("r")]) == 40
                assert len([r for r in RT.runs(limit=100) if r["run"].startswith("r")]) == 40
        except Exception as e:                        # every failure of every thread is kept and shown
            errors.append(f"{type(e).__name__}: {e}")

    def write():
        try:
            for j in range(30):
                RT.ingest([ev("w", "llm", time.time() - 5 + j / 100, title="gpt", tokens={"in": 1, "out": 1})])
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
    threads = [threading.Thread(target=read) for _ in range(8)] + [threading.Thread(target=write)]
    for x in threads:
        x.start()
    for x in threads:
        x.join()
    assert errors == []

