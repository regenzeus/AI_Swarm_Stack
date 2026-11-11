# deployments/example-work/: an example of a work deployment

**The rule of every site.** All work is a workflow run. People act through Asks; agents start and look at runs with
`stack` (or its MCP tools). A change to a factory is a commit to its pack, approved before it is used. Never edit files
on a site by hand: use `stack`.

Placeholders only: a work PC where the builds run on Windows through the Windows worker, every model goes through one
company gateway, and nothing of the home (NAS, phone, mail, Telegram, the web tools, publish) is on: it runs the
platform and the factory of its pack, and refuses home (`REFUSE=home`, PLT-47). A real work deployment copies this
folder to its own machine, outside the repository, lists its packs in `packs.txt` there (the doctor fails without it,
since `trackers.yaml` names a pack) and names the folder in ~/.config/aistack/deployment (docs/PLATFORM.md §2,
docs/WORK-APPROVALS.md).

| File | Holds |
|---|---|
| `deployment.env` | the hosts, paths, accounts and features; `REFUSE=home`; the home's values empty; no tailnet, so the app's gate is local and n8n stays on 127.0.0.1 with only its logic nodes (docs/N8N-MIGRATION.md §10) |
| `workflows.yaml` | the stack's own workflows it runs (PLT-38): only the self-test, none of home's jobs |
| `trackers.yaml` | a placeholder Jira tracker that starts a pack's workflow, and a read-only tracker of record (`write: off`, `records: <pack>`) read for the Measures view; with them comes the tracker poller (GEN-25, PLT-38, REC-02) |
| `data.yaml`, `egress.txt` | the data class (customer) and the only hosts the work may reach (GEN-14) |
| `policy.yaml`, `roles.yaml` | what it changes of the stack's policy (tiers, channels app, ticket and mail, the data rule's extract paths) and its roles with placeholder logins and an escalation order (ASK-02, ASK-04) |
| `models.yaml` | the model policy: gateway_only, the gateway's addresses, the name of its token's secret and the budget |
| `litellm.yaml` | LiteLLM's configuration, written from `models.yaml` by `python3 ops/modelpolicy.py litellm` |
| `checks/<repo>.yaml` | the checks this deployment adds to the judge for a repository (GEN-15) |
| `allowed_signers` (on the work machine) | the owner's public signing key: the release tags `make update` accepts (GEN-16) |
