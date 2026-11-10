# deployments/example-work/: an example of a work deployment

Placeholders only: a work PC where the builds run on Windows through the Windows worker, every model goes through one
company gateway, and nothing of the home (NAS, phone, mail, Telegram, the web tools, publish) is on. A real work
deployment copies this folder to its own machine, outside the repository, and names it in ~/.config/aistack/deployment
(docs/PLATFORM.md §2, docs/WORK-APPROVALS.md).

| File | Holds |
|---|---|
| `deployment.env` | the hosts, paths, accounts and features; the home's values empty; no tailnet, so the app's gate is local and n8n stays on 127.0.0.1 with only its logic nodes (docs/N8N-MIGRATION.md §10) |
| `data.yaml`, `egress.txt` | the data class (customer) and the only hosts the work may reach (GEN-14) |
| `models.yaml` | the model policy: gateway_only, the gateway's addresses, the name of its token's secret and the budget |
| `litellm.yaml` | LiteLLM's configuration, written from `models.yaml` by `python3 ops/modelpolicy.py litellm` |
| `checks/<repo>.yaml` | the checks this deployment adds to the judge for a repository (GEN-15) |
| `allowed_signers` (on the work machine) | the owner's public signing key: the release tags `make update` accepts (GEN-16) |
