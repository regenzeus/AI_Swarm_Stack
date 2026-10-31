"""Health signals the owner can trust (OBS-10, OBS-20; review 2026-10-30, FND-62 to FND-65): a call to a tool whose
arguments are all optional is no problem, a cut-off result the agent read on is no partial read, a kind of issue clears
with the next run that does not have it, and a failing job's alert says why."""
import ast
import json
from pathlib import Path

import observe as O

ROOT = Path(__file__).resolve().parent.parent
HERMES_OWN = {"skills_list", "todo_list", "initial_instructions"}        # Hermes' built-in tools that take no arguments


def no_arg_tools():
    """Every MCP tool in the repo whose parameters all have defaults, by the name it is offered under."""
    out = set()
    for f in sorted((ROOT / "images").rglob("*.py")) + sorted((ROOT / "ops").rglob("*.py")):
        for n in ast.walk(ast.parse(f.read_text())):
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            deco = [d for d in n.decorator_list if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool"]
            if not deco:
                continue
            a = n.args
            params = [x for x in a.args + a.kwonlyargs if x.arg not in ("self", "ctx") and "Context" not in ast.unparse(x.annotation or ast.Constant(""))]
            if len(params) <= len(a.defaults) + sum(d is not None for d in a.kw_defaults):
                named = [k.value.value for d in deco for k in d.keywords if k.arg == "name" and isinstance(k.value, ast.Constant)]
                out.add(named[0] if named else n.name)
    return out


def test_the_no_argument_list_matches_every_tool_that_takes_none():
    assert O.NO_ARGS == no_arg_tools() | HERMES_OWN


def call(tool, args, t=0):
    return {"kind": "call", "title": tool, "detail": json.dumps(args), "t": t}


def test_a_call_with_no_arguments_is_a_problem_only_when_the_tool_needs_some():
    assert not O.empty_call(call("mcp__vault__swarm_swarm_context", {}))
    assert O.empty_call(call("mcp__webfetch__fetch", {})) and O.empty_call({"kind": "call", "title": "skill_view", "detail": ""})
    kinds = [p["kind"] for p in O.problems([call("mcp__vault__swarm_swarm_context", {}, 1), {"kind": "say", "detail": "done", "t": 2}])]
    assert "empty-args" not in kinds


def test_a_cut_off_result_the_agent_read_on_is_no_partial_read():
    cut = {"kind": "result", "title": "fetch", "detail": "page text… Content truncated. Call the fetch tool with a start_index of 5000"}
    url = "https://example.org/report"
    read_on = [call("fetch", {"url": url}, 1), cut, call("fetch", {"url": url, "start_index": 5000}, 3),
               {"kind": "result", "title": "fetch", "detail": "the rest"}, {"kind": "say", "detail": "The report says X."}]
    stopped = [call("fetch", {"url": url}, 1), cut, {"kind": "say", "detail": "The report says X."}]
    assert O.unfollowed_cuts(read_on) == [] and len(O.unfollowed_cuts(stopped)) == 1
    assert "partial-read" not in {p["kind"] for p in O.problems(read_on)}
    assert "cut off and not read on" in next(p["text"] for p in O.problems(stopped) if p["kind"] == "partial-read")


def test_a_failing_job_s_alert_says_why():
    runs = [{"start": 2, "state": "failed", "error": "failed: RuntimeError: AI phone: battery at 19 % and not plugged in: plug the AI phone in"},
            {"start": 1, "state": "failed"}]
    j = O.judge("Phone check", "crew", runs, now=3)
    assert {"kind": "failing", "text": "failed 2 times in a row: AI phone: battery at 19 % and not plugged in: plug the AI phone in"} in j["issues"]
    assert {"kind": "failing", "text": "failed 2 times in a row"} in O.judge("x", "crew", [{"start": 2, "state": "failed"}, {"start": 1, "state": "failed"}], now=3)["issues"]
    import phone_agents as PA
    faults, _, _ = PA.judge({"battery": "  level: 19\n  AC powered: false\n"}, {"connected": True})
    assert "battery at 19 % and not plugged in: plug the AI phone in" in faults
