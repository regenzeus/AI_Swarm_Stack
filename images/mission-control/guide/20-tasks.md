---
title: "Workflows and runs: everything the stack does"
kicker: One model for all the work
part: Everyday use
icon: flow
minutes: 4
summary: Everything the stack does is a workflow, and every time it does it is a run. The Workflows page lists them by factory and area; a workflow's page shows its diagram, its runs and its result; a run's page the path it took.
views: [workflows, workflow, run, task, missions, new]
---
Everything the stack does is a **workflow**: a **trigger** (a schedule, Run now, an event, your request), **steps**
and a **result**. Every time a workflow does its work is a **run**. An **agent** is a building block that does a step;
an **Ask** is a step that waits for you.

## The six places

The menu is the same on the phone and the desk: **Home** (what needs you, what runs, what failed, what is done today,
and the agents' activity), **Workflows** (with the measures of your records), **Agents** (with what agents know),
**Code** (repositories, builds and the agents' ideas), **Chat** and **Stack** (health, costs, tools, connections and
n8n's editor).

## The Workflows page

One list, grouped by **factory** (today: home, and the platform's own upkeep) and **area** (taxes, mail, briefings and
the rest). Each card says, one line each: its name, its area, its trigger, its last run and the next one, the Asks it
has open, and its result's first sentence. Tap an area to see only its workflows, or find one by its name.

```try
label: See every workflow
open: "#/workflows"
note: The standard workflows come first, then each area's.
```

## The standard workflows

The platform ships templates every factory uses: **Request** (understand, work out the steps, do, check, deliver),
**Change** (triage, specification, implement, review, verify, ship, watch) and **Briefing** (collect, research, write,
deliver). Hermes starts a Request with its tool `task_start`. What you ask in a sentence, a question to Claude, a chat request, a build and a briefing show today as runs of
the one they will become. **New request** on the Workflows page starts one.

```try
label: Give the stack a request
open: "#/workflows?new=1"
note: One sentence is enough; its run shows how it goes.
```

## A workflow's page

Its **diagram** is always there: n8n's nodes and connections drawn by the app, the trigger first, each AI Stack step
with what kind of step it is and the agent that does it. Tap a node for what it is; an agent step runs on its agent's harness (Hermes, Claude Code, OpenCode, or Python for a step without a model). Below: **Run now**, its **result**,
its **runs**, its **agents** and its **settings** (its schedule and its on/off switch are n8n's; on the desk **Edit in
n8n** opens its canvas).

## A run's page

The diagram again, with the path this run took lit up: what is done, what runs, what waits for you, what failed, and
what it never reached faded. Below it, each step with its state and times, the run's Asks to answer in place, what it
cost and its result, and its whole record (the steps' logs, what it read, its timeline) one tap away.
