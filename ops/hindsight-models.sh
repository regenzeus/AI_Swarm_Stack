#!/usr/bin/env bash
# One-time download of Hindsight's multilingual models into the hindsight-models volume (Hindsight itself has no
# internet). Needed on a new machine before `make up`; the backup leaves the models out (~0.9 GB, rebuildable).
set -euo pipefail
export DOCKER_HOST=${DOCKER_HOST:-unix:///run/user/1000/docker.sock}
IMG=ghcr.io/vectorize-io/hindsight-api:1.1.0
docker volume create aistack_hindsight-models >/dev/null
docker run --rm -u 0 --network aistack_edge -e HF_HOME=/models -v aistack_hindsight-models:/models \
  --entrypoint /app/api/.venv/bin/python "$IMG" -c '
from sentence_transformers import SentenceTransformer, CrossEncoder
SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
CrossEncoder("cross-encoder/mmarco-mMiniLMv2-L12-H384-v1")'
docker run --rm -u 0 -v aistack_hindsight-models:/models alpine chown -R 1000:1000 /models
echo "hindsight models ready"
