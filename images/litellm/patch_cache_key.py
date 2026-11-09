"""Build-time patch: optionally pass the session id as prompt_cache_key to the ChatGPT backend, as Codex does.

LiteLLM's ChatGPT Responses transform drops every key but a fixed list, so prompt_cache_key never reaches the backend.
Off unless CHATGPT_PROMPT_CACHE_KEY=1 (compose env): if the backend refused the key, every call would fail, so it is
switched on only after a measured probe (docs/TOKENS.md). Fails the build if the patched code changed upstream.
"""
import pathlib
import sys

import litellm

f = pathlib.Path(litellm.__file__).parent / "llms/chatgpt/responses/transformation.py"
s = f.read_text()
edits = [
    ('        request["store"] = False\n',
     '        request["store"] = False\n'
     '        if os.getenv("CHATGPT_PROMPT_CACHE_KEY") == "1":   # aistack patch_cache_key.py\n'
     '            _sid = get_chatgpt_session_id(litellm_params)\n'
     '            if _sid:\n'
     '                request["prompt_cache_key"] = _sid\n'),
    ('            "truncation",\n        }', '            "truncation",\n            "prompt_cache_key",\n        }'),
    ('    ensure_chatgpt_session_id,\n', '    ensure_chatgpt_session_id,\n    get_chatgpt_session_id,\n'),
]
for old, new in edits:
    if s.count(old) != 1:
        sys.exit(f"patch_cache_key: upstream code changed, cannot patch: {old.strip()}")
    s = s.replace(old, new)
if "\nimport os\n" not in s:
    s = "import os\n" + s
f.write_text(s)
print("patched", f)
