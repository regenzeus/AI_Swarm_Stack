# Trials: the swarm gets better by being used

Design, 1 November 2026. Status: the owner took the proposals of the open points (1 Nov); phases 10a and 10b are built
(ops/trials.py, eval/trials, the role cards, the check and its fix loop, budgets; TRL-01 to TRL-11); the
Orchestrator's re-planning checkpoint (TRL-08) and 10c to 10d are next. It builds on
[SWARM-DESIGN.md](SWARM-DESIGN.md) (tasks, the Conductor, artifacts, telemetry) and [SWARM-ROADMAP.md](SWARM-ROADMAP.md).

## What the owner wants

Read from the request of 1 November, not only its words:

1. **One front door.** Give the stack any task in a sentence; it plans, staffs the agents it needs, coordinates them,
   delivers, and says what came of it. Software tasks are the hardest case, not the only one.
2. **To know how good the swarm is, as a number.** Hard, realistic tasks with an answer key ("trials"): did the
   swarm's software pass the test suite, did it find the requirements the code misses, what did it cost, where did it
   need a human.
3. **A loop that improves it through use.** Run a trial, see where it went wrong with the evidence, change one thing,
   prove the change helped on the same trial, keep it. Real tasks feed the same loop; trials are its controlled form.
4. **Trustworthy work through separation of duties.** The one who writes the code does not write the tests, does not
   judge the result and does not see the answer key, as in any good engineering team.
5. **Results to read, not counters.** One report per task that says what was achieved against what was asked, with
   the evidence, what went wrong and what it cost. The Payoff tab is that report per agent.

## What the stack has today, and what is missing

| Needed | Today | Missing |
|---|---|---|
| A task in a sentence, planned | intake: kind, definition of done, a plan of steps with agents (TSK-01 to TSK-04) | - |
| The plan run, in parallel, resumable | the Conductor: a step graph, fan-out, headroom, restarts (TSK-05 to TSK-09) | **loops** (code, test, fix until it passes: a cycle is refused today) and **re-planning** (the plan is fixed once made) |
| The right agent for a step | routing by measured ability, temporary agents with their own keys (TSK-13 to TSK-15) | the **roles** software work needs (below) |
| Code changes | the builder in its sandbox, two reviewers of the other engine, merge queue, parallel builders with file leases | a **fresh project** as the target (today: changes to existing repositories) |
| Judging a result | a model reads the result against the definition of done (TSK-22) | **judging by running tests** and other checks that do not depend on a model's opinion |
| Seeing how it went | provenance, the swarm map, the timeline, telemetry, Phoenix traces (TSK-23 to TSK-27) | a **trial scoreboard** across runs and versions |
| Learning from it | replay sets, failure classes (MAST), the Coach's agent changes, each replayed before it applies; the Checker | a **retro** after each run that turns what went wrong into findings with evidence |
| Limits | headroom on RAM; subscriptions only | **budgets** per task (TSK-28 partial) |
| Results for the owner | a judged result file, a Telegram line | a **report** (the Presenter) |

The answer key for requirements work exists already: the MQTT 5.0 pilot (`spec/README.md`) maps 252 numbered
requirements to the mochi-mqtt broker, whose code carries 186 of the IDs, and has 7 planted deviations. Its fixed
pipeline found the right function for 73% of the requirements and caught 6 of 9 planted deviations. That is the bar
the swarm has to beat on the same material.

## Names

- **Orchestrator** is the role that turns a task into a plan, runs it, checks it at each wave and changes the plan when
  the work shows it must (today intake plans and the Conductor runs; the Conductor is the code, the Orchestrator the
  role the owner sees). "Mission" is not the orchestrator: it is a generalist worker that runs missions and steps.
- **Coordinator**, as an agent that watches all agents and finds where they should work together, is *not* recommended
  as a first step. The MAST study of 2025 sorts multi-agent failures into three kinds: the task and the roles were
  specified badly, the agents misread each other, the result was not checked; the remedies it points to are clearer
  specifications, roles and checks, which a go-between does not supply, while a free-running watcher adds tokens and
  messages to every task. Within
  a task the Orchestrator's checkpoint does that work: after each wave it reads what came back, spots overlaps, gaps and
  conflicts and adjusts the plan. Across tasks the Board and the Ledger already join agents to shared work. The
  Coordinator becomes worth its cost when trials show cross-task waste (duplicate work, conflicting changes, agents
  waiting on each other); the scoreboard measures exactly that.
- **Presenter**: yes, the role that writes the owner's report of a task and fills each agent's results.

## The roster

Roles are cards in `config/agents.yaml`: a purpose, a harness, a model, the tools it may use, what it may read, and its
lane. Most are staffed per task as temporary agents with their own keys that end with the task (TSK-15), so the roster
grows without more always-on agents and without more RAM. The rules every role follows:

- **Separation of duties**: the author of the code, the author of the tests, the reviewer and the judge are different
  agents, and the judge is a program where one exists (a test suite, a parser, a type checker).
- **Information barriers**: what a role may not see is enforced by its key, its network and its workspace, and checked
  afterwards from provenance, not asked for in a prompt.
- **Different engines for checks**: a reviewer runs on the other engine than the author (already so for builds).
- **Briefs, not chatter**: the Orchestrator gives each step a complete brief (goal, inputs, done criteria, what not to
  do); agents hand over through artifacts in the Ledger, not long conversations.

| Role | Does | May read | May not | Exists |
|---|---|---|---|---|
| **Orchestrator** | plans, staffs, runs, checks each wave, re-plans, stops at the budget | everything of the task | do the steps itself | half (intake + Conductor; no checkpoints) |
| **Scout** | research on the web | the web | the owner's private data | yes |
| **Analyst** | writes numbered, testable requirements from specs and documentation, with their sources (EARS form: "When X, the parser shall Y") | specs, docs, manuals | source code, test suites of the target | new |
| **Architect** | modules, interfaces, the task graph for parallel coders | requirements | - | yes (planner) |
| **Coder** | implements tasks in the sandbox, with its own unit tests | requirements, the design, its workspace | the answer key, upstream code | yes (builder; opencode as a second engine) |
| **Tester** | writes acceptance tests from the requirements alone, before or beside the code, each test tagged with its requirement | requirements | the code under test, the answer key | new |
| **Reviewer** | reviews each change against requirements and for security, on the other engine | the change, requirements | - | yes (build reviewers) |
| **Breaker** | tries to make the software fail: edge cases, property-based tests, fuzzing, differential runs against a reference used only as a black box; each report comes with a reproducer | requirements, the program as a black box, a reference as a black box | the answer key; reading upstream code | new |
| **Tracer** | maps each requirement to the code and tests that fulfil it, with evidence, and marks each one met, partial, unmet or contradicted: the gaps are this map's open rows | requirements, code, tests | - | new (the spec pipeline as its tools) |
| **Judge** | scores a result: runs the test suites and checks, and only where no program can judge, a model against the definition of done | everything of the task, the answer key | change anything | half (model only) |
| **Presenter** | writes the task's report and each agent's results | everything of the task | - | new |
| **Coach** | turns scorecards and retros into agent changes, replayed before they apply | runs, scorecards | - | yes |

The requirements mapper and the gap finder the owner named are one role here, the Tracer: gaps are the rows of the
trace that are not met, and finding them needs the same reading of code and requirements. Splitting it would double the
reading for no extra signal; the trial measures mapping and gap finding separately.

## Trials

A trial is a task the owner could have typed, plus an answer key the swarm never sees, a scorer, rules, a budget and
how often to repeat it, in eval/trials/<name>.yaml (the semver trial is the first):

```yaml
name: mustache-cleanroom
task: >-                                   # what the owner types; the trial goes through the real front door
  Build a Python library that renders Mustache templates, from the Mustache specification only. Do not use or read
  any existing Mustache implementation.
forbidden:                                 # enforced: proxy deny list, fetch guard, key scopes; audited from provenance
  urls: [github.com/noahmorrison/chevron, github.com/defunkt/pystache, github.com/mustache/spec]
  packages: [chevron, pystache]
inputs: /srv/ai/trials/mustache/spec/          # the spec's prose and the mustache(5) manual, its test cases taken out
answer_key: /srv/ai/private/trials/mustache/   # outside every agent's reach
scorer: python3 eval/trials/score_mustache.py   # runs the official spec suite against the delivered package
budget: {tokens: 3000000, hours: 8, usage_windows: 2}
arms: [baseline]                           # e.g. [no-tester, tester] to measure what a role adds
repeats: 2                                 # the swarm is not deterministic; one run says little
```

`make trial NAME=semver` gives the task through intake like the owner would, watches it, runs the scorer
when it ends or the budget runs out, runs the clean-room audit, asks the Presenter for the report and writes
`eval/results/<time>-trial-<name>.json`. A trial never runs during a gate or another trial, and runs at night.

### T1: clean-room reimplementation from a specification

Projects whose specification is public and comes with an **official, language-independent test suite**, so the
answer key is not one project's own tests:

| Project | Specification | Answer key | Size | Use |
|---|---|---|---|---|
| Semantic Versioning | semver.org 2.0.0 (11 rules) | python-semver's tests, adapted | hours | calibration: does the pipeline work end to end |
| Mustache | the Mustache spec's prose and the mustache(5) manual (the spec's files mix prose and tests: the harness hands over the prose) | the spec's test cases (interpolation, sections, inverted, partials, comments, delimiters; lambdas and inheritance optional) | a day | **first real trial** |
| TOML 1.0 | toml.io | toml-test (hundreds of valid and invalid documents, run through a small decoder program) | days | second trial: much larger, strict errors |
| JSON Schema | json-schema.org (draft 2020-12) | JSON-Schema-Test-Suite | days | alternative to TOML |
| CommonMark | the CommonMark spec (its examples are part of it: half stay visible, half are held back) | the held-back half of its ~650 numbered examples | a week | the stretch goal |

The protocol:

1. **Requirements phase.** The Analyst and the Scout read the specification and its documentation and write
   numbered requirements with their sources. They may read the spec's prose and examples; the test files that form
   the answer key and every implementation are out of reach.
2. **Build phase.** Architect, Coders and Tester work from the requirements only, in a fresh repository. The Tester's
   tests come from the requirements, never from the code. The Conductor loops code, test, fix within the budget.
3. **Breaking phase.** The Breaker attacks the finished library; confirmed failures go back to the Coders once.
4. **Judging.** The harness, not an agent, runs the official suite: the score is the share of cases passed, per area
   of the spec, with required and optional parts apart.
5. **Clean-room audit.** (a) Provenance lists every page, package and file each agent read: any forbidden one fails
   the run. (b) A similarity check (token fingerprints, the method of MOSS and JPlag) against the known
   implementations: high similarity is flagged even without a forbidden read, because models may have memorised
   popular code. Choosing specifications whose best-known implementations are in other languages lowers that risk;
   the check measures what is left.

A second arm can let the Coders see half of the official suite (the commit0 benchmark gives its agents a project's
unit tests) and score on the hidden half: the difference says how much a test suite in hand is worth, and whether the Tester's own tests close that gap.

### T2: requirements tracing and gap finding

Give the swarm a specification's requirements and an implementation: map each requirement to the code and tests
that fulfil it, and name the ones that are not met. Three answer keys, from cheap to strong:

- **MQTT 5.0 and mochi-mqtt**, existing: 186 requirement IDs in the code, 7 planted deviations, and the pipeline's
  numbers to beat (right function 73%, deviations caught 6 of 9, false alarms 0).
- **Our own T1 library**: the hidden suite says which requirements it fails, so the gap finder's answer is known
  without a human. Where in the code a requirement lives is measured, not guessed: the lines its tests run and
  others don't, confirmed by mutating them and watching those tests fail.
- **The upstream implementation** of the same specification (for Mustache, chevron or pystache), traced the same way:
  the comparison of both traces says where each one is incomplete. Real gaps found upstream are the owner's to report.

Scored: mapping precision and recall, gap recall on known failures and planted deviations, false gaps, cost.

### T3: the Breaker

The Breaker gets the program as a black box, the requirements and, where one exists, a reference implementation as a
second black box. Score: confirmed defects (a reproducer, and the specification says our output is wrong), against
false reports. A confirmed upstream defect is a finding for the owner.

### T4: everyday tasks

Software trials must not make everyday work worse. Eight to ten everyday tasks with a rubric (a research question, a
briefing, an analysis of a file, a comparison) run with each trial batch; the intake gate (TSK-03) and the bench stay
as they are.

## Watching a run

Everything below comes from what is already recorded (runs, provenance, the Ledger, telemetry); the trial page puts it
side by side for one run and across runs:

- **Outcome**: the score, per area; the clean-room audit; requirements met.
- **Cost**: tokens, time, usage windows, if-paid; per role.
- **Coordination**: re-plans, handoffs, waits on another agent, rework loops, conflicts on file leases, messages, idle
  agents, duplicate work.
- **Human**: questions asked, approvals needed, interventions.
- **Failures**: by MAST class (specification, between agents, verification), with the step and its log.
- **The owner's notes**: on any step, "this went wrong because ..." (one tap), kept as evidence in the Ledger.

## The improvement loop

1. **Run** a trial (two repeats).
2. **Retro**, written by the Presenter with the Coach: what went well and badly, each with its evidence (a step, a log
   line, a score), filed as findings in the Ledger.
3. **Choose** one to three changes: an agent's card, a role's brief, a new tool, a new role, a change to the
   Orchestrator or the Conductor. The owner decides; nothing applies itself.
4. **Gate**: an agent change is replayed on its past runs (as today); a change to orchestration reruns the cheapest
   trial that showed the problem.
5. **Rerun** and compare on the scoreboard (score, cost, time, interventions), per version of the agents and the code.
   A change that does not help is reverted.

One change at a time where possible, so the scoreboard says which change did what. Real tasks feed the same loop:
every run is judged already, and the owner's notes on them become findings like a trial's.

## The Presenter and the Payoff tab

Every task ends with a report: what was asked and the definition of done; what came of it, point by point, with the
evidence (test scores, files, sources); what each agent contributed; what went wrong and how it was handled; cost and
time; what needs the owner. It is the task's result page and the e-mail when one is asked for.

The Payoff tab becomes **Results**: what this agent delivered that mattered (results accepted, ideas proved, defects
confirmed, requirements traced) with links, and what did not hold up. The counters it shows today are in the agent's
day table already.

## Order of work

| Phase | What | Done when |
|---|---|---|
| 10a (built) | Trial harness (`eval/trials`, `make trial`, scorers, the answer key out of reach); test-based Judge step; fresh-project workspace; clean-room barrier and audit; the Presenter's report | the semver calibration trial runs end to end through intake and scores itself |
| 10b (built) | Analyst, Tester, Tracer, Breaker cards and briefs; bounded loops in the Conductor (code, test, fix); the Orchestrator's checkpoint after each wave with a visible plan change; budgets per task | Mustache runs with all roles inside its budget |
| 10c (T2 built 1 Nov: eval/trials/mqtt-trace.yaml) | T2 on MQTT against the pipeline's numbers; T1 Mustache twice; T2 and T3 on our library and on upstream; retros; first changes through the loop | a scoreboard with two versions and the change between them explained |
| 10d (scoreboard built 1 Nov: #/trials; Payoff is Results, the delivered results first) | Payoff becomes Results; the trial scoreboard in the app; the Coordinator decided from the coordination numbers | the owner reads a trial's outcome on the phone without asking |

## Limits

- **Subscriptions**: ChatGPT Plus has five-hour usage windows; the builder once used 2.5 million tokens in ten minutes.
  A trial states its budget in tokens and windows, runs at night, and stops cleanly when the budget is spent.
- **RAM**: 16 GB (CST-14 is still violated); two builders at once at most, the browser for journeys aside. Trials run
  one at a time and never during a gate.
- **Licences**: the specifications and suites above are openly licensed; an upstream implementation is only run as a
  black box or read by the Tracer for T2, never by the Coders.

## Open decisions for the owner

1. Call the planning and running role **Orchestrator** in the app, and the "mission" agent a **worker**?
2. The **Coordinator** later, when the numbers show cross-task waste, rather than now?
3. First trials: **semver** to calibrate, then **Mustache**, in **Python**?
4. A budget per trial run (proposed: 3 million tokens, two usage windows, nights only)?
5. The second arm with half the official suite visible: yes or later?
6. Defects found in upstream projects: report them yourself, or leave them in the vault?
