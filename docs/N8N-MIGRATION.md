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
| Tracker polling (Jira, Forgejo) | our adapters, called by the crew job tracker-poll on n8n's schedule; each event routed by the run register (§3.6) |

**Stays, unchanged in what it does:** Hermes, the swarm, the coding agents and their sandbox, OpenCode, Claude Code
tasks, LiteLLM and the subscriptions, the memory system (Hindsight, wikis, journals, the Memory Keeper's rules),
chat, the phone, the house, the mail copy, backups, Phoenix, Open WebUI, the app's Home, Needs you and task pages,
packs, places, artifacts and the record of a run.

**In one line:** n8n decides when and in what order; our services do the work.

## 3. Design

```
                        n8n (core service, tailnet or this PC only)
   triggers: schedule, webhook (a tracker item's run too), Gmail, Telegram, calendar
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
  the app is down. No public exposure. A deployment without the tailnet keeps all of it on the PC (§10).
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
sends its work to the step service and waits for the answer. An answer that failed, was refused or cancelled fails
the block, so the run ends as an error in n8n's history; an answer with an outcome (a wait on an item) is a result. A
question (`ask`) may name a role of the deployment (GEN-27): only its people may answer, and the answer says who did. The Agent, Crew job, Place and Repository pickers read the stack's lists live
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
| Wait for the item (`wait_item`) | the run waits on its tracker item: outcome `reply` with the new comments from others, or `timeout` after `timeout_hours`; a timeout is a result the workflow branches on (an IF node), not a failure | the run register (§3.6, WFL-20) | built |
| Write to the item (`tracker`) | one write: comment, summary, attach, link, transition or label; answers with the shadow or the live reference. `from_step` adds an earlier step's whole answer from the run register, so n8n never carries the text | trackers.write, shadow per kind (WFL-21) | built |
| Coding change for an item (`build` with `item`, `base`, `target`) | the branch `ai/<item>-<slug>` starts at the base ref or tag; with FORGE_PUSH a draft pull request into the target branch, directly (DEC-54); review comments wake the run | builds onto that branch, forgework.publish (GEN-26) | built |
| Report | what Home shows for each step, with the n8n run | the step service itself (WFL-10) | built, not a block |

Every scheduled workflow also has a **Run now** trigger (WFL-13): `POST <n8n>/webhook/run/<file stem>` starts it at
once, while it is published.

### 3.4 Git stays the truth
- Workflows live in `n8n/workflows/<name>.json`. A job exports changes made on the canvas (`n8n export:workflow
  --backup`) and commits them through the landing path; a deploy imports the repository's workflows
  (`n8n import:workflow --separate`). Built-in git sync is a paid feature and is not needed.
- A work deployment keeps its workflows in its pack repository, never in the public one (SEC-22's terms). The
  approved commit's workflows are imported as `<pack>/<name>` under ids made from that name (GEN-43); an approval or
  refusal syncs them at once, a deploy too. A canvas edit of a pack's workflow is a proposal: it goes to the pack's own
  repository as a branch `ai/canvas-<date>` and a draft pull request where the pack's forge allows, and the approved
  version is imported again; the edit runs once a commit with it is approved. A pack's workflow with a node outside
  the deployment's `N8N_NODES_INCLUDE` (the data guard's list, §10) is refused at load (GEN-42). How a new commit meets the runs that wait: §11.

### 3.5 Temporal
Not needed. n8n's waits plus the step service cover runs that wait for days; the tasks table plus steps that are
safe to repeat cover restarts. Plans went back to the Conductor on 10 Nov 2026 at 10:40, and Temporal was removed the
same day (DEC-52): its services and databases' setup, its upgrade path, its SDK, the graph runner, the bridge, the
cutover, the codec, the graph template format and the block editor.

### 3.6 Tracker items and the run register
n8n cannot find a waiting execution by a business key, so the step service keeps the map: the **run register**
(`ops/runreg.py`, `/srv/ai/missions/flows/register/`, WFL-23) is the stack's record of every run n8n drives, next to the
tasks table. It holds each step's request, whole answer, files (artifact ids) and times by its n8n run; each tracker
item's runs (with their executions) and the wait registered on it; and the ledger of routed events. n8n holds time and
order only.

**Routing** (WFL-19). The crew job **tracker-poll** runs on n8n's minute (`crew-tracker-poll.json`, inactive until a
deployment with trackers publishes it) and asks the trackers every `poll_minutes` of the deployment's trackers.yaml (5
by default). `trackers.poll()` and `forgework.poll_prs()` hand their events to the register's outbox before their
cursors move; each event is then placed once by (tracker, key, the change's identity), also across a restart:

| The item | The event | What happens |
|---|---|---|
| a run waits on it (`wait_item`) | brings new comments from someone else | the wait is answered: outcome `reply`, with the comments |
| has no run yet | any | the item's workflow starts: `POST http://127.0.0.1:5678/webhook/item/<pack>/<name>` (n8n's root, never under `/n8n/`) with `{tracker, key, run, ref, comments}`; the item is marked first, so an event never starts two runs |
| its run goes on, busy elsewhere | brings comments | recorded; the run's next `wait_item` takes them at once |
| its run has ended (n8n's execution finished) | brings a new comment | a new run only when the tracker says `restart: on_comment` (default `never`) |
| any | brings no new comments (the stack's own write changes the item too) | recorded; it never wakes a wait |

An event n8n does not take (n8n down, the workflow not published) stays in the outbox for the next pass. A pull
request's review comments come back the same way: its key is the item's (`<tracker>/<key>`).

**The item's workflow** starts with a Webhook trigger, POST, path `item/<pack>/<name>` (the tracker's `workflow`), and
answers at once with its execution: Response Data `={{ JSON.stringify({execution: $execution.id}) }}`, so the register
knows the run's execution from its start (shown on n8n 2.44.7 on 10 Nov 2026). Without it the execution is learnt from
the run's first wait or tracker write. Its waits loop: `wait_item` → IF `{{ $json.outcome }}` is `timeout` → a reminder
(`tracker`, comment) → `wait_item` again.

**Lean answers** (WFL-22). In a customer-class deployment (data.yaml `class: customer`) n8n gets the status, the
outcome, the ids and references (task, step, build, pull request, artifacts, tracker writes) and a summary of at most
300 characters; the whole answer stays in the register and the task's record. `n8n_answers: full` in data.yaml
relaxes it. A step's brief still travels in n8n's execution as the workflow wrote it. A tracker write that should carry
an earlier step's text names that step (`from_step`): the step service takes the whole answer from the register, so
the text goes to the tracker (in shadow first) without passing through n8n.

**A run's record** (GEN-31, WFL-23): `python3 ops/runreg.py export <execution> <zip>` (record.export_run): each step in
order with its request and whole answer, its task's record, the files by artifact id and hash, the tracker writes with
their shadow or live references, the pull request, and the workflow's shape from git or the pack cache.

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

### 4.4 Status (10 Nov 2026, DEC-53)
Built on `feat/n8n-ux`, each fold its own commit with its tests; [UX.md](UX.md) is the app's design now.

| §4.2 finding | What became of it |
|---|---|
| 39 screens behind 6 menu entries | The menu above (APP-64); Engine, Runs and Templates are gone, their old links land on Workflows; Packs and Trackers are one section of Stack → Connections; Share has its list (`#/share`) and Home links it; Home has its own address (`#/home`) |
| Runs on seven screens | One place: the task page (Where it runs, its steps and each step's log, Sources, Timeline) and Workflows → Runs (APP-63). The task map is the task page's Sources; Telemetry is Stack → Costs (the agents, day by day); `#/swarm` was already the Tasks views; `#/live/<run>` stays as a step's log |
| The Stack page is a drawer | Health, Costs, Tools, Connections, Settings (APP-62); the House is on Home's Overview, memory figures and the tidy on Memory, a memory to approve in Needs you, the guide on its own page (`#/guide`) one tap from Stack |
| Old names in the start-page picker | The menu's names; an old choice still opens the right page |
| "Not connected" meant an old file | It says the stack is starting, the runner stopped (and since when) or did not start; "Not connected" only when the app does not answer (APP-65) |
| The desk's CSS zoom | Kept for the app; undone on a tool's frame, where it misplaced clicks |
| Jargon on screens | Plain words on the screens touched; the type scale and one set of components (APP-67) |
| (new) Tools in separate tabs | Phoenix is inside the app at `/phoenix/` (Traces), like n8n (APP-66); Hermes admin, OpenCode, the code map dashboard and Open WebUI take no sub-path and keep their own tab |

## 5. Requirements: what changes

Of 858 requirement items, about 160 trace to code n8n touches. Most keep their intent and change their mechanism.

| Group | Count | What happens |
|---|---|---|
| Temporal engine (GEN-23, GEN-24, GEN-28, GEN-33 to GEN-39) | 10 | Retired on 10 Nov 2026 (DEC-52), each naming what replaced it: n8n in the core (WFL-01), its waits and Needs you (WFL-07), workflows in git (WFL-08), pruned history (WFL-04), one scheduler (WFL-09), the stack's node (WFL-06), the step service (WFL-05). |
| Kept from the engine design (GEN-11, GEN-21, GEN-22, GEN-25 to GEN-27, GEN-29 to GEN-32) | 10 | Kept, the Temporal wording gone (DEC-52); each says what is not wired to n8n yet. The runner's own environment became PLT-37. |
| Conductor and tasks (TSK-05, TSK-06, TSK-08, TSK-10, TSK-11, TSK-21, TSK-22, TSK-36, TSK-42, CRW-01, APP-11 …) | about 60 | Intent kept (every task has a page, steps survive restarts, headroom, one trace, one decision queue); "the Conductor" becomes "the task's workflow in n8n". TSK-21 and TSK-22 (everything through the Conductor) are retired at the end. |
| Schedulers (crew timers, mission schedules, event rules) | about 70 | Mostly unchanged in intent; the trace moves from timers and the runner to `n8n/workflows/*.json`. |
| New: workflows (WFL) | 24 | n8n in the core; its database and secrets; privacy; pruning; the step service; the stack's own node; Run now; Ask the owner through Needs you; workflows in git; one scheduler; Home shows n8n runs; Workflows in the menu; n8n's command node off; and for the first work deployment (§12): n8n on the PC without the tailnet, the app's gate, the node allowlist, executions on the PC, tracker items, wait_item, tracker writes, lean answers, the run register, pack updates in place. |

## 6. Code: what changes

| Code | Lines | Fate |
|---|---|---|
| Temporal runner, bridge, cutover, preview, projector, client, worker, converter, graph, templates, activities | about 2,600 | removed (DEC-52); the step service's runner side is `ops/flows.py` |
| The Temporal upgrade path, its configuration, compose's four Temporal services, its SDK in the runner, the builder and the app | about 500 | removed (DEC-52) |
| Block editor (its sources and Node build stage), the graph template format and its demo templates | about 3,000 | removed (DEC-52) |
| The codec and Runs proxy (`server.engine.py`), the Engine, Runs and Templates screens | | removed in the app's clean-up (DEC-53) |
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
| 4. Remove | Done: Temporal, the graph runner and the block editor with their requirements (DEC-52); the crew's 23 timers (a deploy deletes their installed copies), the Conductor's schedule path, the missions' own schedule check, the event bus's time source, the crew's schedule form and Temporal's two secrets (WFL-12), and the app's Engine, Runs and Templates screens with their codec and Runs proxy (DEC-53) |

**The scheduler, now:** n8n starts every scheduled job. systemd keeps three timers, for what must run when n8n is down:
the boot check, the backup and the restore drill (ops/systemd/AGENTS.md). The event bus keeps the sources n8n cannot
see (news, prices, filings, mail, the house, files, the calendar, finished tasks), which start tasks by rule (TSK-11)
or a task's next run (TSK-21). Not on n8n yet: the weekly self-review's own clock inside the runner. n8n does not catch
up a time the PC was off.

**The first work deployment** (the CR of 10 Nov 2026, §12): built the same day. Tracker items start and wake runs
through the run register, packs' workflows run in n8n, jobs of hours wait their turn at a place, and a customer-class
deployment runs n8n on the PC with its logic nodes and lean answers. Its whole path is one test against stand-ins
(GEN-44), and it ran once on a throwaway n8n 2.44.7.

## 9. Risks

| Risk | Answer |
|---|---|
| An execution that dies mid-step is marked crashed | Long steps run in the runner, not in n8n; n8n only waits, and waits survive restarts |
| Workflows live in n8n's database | Exported to git; deploys import from git |
| The licence | Free for personal and internal business use; selling the stack as a product would need a commercial n8n licence. A deployment where the stack serves a third party (its work done for someone outside the deployment owner's own business) needs n8n's commercial licence: that is the deployment owner's decision. The core uses none of n8n's paid features, and the step service stays orchestrator-neutral |
| A second sign-in | Tailnet only; one more login on the desk |
| Disk on C: | The image is 1.8 GB; the disk guard (PLT-36) prunes the build cache when C: runs low |
| n8n's own upgrades | Pinned by digest; upgraded in the update path after two weeks' age |

## 10. A customer-class deployment

A deployment whose data class is customer (`deployments/<name>/data.yaml`, GEN-14) has the tailnet off, like every
feature that sends data out. `deployments/example-work` is the example. What n8n and the app do there:

- **On the PC only (WFL-15).** n8n's editor address is the app's on the PC, `N8N_EDITOR_URL=http://127.0.0.1:8090/n8n/`,
  and its webhooks and resume URLs are n8n's own, `N8N_WEBHOOK_URL=http://127.0.0.1:5678/`; port 5678 stays on
  127.0.0.1, and there is no port 8450. Compose takes both from the deployment and falls back to the tailnet's
  addresses (home). `python3 ops/deployment.py check` (run by `make up`) refuses a deployment without the tailnet whose
  addresses are elsewhere.
- **The app's gate follows the deployment (WFL-16).** With the tailnet the app admits a request by Tailscale's identity
  header, as before. Without it (`APP_GATE=local`) no such header exists: the app is published on 127.0.0.1 only, so a
  request that names the PC itself (`127.0.0.1`, `localhost`, `::1`, or the app's service name for the stack's own
  checks) is the owner's, under one local login, and any Tailscale header it brings is dropped. Another host name is
  refused, which keeps out a page of another site whose name was made to point at the PC. A write from another site is
  refused under both gates (SEC-20). n8n and Phoenix inside the app work the same way; n8n is told the browser used
  http, and its secure cookie holds on 127.0.0.1 and localhost (n8n's own rule; Safari is the exception). Open the app
  at `http://127.0.0.1:8090` on the PC.
- **Only the logic nodes (WFL-17).** n8n loads the schedule, webhook and manual triggers, wait, if, switch, merge,
  loop (`splitInBatches`), set, no-op, sticky note, execute workflow and its trigger, respond to webhook, and the AI
  Stack step: `N8N_NODES_INCLUDE` in the deployment, handed to n8n as `NODES_INCLUDE`. No HTTP Request, Code, Jira,
  Bitbucket or mail node: the work reaches systems only through the stack's steps, their approvals and shadow mode.
  The list is `N8N_NODES` in `ops/dataguard.py`; the data guard refuses a customer deployment with no list or a node
  off it. `dataguard.n8n_nodes()` gives the code the deployment's list (a tuple of node types, or None when n8n loads
  every node, as at home), so a pack's workflow with a node off it is refused. Checked on a throwaway n8n 2.44.7 on
  10 Nov 2026: with the example's list it loaded those 15 node types and no other (n8n's include rule also leaves out
  every node of a package the list does not name, the AI nodes among them).
- **Execution data stays on the PC (WFL-18).** n8n keeps every node's output in its database, and an agent step's
  whole text is its output. Its database is in the stack's Postgres (volume `pgdata`) and its home is the volume `n8n`;
  both are local volumes, every published port is on 127.0.0.1, and n8n sends no diagnostics or version pings. They
  leave the PC only through the backup (feature `home`, `ops/backup.sh`) and its off-site copy (`offsite`), which
  customer data has off: the data guard checks all of it (`ops/dataguard.py check`, `stays_local`).

## 11. Pack updates and waiting runs (N8, tested 10 Nov 2026)

A pack's workflows run in n8n (GEN-43, `ops/n8n_sync.py sync_packs`), and its runs may wait days or weeks for an
answer. Before building on that we tested, on a throwaway n8n 2.44.7 (the pinned image, its own Postgres on a private
network, never the live one), what n8n does to a waiting execution when its workflow changes under it. The workflow:
a webhook, a Set node, a Wait node resumed by its webhook, and a Set node after it that writes its version. Each case
started a run, let it wait, then changed the workflow the way `ops/n8n_sync.py` does (import under the same id,
publish, restart) and resumed the run through its resume URL.

| Case | What changed while the run waited | The resumed run |
|---|---|---|
| a | the node after the wait changed (v1 to v2) | succeeded, on v1 |
| b1 | the node it waits on renamed | succeeded, on v1 |
| b2 | the node it waits on removed | succeeded, on v1 |
| c | the workflow unpublished | succeeded, on v1 (the resume URL answered 404 for the first two seconds after the restart, then 200) |
| d | the workflow unpublished and archived | succeeded, on v1 |
| e | a trigger 0 s after import, publish and restart | the new run started on the *previous* version; once n8n had settled (6 s later) new runs started on the new one |
| f | executions backdated 40 days, pruning at 1 hour and 1 execution, every minute | the five finished runs were soft-deleted after one minute and then removed; the two waiting runs stayed and resumed, each succeeding |
| f | the container removed and recreated with other settings (time zone, log level, pruning) on the same database | both waiting runs survived and resumed |

**Why:** n8n keeps a copy of the workflow with each execution (`execution_data.workflowData`, with its
`workflowVersionId`) and resumes from that copy, not from the workflow as it is now. Pruning soft-deletes only
executions whose status is not `new`, `running` or `waiting` (`softDeletePrunableExecutions` in n8n's execution
repository), so the 720-hour age (WFL-04) never removes a run that still waits. Publishing in n8n 2.44 goes through a
publication outbox that the server works off after it starts; until then the version published before still answers
the workflow's triggers (case e: 3 to 14 s in our runs).

**The rules (WFL-24, GEN-43):**
- A pack's new commit is imported **in place**, under the same ids. No versioned copies: a run waiting in the old
  commit's version finishes on that version, whatever the new one renamed or removed, and runs that start after the
  import take the new version. The same holds for the stack's own workflows on a deploy.
- A waiting run of an old version calls the step service with the agents and job kinds that run *now* (the pack's new
  commit): its workflow is old, its agents are current. A pack update that removes an agent or job kind a waiting run
  still needs makes that step fail with the step service's reason; cancel such runs in n8n before approving.
- A pack refused or removed has its workflows unpublished: no new run starts, and its waiting runs still finish. To
  stop them, cancel them in n8n's executions.
- For a few seconds after a sync's restart a trigger can still start a run on the previous approved version; that run
  is complete and consistent, only older. Both versions were approved by the owner.
- Pruning is safe for long waits; only finished runs age out.
- Not tested: an n8n upgrade to another minor version with runs waiting. No second pinned n8n image was on the machine,
  and pulling one (about 1.8 GB) was outside this change; the container was recreated with changed settings on the
  same database instead (case f). The next n8n upgrade must repeat case f with the new image before it lands.

The sync itself ran against the same throwaway n8n, with the AI Stack step node loaded: approving the toy pack
imported `toy/bug`, `toy/ticket` and `toy/triage` under ids starting with `pack` and `item/toy/ticket` answered 200; an edit
of `toy/ticket` left in n8n went to the toy's own repository as `ai/canvas-2026-11-10` and the next sync put the
approved version back; removing the pack from packs.txt unpublished all three and the webhook answered 404.

## 12. The first work deployment (CR of 10 Nov 2026)

The CR asked the stack to carry a customer-class deployment on a work PC: a tracker item starts a run, agents triage
it and ask the reporter, the run waits days for the answer with reminders, a licensed tool runs for hours at the WSL
host, a coder makes a change from a tag, a draft pull request goes to the forge. It added nothing about that domain to
the core: the domain comes as a pack, and everything here is tested with the toy pack and stand-ins. The design, in
one place:

- **The run register is the run's truth; n8n holds time and order** (DEC-54, WFL-23, §3.6). What a step asked,
  answered and made is in the register and the task's record; a run's zip is made from them and the workflow's shape
  from git or the pack cache, never from n8n's API.
- **The data class sets up n8n** (§10). Customer data: no tailnet, so n8n and its editor are on 127.0.0.1; only the
  logic nodes and the AI Stack step, from the data guard's one list (`dataguard.n8n_nodes()`, which the pack check
  reads too); executions on the PC; lean answers (status, ids, a summary). A tracker write that should carry an
  earlier step's text takes it from the register (`from_step`), so the text never passes through n8n.
- **The outside-write rule.** Every write to a system outside the stack waits in shadow per kind until the owner lets
  that kind go live (GEN-25, WFL-21). The one stated exception is a draft pull request (DEC-54): a change for an item,
  with FORGE_PUSH, and a canvas edit sent back to its pack go out as drafts directly; nobody uses a draft until they
  merge it, and the stack never merges.
- **Pack workflows** (GEN-42, GEN-43, §3.4): the approved commit's workflows are in n8n as `<pack>/<name>`; a canvas
  edit is a proposal to the pack's repository; a new commit is imported in place and a waiting run finishes on its
  version (the N8 rule, §11).
- **Places for jobs of hours** (GEN-40): one job at a time per worker, a queued request never given up while the
  worker is busy, a job kind's own run limit.

**The end-to-end test** (GEN-44, `tests/test_work_deployment.py`, in the suite): a stand-in n8n runs the toy's item
workflow node by node as n8n does, around the real step service and run register, a stand-in tracker, forge and
builder, the local worker in a temp folder, and example-work's data class and node list. The item starts one run (also
when its event comes twice), the triage's whole text is commented in shadow, the stack's own comment does not wake the
wait, the wait times out to a reminder and a second wait, a reply wakes it, the toy tool runs at wsl-host with another
run's job queued behind it, a draft pull request goes to the stand-in forge from tag `v1.0`, a review comment wakes the
run, the summary is written in shadow and the run ends. The runner side is reloaded from disk mid-wait and mid-job,
n8n restarted mid-wait and mid-job; nothing is lost and each job is submitted once. n8n gets lean answers only, and the
zip holds every step. A second test greps the stand-in domain's names over `ops/`, `images/`, `compose/`, `config/` and
`n8n/` and finds nothing.

**The same flow on a real n8n** (10 Nov 2026): a throwaway n8n 2.44.7 (the pinned digest) with its own Postgres on a
private network, the AI Stack step node and example-work's node list (`NODES_INCLUDE`), the toy's item workflow
prepared and imported as `ops/n8n_sync.py` does (its tool's 600 s shortened to 20 s), and the step service's real
runner code (`ops/flows.py`, `ops/runreg.py`, the domain modules, the local worker) in a throwaway container on the same
network under the name `mission-control`, with the stand-ins above and a fixed triage in place of the agent's model
call. What happened:

| Step | Result |
|---|---|
| The item's first event, 1 s after n8n's restart | the webhook answered 404 (the publication not yet worked off, §11 case c), so the event stayed in the outbox; the next pass, 3 s later, started the run |
| The start | `item/toy/ticket` answered `{"execution": "1"}` (Response Data), so the register knew the run at once; the same change handed on again: `seen`, still one execution |
| Triage, comment | the agent step's answer went to n8n lean; the comment in shadow held the triage's whole text, taken from the register |
| The stack's own comment | `recorded`; the wait stayed |
| n8n restarted mid-wait | back in 5 s; the waiting run was there |
| 72 hours later (the register's clock moved on) | the wait answered `timeout`; the IF node took the reminder branch (a comment in shadow) and a second wait |
| The reporter's reply | `woke`; the IF node took the other branch to the toy tool |
| The toy tool at wsl-host, another run's job queued behind it, n8n restarted mid-job | both jobs done, one after the other (20 s apart); the answer reached n8n after its restart |
| The change | a draft pull request `ai/TOY-7-make-the-change` into `release/1` on the stand-in forge |
| The review comment | `woke` the wait for the review; the summary written in shadow; execution 1 ended `success` |
| n8n's database | one execution, `success`; its data holds a lean answer and none of the triage's last line (the register holds it whole) |
| The run's zip | agent, tracker, wait_item, tracker, wait_item, command, build, wait_item, tracker, with the three shadow writes |

All containers, the network and the volumes were removed afterwards; the live stack was not touched.
