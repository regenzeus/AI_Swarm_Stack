#!/bin/sh
# The interim scorer in a throwaway container (docs/spikes/EVAL.md): the pinned Python image, the pinned packages of
# requirements.txt, the site's Phoenix and model gateway. Run it from the repository's root with the gateway key in the
# environment, never on the command line:
#   sops exec-env secrets/agent-keys.enc.yaml 'sh spikes/eval/run.sh run spikes/eval/change-requests.yaml'
# Paths given to exam.py are read relative to the current folder (mounted read-only at /work).
# --network host: the gateway listens on 127.0.0.1 only, which a container on its own network cannot reach under
# rootless Docker; the container publishes nothing.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
: "${PHOENIX_BASE_URL:=http://127.0.0.1:6006}"
: "${LITELLM_BASE_URL:=http://127.0.0.1:4000/v1}"
: "${JUDGE_KEY_VAR:=VK_EVAL}"
: "${JUDGE_MODEL:=gpt-sub-fast}"
export PHOENIX_BASE_URL LITELLM_BASE_URL JUDGE_KEY_VAR JUDGE_MODEL
exec docker run --rm --name "spike-eval-exam-$$" --network host -v "$here:/exam:ro" -v "$PWD:/work:ro" -w /work \
  -e PHOENIX_BASE_URL -e LITELLM_BASE_URL -e JUDGE_KEY_VAR -e JUDGE_MODEL -e "$JUDGE_KEY_VAR" \
  python@sha256:12316debbfb86890f6b2d825820612741ba527ad5a44e3902759141d572bfe8f \
  sh -c 'pip install -q --root-user-action=ignore --disable-pip-version-check --no-deps -r /exam/requirements.txt >&2 \
         && exec python /exam/exam.py "$@"' exam "$@"
