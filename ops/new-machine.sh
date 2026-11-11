#!/usr/bin/env bash
# New PC, stage 2 (after bootstrap-wsl-1-root.sh and `wsl --shutdown`). Runs as owner:
#   wsl -d Ubuntu-24.04 -u owner -- bash -lc 'bash ~/ai-stack/ops/new-machine.sh'
# Rootless Docker, then the whole stack from the newest backup in ~/restore (copied in by stage 1 from
# C:\AI\_staging), or from the NAS if there is none. Needs the age key (stage 1 copies age-key.txt).
# REHEARSAL=1: everything isolated from the live stack (see compose/rehearsal.yaml), no timers.
set -euo pipefail
# GEN-20: it rebuilds the home stack from the home stack's backup; a deployment without the home feature never runs it
python3 "$(dirname "$0")/deployment.py" need home >/dev/null || { echo "refused: ops/new-machine.sh rebuilds the home stack from its backup, and this deployment has no home feature" >&2; exit 1; }
export XDG_RUNTIME_DIR=/run/user/$(id -u)
cd ~/ai-stack
[ -f ~/.config/sops/age/keys.txt ] || { echo "age key missing: put age-key.txt next to the staged ai-stack" >&2; exit 2; }

if ! systemctl --user is-active -q docker; then
  dockerd-rootless-setuptool.sh install --skip-iptables >/dev/null
fi
if [ ! -f ~/.config/systemd/user/docker.service.d/no-detach-netns.conf ]; then   # see the file for why
  install -D -m 644 ops/systemd/docker-no-detach-netns.conf ~/.config/systemd/user/docker.service.d/no-detach-netns.conf
  install -D -m 644 ops/systemd/docker-boot.conf ~/.config/systemd/user/docker.service.d/boot.conf
  systemctl --user daemon-reload && systemctl --user restart docker
fi
grep -q DOCKER_HOST ~/.bashrc || echo "export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock" >> ~/.bashrc
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
docker info >/dev/null && echo "1/4 rootless docker ready"

# Images built locally (aistack/*) are not in any registry: build them from the repo.
# Each as a deploy builds it: in FROM order (Hermes before the builder), with versions.env's base pins, stopping on a
# failure (review OPS-R6: a failed build was hidden behind "2/4 images built"). Rehearsal: BUILD_ONLY="images/hermes/".
# shellcheck disable=SC2086
python3 ops/deploy.py build ${BUILD_ONLY:-all} || { echo "2/4 an image did not build: stopped (see above)"; exit 1; }
echo "2/4 images built"

file=$(ls -1t ~/restore/*.tar.gz.age 2>/dev/null | head -1 || true)
bash ops/restore.sh apply ${file:+"$file"}
echo "3/4 restored ${file:-newest backup from the NAS}"

if [ -z "${REHEARSAL:-}" ]; then
  # the runner's own Python (PLT-37) lives in ~/.local/share, which no backup holds: made here, before its units start
  # (review 10 Nov, RUNNER2-R2: missions.service and tracker-poll failed "not found" on a new PC)
  bash ops/runner_env.sh || { echo "4/4 the runner's environment could not be made (ops/runner_env.sh): stopped"; exit 1; }
  systemctl --user daemon-reload
  for t in $(python3 ops/deployment.py timers); do systemctl --user enable --now "$t" >/dev/null; done   # its features only (GEN-13)
  systemctl --user enable --now missions.service >/dev/null      # Mission Control runner (schedules briefings, missions)
  echo "4/4 timers enabled; next: make smoke, then the Windows tasks in ops/windows (NEW-MACHINE.md)"
else
  echo "4/4 rehearsal: timers left off"
fi
