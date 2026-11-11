---
title: The stack command line
kicker: How agents work through the system
part: Under the hood
icon: flow
minutes: 4
summary: An agent, or a Claude Code session on a site, starts and inspects runs, answers what it may and asks you for approvals with one command, stack, and the same as tools for your assistant. A gate stays your tap in the app.
views: []
---
On a site, all work is a workflow run, and people act through Asks. Nobody edits the stack's files on a site by hand:
an agent, or a Claude Code session working there, goes through **stack**, a command on the site's own machine. It
talks to the app the way your browser does, so the same rules, roles and record apply, and every answer it gives is
recorded as coming from the command line.

## The commands

| Command | What it does |
|---|---|
| `stack workflows` | every workflow: when it starts, on or off, its agents, its last run |
| `stack agents` | every agent, and every workflow that has a step with it |
| `stack runs --workflow <name> --status failed` | the newest runs, newest first; both filters are optional |
| `stack run <workflow> --input topic=copper` | starts a run now, as **Run now** does, and names the run once its first step reports |
| `stack run show <id>` | one run: its steps, the questions it waits on, and where it is in n8n |
| `stack asks` | what waits in **Needs you**; a private question shows no figures |
| `stack answer <ask> <choice or "words">` | answers a question that is no gate; your words are read as in the app |
| `stack pack approve <pack> <commit>` | asks you to approve a pack's new version: a gate in Needs you |
| `stack doctor` | names what keeps the site from running as its deployment says |

Every command takes `--json` for agents. A command that is refused says why and ends with exit code 1.

## What it never does

- **A gate is your tap.** `stack answer` on a gate is refused with the reason, and so are a dismissal or a later.
  Only a person in the gate's role answers it, by a tap in the app.
- **It approves nothing.** `stack pack approve` only puts the question in Needs you. Nothing of the pack runs until you
  tap **Approve** there.
- **No standing rules, deploys, purchases or builds.** The app takes only its three actions from it: start a run,
  answer a question that is no gate, ask for a pack's approval. The stop switch holds its runs like any other.

```try
label: See what an agent asked you
open: "#/decide"
note: A pack approval asked from the command line waits here, with Approve, Not now and Look.
```

## The same for your assistant

Your assistant in chat has the same as tools: **stack_workflows**, **stack_agents**, **stack_runs**, **stack_run_show**,
**stack_run**, **stack_asks**, **stack_answer** (only with what you told it, never a gate or a private question),
**stack_pack_approve** and **stack_doctor**. They go through the same rules, recorded as an agent's tool.

```try
label: Ask what ran and what failed
chat: Which workflows ran today, and did any run fail? Use the stack tools.
note: The assistant reads the runs with stack_runs and opens a failed one with stack_run_show.
```

## On a new site

The deploy installs the command at `~/.local/bin/stack`. It talks to the app on `http://127.0.0.1:8090`; `STACK_URL`
names another address, and `STACK_OPERATOR` the login it acts as (else the deployment's, else `operator@this-pc`). The
site's roles decide which questions that login may answer.
