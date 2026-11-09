"""Token budget (docs/TOKENS.md): ChatGPT cache affinity in the gateway, lean agent profiles, honest build counts."""
import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_affinity(monkeypatch):
    fake = types.ModuleType("litellm.integrations.custom_logger")
    fake.CustomLogger = object
    for name in ("litellm", "litellm.integrations"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "litellm.integrations.custom_logger", fake)
    spec = importlib.util.spec_from_file_location("cache_affinity", ROOT / "images/litellm/cache_affinity.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_one_conversation_keeps_one_session_id(monkeypatch):
    C = load_affinity(monkeypatch)
    hook = lambda alias, data: asyncio.run(C.proxy_handler_instance.async_pre_call_hook(types.SimpleNamespace(key_alias=alias), None, data, "completion"))
    head = [{"role": "system", "content": "You are the scout."}, {"role": "user", "content": "RAM prices?"}]
    a = hook("vk-scout", {"messages": list(head)})["litellm_session_id"]
    b = hook("vk-scout", {"messages": head + [{"role": "assistant", "content": "…"}, {"role": "tool", "content": "page"}]})["litellm_session_id"]
    assert a == b and a.startswith("aistack-")                                  # every call of the run: one cache
    assert hook("vk-scout", {"messages": [head[0], {"role": "user", "content": "GPU prices?"}]})["litellm_session_id"] != a
    assert hook("vk-mission", {"messages": list(head)})["litellm_session_id"] != a      # keys never share
    assert hook("vk-scout", {"messages": head, "litellm_session_id": "own"})["litellm_session_id"] == "own"
    assert hook("vk-scout", {"input": [{"role": "user", "content": "x"}], "instructions": "I"})["litellm_session_id"].startswith("aistack-")


def test_gateway_loads_it_and_the_cache_key_stays_off_by_default():
    cfg = (ROOT / "config/litellm/config.yaml").read_text()
    assert '"cache_affinity.proxy_handler_instance"' in cfg
    docker = (ROOT / "images/litellm/Dockerfile").read_text()
    assert "COPY cache_affinity.py /app/cache_affinity.py" in docker and "patch_cache_key.py" in docker
    assert "aistack/litellm:1.105.4-p2" in (ROOT / "compose/core.yaml").read_text()
    assert 'os.getenv("CHATGPT_PROMPT_CACHE_KEY") == "1"' in (ROOT / "images/litellm/patch_cache_key.py").read_text()


def test_agent_profiles_carry_only_what_they_use():
    scout = (ROOT / "config/hermes/configure-scout.sh").read_text()
    mission = (ROOT / "config/hermes/configure-mission.sh").read_text()
    builder = (ROOT / "config/hermes/configure-builder.sh").read_text()
    assert "c platform_toolsets.$pf '[\"search\"]'" in scout and "webfetch.tools.prompts false" in scout
    disabled = json.loads(mission.split("c agent.disabled_toolsets '")[1].split("'")[0])
    assert {"skills", "clarify", "session_search"} <= set(disabled) and "vault.tools.resources false" in mission
    assert '"skills"' not in builder.split("c platform_toolsets.cli '")[1].split("'")[0]


def test_claude_builds_count_cache_reads_like_chatgpt_builds(runner):
    import builds as B
    log = json.dumps({"type": "result", "result": "done", "num_turns": 8,
                      "usage": {"input_tokens": 14, "cache_read_input_tokens": 154164, "cache_creation_input_tokens": 14753, "output_tokens": 1981}})
    r = B.claude_result(log)
    assert r["tokens"] == 14 + 154164 + 14753 + 1981 and r["cached"] == 154164
