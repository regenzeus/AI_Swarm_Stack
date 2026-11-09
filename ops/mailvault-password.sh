#!/usr/bin/env bash
# The mail copy's own Gmail app password, typed by the owner: it goes straight to the NAS (secret/, mode 700) and is never
# stored here, logged or shown. Its own password, so that it can be revoked alone. Run through make mailvault-password.
set -euo pipefail
DIR=/volume1/docker/mailvault/secret
[ -n "${GMAIL_ADDRESS:-}" ] || { echo "GMAIL_ADDRESS is not set: run make mailvault-password" >&2; exit 2; }
cat <<'EOT'
1. Open https://myaccount.google.com/apppasswords
2. Create an app password named "NAS mail copy".
3. Paste it here (nothing shows while you type) and press Enter.
EOT
read -r -s -p "App password: " pw; echo
pw=${pw// /}                                 # Google shows it in four groups
[ ${#pw} -ge 16 ] || { echo "That does not look like an app password (16 letters). Nothing was saved." >&2; exit 1; }   # limit: refuses, a Gmail app password has 16 letters
ssh synology "mkdir -p $DIR && chmod 700 $DIR && umask 077 && cat > $DIR/password" <<<"$pw"
ssh synology "umask 077 && cat > $DIR/address" <<<"$GMAIL_ADDRESS"
unset pw
ssh synology "sudo -n /usr/local/bin/docker restart mailvault >/dev/null"
sleep 25
ssh synology "cat /volume1/docker/mailvault/data/status.json" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("The copy says:", d["state"], d["why"], f"({d[\"copied\"]} of {d[\"total\"]} copied)")'
