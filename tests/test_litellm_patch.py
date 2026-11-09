"""images/litellm/patch_stream_args.py: streamed tool calls keep their arguments when ChatGPT sends them only in the
closing event. The patch is applied to a copy of the real LiteLLM code shape and its logic is exercised directly."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
import importlib.util

spec = importlib.util.spec_from_file_location("patch_stream_args", ROOT / "images/litellm/patch_stream_args.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

# the shape of litellm/completion_extras/litellm_responses_transformation/transformation.py (v1.105.4), trimmed
SOURCE = '''class Iterator:
    def __init__(self):
        self._chat_completion_id: str | None = None
''' + P.INIT_ANCHOR + '''
    def chunk_parser(self, chunk: dict[str, object]) -> "ModelResponseStream":
''' + P.PARSE_ANCHOR + '''        return chunk

''' + P.METHOD_ANCHOR + '''        pass
'''


def patched():
    ns = {"verbose_logger": type("L", (), {"debug": staticmethod(lambda *a: None)})}
    exec(P.patch(SOURCE), ns)
    it = ns["Iterator"]()
    it._remember_served_service_tier = lambda c: None
    return it


def test_arguments_only_in_done_become_one_delta():
    it = patched()
    out = [it.chunk_parser(c) for c in (
        {"type": "response.output_item.added", "output_index": 0, "item": {"type": "function_call", "name": "terminal"}},
        {"type": "response.function_call_arguments.done", "output_index": 0, "arguments": '{"command": "git status"}'},
        {"type": "response.output_item.added", "output_index": 1, "item": {"type": "function_call", "name": "read_file"}},
        {"type": "response.function_call_arguments.done", "output_index": 1, "arguments": '{"path": "README.md"}'})]
    deltas = [(c["output_index"], c["delta"]) for c in out if c["type"] == "response.function_call_arguments.delta"]
    assert deltas == [(0, '{"command": "git status"}'), (1, '{"path": "README.md"}')]


def test_calls_that_streamed_deltas_are_left_alone():
    it = patched()
    it.chunk_parser({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"comm'})
    done = it.chunk_parser({"type": "response.function_call_arguments.done", "output_index": 0, "arguments": '{"command": "x"}'})
    assert done["type"] == "response.function_call_arguments.done"            # no second copy of the arguments


def test_patch_is_idempotent_and_refuses_changed_code():
    once = P.patch(SOURCE)
    assert P.patch(once) == once
    with pytest.raises(SystemExit, match="LiteLLM changed"):
        P.patch(SOURCE.replace("_tool_call_index_map", "_index_map"))


def test_dockerfile_base_matches_the_pin():
    pin = re.search(r"^LITELLM_IMAGE=(\S+)$", (ROOT / "versions.env").read_text(), re.M)[1]
    assert f"ARG LITELLM_IMAGE={pin}" in (ROOT / "images/litellm/Dockerfile").read_text()
