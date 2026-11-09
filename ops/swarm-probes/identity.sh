#!/usr/bin/env bash
# Phase 0 identity probe (docs/SWARM-PHASE0.md): a throwaway MCP server on the gateway's network, then
# identity_probe.py with the master key. Prints results and hashes only; removes everything it made.
set -euo pipefail
cd "$(dirname "$0")/../.."
D="$PWD/ops/swarm-probes"
docker rm -f swarmprobe >/dev/null 2>&1 || true
trap 'docker rm -f swarmprobe >/dev/null 2>&1 || true' EXIT
docker run -d --rm --name swarmprobe --network aistack_backend --memory 64m \
  -v "$D/mcp_probe.py":/p.py:ro python:3.12-slim python /p.py >/dev/null
sleep 2
sops exec-env secrets/secrets.enc.yaml "python3 $D/identity_probe.py"
