---
title: "Tasks: say it, the stack does the rest"
kicker: Give a task in a sentence
part: Everyday use
icon: target
minutes: 3
summary: Type what you want done. The stack writes what done means, plans it, picks the agents and starts it; you answer only real questions.
views: [tasks]
---
Every piece of work in the stack is a **task**: a briefing, a long research job, a build, a question to Claude, a
chat. Most of the time you just say what you want, and the stack works out the rest.

## Give a task

On **Home**, type into the bar at the top and tap **Do it** (**Ask** still starts a chat). Or open **Tasks** and use
the box there. One sentence is enough:

```try
label: Give the stack a research task
open: "#/tasks"
note: Type "Find out what a 32 GB DDR4 kit for my laptop costs" and tap Do it.
```

The **intake** agent then writes the task's specification, which you see on the task's card:

- **Done when**: one to five points anyone could check against the result ("names the three cheapest offers with
  price, shop and delivery date"), not "good research".
- **Plan**: the steps, the agent that does each, and why that agent.
- **When**: once, on a schedule, when something happens (news on a subject, a price move, an SEC filing), or after
  another task.

It asks you at most **two questions**, and only when the task can't be planned without the answers. Questions show
under **Needs you** on Home and on the task; answer them there, and it plans again.

Then the task goes to the part of the stack that does that kind of work: research, analysis, watching and briefings
become a **mission**, a change to code becomes a **build**, a question about code goes to **Claude**. Each keeps its
own approvals: a build still waits for your tap before it deploys, a purchase for your OK, the AI phone for yours.

## Tasks that need several agents

A one-off research, analysis or errand task whose plan needs two or more agents is run by the **Conductor**, step by
step. A step starts when the steps it needs have finished; steps that need nothing from each other run at the same time
(two at most). Each step is done by its agent the agent's own way: Hermes' agents in Hermes, Claude through Claude
Code, the writing agents with one model call.

The task's card lists its **steps**, each with its agent, its state and its result. A step that waits says why: the
steps before it, Claude still working, the subscription's usage limit, or too little memory available on the PC (a
step asks for what it starts: a quarter of a GB for a writing step, half a GB for a Hermes step, three quarters for
Claude Code). **Live trace** opens the whole task as one run, with every step and every agent inside
it. When the task is done, **Read the answer** opens it; it is also kept in the vault under `tasks/`.

If the PC restarts in the middle, the task goes on where it stopped: finished steps are never done again, and a step
that was running starts once more.

## With the details set

**Task with details** on Home (or **Details** under the box on **Tasks**) shows the task's fields: kind, when, a
schedule, after which task, a deadline, the effort, and your own points for "done when". Leave a field as it is and
the stack decides it; anything you set is kept exactly.

**Before it starts** decides whether the task starts as soon as it is planned, or shows you the plan first and waits
for **Start it**.

## The board

**Tasks** lists every task of the last seven days and every open one, under **Waiting on you**, **Running**,
**Scheduled** and **Done**. Open a task to see its definition of done, its plan with the agents, a link to its mission,
build or Claude task, and **How it was planned**: the intake's own run, with what it read and answered. Work you started
the old ways (a new agent, a build, a Claude question, a chat) appears here too.

**Cancel** stops a task that has not started yet; work it has already started stays on its own page, where you can
stop it.

## Triggers: tasks that start by themselves

Under the board, **Triggers** holds your rules. A rule says *when* (a source and what to look at), *only with these
words* (optional), *then the stack should* (a sentence, like any task), and *at most once every* so many minutes. The
sources:

| When | What it looks at |
|---|---|
| news on a search, a breaking story on a subject | Google News for your search words |
| a new item in a feed, activity on a GitHub repository | the feed's address, owner/name |
| a price move, a new SEC filing | SYMBOL:percent (CCJ:8), a US ticker |
| activity on Forgejo | your repositories on the NAS: commits, issues, pull requests |
| new mail | your inbox, only while Gmail *read* is granted (Stack → Connections) |
| a change in the House | lights, plugs, shutters, locks, sensors |
| a new file | a file you drop into `C:\AI\exports` |
| a time | daily HH:MM, weekdays HH:MM, weekly mon,thu HH:MM, every Nh |
| a finished task, a mission's own trigger | any, or a task number or words |

Write `{title}`, `{detail}`, `{url}` or `{source}` into the task and they are filled from the event:
"Read {title} and tell me in three lines what it means for my uranium positions".

**Check first** lets a model decide whether the event really is what you mean ("a new supply contract, not a rumour")
before anything starts. Each rule lists its last firings: started a task, waited out its cooldown, or turned down by its
check.

The first time a rule looks at something, it only notes what is already there, so a new rule never fires on old news.

```try
label: Get told when your repository moves
open: "#/tasks"
note: Under Triggers, add a rule: When "activity on a GitHub repository", regenzeus/AI_Swarm_Stack, then "Summarise {title} for me".
```

## Breaking news

A rule on **a breaking story** watches a subject. When three different publishers report the same new story within 30
minutes, it fires once; later reports join that story instead of firing again. Each breaking story shows under
Triggers with its reports; tap **Right** or **Not news**: your ratings tell whether the rule finds what you would call
breaking.

**Sources** under Triggers shows each source: when it last looked and what it found, or why it is off (no rule asks for
it, Gmail not granted, the NAS asleep).

## Judged, measured, and new agents

When a task you gave finishes, it is **judged**: a model reads its result against each point of its definition of done
and marks each ✓ or ✗, with a line on why (a build counts by whether it was deployed). The task's card shows the verdict
(met, partly, not met) and how many tokens of your subscriptions it used.

**Agents, measured** on Tasks lists, per agent and kind of task, how many tasks it worked on in the last 30 days, how
many met their definition of done, how long they took and what they used. From three judged tasks of a kind on, the
Conductor gives a step to the agent that does that kind clearly best, and away from a subscription at its usage limit;
the step says why ("routed: ...").

When no agent fits a step, the stack writes a **temporary agent** for it: a short brief for one model call, with no tools
and its own small key, which ends with the task. Each design is kept with its scores under Temporary agents; one that
met three tasks becomes an idea for a permanent agent under **Agents → Ideas**, which you can have built like any change.
