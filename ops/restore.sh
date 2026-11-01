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
export DOCKER_HOST=${DOCKER_HOST:-unix:///run/user/1000/docker.sock}
MODE=${1:-drill}; DEST=/volume1/docker/ai-backup
FILE=${2:-$(ssh synology "cd $DEST && ls -1t aistack-*.tar.gz.age | head -1")}
VOLS="hermes-home litellm-auth openwebui qmd-data opencode-data"
W=$(mktemp -d); trap "rm -rf $W" EXIT
if [ -f "$FILE" ]; then cat "$FILE"; else ssh synology "cat $DEST/$FILE"; fi \
  | age -d -i ~/.config/sops/age/keys.txt | tar -C $W -xzf -     # FILE: a local path (new PC, OneDrive copy) or a NAS name
( cd $W && sha256sum -c --quiet SHA256SUMS ) && echo "1/4 $FILE decrypted, checksums OK ($(cat $W/MANIFEST))"

unpack_volumes() {          # $1 = volume name prefix
  for v in $VOLS; do docker volume create $1$v >/dev/null; done
  docker run --rm --network none -v $W:/w:ro $(for v in $VOLS; do echo "-v $1$v:/vol/$v"; done) alpine \
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
    docker run -d --rm --name $hs --network none -e POSTGRES_PASSWORD=drill pgvector/pgvector:pg17 >/dev/null
    until docker exec $hs pg_isready -q 2>/dev/null; do sleep 1; done; sleep 2
    docker exec -i $hs psql -q -U postgres -f - < $W/hindsight.sql >/dev/null 2>>$W/pg.err || true
    mem=$(docker exec $hs psql -U postgres -d hindsight -tAc "select count(*) from memory_units" 2>/dev/null || echo failed)
    docker stop $hs >/dev/null
    echo "    long-term memory dump loads: $mem facts"
    [ "$mem" = failed ] && bad=1
  fi
  unpack_volumes drill_
  docker run --rm --network none --entrypoint /opt/hermes/.venv/bin/python \
    $(for v in $VOLS; do echo "-v drill_$v:/vol/$v:ro"; done) -v $(realpath $(dirname $0))/restore_check.py:/check.py:ro \
    $(docker inspect -f "{{.Config.Image}}" aistack-hermes-1) /check.py || bad=1
  for v in $VOLS; do docker volume rm drill_$v >/dev/null; done
  tar -tf $W/home.tar | grep -c . | xargs echo "4/4 home folders: files" ; tar -tf $W/vault.tar | grep -c "\.md$" | xargs echo "    vault markdown files:"
  python3 "$(dirname "$0")/restore_check.py" swarm "$W/srv-ai" || bad=1        # SWM-36: the swarm's ledger restores
  [ -s $W/pg.err ] && { echo "postgres warnings:"; head -5 $W/pg.err; }
  [ "$keys" -gt 0 ] || bad=1
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
rsync -a $W/srv-ai/ /srv/ai/
tar -C /srv -xf $W/vault.tar
tar -C ~ -xf $W/home.tar --keep-newer-files
if [ -n "${REHEARSAL:-}" ]; then                  # restored timers would back up to the NAS and push to Forgejo
  rm -rf ~/.config/systemd/user/timers.target.wants
fi
make restart >/dev/null
echo "Restored $FILE. Check with: make smoke"
