# deployments/: one folder per deployment of the platform

**The rule of every site.** All work is a workflow run. People act through Asks; agents start and look at runs with
`stack` (or its MCP tools). A change to a factory is a commit to its pack, approved before it is used. Never edit files
on a site by hand: use `stack`.

A deployment is one installation: its hosts, owner, features and (as they are built) its model policy, data class,
egress list and constraint values (docs/PLATFORM.md, DEC-45). `platform/` is the platform only (the app, the engine and
the platform's upkeep, no factory); `home/` is this house, the home factory on; `example-work/` shows a work deployment
with placeholders. A real work deployment's folder lives only on its machine, outside this repository, and nothing of
it is committed. Every deployment folder's AGENTS.md opens with the rule above (PLT-48); `python3 ops/deployment.py new
<name|path>` makes a new folder from `platform/` with it.

Which one a machine runs: `$AISTACK_DEPLOYMENT`, else the first line of `~/.config/aistack/deployment`, else `platform`
(PLT-44: a machine that names none runs the platform only, never home); a name is a folder here, a path is a folder
anywhere. A deploy refuses, before any step, on a machine that names none. `ops/deployment.py` reads it; compose gets its
`deployment.env` as its second `--env-file`, and takes the feature list from it as `COMPOSE_PROFILES`.

| File | Holds |
|---|---|
| `AGENTS.md` | the site's rule first, then what the deployment is (PLT-48) |
| `deployment.env` | the hosts, paths and accounts, `DEPLOYMENT`, `FEATURES`, `COMPOSE_PROFILES=${FEATURES}` and `REFUSE`; never a secret |
| `data.yaml` | the data class, personal or customer, per deployment and per repository (GEN-14) |
| `trackers.yaml` | the trackers it watches, each starting its item workflow (GEN-25, WFL-19); a value may name one of `deployment.env` as `${NAME}` |
| `workflows.yaml` | the stack's own workflows it runs (PLT-38): names of `n8n/workflows/` without `.json`, a pattern like `task-*` allowed |
| `packs.txt` (on the site) | the packs it runs, one per line: name, source, commit (GEN-21); a factory that is not home comes from here |

**Factories (PLT-44, PLT-45).** Every workflow file of `n8n/workflows/` and every job of `ops/crew.py` names its factory:
`platform` (the platform's own upkeep, on at every site) or `home` (the household's work, on where `FEATURES` names
`home`). Of a factory that does not run, nothing runs or shows: its listed workflows are left out (a pattern takes only
the files of the factories that run), its jobs have no card and refuse Run now. A file that names no factory runs nowhere.

**Refusing a factory (PLT-47).** `REFUSE=home` (factory or pack names, comma separated) keeps that factory off for good:
`FEATURES` cannot switch it on, a pack of that name is refused, `python3 ops/deployment.py need home` answers
"refused: ... (REFUSE in its deployment.env)" so its scripts stop, and the deploy refuses before any step while
`FEATURES` names it. The message names only the factory and the setting, never a site.

**The doctor (PLT-46).** `python3 ops/deployment.py doctor` (`--json` for `stack doctor`) fails, naming each reason: a
value a feature needs, a workflow listed that does not exist or whose factory does not run, a refused factory switched on,
a workflow file no factory owns, a pack the trackers need that `packs.txt` does not list (or no `packs.txt`), a pack not
approved at its pinned commit or refused, a pack's override of a standard workflow that changed since it was checked
(phase B), a workflow not imported or not published in n8n as the deployment says, and a dead or stale runner (the
runner's service, the CI runner, a worker place). A deploy runs it after its checks and fails when it fails.

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

A feature that is off starts no compose service (each service names its feature as its profile; a deploy stops and
removes a container of one switched off since), enables no timer (each unit names its feature in a `# feature:` line),
and its scripts exit with "not configured" before any network call. Its crew jobs (their unit's feature) have no card,
task or health item and refuse Run now; its workflows (a file of `n8n/workflows/` names its `feature`) are left out of
`workflows.yaml`'s list, so the import unpublishes them; no key is granted its tool server (`ops/update-keys.py`, the
features of `ops/modelpolicy.py` SERVER_FEATURE); the assistant's prompt rule of it goes in empty (`ops/deploy.py`
RULE_FEATURE); and the app, which gets `FEATURES` from compose, draws none of it. The AI phone is home's (home chooses
it) and the first feature the app hides completely where it is not chosen (PHN-28): there its questions in Needs you are
dismissed with the reason "the AI phone is switched off", and adding `phone` to `FEATURES` brings every part back.
