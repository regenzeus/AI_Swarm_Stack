#!/usr/bin/env bash
# Restore a backup made by ops/backup.sh.
#   ops/restore.sh drill [FILE]   default; nothing on this machine changes: fetch + decrypt, verify checksums,
#                                 load the postgres dump into a throwaway container, unpack the volumes into
#                                 throwaway drill_* volumes and open every SQLite file in them. Weekly timer.
#   ops/restore.sh apply [FILE]   put it back on this machine (new PC: after bootstrap + `make up`). Stops the
#                                 stack, replaces volumes, postgres, /srv/ai, the vault and the home folders.
# FILE = name on the NAS (default: newest). Decrypting needs ~/.config/sops/age/keys.txt; on a new machine copy it
# from the NAS first: ssh synology cat .ai-stack/age-key.txt > ~/.config/sops/age/keys.txt
set -euo pipefail
ALPINE_IMAGE=${ALPINE_IMAGE:-$(grep -m1 "^ALPINE_IMAGE=" "$(dirname "$0")/../versions.env" | cut -d= -f2-)}   # pinned (review OPS-R9)
eval "$(python3 "$(dirname "$0")/deployment.py" shell)"   # this deployment's hosts and paths (deployments/<name>/deployment.env)
export DOCKER_HOST=${DOCKER_HOST:-$DOCKER_SOCKET}
MODE=${1:-drill}; DEST=/volume1/docker/ai-backup
# the home stack's backups: on a deployment without the home feature the drill steps aside and a restore is refused, before
# anything is read or replaced (GEN-20; a work site, 9 Nov 2026, kept a local commit of its own to stop them)
if ! python3 "$(dirname "$0")/deployment.py" need home >/dev/null; then
  [ "$MODE" = drill ] && { echo "not configured: the restore drill needs the home feature"; exit 0; }
  echo "refused: ops/restore.sh puts the home stack's backup back, and this deployment has no home feature" >&2; exit 1
fi
FILE=${2:-$(ssh synology "cd $DEST && ls -1t aistack-*.tar.gz.age | head -1")}
VOLS="hermes-home litellm-auth openwebui qmd-data opencode-data"
W=$(mktemp -d); trap 'docker rm -f "drill-pg-$$" "drill-hs-$$" >/dev/null 2>&1; rm -rf "$W"' EXIT   # an abort leaves no drill container (OPS-R13)
# psql's errors other than "already exists" (a fresh database has its roles and extensions): a load that failed, not a warning
pg_errors() { grep -E "ERROR:" "$W/pg.err" 2>/dev/null | grep -v "already exists" || true; }
if [ -f "$FILE" ]; then cat "$FILE"; else ssh synology "cat $DEST/$FILE"; fi \
  | age -d -i ~/.config/sops/age/keys.txt | tar -C $W -xzf -     # FILE: a local path (new PC, OneDrive copy) or a NAS name
# A failed check stops here: left of && it would not trip set -e, and a tampered archive went on (review QA-R3)
if ! ( cd $W && sha256sum -c --quiet SHA256SUMS ); then
  [ "$MODE" = drill ] && echo "{\"ts\": $(date +%s), \"kind\": \"restore-drill\", \"file\": \"$FILE\", \"result\": \"failed\"}" >> /srv/ai/state/backups.jsonl
  echo "RESTORE STOPPED: $FILE does not match its checksums"; exit 1
fi
echo "1/4 $FILE decrypted, checksums OK ($(cat $W/MANIFEST))"

unpack_volumes() {          # $1 = volume name prefix
  for v in $VOLS; do docker volume create $1$v >/dev/null; done
  docker run --rm --network none -v $W:/w:ro $(for v in $VOLS; do echo "-v $1$v:/vol/$v"; done) "$ALPINE_IMAGE" \
    sh -c "for v in $VOLS; do find /vol/\$v -mindepth 1 -delete; done; tar -C /vol -xf /w/volumes.tar"
}

if [ "$MODE" = drill ]; then
  pg=drill-pg-$$
  docker run -d --rm --name $pg --network none -e POSTGRES_PASSWORD=drill $(docker inspect -f "{{.Config.Image}}" aistack-postgres-1) >/dev/null
  until docker exec $pg pg_isready -q 2>/dev/null; do sleep 1; done; sleep 2
  docker exec -i $pg psql -q -U postgres -f - < $W/postgres.sql >/dev/null 2>$W/pg.err || true
  n=$(docker exec $pg psql -U postgres -d litellm -tAc "select count(*) from information_schema.tables where table_schema=current_schema()")
  keys=$(docker exec $pg psql -U postgres -d litellm -tAc "select count(*) from \"LiteLLM_VerificationToken\"")
  docker stop $pg >/dev/null
  echo "2/4 postgres dump loads: $n tables, $keys virtual keys"
  if [ -f $W/hindsight.sql ]; then                # long-term memory (backups from 2026-10-25 on)
    hs=drill-hs-$$
    docker run -d --rm --name $hs --network none -e POSTGRES_PASSWORD=drill $(docker inspect -f "{{.Config.Image}}" aistack-hindsight-db-1) >/dev/null   # the live one's image (OPS-R9)
    until docker exec $hs pg_isready -q 2>/dev/null; do sleep 1; done; sleep 2
    docker exec -i $hs psql -q -U postgres -f - < $W/hindsight.sql >/dev/null 2>>$W/pg.err || true
    mem=$(docker exec $hs psql -U postgres -d hindsight -tAc "select count(*) from memory_units" 2>/dev/null || echo failed)
    docker stop $hs >/dev/null
    echo "    long-term memory dump loads: $mem facts"
    # review OPS-R13: 0 facts passed; the live memory is not empty (194 facts on 1 Nov), so none restored is a failed backup
    case "$mem" in ''|failed|0) echo "    long-term memory restores nothing"; bad=1 ;; esac
  fi
  unpack_volumes drill_
  docker run --rm --network none --entrypoint /opt/hermes/.venv/bin/python \
    $(for v in $VOLS; do echo "-v drill_$v:/vol/$v:ro"; done) -v $(realpath $(dirname $0))/restore_check.py:/check.py:ro \
    $(docker inspect -f "{{.Config.Image}}" aistack-hermes-1) /check.py || bad=1
  for v in $VOLS; do docker volume rm drill_$v >/dev/null; done
  tar -tf $W/home.tar | grep -c . | xargs echo "4/4 home folders: files" ; tar -tf $W/vault.tar | grep -c "\.md$" | xargs echo "    vault markdown files:"
  python3 "$(dirname "$0")/restore_check.py" swarm "$W/srv-ai" || bad=1        # SWM-36: the swarm's ledger restores
  [ -s $W/pg.err ] && { echo "postgres warnings ($(wc -l < $W/pg.err) lines; the first 5):"; head -5 $W/pg.err; }   # cap: list
  if [ -n "$(pg_errors)" ]; then echo "postgres load errors ($(pg_errors | wc -l)):"; pg_errors; bad=1; fi
  [ "${keys:-0}" -gt 0 ] 2>/dev/null || bad=1
  if [ -n "${bad:-}" ]; then
    echo "{\"ts\": $(date +%s), \"kind\": \"restore-drill\", \"file\": \"$FILE\", \"result\": \"failed\"}" >> /srv/ai/state/backups.jsonl
    echo "DRILL FAILED: $FILE"; exit 1
  fi
  echo "{\"ts\": $(date +%s), \"kind\": \"restore-drill\", \"file\": \"$FILE\", \"result\": \"ok\"}" >> /srv/ai/state/backups.jsonl
  echo "DRILL OK: $FILE restores."
  exit 0
fi

[ "$MODE" = apply ] || { echo "usage: $0 drill|apply [FILE]"; exit 2; }
cd ~/ai-stack
make down >/dev/null 2>&1 || true
unpack_volumes aistack_
# /srv/ai and the vault go back while the stack is down: a running service (the swarm's Ledger, the price watch) would write
# its own empty state over them (review OPS-R2). The live Ledger is set aside, so the swarm starts from the backup's snapshot.
rsync -a $W/srv-ai/ /srv/ai/
tar -C /srv -xf $W/vault.tar
if [ -f $W/srv-ai/swarm/swarm.snapshot.db ]; then
  for f in /srv/ai/swarm/swarm.db /srv/ai/swarm/swarm.db-wal /srv/ai/swarm/swarm.db-shm; do
    if [ -e "$f" ]; then mv "$f" "$f.before-restore-$(date +%Y%m%d-%H%M%S)"; fi
  done
fi
[ -n "${REHEARSAL:-}" ] || bash ops/hindsight-models.sh >/dev/null   # not in the backup (rebuildable); rehearsal runs no Hindsight
make up >/dev/null; until docker exec aistack-postgres-1 pg_isready -q 2>/dev/null; do sleep 2; done
docker stop aistack-litellm-1 >/dev/null
docker exec aistack-postgres-1 psql -q -U litellm -d postgres -c "drop database litellm with (force)" -c "create database litellm"
docker exec -i aistack-postgres-1 psql -q -U litellm -d litellm -f - < $W/postgres.sql >/dev/null 2>$W/pg.err || true
if [ -f $W/hindsight.sql ]; then
  docker stop aistack-hindsight-1 >/dev/null 2>&1 || true     # not running in a rehearsal
  docker exec aistack-hindsight-db-1 psql -q -U hindsight -d postgres -c "drop database hindsight with (force)" -c "create database hindsight"
  docker exec -i aistack-hindsight-db-1 psql -q -U hindsight -d hindsight -f - < $W/hindsight.sql >/dev/null 2>>$W/pg.err || true
fi
[ -s $W/pg.err ] && { echo "postgres warnings ($(wc -l < $W/pg.err) lines; the first 20):"; head -20 $W/pg.err; }   # cap: list
# A file here that is newer than the backup's stays. GNU tar says so for each one and exits 2 (review OPS-R1: under set -e
# that stopped every restore here, before the restart). Only those messages are no failure.
rc=0; tar -C ~ -xf $W/home.tar --keep-newer-files 2>$W/home.err || rc=$?
if [ "$rc" -ne 0 ] && { [ "$rc" -ne 2 ] || grep -v -e "is newer or same age" -e "Unexpected inconsistency when making directory" \
                         -e "Exiting with failure status due to previous errors" $W/home.err | grep -q .; }; then
  cat $W/home.err >&2; echo "RESTORE STOPPED: the home folders did not unpack (tar exit $rc)"; exit 1
fi
echo "home folders back; $(grep -c 'is newer' $W/home.err || true) files here were newer than the backup and were kept"
if [ -n "${REHEARSAL:-}" ]; then                  # restored timers would back up to the NAS and push to Forgejo
  rm -rf ~/.config/systemd/user/timers.target.wants
fi
make restart >/dev/null
# The rest is back and the stack runs, but a database that did not load is no restore (review OPS-R13: errors were dropped)
if [ -n "$(pg_errors)" ]; then
  echo "RESTORE INCOMPLETE: $FILE: postgres reported $(pg_errors | wc -l) errors while loading:" >&2; pg_errors >&2; exit 1
fi
echo "Restored $FILE. Check with: make smoke"
