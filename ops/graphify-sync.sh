#!/usr/bin/env bash
# Keep code graphs current: for every git repo in ~/code whose HEAD moved since its last graph, re-extract
# (tree-sitter, offline, no LLM), then rebuild the merged cross-repo graph the MCP server serves.
# The server hot-reloads graph.json on change. Runs every 60 s from a systemd user timer.
set -uo pipefail
eval "$(python3 "$(dirname "$0")/deployment.py" shell)"   # this deployment's hosts and paths (config/deployment.env)
CODE=$CODE_DIR; STATE=/srv/ai/state/graphify; mkdir -p "$STATE" "$CODE/.graphify"
exec 9>"$STATE/lock"; flock -n 9 || exit 0
G="docker run --rm --network none -v $CODE:/code aistack/graphify:0.9.85"
# ai-stack itself is studied through a mirror clone in ~/code (graph, code map; never built from): keep it level with the
# live checkout. The builder works on its own clone, so this one only ever fast-forwards.
[ -d "$CODE/ai-stack/.git" ] || git clone -q "$STACK_DIR" "$CODE/ai-stack"
git -C "$CODE/ai-stack" pull -q --ff-only 2>/dev/null || true
changed=0
for repo in "$CODE"/*/; do
  name=$(basename "$repo"); [ -d "$repo/.git" ] || continue
  # graphify-out/ is this tool's output, not the project: out of git status, or the code map viewer counts its cache
  # files as "working-tree changes" and warns that the map is out of date
  grep -qx "graphify-out/" "$repo/.git/info/exclude" 2>/dev/null || echo "graphify-out/" >> "$repo/.git/info/exclude"
  head=$(git -C "$repo" rev-parse HEAD 2>/dev/null) || continue
  [ "$(cat "$STATE/$name.head" 2>/dev/null)" = "$head" ] && { [ -f "$repo/graphify-out/graph.json" ] || [ -f "$repo/graphify-out/.no-code" ]; } && continue
  [ "$(cat "$STATE/$name.failed" 2>/dev/null)" = "$head" ] && continue          # failed at this commit: try again at the next one
  # An update reads the old graph: when it cannot (no graph yet, or a graph.json broken by a crash, as ai-stack's was on
  # 2026-10-30 and then failed silently every minute for hours), the graph is built anew from the code.
  gj="$repo/graphify-out/graph.json"
  if [ -f "$gj" ] && ! python3 -c 'import json, sys; json.load(open(sys.argv[1], encoding="utf-8"))' "$gj" 2>/dev/null; then
    mv "$gj" "$gj.broken-$(date +%F-%H%M)"                   # an extract reads it too: set aside (kept), so the next one starts clean
    echo "$(date '+%F %T') graph.json of $name unreadable: kept as $(basename "$gj").broken-$(date +%F-%H%M), building it anew" >&2
  fi
  said=$(mktemp)
  if { [ -f "$gj" ] && $G graphify update "/code/$name" >/dev/null 2>&1; } \
     || $G graphify extract "/code/$name" --code-only >"$said" 2>&1; then
    echo "$head" > "$STATE/$name.head"; rm -f "$STATE/$name.failed" "$repo/graphify-out/.no-code"; changed=1; echo "$(date '+%F %T') graph updated: $name @ ${head:0:7}"   # cap: id (a short commit hash)
  elif grep -q "graph is empty" "$said"; then    # only web pages or documents: nothing for this tool to read, which is no failure
    echo "$head" > "$STATE/$name.head"; rm -f "$STATE/$name.failed"; mkdir -p "$repo/graphify-out"; touch "$repo/graphify-out/.no-code"
    echo "$(date '+%F %T') no code to graph: $name @ ${head:0:7}"   # cap: id (a short commit hash)
  else
    echo "$head" > "$STATE/$name.failed"; echo "$(date '+%F %T') graph FAILED: $name @ ${head:0:7} (update and rebuild; next try at its next commit)" >&2   # cap: id (a short commit hash)
  fi
  rm -f "$said"
done
if [ "$changed" = 1 ] || [ ! -f "$CODE/.graphify/merged-graph.json" ]; then
  graphs=$(for g in "$CODE"/*/graphify-out/graph.json; do echo "/code/${g#$CODE/}"; done)
  $G graphify merge-graphs $graphs --out /code/.graphify/merged-graph.json >/dev/null 2>&1 \
    && python3 "$STACK_DIR/ops/graph_repos.py" "$CODE/.graphify/merged-graph.json" >/dev/null \
    && echo "$(date '+%F %T') merged graph rebuilt ($(echo $graphs | wc -w) repos)"
fi
