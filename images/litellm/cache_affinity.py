"""Cache affinity for the ChatGPT subscription (loaded via litellm_settings.callbacks in config/litellm/config.yaml).

LiteLLM gives every ChatGPT request that arrives without a session id a fresh one (the call id; see
llms/chatgpt/common_utils.py get_chatgpt_session_id), and the ChatGPT backend routes its prompt cache by that id. So
the calls of one agent run landed in different caches: in the Gamma Metals run only 35 % of the input was cached,
although every call starts with the same 7-10k tokens. A request without a session id now gets a stable one: a hash
of the key, the system prompt and the first user message, which is the same for every call of one conversation and
different for the next one. Clients that send their own session id keep it.
"""
import hashlib
import json

from litellm.integrations.custom_logger import CustomLogger


def conversation_key(alias, data):
    msgs = data.get("messages")
    if isinstance(msgs, list) and msgs:
        head = [m for m in msgs if isinstance(m, dict)][:2]        # system + first user turn: fixed for the conversation  # cap: parse
        parts = [json.dumps(m.get("content"), sort_keys=True, default=str) for m in head]
    else:
        inp = data.get("input")
        first = inp[0] if isinstance(inp, list) and inp else inp
        parts = [str(data.get("instructions") or ""), json.dumps(first, sort_keys=True, default=str)]
    return "aistack-" + hashlib.sha256("\x00".join([alias or "", *parts]).encode()).hexdigest()[:32]  # cap: id (a hash's first 32 hex digits)


class CacheAffinity(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if data.get("litellm_session_id") or meta.get("session_id") or not (data.get("messages") or data.get("input")):
            return data
        data["litellm_session_id"] = conversation_key(getattr(user_api_key_dict, "key_alias", "") or "", data)
        return data


proxy_handler_instance = CacheAffinity()
