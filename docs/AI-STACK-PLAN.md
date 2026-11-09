# The AI Stack, built as one big bang: the implementation plan

Written 9 November 2026. It implements the signed design in [AI-STACK.md](AI-STACK.md) (DEC-50, GEN-21 to GEN-39).

**The owner chose a big bang.** Everything in the design is built together on one integration branch, and home switches
to it in one cutover. That changes only the order of the design's §15, not what is built:

- **One integration branch.** All work packages are built on it, each with its tests, and its whole check stays green there. Main keeps taking only urgent fixes until the cutover, and the integration branch takes in main every day.
- **One cutover landing, deployed dark.** It brings Temporal, the graph runner, the packs, trackers, canvas and the rest. The new engine starts idle, and the cutover script switches home to it only after its smoke checks pass.
- **The Conductor stays as the rollback for 14 days,** switched off but still in the code. The signed condition (GEN-35) becomes the end of that window: once every kind of home plan has run 14 days on Temporal with nothing falling back, the next landing deletes it.

## 1. Versions to pin

Looked up on 9 November 2026. The rule: take the newest patch that is at least 14 days old when the work package
starts, check its release notes, and record the pin in the image or the requirements file.

| Part | Newest now | Notes |
|---|---|---|
| Temporal server (`temporalio/server`) | 1.32.2 (2 Nov) | Postgres through the `postgres12` plugin, which serves Postgres 12 and later; ours is 17.11 |
| Temporal admin tools (`temporalio/admin-tools`) | 1.32.2 (3 Nov) | `temporal-sql-tool` for schema setup and upgrades; run once per setup or update, never left running |
| Temporal web UI (`temporalio/ui`) | 2.58.1 (6 Nov) | behind the app's gate, with the codec server |
| Temporal Python SDK (`temporalio`) | 1.35.0 (28 Oct) | worker, workflows, `Replayer`, the time-skipping test environment |
| `atlassian-python-api` | 5.0.5 (14 Sep) | Jira, Confluence and Bitbucket Data Center |
| `mcp-atlassian` | 0.24.1 (8 Nov) | read-only mode; too new, so take the release before it |
| `@workflowbuilder/sdk` / `ui` | 3.0.0 / 1.0.0 (2 Oct) | the editor; Apache 2.0 |
| `@xyflow/react` | 12.12.1 (2 Nov) | React Flow, under the editor; MIT |
| `react` | 19.3.1 (14 Oct) | for the canvas page only |
| agentgateway | v1.7.0 (27 Oct) | tool grants (WP16) |

## 2. What the Conductor does today, and where each part goes

`ops/conductor.py` (1,285 lines, 54 functions) is imported by 11 modules and touched by 20 test files. The mapping:

| Conductor today | In the AI Stack |
|---|---|
| `graph()`, `fold_builders()`: check a plan and turn it into steps | **The graph model:** a plan converts one to one into a graph (`step`, `agent`, `after`, `each`, `loop` become nodes and edges); the same checks, refusals and limits, now over graphs |
| the step table (`task_steps`) and `put`, `steps`, `state`, `occurrences` | **A projection:** the app's tables stay; a projector writes each run's node states into them, so the Tasks tab, the task page, the Network view and the journeys read what they read today |
| `tick()`, `worker()`, `ready()`, `recover()` | **Temporal:** the worker polls; recovery is replay |
| `run_hermes`, `run_claude`, `run_build`, `run_check`, `run_wiki`, `run_opencode`, `run_python`, `run_temp` and the domains' step kinds (`ops/changes.py`, `ops/desk_steps.py`, `ops/shop_steps.py`) | **Activities**, moved almost unchanged; `ops/stepkinds.py` keeps its registry and refusals and now registers activities |
| waits for a usage limit or the NAS (`waiting_for`) | activity retry policies with backoff, shown as waiting with the reason |
| `free_gb()`, `headroom()`: memory before a step | the same check at an activity's start; without headroom it waits with a heartbeat, and never fails |
| `spent()`, `over_budget()` | the runner's budget, checked before each block (a tagged limit) |
| `checkpoint()`, `between_waves()`: the Orchestrator looks again between waves | a checkpoint activity between waves of a free plan, whose answer (the new remainder of the graph) is recorded in the history; templates have none |
| loops (`again()`, TRL-08) | the runner's loop-back edge |
| `cancel()`, `stop_at_door()` in `ops/tasks.py` | workflow cancellation |
| `fire()`, `event_of()`: an event starts or feeds a task | signal-with-start |
| `due()`, `next_run()`: rhythms and schedules | **Temporal Schedules**, one per scheduled task |
| `handoff()`, `result_file()`: outputs are files, passed by reference | unchanged; this is already the references-only rule (GEN-36) |
| `prompt_of()`, `step_memory()`, `wiki_context()`, `routed()` | unchanged helpers, called by the activities |
| `gate()`, `recorded_item()`, `triggers_proof()`: its own checks | the same checks against the projection |

**Not moved in the cutover:**
- missions' own runs (`ops/missions.py`, the shopping and phone runs);
- the Claude task queue (`ops/claude_tasks.py`, whose limit `CLAUDE_PARALLEL` becomes the `claude` pool).

They are not Conductor plans, and they become templates afterwards.

## 3. New and changed files

New, under a new package named engine in `ops/` (paths given in plain text because they do not exist yet):

| File | What it holds |
|---|---|
| ops/engine/client.py | the Temporal client: namespace per deployment, start, signal-with-start, cancel, query, schedules |
| ops/engine/converter.py | the references-only data converter, the payload codec (AES-GCM, key by secret name) and the size limit |
| ops/engine/graph.py | the graph schema, its checks, plan-to-graph, the YAML and layout files, the round trip |
| ops/engine/runner.py | the one generic workflow: blocks, gates, waits, loops, fan-out as children, changes as children, continue-as-new, budget, checkpoints, the state query |
| ops/engine/activities.py | the harness adapters and step kinds moved from the Conductor, plus load-pinned-graph, decision, tracker, command, artifact |
| ops/engine/worker.py | the worker thread in the host runner: task queues per place and pool, OpenTelemetry into Phoenix |
| ops/engine/projector.py | run states into the app's tables, and a stream for the live canvas |
| ops/engine/migrate.py | the cutover: drain, move scheduled and open tasks, switch, roll back |
| ops/engine/upgrade.py | Temporal's schema and server upgrades for the update path (GEN-39) |
| ops/packs.py | the pack loader, names, approval per commit |
| ops/trackers.py | Jira Data Center and Forgejo issues, the poller, writes as action classes, shadow per kind of write |
| ops/artifacts.py | files by hash, with their record |
| ops/record.py | the export of a run as one bundle |
| ops/worker_host.py | the WSL-host worker, the fake worker's code run for real |
| config/templates/ | home's fixed plans as templates: the change sizes, the briefing, the desk, shopping |
| images/mission-control/canvas/ | the canvas page's source, built in the image from a pinned lock file |
| tests/fixtures/packs/toy/ | the toy pack |
| tests/fixtures/histories/ | recorded toy histories for the replay test |
| tests/standins/ | Jira and tracker stand-ins next to the Bitbucket one |

**Changed:**

| File | Change |
|---|---|
| `ops/tasks.py` | `conduct()` and `dispatch()` start runs on the engine; cancel goes to the engine; rhythms become schedules |
| `ops/missions.py` | starts the engine worker and the projector in place of the Conductor's tick |
| `ops/changes.py`, `ops/desk_steps.py`, `ops/shop_steps.py` | their step kinds register as activities; their fixed plans become templates |
| `ops/staffing.py`, `ops/provenance.py`, `ops/repofacts.py`, `ops/onboard.py`, `ops/shopping.py`, `ops/mission_extras.py`, `ops/journeys.py` | read the projection instead of the Conductor's functions (`CD.steps`, `CD.put`, `CD.run_of`) |
| `ops/stepkinds.py` | registers activities; `where` adds `wsl-host`; a kind may name its pool |
| `ops/events.py` | `fire` signals or starts; the tracker and pull-request sources |
| `ops/decisions.py` | a gate's decision carries its role; answering it signals the run |
| `ops/winworker.py` | the command activity's half of the folder protocol |
| `ops/builds.py`, `ops/forge.py` | a change from a named base ref; pull-request comments as signals |
| `ops/backup.sh` | dumps databases one by one and leaves the Temporal databases out on a customer-class deployment |
| `ops/update.py` | runs the Temporal upgrade steps (GEN-39) |
| `compose/core.yaml` | the Temporal server and its UI join the core; Postgres gets the Temporal databases and their role |
| `config/gate/` | the gate in front of the Temporal UI and its codec server |
| `images/mission-control/server.py` and the app's static files | the canvas screen, the live stream, the engine's health, pool leases, history size, the 14-day count |
| `requirements/*.yaml`, `docs/` | status per requirement as it lands; the guide gets the canvas |

## 4. Work packages

Each package lands on the integration branch with its own tests. "Done when" is its acceptance, taken from the
requirement it serves.

| WP | What | Serves | Needs | Done when |
|---|---|---|---|---|
| 0 | **Preparation:** branch and worktree, pins, the Temporal test server and CLI binaries fetched through the package proxy, the Temporal databases and role in Postgres, the codec key's secret name, the exam held | — | — | the integration branch's whole check is green before any change |
| 1 | **The engine service:** Temporal server and UI in the core, schema set up by the admin tools, one namespace per deployment, the gate and codec server, the backup's database list | GEN-33, GEN-36 | 0 | the server starts with the core on home and on the work example; two namespaces never list each other's runs; the backup on the work example names no Temporal database |
| 2 | **The engine library:** client, worker thread, converter and codec, OpenTelemetry into Phoenix | GEN-33, GEN-36 | 1 | on the work example, an activity returning file content fails in the converter; a stored payload is ciphertext; a run's spans reach Phoenix |
| 3 | **The graph model:** schema, checks, plan-to-graph, YAML plus layout file, lossless round trip | GEN-23, GEN-34 | — | every plan the Conductor's tests build converts, and is refused or kept for the same reasons; every template round-trips byte for byte |
| 4 | **The graph runner:** blocks, gates, waits with keys and timers, loops, fan-out as children in batches, changes as children, continue-as-new, budget, checkpoints, the state query, the pinned graph, the replay test | GEN-23, GEN-24, GEN-37, GEN-38 | 2, 3 | the toy template survives a restart of the worker and of the server in each state; a 300-item fan-out with 6 change rounds and 20 reminders stays under a tenth of the history limit; the replay test fails a non-deterministic change |
| 5 | **The activities:** every harness adapter and domain step kind, waits as retries, memory headroom, the command activity on the worker protocol | GEN-22 | 4 | each adapter's existing tests pass as activity tests; a Windows job still runs only with its approved hash |
| 6 | **The app on the engine:** dispatch, cancel, events, schedules, the projector, the Tasks tab and task page unchanged in what they show | GEN-35 | 5 | the Tasks tab, the task page, the Network view and the nightly journeys pass unchanged against runs on Temporal |
| 7 | **Cutover tooling:** drain, migrate scheduled and open tasks, switch, roll back, the 14-day count on the health board | GEN-35 | 6 | on a copy of home's state, every open and scheduled task moves, resumes at its step, and moves back on rollback |
| 8 | **Packs:** loader, names, approval per commit, `--plugin-dir`, `stack.yaml`, job kinds copied to the workers | GEN-21, GEN-32 | 4 | the toy pack copied outside the repository runs end to end; a clash and an unapproved commit are refused |
| 9 | **Trackers and the forge:** Jira and Forgejo issues, the poller with signal-with-start, writes as action classes, shadow per kind of write, stand-ins, a branch from a tag, pull-request comments as signals | GEN-25, GEN-26 | 4 | on stand-ins: one run per item across a restart, the summary edited not duplicated, nothing outward in shadow, a draft into a release branch, a reviewer comment resumes the run |
| 10 | **Roles on gates** | GEN-27 | 4 | two gates wait for two roles; an answer from outside a role is refused and recorded |
| 11 | **Places and pools:** the WSL-host worker under the deployment's named user, task queues per place and pool, the coder's check command | GEN-22, GEN-28 | 5 | a 10-item fan-out on a pool of 2 never runs 3; a check's verdict reaches the coder in the same build |
| 12 | **Artifacts** | GEN-29 | 4 | a toy zip is attached to a stand-in item, and its record names its commit and run |
| 13 | **The canvas:** the editor built in the image, the block palette, the YAML adapter, the layout file, save to a pack branch for approval, the live view, drafting from chat | GEN-34 | 3, 6 | journey: a template is drawn, saved, approved and run, and the canvas shows each block change state |
| 14 | **The record export and pack exams** | GEN-31 | 6 | a toy run exports a bundle a person can follow; a toy exam set runs and scores |
| 15 | **Temporal upgrades in the update path** | GEN-39 | 1 | an update across two minor versions on a test database runs each step in order; a failing step restores the snapshot |
| 16 | **Tool grants:** pack grants, then agentgateway | GEN-30 | 8 | a granted agent reaches a stand-in MCP tool, an ungranted one cannot, a server off the egress list is refused |
| 17 | **Docs, guide and requirements** | all | each | every requirement's status matches what landed; the guide explains the canvas behind its info control |

**Critical path:** 0, 1, 2, then 3 and 4 together, then 5, 6, 7. **In parallel after WP4:** 8 to 12, 14 and 16. The
canvas (13) needs 6, and the upgrades (15) need only 1. Packages on separate files run in parallel sessions, each in its
own worktree.

**The canvas has a fallback.** If Workflow Builder's SDK cannot read and write our YAML losslessly, WP13 uses React Flow
directly, with our own block palette. The YAML stays the truth either way.

## 5. Moving home's state at the cutover

Everything lives in `missions.sqlite` today. Each kind of task moves this way:

| Kind | Moves as |
|---|---|
| A scheduled task (a rhythm) | a Temporal Schedule with the task's id and rhythm; its next due time is kept |
| A plan task not yet started | a run started on the engine with its plan as a graph |
| A plan task in flight | a run started with its graph and its done nodes marked done, each with its output's reference, so the runner begins at the first open node. A step that was running is started again: steps are already idempotent, as the Conductor's recovery requires |
| A step waiting for a usage limit or the NAS | the same step, as an activity that retries |
| A task waiting for the owner | a gate or a wait in the run, with its decision still in the queue |
| A finished task | stays as it is; its history stays in the old tables, read-only |
| An event rule | unchanged: rules live in `ops/events.py`, and fire now signals or starts |

**Rollback.** Open runs are cancelled, and their tasks go back to the Conductor with the nodes done so far, so the same
move works in reverse. The script keeps a log of every task it moved, in both directions.

## 6. The cutover, step by step

1. **Hold:** the replay exam is held (its hold file), and the app shows that an upgrade is under way.
2. **Back up:** a full backup of home, including `missions.sqlite` and Postgres, checked by its drill.
3. **Land dark:** the integration branch lands with its whole check and the privacy scan. Temporal starts with the core; the engine worker starts idle; the Conductor still runs.
4. **Smoke checks** on the live machine:
   - Temporal answers and the UI opens behind its gate;
   - a toy run starts, waits, is signalled and finishes;
   - the replay test passes;
   - the converter refuses content on a customer-class test namespace.

   If any check fails, nothing switches.
5. **Drain:** no new task starts; running steps get up to 30 minutes to finish (a tagged limit); the rest are moved as in §5.
6. **Move and switch:** the migration runs, the runner restarts on the engine, and the Conductor's tick stays off.
7. **Verify:**
   - the nightly journeys run at once, including the decide journey and the screen check in every window shape;
   - one real small change, one briefing and one scheduled task are each run through.
8. **Watch for 14 days:** the health board counts the days per kind of plan. Any fallback resets that kind's count and is a finding. A rollback is the script's reverse.
9. **Remove the Conductor:** the landing after the 14th clean day deletes `ops/conductor.py` and the switch.

**The work deployment** takes the release through its signed tag. It has no plans in flight to move, and its trackers
start in shadow mode for every kind of write.

## 7. Tests

- **Unit and workflow tests** use Temporal's time-skipping test environment, so waits of weeks run in seconds. Its binaries come through the package proxy and are pinned like the rest.
- **The replay test** runs over tests/fixtures/histories on every change to the runner, inside the landing's checks.
- **Ported tests:** the Conductor's tests become graph and runner tests. The 20 test files that touch it keep their sentences, so what is proven stays the same.
- **End to end with stand-ins:** the toy pack takes an item from the tracker stand-in to a draft pull request on the Bitbucket stand-in, through a gate, a wait, a reply and the close, across restarts.
- **Customer class:** the converter, the codec and the backup's database list, on the work example.
- **Load:** the 300-item fan-out and the history size.
- **Journeys and screens:** the nightly journeys and the screen check in every window shape, unchanged, against runs on the engine.

## 8. Risks, and what answers each

| Risk | Answer |
|---|---|
| A big bang hides which part broke | Each package lands on the integration branch with its own tests; the cutover lands dark and switches only after smoke checks; rollback is scripted |
| Workflow code that is not deterministic | One small workflow module with no I/O, Temporal's sandbox, and the replay test on every change |
| Memory on home's WSL (9 GB visible) | Temporal adds about 300 MB; the worker runs inside the host runner, not as a new process; it is measured at WP1, and SSD swap covers peaks |
| The canvas SDK's API differs from what we need | The React Flow fallback (§4); the YAML stays the truth |
| The integration branch drifts from main | Main's fixes are taken in every day; main takes only urgent fixes until the cutover |
| The replay exam runs during the work | The exam stays held until the cutover is verified |
| Content slips into the history | The converter refuses it on customer class, and its test runs in every landing |

## 9. Preparation checklist

| Item | State |
|---|---|
| The design signed (DEC-50) | done |
| Versions looked up and the pin rule set (§1) | done |
| The Conductor's callers and parts mapped (§2) | done |
| The work packages, the state move and the cutover written (§4 to §6) | done |
| The integration branch and its worktree | at WP0 |
| The Temporal test binaries allowed through the package proxy | at WP0 |
| The Temporal databases and role, and the codec key's secret name | at WP0 |
| The replay exam held for the build | at WP0, by its hold file |
| The WSL-host worker's user and unit on a work machine | the owner's step, at WP11, only where a deployment needs it |
