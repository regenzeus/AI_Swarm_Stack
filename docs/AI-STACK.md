# The AI Stack: how it is built

The architecture as it stands on 10 November 2026. n8n decides when work starts and in what order (DEC-51); the
stack's own services do the work; Temporal and the block editor are gone (DEC-52). How the move to n8n proceeds, phase
by phase, is in [N8N-MIGRATION.md](N8N-MIGRATION.md); the platform underneath (deployments, features, the data guard,
the Windows worker) is in [PLATFORM.md](PLATFORM.md). Requirements: WFL-01 to WFL-12 for the workflows, GEN-21 to
GEN-32 for what a domain's work uses.

**In one line:** n8n decides when and in what order; our services do the work.

## 1. The layers

| Layer | What it holds | Where |
|---|---|---|
| **Interface** | The app (Mission Control) for phone and desk, Telegram, chat, the AI phone, the House | `images/mission-control/`, `images/phone/` |
| **Orchestration** | n8n: schedules and triggers, the order of steps, waits of any length, every run's history | `compose/core.yaml`, `n8n/` |
| **The step service** | The one seam between n8n and the stack: n8n hands a step over, the runner does it and answers | `ops/flows.py`, `images/mission-control/server.flows.py` |
| **Workers** | The host runner and what it starts: agents, the coding sandbox, crew jobs, commands at places | `ops/`, `images/builder/` |
| **Knowledge** | Long-term memory, the wikis, each agent's journal, the code map, saved files | `ops/journal.py`, `ops/memory.py`, `ops/domain/artifacts.py` |
| **Models** | One gateway for every model call: the subscriptions and the local models, with costs and budgets | `config/litellm/` |
| **Platform** | Compose, deployments, secrets, backups, updates, health and observability | `compose/`, `deployments/`, `ops/` |

## 2. Interface

- **The app** is the owner's one place: Home (results, Needs you), Tasks, Memory, Code, Chat, Stack, and on the desk
  **Workflows**, which opens n8n. Phone first; n8n's editor is for the desk only (WFL-11).
- **Needs you** holds every decision: a workflow's question (WFL-07), a pack commit, a command to approve, a tracker
  write in shadow. A tap answers; a waiting workflow then goes on.
- **Home** shows each run's result with a link to its execution in n8n (WFL-10).
- Telegram and the app's notifications tell the owner, quiet hours respected.

## 3. Orchestration: n8n

- **One core service on every deployment** (WFL-01): pinned by digest, its own role and database in the stack's
  Postgres (WFL-02), on 127.0.0.1 and the tailnet only, no telemetry, its command node off (WFL-03), executions pruned
  after 30 days (WFL-04).
- **Workflows live in git** (WFL-08): `n8n/workflows/<name>.json`, imported by every deploy (`ops/n8n_sync.py`). A
  new crew job's workflow is made by `ops/n8n_gen.py crew <job> '<cron>'`; a task that gets a schedule gets its own
  from the runner, once (`ops/n8n_jobs.py`), kept beside the repository's until an export brings it into git.
- **One scheduler** (WFL-09): n8n starts every scheduled job, the crew's, the tasks' and the missions'. A job's
  schedule, next run and on/off switch are read from its workflow; they are changed on n8n's canvas (Workflows), and
  `ops/n8n_switch.py <file> on|off` publishes or unpublishes one. systemd keeps only the timers of what must run when
  n8n is down: the boot check, the backup and the restore drill (`ops/systemd/AGENTS.md`). The Conductor starts a
  task's runs only on an event (TSK-21) or when n8n asks; the event bus watches what n8n cannot see (news, prices,
  filings, mail, the house, files, the calendar, finished tasks). n8n does not catch up a time the PC was off.

## 4. The step service

The step service is the seam: nothing in the stack's agents depends on n8n, and another orchestrator could call it.

- n8n's **AI Stack step** node (`n8n/custom/AistackStep.node.js`, WFL-06) posts a step to Mission Control's step
  service on the internal `stepnet` network and waits. Kinds: agent, crew, task, ask, notify.
- The app drops the request into the runner's inbox; the runner (`ops/flows.py`) runs it with the code that runs
  every step today: the Conductor's step runners (`ops/stepkinds.py`: Hermes, Claude Code, build, check, OpenCode,
  wiki, and the domain modules' kinds), with headroom, budget, routing, memory, costs and one trace per run (WFL-05).
- On the end the runner calls n8n's resume URL with the result, also after a restart of either side.
- **Ask** puts the question into Needs you; the owner's tap resumes the workflow (WFL-07). **Notify** tells the owner.

## 5. Workers

- **The host runner** (`ops/missions.py`, systemd `missions.service`) runs in its own pinned Python environment
  (PLT-37). It takes the requests, keeps the state the app shows, runs the Conductor's worker and the step service.
- **Agents**: Hermes profiles (the owner's assistant, the scout, the curator, the desk and others), each described by
  a card in `config/agents.yaml` and its prompts in `prompts/`.
- **The coding sandbox** (`images/builder/`): Claude Code and Hermes build and check on a branch, with Serena and the
  code graph; the owner approves before anything lands.
- **The crew**: housekeeping jobs (the Checker, the Memory Keeper, the Health doctor, the Librarian, …), each a command
  the step service can run (`ops/crew.py`).
- **Places** (`ops/domain/places.py`, GEN-22): a command runs at `wsl` (the runner), `wsl-host` (the user who owns the
  deployment's licensed tools) or `windows` (the pull-only Windows worker), through the worker protocol
  (`ops/winjobs.py`). Each job kind is approved at its place by the hash of its file; values arrive as typed
  parameters. n8n's own command node stays off.

## 6. What a domain's work uses (`ops/domain/`)

These came from the earlier engine design and stay, free of any orchestrator. Each is built and tested; where a part is
not wired to n8n yet, its requirement says so.

| Part | What it does | Requirement |
|---|---|---|
| **Packs** (`packs.py`) | A domain kept outside the repository: Claude Code plugin folders (agents, skills, MCP servers), `stack.yaml`, job kinds, n8n workflows (`workflows/*.json`, named `<pack>/<name>`, never using n8n's command node) and exams; listed in the deployment's `packs.txt`, pinned by commit, each commit approved in Needs you while the last approved one keeps running | GEN-21, GEN-32 |
| **Grants** (`packs.py`) | Each pack agent's step gets exactly the MCP servers and tools its `stack.yaml` grants; a server off the deployment's egress list is dropped | GEN-30 |
| **Trackers** (`trackers.py`) | Jira Data Center and Forgejo issues read with a cursor; each change of an item handed on once for the run named after it; writes (comment, one summary, attach, link, transition, label) in shadow per kind until the owner lets the kind go live | GEN-25 |
| **The forge** (`forgework.py`) | A change starts at the tag or branch its workflow names, pushes `ai/<item>-<slug>` through `FORGE_PUSH`, opens a draft pull request, and hands reviewers' comments on once | GEN-26 |
| **Roles** (`roles.py`) | The deployment's map of roles to people; with none, every role is the owner's | GEN-27 |
| **Saved files** (`artifacts.py`) | Files kept by their SHA-256 with the task, step, run and commit that made them, their data class and retention; a run passes only their ids | GEN-29 |
| **The record** (`record.py`) | A finished run as one zip a person can follow without the app, and a pack's exam cases scored against their known outcomes | GEN-31 |

What is not wired yet: importing a pack's workflows into n8n, a workflow step that runs a command at a place, the
tracker poller on a schedule, a run's export from n8n's execution, and a question addressed to a role. Each of these
comes as a block of n8n's palette ([N8N-MIGRATION.md](N8N-MIGRATION.md)).

## 7. Knowledge

- **Long-term memory** (Hindsight) for the owner's facts, written only through the memory gate.
- **Wikis** in the vault: the vault wiki and each agent's own, kept by the Librarian.
- **Journals**: each agent's working state and notes, opened in front of its next run.
- **The code map** and each repository's facts for the coding agents.
- Details: [MEMORY.md](MEMORY.md), [MEMORY-STACK.md](MEMORY-STACK.md), [REPO-KNOWLEDGE.md](REPO-KNOWLEDGE.md).

## 8. Models

Every model call goes through the LiteLLM gateway: the owner's subscriptions (ChatGPT, Claude) by role, local models
through Ollama, each agent with its own key and budget. The data guard keeps a customer-class deployment's data on its
machine and its gateway's models (GEN-14, [PLATFORM.md](PLATFORM.md)).

## 9. Platform

- **Compose** (`compose/`): the core (Postgres, the gateway, Phoenix, Ollama, n8n) on every deployment; the rest
  behind features.
- **Deployments** (`deployments/<name>/`): hosts, features, model policy, data class, egress, packs, roles, places and
  trackers of one installation.
- **Secrets** in sops; **backups** nightly (Postgres as a dump, n8n's database included); **updates** from signed tags;
  **the disk guard** and the boot check keep the stack up.
- **Observability**: the run record, Phoenix's traces, the health board ([OBSERVABILITY.md](OBSERVABILITY.md)).

## 10. History

- 9 November 2026 (DEC-50): Temporal was chosen as the engine, with a graph runner, templates drawn in a block editor,
  packs, places, trackers, roles and the record.
- 10 November 2026 (DEC-51): the owner found that layer hard to reach and half moved; n8n became the one place that
  decides when work runs.
- 10 November 2026 (DEC-52): plans went back to the Conductor at 10:40, and Temporal, the graph runner, its bridge and
  cutover, the codec, the template format and the block editor were removed. Packs, places, trackers, roles, saved
  files and the record stayed, in `ops/domain/`.
