#!/usr/bin/env bash
# CI: are the compose files valid, for every deployment of deployments/ with the features it switches on? Required secrets
# (${VAR:?...}, digits too: N8N_DB_PASSWORD) get dummy values, so no real secret is needed; a deployment's own values are real ones, from its file.
set -euo pipefail
cd "$(dirname "$0")/.."
for env in deployments/*/deployment.env; do
  (
    for v in $(grep -ho '\${[A-Z0-9_]*:?' compose/*.yaml | tr -d '${:?' | sort -u); do
      grep -q "^$v=." "$env" || export "$v=ci-dummy"
    done
    unset COMPOSE_PROFILES                       # the deployment's own FEATURES, from its file
    docker compose --env-file versions.env --env-file "$env" -f compose/core.yaml -f compose/apps.yaml config -q
  )
  echo "compose files valid for $(basename "$(dirname "$env")")"
done
