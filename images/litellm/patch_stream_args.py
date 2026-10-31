"""Build-time patch for LiteLLM (images/litellm/Dockerfile): streamed tool calls must keep their arguments.

ChatGPT (the subscription models gpt-sub / gpt-sub-fast) often streams a tool call with NO argument deltas: the
arguments arrive only in `response.function_call_arguments.done` (and `response.output_item.done`). LiteLLM's
Responses -> chat-completions stream translation ignores both for per-stream callers ("already received via
deltas"), so every such call reached Hermes as `arguments: "{}"`. Measured: all parallel tool calls of the builder and
~15 % of the main profile's. Reproduce: tests/test_litellm_patch.py, and the probe in images/litellm/AGENTS.md.

The patch: per stream, remember which tool calls got argument deltas; a `function_call_arguments.done` for a call
without any is turned into one delta carrying the full arguments. Calls that did stream deltas are untouched.
Fails the image build if LiteLLM's code no longer matches (then re-check the bug on the new version, see UPGRADE.md).
Usage: python patch_stream_args.py [path to transformation.py]   (default: the installed litellm)
"""
import sys
from pathlib import Path

INIT_ANCHOR = "        self._tool_call_index_map: dict[int, int] = {}  # mutable-ok: per-stream accumulator state\n"
INIT_ADD = ("        self._tool_call_args_streamed: set[int] = set()  # ai-stack patch: tool calls that got argument deltas\n")
PARSE_ANCHOR = ('        verbose_logger.debug("Chat provider: transform_streaming_response called with chunk: %s", chunk)\n'
                "        self._remember_served_service_tier(chunk)\n")
PARSE_ADD = '''        chunk = self._arguments_only_in_done(chunk)  # ai-stack patch, see _arguments_only_in_done
'''
METHOD_ANCHOR = "    def _remember_served_service_tier(self, chunk: dict[str, object]) -> None:\n"
METHOD = '''    def _arguments_only_in_done(self, chunk: dict[str, object]) -> dict[str, object]:
        """ai-stack patch (images/litellm/patch_stream_args.py): ChatGPT may send a tool call's arguments only in
        response.function_call_arguments.done, with no delta events. Turn that into one arguments delta."""
        kind = getattr(chunk.get("type"), "value", chunk.get("type"))
        index = chunk.get("output_index", 0)
        if kind == "response.function_call_arguments.delta":
            self._tool_call_args_streamed.add(index)
        elif kind == "response.function_call_arguments.done" and index not in self._tool_call_args_streamed and chunk.get("arguments"):
            self._tool_call_args_streamed.add(index)
            return {**chunk, "type": "response.function_call_arguments.delta", "delta": chunk["arguments"]}
        return chunk

'''


def patch(text):
    for anchor in (INIT_ANCHOR, PARSE_ANCHOR, METHOD_ANCHOR):
        if text.count(anchor) != 1:
            raise SystemExit(f"LiteLLM changed: anchor not found exactly once:\n{anchor}")
    if "_arguments_only_in_done" in text:
        return text
    text = text.replace(INIT_ANCHOR, INIT_ANCHOR + INIT_ADD)
    text = text.replace(PARSE_ANCHOR, PARSE_ANCHOR + PARSE_ADD)
    return text.replace(METHOD_ANCHOR, METHOD + METHOD_ANCHOR)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        f = Path(sys.argv[1])
    else:
        import litellm.completion_extras.litellm_responses_transformation.transformation as t
        f = Path(t.__file__)
    f.write_text(patch(f.read_text()))
    compile(f.read_text(), str(f), "exec")
    print(f"patched {f}")
