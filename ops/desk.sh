#!/usr/bin/env bash
# Topic Desk: one briefing per focus topic (topics/<slug>/TOPIC.md). Scheduled by Mission Control (ops/missions.py,
# missions/<slug>/MISSION.md); without a slug it runs every topic whose mission is active. Runs the desk container,
# files the briefing into the workbook (topics/<slug>/reports/YYYY/MM/YYYY-MM-DD.md), commits the vault, re-indexes
# search, sends the short version to Telegram (DESK_TELEGRAM=0: not).
#   ops/desk.sh [slug] [--date YYYY-MM-DD]       (needs VK_DESK and SEC_CONTACT: run via make desk / Mission Control)
set -uo pipefail
PROMPTS="$(cd "$(dirname "$0")/.." && pwd)/prompts"     # prompts/desk.md, mounted read-only (MEM-13)
export DOCKER_HOST=${DOCKER_HOST:-unix:///run/user/1000/docker.sock}
V=/srv/vault; ONLY=${1:-}; DATE=$(date +%F)
[ "${2:-}" = "--date" ] && DATE=$3
notify() { [ "${DESK_TELEGRAM:-1}" = 0 ] || NOTIFY_CATEGORY=result "$(dirname "$0")/notify.sh" "$1" >/dev/null 2>&1 || true; }

for t in "$V"/topics/*/TOPIC.md; do
  slug=$(basename "$(dirname "$t")")
  [ -n "$ONLY" ] && [ "$ONLY" != "$slug" ] && continue
  m="$V/missions/$slug/MISSION.md"
  [ -z "$ONLY" ] && [ -f "$m" ] && ! grep -q '^status: active' "$m" && continue   # paused or archived
  S=/srv/ai/desk/$slug; mkdir -p "$S/state" "$S/out"
  docker run --rm -u 0 -v "$S":/d alpine sh -c "chown 0:0 /d; chown -R 10005 /d/state /d/out"   # container writes only these
  if ! docker run --rm --network aistack_webonly -e VK_DESK -e SEC_CONTACT -v "$V/topics/$slug":/topic:ro -v "$S/state":/state \
       -v "$S/out":/out -v "$PROMPTS":/prompts:ro aistack/desk:1 --topic /topic --state /state --out /out --date "$DATE" 2>"$S/last.log"; then
    notify "Topic Desk ($slug): the briefing for $DATE failed. $(tail -1 "$S/last.log")"
    continue
  fi
  python3 "$(dirname "$0")/prompts.py" keep "$S/out/prompt-cases.jsonl" || true   # the run's calls become replay cases (MEM-11)
  dest="topics/$slug/reports/${DATE:0:4}/${DATE:5:2}/$DATE.md"
  if ! { docker exec -u hermes aistack-hermes-1 mkdir -p "/vault/$(dirname "$dest")" &&
         docker exec -i -u hermes aistack-hermes-1 sh -c "cat > /vault/$dest" < "$S/out/$DATE.md"; }; then
    notify "Topic Desk ($slug): the briefing for $DATE was written but could not be filed into the vault ($dest)."
    echo "$(date '+%F %T') $slug $DATE NOT filed: $dest"
    continue
  fi
  ( cd "$V" && git add "topics/$slug" && git commit -qm "desk: $slug briefing $DATE" \
      -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" && git push -q 2>/dev/null ) || true
  docker exec aistack-qmd-1 sh -c 'qmd update >/dev/null 2>&1 && qmd embed >/dev/null 2>&1' || true
  topic=$(grep -m1 '^topic:' "$t" | cut -d: -f2- | xargs)
  notify "$topic · $(date -d "$DATE" +%d.%m.%Y)
$(cat "$S/out/$DATE.telegram.txt")

Full report with sources: Obsidian, $dest. Ask me about it right here."
  echo "$(date '+%F %T') $slug $DATE filed: $dest $(grep -m1 '^stats:' "$S/out/$DATE.md")"
done
