---
title: "Workflows: n8n inside the app"
kicker: What runs when, and in what order
part: Under the hood
icon: flow
minutes: 4
summary: n8n decides when each piece of work starts and in what order; the stack's agents do the work. Its editor opens inside the app, every task shows where it runs, and every agent the workflows it is in.
views: [workflows]
---
**n8n** is the stack's workflow tool. A workflow says when work starts (a schedule, a call, an event) and in what
order its steps run. Its **AI Stack steps** hand the work to the stack: an agent, a crew job, a plan task, a question
for you or a message to you. The stack does the work the way it always does and hands the answer back.

## The Workflows page

On the desk, **Workflows** in the menu opens n8n's own editor inside the app, beside the app's menu. **Runs** shows
every run. The first time, n8n asks you to sign in with its own account; the app's Tailscale login comes first, so
nobody off your tailnet reaches it.

On a phone, the page lists the workflows instead: whether n8n runs each one or its old schedule still does, when it
runs, and its last runs with the steps the stack ran and how each ended. n8n's canvas is made for a big screen.

```try
label: See the workflows
open: "#/workflows"
note: On the desk n8n's editor opens here; on a phone each workflow's last run and its steps.
```

## Where it runs

A task or a crew job that belongs to a workflow shows **Where it runs** at its top: the workflow, the run, its state
and the step it is on. On the desk the run itself opens below it on n8n's canvas, with each node's input and output;
on a phone you get its steps as a list.

## In workflows

An agent's page and a crew job's page list every workflow they are a step of. Each opens that workflow inside the app.

## If the app is down

The Workflows page needs the app. n8n's own tailnet port, 8450, only takes the answers to its waiting steps, and a
workflow's webhook takes only a call from the stack itself on this PC: anything else is refused (SEC-27).

## The canvas

Each workflow is a canvas of blocks: a trigger on the left (a schedule, a message, a webhook), then the steps in order.

- **AI Stack step** is the stack's own block. It runs an agent with a brief, a crew job, a plan task, asks you
  something, or tells you something.
- **Runs** shows every run: when it started, how long each block took, and what came out.

```try
label: Find a crew job's workflow
open: "#/tasks?v=team&p=crew"
note: Open a crew job. Where it runs names its workflow; “its old schedule runs it” means n8n does not start it yet.
```

> [!note] n8n is made for a wide screen. On the phone you keep Home and Needs you; nothing there needs n8n.

## Questions from a workflow

When a workflow needs you, its question appears in **Needs you** with its answers as buttons. Your tap is the answer,
and the workflow goes on from there. A workflow can also just tell you something, through Telegram or the app, and
quiet hours are respected.

```try
label: Look at what waits for you
open: "#/decide"
note: Questions from workflows sit here with everything else that needs your yes or no.
```

## Packs

A pack is a domain kept outside the stack's repository: its agents with their prompts, skills, commands, workflows and
exams. **Packs and trackers** on the Stack page lists each pack and what it brings. A new commit runs only after you
approve it there or in **Needs you**, where you see its agents' prompts, its commands and what changed; until then the
commit before keeps running. Each of its commands is approved again at the place it runs, by the hash of its file. A
pack's workflow may never run a shell command of its own.

## Trackers

The stack can read an issue tracker and write back to it. Everything it would write starts **in shadow**: you see it in
Needs you and under **Packs and trackers** on the Stack page, and nothing leaves the stack. Each write has three
answers:

- **Right, send it**: it goes to its item now, once, and counts as right. A question to someone on the tracker reaches
  them this way while its kind is still in shadow.
- **Right, don't send**: it counts as right, and nothing leaves.
- **Wrong**: it does not count.

Once you judged enough writes of one kind right, you may let that kind go live, and send it back to shadow at any
time. A tracker that is new to the stack starts nothing for the items it already holds: they count from their next
change (or from the date its `start` names).

**Write an issue in your inbox repository.** At home the stack watches your private repository **inbox** on your
Forgejo. Write an issue there as you would write a note to your assistant: within a few minutes the assistant reads
it, answers it in a comment on the issue (or does what it asks and says what it did), and waits up to a week for your
reply. Reply in a comment and it answers once more, then sums up and closes the issue. A new comment on a closed issue
starts it again. While its comments are still in shadow, you find its answers in Needs you instead of on the issue;
**Right, send it** puts one on the issue at once.

