# The AI Stack: an observable software factory

*Version 3, 11 Nov 2026. It merges the factory design (v2), the interaction design, the Ask system and run observability, and puts observability at the centre. It replaces the separate documents.*

## 0. What the review found

Read together, the earlier documents disagreed in nine places:

| # | Inconsistency | Resolution in v3 |
|---|---|---|
| 1 | Observability was phase C, after everything else: watching the factory was an afterthought | **The live run is the centre of the product** (§3). It is built together with the move onto one engine, because one can't be had without the other. |
| 2 | "Every workflow shows its diagram" while a briefing is one box: its real steps run hidden inside that box on the old scheduler | **Every agent step is its own n8n node.** Plans made at run time run as a loop of n8n steps (§2, rule 3), so every step can be seen live. |
| 3 | The diagram was drawn by our own renderer | **n8n's own canvas,** with our live layer on top (§4) |
| 4 | Six places listed Improve; the owner wants Code back and Improve out | Home, Workflows, Agents, Code, Chat, Stack. Improve's parts live in Code and Workflows until it has substance. |
| 5 | The Ask system and tickets still spoke of "tasks" | Asks and tickets belong to a **run** and its **work item** (the ticket, mail or request that started it) |
| 6 | Chat was an exception to "everything is a workflow" | **A chat turn is a run** of the Chat workflow. It is observable like any other; replies still stream at chat speed. |
| 7 | A "private run" layer | Dropped at home (the owner). Two rules remain: only ChatGPT reads tax content, and the work deployment's data class applies. |
| 8 | Measures and records lived under Improve | They live under Workflows (per factory) and Stack |
| 9 | Phase A showed old work as runs of standard workflows through an adapter, and rule 2 said all runs are n8n executions | Phase A's adapter is temporary and labelled as such. Phase B ends it. |

## 1. The terms

| Term | What it is |
|---|---|
| **Platform** | The AI Stack itself: n8n, the step service, the agent runtime, Asks, policy, trackers, records, the app, the `stack` command line. It holds no factory. |
| **Factory** | A body of work run on the platform (home, the work factory). Its code is a **pack**, used at an approved commit. |
| **Site** | One machine running the platform and the factories its deployment chooses |
| **Workflow** | The one unit of work: a trigger, steps, an outcome. A **standard workflow** is a platform template (Request, Change, Briefing, Monitor, Improve, Chat) that a factory adopts or overrides. |
| **Run** | One execution of a workflow, the same as n8n's execution. **Observable live, and kept as its record afterwards.** |
| **Step** | One n8n node of a run: an Agent step, an Ask, a Tool step, or logic |
| **Agent** | A building block: role, instructions, skills, model, tools, knowledge, budget. It runs only as a step; one agent, many workflows. |
| **Activity** | What an agent step does while it runs: each thought summary, tool call, memory read, hand-over, with input, output, time and tokens |
| **Trace** | The full technical record of an agent step's calls, in Phoenix |
| **Ask**, **gate** | A step waiting for a person; a gate is answered only by a named role holder's tap |
| **Result** | What a run produces (report, draft PR, files, answer) |
| **Work item** | The thing a run works on: a ticket, a mail, a request. Its ticket in the tracker is the durable record across runs. |
| **Policy**, **Scorer** | What may happen without asking; how runs are graded |

## 2. The rules

1. The platform holds no factory; packs bring them, at approved commits.
2. **Everything that happens is a run of a workflow, and every run is an n8n execution.** That includes chat turns, upkeep, and the stack's improvements to itself.
3. **Every agent step is an n8n node.** A plan made at run time (a request whose steps an agent decides) runs as n8n's loop over the planned steps. Each iteration is one AI Stack step, visible and animated like any other.
4. **Every run is observable while it runs** (§3), and its record is complete when it ends: inputs, activity, outputs, Asks, cost, trace.
5. Agents only run as steps; people act through Asks; agents and sessions on a site act through `stack` or MCP; factory changes are commits.
6. A template change is replayed on every factory that uses or overrides it; the doctor flags drifted overrides.
7. Fail loud: deploy and doctor stop on a half-published factory.

## 3. The star: the live run

The Run page is the heart of the app. Everything else leads to it: Home's "Running now", a workflow's runs, an Ask, a notice, an agent's recent steps.

**Layout, desk:**
```
┌──────────────────────────────────────────────┬─────────────────────────┐
│  n8n canvas, read mode, with the live layer:  │  Step panel             │
│  the running step pulses, done steps ✓ with   │  (the step you tapped,  │
│  their time, data flows along the edges,      │   or the running one)   │
│  Asks glow amber, failures red                │  · In   · Activity      │
│                                               │  · Out  · Trace         │
├──────────────────────────────────────────────┴─────────────────────────┤
│  Timeline: one bar per step (waterfall), Asks inline, cost/tokens/time   │
└─────────────────────────────────────────────────────────────────────────┘
```
**Layout, phone:** the timeline first (step list with status and live timer), then the step panel. The canvas is one tap away, full screen, with the same live layer.

**The step panel** has four tabs, live while the step runs:

| Tab | What it shows | Ready |
|---|---|---|
| **In** | Every input by name, with its source and size: instructions, earlier steps' outputs, the work item's text and files, memory recalled, skills loaded. Exactly what the agent saw, section by section, plus n8n's raw item data. | The moment the step starts |
| **Activity** | The agent's work in plain words, newest first ("Searching the web: RAM prices for a 32 GB kit" → "Reading 4 sources" → "Writing the summary, 1,200 words so far"). Each line opens to that call's exact input and output, time and tokens. The text being written streams live where the model streams. | Live, as each call starts and ends |
| **Out** | The result text, its named values, its files, its outcome (done, needs you, failed with the reason) | The moment the step ends |
| **Trace** | Phoenix's trace of this step, embedded: the call tree, prompts, completions, token counts | Each call within about a second of its end |

**Around it:**
- Counters for elapsed time, tokens, and the share of the subscription.
- Compare with the last good run, step by step.
- Replay from any step: rerun from step N with the same inputs.
- Answer an Ask in place.
- Stop the run.

**Home, the factory floor:** each live run is one line, "China briefing · step 2 of 4 · Scout: reading 4 sources · 1 min 12 s", with a small live canvas thumbnail on the desk. Failures and Asks come first.

**Agent page:** that agent's steps across all workflows, live and recent, each opening the Run page at that step.

## 3a. Workflows and runs, side by side

A workflow is the recipe; a run is one execution of it. **One workflow can have many runs at the same time.** The inbox has one per issue, Request one per request, and a monthly run can overlap the answering of the last one.

**In the model:**

- **A run is named by what it works on:** its work item or main input. For example "Inbox · Printer offline again", "Request · Which NAS has 4 bays", "China briefing · week 46". The number stays secondary.
- **A run keeps the workflow version it started with.** n8n resumes a waiting run on its starting version. A run started before its workflow changed says so.
- **Overlap per workflow,** declared in its settings and shown on its page:
  - **side by side** (the default);
  - **one at a time** (later runs queue, and their queue position shows);
  - **skip if one is running** (upkeep);
  - **replace** (a new run cancels the older one; for example, a fresh briefing replaces a stuck one).
- **Capacity is visible.** The platform runs as many agent steps at once as its slots allow (today 2). A step waiting for a slot says "waiting for a slot (2 of 2 busy)" in the timeline and on the canvas, never a silent pause. Stack shows the slots and who holds them.

**In the app.** Two objects, two views, never mixed. The pattern is the one mature orchestration tools share (GitHub Actions, Airflow, n8n's executions, Temporal, Dagster). A **workflow** is configuration: you visit it to understand or change the recipe. A **run** is operations: you live in the runs. A list shows many runs, concurrent ones included; a canvas only ever shows one run, or the recipe.

1. **The Runs list,** the main operational view. One row per run, updating in place.
   - **Columns:** status, run name, workflow, started by, progress (step n of m, current activity), started, live duration.
   - **Views:** Active (running and waiting; the default), Needs you, Failed, All.
   - **Filters:** workflow, status, started by, area, time; a search over what runs work on.
   - **Desk:** select several runs to stop or retry them together.
   - **Phone:** two lines per run.
   - **Live updates stay calm:** the sort stays stable, new runs appear at the top with a brief highlight, and nothing jumps.

   Concurrent runs of one workflow are simply several rows; filtering by workflow shows exactly them.
2. **The Workflow page:** the recipe and its health.
   - **Header:** name, trigger, overlap rule, version; Run now, Edit.
   - **Overview:**
     - n8n's canvas of the recipe;
     - health (success rate, typical duration, last failure);
     - a **run strip**, the last 20 runs as colored marks, each opening its run.
   - **Runs:** the Runs list filtered to this workflow. The header's "2 running" links there.
   - **Grid** (desk): runs as columns and steps as rows, each cell colored by that step's state in that run. It shows where each concurrent run is, and which step fails across runs.
   - **Settings, versions.**
3. **The Run page:** as in §3. The canvas with this run's path, the timeline, the step panel. A breadcrumb leads to the workflow; "other runs of this workflow" opens the filtered list. No arrows between runs: that is the list's job.
4. **The factory timeline** (desk): every run as a bar over time, one lane per workflow. It shows overlaps, queued runs and slot contention ("2 of 2 slots busy, 1 queued").
5. **Home:** a summary, never a second list.
   - Counts link to filtered views.
   - Needs you is answered in place.
   - The 3 most recent active runs.
6. **One status vocabulary everywhere:** Queued, Running, Waits for you, Waiting (on a reply or a ticket), Done, Failed, Cancelled, Skipped. Always an icon, a color and a word.
7. **Where Runs live:** the Workflows place has two tabs, **Runs** (default) and **Workflows**, the way n8n pairs Workflows with Executions. This keeps the bottom bar at six places. The alternative is a seventh place.
8. **Asks and agents:** each Ask names its run ("Inbox · Printer offline: needs you"). An agent's page lists its steps across runs ("busy in 2 runs now"), each opening the Run page at that step.

## 4. The canvas: integration options

| Option | What it is | Gets right | Gets wrong |
|---|---|---|---|
| **A. n8n alone** | n8n's canvas and execution view, nothing added | Exact for every node type; native per-node input and output after a run | No live animation for scheduled or webhook runs (n8n animates only runs started from the open editor); no agent activity; no Phoenix |
| **B. n8n plus our live layer** *(recommended)* | n8n's canvas in read mode, served through the app's own address. The app adds a thin layer to n8n's page: it follows the run's live events, marks each node (pulse, ✓ with time, amber Ask, red failure), animates data along the edges, shows a badge with time and tokens, and opens our step panel on a tap. | Every node type and shape (n8n draws them); live for every run, whatever started it; our panel for activity, I/O and trace; Edit switches to n8n's full editor | The layer follows n8n's page structure, so an n8n upgrade can break it. Mitigated: n8n is pinned, the upgrade test checks the layer, and if the layer can't attach, the canvas still works and the timeline and panel carry the live view. |
| **C. Our own renderer** | What phase A built | Full control | Not scalable (the owner's verdict); duplicates n8n. **Dropped** except as the fallback when n8n can't be reached. |
| **D. Runs started from the canvas** | Run now inside n8n's editor | n8n's own native animation | Only for runs you start yourself; no scheduled or webhook runs |

**Recommendation:** B, with D's native animation as a bonus when you run something from the editor. In read mode the canvas is n8n's read-only canvas. **Edit** switches to n8n's full editor in the same frame, and **Done** returns to read mode. The app signs in to n8n for your session (you store the n8n login once), so you never see n8n's login.

**On the canvas itself,** the AI Stack node shows:
- its agent in the subtitle, linking to the agent's page;
- its inputs and outputs in the subtitle ("Scout · in: topic, last week · out: findings");
- named exits: **done**, **needs you**, **failed**.

A workflow branches by connecting those exits.

## 5. Live data: where it comes from

| Live signal | Source | How it reaches the screen |
|---|---|---|
| Step started or ended, Asks, outcome | The step service and run register (recorded today) | Pushed as events |
| Node status and data on the canvas | n8n's execution, saving progress after each node (`EXECUTIONS_DATA_SAVE_ON_PROGRESS`) | The live layer marks nodes from the events; the data from n8n's execution |
| Agent activity | The runtime record: the Hermes plugin reports every tool call as it starts and ends; model output where the model streams | Pushed as events, turned into one plain line each |
| Trace | Phoenix: spans exported every second (set short), linked to the step by the run's id | Embedded per step; refreshes as spans arrive |
| Tokens and cost | The runtime record and the gateway | A running counter |

**One live stream per run** (server-sent events) feeds the canvas layer, the timeline and the step panel, within about a second. A finished run is drawn from the same record, so the live and the finished page are one page.

## 6. What goes into an agent

The AI Stack node's **Context** section takes its defaults from the agent's card. The step can change them.

| Field | What you set |
|---|---|
| **Instructions** | What this step must do. It may point at earlier steps. |
| **Inputs** | A named list. Each name gets a source: an earlier step's output or one of its values, the run's input, the work item's text or files, a file, or a memory question. Each becomes a labelled section of what the agent sees, and shows up in the In tab. |
| **Knowledge** | Skills, and the agent's **memory plug**. The plug says whether the agent is connected to the memory system at all, and if so which parts: sectors and collections, the repository knowledge of the repositories in its work (card, wiki, facts, code map), recall by question or pushed at start, read only or read and write through the write gate, and a budget. A step can narrow the card's plug, never widen it. |
| **Output** | Free text, or named values with types (checked). Values become fields the next steps use. |
| **Limits** | Time, tokens, model; the policy tier for what it may do |

You set it in n8n (with its expression picker) or in the app's step settings. Both write the same workflow in the factory's pack. The In tab shows the result exactly.

## 7. People in the run: Asks

An Ask is a step. It glows on the canvas, sits in the timeline, and is answered in place: chips, your own words (understood by the interpreter), Later, Dismiss. A gate is answered only by its role holder's tap. Every answer is part of the run's record and its work item's ticket. Policy (tiers, standing rules, undo) decides what needs an Ask at all: the human is on the loop, not in it.

## 8. The app

Six places, the same on phone and desk:

| Place | What it shows |
|---|---|
| **Home** | The factory floor: live runs, Needs you, failures, done today, factory health, the stop switch |
| **Workflows** | Per factory and area. A workflow's page: n8n's canvas (read mode, with the last run's marks), Run now, Edit, runs, result view, its agents strip, measures. |
| **Agents** | Each agent: card, used in, its live and recent steps, scores, its memory plug. The memory system (stores, sectors, the keepers' findings) lives here. |
| **Code** | Repositories, each with its **landing page**: overview, the repository card, wiki, facts, code map, environment, how it is checked, its onboarding runs, its changes and PRs with evidence and outcome, its measures. Also the review queue (PRs waiting for a person, with evidence) and proposals (Improve's PRs). |
| **Chat** | Each turn a run of Chat; its reply links to the run |
| **Stack** | Sites, factories and packs, the doctor, connections, health, policy, n8n's editor, Phoenix |

## 9. Build order

Each phase is reported as "X of Y moved" and checked on the phone.

| Phase | What | You see |
|---|---|---|
| **A** *(landed)* | Words, places, `stack`, doctor, sites | The new app; workflows with a first diagram |
| **A2** | n8n's canvas in read and edit mode, signed in for you; agents linked; Code back, Improve out | n8n's own canvas everywhere |
| **B. One engine + the live run** *(observability goes here, not after)* | Briefing, Request, Change and Chat as n8n workflows with one node per agent step, and plans as loops; the live stream; the Run page (timeline, step panel with In, Activity, Out and Trace, the canvas layer); Home's factory floor | Every run, live, step by step |
| **C. Measure** | One record per run (old tables imported); judge scorers; metrics; compare with the last good run; replay from a step | How well each workflow works, and why |
| **D. Improve** | The Improve workflow (replay-tested PRs), Monitor, the full Change loop | The factory improving itself, in front of you |
