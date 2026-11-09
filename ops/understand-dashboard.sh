#!/usr/bin/env bash
# Show a repo's Understand Anything code map in the read-only viewer, on your tailnet only:
#   make understand-dashboard REPO=name   ->  https://<pc>.ts.net:8446/  (Mission Control: Code -> repo)
# One repo at a time; the next call replaces it. The viewer only reads <repo>/.ua and the files listed in the graph and
# listens on loopback inside its container. A gate sidecar in the same network namespace (config/gate/codemap.Caddyfile)
# publishes it on 127.0.0.1:5173 of WSL (tailscale serve :8446), lets in only requests that carry your Tailscale login,
# and adds the viewer's access token itself: no token or password to know.
set -euo pipefail
eval "$(python3 "$(dirname "$0")/deployment.py" shell)"   # this deployment's hosts and paths (deployments/<name>/deployment.env)
export DOCKER_HOST=${DOCKER_HOST:-$DOCKER_SOCKET}
NAME=${1:?usage: ops/understand-dashboard.sh <repo name in ~/code>}
REPO=$CODE_DIR/$NAME
STACK=$(cd "$(dirname "$0")/.." && pwd)
case "${CODEMAP_GATE:-tailnet}" in                       # the deployment's choice (docs/PLATFORM.md): tailnet (home) or local
  tailnet) CONF=$STACK/config/gate/codemap.Caddyfile ;;
  local)   CONF=$STACK/config/gate/codemap-local.Caddyfile ;;   # no tailnet: loopback only, no login to check
  *) echo "CODEMAP_GATE=$CODEMAP_GATE: tailnet or local" >&2; exit 2 ;;
esac
GATE=$(grep -m1 '^GATE_IMAGE=' "$(dirname "$0")/../versions.env" | cut -d= -f2)
[ -f "$REPO/.ua/knowledge-graph.json" ] || { echo "No code map for $NAME yet: make understand REPO=$NAME" >&2; exit 2; }
docker rm -f aistack-ua-viewer aistack-ua-viewer-port >/dev/null 2>&1 || true
# The token only has to match the gate's: the gate is the access control.
docker run -d --name aistack-ua-viewer --restart unless-stopped --read-only --memory 256m \
  -p 127.0.0.1:5173:5174 -e UNDERSTAND_ACCESS_TOKEN=tailnet -v "$REPO:/work/$NAME:ro" aistack/opencode:1.19.4-ua1 \
  understand-anything-viewer "/work/$NAME" --port 5173 --no-open >/dev/null
docker run -d --name aistack-ua-viewer-port --restart unless-stopped --read-only --memory 64m --tmpfs /data --tmpfs /config \
  --network container:aistack-ua-viewer -v "$CONF:/etc/caddy/Caddyfile:ro" "$GATE" >/dev/null
for _ in $(seq 20); do docker logs aistack-ua-viewer 2>&1 | grep -q "Dashboard URL" && break; sleep 1; done
if [ "${CODEMAP_GATE:-tailnet}" = local ] || [ -z "${PC_TAILNET_HOST%%*.invalid}" ]; then echo "http://127.0.0.1:5173/  ($NAME)"
else echo "https://$PC_TAILNET_HOST:8446/  ($NAME)"; fi
