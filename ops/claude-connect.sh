#!/usr/bin/env bash
# Connect the builder's Claude Code engine to your Claude subscription, in one go (make claude-connect):
#   1. sign in: Claude Code's setup-token flow in a throwaway container (you open the link, sign in, paste the code back)
#   2. you paste the token it prints; it is read hidden, never shown or logged
#   3. it is saved encrypted into secrets/secrets.enc.yaml (sops set) and the runner restarts to pick it up
# Run it again to replace the token (for example after revoking it on claude.ai).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Step 1 of 2: sign in to Claude (a link appears; open it, sign in, paste the code back here)."
docker run --rm -it --entrypoint claude -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 aistack/builder:1 setup-token
echo
echo "Step 2 of 2: paste the token shown above (it starts with sk-ant-oat). It stays hidden while you paste."
read -rs -p "Token: " token; echo
token=$(printf '%s' "$token" | tr -d '[:space:]')
case "$token" in
  sk-ant-*) ;;
  *) echo "That does not look like a Claude token (it should start with sk-ant-). Nothing was saved." >&2; exit 1 ;;
esac
printf '"%s"' "$token" | sops set --value-stdin secrets/secrets.enc.yaml '["CLAUDE_CODE_OAUTH_TOKEN"]'   # never on a command line
unset token
echo "Saved (encrypted). Restarting the Mission Control runner so it can use it..."
systemctl --user restart missions.service
echo "Done. In Mission Control, Code -> New build -> Engine: Claude Code."
