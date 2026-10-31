#!/usr/bin/env bash
# CI: are the compose files valid? Required secrets (${VAR:?...}) get dummy values, so no real secret is needed.
set -euo pipefail
cd "$(dirname "$0")/.."
for v in $(grep -ho '\${[A-Z_]*:?' compose/*.yaml | tr -d '${:?' | sort -u); do export "$v=ci-dummy"; done
docker compose --env-file versions.env -f compose/core.yaml -f compose/apps.yaml config -q
echo "compose files valid"
