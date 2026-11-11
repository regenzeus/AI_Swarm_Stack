# deployments/platform/: the platform only

**The rule of every site.** All work is a workflow run. People act through Asks; agents start and look at runs with
`stack` (or its MCP tools). A change to a factory is a commit to its pack, approved before it is used. Never edit files
on a site by hand: use `stack`.

The platform with no factory (PLT-44): the app, the engine (n8n and the step service) and the platform's upkeep. A
machine that names no deployment runs this, never home, and `python3 ops/deployment.py new <name|path>` starts a new
deployment from this folder. A factory comes on with `FEATURES` (home) or with a pack its `packs.txt` names.

| File | Holds |
|---|---|
| `deployment.env` | the app and memory on (`FEATURES=mission-control,memory`), no home value, no tailnet: the app's gate is local and n8n stays on 127.0.0.1 (WFL-15, WFL-16); the account and folders from `${USER}` and `${HOME}` |
| `workflows.yaml` | the platform's upkeep it runs (PLT-38): the self-test, the memory upkeep, the skill curator, the vault ingest, the ideas sync (`crew-swarm-sync`), the trial rotation, the nightly restart and the upgrade check; every one's factory is `platform` |
| `models.yaml` | the model policy: subscription_only, so no key can spend money until the site says otherwise (GEN-05) |
| `data.yaml` | the data class: personal, and nothing that sends data out is on (GEN-14) |
