# config/temporal: the engine's own configuration (GEN-33, GEN-39)

- `db.sh` makes Temporal's role and two databases in the core's Postgres (its password: the secret TEMPORAL_DB_PASSWORD).
- `schema.sh` sets up and moves the schema to the pinned version; safe to repeat (the one-shot service temporal-schema).
- `dynamicconfig.yaml`: the server's dynamic settings.
- `steps.yaml`: every Temporal version the update path may step through, pinned by digest (ops/temporal_upgrade.py);
  a new minor version is added here before versions.env moves to it.
