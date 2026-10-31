# The swarm roadmap: give a task, the stack does the rest

Written 31 October 2026, after the owner asked where the stack has to go to be a bleeding-edge, low-maintenance agent
swarm. This is the plan; the requirements it adds are the contract (`requirements/tasks.yaml`, `TSK-*`, and the needs
SN-19 and SN-20). When this document and a requirement disagree, the requirement wins.

## The goal, in the owner's words

- Coordinated agents on different models and different harnesses.
- Observability and telemetry of the whole swarm.
- Any task: coding, research, analysis, watching, errands.
- No deciding which agent does what. Agents coordinate how a task gets done, which agents to deploy, and invent new
  agents for a task where none fits.
- Long-horizon work, one-shot tasks, periodic tasks, and tasks that start when other agents finish.
- Triggers on many kinds of events, such as a news story breaking.
- The usual way of working is to give a task and let the stack figure out the rest; a deliberate task with preset
  details stays possible.
- Advanced and easy to use at once, observable, with metrics.

## Where the stack stands (31 October 2026)

Strong:

- **Governance:** every behaviour has a requirement, approvals gate every risky action, and the builder cannot deploy
  without the owner's tap.
- **Observability:** the run record, timelines, Phoenix traces and the health board.
- **Self-maintenance:** the Health doctor, the maintainability review, the test agent, the Coach with replay-tested
  agent changes, and the Checker that judges outcomes from ground truth.
- **Cost:** subscriptions only, $0 spent on models (CST-02).
- **Standards:** the swarm already speaks A2A internally: agent cards, the message shape and the task states (SWM
  requirements with tests).

Missing, against the goal:

| Area | Today | Gap |
|---|---|---|
| Ways in | Chat, three mission types (briefing, task, shopping), builds and Claude tasks; the owner picks the door | One door that takes any task |
| Who does what | 18 agents defined by hand in `config/agents.yaml`, each with a fixed job | Agents chosen per task, and agents created for a task |
| Planning | Only builds get a planner (tasks with dependencies); two builds at once at most | A plan graph for every task |
| Rhythm | Missions on schedules; "after another finished" only between build tasks | Once, scheduled, on an event or after other tasks, for any task |
| Triggers | SEC filings, price moves and a news search, checked every 10 minutes | One event bus with many sources, and breaking-news detection |
| Models and harnesses | ChatGPT and Claude subscriptions and a tiny local test model; harness or model changes by card are planned (SWM-02); OpenCode has no swarm adapter (SWM-28) | Any step on any harness, routed by measured results |
| Durability | The Ledger and the runner's outbox survive restarts; the mail approval can be stranded (SWM-19) | Every step recorded with its resume point |
| Telemetry | Per-run timelines and Phoenix traces; cost per run is partial (MIS-16); no metrics history | One trace tree per task across harnesses; a metrics history |
| Platform | 16 GB PC with full swap, `wsl.exe` timeouts (CST-14 violated); usage limits pause chat (AST-12) | Headroom before more parallel work |

## What the field does (October 2026)

- **Model-written orchestration.** Anthropic's dynamic workflows (Managed Agents beta from 9 October 2026, and in
  Claude Code): the lead model writes a program that decides how many agents run, in what order and with which
  prompts, and a runtime executes it.
- **Blitzy** (coding only, enterprise): maps the codebase into a knowledge graph, turns requirements into a
  specification and an action plan, runs thousands of agents created for the job across several models, and checks
  the result against the specification. Its scale figures are its own and unverified. The pattern is worth copying,
  the scale is not a goal on one PC: task → specification → plan → agents chosen for the job → check against the
  specification.
- **Standards.** MCP (agents to tools) and A2A (agents to agents) are both hosted by the Linux Foundation.
  OpenTelemetry's GenAI conventions model an agent run as one span tree (`invoke_agent` with `chat` and
  `execute_tool` under it); they are still at development status.
- **Durable execution** (Temporal, Restate) is becoming standard for agents that run for days: each step is recorded
  and resumes after a crash.
- **Routing.** Learned routers save money per call, but on long agent tasks the Vals Router Index (20 October 2026)
  found that none of the routers it tested beat the best single model. Route by task type from measured results, not
  per call.
- **Self-designed agents.** Automated Design of Agentic Systems: a meta-agent writes agents as code and keeps a
  scored archive of designs.

## The phases

Each phase ships, is tested and deployed on its own, and the next one starts only when its gate is met (the same rule
as the swarm's phases, SWM-85).

| Phase | What it brings | Requirements | Gate |
|---|---|---|---|
| 0. Headroom | Memory the swarm can use, chat through usage limits, one notification path | CST-14, AST-12, OBS-16 (existing) | A week in which the PC keeps 1 GB free with the stack, a build and a Claude session running |
| 1. Task kernel | One task object, one composer, the intake agent's specification, the task board | TSK-01 to TSK-04, TSK-20 decided | 20 recorded one-sentence tasks (coding, research, analysis, watching) each get a specification with a checkable definition of done |
| 2. Plan graph and durable steps | The Conductor's plan graph, steps that survive restarts, any step on any harness, admission by headroom, one trace per task | TSK-05 to TSK-09 | A five-step task on three harnesses survives a runner kill at step 3, with one complete trace tree |
| 3. Event fabric | One event bus, trigger rules, breaking-news detection | TSK-10 to TSK-12 | Each source fires in a test; a week of feeds gives breaking-news events the owner rates as right |
| 4. Self-staffing | Measured abilities, routing, agents made for a task, good ones made permanent, tasks judged against their definition of done | TSK-13 to TSK-17 | Routing beats the fixed assignment on the replay sets; a temporary agent is created and ended within its grants (security review) |
| 5. Reach | More harnesses at no cost, outside agents through A2A | TSK-18, TSK-19 decided | The owner approves the exposure |

Progress:

- **Phase 0, software part (31 Oct 2026):** one notification path with preferences and quiet hours (OBS-16), and chat
  through a usage limit (AST-12). The memory gate (CST-14) waits for more RAM.
- **Phase 1 (31 Oct 2026):** the task kernel (`ops/tasks.py`): one task for every kind of work, the composer on Home
  and on Tasks, the intake agent's specification, and the task board (TSK-01 to TSK-04). The board's live tree of agents
  inside a task waits for phase 2's one trace per task (TSK-09). TSK-20 is decided (DEC-34): tasks start when
  planned, and each door keeps its own approvals.
- **Phase 2 (31 Oct 2026):** the Conductor (`ops/conductor.py`): a one-off task whose plan uses two or more agents runs
  as a plan graph, each step on its agent's harness (Hermes, Claude Code, Python), recorded before and after it runs,
  started only with headroom, and the task one trace with a run per step (TSK-05 to TSK-09). The gate passed: five
  steps on Hermes, Claude Code and Python, the runner restarted while the Claude step waited, every step ran once, one
  trace (`eval/results/20261031-152501-conductor-gate.json`). OpenCode has no adapter yet, and the trace is not yet
  exported to Phoenix.
- **Phase 3 (31 Oct 2026):** the event bus (`ops/events.py`): one event log from news, breaking stories, feeds,
  GitHub, prices, filings, Forgejo, mail, the House, files, schedules, finished tasks and the missions' own triggers;
  the owner's rules start tasks (cooldown, optional model check, every firing recorded); breaking news is a story three
  publishers report within 30 minutes (TSK-10 to TSK-12). No calendar yet. The gate's second half, a week of breaking
  stories the owner rates on Tasks → Triggers, has started.
- **Phase 4 (31 Oct 2026):** self-staffing (`ops/staffing.py`): each finished task judged point by point against its
  definition of done, a daily history per agent, model and kind, routing by those results and away from a subscription
  at its limit, temporary agents for steps no agent fits (one model call, own key, no tools, ended with the task), and an
  idea for a permanent agent after three met tasks (TSK-13 to TSK-17). Security review: docs/SECURITY.md. Whether routing
  beats the fixed assignment needs enough judged tasks to measure.

## Built here, and what is not

- **The plan graph and the step journal live with the tasks** (the runner's task database, DEC-35) instead of
  Temporal or Restate: a durable engine is the right idea, but another server does not fit 16 GB. (The roadmap first
  said the Ledger; a step has to be recorded in the same transaction that starts it, and the Ledger is another service.)
- **Plans are written by a model** (as the dynamic workflows do), but run on our own runner, so a step can go to any
  harness and model, not only Claude.
- **No per-call router.** Routing is by task type, from the Checker's measured results.
- **No Blitzy scale.** Thousands of parallel agents need paid cloud capacity; on this PC the limit is memory and the
  subscriptions' usage limits, so the Conductor admits steps by headroom (TSK-08).
- **Standards over bespoke parts** keep it low-maintenance: OpenTelemetry's span shape for traces, A2A for agents,
  MCP for tools.

## Decisions for the owner

1. **What the Conductor may do without asking** (TSK-20): decided on 31 Oct 2026 (DEC-34), the proposed default. It
   plans, staffs and runs tasks and creates temporary agents within read-only and sandboxed grants, and asks before
   messaging other people, spending money, deploying code, deleting data or acting on the AI phone.
2. **The $0 rule** (CST-02): it stays, unless the owner wants paid cloud capacity for more parallel agents.
3. **Hardware:** 32 or 64 GB of RAM is the cheapest way through phase 0's gate.
4. **Outside agents** (TSK-19, proposed): whether agents outside the stack may send it tasks over the tailnet.

## Sources

- Anthropic: [Managed Agents multiagent orchestration](https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration),
  [Claude Code dynamic workflows](https://code.claude.com/docs/en/workflows),
  [release notes](https://platform.claude.com/docs/en/release-notes/overview)
- Blitzy: [blitzy.com](https://blitzy.com/), [SWE-Bench Pro post](https://blitzy.com/blog/blitzy-scores-a-record-66-5-on-swe-bench-pro),
  [TWIML podcast with its CTO](https://twimlai.com/podcast/twimlai/agent-swarms-knowledge-graphs-autonomous-software-development)
- [Linux Foundation: A2A at one year](https://linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)
- [OpenTelemetry GenAI conventions explained](https://www.dash0.com/knowledge/opentelemetry-genai-semantic-conventions-explained)
- [Durable execution for agents](https://forkast.news/durable-execution-is-the-next-agent-infrastructure-sub-sector)
- [Vals Router Index](https://www.vals.ai/benchmarks/vals_router_index)
- [Automated Design of Agentic Systems](https://iclr.cc/virtual/2025/poster/28073)
