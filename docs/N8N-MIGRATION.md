# n8n as the stack's workflow pillar

Design, migration plan and the changes it brings to requirements, code and the app. Decided by the owner on
10 Nov 2026 (DEC-51). It replaced the engine of DEC-50, which was removed the same day (DEC-52); packs, places,
trackers and saved files from that design stay. The architecture as it stands is in [AI-STACK.md](AI-STACK.md).

## 1. Why

On 10 Nov 2026 the owner found the new engine layer hard to reach, half migrated and rough. The analysis:

- **Four things decide when work starts:** 26 systemd timers (crew jobs, backup, syncs), the runner's mission
  schedules and event rules, the Conductor (plan steps), and Temporal (9 plan tasks since 9 Nov). Nobody can see all
  of them in one place.
- **Runs show on about seven screens:** Live, Swarm, Engine, Runs, Telemetry, a crew job's page, a task's map.
- **Our block editor** (Workflow Builder SDK on React Flow) is young: no right-click menu, Start and End drawn as
  plain cards, no run view on the canvas. Making it as good as a mature tool is months of work.

n8n gives the missing layer as a maintained product: a canvas, schedules and triggers, waits of any length, a run
history on the canvas, hundreds of integrations. It is free for personal and internal business use (the
Sustainable Use License).

## 2. What n8n replaces, and what stays

| Today | With n8n |
|---|---|
| systemd timers for crew jobs and syncs (26) | n8n Schedule triggers, one workflow per job |
| The runner's mission schedules, the event bus's rules (TSK-11), calendar and breaking-news triggers | n8n triggers (schedule, webhook, Gmail, calendar, RSS) |
| The Conductor's plan graphs: step order, branches, fan-out, waiting for the owner | n8n workflows |
| Temporal, its runner, bridge, cutover, codec | removed (DEC-52) |
| Our block editor, Templates, Engine screens | n8n's editor and its executions |
| Tracker polling (Jira, Forgejo) | n8n's Jira trigger, or our adapter called by n8n |

**Stays, unchanged in what it does:** Hermes, the swarm, the coding agents and their sandbox, OpenCode, Claude Code
tasks, LiteLLM and the subscriptions, the memory system (Hindsight, wikis, journals, the Memory Keeper's rules),
chat, the phone, the house, the mail copy, backups, Phoenix, Open WebUI, the app's Home, Needs you and task pages,
packs, places, artifacts and the record of a run.

**In one line:** n8n decides when and in what order; our services do the work.

## 3. Design

```
                        n8n (core service, tailnet only)
   triggers: schedule, webhook, Gmail, Telegram, Jira, calendar
   nodes:    the "AI Stack step" node (the block palette)  +  n8n's own nodes
                 |  POST /steps (kind, agent, brief, resume URL)
                 v
   Mission Control: step service (internal port, n8n's network only)
                 |  request file (the runner's inbox, as today)
                 v
   runner: runs the step with today's code (stepkinds registry, sandboxes, memory, costs)
                 |  result, files, cost  ->  POST resume URL
                 v
   n8n: the waiting execution continues
   Needs you: an "Ask the owner" node adds an item; the owner's tap resumes the run
```

### 3.1 n8n in the stack
- Core service on every deployment, image pinned by digest in `versions.env`, its own role and database in the
  stack's Postgres (made by the one-shot `n8n-db`, safe to repeat), so the nightly `pg_dumpall` backs it up.
- Port 5678 on 127.0.0.1 only. The editor lives inside the app: the app serves it under `/n8n/` behind its own
  gate (`N8N_PATH=/n8n/`, live updates over plain HTTP streaming, `N8N_PUSH_BACKEND=sse`; WFL-14). n8n's own tailnet
  port (`tailscale serve --https=8450`) keeps webhooks and resume URLs at n8n's root and is the direct fallback when
  the app is down. No public exposure.
- Its own login: the owner creates the owner account once in the browser. Single sign-on is a paid feature.
- Secrets `N8N_DB_PASSWORD` and `N8N_ENCRYPTION_KEY` in the sops file; n8n's stored credentials are encrypted with
  the key.
- Privacy: no telemetry, no version pings, no personalisation survey.
- Execution data pruned after 30 days (a tagged limit).
- n8n's Execute Command node stays off (its 2.x default): commands run only through places, approved by fingerprint.
- Networks: the Postgres network (internal) and its own outbound network for integrations; in phase 2 a network
  shared with Mission Control's step service only.

### 3.2 The step service (phase 2)
The Conductor's step kinds (`ops/stepkinds.py`: hermes, claude-code, build, python, temp, check, opencode, wiki,
plus the change, shopping and desk steps) are exposed to n8n:
- `POST /steps {kind, agent, brief, task, resume_url}` returns a step id at once.
- The runner runs the step as today: same headroom check, sandboxes, memory, journals, costs, run record.
- On finish it posts the result to the resume URL. After a restart the runner requeues interrupted steps
  (`requeue_interrupted`) and still calls back. n8n holds no long work in memory; a waiting execution survives an
  n8n restart.
- The service listens on an internal port reachable only from n8n's network, with a shared token from sops.

### 3.3 The stack's own node: the block palette (phase 2)
One node, **AI Stack step** (`n8n/custom/AistackStep.node.js`, type `CUSTOM.aistackStep`, plain JavaScript loaded
through `N8N_CUSTOM_EXTENSIONS`; the TypeScript package once planned is not needed). Its kind makes it one block; each
sends its work to the step service and waits for the answer. An answer that is not `done` fails the block, so the run
ends as an error in n8n's history. The Agent, Crew job, Place and Repository pickers read the stack's lists live
(`GET /catalog` on the step service: the agents of the stack and of the running packs, the crew jobs, the places with
the commands approved there, the repositories the builder may change).

| Block (kind) | Does | Through | Status |
|---|---|---|---|
| Agent step (`agent`) | one agent does one piece of work; its brief is the step it reads | the Conductor's run_step and adapters | built |
| Coding change (`build`) | the coder in the sandbox on a repository; answers with the build, its state, branch or pull request, CI and checks | the Conductor's build step (ops/builds.py), the owner's review included | built |
| Crew job (`crew`) | a housekeeping job, as Run now starts it | its systemd unit | built |
| Plan task (`task`) | one run of a plan task (a briefing, a price watch) | the Conductor's occurrence | built |
| Ask the owner (`ask`) | a question in Needs you; the tap is the answer | ops/decisions.py | built |
| Notify the owner (`notify`) | a message, quiet hours respected (OBS-16) | ops/notify.py | built |
| Recall (`recall`) | a search of the stack's memory; the hits are the answer | the memory tool's search (MEM-28) | built |
| Remember (`remember`) | a lesson, fact, failure or skill; kept only after its check | the memory tool's write gate (MEM-28, MEM-35) | built |
| Run command (`command`) | a job kind at a place (WSL, WSL host, Windows), only once approved there by its fingerprint | ops/domain/places.py (GEN-22) | built |
| Run a plan (`plan`) | an improvised plan's steps as waves of agent steps; every step's output is the answer | the agent path, one task with a row per step | built |
| Report | what Home shows for each step, with the n8n run | the step service itself (WFL-10) | built, not a block |

Every scheduled workflow also has a **Run now** trigger (WFL-13): `POST <n8n>/webhook/run/<file stem>` starts it at
once, while it is published.

### 3.4 Git stays the truth
- Workflows live in `n8n/workflows/<name>.json`. A job exports changes made on the canvas (`n8n export:workflow
  --backup`) and commits them through the landing path; a deploy imports the repository's workflows
  (`n8n import:workflow --separate`). Built-in git sync is a paid feature and is not needed.
- A work deployment keeps its workflows in its pack repository, never in the public one (SEC-22's terms).

### 3.5 Temporal
Not needed. n8n's waits plus the step service cover runs that wait for days; the tasks table plus steps that are
safe to repeat cover restarts. Plans went back to the Conductor on 10 Nov 2026 at 10:40, and Temporal was removed the
same day (DEC-52): its services and databases' setup, its upgrade path, its SDK, the graph runner, the bridge, the
cutover, the codec, the graph template format and the block editor.

## 4. The app with n8n

### 4.1 Where n8n appears
- **Desk:** **Workflows** in the menu opens n8n's editor inside the app, beside the app's menu (`#/workflows`, a
  frame on the app's own address; WFL-11, WFL-14). A task or crew job that belongs to a workflow shows **Where it
  runs** at its top: the workflow, the run, its state and the step it is on, with the run on n8n's canvas below. An
  agent's and a crew job's page list every workflow it is a step of; each opens inside the app.
- **Phone:** Home and Needs you; approvals by one tap or Telegram. n8n's editor is not made for a phone: the
  Workflows page lists the workflows instead (whether n8n runs each, its schedule, its last runs with their steps), a
  task's Where it runs lists the run's steps, and the phone's menu has no Workflows entry.
- **Home:** each run reports its start and end through the Report node, with the execution's link.
- **Look:** n8n keeps its own look (a maintained product; no restyling). Our app keeps its own.

### 4.2 What in our app is outdated (audit, 10 Nov 2026)
- **39 screens behind 6 menu entries.** Engine, Runs, Templates, Packs and Trackers hang off banners and links
  (Stack → Tools → Engine banner; Tasks → Templates → Packs → Trackers). Share and the plain Home route have no link.
- **Runs on seven screens:** Live, Swarm, Engine, Runs, Telemetry, a crew job's page, a task's map. With n8n:
  executions in n8n, results on Home and the task page, nothing else.
- **The Stack page is a drawer:** tools, house, engine, A2A, subscriptions, connections, health, resources, agents,
  services, scheduled jobs, memory review, librarian, telemetry and the guide. It should be health and services only.
- **Memory has eight sub-screens** (skills, how-to, long-term, code memory, journals, search, sources, overview).
- **Old names:** the start-page picker still offers "Agents" (`#/missions`) and "Wiki" (`#/wiki`), names from before
  the Tasks and Memory redesigns.
- **"Not connected" means the runner's file is old**, not that the app is down; after a reboot it showed 03:36 for
  20 minutes (fixed at its cause on 10 Nov, the wording is still wrong).
- **The desk scales by CSS zoom** (1.12 / 1.3 / 1.6), which broke the canvas and needed a counter-zoom.
- **Jargon on screens:** packs, trackers, places, pools, namespace, occurrence.

### 4.3 The app after the migration
Menu: **Home** (results, Needs you), **Tasks** (what you asked, each with its page), **Memory**, **Code**, **Chat**,
**Workflows** (n8n, desk only), **Stack** (health and services). Engine, Runs, Templates, Trackers, Live, Swarm,
Telemetry and the task map fold into n8n's executions, the task page or Stack. Each fold is its own change, with the
owner's look at the result before the old screen goes.

## 5. Requirements: what changes

Of 858 requirement items, about 160 trace to code n8n touches. Most keep their intent and change their mechanism.

| Group | Count | What happens |
|---|---|---|
| Temporal engine (GEN-23, GEN-24, GEN-28, GEN-33 to GEN-39) | 10 | Retired on 10 Nov 2026 (DEC-52), each naming what replaced it: n8n in the core (WFL-01), its waits and Needs you (WFL-07), workflows in git (WFL-08), pruned history (WFL-04), one scheduler (WFL-09), the stack's node (WFL-06), the step service (WFL-05). |
| Kept from the engine design (GEN-11, GEN-21, GEN-22, GEN-25 to GEN-27, GEN-29 to GEN-32) | 10 | Kept, the Temporal wording gone (DEC-52); each says what is not wired to n8n yet. The runner's own environment became PLT-37. |
| Conductor and tasks (TSK-05, TSK-06, TSK-08, TSK-10, TSK-11, TSK-21, TSK-22, TSK-36, TSK-42, CRW-01, APP-11 …) | about 60 | Intent kept (every task has a page, steps survive restarts, headroom, one trace, one decision queue); "the Conductor" becomes "the task's workflow in n8n". TSK-21 and TSK-22 (everything through the Conductor) are retired at the end. |
| Schedulers (crew timers, mission schedules, event rules) | about 70 | Mostly unchanged in intent; the trace moves from timers and the runner to `n8n/workflows/*.json`. |
| New: workflows (WFL) | 13 | n8n in the core; its database and secrets; privacy; pruning; the step service; the stack's own node; Run now; Ask the owner through Needs you; workflows in git; one scheduler; Home shows n8n runs; Workflows in the menu; n8n's command node off. |

## 6. Code: what changes

| Code | Lines | Fate |
|---|---|---|
| Temporal runner, bridge, cutover, preview, projector, client, worker, converter, graph, templates, activities | about 2,600 | removed (DEC-52); the step service's runner side is `ops/flows.py` |
| The Temporal upgrade path, its configuration, compose's four Temporal services, its SDK in the runner, the builder and the app | about 500 | removed (DEC-52) |
| Block editor (its sources and Node build stage), the graph template format and its demo templates | about 3,000 | removed (DEC-52) |
| The codec and Runs proxy (`server.engine.py`), the Engine, Runs and Templates screens | | removed in the app's clean-up |
| Packs, trackers, places, artifacts, record, roles, draft pull requests | about 1,300 | kept, in `ops/domain/` |
| `ops/conductor.py` (1,215) | | its step runners stay behind the step service; its schedule path went on 10 Nov 2026 (WFL-12); graph walking and fan-out stay for the runs n8n starts |
| `ops/crew.py` (1,285) | | each job stays a command the step service runs; its timers went on 10 Nov 2026, its schedule is read from its workflow |
| `ops/missions.py` (1,296), `ops/events.py` (623) | | a mission's schedule became its task's workflow and the bus's time source went (10 Nov 2026); the rules on what n8n cannot see, the inbox, state and threads stay |
| systemd timers (26) | | crew and sync timers became workflows and were removed (10 Nov 2026); the boot check, the backup and the restore drill keep theirs (they must run when n8n is down) |
| New | | `compose` n8n service, `config/n8n`, `n8n/workflows`, the step service (`ops/flows.py`, `images/mission-control/server.flows.py`), the stack's own node (`n8n/custom/AistackStep.node.js`), `ops/n8n_sync.py`, tests |

Net: the stack shrinks by several thousand lines and from four schedulers to one.

## 7. Plan

Each phase ends in something the owner can look at. Nothing moves without a switch that can be turned back. Progress
is reported as "X of Y moved".

| Phase | What | Exit |
|---|---|---|
| 0. Stable | Disk guard (PLT-36) and the boot check (stack_ready) fixed and landed | the runner starts within a minute of a boot |
| 1. n8n in the core | The service, database, secrets, privacy settings, pruning, tests; the owner opens it on the tailnet and creates the account | n8n answers on the tailnet; the owner can sign in |
| 2. Foundation | The step service, the node package, the git export and import, Home and Needs you integration | a test workflow runs a Hermes step and waits for the owner's tap |
| 3. Move | Briefings and plans (5), then crew jobs (23) one switch each, then change requests, missions, event rules | 0 work left on the timers, the Conductor and Temporal |
| 4. Remove | Temporal, the Conductor's scheduling, the editor and its screens, the timers; requirements rewritten | one scheduler; the app's menu as in §4.3 |

Owner steps: `tailscale serve --bg --https=8450 http://127.0.0.1:5678` on Windows (once; and the fallback's
`--set-path=/n8n` line in `ops/windows/host-setup.ps1`), the n8n owner account (once, in the app's Workflows page), a
look at each phase's result.

## 8. Status (10 Nov 2026)

| Phase | State |
|---|---|
| 0. Stable | Done: the disk guard (PLT-36) and the boot check (it waited for tools MEM-28 had replaced) are live |
| 1. n8n in the core | Done: n8n 2.44.7 runs in the core, its data in Postgres, on the tailnet at port 8450; the owner's account is the one step left |
| 2. Foundation | Done: n8n inside the app at /n8n/ behind the app's gate (WFL-14), the Workflows page, Where it runs and In workflows (WFL-11); the step service with the whole block palette (§3.3: agent, coding change, crew job, plan task, ask, notify, recall, remember, run command, run a plan), the stack's own node with live pickers (WFL-06), Run now on every scheduled workflow (WFL-13), workflows in git imported by deploys, Home's feed, Workflows in the desk menu |
| 3. Move | Done: 25 of 25 scheduled jobs moved on 10 Nov 2026 (20 crew jobs, 5 plan tasks). Three more jobs left their timers for workflows the same day (vault ingest, the trial rotation, the nightly restart), inactive until their switch. Missions on a schedule and new scheduled tasks get their workflows from the runner (`ops/n8n_jobs.py`) |
| 4. Remove | Mostly done: Temporal, the graph runner and the block editor with their requirements (DEC-52); the crew's 23 timers (a deploy deletes their installed copies), the Conductor's schedule path, the missions' own schedule check, the event bus's time source, the crew's schedule form and Temporal's two secrets (WFL-12). Left: the app's Engine, Runs and Templates screens and their proxy (the app's clean-up) |

**The scheduler, now:** n8n starts every scheduled job. systemd keeps three timers, for what must run when n8n is down:
the boot check, the backup and the restore drill (ops/systemd/AGENTS.md). The event bus keeps the sources n8n cannot
see (news, prices, filings, mail, the house, files, the calendar, finished tasks), which start tasks by rule (TSK-11)
or a task's next run (TSK-21). Not on n8n yet: the weekly self-review's own clock inside the runner. n8n does not catch
up a time the PC was off.

## 9. Risks

| Risk | Answer |
|---|---|
| An execution that dies mid-step is marked crashed | Long steps run in the runner, not in n8n; n8n only waits, and waits survive restarts |
| Workflows live in n8n's database | Exported to git; deploys import from git |
| The licence | Free for personal and internal business use; selling the stack as a product would need a commercial n8n licence |
| A second sign-in | Tailnet only; one more login on the desk |
| Disk on C: | The image is 1.8 GB; the disk guard (PLT-36) prunes the build cache when C: runs low |
| n8n's own upgrades | Pinned by digest; upgraded in the update path after two weeks' age |
