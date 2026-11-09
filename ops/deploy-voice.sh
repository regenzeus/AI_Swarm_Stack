#!/usr/bin/env bash
# Deploy Hermes' voice services to the NAS (host-side, like deploy-ha.sh: agents never hold the NAS key).
# Writes nas/voice/compose.yaml to /volume1/docker/voice, pulls the pinned images and starts them; the downloaded
# models stay in /volume1/docker/voice/{whisper,piper}. Never deletes NAS data.
#   ops/deploy-voice.sh [WHISPER_MODEL=...] [STT_LIBRARY=sherpa|faster-whisper] [PIPER_VOICE=en_GB-alba-medium]   (defaults: nas/voice/compose.yaml)
set -euo pipefail
python3 "$(dirname "$0")/deployment.py" need voice || exit 0   # GEN-13
cd "$(dirname "$0")/.."
DIR=/volume1/docker/voice
DOCKER="sudo -n /usr/local/bin/docker"      # the docker-only NOPASSWD sudoers rule on the NAS

ssh synology "mkdir -p $DIR/whisper $DIR/piper"
ssh synology "cat > $DIR/compose.yaml" <nas/voice/compose.yaml
if [ $# -gt 0 ]; then                       # the settings (sudo drops the environment; compose reads .env); none given: kept
  printf '%s\n' "$@" | ssh synology "cat > $DIR/.env"      # review OPS-R18: a run without them blanked the NAS's settings
fi
ssh synology "cd $DIR && $DOCKER compose pull -q && $DOCKER compose up -d"
for _ in $(seq 1 60); do                    # the first start downloads the model (Parakeet: about 650 MB)
  if ssh synology python3 - describe <ops/voice_bench.py >/dev/null 2>&1; then     # both answer the Wyoming describe
    echo "voice services are up on the NAS (127.0.0.1:10300 Whisper, 127.0.0.1:10200 Piper)"
    exit 0
  fi
  sleep 5
done
echo "a voice service did not start within 300 s; see: ssh synology '$DOCKER logs --tail 50 voice-whisper'" >&2
exit 1
