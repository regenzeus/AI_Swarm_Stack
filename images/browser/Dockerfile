# The scout's browser: Playwright MCP (headless Chromium, pinned) behind guard.py, which only lets it look (open,
# look, click, search, back; no logins, carts, checkout or payment). Isolated like images/fetch: on "webonly" it
# reaches the internet and LiteLLM only, and entrypoint.sh rejects private/LAN/Tailscale ranges. Unprivileged.
FROM node:22.23.4-bookworm-slim
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends iptables util-linux python3 python3-venv \
 && npm install -g --no-fund --no-audit @playwright/mcp@0.0.83 \
 && node "$(npm root -g)/@playwright/mcp/node_modules/playwright/cli.js" install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/* /root/.npm \
 && python3 -m venv /opt/guard && /opt/guard/bin/pip install --no-cache-dir mcp==2.3.0 \
 && useradd -r -u 10008 -m browser && chmod -R a+rX /ms-playwright
COPY entrypoint.sh /entrypoint.sh
COPY guard.py /app/guard.py
EXPOSE 8000
ENTRYPOINT ["sh", "/entrypoint.sh"]
