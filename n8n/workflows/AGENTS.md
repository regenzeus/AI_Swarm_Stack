# n8n/workflows

One n8n workflow per file (WFL-08, WFL-09). See [../AGENTS.md](../AGENTS.md). n8n is the stack's one scheduler: every
scheduled job runs from its workflow here; systemd keeps only the backup, the restore drill and the boot check, which
must run when n8n is down (ops/systemd/AGENTS.md). A crew job's workflow is made by `ops/n8n_gen.py crew <job> '<cron>'`
(inactive); `ops/n8n_switch.py <file> on|off` publishes or unpublishes one, and the file's `active` follows. A task that
gets a schedule (a sentence on the Tasks page, a briefing a mission hands over, a mission made with a schedule) gets its
workflow from the runner, once (`ops/n8n_jobs.py`, kept in `/srv/ai/missions/flows/made/` until an export brings it
here). After that a schedule is changed on n8n's canvas (Workflows in the app) and exported (WFL-08); the app has no
schedule form of its own.

Not every deployment runs every file here (PLT-38): a deployment imports those its `deployments/<name>/workflows.yaml`
names, plus the tracker poller and its trackers' item workflows; the Active column below is home's, which runs them
all. `ops/n8n_gen.py crew` adds a new job's name to the running deployment's list.

The stack's own **item workflows** (`item-home-<name>.json`, named `Item: home/<name>`) start from a tracker item: the
run register posts `item/home/<name>` when a tracker of the deployment names `home/<name>` as its workflow
(docs/N8N-MIGRATION.md §3.6). They have no Run now; no pack may be named `home`, so no pack listens there.

Every scheduled workflow also has a **Run now** trigger (WFL-13): a POST to `<n8n>/webhook/run/<file stem>` with the
runner's header `X-Aistack-Hook: $N8N_HOOK_TOKEN` (SEC-27; every webhook here asks for it) starts it at once, as its
schedule would (for example `http://127.0.0.1:5678/webhook/run/crew-checker`, under n8n's path prefix when it has one). n8n registers it only while the workflow is published (Active yes). `ops/n8n_gen.py` adds it to a
file that lacks it and changes nothing else in the file.

| File | Workflow | Schedule | Run now | Active |
|---|---|---|---|---|
| `crew-checker.json` | Crew: Checker | `0 * * * *` | `run/crew-checker` | yes |
| `crew-coach.json` | Crew: Coach | `0 6 02 * *` | `run/crew-coach` | yes |
| `crew-code-graph.json` | Crew: Code graph | `* * * * *` | `run/crew-code-graph` | yes |
| `crew-daily-digest.json` | Crew: Daily digest | `30 7 * * *` | `run/crew-daily-digest` | yes |
| `crew-editor.json` | Crew: Editor | `15 7 * * *` | `run/crew-editor` | yes |
| `crew-health-doctor.json` | Crew: Health doctor | `0 */6 * * *` | `run/crew-health-doctor` | yes |
| `crew-inbox-digest.json` | Crew: Inbox digest | `15 7 * * *` | `run/crew-inbox-digest` | yes |
| `crew-journey-checks.json` | Crew: Journey checks | `10 4 * * *` | `run/crew-journey-checks` | yes |
| `crew-maintainability-review.json` | Crew: Maintainability review | `30 4 * * 1` | `run/crew-maintainability-review` | yes |
| `crew-mail-sorter.json` | Crew: Mail sorter (CNX-12; it moves only the mail of senders the owner approved) | `0 5 * * 6` | `run/crew-mail-sorter` | yes |
| `crew-memory-gatekeeper.json` | Crew: Memory gatekeeper | `*/10 * * * *` | `run/crew-memory-gatekeeper` | yes |
| `crew-nightly-restart.json` | Crew: Nightly restart | `50 3 * * *` | `run/crew-nightly-restart` | yes |
| `crew-phone-check.json` | Crew: Phone check | `0 9 * * 1` | `run/crew-phone-check` | yes |
| `crew-phone-cleanup.json` | Crew: Phone cleanup | `0 10 * * 0` | `run/crew-phone-cleanup` | yes |
| `crew-postmaster.json` | Crew: Postmaster | `0 * * * *` | `run/crew-postmaster` | yes |
| `crew-repository-facts.json` | Crew: Repository facts | `*/5 * * * *` | `run/crew-repository-facts` | yes |
| `crew-skill-curator.json` | Crew: Skill curator | `0 4 * * 0` | `run/crew-skill-curator` | yes |
| `crew-skill-keeper.json` | Crew: Skill keeper | `*/5 * * * *` | `run/crew-skill-keeper` | yes |
| `crew-swarm-sync.json` | Crew: Swarm sync | `* * * * *` | `run/crew-swarm-sync` | yes |
| `crew-tracker-poll.json` | Crew: Tracker poll (WFL-19; it asks the trackers every `poll_minutes`, 5 by default) | `* * * * *` | `run/crew-tracker-poll` | yes: with the deployment's trackers (PLT-38) |
| `item-home-inbox.json` | Item: home/inbox (GEN-45; an issue in the owner's inbox repository, answered on the issue) | webhook `item/home/inbox` | none: its item starts it | yes: with its tracker (PLT-38) |
| `crew-test-agent.json` | Crew: Test agent | `30 4 * * 2` | `run/crew-test-agent` | yes |
| `crew-trial-rotation.json` | Crew: Trial rotation | `0 1 * * *` | `run/crew-trial-rotation` | yes |
| `crew-upgrade-check.json` | Crew: Upgrade check | `0 9 01 * *` | `run/crew-upgrade-check` | yes |
| `crew-vault-ingest.json` | Crew: Vault ingest | `* * * * *` | `run/crew-vault-ingest` | yes |
| `memory-keeper.json` | Memory Keeper | `30 4 * * *` | `run/memory-keeper` | yes |
| `stack-self-test.json` | Stack self-test | webhook | `stack-self-test` | yes |
| `tax-desk.json` | Tax desk (TAX-08: find, read with Hermes on ChatGPT, file and prepare; `ops/n8n_gen.py chain`; the app's task Your taxes, TAX-09) | `0 7 3 * *` | `run/tax-desk` | no: the lead switches it on after the first live run |
| `task-10-ram-upgrade-to-32-gb.json` | Task #10: RAM upgrade to 32 GB | `0 8 * * *` | `run/task-10-ram-upgrade-to-32-gb` | yes |
| `task-11-copper-mining.json` | Task #11: Copper mining | `30 6 * * *` | `run/task-11-copper-mining` | yes |
| `task-2-beta-materials-aspi-investment-news-briefing.json` | Task #2: Beta Materials (ASPI): investment news briefing | `30 6 * * *` | `run/task-2-beta-materials-aspi-investment-news-briefing` | yes |
| `task-5-home-assistant-voice-speaker-one-to-try.json` | Task #5: Home Assistant Voice speaker (one to try) | `30 8 * * *` | `run/task-5-home-assistant-voice-speaker-one-to-try` | yes |
| `task-79-weekly-chinese-automotive-news-email.json` | Task #79: Weekly Chinese Automotive News Email | `0 8 * * 1` | `run/task-79-weekly-chinese-automotive-news-email` | yes |

Every file names its **area** ("area": what it is for, TSK-52, ops/areas.py); ops/n8n_gen.py writes it, and a test fails on a file without one. A canvas export (ops/n8n_sync.py) keeps the file's area, feature and factory.

Every file also names its **factory** ("factory", PLT-45): `platform` (the platform's own upkeep, on at every site:
the self-test, the memory upkeep, the code and ideas jobs, the tracker poller) or `home` (the household's work: the
owner's briefings `task-*`, the tax desk, mail, the AI phone, the inbox's item workflow, and the jobs whose unit needs
home's NAS). A workflow of home never runs on a site without home, even when a list or a pattern names it; a file that
names no factory runs nowhere, and `python3 ops/deployment.py check` and `doctor` name it. ops/n8n_gen.py writes the
factory of the crew job (ops/crew.py), and a new one made on the canvas gets the factory of the site it was made on.
