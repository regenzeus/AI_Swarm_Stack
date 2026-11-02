#!/usr/bin/env bash
# Vault ingest: one inbox file at a time, deterministic steps around one curator run.
# Runs from a systemd user timer (every 60 s) or by hand: ops/vault-ingest.sh
set -uo pipefail
V=/srv/vault
INBOX=$V/raw/_inbox
LOG=/srv/ai/state/vault-ingest.log
exec 9>/srv/ai/state/vault-ingest.lock; flock -n 9 || exit 0      # one run at a time
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
notify() { "$(dirname "$0")/notify.sh" "$1" >/dev/null 2>&1 || true; }      # the one notification path (OBS-16)

shopt -s nullglob
for f in "$INBOX"/*; do
  name=$(basename "$f")
  case "$name" in .gitkeep|~\$*|*.tmp|.~lock*|*.swp|*.part|*.crdownload) continue;; esac
  [ $(( $(date +%s) - $(stat -c %Y "$f") )) -lt 5 ] && continue     # still being written
  stem="${name%.*}"; ext="${name##*.}"; ext="${ext,,}"
  dest="$V/raw/articles/$stem.md"
  [ -e "$dest" ] && dest="$V/raw/articles/$stem-$(date +%Y%m%d%H%M%S).md"
  case "$ext" in
    md|markdown|txt) mv "$f" "$dest" ;;
    pdf|docx|pptx|xlsx|html|htm|msg|rst|epub)
      mkdir -p "$V/raw/_files"
      if docker run --rm --network none -v "$INBOX":/in:ro aistack/tools:1 markitdown "/in/$name" > "$dest.tmp" 2>/dev/null && [ -s "$dest.tmp" ]; then
        { printf -- '---\nsource_file: raw/_files/%s\nconverter: markitdown@0.1.9\nconverted: %s\n---\n\n' "$name" "$(date +%F)"; cat "$dest.tmp"; } > "$dest"
        rm -f "$dest.tmp"; mv "$f" "$V/raw/_files/$name"
      else
        rm -f "$dest.tmp"; log "convert failed: $name"; notify "Ingest: could not convert $name (left in _inbox)"; continue
      fi ;;
    *) log "skip unsupported: $name"; continue ;;
  esac
  rel="raw/articles/$(basename "$dest")"
  log "ingest start: $rel"
  prompt=$(python3 "$(dirname "$0")/prompts.py" render curator INGEST time="$(date "+%Y-%m-%d %H:%M")" rel="$rel")   # MEM-11: prompts/curator.md
  out=$(docker exec -u hermes -w /vault aistack-hermes-1 hermes -p curator -z "$prompt" 2>&1)
  pages=$(echo "$out" | grep -oE 'PAGES:.*' | tail -1)
  # Guard: every wiki page must end in .md (a model once named the qmd page "qmd", reading "md" as the extension)
  find "$V/wiki" -type f ! -name "*.md" ! -name ".gitkeep" | while read -r bad; do mv "$bad" "$bad.md"; log "renamed to .md: ${bad#$V/}"; done
  cd "$V" && git add -A && git commit -qm "ingest: $(basename "$dest")" -m "${pages:-PAGES: (none reported)}" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push -q 2>/dev/null
  docker exec aistack-qmd-1 sh -c 'qmd update >/dev/null 2>&1 && qmd embed >/dev/null 2>&1' || log "qmd reindex failed"
  n=$(git -C "$V" show --stat --format= HEAD | grep -c "wiki/")
  "$(dirname "$0")/private-terms.sh" || log "private-terms refresh failed"
  log "ingest done: $rel ($n wiki files) ${pages:-}"
  notify "Vault: ingested $(basename "$dest") - $n wiki pages written or updated."
done
