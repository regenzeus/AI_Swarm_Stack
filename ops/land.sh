#!/usr/bin/env bash
# Land an owner-supervised session's branch on main the way a build lands (BLD-20, FND-04):
#   bash ops/land.sh <branch> "<the owner's approval, e.g. chat 2026-10-29: implement all now>"
# 1. the checks (ops/check.sh, in the builder's image) on the exact commit that lands; any failure stops here
# 2. the land lock, fast-forward main to the branch, push
# 3. ops/deploy.py (which takes the deploy lock and records the deploy with its source)
# 4. the runner restarts when the deploy says so: at once when no run is going, otherwise as soon as it is idle
# 5. one activity event ("Session deploy …", with the approval) so Mission Control shows what shipped and why
#   bash ops/land.sh --restart-runner-when-idle      (internal: step 4's wait, started through systemd-run)
set -uo pipefail
REPO=${AISTACK:-$HOME/ai-stack}          # the live checkout: the branch is landed there, wherever this script runs from
cd "$REPO" || exit 2
EVENTS=/srv/ai/missions/public/events.jsonl
DB=/srv/ai/missions/missions.sqlite

running() { sqlite3 "$DB" "select count(*) from runs where status='running'" 2>/dev/null || echo 0; }

if [ "${1:-}" = "--restart-runner-when-idle" ]; then
  for _ in $(seq 1 120); do                      # up to 2 hours
    if [ "$(running)" = "0" ]; then systemctl --user restart missions.service; echo "runner restarted"; exit 0; fi
    sleep 60
  done
  echo "runner still busy after 2 h: not restarted" >&2; exit 1
fi

BRANCH=${1:?usage: ops/land.sh <branch> "<owner approval>"}
APPROVAL=${2:?name the owner\'s approval (where and when he approved it)}
git rev-parse -q --verify "refs/heads/$BRANCH" >/dev/null || { echo "no branch $BRANCH" >&2; exit 2; }
TIP=$(git rev-parse "refs/heads/$BRANCH")

echo "== checks on $BRANCH (${TIP:0:8})"
LOG=$(mktemp)
if ! git archive --format=tar "$TIP" | docker exec -i aistack-builder-1 sh -c \
    'rm -rf /tmp/land && mkdir -p /tmp/land && tar -xf - -C /tmp/land && cd /tmp/land && PATH=/opt/tools/bin:$PATH PYTEST=/opt/tools/bin/pytest bash ops/check.sh' >"$LOG" 2>&1 \
   || ! grep -q "ALL CHECKS PASSED" "$LOG"; then
  grep -E "FAILED|failed|^E " "$LOG" | tail -15
  echo "NOT LANDED: the checks failed (full log: $LOG)" >&2
  exit 1
fi
grep -E "passed in|ALL CHECKS" "$LOG" | tail -2

export LAND_TIP=$TIP LAND_BRANCH=$BRANCH
OUT=$(flock ~/.aistack-land.lock bash -c '
  set -e
  git pull -q --ff-only origin main
  OLD=$(git rev-parse HEAD)
  git merge -q --ff-only "$LAND_TIP"
  NEW=$(git rev-parse HEAD)
  git push -q origin main
  echo "LANDED $OLD $NEW"
  DEPLOY_SOURCE=session sops exec-env secrets/secrets.enc.yaml "sops exec-env secrets/agent-keys.enc.yaml \"python3 ops/deploy.py $OLD $NEW\""
' 2>&1)
rc=$?
echo "$OUT" | grep -E "LANDED|passed, |FAIL|DEPLOY|RESTART_RUNNER|health" | tail -8
read -r _ OLD NEW <<<"$(echo "$OUT" | grep '^LANDED' | tail -1)"
[ -n "${NEW:-}" ] || { echo "NOT LANDED: merge or push failed" >&2; exit 1; }

if echo "$OUT" | grep -q RESTART_RUNNER; then
  if [ "$(running)" = "0" ]; then
    systemctl --user restart missions.service && echo "runner restarted"
  else
    systemd-run --user --quiet --unit="runner-restart-$(date +%s)" bash "$REPO/ops/land.sh" --restart-runner-when-idle
    echo "runner restarts when its current run ends"
  fi
fi

SUBJECT=$(git log -1 --format=%s "$NEW")
OK=$([ $rc -eq 0 ] && echo "deployed" || echo "DEPLOY FAILED")
python3 - "$EVENTS" "$OLD" "$NEW" "$SUBJECT" "$APPROVAL" "$OK" <<'EOF'
import datetime, json, sys
path, old, new, subject, approval, ok = sys.argv[1:]
e = {"ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "kind": "deploy", "slug": "", "title": "Session deploy",
     "text": f"{ok}: {subject} ({old[:8]}..{new[:8]}) · approved: {approval}", "push": ok != "deployed"}
with open(path, "a") as f:
    f.write(json.dumps(e, ensure_ascii=False) + "\n")
EOF
echo "$OK $OLD..$NEW"
exit $rc
