#!/usr/bin/env bash
# Deploy a committed revision of TestRepo (~/code/TestRepo) to the Synology NAS. Host-side only: the coding
# agent never holds the NAS key. Mirrors TestRepo's deploy/deploy.ps1 (scp -O: SFTP is off on the NAS).
# Usage: ops/deploy-testrepo.sh [ref]
set -euo pipefail
REPO=/home/owner/code/TestRepo; REF="${1:-HEAD}"; APP=/volume1/docker/testrepo
[ -z "$(git -C "$REPO" status --porcelain)" ] || { echo "TestRepo has uncommitted changes; commit first." >&2; exit 1; }
sha=$(git -C "$REPO" rev-parse --short=12 "$REF")
echo "Deploying TestRepo $sha"
tmp=$(mktemp --suffix=.tar); git -C "$REPO" archive --format=tar -o "$tmp" "$sha"
ssh synology "mkdir -p $APP/config $APP/data $APP/backups $APP/scripts $APP/state $APP/releases/$sha"
scp -O -q "$tmp" "synology:$APP/releases/$sha.tar"; rm -f "$tmp"
ssh synology "cd $APP/releases/$sha && tar -xf ../$sha.tar && rm ../$sha.tar && cp deploy/compose.yaml $APP/config/compose.yaml && cp deploy/ops.sh $APP/scripts/ops.sh && sed -i 's/\r\$//' $APP/scripts/ops.sh && chmod 750 $APP/scripts/ops.sh && sh $APP/scripts/ops.sh deploy $sha && cd $APP/releases && ls -1t | tail -n +6 | xargs -r rm -rf"
curl -s http://192.168.1.80:8088/api/info; echo
