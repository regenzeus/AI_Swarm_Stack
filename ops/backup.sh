#!/usr/bin/env bash
# Nightly encrypted backup of everything that is not already in git, to the NAS. Host-side (the agents have no
# NAS key). One file per run: /volume1/docker/ai-backup/aistack-<date>.tar.gz.age, encrypted to the sops age key,
# the 14 newest are kept. Restore: ops/restore.sh (see there). Usage: ops/backup.sh
set -euo pipefail
eval "$(python3 "$(dirname "$0")/deployment.py" shell)"   # this deployment's hosts and paths (config/deployment.env)
export DOCKER_HOST=${DOCKER_HOST:-$DOCKER_SOCKET}
DEST=/volume1/docker/ai-backup
KEEP=14
OUTBOX=/srv/ai/backup-outbox; mkdir -p $OUTBOX
NAME=aistack-$(date +%Y%m%d-%H%M).tar.gz.age
RCPT=$(age-keygen -y ~/.config/sops/age/keys.txt)
STAGE=$(mktemp -d); trap "rm -rf $STAGE; docker unpause aistack-hermes-1 aistack-openwebui-1 aistack-qmd-1 aistack-opencode-1 >/dev/null 2>&1 || true" EXIT

# Databases: postgres as a dump (LiteLLM keys, budgets, spend); the SQLite files inside the volumes are copied
# while their containers are paused, so each file is a consistent crash image.
docker exec aistack-postgres-1 pg_dumpall -U litellm > $STAGE/postgres.sql
docker exec aistack-hindsight-db-1 pg_dumpall -U hindsight > $STAGE/hindsight.sql      # long-term memory bank
# /srv/ai, without what ops/backup-copy.sh names; a file the backup user cannot read is skipped and logged, not a failed
# backup (PLT-13: one did that on 2026-10-29, the AI phone's key, and another on 2026-10-31, a container's file in workbench/)
"$(dirname "$0")/backup-copy.sh" /srv/ai/ $STAGE/srv-ai/
# The vault and the repositories stay in use: tar's exit 1 says a file changed while it read it, and the archive is still good
# (6 Nov 2026: the vault's git, the night's backup lost). Anything worse stops the backup.
# limit: stops, tar's exit above 1 is a real failure; 1 only says a file changed while it was read
live_tar() { local rc=0; tar "$@" || rc=$?; [ "$rc" -le 1 ] || exit "$rc"; }
live_tar -C ~ -cf $STAGE/home.tar ai-stack hermes-skills code .config/systemd/user
live_tar -C /srv -cf $STAGE/vault.tar vault
docker pause aistack-hermes-1 aistack-openwebui-1 aistack-qmd-1 aistack-opencode-1 >/dev/null
docker run --rm --network none -v $STAGE:/stage \
  -v aistack_hermes-home:/vol/hermes-home:ro -v aistack_litellm-auth:/vol/litellm-auth:ro \
  -v aistack_openwebui:/vol/openwebui:ro -v aistack_qmd-data:/vol/qmd-data:ro \
  -v aistack_opencode-data:/vol/opencode-data:ro alpine \
  tar -C /vol -cf /stage/volumes.tar --exclude=openwebui/cache --exclude=qmd-data/cache/qmd/models \
      --exclude="hermes-home/cache" --exclude="hermes-home/logs" .
docker unpause aistack-hermes-1 aistack-openwebui-1 aistack-qmd-1 aistack-opencode-1 >/dev/null

( cd $STAGE && sha256sum postgres.sql hindsight.sql home.tar vault.tar volumes.tar > SHA256SUMS && echo "$NAME $(hostname) $(date -Is)" > MANIFEST )
tar -C $STAGE -czf - MANIFEST SHA256SUMS postgres.sql hindsight.sql srv-ai home.tar vault.tar volumes.tar \
  | age -r "$RCPT" > $OUTBOX/.$NAME.part && mv $OUTBOX/.$NAME.part $OUTBOX/$NAME
ssh synology "mkdir -p $DEST && cat > $DEST/.$NAME.part && mv $DEST/.$NAME.part $DEST/$NAME" < $OUTBOX/$NAME
find $OUTBOX -name "aistack-*.tar.gz.age" ! -name "$NAME" -delete   # off-site: Windows task copies the newest to OneDrive
size=$(ssh synology "cd $DEST && ls -1t aistack-*.tar.gz.age | tail -n +$((KEEP+1)) | xargs -r rm -f; du -h $NAME | cut -f1")
echo "{\"ts\": $(date +%s), \"kind\": \"backup\", \"file\": \"$NAME\", \"size\": \"$size\"}" >> /srv/ai/state/backups.jsonl
echo "backup $NAME ($size) -> synology:$DEST"
