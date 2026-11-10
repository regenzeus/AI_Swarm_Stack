#!/bin/bash
# The host runner's own Python environment (PLT-37): its packages (ops/runner-requirements.txt) in one environment of
# the runner's own, outside the system Python, set up by uv (a pinned, checksummed binary) and needing no sudo, so a
# work machine whose user has none can run it too.
#
#   bash ops/runner_env.sh          make or refresh the environment; prints its python on success
#   bash ops/runner_env.sh lock     write ops/runner-requirements.lock from ops/runner-requirements.txt (with hashes)
#
# The environment follows ops/runner-requirements.lock exactly (hashes required); it is made again only when the lock
# changes. Downloads honour HTTPS_PROXY, as a site behind a company proxy needs.
set -euo pipefail
UV_VERSION=0.13.5
UV_SHA256=f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f   # uv-x86_64-unknown-linux-gnu.tar.gz, GitHub's digest
HERE=$(cd "$(dirname "$0")" && pwd)
TOOLS=${AISTACK_TOOLS:-$HOME/.local/share/aistack}
VENV=${AISTACK_RUNNER_ENV:-$TOOLS/runner}
REQ=$HERE/runner-requirements.txt
LOCK=$HERE/runner-requirements.lock
ARCH=$(uname -m)
if [ "$ARCH" != x86_64 ]; then   # limit: refuses, uv is pinned for x86_64 only; a machine of another kind gets its pin added first
  echo "refused: the runner's environment is pinned for x86_64, and this machine is $ARCH" >&2; exit 2
fi
UV=$TOOLS/uv-$UV_VERSION/uv
if [ ! -x "$UV" ]; then
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  curl -fsSL --retry 3 -o "$tmp/uv.tgz" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
  if ! echo "$UV_SHA256  $tmp/uv.tgz" | sha256sum -c --quiet; then
    echo "refused: the uv download does not match its pinned checksum" >&2; exit 3
  fi
  tar -xzf "$tmp/uv.tgz" -C "$tmp"
  mkdir -p "$TOOLS/uv-$UV_VERSION"
  install -m 755 "$tmp/uv-x86_64-unknown-linux-gnu/uv" "$UV"
fi
if [ "${1:-}" = lock ]; then
  "$UV" pip compile -q --python-version 3.12 --generate-hashes --no-header -o "$LOCK" "$REQ"
  echo "wrote $LOCK"; exit 0
fi
want=$(sha256sum "$LOCK" | cut -c1-16)   # cap: id, the lock's fingerprint
if [ "$(cat "$VENV/.lock-sha" 2>/dev/null || true)" != "$want" ]; then
  [ -x "$VENV/bin/python" ] || "$UV" venv -q --python /usr/bin/python3 "$VENV"
  "$UV" pip sync -q --require-hashes --python "$VENV/bin/python" "$LOCK"
  echo "$want" > "$VENV/.lock-sha"
fi
"$VENV/bin/python" -c "import yaml" && echo "$VENV/bin/python"
