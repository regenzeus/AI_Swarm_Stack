# deployments/home/: the home deployment

**The rule of every site.** All work is a workflow run. People act through Asks; agents start and look at runs with
`stack` (or its MCP tools). A change to a factory is a commit to its pack, approved before it is used. Never edit files
on a site by hand: use `stack`.

Home is the one deployment with the home factory on (`home` in `FEATURES`, PLT-44); the PC names it in
`~/.config/aistack/deployment`. This house: one Windows 10 PC with WSL, the NAS, the AI phone, Home Assistant, Gmail and Telegram. Every feature is on,
the AI phone (`phone`) among them: it is home's, not the platform's, and a site that leaves it out of `FEATURES` sees
nothing of it (PHN-28). The model policy is subscriptions only (CST-02). It is one deployment of the platform and the example the others
follow (DEC-45, docs/PLATFORM.md).

| File | Holds |
|---|---|
| `deployment.env` | the hosts, paths, accounts and features (PLT-33) |
| `models.yaml` | the model policy: subscription_only, and what serves each alias (GEN-05) |
| `workflows.yaml` | the stack's own workflows home runs (PLT-38): every job of `n8n/workflows/`, the self-test and `task-*`; the poller and the inbox's item workflow come with `trackers.yaml`; a listed one of a feature that is off is left out (a copy of home without `phone` runs neither of the AI phone's two) |
| `policy.yaml` | what home changes of the stack's policy: its channels (app, ticket, Telegram) and the tracker of its tickets (ASK-02, ASK-09) |
| `trackers.yaml` | its one tracker: the owner's private repository `${FORGEJO_OWNER}/inbox` on Forgejo, a front door to the stack's item workflow `home/inbox` (GEN-45) |

An issue in the inbox repository is answered on the issue by the main agent, which waits for the owner's reply,
answers that and closes the issue (docs/N8N-MIGRATION.md §3.6). The Forgejo token is the owner's own account, so the
entry leaves `me` unset: the stack knows its own comments by their write mark (WFL-26).
