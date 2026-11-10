# deployments/: one folder per deployment of the platform

A deployment is one installation: its hosts, owner, features and (as they are built) its model policy, data class,
egress list and constraint values (docs/PLATFORM.md, DEC-45). `home/` is this house, every feature on; `example-work/`
shows a work deployment with placeholders. A real work deployment's folder lives only on its machine, outside this
repository, and nothing of it is committed.

Which one a machine runs: `$AISTACK_DEPLOYMENT`, else the first line of `~/.config/aistack/deployment`, else `home`; a
name is a folder here, a path is a folder anywhere. `ops/deployment.py` reads it; compose gets its `deployment.env` as its
second `--env-file`, and takes the feature list from it as `COMPOSE_PROFILES`.

| File | Holds |
|---|---|
| `deployment.env` | the hosts, paths and accounts, `DEPLOYMENT`, `FEATURES` and `COMPOSE_PROFILES=${FEATURES}`; never a secret |
| `data.yaml` | the data class, personal or customer, per deployment and per repository (GEN-14) |
| `trackers.yaml` | the trackers it watches, each starting its item workflow (GEN-25, WFL-19); a value may name one of `deployment.env` as `${NAME}` |

Without the tailnet a deployment sets `APP_GATE=local` and n8n's two addresses on 127.0.0.1 (`N8N_EDITOR_URL`,
`N8N_WEBHOOK_URL`); with customer data it also lists n8n's logic nodes in `N8N_NODES_INCLUDE` (docs/N8N-MIGRATION.md
§10). `python3 ops/deployment.py check` and `python3 ops/dataguard.py check` refuse a deployment that does not.

A feature that is off starts no compose service (each service names its feature as its profile), enables no timer (each
unit names its feature in a `# feature:` line), and its scripts exit with "not configured" before any network call.
