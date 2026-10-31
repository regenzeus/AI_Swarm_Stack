#!/usr/bin/env bash
# Phase 0 Kanban probe (docs/SWARM-PHASE0.md): create a task twice with one idempotency key, comment, complete,
# read task_events read-only inside the Hermes container, then archive the probe board. No profile runs.
set -euo pipefail
H() { docker exec -u hermes aistack-hermes-1 hermes kanban "$@"; }
B=(--board swarm-probe)
H boards create swarm-probe >/dev/null
trap 'H boards rm swarm-probe >/dev/null 2>&1 || true' EXIT
mk() { H "${B[@]}" create "probe: idea detector:partial-read" --assignee scout --idempotency-key idea:detector:partial-read \
  --created-by swarm-probe --initial-status blocked --json | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])'; }
first=$(mk); second=$(mk)
echo "idempotent create: $([ "$first" = "$second" ] && echo yes || echo NO) ($first, $second)"
H "${B[@]}" comment "$first" "evidence: probe comment from outside Hermes" >/dev/null
H "${B[@]}" dispatch --dry-run --json | python3 -c 'import sys,json; print("dry-run spawned:", json.load(sys.stdin)["spawned"])'
H "${B[@]}" complete "$first" --result "probe done" >/dev/null
docker exec -i -u hermes aistack-hermes-1 python3 - <<'EOF'
import sqlite3
c = sqlite3.connect("file:/opt/data/kanban/boards/swarm-probe/kanban.db?mode=ro", uri=True)
rows = c.execute("select id, kind, payload from task_events order by id").fetchall()
print("events readable from outside:", [(i, k) for i, k, _ in rows], "journal:", c.execute("pragma journal_mode").fetchone()[0])
EOF
