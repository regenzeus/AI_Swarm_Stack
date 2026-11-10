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
| `workflows.yaml` | the stack's own workflows it runs (PLT-38): names of `n8n/workflows/` without `.json`, a pattern like `task-*` allowed |

Which of the stack's own workflows (`n8n/workflows/`) a deployment runs is its `workflows.yaml` plus what its trackers
imply: with any tracker, the tracker poller `crew-tracker-poll`, and for a tracker whose workflow is `home/<name>` the
item workflow `item-home-<name>` (PLT-38, `python3 ops/deployment.py workflows` lists them). A deploy imports only
those and unpublishes one it imported earlier that is no longer chosen (`ops/n8n_sync.py`); `ops/n8n_switch.py` publishes
only a chosen one; a crew job made with `ops/n8n_gen.py crew`, or a workflow made on the canvas and exported, is added
to the list by that command. The app's Workflows page and its schedules show only the chosen ones. A workflow the
runner makes for a task here (its folder `/srv/ai/missions/flows/made/`) is always this deployment's.
`python3 ops/deployment.py check` refuses a name that matches no file.

Without the tailnet a deployment sets `APP_GATE=local` and n8n's two addresses on 127.0.0.1 (`N8N_EDITOR_URL`,
`N8N_WEBHOOK_URL`); with customer data it also lists n8n's logic nodes in `N8N_NODES_INCLUDE` (docs/N8N-MIGRATION.md
§10). `python3 ops/deployment.py check` and `python3 ops/dataguard.py check` refuse a deployment that does not.

A feature that is off starts no compose service (each service names its feature as its profile), enables no timer (each
unit names its feature in a `# feature:` line), and its scripts exit with "not configured" before any network call.
