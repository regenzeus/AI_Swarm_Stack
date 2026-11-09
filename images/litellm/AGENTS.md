# images/litellm/: the model gateway, patched

The pinned LiteLLM image (`LITELLM_IMAGE` in `versions.env`) plus one build-time patch, `patch_stream_args.py`. ChatGPT
often streams a tool call with no argument deltas (the arguments come only in `function_call_arguments.done`), and
LiteLLM's stream translation dropped them, so Hermes got `{}`: every parallel tool call of the builder, about 15 % of the
main profile's. The patch turns those closing arguments into one delta. Configuration stays in `config/litellm/`.

Prompt-cache affinity: LiteLLM gave every ChatGPT request without a session id the call's own id, and the backend
routes its prompt cache by it, so the calls of one agent run missed each other's cache (35 % cached). `cache_affinity.py`
(a proxy callback, `litellm_settings.callbacks`) sets a stable id per conversation: hash of key, system prompt and first
user message. `patch_cache_key.py` can also send it as `prompt_cache_key` (off; `CHATGPT_PROMPT_CACHE_KEY=1` after a
probe shows the backend accepts it). Numbers: `docs/TOKENS.md`.

## Rules

- The patch must apply exactly, or the build fails. On a LiteLLM upgrade, if it fails: run the probe below on the new
  version first. If the bug is fixed upstream, delete the patch; otherwise update its anchors (`UPGRADE.md`).
- Keep `ARG LITELLM_IMAGE=` in the Dockerfile equal to `versions.env`. `tests/test_litellm_patch.py` checks it, and
  `ops/deploy.py` passes the pin as a build argument.
- Bump the tag in `compose/core.yaml` (`aistack/litellm:<version>-p<n>`) whenever the base or the patch changes.

## Probe (costs a few subscription calls)

Stream one request with two tools that asks for both at once. Both tool calls must arrive with their arguments
(the reproduction script is `ops/probe_tool_calls.py`, run by `make probe-tools`).
