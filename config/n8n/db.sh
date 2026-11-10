#!/bin/sh
# n8n's role and database in the stack's Postgres (WFL-02, docs/N8N-MIGRATION.md). Runs in the Postgres image as the
# one-shot service n8n-db on every start of the core; every step is safe to repeat. The role n8n owns only its own
# database; its password is the secret N8N_DB_PASSWORD (sops), set again each time.
set -eu
export PGPASSWORD="$PG_PASSWORD"
psql_admin() { psql -v ON_ERROR_STOP=1 -h postgres -U litellm -d litellm -tA "$@"; }
[ "$(psql_admin -c "select 1 from pg_roles where rolname = 'n8n'")" = 1 ] || psql_admin -c "create role n8n login"
echo "alter role n8n password :'pw';" | psql_admin -v pw="$N8N_DB_PASSWORD" >/dev/null
[ "$(psql_admin -c "select 1 from pg_database where datname = 'n8n'")" = 1 ] || psql_admin -c "create database n8n owner n8n"
echo "n8n's role and database are in place"
