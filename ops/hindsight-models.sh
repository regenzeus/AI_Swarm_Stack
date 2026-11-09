#!/usr/bin/env bash
# One-time download of Hindsight's multilingual models into the hindsight-models volume (Hindsight itself has no
# internet). Needed on a new machine before `make up`; the backup leaves the models out (~0.9 GB, rebuildable).
set -euo pipefail
ALPINE_IMAGE=${ALPINE_IMAGE:-$(grep -m1 "^ALPINE_IMAGE=" "$(dirname "$0")/../versions.env" | cut -d= -f2-)}   # pinned (review OPS-R9)
eval "$(python3 "$(dirname "$0")/deployment.py" shell)"   # this deployment's hosts and paths (deployments/<name>/deployment.env)
export DOCKER_HOST=${DOCKER_HOST:-$DOCKER_SOCKET}
IMG=ghcr.io/vectorize-io/hindsight-api:1.1.0
docker volume create aistack_hindsight-models >/dev/null
docker run --rm -u 0 --network aistack_edge -e HF_HOME=/models -v aistack_hindsight-models:/models \
  --entrypoint /app/api/.venv/bin/python "$IMG" -c '
from sentence_transformers import SentenceTransformer, CrossEncoder
SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")'
docker run --rm -u 0 -v aistack_hindsight-models:/models "$ALPINE_IMAGE" chown -R 1000:1000 /models
echo "hindsight models ready"
