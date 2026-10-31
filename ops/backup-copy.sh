#!/usr/bin/env bash
# Copy /srv/ai into the backup's staging folder (ops/backup.sh). PLT-13: a file the backup user cannot read (a file a
# container wrote under its own user, the AI phone's ADB key) is skipped and named in the log instead of failing the
# whole backup; any other copy error still fails it.   Usage: ops/backup-copy.sh <source/> <destination/>
# Not copied: the backup outbox, the AI phone's pairing key (paired again after a restore), workbench/ (scratch
# copies of repositories for builds and Claude tasks, made again from git), and the live swarm database files (its
# hourly snapshot is copied instead).
set -uo pipefail
src=$1; dest=$2
err=$(mktemp); trap 'rm -f "$err"' EXIT
rsync -a --exclude backup-outbox --exclude phone/home --exclude workbench --exclude 'swarm/swarm.db*' --exclude swarm/runner.sock \
  "$src" "$dest" 2>"$err"
rc=$?
if [ "$rc" -eq 23 ] && ! grep -v -E 'Permission denied \(13\)|some files/attrs were not transferred' "$err" | grep -q .; then
  echo "backup: skipped $(grep -c 'Permission denied (13)' "$err") file(s) the backup user cannot read:"
  grep 'Permission denied (13)' "$err" | sed 's/^/  /'
  exit 0
fi
[ "$rc" -eq 0 ] || cat "$err" >&2
exit "$rc"
