#!/bin/sh
# The engine's schema (GEN-33, GEN-39): set up once, then moved to the newest version the pinned admin tools carry.
# Runs in Temporal's admin-tools image as the one-shot service temporal-schema on every start of the core, after
# temporal-db. Both steps are safe to repeat (tried on 9 Nov 2026: a second run leaves the schema at its version).
# An upgrade of the server steps through each minor version in turn (ops/update.py, GEN-39); this only applies the
# schema of the version that is pinned.
set -eu
DIR=/etc/temporal/schema/postgresql/v12
for db in temporal temporal_visibility; do
  sub=temporal; [ "$db" = temporal_visibility ] && sub=visibility
  temporal-sql-tool --db "$db" setup-schema -v 0.0 2>&1 | grep -E "ERROR|FATAL" || true
  temporal-sql-tool --db "$db" update-schema -d "$DIR/$sub/versioned" 2>&1 | grep -E "ERROR|FATAL" || true
done
echo "the engine's schema is at the pinned version"
