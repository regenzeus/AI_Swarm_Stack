# How the swarm works: the design after phase 4

Written 31 October 2026, when the owner asked for every task through the Conductor, a picture of the swarm, telemetry,
customisation, a UX pass and more reach, "implemented properly, best practice". [SWARM-ROADMAP.md](SWARM-ROADMAP.md)
is the plan that got the stack here (phases 0 to 4); this is the design of what comes next, phases 6 to 9. The
requirements are the contract (`requirements/tasks.yaml`, TSK-21 to TSK-33); where they and this text disagree, the
requirement wins.

## What went wrong on 31 October, and what it teaches

- **A weekly briefing bypassed the swarm.** The intake planned four steps (set up, scout, write, mail), but a recurring
  task went to the briefing pipeline, which pasted the plan into its notes and ran one script. The writer reported
  itself "blocked". *Lesson: the plan the owner sees must be the plan that runs, every time the task runs.*
- **A job hunt had no tool for the job.** Web search finds job ads badly; the federal job board has them. Once the
  board was a tool, the scout ignored it until its brief named it. *Lesson: a capability counts only when the agent's
  brief routes work to it, and a replay proves it does.*
- **The owner found six faults the 650 tests missed:** the email headline, the weekly window, Chinese search, the
  Makefile, a card that wasn't a link, a page wider than the phone. *Lesson: unit tests check parts; the owner uses
  journeys. Journeys need their own checks.*
- **WSL froze six times.** *Lesson: parallelism is bounded by memory; the Conductor admits work by headroom, and the
  UI says when work waits for room.*

## The model: tasks, occurrences, steps, artifacts

The design follows the standards the field converged on in 2026: a task is a durable plan graph (as in Temporal or
Restate, kept in the runner's own database, DEC-35), agents are described by cards and talk by A2A's shapes, tools
come over MCP, traces use OpenTelemetry's GenAI conventions, and what was used and made is recorded in W3C PROV's
terms.

| Thing | What it is | Where it lives |
|---|---|---|
| **Task** | What the owner asked for: goal, definition of done, the plan template, its rhythm (once, schedule, event, after another task) | `tasks` |
| **Occurrence** | One time the task runs: a schedule tick, an event, a "run now". It has its own plan graph, trace and verdict | `task_runs` (new), the trace `task:<id>:<n>` |
| **Step** | One unit of work for one agent on one harness; it can **fan out** into parallel copies, one per item of a list, joined by the next step | `task_steps` |
| **Artifact** | Anything used or made: a web page, a feed item, a job ad, a filing, a price series, a vault note, a memory, a step's finding, the report, the sent email | `artifacts`, `artifact_links` in the runtime record |
| **Agent** | A card: purpose, harness, model, tools, prompts, budgets | `config/agents.yaml`, editable in the app (TSK-30) |

### Every task through the Conductor (TSK-21, TSK-22)

- Every occurrence of every task runs as a plan graph under the Conductor: one-off, scheduled, event-triggered and
  "after another task" alike. A single-agent task is a one-step graph, so it is traced, judged and shown the same way.
- The doors become **step kinds**, not exits: `hermes` (an agent with tools), `claude` (Claude Code), `opencode`,
  `build` (a builder assignment with its deploy tap), `desk` (the Topic Desk's collect or write, as a Python step),
  `deliver` (Telegram, email, the app), `temp` (a temporary agent). Approvals stay with their step kind (DEC-34).
- A recurring task keeps its plan as a **template**. Each occurrence copies it, fills its window ("the last 7 days"),
  and runs. The occurrence's result is filed and delivered by its own `deliver` step, so delivery shows in the trace.
- **Fan-out:** a step with `each: [...]` becomes one step per item, all with the same agent and instructions plus their
  item, run in parallel as headroom allows; the step after them gets every result. A weekly briefing is
  `collect` (desk, Python: feeds, searches, the job board, prices) → `research ×N` (scouts, one per topic group,
  in parallel) → `write` (desk writer, cites every claim) → `check` (citations and the definition of done) → `deliver`.
- **Admission by headroom** stays (TSK-08): a fan-out of six runs two at a time on this PC, and the step says
  "waits for memory" while it waits.

### Artifacts and provenance (TSK-23)

Each artifact has a stable id (the URL's or path's hash), a kind, a title, where it came from, and its first and last
use. Each link is one of PROV's relations:

- `used`: a step read it (a fetched page, a search result list, a job ad, a vault note, a memory),
- `generated`: a step made it (a finding, a draft, the report, the email),
- `derived`: an artifact came from another (the report from the findings; a finding from the pages it cites),
- `cited`: the report's text cites it, so the map can show what was read but never used.

They are recorded where the work happens, not reconstructed: the runtime record's tool calls (`fetch`, `web_search`,
`jobs_search`, `job_details`, the vault tools), the desk's collected items, the Conductor's step outputs, and the
deliveries.

### The swarm map (TSK-24)

On every task and occurrence, and live while it runs:

- **Flow:** columns of sources → agents → findings → writer → outputs, links drawn between them. A tap on any box
  shows its lineage (what it came from, what it fed) and opens the artifact or the agent's run. Sources read but
  never cited are dashed and greyed, so the reading that paid off is visible.
- **Timeline:** one lane per agent run, bars over time, so parallel work is visible at a glance; dots for artifacts
  read, squares for artifacts made.
- **Numbers on top:** sources read → cited, agents and how many at once, wall time, tokens.
- Large runs stay readable: sources group by site with a count, and the map pans on a phone instead of shrinking.

## Telemetry (TSK-25, TSK-26, TSK-27)

- **History:** a daily row per agent, model, harness and kind of task: runs, successes, the judge's met/partly/not
  met, tokens in and out, median and 95th-percentile time, and cost. Kept for a year (a few thousand rows).
- **Dashboard (Stack → Telemetry):** success rate, tokens and time per agent per day; the busiest and the failing
  agents; subscription usage against limits; filters by agent, model and kind; every number links to its runs.
- **One trace per occurrence in Phoenix:** the occurrence is the root span (`invoke_agent conductor`), each step a child
  (`invoke_agent <agent>`), and each model call and tool call under its step (`chat`, `execute_tool`), with the
  GenAI and OpenInference attributes the stack already writes for Claude runs (`otlp.py`).
- **Cost per run:** the subscriptions cost $0 per call, so each run shows its tokens and what they would cost at the
  provider's list price ("$0.42 if paid"), from the gateway's price table. The point is comparison and waste
  detection, not billing.

## Customisation (TSK-28, TSK-29, TSK-30)

- **Agent settings** (Agents → an agent → Settings): model, harness, tools, budgets, schedule and prompts, each with
  what it changes. A change is a proposal that goes through the same gate as the Coach's: the agent's replay set runs on
  the old and the new card and prompts, the judge compares, and it applies only when it passes. The owner sees the
  result and the diff, and can roll back.
- **Tools are grants.** Removing a tool applies after the replay. Adding one changes the agent's key grants, so it also
  needs the owner's tap and is recorded as a security change.
- **The composer picks agents on request:** "Automatic" (the default: the intake and routing decide) or chosen agents,
  a model and an effort for this task. The plan shows which were the owner's choice.

## UX standards (TSK-31)

- One format for dates (31 Oct, 18:40; relative within a day) and numbers (1,234; 4.2k tokens) everywhere, English.
- A card that stands for a page opens it on a tap. Every empty state says what fills it and offers that action. Every
  action says what happens next ("Runs now, about 15 min; the result lands here and by email").
- Every screen at 375 px without sideways scrolling. A journey check opens every route at phone width in the browser
  sandbox, and fails on overflow, a script error or an empty main area.
- **Journey checks** (TSK-32): give a task, follow it to its result, render the email at phone width, dry-run every
  make target. They run on demand and nightly on replayed data, and reach the health board when they fail.

## Reach (TSK-33, TSK-18, TSK-10, TSK-19)

- **OpenCode** as a third harness (TSK-07, TSK-18): a step kind that runs `opencode run` in its container with its
  card's model, its output and tool calls recorded like the others.
- **The calendar** as an event source (TSK-10): an ICS or CalDAV address the owner provides, read-only, so "an hour
  before a meeting with X, brief me on X" is a rule.
- **Outside agents over A2A** (TSK-19): the stack's agent card at `/.well-known/agent-card.json` and A2A's message and
  task methods, on the tailnet only, with a token per outside agent, off until the owner switches it on. An outside
  request becomes a task that waits for the owner's OK by default.

## Order of work

| Phase | What | Gate |
|---|---|---|
| 6 | Every task through the Conductor, fan-out, recurring occurrences; the weekly briefing as a fan-out | A weekly briefing's occurrence runs collect → scouts in parallel → write → check → deliver with one trace |
| 7 | Artifacts and the swarm map; telemetry history, dashboard, Phoenix trees, cost per run | A finished occurrence's map shows every source with cited or not; its trace in Phoenix is one tree |
| 8 | Agent settings with the replay gate; the composer's agent picker; the UX pass and journey checks | Every route passes the journey check at 375 px; a model change is replayed before it applies |
| 9 | OpenCode steps, the calendar source, A2A in | A step runs on OpenCode; a calendar rule fires; an outside agent's request waits for the owner |
