#!/usr/bin/env bash
# Deploy the mail copy to the NAS (host-side, like deploy-ha: agents never hold the NAS key). Never deletes NAS data: the
# copy and the secret survive every redeploy. Without an app password it starts, waits and says so.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=/volume1/docker/mailvault
DOCKER="sudo -n /usr/local/bin/docker"      # the docker-only NOPASSWD sudoers rule on the NAS

ssh synology "mkdir -p $DIR/data $DIR/secret && chmod 700 $DIR/data $DIR/secret"
# no scp/SFTP on the NAS: pipe the files over ssh
ssh synology "cat > $DIR/compose.yaml" <nas/mailvault/compose.yaml
ssh synology "cat > $DIR/vault.py" <nas/mailvault/vault.py
ssh synology "cd $DIR && $DOCKER compose up -d --force-recreate"
sleep 5
ssh synology "$DOCKER logs --tail 5 mailvault" 2>&1 | cut -c1-160   # cap: id (a log line in a terminal)
