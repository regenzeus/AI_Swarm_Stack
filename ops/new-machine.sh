#!/usr/bin/env bash
# New PC, stage 2 (after bootstrap-wsl-1-root.sh and `wsl --shutdown`). Runs as owner:
#   wsl -d Ubuntu-24.04 -u owner -- bash -lc 'bash ~/ai-stack/ops/new-machine.sh'
# Rootless Docker, then the whole stack from the newest backup in ~/restore (copied in by stage 1 from
# C:\AI\_staging), or from the NAS if there is none. Needs the age key (stage 1 copies age-key.txt).
# REHEARSAL=1: everything isolated from the live stack (see compose/rehearsal.yaml), no timers.
set -euo pipefail
export XDG_RUNTIME_DIR=/run/user/$(id -u)
cd ~/ai-stack
[ -f ~/.config/sops/age/keys.txt ] || { echo "age key missing: put age-key.txt next to the staged ai-stack" >&2; exit 2; }

if ! systemctl --user is-active -q docker; then
  dockerd-rootless-setuptool.sh install --skip-iptables >/dev/null
fi
if [ ! -f ~/.config/systemd/user/docker.service.d/no-detach-netns.conf ]; then   # see the file for why
  install -D -m 644 ops/systemd/docker-no-detach-netns.conf ~/.config/systemd/user/docker.service.d/no-detach-netns.conf
  systemctl --user daemon-reload && systemctl --user restart docker
fi
grep -q DOCKER_HOST ~/.bashrc || echo "export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock" >> ~/.bashrc
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
docker info >/dev/null && echo "1/4 rootless docker ready"

# Images built locally (aistack/*) are not in any registry: build them from the repo.
for d in ${BUILD_ONLY:-images/*/}; do          # rehearsal: BUILD_ONLY="images/hermes/" (memory)
  tag=$(grep -rhoE "aistack/$(basename "$d"):[A-Za-z0-9._-]+" compose versions.env Makefile 2>/dev/null | head -1)
  [ -n "$tag" ] && docker build -q -t "$tag" "$d" >/dev/null && echo "    built $tag"
done
echo "2/4 images built"

file=$(ls -1t ~/restore/*.tar.gz.age 2>/dev/null | head -1 || true)
bash ops/restore.sh apply ${file:+"$file"}
echo "3/4 restored ${file:-newest backup from the NAS}"

if [ -z "${REHEARSAL:-}" ]; then
  systemctl --user daemon-reload
  for t in ~/.config/systemd/user/*.timer; do systemctl --user enable --now "$(basename "$t")" >/dev/null; done
  systemctl --user enable --now missions.service >/dev/null      # Mission Control runner (schedules briefings, missions)
  echo "4/4 timers enabled; next: make smoke, then the Windows tasks in ops/windows (NEW-MACHINE.md)"
else
  echo "4/4 rehearsal: timers left off"
fi
