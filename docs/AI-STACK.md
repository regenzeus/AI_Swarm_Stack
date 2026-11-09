# The AI Stack: packs, a durable engine and a canvas for agents

Written 9 November 2026. **Status: signed off by the owner on 9 November 2026 with the amendments in §16 and the
review's five additions (GEN-36 to GEN-39, and Temporal as core); decision DEC-50. Nothing of it is built yet.** It carries on from
[PLATFORM.md](PLATFORM.md) (DEC-45: the stack is a platform, home is one deployment) and makes real the item that
[GENERALISATION.md](GENERALISATION.md) parked: "plugin manifests, Bitbucket, Jira … only for a real domain that needs
them". A work deployment now needs them. It sent a change request for a ticket-to-patch loop that runs for weeks per
ticket, with the person who asked in the loop. This document is the stack's answer, said for any domain. Requirements
GEN-21 to GEN-39, *planned*.

**The owner's direction (9 Nov):**
- reuse professional tools rather than build from scratch;
- see how the agents work together, as with Lego Mindstorms;
- the engine is Claude's call, decided by research, not by an experiment;
- work sites will have 64 GB, and home runs slim with SSD swap.

## 1. The decision in one table

| Piece | We take | Instead of building |
|---|---|---|
| Durable runs that wait for weeks | **[Temporal](https://temporal.io)** (MIT), on the Postgres we already run | Waits, timers, retries, leases and a run history in the Conductor |
| Templates you can see and draw | **[Workflow Builder](https://github.com/synergycodes/workflowbuilder)**'s editor (Apache 2.0, built on React Flow) | A graph editor of our own |
| Agents, skills, MCP servers in packs | **Claude Code plugin folders** and the **`SKILL.md` format** (Claude Code and Hermes both read it) | A pack format of our own |
| Commands from packs, with trust | **The worker protocol** we have (`ops/winjobs.py`, PLATFORM.md §6) | Nothing new: Temporal activities hand jobs to it |
| Tracker and Bitbucket writes | **`atlassian-python-api`** (Jira, Confluence, Bitbucket Data Center) | Hand-written REST calls |
| Agents reading the tracker | **`mcp-atlassian`** in read-only mode | An MCP server of our own |
| Which agent may use which tool | **[agentgateway](https://github.com/agentgateway/agentgateway)** (Linux Foundation), when grants are built | Per-agent config of our own |
| Seeing a run end to end | **Temporal's web UI** plus **OpenTelemetry into Phoenix**, which we run already | A tracing view of our own |

What stays ours, because nothing outside does it for us:
- the worker trust model (approved hashes, typed values, patch path checks, a separate account);
- the change loop and its judge;
- the model policy and the data guard;
- the decision queue and autonomy levels;
- the app;
- one generic graph runner, about one module, that runs a template on Temporal.

## 2. Layers

| Layer | What it holds | Where |
|---|---|---|
| **Platform** (the core) | the engine (Temporal and our graph runner), the change loop and its judge, the worker protocol, trackers and forges, memory, the record, the app and its canvas | `ops/`, `images/`, `compose/`, `config/` |
| **Domains in the repository** | home's kinds of work: briefings, shopping, the phone, mail | their modules, each behind a feature |
| **Packs** | a domain kept outside the repository: agents, skills, commands, templates, rules, exams | their own git repository, pinned by commit |
| **Deployments** | one installation: hosts, features, model policy, data class, egress, packs, roles, pools, trackers | `deployments/<name>/`, which may live outside the repository |

**The boundary.** The core names no domain. This is proven three ways:
- the core's tests pass with no pack loaded;
- a toy pack, copied to a folder outside the repository, runs end to end;
- the guard (SEC-22) refuses every listed work term in every commit, commit message and push. Its list is private, so no test spells the terms out.

## 3. The engine: Temporal (GEN-33)

**Why Temporal.** It has the durable-execution pieces the request needs, as standard parts:

| The request needs | Temporal's part |
|---|---|
| One run per ticket, never started twice | A workflow id per ticket (`<pack>/<template>:<item>`) and *signal with start*: the tracker poller signals the run, or starts it if there is none |
| Waiting days or weeks for a reply, for nothing | A signal wait; a waiting run holds no process, slot or memory |
| Reminders and timeouts | Durable timers |
| Places: here, the WSL host, Windows | Task queues, one per place |
| Capacity pools | One task queue per pool, with the worker's limit on running activities as the pool's size |
| Retries, heartbeats, lost work found again | Activity retry policies and heartbeats |
| A history of every step | The workflow's event history, in its web UI |

**Why not DBOS.** It is lighter (a library on Postgres), but its dashboard is a proprietary product, and running it
yourself in production needs a licence key. Seeing the agents work together is the point, so that decides it. §13
lists the other tools and why they were not taken.

**How it runs:**
- **Core, not a feature.** The Conductor will be retired, so the engine cannot be switched off; every deployment runs it, home too. The slim setup is one Temporal container in the `core` compose services, with its own database in our existing Postgres and SQL visibility, so no Elasticsearch.
- **One Temporal namespace per deployment,** so two deployments on one machine never see each other's runs.
- **Footprint:** about 250 MB idle, by a published measurement; we measure it here when it lands.
- **Web UI:** behind the app's gate, embedded as a screen the way the code map is.
- **Workers:** one Python worker process (the Temporal Python SDK) in the runner, polling the task queues. Its activities are the stack's existing functions: a Claude step, a change, a worker job, a tracker call, a decision in the queue.

**Customer data never enters the history (GEN-36).** Temporal stores the input and output of every activity, signal
and workflow in its database. That database is in our Postgres, and Postgres is backed up. Three rules apply:
- **References only.** Workflows, activities and signals pass references: an artifact's hash, a path, a ticket key, a commit, a verdict's pass and its problem count. They never pass content: no file, no extract, no diff, no item text, no model output. Content stays in the artifact store and the worker folders, which keep their data class.
- **Enforced by the data converter, not by care.** On a customer-class deployment, the stack's data converter refuses any payload that is not a known reference shape, or that is larger than a few kilobytes (a tagged limit, `refuses`). An activity that tries to return content fails at once, in tests as in production.
- **Encrypted, and kept off the NAS.** A payload codec encrypts every payload with a key the deployment keeps by secret name. On a customer-class deployment, the Temporal database is also left out of every backup that leaves the machine, and the backup's guard test proves it. Home, whose data is personal, keeps it in the backup.

The web UI shows payloads, so it sits behind the app's gate. It decodes them only through a codec server that runs
beside it, behind the same gate, with the same key. Without the key, the UI shows ciphertext.

**Versions while runs wait for weeks (GEN-37).** Temporal replays a workflow's history against its code, so code that
changes under a running workflow breaks the replay. Templates and the runner are versioned separately:
- **A run pins its template.** When a run starts, an activity loads the graph from the pack's commit approved at that moment, so the graph is recorded in the history. The runner reads only that recorded copy. Editing a template on the canvas changes new runs, never a run in flight; a run that should take the new version is restarted on purpose, from a step the owner names.
- **The runner's own code changes by Temporal's versioning,** with patches or worker versions, so old runs finish on the path they started on.
- **A replay test guards every runner change.** Recorded histories of toy runs, one per block and per state, are kept in the repository. Before any change to the graph runner lands, Temporal's replayer runs them all against the new code, and a non-deterministic change stops the landing.

**History stays small (GEN-38).** Temporal caps one workflow's history at about 50,000 events or 50 MB. A coder and
judge loop with retries, weeks of reminders and a fan-out over hundreds of items could reach that. So:
- **Fan-out runs as child workflows.** The parent's history holds one start and one result per item, and the items' work fills their own histories. Very large lists start their children in batches, within Temporal's limit on pending children (a tagged limit).
- **Each change runs as a child workflow,** so its rounds of coding, building and judging never land in the ticket's history.
- **The runner continues as new** when Temporal suggests it, and after every long wait. It carries over the pinned graph reference, the current blocks, the loop counters, the wait keys and the timers still due. The ticket keeps one workflow id across these continuations, so signals still find it.
- **Payloads are references,** so the size limit is far away.
- **The health board shows each run's history size** next to its age.

**The Conductor's future.** One engine is the goal, and "everything is a task" (DEC-46) stays true throughout:
1. Pack templates run on Temporal first. Each run is also a row in the Tasks tab's table, so the app shows one list.
2. Home's fixed plans (the change loop, briefings, scheduled tasks) move to templates.
3. The planner's free plans become graphs that the same runner runs, and the Conductor is retired.

Each stage lands alone, with home's whole check green. Two engines run side by side only during this move, and the
move has an end condition: **once every kind of home plan has run on Temporal for 14 days with nothing falling back to
the Conductor, the next landing removes the Conductor.** The health board counts those days, per kind of plan.

## 4. Templates are graphs (GEN-23)

A template is a graph of blocks, stored as YAML in the pack's repository so every change is a reviewable diff. The
canvas (§5) draws and edits it. Its nodes and edges map one to one onto Workflow Builder's JSON.

| Block | What it does | Runs as |
|---|---|---|
| **Agent** | an agent card does a step: prompt, model alias, tools | a Claude step activity |
| **Command** | an approved job kind at a place | an activity that hands the job to the worker protocol and waits |
| **Change** | the coder and judge loop, from a named base ref | the change activity we have, or a child workflow |
| **Gate** | a role says yes or no | a decision in the queue, then a signal wait |
| **Wait** | for an outside party on a key, with reminders and a timeout | a signal wait with timers |
| **Tracker** | comment, summary, attach, transition, label | an activity that passes its action class |
| **Branch** | one path, by a condition on earlier answers | the runner's choice |
| **Fan-out** | one block over a list from an earlier answer, then join | parallel activities, paced by their pool |
| **Loop back** | send failures back to an earlier block, a set number of times | the runner's loop |

```yaml
template: toy/bug
budget: {tokens: 2000000, days: 60}
nodes:
  intake:    {block: agent, agent: toy:intake, title: Read the item and ask what is missing}
  reply:     {block: wait, for: requester, key: item, remind: [3d, 7d], timeout: 21d, then: triager}
  reproduce: {block: command, kind: toy.reproduce, values: {input: item.attachment}}
  spec:      {block: agent, agent: toy:analyst, title: Write acceptance criteria}
  approve:   {block: gate, role: spec-approver}
  implement: {block: change, base: item.version, target: release}
  regress:   {block: command, kind: toy.regress, each: spec.items, pool: tool}
  classify:  {block: agent, agent: toy:classifier, loop: {to: implement, max: 3}}
  deliver:   {block: tracker, call: comment, gate: delivery-approver}
  accepted:  {block: wait, for: requester, key: item, timeout: 42d, then: triager}
edges: [[intake, reply], [reply, reproduce], [reproduce, spec], [spec, approve], [approve, implement],
        [implement, regress], [regress, classify], [classify, deliver], [deliver, accepted]]
```

**The graph runner** is one Temporal workflow, written in Python, that runs any template.
- It loads the pinned graph through an activity (GEN-37), walks it, runs each block as its activity or child workflow (GEN-38), and waits on signals and timers.
- Everything it passes is a reference (GEN-36).
- It keeps every rule the Conductor keeps today. A gate, a wait and a check are always kept: nothing may drop them.
- A budget stops a run with its reason, as a tagged limit.
- Workflow Builder ships a runner of its own (TypeScript, no loops). We use its editor and its live view, not its runner.

## 5. The canvas: building with blocks, watching them run (GEN-34)

One screen in the app holds Workflow Builder's editor, built once and kept in the repository at a pinned version. It is
the app's only React page; the rest stays plain JavaScript.

- **Draw.** Drag blocks, connect them and set their values. The palette holds the blocks of §4 and the pack's agents and job kinds.
- **Describe.** Say in chat what the template should do. The planner drafts the graph, and it opens on the canvas for you to adjust.
- **Save.** Saving writes the YAML on a branch of the pack's repository. The new commit waits for approval like any pack commit (§6), and the diff shows in the queue.
- **Watch.** A running task opens on the same canvas, read-only: each block lights up as waiting, running, done or failed, with its agent's latest output, its cost and its artifacts. States stream from the runner to the page.
- **Dig deeper.** From any block, open Temporal's history for that step, or its model calls in Phoenix.
- **The YAML is the source of truth.** The canvas reads and writes it without losing anything; a round-trip test loads every template, saves it unchanged, and compares the bytes. Block positions live in a separate file beside it (`<name>.layout.json`), so moving blocks never shows as a change in review.
- **If the editor fades,** nothing is lost: templates run without it, and React Flow underneath is a widely used library.

## 6. A pack (GEN-21)

```
<pack>/
  .claude-plugin/plugin.json   Claude Code's plugin manifest: name, version, description
  agents/<name>.md             agent cards: Claude Code's subagent format (front matter, then the prompt)
  skills/<name>/SKILL.md       skills
  .mcp.json                    MCP servers the pack's agents may use, by name
  stack.yaml                   what only the stack knows: agent harness and model alias, autonomy classes, event rules, grants
  jobs/<kind>.json             commands: job kinds of the worker protocol
  templates/<name>.yaml        templates (§4)
  exams/<set>.yaml             historical cases, each with its known outcome
```

**Loading and names.**
- The deployment lists its packs in `packs.txt`, one per line: name, git URL or path, commit.
- Each pinned commit is checked out read-only and merged with the core.
- Names are namespaced by the pack (`toy:intake`, `toy.reproduce`, `toy/bug`), as Claude Code namespaces a plugin's skills, so packs cannot clash.
- A pack named like a core module or another pack is refused, with the reason.

**Trust.**
- A pack is approved per commit. A new commit is one decision in the queue, with the security floor: it always asks, and it shows the manifest, the prompts, the commands and the diff.
- Until the owner says yes, the deployment keeps running the last approved commit.
- Job kinds are still copied into each worker's `jobs.d` and approved there, file by file. So a command never runs on the pack's word alone.

**Running a pack agent.** Its step runs Claude Code with `--plugin-dir` set to the pack, under the deployment's model
policy, like every Claude step.

## 7. Places and the workers (GEN-22)

A Command block runs at a place. Each place is a Temporal task queue, and behind it sits the worker protocol, unchanged:

| Place | Runs | For |
|---|---|---|
| `wsl` | in the runner or the builder sandbox, as today | everything the core does |
| `windows` | the Windows worker (PLATFORM.md §6) | Windows-only tools |
| `wsl-host` | the same protocol on the WSL host, as its own Linux user `aiworker` | licensed or vendor tools that cannot go in a container |

- **Windows stays pull-only.** The activity writes the job into the worker's folders and waits with a heartbeat, so Windows never connects to Temporal and never receives code from it.
- **The WSL-host worker** is `ops/fakeworker.py` made real.
  - **Its user:** it runs as the Linux user that owns the deployment's licensed tools and repositories, which may not be the user the stack runs as. The deployment names that user in its folder.
  - **Setup:** that user may have no sudo, so the owner does the sudo part once: either a system unit with that user set, or `loginctl enable-linger` for that user plus a user unit.
  - **Tests:** the fake worker stays for them.
- **A toolchain is wherever its job kind is approved.** The worker's `status.json` already says which kinds are approved and the tool versions they report.
- **Per-change values** reach a job as its typed parameters, so the kind's ranges are the allowed set.
- **Checks during the coder's loop.** The coder may start a check job against its current diff with one allowed command, and gets the verdict back in the same build. Runs per build are paced by a tagged limit.

## 8. Trackers and the forge (GEN-25, GEN-26)

**The poller.** Each tracker the deployment lists in `trackers.yaml` is polled with a cursor, through
`atlassian-python-api` for Jira Data Center and the forge code for Forgejo issues.
- Each change signals the run named after its item, or starts it, so a restart never starts a template twice.
- Polling is the default, because a work PC cannot be reached from the tracker. A webhook receiver can come later, behind a feature.

**Writes.**
- Every write is an activity that passes an action class with a level: `tracker-comment` starts at 0 and may rise to 1; attach and transition carry the people floor.
- Temporal runs each activity once per step, and a write id makes a retry harmless. The stack's single summary comment is edited, never duplicated.
- **Shadow mode is per kind of write,** not per tracker. Comment, summary, attach, transition and label each start in shadow: writes go to a log and the queue, never outward. Comments can go live long before transitions do.
- **Leaving shadow mode has a stated measure.** A kind of write leaves shadow on the owner's tap, once the owner has approved its shadow output on a number of items the deployment sets. The queue shows the count so far.

**Data and reading.** The data guard applies: a customer-class deployment sends item text only to the gateway's models.
Agents read the tracker through `mcp-atlassian` in read-only mode, with its host on the egress list.

**The forge.**
- A change starts from the base ref its template names (a tag or a branch).
- It pushes `ai/<item>-<slug>` through `FORGE_PUSH` (GEN-18) and opens a draft pull request into the template's target branch.
- Pull-request comments signal the run, through the same poller.

## 9. Gates name roles (GEN-27)

A gate names a role, and the deployment's `roles.yaml` maps each role to people. The decision records who answered.
- Until sign-in exists (GEN-12), every answer in the app is the owner's, and a role mapped to someone else says so.
- Gates answered by tracker comments are not built: comments can be edited or written by someone else.

## 10. Pools, artifacts and tool grants (GEN-28, GEN-29, GEN-30)

**Pools.** The deployment's `pools.yaml` names its pools and their sizes, for example `tool: 2` and `claude: 4`.
- Each pool is a task queue, and its size is the worker's limit on running activities. A fan-out of 10 on a pool of 2 never runs 3 at once.
- A lost activity's heartbeat stops, and Temporal gives the work back.

**Artifacts.** Files are kept by their SHA-256 in `/srv/ai/artifacts/`, with one row naming the task, step, run and commit
that made them, their data class and the deployment's retention (a tagged limit). Temporal carries only their ids.

**Grants.** A pack gives each agent its MCP servers and commands; the step gets exactly those, through
`--mcp-config` and `--allowedTools`. When grants grow beyond that, agentgateway takes over the check per tool, with its
traces in Phoenix.

## 11. The record and exams (GEN-31)

- **The chain:** Temporal's history, our task row and Phoenix's traces together hold every step, decision, cost and model call.
- **Export:** one zip with the run's JSON and an HTML page a person can follow without the app: item, spec, commits, runs, artifacts, decisions.
- **Exams:** a pack's exam cases, each with its known outcome, run through the replay exam, before the deployment goes live and before any class is promoted.

## 12. Updates (GEN-32)

`packs.txt` pins commits. An update verifies the stack's signed tag (PLATFORM.md §7 H), and checks that every pinned pack
commit is approved. A new commit waits in the queue while the old one runs.

**Temporal's own upgrades (GEN-39)** are the update path's job, never a manual step:
- Temporal is pinned like every other image.
- Its database schema is upgraded with Temporal's own tool (`temporal-sql-tool`), and the server steps through each minor version in turn, as Temporal requires.
- An update that moves Temporal first snapshots its database on the machine; on a customer-class deployment that snapshot never leaves it. It then runs each schema step and each server version in order, checks that the server answers and that the replay test passes, and goes back to the snapshot when any step fails.

## 13. Tools considered and not taken

| Tool | Why not |
|---|---|
| DBOS | Its dashboard is proprietary and needs a licence key to self-host in production |
| Windmill | Its native Windows workers are an Enterprise feature, and it duplicates our tasks, schedules and secrets |
| n8n | Its licence is restrictive, and its workflows live in its database, not in git |
| Airflow, Prefect | Batch pipelines first. Airflow 3.1 can pause for a person, but the model is a DAG of batch tasks |
| Argo Workflows | Needs Kubernetes |
| LangGraph, Langflow | They run their own agents in their own process; ours are Claude Code and Hermes |
| Zigflow, Serverless Workflow YAML | A standard YAML format on Temporal, but no visual editor and two maintainers; the canvas mattered more |
| Workflow Builder's own runner | TypeScript, and no loops; our Python runner keeps one language and loops |

## 14. Footprint and limits

- **Size:** Temporal's server and UI add about 300 MB. Home runs it too, with SSD swap; work sites have 64 GB.
- **Pool sizes from measurement:** the first work site measured its licensed tool: 2 parallel runs were 1.5 times faster than one, and at 4 the licence check refused a run. Its pool is 2.
- **Limits:** every new limit is tagged and listed, and each is the deployment's to set: budgets, runs per build, retention, pool sizes, the payload size a customer-class converter accepts, and the batch of children a fan-out starts at once.
- **Nothing here** sends anything outside, or merges, without its gate.

## 15. Order

Each step lands alone, between exam arms, with home's whole check green and no change in what home does.

1. **This design, signed** by the owner.
2. **The walking skeleton**, against stand-ins and with a toy pack:
   - the Temporal service and the graph runner, with the reference-only converter, the payload codec, the pinned graph, child workflows, continue-as-new and the replay test from the first landing: these are hard to add later;
   - the pack loader;
   - a Command block on the worker protocol;
   - a gate and a wait;
   - the tracker poller with signal-with-start, comments and shadow mode;
   - a branch from a tag, and a draft pull request.

   It ends in one test that takes a toy item from created, to a draft pull request plus a comment plus a wait, to the reply, the resume and the close, across a restart of the worker and of the server.
3. **The canvas:** the editor, chat drafting, saving to the pack's git, and the live view.
4. The WSL-host worker, pools, artifacts, checks during the coder's loop.
5. Home's fixed plans move to templates, then free plans; 14 days with no fallback per kind of plan, and the Conductor is removed (GEN-35).
6. Roles, the record export, pack exams, agentgateway grants, pinned updates.

## 16. The sign-off, with its conditions

The owner signed off on 9 November 2026. A review on the work deployment's side checked the claims and added five
things: references only in the history (GEN-36), pinned templates and the replay test (GEN-37), small histories
(GEN-38), Temporal as core with an end condition for the move (GEN-33, GEN-35), and upgrades by the update path
(GEN-39). All five are written in above.

| # | Question | Decision |
|---|---|---|
| 1 | Pack names namespaced (`pack:agent`, `pack.kind`) | Yes, and one Temporal namespace per deployment as well (§3) |
| 2 | The WSL-host worker's user and unit | Yes. It runs as the user that owns the deployment's tools and repositories, which the deployment names. The owner does the sudo part once: a system unit, or lingering plus a user unit (§7) |
| 3 | Shadow mode first | Yes, per kind of write, not per tracker; each leaves shadow on the owner's tap, after a stated number of approved shadow items (§8) |
| 4 | Packs approved per commit, job kinds on their worker | Yes. A pack update asks for a worker approval again only when a job's file, and so its hash, changes |
| 5 | The canvas as one pinned React page | Yes, with the YAML as the source of truth: a lossless round trip, positions in a separate file, and templates that run without the editor (§5) |
