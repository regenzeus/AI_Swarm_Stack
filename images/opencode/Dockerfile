# OpenCode 1.19.x server + web UI. Works in /code (WSL ext4). Talks to models only via LiteLLM (vk-code).
# No internet at runtime: provider packages are preloaded at build time; git push and deploys are
# explicit host-side commands, never the agent's.
# Also carries Understand Anything (skills /understand, /understand-chat, ... + the read-only graph viewer),
# built here at a pinned commit so nothing is fetched at runtime.

FROM node:22-bookworm-slim AS ua
ARG UA_REF=e24fcf6
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git ca-certificates python3 make g++ \
 && npm install -g pnpm@10.18.3
RUN git clone -q https://github.com/Lum1104/Understand-Anything /opt/ua && git -C /opt/ua checkout -q ${UA_REF} \
 && rm -rf /opt/ua/.git /opt/ua/homepage
WORKDIR /opt/ua/understand-anything-plugin
RUN pnpm install --frozen-lockfile && pnpm --filter @understand-anything/core build \
 && pnpm --filter understand-anything-viewer build

FROM node:22-bookworm-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git ca-certificates python3 python3-pip python3-venv python-is-python3 ripgrep \
 && rm -rf /var/lib/apt/lists/* && npm install -g opencode-ai@1.19.4 && npm cache clean --force
COPY opencode.json /root/.config/opencode/opencode.json
# Preload the OpenAI-compatible provider package OpenCode would otherwise fetch on first use.
RUN LITELLM_API_KEY=build opencode models litellm >/dev/null 2>&1 || true; ls /root/.cache/opencode 2>/dev/null || true
COPY --from=ua /opt/ua/understand-anything-plugin /opt/ua
ENV CLAUDE_PLUGIN_ROOT=/opt/ua
RUN mkdir -p /root/.config/opencode/skills && for s in /opt/ua/skills/*/; do ln -s "$s" /root/.config/opencode/skills/; done \
 && ln -s /opt/ua /root/.understand-anything-plugin && mkdir -p /root/.agents && ln -s /opt/ua/skills /root/.agents/skills \
 && chmod +x /opt/ua/packages/viewer/bin/viewer.mjs && ln -s /opt/ua/packages/viewer/bin/viewer.mjs /usr/local/bin/understand-anything-viewer
# The viewer's own look, for the frame Mission Control shows it in (viewer.css: no minimap)
COPY viewer.css /opt/ua/packages/viewer/dist/aistack.css
RUN sed -i 's#</head>#<link rel="stylesheet" href="/aistack.css"></head>#' /opt/ua/packages/viewer/dist/index.html \
 && grep -q aistack.css /opt/ua/packages/viewer/dist/index.html
WORKDIR /code
