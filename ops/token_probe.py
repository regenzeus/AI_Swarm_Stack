#!/usr/bin/env python3
"""Measure the ChatGPT prompt cache and thinking summaries through LiteLLM (docs/TOKENS.md). About 8 small calls.

  A) 3 calls of one growing conversation with a ~3k-token system prompt and NO session id: the gateway's
     cache_affinity hook gives them one id, so calls 2 and 3 should report cached tokens.
  B) the same with a fresh random session id per call (how it was before the hook): expect little or no cache.
  C) one call asking for a reasoning summary: does any thinking text come back (reasoning_content)?
Writes /srv/ai/state/token-probe.json. Usage (needs the keys): sops exec-env secrets/agent-keys.enc.yaml 'python3 ops/token_probe.py'
"""
import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

URL = "http://127.0.0.1:4000/v1/chat/completions"
KEY = os.environ.get("VK_GUARD", "")
SYSTEM = ("You are a careful assistant for a home AI stack. " + " ".join(
    f"Rule {i}: answer briefly, cite the step you used, never invent numbers, prefer the vault over the web, and say when "
    f"something is unknown." for i in range(1, 120)))        # ~3k tokens: above the backend's caching threshold


def call(messages, session=None, extra=None):
    body = {"model": "gpt-sub-fast", "messages": messages, "max_tokens": 40, **(extra or {})}
    if session:
        body["litellm_session_id"] = session
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(errors="replace")[:300]}  # cap: untrusted
    u = d.get("usage") or {}
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    return {"in": u.get("prompt_tokens"), "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens"), "seconds": round(time.time() - t, 1),
            "thinking": (msg.get("reasoning_content") or "")[:300], "answer": (msg.get("content") or "")[:80]}  # cap: preview


def conversation(session_of):
    msgs, out = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Name one prime number."}], []
    for i in range(3):
        r = call(msgs, session_of(i))
        out.append(r)
        msgs += [{"role": "assistant", "content": r.get("answer") or "7"}, {"role": "user", "content": f"And another one ({i})?"}]
        time.sleep(2)
    return out


res = {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
       "A_stable_session_by_hook": conversation(lambda i: None),
       "B_new_session_each_call": conversation(lambda i: str(uuid.uuid4())),
       "C_thinking": call([{"role": "user", "content": "Is 391 prime? Think, then answer yes or no."}], None,
                          {"reasoning_effort": "low", "reasoning": {"summary": "auto"}, "max_tokens": 400})}
Path("/srv/ai/state").mkdir(parents=True, exist_ok=True)
Path("/srv/ai/state/token-probe.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res, indent=1))
