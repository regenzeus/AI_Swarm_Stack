#!/bin/bash
# wslhost-setup.sh <user> [root]: the wsl-host place's worker (GEN-22, docs/AI-STACK.md §7), set up once by the owner.
# The worker runs the worker protocol (ops/fakeworker.py, the same rules as Windows' worker) as the Linux user that owns
# the deployment's licensed tools and repositories, which may not be the user the stack runs as. That user may have no
# sudo, so this script, run once with sudo, makes the root folders that user owns and a system unit running as them.
# Then the deployment names the place in its places.yaml:  places: {wsl-host: {root: <root>, user: <user>}}
# The stack only writes requests into <root>/inbox and reads <root>/outbox; job kinds are approved by the owner in
# Needs you, by the hash of their file, before one runs.
set -euo pipefail
U=${1:?the user that owns the tools}
ROOT=${2:-/home/$U/aistack-worker}
REPO=$(cd "$(dirname "$0")/.." && pwd)
[ "$(id -u)" = 0 ] || { echo "run it with sudo, once: sudo $0 $U" >&2; exit 1; }
id "$U" >/dev/null
install -d -o "$U" -g "$U" -m 0750 "$ROOT" "$ROOT/outbox" "$ROOT/jobs.d" "$ROOT/repos" "$ROOT/scratch"
install -d -o "$U" -g "$(stat -c %G "$REPO")" -m 0770 "$ROOT/inbox"      # the stack's user writes requests here
cat > /etc/systemd/system/aistack-wslhost-worker.service <<EOF
[Unit]
Description=The AI Stack's wsl-host worker (GEN-22), as $U
After=network.target

[Service]
User=$U
ExecStart=/usr/bin/python3 $REPO/ops/fakeworker.py $ROOT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now aistack-wslhost-worker.service
echo "the wsl-host worker runs as $U over $ROOT; add to the deployment's places.yaml:"
echo "  places: {wsl-host: {root: $ROOT, user: $U}}"
