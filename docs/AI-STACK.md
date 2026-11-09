# The AI Stack: packs, templates and work that waits for people

Written 9 November 2026. **Status: a design for the owner's sign-off. Nothing of it is built yet.** It carries on from
[PLATFORM.md](PLATFORM.md) (DEC-45: the stack is a platform, home is one deployment) and makes real the item that
[GENERALISATION.md](GENERALISATION.md) parked: "plugin manifests, Bitbucket, Jira … only for a real domain that needs
them". A work deployment now needs them. It sent a change request for a ticket-to-patch loop that runs for weeks per
ticket, with the person who asked in the loop. This document is the stack's answer, said for any domain. Requirements
GEN-21 to GEN-32, all *proposed* until the sign-off.

## 1. The idea in one paragraph

Domain knowledge moves out of the repository into **packs**, and the core learns to run long work that waits for people
outside the house. We build as little new as we can, because most of it exists under another name:

| The request asks for | What already does it | What is new |
|---|---|---|
| Domain commands with an approved hash, JSON in and out, a lease, artifacts | The Windows worker's protocol (`ops/winjobs.py`, `ops/fakeworker.py`, §6 of PLATFORM.md) | The same worker on a second place, the WSL host |
| Agents, skills, MCP servers and hooks from outside the repository | Claude Code's plugin folder (`--plugin-dir`, in the CLI the builder runs); skills in the `SKILL.md` format Hermes already reads | A small `stack.yaml` for what Claude Code does not know about |
| Workflow templates with loops, fan-out and gates | The Conductor's plan format: `step`, `agent`, `after`, `each`, `loop` (TSK-22, TRL-08), `fixed_plan` and `held` (TSK-36) | A template is a saved plan, plus a gate, a wait on a key and a budget |
| Waiting days or weeks | Step states `waiting`, `waiting_for` and `resume` | A key that an event must match, reminders, a timeout |
| A tracker as an event source | `ops/events.py` sources; events deduplicated by key | One tracker module, built like `ops/forge.py` |
| Write-back that passes gates | Autonomy classes and levels, the one decision queue (AUT-05) | Tracker writes as action classes; shadow mode |
| Pull requests on Bitbucket DC | `ops/forge.py` (GEN-04); `FORGE_PUSH` (GEN-18) | A branch from a named tag; pull-request comments as events |
| Capacity | `SLOTS`, the worker's `lock` and `needs_gb`, `CLAUDE_PARALLEL` | One lease table with named pools |

What we do **not** build: a plugin framework that imports a pack's code, a workflow server, a message broker or an
artifact service (§12).

## 2. Four layers

| Layer | What it holds | Where |
|---|---|---|
| **Platform** (the core) | the Conductor, templates, waits, the change loop and its judge, the worker protocol, trackers and forges, memory, the record, the app | `ops/`, `images/`, `compose/`, `config/` |
| **Domains in the repository** | home's kinds of work: briefings, shopping, the phone, mail | their modules, each behind a feature |
| **Packs** | a domain kept outside the repository: agents, skills, step kinds, templates, rules, exams | their own git repository, pinned by commit |
| **Deployments** | one installation: hosts, features, model policy, data class, egress, packs, roles, pools, trackers | `deployments/<name>/`, which may live outside the repository |

**The boundary.** The core names no domain. This is proven three ways:
- the core's tests pass with no pack loaded;
- a toy pack in tests/fixtures/packs/toy (new) is copied to a folder outside the repository, loaded from there, and runs end to end;
- the guard (SEC-22) refuses every listed work term in every commit, commit message and push. Its list is private, so no test ever spells the terms out.

## 3. A pack (GEN-21)

```
<pack>/
  .claude-plugin/plugin.json   Claude Code's plugin manifest: name, version, description
  agents/<name>.md             agent cards: Claude Code's subagent format (front matter, then the prompt)
  skills/<name>/SKILL.md       skills, in the format Claude Code and Hermes both read
  .mcp.json                    MCP servers the pack's agents may use, by name
  stack.yaml                   what only the stack knows (below)
  jobs/<kind>.json             step kinds: job kinds of the worker protocol (§4)
  templates/<name>.yaml        task templates (§5)
  exams/<set>.yaml             historical cases, each with its known outcome (§11)
```

`stack.yaml`:

```yaml
name: toy                        # the pack's namespace: toy:intake, toy.reproduce, toy/bug
needs: v2026.11.09               # the oldest stack release it works with
agents:                          # how each card runs as a Conductor step
  intake:  {harness: claude, role: reader}       # role: an alias of the deployment's model policy
  coder:   {harness: build}
classes:                         # autonomy classes it adds; each starts at level 0 and can never lower a floor
  toy-reply: {title: Reply to the requester, highest: 1, exam: toy-replies, what: "post a comment on the item"}
rules:                           # event rules: which tracker event starts which template
  - {on: tracker.created, where: {label: ai}, start: toy/bug}
grants:                          # tools per agent (§10)
  intake: {mcp: [tracker-read], commands: []}
```

**Loading.** The deployment folder lists its packs in `packs.txt`, one per line: name, git URL or path, commit.
ops/packs.py (new) checks out each pinned commit into `/srv/ai/packs/<name>@<commit>`, which agents can read and not write,
reads the manifest and merges the pack's contents with the core's:
- **Names are namespaced** by the pack's name, as Claude Code already namespaces a plugin's skills, so two packs cannot claim the same agent.
- A pack named like a core module or like another pack is refused, with the reason and whose name it is (`stepkinds.own`, as today).

**Trust.** A pack is approved per commit, as the worker approves a job kind per file hash:
- An unapproved commit becomes one decision in the queue, class `pack`, with the security floor, so it always asks.
- The decision shows the manifest, the agents' prompts, the job kinds' commands and the diff from the last approved commit.
- Until the owner says yes, the deployment keeps running the last approved commit.
- Job kinds are also copied into the worker's `jobs.d` and approved there, file by file, as today. So a command never runs on the pack's word alone.

**How a pack's agent runs.** A step on a pack agent runs Claude Code with `--plugin-dir` set to the pack, the card's
prompt, and the deployment's model policy, like every Claude step. The pack's skills and MCP servers come with it, after
the egress and data checks (§10). Hermes-harness pack agents wait until a pack needs one.

## 4. Step kinds are commands, and places are workers (GEN-22)

A pack's step kind **is** a job kind of the worker protocol. Nothing is added to the contract:
- typed parameters;
- argument lists, never a shell;
- patch path checks;
- `collect`, `minutes`, `needs_gb` and `lock`;
- approval by SHA-256.

The step's answer is the job's `artifacts/answer.json` when the kind writes one, and a check's verdict is its
`artifacts/verdict.json` (`{pass, problems, evidence}`, as the judge already reads). Packs stay language-neutral, and no
pack code runs in the runner's process.

**Places.** `where` gains a third value:

| `where` | Runs | For |
|---|---|---|
| `wsl` | in the runner or the builder sandbox, as today | everything the core does |
| `windows` | the Windows worker (PLATFORM.md §6) | Windows-only tools |
| `wsl-host` | the same worker protocol on the WSL host, as its own Linux user `aiworker`, over `/srv/ai/worker/wsl-host/` | licensed or vendor tools that cannot go in a container |

The WSL-host worker is `ops/fakeworker.py` made real:
- the same code, run by a systemd unit as `aiworker`;
- `jobs.d` and `approved.json` owned by the owner, which `aiworker` can read and not write;
- its own scratch folder, and the egress proxy for its network.

Creating the user and the unit is the owner's step (ops/worker-host-setup.sh (new), with sudo), as `worker-setup.ps1` is on
Windows. The fake worker stays for the tests.

**Toolchains need no registry.** A kind's toolchain is whichever places have that kind approved. The worker's
`status.json` already reports each approved kind, its hash and the tool versions its probe steps print. A step names a
kind, the Conductor sends it to a place where the kind is approved and free, and a kind approved in two places has
capacity in both.

**Per-change values** come from the task, such as the items a spec names or a tool version. They reach the job as its
typed parameters, so the kind's `enum` and `int` ranges are the allowed set. A value outside it refuses the job, with
which parameter and why.

**Checks during the coder's loop.** The coder gets one allowed command, `aistack-check <kind> [name=value ...]`. It
asks the runner to start that job against the build's current diff, waits, and prints the verdict. The judge still runs
the deployment's checks after the build, as today. Runs per build are paced by a tagged limit
(`# limit: paces`), which the deployment sets.

## 5. Templates: saved plans that may run for weeks (GEN-23)

A template is a plan in the format the Conductor already checks, written down in the pack:

```yaml
name: toy/bug
budget: {tokens: 2000000, days: 60}          # per task; replaces MAX_STEPS and LOOP_MAX for its tasks
steps:
  - {step: Read the item and ask what is missing, agent: toy:intake}
  - {step: Wait for the requester's answer, wait: {for: requester, key: "{item}", remind: [3d, 7d], timeout: 21d, then: triager}, after: [1]}
  - {step: Reproduce on the given input, kind: toy.reproduce, values: {input: "{item.attachment}"}, after: [2]}
  - {step: Write acceptance criteria, agent: toy:analyst, after: [3]}
  - {step: Approve the spec, gate: spec-approver, after: [4]}
  - {step: Implement, kind: change, values: {base: "{item.version}"}, after: [5]}
  - {step: Regression, kind: toy.regress, each: "{step 4.items}", after: [6]}
  - {step: Check regressions, agent: toy:classifier, loop: {to: 6, max: 3}, after: [7]}
  - {step: Post the branch and ask for feedback, tracker: comment, gate: delivery-approver, after: [8]}
  - {step: Wait for acceptance, wait: {for: requester, key: "{item}", timeout: 42d, then: triager}, after: [9]}
```

**What is new for the Conductor:**
- `kind` (a pack step kind), `gate` (§9), `wait` (§6) and `tracker` (§7) on a step;
- `budget` on a template;
- `each` taking a list from an earlier step's answer, expanded when that step finishes. Today `each` takes a list written into the plan. The limit `EACH` still applies.

A template's plan is fixed: checkpoints never look at it, and gate, wait and check steps are `held`. The planner does
not fill parts of a template. Its open work happens inside the `change` step, whose coder and judge already loop. Every
state lives in the Conductor's SQLite tables, so a restart in any state resumes where it was.

## 6. Waiting for someone outside (GEN-24)

A `wait` step sets its status to `waiting` with a **key**: here the tracker item, or a pull request. When an event
arrives, `events.fire` first checks for a waiting step with that key and, if there is one, resumes it with the event as
its input. An event without a matching key wakes nothing.

- **Reminders:** the runner's tick posts each reminder at its time as a tracker comment, and that comment passes its own class (§7).
- **Timeout:** the task goes to the queue of the role named in `then`.
- **No resources held:** a waiting step holds no slot, no lease and no process.
- **Visible:** the health board lists each long wait, what it waits for, and since when.

## 7. Trackers (GEN-25)

ops/trackers.py (new) gives one interface with two implementations, built like `ops/forge.py`. It uses the standard library
only, and credentials by secret name:

| Call | Jira Data Center (REST v2, personal access token) | Forgejo issues (home's, so home can test it) |
|---|---|---|
| `items(query, since)` | a JQL query plus `updated >` the cursor | issues updated since |
| `item`, `comments` | read | read |
| `comment` | add | add |
| `summary(key, text)` | edits the stack's one summary comment, found by an issue property | found by a marker line |
| `attach`, `link`, `transition`, `label` | yes | where Forgejo has them |

**The source.** A deployment lists its trackers in `trackers.yaml`: name, kind, address, secret name, query, and how
often to poll. Polling is the default, because a work PC cannot be reached from the tracker. A webhook receiver can come
later, behind a feature.

The tracker source keeps a cursor per tracker and emits `created`, `updated`, `commented` and `transitioned` events,
each with the item's key. Events are deduplicated by key, as all events are, so a restart never starts a template twice.
A pack's rules decide what an event starts.

**Writes.** Every outward write is an action class with a level:
- `tracker-comment` starts at 0, highest 1;
- `tracker-attach` and `tracker-transition` carry the people floor;
- a pack may add finer classes.

Each write has an id built from task, step and call, and a write log. A retry never posts twice, and the summary
comment is edited, never duplicated.

**Shadow mode** (`TRACKER_WRITES=shadow`, the default for every new tracker) writes nothing outward. Each write goes to
`/srv/ai/state/tracker-shadow.jsonl` and to the queue, so the deployment can run on live items while nobody outside
sees it. The data guard applies: a customer-class deployment sends item text only to the gateway's models, never to a
subscription model or a chat channel.

**Reading, for agents:** the open-source `mcp-atlassian` server in its read-only mode. The deployment adds it as an MCP
server, and its host must be on the egress list. We do not write our own.

Tests run against a tracker stand-in (tests/standins/jira.py (new), standard library only), as the forge is tested against
its Bitbucket stand-in.

## 8. The forge: a branch from a named tag (GEN-26)

- A change may name `base`, a tag or a branch. Its build clones at that ref instead of the default branch.
- A template names the pull request's `target` branch.
- The branch is `ai/<item>-<slug>`, pushed through `FORGE_PUSH` (GEN-18), and opened as a draft. The stack never merges on a work deployment.
- Pull-request comments become events through the same poll as the tracker, with the pull request as the key, so a reviewer's comment resumes a waiting step.

## 9. Gates name roles (GEN-27)

A gate step names a role. The deployment's `roles.yaml` maps each role to the people who hold it. The decision item
carries the role, and the answer records who gave it.
- **Until sign-in exists (GEN-12):** every answer in the app is the owner's. A role mapped to someone else says so in the queue, and cannot be answered there.
- **Gates answered by tracker comments are not built.** A comment can be edited or written by someone else, so that waits for a decision of its own.

## 10. Capacity, artifacts and tools

**Pools (GEN-28).** The deployment's `pools.yaml` names its pools and their sizes, for example `tool: 2`,
`memory_gb: 48`, `claude: 4`.
- A step kind or job kind names the pool it takes. The worker's `lock` is a pool of one, `SLOTS` becomes the pool `steps`, and `CLAUDE_PARALLEL` becomes the pool `claude`.
- Leases live in one SQLite table and carry a heartbeat. A lease with a stale beat is freed, by the worker's own rule.
- Waiting steps are served oldest first, taking tasks in turn.
- The board shows each pool's leases.

**Artifacts (GEN-29).** Files are kept by their SHA-256 in `/srv/ai/artifacts/`, with one row per file: its name, kind,
size, data class, and the task, step, run and commit that made it.
- A worker job's artifacts are taken in when the job ends.
- A step can hand an artifact to `tracker.attach` or to the forge.
- Retention is the deployment's, as a tagged limit (`# limit: drops`).
- Binary files in patches stay refused.

**Tools per agent (GEN-30).** A pack's `grants` give each agent MCP servers by name and allowed commands. The step gets
exactly those, through `--mcp-config` and `--allowedTools`, as Claude steps do today. `servers_for()` already drops a
server the data class or the egress list does not allow. Tools that write to the outside exist only as tracker or forge
calls, so they pass gates.

## 11. The record of a journey, and pack exams (GEN-31)

A task's record already holds every step, attempt, cost and event.
- **Export:** the new ops/record.py, run as *export* with a task writes one zip: `record.json`, plus one HTML page a person can read without the app. The page follows the chain: item, spec, commits, runs, artifacts, decisions.
- **Exams:** a pack's `exams/*.yaml` lists historical items, each with the outcome it must reach. `ops/replay.py` runs them, so a deployment is measured before it goes live and before any class is promoted.

## 12. What we do not build, and why

| Not built | Why |
|---|---|
| Pack code inside the runner (Python plugins) | Commands keep packs language-neutral and the runner's process clean; the worker already sandboxes them |
| Temporal, Airflow, Prefect, Argo, n8n, Windmill | The Conductor already persists plans, waits and loops. Each of these adds a server, a database or a second app |
| LangGraph or a similar in-process graph | It runs domain code in our process |
| Redis or Celery for capacity | One SQLite table does it |
| An artifact service | A folder named by hash, and one table |
| Planner-filled sections in templates | The `change` step is already the open part |
| Tracker webhooks; gates by tracker comment; sign-in | Later, each behind its own decision or feature |

## 13. Updates (GEN-32)

`packs.txt` pins commits. `make update` already verifies the stack's signed tag (H). It also checks that every pinned
pack commit is approved, and a new commit waits in the queue while the old one keeps running. A pack repository may sign
its commits, and the deployment's `allowed_signers` checks them as it checks the stack's tags.

## 14. Order

Each step lands alone, between exam arms, with home's whole check green and no change in what home does.

1. **This design, signed** by the owner.
2. **The walking skeleton**, against stand-ins and with the toy pack. It ends in one test that drives a toy item from
   created, to a draft pull request plus a comment plus a wait, to the reply, the resume and the close:
   1. the pack loader: namespaces, approval in the queue, agents, skills, job kinds;
   2. the worker on `wsl-host` (the user's setup is the owner's step);
   3. templates as saved plans, with `gate`, `wait` and keys;
   4. the tracker module: the stand-in, Forgejo issues, Jira; the source, comments, the summary, shadow mode;
   5. a branch from a tag, and pull-request comments as events.
3. Pools, artifacts, checks during the coder's loop, `each` from a step's answer.
4. Roles, the record export, pack exams, pinned updates.

## 15. Questions for the sign-off

1. **Namespacing:** pack names as `pack:agent` and `pack.kind`, so clashes cannot happen. Agreed?
2. **The WSL-host worker** needs a Linux user and a systemd unit, made with sudo. Is that your step, as on Windows?
3. **Shadow mode first:** every new tracker starts in shadow mode, and leaving it is your tap. Agreed?
4. **Approval per pack commit,** with each job kind still approved on its own worker. Agreed?
