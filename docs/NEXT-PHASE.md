# The next phase: earned autonomy, four flagships, a standing benchmark, one kind of job

Designed 2 Nov 2026 at the owner's request ("All of this I want. Design it out ... we need to probe this AI Stack with
experiments and tasks"). It follows the analysis of the same day: the stack can do hard work (the Mustache trial: 136
of 136 from the spec alone) and is measured and gated, but it is ahead of its use, its weak points are the joins
between agents, the owner's taps queue up, and it runs on a PC with too little memory. The 32 GB upgrade is coming;
until then everything here has to fit what there is, which is a good discipline anyway.

Requirements: `requirements/autonomy.yaml` (AUT, new), TRL-14..17, PLT-24..27, SHP-13, MIS-22, BLD-25, VOI-09, all
*proposed* until the owner takes each phase.

## Where we stand (measured 2 Nov)

| What | Number | Source |
|---|---|---|
| Runs on record | since 28 Oct only (5 days) | runtime.db |
| Busiest agents, 5 days | scout 239 runs, claude-task 101, crew checker 95 (**25 failed**), main 64, mission 56 | runtime.db |
| Agents with one or two runs | presenter, tracer, breaker, planner, evals, house, crew tests, crew maintainability, coach ... | runtime.db |
| Tasks | 113: 47 Claude, 26 chat, 13 build, 12 mission, 14 planned | missions.sqlite |
| Ways to schedule work | 4: missions, 11 crew timers, 11 maintenance timers, Conductor tasks | systemd, missions.sqlite |
| Places that wait for the owner | 9: task start, task questions, build deploy, purchases, phone steps, Keeper disputes, agent changes, skills, ideas | code |
| Memory | WSL 10 GB, 547 MB free, swap 2.9 of 3 GB used; Hindsight 1.5 GB, LiteLLM 630 MB, builder 610 MB, Hermes 520 MB, qmd 485 MB, Ollama 410 MB | free, docker stats |
| Largest files | app.js 4,040 lines, server.py 2,794 | wc |

Two things follow. Nobody can yet say what is unused, because the record is five days old and the app does not count
which screens are opened; and the crew's checker fails one run in four, which no page has raised.

## Principles

1. **Autonomy is earned, per kind of action, and lost automatically.** Never granted in general.
2. **Shadow first.** Before the stack may do something unasked, it decides it in the shadow for two weeks and its
   decisions are compared with yours. Agreement is the evidence; a trial alone is not.
3. **Some things stay yours, always.** Money, people, irreversible acts, security. No score buys them.
4. **One of each.** One kind of job, one decision queue, one page per thing, one audit trail.
5. **Measured by what you get.** Every flagship has one outcome number; a feature without one is a candidate to retire.
6. **Fits in 10 GB.** One trial or heavy job at a time; idle services sleep; every container has a budget.

## Part 1: Earned autonomy

### The idea

The Memory Keeper already works this way: it changes long-term memory without asking only while its answer-key
trial passes (precision ≥ 0.95, recall ≥ 0.6, at most 40 changes a pass), every change is logged and can be undone, and
a failed trial sends it back to suggesting. Part 1 makes that the rule for every kind of action that waits for you
today.

### Action classes and licences

An **action class** is one kind of thing the stack does that can wait for you: "start a research task it proposed
itself", "deploy a low-risk change", "run a routine phone step". Each class has a **licence** at one of three levels:

| Level | Name | What happens | You see it |
|---|---|---|---|
| L0 | Ask | it waits in the decision queue | a decision |
| L1 | Do and tell | it acts, tells you once, and keeps an undo for a set window | a line in the day's digest with Undo |
| L2 | Do quietly | it acts and records it | the class's page and the weekly summary |

A licence is held while **all** of these hold, checked after every exam and every act:

- **The exam passes:** the class's answer-key trial scores at or above its bar on its last three runs.
- **The shadow agrees:** while at L0 the stack also records what it *would* have decided; over the last 20 of your real
  decisions in that class it agreed with at least 90 % and never chose the unsafe side (approve where you refused).
- **The record is clean:** at L1 or L2, none of its acts in 14 days was undone by you or failed its own check.

**Promotion** to the next level needs all three plus one tap from you (a decision in the queue: "Research may now run
unasked. Allow?"). **Demotion** is automatic and immediate: a failed exam, a disagreement where you refused, an undo,
or a failed act drops the class one level and says why. A change to the agent, prompt or code a class runs on puts its
licence back under exam (the benchmark, Part 3) before it acts again.

### The classes

| Class | What it may do | Exam (answer key) | Highest level | Stays yours |
|---|---|---|---|---|
| memory | retire, translate, merge long-term facts; settle disputes | the Keeper's trial (exists) | L2 (now) | retiring a fact you wrote |
| research | start a research or refresh task it proposed itself, within a token budget | **research accuracy**: 25 questions with known answers from stable sources; claims checked, citations checked | L1 | anything that spends money or writes to someone |
| briefing | drop an item rated noise, re-time a briefing, add a source | the briefing's own ratings (Part 2) | L1 | starting or deleting a briefing |
| shopping-pick | choose which offer to propose, discard bad ones | **offer picking**: 30 recorded offer sets with the right pick and traps (refurbished, wrong kit size, marketplace sellers, shipping on top) | L2 | **buying**: always your tap, at a ceiling you set |
| coding-low-risk | deploy a change after both reviews pass | **coding** (semver, Mustache) and **review catch**: 10 seeded bugs the reviews must find | L1, with automatic revert on a failed health check | security, compose, secrets, NAS, network, anything public |
| phone-routine | the routines you listed (storage cleanup steps, app updates, reading a screen) | **phone routine**: a scripted run on the AI phone with checks | L1 | messages, calls, purchases, accounts, settings |
| wiki | fold findings into a wiki, mark contradictions | the memory trial's wiki half | L2 (now) | deleting a wiki |
| ideas | turn an agent's idea into a task | shadow agreement only | L1 | ideas that cost money |

**Low risk** for coding is a rule, not a judgement: under 300 changed lines; no path under `secrets/`, `compose/`,
`nas/`, the security checks in `ops/`, `config/agents.yaml`, `.github/`; no requirement's status lowered; the checks and both
reviews pass; one commit, revertible on its own.

### The floor: never licensed

Money above a ceiling you set per wish, and any new payee. Writing to a person (mail, chat, comments) in your name.
Deleting data that has no undo. Security settings, credentials, accounts, public exposure, port forwarding. Anything
on the AI phone outside the listed routines. These stay L0 by construction: the licence code has no path that raises
them, and a test says so.

### One place that decides

a new ops/autonomy.py holds the classes (a new config/autonomy.yaml: exam, bars, highest level, floor), each class's state
(`/srv/ai/state/autonomy.json`: level, exam scores, shadow agreement, last acts) and one function every door calls:

```
decide(cls, item) -> "ask" | "act" | "act-quietly", with the reason
```

The doors keep their own safety (the shopping file's ceiling and words, the phone's standing permission, the build's
checks); the licence only says whether the owner's tap is needed in between. Every act is logged with the evidence that
allowed it (`/srv/ai/state/autonomy.jsonl`) and appears in the run record and on the class's page (`#/autonomy`).

### The decision queue

Everything that waits for you becomes one list, `#/decide`, instead of nine places:

| Source today | Becomes |
|---|---|
| a task waiting for its start, a task's questions | "Start this task?" / its questions |
| a build ready to deploy | "Deploy build #N?" with the reviews' verdicts |
| a purchase proposal | "Buy X for €N at Y?" with the comparison |
| phone steps | "Run these 4 cleanup steps?" |
| a Keeper dispute its research could not settle | "Which is true?" with both sides |
| the coach's agent change, a skill, an idea | "Take this change?" |
| a licence promotion | "Research may now run unasked?" |

Each decision carries: what, why, the stack's recommendation and how sure it is, what happens if you do not answer
(and when), and one-tap answers. They are ranked by what expires first and what costs most to delay. Routine ones of a
class can be taken together ("Approve all 4 phone steps"), as phone cleanup already allows.

- **Once a day**, at a time you pick, one notification: "3 decisions need you" (Telegram and the app). Nothing else
  pings for a decision unless it expires within two hours.
- **By voice**: "Hermes, what needs me?" reads them one by one; you answer yes, no or later. Voice may answer anything
  but money: a purchase is confirmed by tap in the app, where the amount is on screen.
- **Measured**: decisions a day, median time to answer, how many expired. Target: at most 5 a day, answered within 12
  hours; the number falls as classes earn licences.

## Part 2: Four flagships, excellent end to end

Each flagship has one outcome number shown on its page and in the weekly summary, a journey from your sentence to the
result, and a probe that exercises it.

### Shopping: watch, decide, buy within limits

- **Outcome:** price paid against the best valid offer seen in the window (lower is better, target within 5 %), and
  days from wish to delivery.
- **Journey:** wish ("32 GB DDR4 for my PC, up to €150 delivered") → it asks only what it must (budget, deadline) →
  watches → proposes the best valid offer with the runners-up and why → you tap Buy → it buys through the narrow
  purchase file → tracks the delivery → asks you once that it arrived and works → closes with the outcome number.
- **Gaps:** delivery tracking and the "arrived and works" close are missing; the pick is not examined (the offer-picking
  trial, Part 3); a proposal does not show the window's price history.
- **Live case:** the RAM upgrade. It runs as it does now; the comparison against the best offer is computed when it ends.

### Home voice: Hermes in every room

- **Outcome:** spoken questions answered a day, and the share answered in under 4 seconds.
- **Journey:** the V1 to V5 phases of `docs/HOME-VOICE.md`, unchanged; V4 ("research X" by voice, the result spoken
  where you are) joins the decision queue (Part 1).
- **Probe:** the speech test with your recorded voice, weekly (the benchmark's voice slot): words wrong, first word
  time, false wakes.

### Briefings that change a decision

- **Outcome:** the share of briefings you rated "I acted on this" or "useful", against "noise".
- **Journey:** each briefing (uranium, ASP Isotopes, China automotive) ends with three buttons in the mail, the app and
  Telegram: **Acted on it · Useful · Noise**, and an optional line. Ratings feed the desk: an item kind rated noise
  three times is dropped (licence class *briefing*); a briefing rated noise three weeks running asks whether to stop.
- **Exam:** the research-accuracy trial covers its facts; the citations are checked against the sources it read (the
  task page's sources already show which were cited).

### The builder on your own projects

- **Outcome:** changes to your own repositories merged a week, and how many were reverted.
- **Journey:** "fix X in TestRepo" from the phone → plan → build in the sandbox → both reviews → your tap (or L1 for low
  risk, Part 1) → deployed → the task page shows the diff, the reviews and the checks.
- **Probe:** one real change a week on TestRepo or another repository you name, plus the review-catch exam.

## Part 3: A standing benchmark

The trials become a weekly rotation with a trend line, and a change that lowers a score does not ship.

### The rotation

One trial a night at 01:00, never two at once (memory), the slot skipped when a task is running:

| Night | Trial | Exam for | Exists |
|---|---|---|---|
| Mon | research accuracy (25 questions, known answers) | research, briefing | new |
| Tue | stack-trace (the stack against its requirements) | coding | yes |
| Wed | memory (the Keeper's 32 planted facts) | memory, wiki | yes |
| Thu | coding: semver and Mustache in turn | coding-low-risk | yes |
| Fri | review catch (10 seeded bugs on a TestRepo branch) | coding-low-risk | new |
| Sat | offer picking (30 recorded offer sets) | shopping-pick | new |
| Sun | phone routine, then the voice speech test | phone-routine, voice | new |

mqtt-trace stays a monthly deep run. A new trial runs three times when it is added, to measure its own noise: the
spread of those three runs is its noise band.

### The gate

- **Prompt and agent changes:** as today, a replay must not lower any score; in addition, the trial of every class the
  agent serves runs before the change lands.
- **Code changes:** cannot wait a week, so they land as now; the next night's trial of each class whose code changed
  runs first in the rotation. A drop beyond the noise band opens a finding, freezes that class's licence at L0, and
  names the commits since the last good run.
- **The trend:** `#/trials` draws each trial's score, time and tokens over the weeks, with the commits between points.

## Part 4: Consolidate

### One kind of job

Today work is scheduled four ways. The model becomes one: a **task** with a rhythm (once, schedule, event, after
another), a door (who does it), a definition of done, a licence class, and its page. Missions, crew jobs and the
Conductor's tasks are tasks; machine upkeep (backup, restore drill, upgrade check, sync jobs) stays systemd timers,
because it is not agent work, but each reports as a task run so it has a page and appears in one list.

The move, in three steps, each one shippable:

1. **Crew jobs as tasks.** Each `crew-*.timer` calls the runner's inbox instead of the job directly; the job runs as a
   task with door `crew` and its run is that task's. The crew pages stay, reading from the task.
2. **Missions as tasks, finished.** Briefings and shopping already run under the Conductor; long-term missions and
   price watches follow; the mission scheduler is removed. A mission's page becomes the task's page with its wiki and
   topic.
3. **One list.** The Tasks board shows everything that runs, with a filter for scheduled, crew and upkeep; the Agents
   pages read their work from tasks.

### Split the two big files

- `server.py` (2,794 lines) into routers by area: tasks, wiki and memory, shopping, phone and house, swarm, system and
  telemetry, the A2A door; `server.py` keeps the app's assembly and the middleware.
- `app.js` (4,040 lines) into one file per area, as `task.js`, `swarm.js`, `shop.js` and `guide.js` already are; `app.js`
  keeps routing, the formatting block and the shared helpers.
- A test fails when a source file passes 1,500 lines.

### Retire what nobody uses

- **Start counting now.** The app records which screens are opened (route, day, count; nothing else) and the run record
  already counts agent runs. After 30 days (from 2 Dec) a monthly report lists agents with no run, screens with no
  visit and services with no call in 30 days.
- **Retirement is your decision**, one per item in the queue, with what it costs (memory, code, tests) and what goes
  with it.
- **Candidates to check now**, not to remove yet: Open WebUI (175 MB; the app has its own chat), the Hermes dashboard
  (165 MB), OpenCode (190 MB; a step adapter with few runs), Ollama (410 MB; check what still calls it), agents with one
  or two runs in five days (presenter, tracer, breaker, planner, house).

### Memory budget (until the 32 GB, and after)

- Each container gets a budget under its limit and the doctor reports one that stays above it.
- Services used only by trials and builds (OpenCode, the browser, the CI runner) start on demand and stop when idle.
- Hindsight (1.5 GB) is the biggest single user: measure what it needs and cap it.
- Target until the upgrade: swap under 1 GB in a normal day, no WSL time-outs in the doctor's checks.

## Part 5: Probing the stack: experiments

The benchmark checks that nothing gets worse. Probes look for what we do not know yet. Each has a question, a setup,
what is measured and what we change if it fails. One a night, small enough for the memory there is.

| # | Probe | Question | Measure |
|---|---|---|---|
| P1 | The failing checker | why does the crew's checker fail one run in four? | its 25 failed runs, grouped by cause |
| P2 | Two at once | do two tasks that use the scout at the same time stay apart (FND-111) and fit in memory? | each task's sources and tokens; swap; time-outs |
| P3 | One sentence | given ten underspecified one-sentence tasks, does the intake ask the right questions and plan well? | a grader's score per plan against a rubric written before |
| P4 | Pull the plug | a container is stopped mid-task: does the task resume or fail honestly, with the reason on its page? | end state, the page, the run record |
| P5 | The memory ceiling | a briefing and a trial at once: where do time-outs start? | free memory, swap, failures, per container |
| P6 | Breaking news | a planted event on the bus: how long until the alert reaches you? | minutes from event to message |
| P7 | Remember last week | ten facts from last week's work asked in chat | right, wrong, "I don't know" |
| P8 | Long horizon | a three-day watch with checkpoints (the RAM watch is one) | it stays on course; checkpoints change the plan when they should |
| P9 | Shadow agreement | two weeks of the decision queue in shadow | agreement with your decisions, per class |
| P10 | Your voice | the speech test with your recordings, TV on and off | words wrong, first word time |

Each probe is a task like any other (source `probe:<name>`), so its page shows who worked, what was read and what went
wrong, and its result goes into a new docs/PROBES.md with the change it led to.

## The order

| Phase | What | Done when |
|---|---|---|
| N1 (week 1) | decision queue (all nine sources), the shadow for every class, screen counts, the research-accuracy trial, the rotation with what exists, probes P1, P2, P4 | every decision is in one list; the shadow records; a week of the rotation on #/trials |
| N2 (week 2) | offer-picking and review-catch trials; briefing ratings; shopping's delivery close; crew jobs as tasks; probes P3, P5, P6 | each flagship shows its outcome number; crew runs are task runs |
| N3 (weeks 3–4) | first licences (research, shopping-pick) after shadow and exams; coding-low-risk at L1 with auto-revert; missions as tasks; the server.py split; probes P7, P8, P9 | at least two classes earned L1 with your tap; one way to schedule work |
| N4 (week 5+) | phone routines; the app.js split; the first unused report and retirements; voice V2 onward | decisions per day fall; the unused report has been acted on |

## Decisions for the owner

| # | Decision | Proposal |
|---|---|---|
| D1 | The floor (never licensed) | as listed: money above a ceiling, new payees, writing to people, unrecoverable deletion, security, accounts, public exposure, phone outside routines |
| D2 | Promotion needs your tap | yes, once per class and level; demotion never needs you |
| D3 | Voice may answer decisions | yes, except money |
| D4 | The daily decision time | 08:00, with the morning briefings |
| D5 | Benchmark nights | 01:00, one a night, as in the rotation |
| D6 | Low risk for code | as defined above, auto-revert on a failed health check |
| D7 | Retirements | after the first 30-day report, one by one in the queue |
| D8 | Strong models for critical calls (Part 6) | link the Max plan's API credits to a Console organisation with no card and no auto-reload; allow them for the calls in Part 6 only |

## Part 6: Strong models where it matters

Added 2 Nov after the owner learned the Max plan includes API credits: "some agents with low token throughput but high
criticality [should] use stronger models".

### What pays for what today

| Engine | How it is paid | What runs on it (5 days to 2 Nov) |
|---|---|---|
| ChatGPT (gpt-sub, gpt-sub-fast) | the Plus subscription, through the Codex sign-in; its usage limits | 2,400 calls: the scout (30 M input tokens), Hermes, missions, the curator, and every direct call of the runner: planning, the Orchestrator's checkpoints, the judge, the Keeper, the desk's writing |
| Claude Code (Sonnet 5.5) | the Max subscription; its usage limits | 442 calls: Claude tasks, the builder's Claude side, the reviews, the coach |
| The Claude API | nothing yet: the Max plan's $100 a month in API credits is unclaimed | an old API key sits unused in the gateway |

### The idea

Most tokens go to bulk work (searching, reading, chatting), where a fast model is right. A few calls decide where the
rest goes or what you are told: the plan, the checks between waves, the verdict on done, what memory keeps, the
briefing's final text, the offer proposed to you. They are few and small, and a mistake there costs more than
everything else. They get the strongest model; the bulk stays where it is.

| Tier | Model | Paid by | Used for |
|---|---|---|---|
| Critical | Claude Opus 5.5, effort high | the Max plan's monthly API credits | the calls below |
| Critical, by Claude Code | Claude Code with `--model opus` | the Max subscription's limits | the reviews of a build, the coach's agent changes, the trace analyses of the trials |
| Bulk | gpt-sub, gpt-sub-fast | ChatGPT Plus | the scout, Hermes, missions, the curator, extraction |
| Fallback | gpt-sub | ChatGPT Plus | any critical call when the API fails, refuses, or the month's budget is spent |

### The critical calls and what they would cost

At Opus 5.5's list price ($4 per million input tokens, $20 per million output; thinking counts as output), from the
volumes of the last five days times six, with output tripled for thinking:

| Call | Where | A month | Opus 5.5 |
|---|---|---|---|
| The plan of a task (intake) and the Orchestrator's checkpoints | tasks.intake, conductor checkpoint | 0.2 M in, 0.15 M out | ~$4 |
| The verdict on done (the judge) | staffing.judge | 0.6 M in, 0.25 M out | ~$7 |
| The Keeper's weekly judgement pass | keeper (KEEPER_DEEP) | 1.4 M in, 0.3 M out | ~$12 |
| A briefing's final text and an alert | desk write, desk alert | 0.1 M in, 0.15 M out | ~$4 |
| The offer proposed to you | shopping, the pick step only | 0.2 M in, 0.1 M out | ~$3 |
| Grading the new exams (research accuracy) | trials | 0.3 M in, 0.1 M out | ~$3 |
| **Together** | | | **~$33 of the $100** |

The rest is headroom for growth and for the probes that compare models. Claude Fable 5.1 (2.5 times the price) is not
needed for any of these; the plan is the one call worth testing it on (probe P11).

### How it stays at no extra cost

- The credits are claimed by linking a Console organisation in claude.ai (Settings, Billing, API credits) with **no card
  and no auto-reload**: when the month's credits are spent, Anthropic stops the requests; nothing is charged.
- The gateway gets one model, `claude-critical` (Opus 5.5), on that organisation's key, with gpt-sub as its fallback, so
  a spent budget, an error or a refusal never stops the work; it only goes back to ChatGPT.
- The stack meters the month's spend from the run record (it already prices every call) and moves the critical calls
  back to gpt-sub at 80 %, so the last fifth stays for the plan and the judge; the meter shows on the Stack page.
- The old, unused API key in the gateway is removed; the new key comes in through the secrets file like every other.
- Only the named calls may use `claude-critical`; a test fails when any other code names it.

### Proving it is worth it

A stronger model is a change like any other: it must earn its place on the benchmark. Probe P11 runs the judge on the
trials' finished runs both ways and compares each verdict with the answer key (the judge said "partly" on runs the key
scored 136 of 136, FND-92); probe P12 runs the planner on ten one-sentence tasks both ways and grades the plans against
a rubric written before. A call moves to Opus 5.5 when its probe shows it better, and stays on ChatGPT when it does not.

| # | Probe | Question | Measure |
|---|---|---|---|
| P11 | Judge strength | does Opus 5.5 judge done more like the answer keys than gpt-sub? | agreement with the key on every finished trial run |
| P12 | Plan strength | do plans from Opus 5.5 (and Fable 5.1) score higher than gpt-sub's? | a rubric score per plan, written before the run |
