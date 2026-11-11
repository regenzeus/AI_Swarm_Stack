# AI Stack: the end state and the road to it

*Master design, 11 Nov 2026, version 1.3: the work side's review folded in (§12), big bang with import (§11), the memory system and repository onboarding kept, the core objects fixed (§3a), and the gaps to a full software factory closed in the design (§13). It describes where the platform ends up and how we get there from today. Its UX chapter is FACTORY-DESIGN.md (§3 to §8: the live run, runs and workflows, the canvas, agent context, Asks, the app's places), which stays in force.*

## 1. What you are building

**A professional AI software factory platform.** Work arrives as tickets, schedules, mail or requests. Workflows of agents do it. People supervise through questions and gates. Every run can be watched live and audited afterwards, and the factory measures and improves itself.

The platform is generic and published. A **factory** is a body of work that runs on it. Home is the example factory; the work factory is another.

**Qualities the end state must have:**

| Quality | What it means here |
|---|---|
| **Observable** | Every run is live while it runs and a complete record after. This is the centre of the product. |
| **Durable** | No work is lost on a restart, crash or deploy. Every step has a stated timeout, retry and idempotency rule. |
| **Safe to change** | Nothing is edited in production. Every change is a commit that is tested against real past runs, approved at a gate, and reversible. |
| **Lean** | Our own code exists only where no mature open-source tool does the job. One engine, one database, one event stream, one front end. |
| **Scalable** | One PC today. More workers, then more machines, without a redesign. |
| **Governed** | Roles, gates, policy, an audit trail, factories isolated from each other. |

## 2. Where we are (11 Nov 2026)

| | Today | Problem |
|---|---|---|
| Own code | About 61,600 lines of Python (148 runner and tool files, 23 app server files, 21 service folders) and 8,600 lines of untyped JavaScript | Much of it hand-builds what open-source tools do: scheduling, queues, retries, tracing, evaluation, state storage, upgrade checks |
| Engines | n8n **and** the stack's own scheduler (plans, missions, builds, questions to Claude) | Agents run outside any workflow; two models of "work" |
| Ways work enters | 8, with 6 separate run tables | No single history |
| State | 5 SQLite files, about 950 JSON state files, plus Postgres for n8n and the gateway | Lock storms (10 Nov), half-written files, no transactions across stores |
| Step hand-off | Files dropped in folders, polled | No real queue; retries and timeouts are ad hoc |
| Observability | Phoenix traces, our own "runtime record", the app's activity feed, n8n's executions: four partial views | Nobody sees one run end to end, live |
| Evaluation | A judge per task, prompt replays, ideas | No test sets, no labels, no gate before a change lands |
| Changing things | Landing scripts with strong checks, but workflows are edited live and agents have no versions | Edits in production |
| Front end | Vanilla JavaScript, 17 files | No types or components; every new view is hand-built |
| Platform vs home | One repository | Every site inherits the house |
| Operations | 30 containers, 57 systemd units, custom deploy and upgrade scripts | A lot to keep alive by hand |

**What is good and stays:**

- the requirement discipline (816 requirements traced to tests);
- the landing checks, the privacy and never-in-git guards, the doctor;
- the Ask system with roles and gates, and the trust boundary;
- the step service as a seam;
- the pack idea;
- n8n as the canvas;
- the gateway, Forgejo;
- the memory system (DEC-44): sectors, layers, collections, the write gate, the keepers (the owner, 11 Nov 2026: kept);
- repository onboarding and what it makes: the repository card, wiki, facts, code map (kept as a workflow, with each repository's landing page).

## 3. The end state on one page

```
 People ── app (phone, desk) ── chat ── tickets ── mail ── stack CLI / MCP (agents, sessions)
                │
        ┌───────┴────────────────────────────────────────────────────────────┐
        │  EDGE: one reverse proxy + sign-in (OIDC) → identity, roles         │
        └───────┬────────────────────────────────────────────────────────────┘
                │
   ┌────────────┴───────────┐      ┌──────────────────────────┐
   │  PLATFORM API (own)    │◄────►│  n8n: workflows, canvas,  │  one engine
   │  runs · asks · policy  │      │  triggers, waits          │
   │  records · live stream │      └───────────┬──────────────┘
   └───────┬────────────────┘                  │ step requests (the seam)
           │                        ┌──────────▼──────────────┐
           │                        │  STEP QUEUE (Postgres)   │  durable: timeout, retry,
           │                        └──────────┬──────────────┘  idempotency, dead letters
           │                        ┌──────────▼──────────────┐
           │                        │  AGENT WORKERS (own, thin│  N stateless workers
           │                        │  ) → harness: Hermes,    │
           │                        │  Claude Code, Codex      │
           │                        └──────────┬──────────────┘
           │                                   │ model calls, tools
   ┌───────▼────────┐  ┌────────────┐  ┌───────▼───────┐  ┌──────────────┐
   │ POSTGRES: the   │  │ OpenTelem. │  │ LiteLLM       │  │ Memory       │
   │ one database    │  │ → Phoenix  │  │ gateway       │  │ (Hindsight,  │
   │ runs, steps,    │  │ traces,    │  │ models, keys, │  │  doc search) │
   │ events, asks,   │  │ test sets, │  │ budgets       │  └──────────────┘
   │ records, audit  │  │ evals      │  └───────────────┘
   └─────────────────┘  └────────────┘
   FACTORIES (packs in git): workflows · agents · skills · evals · policy · roles · records
   Tracker + forge + CI: Forgejo (home) / Jira + Bitbucket (work), through adapters
```

**The whole platform is five kinds of thing:**

1. the engine (n8n);
2. a thin layer of our own (the API, the step queue and workers, the front end);
3. open-source services (database, gateway, tracing, memory, forge);
4. factories as packs;
5. the edge.

## 3a. The core objects (fixed now, so later work only adds)

A big rework happens when a new feature needs a new core object or a new link between objects. These objects, and the links between them, are fixed in the first schema. Later stages add fields and screens, not objects.

| Object | What it is | Links |
|---|---|---|
| **Factory** | A body of work and its pack: workflows, agents, skills, policy, roles, data class, evals | has repositories, workflows, agents |
| **Repository** | A codebase the factory works on, with its knowledge (card, wiki, facts, code map), its **environment** (`devcontainer.json`), its **check plan** (how to build, test and verify, runnable by name) and its forge | made and kept current by the Onboard workflow; has changes |
| **Work item** | The intent: where it came from (ticket, chat, mail, schedule, signal), its **acceptance criteria**, its change class, its links to the tracker | started runs; resulted in changes |
| **Workflow, version** | An n8n workflow in the pack, with versions | has runs |
| **Run** | One execution: trigger, the versions it used, the work item, status, cost, **failure class** when it failed | has steps; belongs to a work item |
| **Step** | One unit under the reliability contract; carries its **scope** (tools, repositories, memory plug, budget, policy tier), never wider than its run's | runs on a worker in a workspace; emits activity |
| **Workspace** | The sandbox a step works in: made from the repository's environment, its own egress and package rules, credentials never inside, destroyed after the run | belongs to a step |
| **Agent, version** | A building block: card, instructions, harness, model, tools, **memory plug**, limits | used by steps |
| **Change** | One pull request in one repository, with its **evidence** (check results, UI recording, diff summary) and its **outcome**: merged as is, merged after edits, closed, reverted later | belongs to a work item (one item, several repositories: several changes) |
| **Ask** | A question or gate to a person or role | belongs to a run |
| **Label** | A person's judgment on a result, a step or a change | trains judges |
| **Audit entry** | Who or what did what, under which authority, **hash-chained** so the log cannot be edited unnoticed | refers to any of the above |

**Every actor has an identity.** Each agent acts under its own identity. In the forge it commits as a bot account, with the run in a trailer. At the gateway it uses its own key. In the audit log it is named. A person's approval is recorded as theirs.

## 4. Technology: open source first

| Layer | Choice | Licence | Replaces (own code or today's part) |
|---|---|---|---|
| Orchestration, canvas, triggers, waits | **n8n**. Queue mode with workers when one node is not enough. | Sustainable Use (fair-code: free for our own and internal business use; not for reselling as a hosted product) | The stack's own scheduler, plans, missions, crew timers, event bus |
| Step queue and worker reliability | **A Postgres-backed job queue** (candidate: Procrastinate; confirmed by a spike in stage 0) | MIT | File-drop hand-off, hand-made retries, the runner's loops |
| Agent harnesses | **Hermes Agent** for general agents; **Claude Code** and **Codex CLI** for coding. All behind one harness interface, on the subscriptions. | MIT / vendor CLIs | — (kept) |
| Model gateway | **LiteLLM** | MIT | — (kept) |
| Tracing | **OpenTelemetry** with the OpenInference conventions for AI calls | Apache-2.0 | Our own runtime record |
| Traces, test sets, experiments, judges, labels, prompt versions | **Arize Phoenix** (already running). Fallback if it falls short: Langfuse (MIT). | Elastic 2.0 (source-available, free to self-host) | The staffing judge, prompt replays, trials, exams, the Coach's evaluation, ideas scoring |
| Database | **PostgreSQL** with pgvector: one instance, one schema per concern, migrations with Alembic | PostgreSQL / MIT | 5 SQLite files, about 950 JSON state files |
| Memory | **The memory system** (kept, DEC-44) on **Hindsight**, document search (qmd) and the code graph (graphify), scoped per factory. Agents connect through their memory plug (§3a). Its state moves into Postgres; its upkeep (keepers, curation, vault ingest) runs as Upkeep workflows. | MIT | Its own timers and JSON state |
| Workspaces | **Dev Containers** (the open `devcontainer.json` spec and its reference CLI) for each repository's environment; Docker per run, with gVisor as a stronger runtime when a factory's policy asks for it | MIT / Apache-2.0 | The builder's shared checkouts |
| Egress and packages | **Smokescreen** (default-deny egress proxy) per workspace; the package proxies already running, extended to an allow list | MIT | Ad hoc network rules |
| Verification | The repository's own checks, plus **Playwright** for UI checks with a recording, gathered as evidence on the PR | Apache-2.0 | — |
| Forge, tracker, CI | **Forgejo** with Forgejo Actions; adapters for Jira, Bitbucket, GitHub | GPL-3.0+ | Parts of the landing and deploy scripts (checks run as pipeline jobs) |
| Dependency and image updates | **Renovate** | AGPL-3.0 | The upgrade-check job |
| Sign-in | **OIDC** through oauth2-proxy at the edge. Home: Tailscale as the identity provider. Work: the company's. | MIT | Header checks spread through the app |
| Edge | **Caddy**, one instance | Apache-2.0 | Several small proxies |
| Secrets | **sops** with age | MPL-2.0 / BSD | — (kept) |
| Backup | **restic** to the NAS and off-site, with a restore drill as a workflow | BSD-2 | Custom backup scripts |
| Front end | **TypeScript, React, TanStack (Query, Table), Radix-based components, Vite**, as a PWA | MIT | 8,600 lines of vanilla JavaScript |
| UI tests | **Playwright** | Apache-2.0 | Hand-made screenshot scripts, the journeys |
| API | Python, **FastAPI**, SQLAlchemy, psycopg | MIT / BSD | The app server's 23 part files |
| Packaging | Docker Compose, images pinned by digest. A Helm chart only when a deployment needs more than one machine. | Apache-2.0 | — |

**What stays our own code,** because nothing off the shelf does it. The target is **under 15,000 lines of Python** (from about 61,600) plus a typed front end:

- the platform API (runs, Asks, policy, roles and gates, records, the live stream);
- the agent worker and the harness interface;
- the n8n node and the canvas live layer;
- the tracker adapters (idempotent writes, shadow mode);
- pack loading and the doctor;
- the requirements tool and the privacy guards;
- the front end.

## 5. The decisions that shape it

**D1. n8n stays the engine, behind the seam.** n8n gives the canvas, triggers, waits, a draft-and-publish model and worker scaling. Its limits are known:

- it is fair-code, not open source;
- the free edition has no single sign-on, no git sync and no environments.

We cover those ourselves: the app signs in, packs are the git sync, sites are the environments. Everything durable goes through the step service contract and never depends on n8n's internals. That covers agent steps, Asks and records. If n8n ever has to go (its licence, or scale), the workflows are re-expressed and the rest stays. *Reconsidered and kept:* switching engines a third time would cost more than any engine's flaws.

**D2. One database.** All platform state lives in Postgres:

- runs, steps, events and Asks;
- records, policy and the audit log;
- the queue.

Files hold only artifacts (reports, attachments), addressed by hash. This ends the lock storms and half-written state, and makes backup one thing.

**D3. A real queue with a reliability contract** (§6). n8n asks for a step, the request lands in the queue, and a worker runs it. The queue gives timeouts, retries with backoff, locks, dead letters and resume after a restart. Workers are stateless, so "more capacity" means "more workers".

**D4. One event stream.** A step emits its start, its end and every activity as OpenTelemetry spans and events. The same events feed the live view (through Postgres notifications to the browser), Phoenix (traces), the audit log, and the metrics. One run id travels from trigger to n8n, queue, worker, harness, gateway and Phoenix.

**D5. Evaluation is Phoenix's, not ours.** Test sets are built from real runs. Your thumbs and corrections are labels. Judges are calibrated on those labels, and experiments compare a change against the test set. Our code only wires runs into Phoenix and reads the verdict at the gate.

**D6. Nothing is edited in production** (§7).

**D7. The front end is rebuilt, typed, on mainstream components.** The live run, the runs list, the grid and the timeline are all new work anyway. Building them in untyped vanilla JavaScript would create the next debt. The new shell takes over place by place, and the old files are deleted as each place moves.

**D8. Platform and factories are separate repositories.** The platform is public on GitHub, with `example-home` (demo data) as the example factory. The real home factory is a private pack on Forgejo; the work factory is the work side's pack. A site's deployment names its packs at approved commits.

**D9. Identity at the edge.** One proxy authenticates (OIDC) and passes a verified identity. Roles come from the deployment. Services trust only the proxy. This is the trust boundary made standard.

## 6. The reliability contract

Every step, of any kind, runs under the same stated contract. It is visible in the step's settings and in the Run page.

| Guarantee | Rule |
|---|---|
| **Timeout** | Every step has one (default per kind). On timeout the step fails with that reason; it never hangs. |
| **Retry** | Declared per step: how often, with backoff, and on which failures (transient ones only). A retry is visible as an attempt in the timeline. |
| **Idempotency** | Every side effect carries the step's key. A retry or a replay never sends, writes or buys twice. |
| **Resume** | A restart of n8n, a worker or the machine loses nothing. Queued and running steps continue or retry; waits survive. |
| **Dead letters** | A step that exhausted its retries goes to a queue you can act on: retry, skip, or fail the run. |
| **Circuit breaker** | When a provider is down or a subscription limit is reached, steps for it wait and the cause is shown once. They do not fail one by one. |
| **Overlap** | Per workflow: side by side, one at a time, skip, replace. |
| **Capacity** | Slots per harness and per factory. Waiting for a slot is a visible state. |
| **Backpressure** | Triggers that outrun capacity queue with a bound; beyond it they are refused with a reason and an alert. |

## 7. Changing the factory

One path for every change to a workflow, agent, skill, prompt, evaluation or policy, whoever proposes it: you, an agent, or the Improve workflow.

```
edit a draft ──► pull request in the pack ──► checks ──► replay on the test set ──► gate ──► publish ──► watch
 (canvas draft,     (the diff, readable:       (lint,      (Phoenix experiment:        (a named     (the site    (first runs
  or a commit)       workflow, agent, skill)    contract)   better, same, worse)        person)      imports it)  compared)
```

- **Drafts:** the canvas edits n8n's draft; Publish and Execute are blocked there. "Propose" exports the draft into the pack as a pull request.
- **Versions:** every workflow and agent has versions. A run records the versions it used. Rollback is publishing the previous version.
- **Template changes** replay on every factory that uses or overrides the template. The doctor flags overrides whose template moved.
- **Promotion between sites:** a pack commit is approved per site. Work approves on its own.
- **Merging is a factory's policy:** `merge: never | after-gate`.
  - With `never` (the work factory), the platform stops at a reviewed pull request, and a person merges in the factory's own forge.
  - With `after-gate` (home), the platform merges and publishes once the named person has approved at the gate.
  - Agents never merge on their own.

## 8. Evaluation

| Part | How |
|---|---|
| **Test sets** | Per workflow and per agent, built from real runs: inputs and the accepted outputs. Curated in Phoenix, growing with use. |
| **Labels** | Your thumbs up or down on a result, your corrections, an Ask answered against the default, an Undo: each is a label attached to the run. |
| **Judges** | LLM judges with rubrics per workflow, **calibrated against your labels**. A judge that disagrees with you too often is not trusted until fixed. |
| **Gates** | A change that makes its test set worse does not publish (§7). |
| **Production scoring** | A sample of live runs is scored. A falling score raises a finding for Monitor. |
| **Service levels** | Per workflow: success rate, duration, interventions per 100 runs, cost per result. Shown on the workflow's page; alerts on breach. |

## 9. Security and governance

- **Identity and roles** at the edge. Gates are answered only by named role holders.
- **Least privilege:** each agent has its own gateway key, tools and memory plug; each factory has its own credentials and data class.
- **The agent proposes, policy authorizes, infrastructure enforces.** Four boundaries are enforced outside the agent:
  1. **The workspace:** a sandbox per step, destroyed after the run.
  2. **The network:** default-deny egress, and only the hosts the factory allows.
  3. **The supply chain:** packages only through the proxies, from an allow list.
  4. **Identity:** credentials stay outside the workspace. The platform's own adapters push, comment and open PRs on the agent's behalf, so an agent never holds a forge or tracker token.
- **Isolation:** factories don't share memory, secrets or trackers.
- **Policy:** risk tiers, standing rules, undo, the stop switch.
- **Audit:** one append-only log of who or what did what, under which authority (a policy, an answer, a default), queryable in the app.
- **Data rules:** a factory's data class decides what may leave the machine. Customer data travels by reference, never through n8n. Home's tax content is read only by the engine you chose.
- **Supply chain:** images pinned by digest, dependencies locked with hashes, updates through Renovate's pull requests, privacy and never-in-git guards on every commit and landing.

## 10. Repositories

```
platform (public, GitHub)                 factory packs (their own repos)
├─ api/            platform API           home-pack (private, Forgejo)
├─ worker/         agent worker,          ├─ factory.yaml      what this factory is
│                  harness adapters       ├─ workflows/        n8n workflows
├─ web/            the front end          ├─ agents/  skills/  cards, instructions
├─ n8n/            our node, the          ├─ evals/            rubrics, test-set refs
│                  standard workflows     ├─ policy.yaml  roles.yaml  records.yaml
├─ deploy/         compose, edge, doctor  └─ services/         home-only services (mail, phone,
├─ packs/example-home/   demo factory                           house, shopping, taxes)
├─ requirements/   the requirements       work-pack (the work side's)
└─ docs/           design, decisions, guides
```

## 11. Roadmap

**Big bang** (the owner, 11 Nov 2026): the new platform is built complete next to the old one, home and the work site switch over once each, and then the old data is imported into the new. There is no dual run and no service-by-service move. The old stack stays home's working stack until switch day, but it gets fixes only: no new features. After the switch, the old code is deleted, not kept alongside.

| Stage | What | Done when |
|---|---|---|
| **0. Decide and freeze** | Already live from phase A: the platform-only default, the `stack` CLI and MCP tools, the loud doctor and deploy. Now: publish to GitHub so the work side has phase A; the n8n canvas; four spikes that settle the risky choices (Postgres queue with a remote Windows worker, OpenTelemetry live events, a Phoenix judge as the interim scorer, the front-end shell). The **acceptance spec**: the requirements sorted into keep, change and drop (§11a), with every kept one tied to an acceptance test written against behaviour, not against old code. | Each spike has a yes or a replacement; the spec is signed off by the owner; the old stack is frozen |
| **1. Build the new platform** | All of it, in a new repository layout, as a separate compose project on its own ports: Postgres as the one store; the queue and workers under the reliability contract; FastAPI; one OpenTelemetry stream into the live view and Phoenix; the edge in the deployment's mode; n8n behind the seam; the core objects of §3a as the first schema; workspaces per step with the four boundaries; Request, Change (with verification and evidence), Onboard, Briefing, Chat, Monitor and Upkeep as n8n workflows; the memory system behind the agents' memory plugs; the factory measures; the whole typed front end (every place, phone and desk); the draft-to-publish path; the pack format. | The acceptance tests pass on the new platform with demo data; a kill test loses nothing |
| **2. Port the factories** | Home's logic (tax, mail, house, shopping, phone, inbox, voice, Windows desk) into home's pack as steps; the work factory's pack via `stack pack migrate`; `example-home` with demo data. | Each home and work workflow runs on the new platform against demo or copied data |
| **3. The import and a rehearsal** | `stack import` reads the old stores (the runtime database, missions, Asks, swarm history, the JSON state, memory and journals) and writes them into the new schema. A dress rehearsal on a copy: a copy of home's data imported into a throwaway new stack, the acceptance list walked on the phone. This is not a dual run: nothing is written twice or compared over time. | The rehearsal imports everything with counts that match ("X of Y rows imported", per table) and passes the list |
| **4. Switch day** | Old stack stopped; a final frozen copy of its state; the import; the new stack started on the old addresses; the acceptance list on the phone. The fallback is to start the old stack from its git tag and frozen state; work done on the new stack since the switch would be lost, so the fallback is for the first day only. | Home runs on the new platform; the owner says it holds |
| **5. Delete and publish** | The old code is deleted; the frozen copy is kept as a backup archive; the platform is published to GitHub with `example-home`. The work site switches with the same import, after home has held for a week. | Under 15,000 lines of own Python; the work site runs the new platform |
| **6. Evaluate and improve** | Test sets from runs, labels, calibrated judges, gates, production scoring, budgets; the Improve workflow and Monitor close the loop. | A worse change is stopped at the gate; an improvement is merged, measured |
| **7. Harden and scale, 1.0** | The audit log in the app; restore drill as a workflow; n8n queue mode and a second worker; requirements and code reconciled. | A restore rehearsal passes; requirements and code agree, checked |

### 11a. What we keep, what goes (count of 11 Nov 2026)

Own code today: about 70,000 lines. Of these, 47,600 lines are Python in `ops/`, 7,500 are the app server, 6,500 are other images, and 8,600 are the app's JavaScript. On top of that come 34,000 lines of tests.

| Part | Lines | What happens |
|---|---|---|
| Engines, run tables, own queue, own observability, the swarm (missions, conductor, crew, tasks, runtime, run register, event bus, step service, journeys, trials, evals, replay, telemetry, swarm image) | 18,000 in `ops`, 2,500 swarm image | **Replaced** by n8n, the Postgres queue, OpenTelemetry and Phoenix |
| The app server and front end | 7,500 Python, 8,600 JavaScript | **Replaced** by FastAPI and the typed front end; the API shapes and the screens' content are the spec |
| Factory logic: Asks, records, packs, trackers, roles, forge and draft pull requests, change requests, onboarding | 9,000 | **Ported** as step code and Postgres tables; expected to shrink to about half, because the orchestration inside it goes |
| Home's logic: tax, mail sorting, inbox, house, shopping, phone, user agents, voice, Windows desk, mail and phone images | 6,100 plus 3,200 in images | **Moved** into home's pack, mostly as it is |
| Platform tools: deployment, doctor, `stack` CLI, publish, never-in-git and data guards, requirements, limits and truncation checks, deploy, n8n sync | 6,200 | **Kept** and adapted to the new layout |
| Knowledge and memory (memory stack, librarian, journals, decisions, repo facts, repo wiki, repo card, provenance) | 8,200 | **Kept** (the owner, 11 Nov 2026). Ported with its state into Postgres; its timers become Upkeep workflows; repository knowledge is made by the Onboard workflow. Agents connect through their memory plug. The coder-knowledge exam decides each agent's plug, not whether the system exists. |
| Tests | 34,000 | Tests of replaced code go with it. Behaviour tests become the acceptance tests of the new platform. |

**Saved whatever happens:**
- the data, through the import;
- the 793 requirements and 56 decisions (they are the spec);
- the prompts, and the agent and workflow definitions;
- the lessons in the reviews and AGENTS.md files (WSL, rootless Docker, n8n quirks);
- the git history and a tag on the last old commit;
- the frozen state archive.

**Running through all stages:**
- every change lands through the checks;
- requirements move with the code;
- phone and widescreen are both checked before "done".

## 12. Folded in from the work side's review (11 Nov 2026)

| Point | Rule now in the design |
|---|---|
| Phase A items needed now | Already live (the platform-only default, the `stack` CLI and MCP tools, the loud doctor and deploy); published to GitHub in stage 0 |
| Data move | The owner chose a big bang: no dual run. Instead: an import tool with per-table counts, a rehearsal on a copy, a frozen copy of the old state, and a first-day fallback to the old stack (§11). The work site switches with the same tool after home has held for a week. |
| Merging | A factory policy: `merge: never \| after-gate` |
| Workers | A worker is a kind: agent harnesses (Hermes, Claude Code, Codex) and remote workers (a Windows build and verify worker, other machines) pull from the same queue through the platform API, under the same contract, with their own token |
| Data class | Traces, test sets, run records, labels follow the deployment's data class; at work they stay on-site. Test sets in git use made-up items only; real ones stay in the site's Phoenix. Improve PRs carry diffs and references, never customer content. |
| Network | Model gateway, proxies, image registries, package indexes and Renovate's sources are deployment configuration, never fixed in code |
| Sign-in | The edge mode per deployment: `oidc`, `tailnet`, or `localhost` (ports on 127.0.0.1, one local identity, no identity provider needed) |
| Never in git | Each deployment keeps its own deny list of names outside git; the guard reads it. Only home publishes to GitHub. |
| Packs | `stack pack migrate` and one stage of reading both layouts |
| Scorer | An interim judge (a Phoenix evaluator with a rubric) from the stage 0 spike, usable for the work side's exams at once, and grown into stage 6's evaluation, not replaced |
| Licences | n8n's Sustainable Use licence and Phoenix's Elastic 2.0 allow self-hosted internal use at work (confirmed by the work side) |

## 13. Measured against a full AI software factory (research, 11 Nov 2026)

**Sources compared:**
- Warp's factory (intake from chat and tickets, verification with a recording, an observer agent that changes the factory after a failure recurs in about 20 to 25 runs, model routing from replays);
- the Secure Software Factory reference architecture (agentbaseline.org, draft: four boundaries, autonomy levels, a tamper-evident record);
- the software-factory surveys by Hashnode and Signadot (intake, isolation, implementation, verification, review; time to signal, escape rate);
- GitHub's Agent HQ (any agent, one mission control, admin policy over agents);
- the studies of agent pull requests (merge rate as the base measure, read together with human edits before merge).

**What we already had:** intake from tickets, chat, mail and schedules; workflows; Asks, roles and gates; policy tiers; durable steps; one event stream; Phoenix evaluation; the Improve loop; draft-to-publish; merge policy; data classes; the gateway with budgets; memory; repository knowledge; packs; a remote Windows worker.

**The gaps, all closed in this design.** A gap is *structural* when it changes the core objects, the step contract or the boundaries. A missing structural gap is what would force another major rework, so every structural gap is in the first schema and the stage 1 build. *Additive* gaps are features on top, with no rework.

| Gap | What the design now says | Kind |
|---|---|---|
| A sandbox per run | The Workspace object: made from the repository's `devcontainer.json`, destroyed after the run; gVisor where policy asks (§3a, §4) | Structural |
| Credentials and network outside the agent | The four boundaries (§9): default-deny egress, packages from an allow list, adapters hold the tokens | Structural |
| Intent with acceptance criteria | The Work item object with criteria and change class (§3a) | Structural |
| Verification and evidence | Each repository's check plan, run by name; UI checks with a recording; evidence attached to each Change (§3a, §4) | Structural (the objects); the UI recording is additive |
| Outcomes of changes | A Change's outcome (merged as is, after edits, closed, reverted) read back from the forge | Structural |
| One intent, several repositories | A work item has one or more changes | Structural |
| Authority narrowing for sub-steps | Each step carries its scope (tools, repositories, memory plug, budget, tier), never wider than its run's | Structural |
| Agent identity | Bot account in the forge, own gateway key, named in the hash-chained audit log | Structural |
| Autonomy by change class | Policy per factory and change class: merge `never` or `after-gate`, the Ask tier, and the verification required. Autonomy is capped at what can be verified. | Structural (policy schema) |
| Failure classes | Each failed run gets a class (a judge classifies afterwards); a class recurring past a threshold starts Improve | Structural (the field); the observer is additive (stage 6) |
| Factory measures | Automation share, human interventions per change, merge rate as is and after edits, time to first signal, escape rate (reverts and bugs after merge), cost per merged change, review time. Computed from the objects. | Additive (the data is structural) |
| A review queue | PRs waiting for a person, with their evidence, in Code | Additive |
| Signals become work | CI failures, Renovate, incidents, scanners create work items through Monitor | Additive |
| Model routing from evidence | Replay past work items across model settings, then choose by cost and quality | Additive (stage 6) |
| Memory per agent | The memory plug: on or off, which parts, read or write, budget | Structural (the agent card) |
| Repository onboarding and landing pages | Onboard as a standard workflow; the Repository object; each repository's landing page in Code | Structural (the object) |

**Not taken now,** because nothing here needs them: microVM sandboxes (gVisor is the stronger step when needed); SAML (OIDC covers it); certifications; a hosted multi-tenant service.

**Sources:**
- [Inside Warp's software factory (How I AI)](https://www.chatprd.ai/how-i-ai/inside-warps-software-factory)
- [Latent Space: software factories](https://latent.space/p/software-factories)
- [The Secure Software Factory reference architecture](https://agentbaseline.org/reference-architecture)
- [AI software factory tools in 2026 (Hashnode)](https://hashnode.com/blog/ai-software-factory-tools)
- [What is a software factory (Signadot)](https://www.signadot.com/software-factory/)
- [Introducing Agent HQ (GitHub)](https://github.blog/news-insights/product-news/welcome-home-agents/)
- [Agentic pull requests on GitHub (arXiv)](https://arxiv.org/html/2509.14745v3)
- [Where do AI coding agents fail (arXiv)](https://arxiv.org/html/2602.08915v1)

## 14. Risks

| Risk | Answer |
|---|---|
| The big bang grows and never ships | The acceptance spec is fixed in stage 0, and nothing outside it is built before switch day. The old stack gets fixes only. Progress is reported as "X of Y acceptance tests pass". |
| Hard-won fixes inside the replaced code get lost | Every kept requirement has a behaviour test; the reviews and AGENTS.md lessons are read into the spec; the rehearsal walks the real data |
| Switch day fails | The rehearsal on a copy first; a frozen copy and the old git tag; the first-day fallback |
| n8n changes its licence, or breaks our live layer | The seam (D1); the version pinned; the upgrade test includes the layer; the timeline and panel work without the layer. |
| A spike fails (queue, live events, Phoenix evaluation) | Each has a named alternative: Celery and Redis; our own event table; Langfuse. |
| Home breaks during the build | The old stack keeps running untouched until switch day; the new one runs on its own ports. |
