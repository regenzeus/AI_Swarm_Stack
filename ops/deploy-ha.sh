#!/usr/bin/env bash
# Deploy Home Assistant to the NAS (host-side, like deploy-testrepo: agents never hold the NAS key).
# Writes nas/homeassistant/compose.yaml to /volume1/docker/homeassistant, seeds configuration.yaml only if there is
# none yet, pulls the pinned image and starts it. Never deletes NAS data; the config folder survives every redeploy.
set -euo pipefail
cd "$(dirname "$0")/.."
DIR=/volume1/docker/homeassistant
DOCKER="sudo -n /usr/local/bin/docker"      # the docker-only NOPASSWD sudoers rule on the NAS

ssh synology "mkdir -p $DIR/config"
# no scp/SFTP on the NAS: pipe the files over ssh
ssh synology "cat > $DIR/compose.yaml" <nas/homeassistant/compose.yaml
ssh synology "test -s $DIR/config/configuration.yaml || cat > $DIR/config/configuration.yaml" <nas/homeassistant/configuration.yaml
ssh synology "cd $DIR && $DOCKER compose pull -q && $DOCKER compose up -d"
for _ in $(seq 1 40); do
  if curl -fsS -o /dev/null --max-time 5 http://192.168.1.80:8123/manifest.json; then
    echo "Home Assistant is up: http://192.168.1.80:8123"
    exit 0
  fi
  sleep 5
done
echo "Home Assistant did not answer within 200 s; see: ssh synology '$DOCKER logs --tail 50 homeassistant'" >&2
exit 1
