#!/usr/bin/env bash
# Keep code graphs current: for every git repo in ~/code whose HEAD moved since its last graph, re-extract
# (tree-sitter, offline, no LLM), then rebuild the merged cross-repo graph the MCP server serves, but only when what goes
# into it changed: a graph's content (its build stamp aside) or the set of graphs (BLD-40). The merge runs under a memory
# cap. The server hot-reloads graph.json on change. Run every minute by its n8n workflow (crew-code-graph) and by onboarding.
set -uo pipefail
eval "$(python3 "$(dirname "$0")/deployment.py" shell)"   # this deployment's hosts and paths (deployments/<name>/deployment.env)
CODE=$CODE_DIR; STATE=${GRAPHIFY_STATE:-/srv/ai/state/graphify}; mkdir -p "$STATE" "$CODE/.graphify"
exec 9>"$STATE/lock"; flock -n 9 || exit 0
G="docker run --rm --network none -v $CODE:/code aistack/graphify:0.9.85"
# The merge holds every graph at once: 3 GB on 10 Nov 2026, in an unlimited container, while WSL ran out of memory and
# restarted (review O9). The owner approved a cap (11 Nov 2026); docs/LIMITS.md has it. Measured 11 Nov 2026 on the 16
# graphs then in ~/code (621 MB): the merge 3,153 MB at most (83 s), graph_repos.py 2,441 MB (34 s); so a merge goes a
# little into swap and is ended only near twice what it needs.
# limit: stops, the merge may use 3 GB of RAM and 3 GB of swap and is ended beyond; WSL died under an unlimited one (review O9)
MERGE_MEM=3g; MERGE_SWAP=6g
M="docker run --rm --network none --memory $MERGE_MEM --memory-swap $MERGE_SWAP -v $CODE:/code -v $STACK_DIR/ops/graph_repos.py:/opt/graph_repos.py:ro aistack/graphify:0.9.85"
MERGED=$CODE/.graphify/merged-graph.json
# A graph's content without its build stamp: built_at_commit moves with every commit, also one that changes no code (a
# docs commit pulled into the ai-stack mirror), and the rest of a graph is the same for the same code (three builds of
# one sympy commit on 8-9 Nov: equal but for the stamp).
gsum() { python3 -c 'import hashlib, re, sys; print(hashlib.sha256(re.sub(rb"\"built_at_commit\":\s*\"[^\"]*\"", b"", open(sys.argv[1], "rb").read())).hexdigest())' "$1"; }
# ai-stack itself is studied through a mirror clone in ~/code (graph, code map; never built from): keep it level with the
# live checkout. The builder works on its own clone, so this one only ever fast-forwards.
[ -d "$CODE/ai-stack/.git" ] || git clone -q "$STACK_DIR" "$CODE/ai-stack"
git -C "$CODE/ai-stack" pull -q --ff-only 2>/dev/null || true
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
    echo "$head" > "$STATE/$name.head"; rm -f "$STATE/$name.failed" "$repo/graphify-out/.no-code"
    sum=$(gsum "$gj")
    if [ "$sum" = "$(cat "$STATE/$name.sum" 2>/dev/null)" ]; then
      echo "$(date '+%F %T') graph unchanged: $name @ ${head:0:7} (the same code graph, no merge for it)"   # cap: id (a short commit hash)
    else
      echo "$sum" > "$STATE/$name.sum"; echo "$(date '+%F %T') graph updated: $name @ ${head:0:7}"   # cap: id (a short commit hash)
    fi
  elif grep -q "graph is empty" "$said"; then    # only web pages or documents: nothing for this tool to read, which is no failure
    echo "$head" > "$STATE/$name.head"; rm -f "$STATE/$name.failed"; mkdir -p "$repo/graphify-out"; touch "$repo/graphify-out/.no-code"
    echo "$(date '+%F %T') no code to graph: $name @ ${head:0:7}"   # cap: id (a short commit hash)
  else
    echo "$head" > "$STATE/$name.failed"; echo "$(date '+%F %T') graph FAILED: $name @ ${head:0:7} (update and rebuild; next try at its next commit)" >&2   # cap: id (a short commit hash)
  fi
  rm -f "$said"
done
# What goes into the merge: every graph by name and content. A repository removed from ~/code changes it too.
graphs=(); inputs=""
for g in "$CODE"/*/graphify-out/graph.json; do
  [ -f "$g" ] || continue
  name=$(basename "$(dirname "$(dirname "$g")")")
  [ -s "$STATE/$name.sum" ] || gsum "$g" > "$STATE/$name.sum"      # a graph made before the sums were kept: once
  graphs+=("/code/$name/graphify-out/graph.json"); inputs+="$name $(cat "$STATE/$name.sum")"$'\n'
done
[ ${#graphs[@]} -gt 0 ] || exit 0
want=$(printf '%s' "$inputs" | sha256sum | cut -d' ' -f1)
[ -f "$MERGED" ] && [ "$want" = "$(cat "$STATE/merged.inputs" 2>/dev/null)" ] && exit 0     # the merged graph is of these already
[ "$want" = "$(cat "$STATE/merged.failed" 2>/dev/null)" ] && exit 0      # these failed to merge: try again when a graph changes
# Merged into a file of its own and moved over the served one only when whole: a merge ended at its cap leaves the old one.
if $M graphify merge-graphs "${graphs[@]}" --out /code/.graphify/merged-graph.next.json >/dev/null 2>"$STATE/merge.err" \
   && $M python3 /opt/graph_repos.py /code/.graphify/merged-graph.next.json >/dev/null 2>>"$STATE/merge.err" \
   && mv "$CODE/.graphify/merged-graph.next.json" "$MERGED"; then
  echo "$want" > "$STATE/merged.inputs"; rm -f "$STATE/merged.failed"
  echo "$(date '+%F %T') merged graph rebuilt (${#graphs[@]} repos)"
else
  rc=$?; echo "$want" > "$STATE/merged.failed"; rm -f "$CODE/.graphify/merged-graph.next.json"
  why=$([ "$rc" = 137 ] && echo "ended at its memory cap of $MERGE_MEM RAM and $MERGE_SWAP with swap" || echo "exit $rc")
  echo "$(date '+%F %T') merged graph FAILED ($why; the old one is still served; next try when a graph changes): $(cat "$STATE/merge.err")" >&2
  exit 1
fi
