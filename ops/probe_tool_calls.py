#!/usr/bin/env python3
"""Probe: do streamed parallel tool calls arrive with their arguments through LiteLLM? (images/litellm explains the bug)

One streamed request per subscription model with two tools, asking for both at once. Fails (exit 1) if a tool call
arrives without arguments. A few subscription calls, $0. Run: make probe-tools; ops/deploy.py runs it after a change to
LiteLLM (images/litellm, config/litellm, versions.env). Key: VK_BUILDER (the builder relies on parallel tool calls).
"""
import json, os, sys, urllib.request

URL = "http://127.0.0.1:4000/v1/chat/completions"
TOOLS = [{"type": "function", "function": {"name": "terminal", "description": "Run a shell command",
          "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
         {"type": "function", "function": {"name": "read_file", "description": "Read a file",
          "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
ASK = ("In one turn, call BOTH tools in parallel: terminal with command 'git status' and read_file with path "
       "'README.md'. Do not answer in text.")


def streamed_calls(model, key):
    body = json.dumps({"model": model, "stream": True, "tools": TOOLS, "parallel_tool_calls": True,
                       "messages": [{"role": "user", "content": ASK}]}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    calls = {}
    with urllib.request.urlopen(req, timeout=240) as r:
        for raw in r:
            line = raw.decode().strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            for choice in json.loads(line[6:]).get("choices") or []:
                for tc in choice.get("delta", {}).get("tool_calls") or []:
                    c = calls.setdefault(tc.get("index", 0), {"name": "", "arguments": ""})
                    c["name"] += (tc.get("function") or {}).get("name") or ""
                    c["arguments"] += (tc.get("function") or {}).get("arguments") or ""
    return [calls[i] for i in sorted(calls)]


def main():
    key = os.environ.get("VK_BUILDER") or sys.exit("VK_BUILDER missing: run via make probe-tools")
    bad = 0
    for model in ("gpt-sub-fast", "gpt-sub"):
        calls = streamed_calls(model, key)
        empty = [c["name"] for c in calls if not c["arguments"].strip("{} ")]
        print(f"{'FAIL' if empty or not calls else 'PASS'}  {model}: {len(calls)} streamed tool calls"
              + (f", without arguments: {', '.join(empty)}" if empty else "") + ("" if calls else " (no tool call at all)"))
        bad += bool(empty or not calls)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
