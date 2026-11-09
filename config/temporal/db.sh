#!/bin/sh
# The engine's role and databases in the stack's Postgres (GEN-33, docs/AI-STACK-PLAN.md WP1). Runs in the Postgres
# image as the one-shot service temporal-db on every start of the core; every step is safe to repeat. The role
# temporal owns only its two databases; its password is the secret TEMPORAL_DB_PASSWORD (sops), set again each time.
set -eu
export PGPASSWORD="$PG_PASSWORD"
psql_admin() { psql -v ON_ERROR_STOP=1 -h postgres -U litellm -d litellm -tA "$@"; }
[ "$(psql_admin -c "select 1 from pg_roles where rolname = 'temporal'")" = 1 ] || psql_admin -c "create role temporal login"
echo "alter role temporal password :'pw';" | psql_admin -v pw="$TEMPORAL_DB_PASSWORD" >/dev/null
for db in temporal temporal_visibility; do
  [ "$(psql_admin -c "select 1 from pg_database where datname = '$db'")" = 1 ] || psql_admin -c "create database $db owner temporal"
done
echo "the engine's role and databases are in place"
