#!/usr/bin/env bash
# Put the skills folder back exactly as committed in ~/hermes-skills (after a `git revert` there, or to undo a
# bad curator run). Usage counters and curator state stay as they are.
set -euo pipefail
ref="${1:-HEAD}"
cd ~/hermes-skills
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git archive "$ref" skills | tar -C "$tmp" -xf -
docker exec -u hermes aistack-hermes-1 sh -c 'cd /opt/data/skills && find . -mindepth 1 -maxdepth 1 ! -name ".usage.json*" ! -name ".curator_state" ! -name ".curator_backups" -exec rm -rf {} +'
tar -C "$tmp" -cf - skills | docker exec -i -u hermes aistack-hermes-1 tar -C /opt/data -xf -
docker restart aistack-hermes-1 >/dev/null   # the gateway caches the skills index
docker restart aistack-hermes-dashboard-1 aistack-gate-hermes-dashboard-1 >/dev/null   # they share Hermes' network
echo "skills restored from hermes-skills@$(git rev-parse --short "$ref")"
