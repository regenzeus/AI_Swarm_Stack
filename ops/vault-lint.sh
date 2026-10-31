#!/usr/bin/env bash
# Vault lint (weekly from ops/curate.py, or by hand). Step 1 is deterministic: ops/vault_check.py --fix repairs
# index entries and file names and lists broken links, orphans and frontmatter errors. Step 2 is one curator pass
# for the judgement calls only (contradictions, missing concept pages, misfiled pages). Committed, then reported.
set -uo pipefail
V=/srv/vault
exec 9>/srv/ai/state/vault-ingest.lock; flock 9            # never run alongside an ingest
check=$(docker exec -i -u hermes -e VAULT=/vault aistack-hermes-1 /opt/hermes/.venv/bin/python - --fix < "$(dirname "$0")/vault_check.py" 2>&1)
prompt=$(python3 "$(dirname "$0")/prompts.py" render curator LINT time="$(date '+%Y-%m-%d %H:%M')" check="$check")   # MEM-11: prompts/curator.md
out=$(docker exec -u hermes -w /vault aistack-hermes-1 hermes -p curator -z "$prompt" 2>&1 | tail -60)
report=$(echo "$out" | sed -n '/REPORT:/,$p')
find "$V/wiki" -type f ! -name "*.md" ! -name ".gitkeep" -exec sh -c 'mv "$1" "$1.md"' _ {} \;
cd "$V" && git add -A && git commit -qm "lint: $(date +%F)" -m "${report:-REPORT: (none)}" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push -q 2>/dev/null
docker exec aistack-qmd-1 sh -c 'qmd update >/dev/null 2>&1 && qmd embed >/dev/null 2>&1' || true
echo "$check"; echo "${report:-$out}"
docker exec -u hermes aistack-hermes-1 sh -c 'hermes send -t "telegram:$TELEGRAM_ALLOWED_USERS" "$0"' "Vault lint $(date +%F):
${report:-no report}" >/dev/null 2>&1 || true
