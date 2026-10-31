#!/usr/bin/env bash
# WSL bootstrap, stage 2. Runs as owner after `wsl --shutdown`:
#   wsl -d Ubuntu-24.04 -u owner -- bash -lc '~/ai-stack/ops/bootstrap-wsl-2-user.sh'
# Rootless Docker, age key + sops rules, first secrets, git repos, vault skeleton, push to Forgejo.
set -euo pipefail
export XDG_RUNTIME_DIR=/run/user/$(id -u)
cd ~/ai-stack

# Rootless Docker for owner
if ! systemctl --user is-active -q docker; then
  dockerd-rootless-setuptool.sh install --skip-iptables >/dev/null
fi
if [ ! -f ~/.config/systemd/user/docker.service.d/no-detach-netns.conf ]; then   # see the file for why
  install -D -m 644 ops/systemd/docker-no-detach-netns.conf ~/.config/systemd/user/docker.service.d/no-detach-netns.conf
  systemctl --user daemon-reload && systemctl --user restart docker
fi
grep -q DOCKER_HOST ~/.bashrc || echo "export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock" >> ~/.bashrc
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
docker run --rm hello-world >/dev/null && echo "rootless docker OK"

# age key + sops creation rule
mkdir -p ~/.config/sops/age
[ -f ~/.config/sops/age/keys.txt ] || { age-keygen -o ~/.config/sops/age/keys.txt 2>/dev/null; chmod 600 ~/.config/sops/age/keys.txt; }
recipient=$(grep -o 'age1[0-9a-z]*' ~/.config/sops/age/keys.txt | head -1)
cat > .sops.yaml <<EOF
creation_rules:
  - path_regex: secrets/.*\.enc\.yaml$
    age: $recipient
EOF

# First secrets: generated here, provider keys added later by you with `make secrets-edit`
if [ ! -f secrets/secrets.enc.yaml ]; then
  mkdir -p secrets
  tmp=$(mktemp)
  printf 'LITELLM_MASTER_KEY: sk-%s\nPG_PASSWORD: %s\nANTHROPIC_API_KEY: ""\nOPENROUTER_API_KEY: ""\n' \
    "$(openssl rand -hex 24)" "$(openssl rand -hex 24)" > "$tmp"
  sops -e --filename-override secrets/secrets.enc.yaml --input-type yaml --output-type yaml "$tmp" > secrets/secrets.enc.yaml
  rm -f "$tmp"
fi

# Git identity (repo-local)
for d in ~/ai-stack /srv/vault; do
  git -C "$d" init -q -b main 2>/dev/null || true
  git -C "$d" config user.name "Owner"
  git -C "$d" config user.email "owner@example.com"
done

# Vault skeleton (Karpathy LLM Wiki layout)
cd /srv/vault
mkdir -p raw/{_inbox,_files,articles,papers,notes,clips} wiki/{concepts,entities,projects,howto,comparisons,answers}
for d in raw/_inbox raw/articles raw/papers raw/notes raw/clips wiki/concepts wiki/entities wiki/projects wiki/howto wiki/comparisons wiki/answers; do
  [ -e "$d/.gitkeep" ] || touch "$d/.gitkeep"
done
[ -f .gitignore ] || printf '.obsidian/workspace*.json\n.obsidian/cache\nraw/_files/\n.trash/\n' > .gitignore
[ -f index.md ] || printf '# Index\n\nCatalogue of every wiki page, one line each. Maintained by the curator.\n' > index.md
[ -f log.md ] || printf '# Log\n\nAppend-only. Entries start with `## [YYYY-MM-DD HH:MM] <op> <target>`.\n' > log.md
[ -f AGENTS.md ] || cp ~/ai-stack/vault-template/AGENTS.md AGENTS.md
git add -A && git commit -qm "Vault skeleton (LLM Wiki layout)" 2>/dev/null || true

# Skills repo placeholder until Hermes exists (MVP 1 points ~/.hermes/skills at it)
mkdir -p ~/hermes-skills && cd ~/hermes-skills
git init -q -b main 2>/dev/null || true
git config user.name "Owner"; git config user.email "owner@example.com"
[ -f README.md ] || printf '# hermes-skills\n\nSkills learned by Hermes (agentskills.io SKILL.md). Auto-committed by the curation glue.\n' > README.md
printf '.usage.json\n.curator_backups/\n' > .gitignore
git add -A && git commit -qm "Initialise skills repo" 2>/dev/null || true

cd ~/ai-stack && git add -A && git commit -qm "MVP 0: core stack, keys, smoke test" 2>/dev/null || true

# Push all three (Forgejo creates private repos on first push)
for r in ai-stack:$HOME/ai-stack vault:/srv/vault hermes-skills:$HOME/hermes-skills; do
  name=${r%%:*}; dir=${r#*:}
  git -C "$dir" remote get-url origin >/dev/null 2>&1 || git -C "$dir" remote add origin "forgejo:regenzeus/$name.git"
  git -C "$dir" push -q -u origin main && echo "pushed $name"
done
echo "STAGE2_DONE"
