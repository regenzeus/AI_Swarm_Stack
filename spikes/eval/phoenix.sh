#!/bin/sh
# A throwaway Phoenix for the spike (docs/spikes/EVAL.md): the stack's pinned image by digest, the on-site settings of
# phoenix-onsite.env, its own network, its UI and API on 127.0.0.1:16006 only, no volume (gone when removed).
#   sh spikes/eval/phoenix.sh start | stop
set -eu
here=$(cd "$(dirname "$0")" && pwd)
case "${1:-}" in
  start)
    docker network inspect spike-eval-net >/dev/null 2>&1 || docker network create spike-eval-net >/dev/null
    docker run -d --name spike-eval-phoenix --network spike-eval-net -p 127.0.0.1:16006:6006 \
      -e PHOENIX_WORKING_DIR=/data --env-file "$here/phoenix-onsite.env" \
      arizephoenix/phoenix@sha256:095f498723ec1fa3b55592af83d5a1e3bf026ba15a4a44e325f20dfdbb71452a >/dev/null
    echo "starting; ready when http://127.0.0.1:16006/healthz answers OK (about 80 s on the first start)" ;;
  stop)
    docker rm -f spike-eval-phoenix >/dev/null 2>&1 || true
    docker network rm spike-eval-net >/dev/null 2>&1 || true ;;
  *) echo "usage: phoenix.sh start|stop" >&2; exit 2 ;;
esac
