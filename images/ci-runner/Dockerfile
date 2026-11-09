# Forgejo Actions runner for the repos on the NAS Forgejo. Jobs run directly in this container ("host" label):
# no Docker socket, no access to the stack, its secrets or the NAS; only lint and test tools. Internet only
# to fetch actions (actions/checkout) and packages.
FROM code.forgejo.org/forgejo/runner:13.2.0 AS runner
FROM python:3.12-slim
ARG COMPOSE_VERSION=2.40.3
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends git ca-certificates curl nodejs shellcheck \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir ruff==0.14.2 pyyaml==6.0.3 semgrep==1.181.1 \
 && mkdir -p /usr/local/lib/docker/cli-plugins \
 && curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
      "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
 && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
 && curl -fsSL -o /tmp/docker.tgz https://download.docker.com/linux/static/stable/x86_64/docker-28.5.1.tgz \
 && tar -xzf /tmp/docker.tgz -C /tmp && mv /tmp/docker/docker /usr/local/bin/ && rm -rf /tmp/docker* \
 && useradd -m -u 1000 runner
# ESLint for ops/app_lint.py (APP-24: the app's scripts checked for undefined names)
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends npm && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /opt/eslint && cd /opt/eslint && npm init -y >/dev/null && npm install --no-fund --no-audit eslint@9.39.1 globals@16.5.0 \
 && /opt/eslint/node_modules/.bin/eslint --version && npm cache clean --force
COPY --from=runner /bin/forgejo-runner /usr/local/bin/forgejo-runner
COPY config.yaml /etc/runner/config.yaml
USER runner
WORKDIR /data
CMD ["sh", "-c", "[ -f .runner ] || { echo not registered; exit 1; }; exec forgejo-runner daemon --config /etc/runner/config.yaml"]
