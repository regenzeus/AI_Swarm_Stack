# LiteLLM (the model gateway) with one build-time patch: streamed tool calls keep their arguments when ChatGPT sends
# them only in the closing event (patch_stream_args.py explains the bug). The build fails if the patched code changed.
# Base pinned in versions.env (LITELLM_IMAGE); the default below must match it (tests/test_litellm_patch.py checks).
ARG LITELLM_IMAGE=ghcr.io/berriai/litellm:v1.105.4
FROM ${LITELLM_IMAGE}
COPY patch_stream_args.py /tmp/patch_stream_args.py
RUN /app/.venv/bin/python /tmp/patch_stream_args.py && rm /tmp/patch_stream_args.py
# Prompt-cache affinity: a stable ChatGPT session id per conversation (cache_affinity.py, a proxy callback loaded from
# the config's folder), and optionally prompt_cache_key (patch_cache_key.py, off unless CHATGPT_PROMPT_CACHE_KEY=1).
COPY patch_cache_key.py /tmp/patch_cache_key.py
RUN /app/.venv/bin/python /tmp/patch_cache_key.py && rm /tmp/patch_cache_key.py
COPY cache_affinity.py /app/cache_affinity.py
