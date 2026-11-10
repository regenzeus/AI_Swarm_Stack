# The builder sandbox: Hermes (profile config: config/hermes/configure-builder.sh) with a shell and file tools that
# work only inside this container. It sees /work (the workbench clones, /srv/ai/workbench) and nothing else: no
# vault, no secrets, no SSH keys, no Docker. Networks: LiteLLM (its own key vk-builder) and pkgproxy (npm + PyPI).
# It commits on a branch; the host runner pushes, Forgejo CI checks, the owner approves in Mission Control, then deploy.
ARG HERMES_IMAGE=aistack/hermes:0.22.5-web3
FROM ${HERMES_IMAGE}
USER root
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends shellcheck jq ripgrep \
 && rm -rf /var/lib/apt/lists/* \
 && python3 -m venv /opt/tools && /opt/tools/bin/pip install --no-cache-dir ruff==0.14.2 pytest==8.3.4 pytest-xdist==3.6.1 pyyaml==6.0.3 httpx==0.28.1 mcp==2.3.0 \
 && python3 -m venv /opt/semgrep && /opt/semgrep/bin/pip install --no-cache-dir semgrep==1.181.1 \
 && ln -s /opt/tools/bin/ruff /usr/local/bin/ruff && ln -s /opt/tools/bin/pytest /usr/local/bin/pytest \
 && ln -s /opt/semgrep/bin/semgrep /usr/local/bin/semgrep \
 && git config --system --add safe.directory '*' \
 && git config --system user.name "AI Stack Builder" && git config --system user.email "builder@ai-stack.local"
# Second engine: Claude Code (pinned), signed in per build with the owner's Claude subscription token (never stored here).
# npm 12 blocks install scripts unless allowed; Claude Code's fetches its native binary. Its bin goes onto the PATH.
RUN npm install -g --no-fund --no-audit --allow-scripts=@anthropic-ai/claude-code @anthropic-ai/claude-code@2.1.305 \
 && ln -sf "$(npm prefix -g)/bin/claude" /usr/local/bin/claude && claude --version
# ESLint for ops/app_lint.py (APP-24: the app's scripts checked for undefined names)
RUN mkdir -p /opt/eslint && cd /opt/eslint && npm init -y >/dev/null && npm install --no-fund --no-audit eslint@9.39.1 globals@16.5.0 \
 && /opt/eslint/node_modules/.bin/eslint --version
# Serena (pinned): code tools that understand the code through language servers (find a symbol, its references, rename,
# replace a function body) for both engines, as an MCP server. The language servers are fetched here, while the build
# has internet; the sandbox only reaches the package registries. They live in Serena's own home, not the data volume.
# The Bash server's own ShellCheck download does not unpack here, so it gets the image's ShellCheck (path = Serena's pin).
COPY serena-mcp /usr/local/bin/serena-mcp
RUN python3 -m venv /opt/serena && /opt/serena/bin/pip install --no-cache-dir serena-agent==2.0.0 uv==0.13.1 \
 && mkdir -p /opt/serena-home && cd /tmp \
 && PATH=/opt/serena/bin:$PATH HOME=/opt/serena-home serena download-ls-dependencies python typescript bash \
 && sc=/opt/serena-home/.serena/language_servers/static/BashLanguageServer/bash-lsp/shellcheck/shellcheck-v0.10.0 \
 && mkdir -p $sc && ln -sf /usr/bin/shellcheck $sc/shellcheck \
 && chmod 755 /usr/local/bin/serena-mcp && chown -R hermes:hermes /opt/serena-home
# Login shells (Claude Code's Bash tool) reset PATH from /etc/profile and lost the check tools (ruff, pytest, the
# Python with pyyaml): put them first there too.
RUN printf 'export PATH=/opt/tools/bin:/opt/hermes/bin:$PATH\n' > /etc/profile.d/10-builder-tools.sh
# CHG-13: a change request builds and tests a repository in this sandbox, so it carries each repository's toolchain: Go, Rust,
# Java with Maven, pnpm. CHG-14: the Prober drives web pages with Playwright on the distribution's Chromium (no browser download).
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends golang-go cargo default-jdk-headless maven chromium \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g --no-fund --no-audit pnpm@10.18.0 && ln -sf "$(npm prefix -g)/bin/pnpm" /usr/local/bin/pnpm \
 && /opt/tools/bin/pip install --no-cache-dir playwright==1.55.0 \
 && go version && cargo --version && mvn --version | head -1 && pnpm --version && chromium --version
