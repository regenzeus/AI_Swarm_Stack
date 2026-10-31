#!/usr/bin/env bash
# Keep code graphs current: for every git repo in ~/code whose HEAD moved since its last graph, re-extract
# (tree-sitter, offline, no LLM), then rebuild the merged cross-repo graph the MCP server serves.
# The server hot-reloads graph.json on change. Runs every 60 s from a systemd user timer.
set -uo pipefail
CODE=/home/owner/code; STATE=/srv/ai/state/graphify; mkdir -p "$STATE" "$CODE/.graphify"
exec 9>"$STATE/lock"; flock -n 9 || exit 0
G="docker run --rm --network none -v $CODE:/code aistack/graphify:0.9.85"
# ai-stack itself is studied through a mirror clone in ~/code (graph, code map; never built from): keep it level with the
# live checkout. The builder works on its own clone, so this one only ever fast-forwards.
[ -d "$CODE/ai-stack/.git" ] || git clone -q /home/owner/ai-stack "$CODE/ai-stack"
git -C "$CODE/ai-stack" pull -q --ff-only 2>/dev/null || true
changed=0
for repo in "$CODE"/*/; do
  name=$(basename "$repo"); [ -d "$repo/.git" ] || continue
  # graphify-out/ is this tool's output, not the project: out of git status, or the code map viewer counts its cache
  # files as "working-tree changes" and warns that the map is out of date
  grep -qx "graphify-out/" "$repo/.git/info/exclude" 2>/dev/null || echo "graphify-out/" >> "$repo/.git/info/exclude"
  head=$(git -C "$repo" rev-parse HEAD 2>/dev/null) || continue
  [ "$(cat "$STATE/$name.head" 2>/dev/null)" = "$head" ] && [ -f "$repo/graphify-out/graph.json" ] && continue
  [ "$(cat "$STATE/$name.failed" 2>/dev/null)" = "$head" ] && continue          # failed at this commit: try again at the next one
  # An update reads the old graph: when it cannot (no graph yet, or a graph.json broken by a crash, as ai-stack's was on
  # 2026-10-30 and then failed silently every minute for hours), the graph is built anew from the code.
  gj="$repo/graphify-out/graph.json"
  if [ -f "$gj" ] && ! python3 -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$gj" 2>/dev/null; then
    mv "$gj" "$gj.broken-$(date +%F-%H%M)"                   # an extract reads it too: set aside (kept), so the next one starts clean
    echo "$(date '+%F %T') graph.json of $name unreadable: kept as $(basename "$gj").broken-$(date +%F-%H%M), building it anew" >&2
  fi
  if { [ -f "$gj" ] && $G graphify update "/code/$name" >/dev/null 2>&1; } \
     || $G graphify extract "/code/$name" --code-only >/dev/null 2>&1; then
    echo "$head" > "$STATE/$name.head"; rm -f "$STATE/$name.failed"; changed=1; echo "$(date '+%F %T') graph updated: $name @ ${head:0:7}"
  else
    echo "$head" > "$STATE/$name.failed"; echo "$(date '+%F %T') graph FAILED: $name @ ${head:0:7} (update and rebuild; next try at its next commit)" >&2
  fi
done
if [ "$changed" = 1 ] || [ ! -f "$CODE/.graphify/merged-graph.json" ]; then
  graphs=$(for g in "$CODE"/*/graphify-out/graph.json; do echo "/code/${g#$CODE/}"; done)
  $G graphify merge-graphs $graphs --out /code/.graphify/merged-graph.json >/dev/null 2>&1 \
    && python3 /home/owner/ai-stack/ops/graph_repos.py "$CODE/.graphify/merged-graph.json" >/dev/null \
    && echo "$(date '+%F %T') merged graph rebuilt ($(echo $graphs | wc -w) repos)"
fi
