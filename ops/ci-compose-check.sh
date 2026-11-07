#!/usr/bin/env bash
# CI: are the compose files valid? Required secrets (${VAR:?...}) get dummy values, so no real secret is needed.
set -euo pipefail
cd "$(dirname "$0")/.."
for v in $(grep -ho '\${[A-Z_]*:?' compose/*.yaml | tr -d '${:?' | sort -u); do
  grep -q "^$v=" config/deployment.env || export "$v=ci-dummy"       # the deployment's own values are real ones, from the file
done
docker compose --env-file versions.env --env-file config/deployment.env -f compose/core.yaml -f compose/apps.yaml config -q
echo "compose files valid"
