#!/usr/bin/env bash
# WSL bootstrap, stage 1. Runs as root from Windows while /mnt/c still exists:
#   wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/AI/_staging/ai-stack/ops/bootstrap-wsl-1-root.sh
# Creates user owner (no sudo; admin work goes through `wsl -u root`), installs Docker (rootless)
# and sops, locks WSL down, and copies the staged ai-stack. Then: wsl --shutdown, stage 2.
# New PC (restore, see NEW-MACHINE.md): also put the newest backup (*.tar.gz.age from OneDrive\AI-Backup) and
# age-key.txt (OneDrive\AI-Keys) into C:\AI\_staging; they are copied in, then stage 2 is ops/new-machine.sh.
# Overridable for a rehearsal (ops/windows/rehearse-new-pc.ps1): STAGE, VAULT_WIN, EXPORTS_WIN.
set -euo pipefail
U=owner
STAGE=${STAGE:-/mnt/c/AI/_staging/ai-stack}
VAULT_WIN=${VAULT_WIN:-C:/AI/vault}
EXPORTS_WIN=${EXPORTS_WIN:-C:/AI/exports}
source "$STAGE/versions.env"

# Fresh Ubuntu images already have a uid-1000 user (the image's "ubuntu", or whoever the installer created):
# take it over as owner, since the stack's volumes and files belong to uid 1000.
old=$(getent passwd 1000 | cut -d: -f1 || true)
if [ -n "$old" ] && [ "$old" != "$U" ]; then
  usermod -l "$U" -d /home/$U -m "$old"; groupmod -n "$U" "$(id -gn "$U")" 2>/dev/null || true
  sed -i "s/^$old:/$U:/" /etc/subuid /etc/subgid              # rootless Docker looks its ranges up by name
fi
id "$U" >/dev/null 2>&1 || useradd -m -u 1000 -s /bin/bash "$U"
passwd -l "$U" >/dev/null                       # no password login; no sudo membership
for g in sudo admin; do gpasswd -d "$U" "$g" >/dev/null 2>&1 || true; done

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg uidmap dbus-user-session slirp4netns \
  age git make sqlite3 python3 jq nano rsync >/dev/null

# Docker from Docker's apt repository (no curl | sh)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $VERSION_CODENAME stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin docker-ce-rootless-extras >/dev/null
systemctl disable --now docker.service docker.socket >/dev/null 2>&1 || true
loginctl enable-linger "$U"

# sops, pinned, checksum-verified
cd /tmp
# (the checksum list covers the static binaries, not the .deb)
curl -fsSLO "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.amd64"
curl -fsSLO "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.checksums.txt"
grep " sops-v${SOPS_VERSION}.linux.amd64\$" "sops-v${SOPS_VERSION}.checksums.txt" | sha256sum -c -
install -m 0755 "sops-v${SOPS_VERSION}.linux.amd64" /usr/local/bin/sops

# Lock WSL down: no automatic Windows drives, no Windows interop, systemd on
cat > /etc/wsl.conf <<EOF
[boot]
systemd=true
[automount]
enabled=false
mountFsTab=true
[interop]
enabled=false
appendWindowsPath=false
[user]
default=$U
EOF

mkdir -p /srv/vault /srv/win-exports /srv/ai/bulk /srv/ai/state
chown -R "$U:$U" /srv/ai
grep -q '/srv/vault ' /etc/fstab || cat >> /etc/fstab <<EOF
$VAULT_WIN   /srv/vault       drvfs rw,noatime,uid=1000,gid=1000,metadata 0 0
$EXPORTS_WIN /srv/win-exports drvfs ro,noatime,uid=1000,gid=1000 0 0
EOF

# Stage files into owner's home
install -d -o "$U" -g "$U" /home/$U/ai-stack /home/$U/code /home/$U/.ssh /home/$U/restore
cp -rn "$STAGE/." /home/$U/ai-stack/
for f in "$STAGE"/../*.tar.gz.age; do [ -f "$f" ] && cp "$f" /home/$U/restore/; done
if [ -f "$STAGE/../age-key.txt" ]; then
  install -d -m 700 -o "$U" -g "$U" /home/$U/.config /home/$U/.config/sops /home/$U/.config/sops/age
  install -m 600 -o "$U" -g "$U" "$STAGE/../age-key.txt" /home/$U/.config/sops/age/keys.txt
fi
if [ -f /mnt/c/Users/Owner/.ssh/id_ed25519_forgejo ] && [ -z "${REHEARSAL:-}" ]; then
  cp /mnt/c/Users/Owner/.ssh/id_ed25519_forgejo /mnt/c/Users/Owner/.ssh/id_ed25519_forgejo.pub /home/$U/.ssh/
  chmod 600 /home/$U/.ssh/id_ed25519_forgejo
fi
cat > /home/$U/.ssh/config <<'EOF'
Host forgejo
  HostName 192.168.1.80
  Port 2222
  User git
  IdentityFile ~/.ssh/id_ed25519_forgejo
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chown -R "$U:$U" /home/$U
chmod 700 /home/$U/.ssh; chmod 600 /home/$U/.ssh/config

echo "STAGE1_DONE: now run 'wsl --shutdown', then stage 2 (first install: bootstrap-wsl-2-user.sh; new PC: new-machine.sh)"
