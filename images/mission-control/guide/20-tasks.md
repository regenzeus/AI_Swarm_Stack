---
title: "Tasks: what needs doing, and who does it"
kicker: Everything you ask for, and the agents that do it
part: Everyday use
icon: tasks
minutes: 5
summary: Every piece of work is a task, once or repeating. The Tasks tab shows your tasks, what happens now, the team, which agents work on which task, and the stack's ideas.
views: [tasks, task, missions, new]
---
Every piece of work in the stack is a **task**: a briefing, a long research job, a price watch, a cleanup, a build, a
question to Claude, a chat. A task is *what* needs to be done; an **agent** is *who* does it. One task can have many
agents (one per step of its plan), and one agent works on many tasks.

How long a task runs doesn't make it a different thing. Its **When** says it: **once**, **repeats** (daily at 06:30,
weekly on Mondays, every 6 hours), **on an event** (news on a subject, a price move, an SEC filing) or **after another
task**. A daily briefing is a task that repeats.

A task is **yours** or **the stack's**. The stack's are the work it gives itself: the crew's duties (the Memory
Keeper's nightly pass, the Health doctor, the backups), the trials and probes, the doctor's questions to Claude. Your
list shows yours; the stack's are one tap away, never hidden.

## The Tasks tab

The second tab, **Tasks**, has five views under its title, each answering one question:

| View | The question | What it shows |
|---|---|---|
| **Tasks** | What is the stack doing? | every task in one list: **Needs you**, **Failed**, **Running now**, **Recent results**, **Scheduled**; each with its area (a filter if you want one); the stack's **Upkeep** as one row; a search |
| **Activity** | What's happening now? | who works right now, then the room and the run timeline |
| **Team** | Who does the work, and how well? | **On your tasks** (every agent, its role and scorecard), **Crew** (the stack's duties with their health), **Measured** (results per agent and kind, Telemetry, Trials) |
| **Network** | Which agents work on which tasks? | tasks on the left, agents on the right, a line for every pair that worked together |
| **Ideas** | What could be better? | the stack's ideas about itself, ranked; one you build becomes a task |

Each task's row shows where it stands (needs you, a step at work, next run, done), its When, its last result, and
small circles for the agents on it this week; a blue ring is one at work now. Tap a row for the task's page. A
mission's page and a crew duty's page are their tasks' pages: **Agents** there shows who worked on it.

```try
label: See your tasks
open: "#/tasks"
note: Active first: what needs you, then what runs, then what comes next.
```

## Who does a task

Agents are given per **step**, not per task. When a task is planned, the intake names an agent for each step and
says why; when a step starts, the Conductor gives it to the agent that does that kind of work best (measured, below)
and is not at its usage limit. When no agent fits a step, a temporary one is written for it. You can steer: tick
agents under **New task → More**, and only they do the steps; or choose **Show me the plan first**.

A task without an agent at work always says why: it is being planned, waits for you, waits for its next run, or a step
found no agent and the task stopped with that reason.

## Network: who works on what

**Network** draws the last 7 days (or today, 30 or 90 days): your tasks on the left, the agents that worked on them
on the right, a line for every pair, thicker for more runs, blue while it runs. Tap a task: its agents light up and the
order they worked in shows below. Tap an agent: every task it worked on. **The stack's** and **All** add the stack's
own tasks. **Agents together** is the team map: who works with whom.

What ran without any task (a chat with Hermes, the mail copy's own sync) is counted under **Not on any task**.

```try
label: See which agents work on which task
open: "#/tasks?v=network"
note: Tap a task on the left; its agents light up.
```

## Give a task

On **Home**, type into the box at the top and tap **Send**: your assistant answers a question and starts a job as a task (its `task_start` tool). Or open **Tasks** and tap
**New task**. One sentence is enough:

```try
label: Give the stack a research task
open: "#/tasks"
note: Type "Find out what a 32 GB DDR4 kit for my laptop costs" and tap Send.
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

## How a task runs: the Conductor

Every task the intake plans is run by the **Conductor**, step by step: one step or many, once, on a schedule or each
time something happens. A **briefing** runs as four steps:
the Topic Desk collects the news, feeds, filings, job openings and prices of its window; a scout researches each of the
topic's key questions, all at the same time; the desk writes the report from both with every claim cited; and it is
delivered the ways you asked (the app, Telegram, e-mail). A step starts when the steps it needs have finished;
steps that need nothing from each other run at the same time (two at most). A step can be done once per item, such as
one research step per topic, all at the same time. Each step is done by its agent the agent's own way: Hermes' agents
in Hermes, Claude through Claude Code, the writing agents with one model call, and a change to code as a **build**,
which still waits for your tap before it deploys.

A task on a schedule runs **at once** and then on its schedule. Each run copies the plan and has its own steps, trace
and result; the card shows when it last ran and when it runs next, and **Run again now** starts another run.

A task that waits for an event (news on a search, a price move, an SEC filing) starts nothing until it happens; the card
says **waits for its trigger**. Each time the trigger fires, a new run starts, and every step of it is told what happened
and where to read it. An event that comes while a run is still going waits for it (up to five wait; older ones are
dropped and logged). A briefing that waits for an event writes the Topic Desk's short **alert** on it and delivers it.

A **price watch** (a shopping task) gets its own shopping agent once, with your limits, its proposals and its price
history. Each run of the task is one check by that agent: the offers, then a proposal or "wait until ≤ €X". When a waiting
proposal reaches its price or date, the task runs again by itself. **Its shopping agent** on the task opens the agent,
where you approve a purchase: buying, after your tap, and following the order stay the agent's own work (Shopping).

A briefing or price watch you gave before 1 November ran as its own mission. The stack moves each one under the
Conductor by itself: from then on the task runs it as planned steps, on the same schedule (the next run when it is
due), and judges each run. The mission stays, holding the topic, its wiki and the articles it has already seen (or the
proposals and your limits), but no longer runs by itself. A briefing's alerts on a filing or a price move move with it:
the task watches them and sends the desk's short alert, between its scheduled briefings.

**Runs** on the card lists each run of a recurring task: how it started (at once, on its schedule, you, or the event),
when, its verdict and its answer.

## A task's own page

Every task has its own page: tap a task anywhere (a notification, Home, the Tasks list, an agent's **Tasks** tab)
and it opens, with **Tasks** lit below. On top: its name, where it stands and
why (a step that could not do its work says what was missing). A recurring task shows one run at a time, its newest:
pick another under **Showing**.

The **Overview** starts with the result and then tells how it came about, most important first:

- **The answer**, folded after a screen; **Show the whole answer** opens all of it.
- The numbers: how many agents worked on it, steps done, the time, the tokens, the sources read and cited, what its
  agents read from and kept in memory, and the verdict; then your own words, as you gave the task.
- **Who worked on it**: a map of the agents. A bubble is an agent, its colour its part (blue: planned it or ran the
  plan; green: did a step; orange: called in by another agent), its size the tokens of its own model calls (an agent
  that hands its work to Claude Code is small: the Claude run it called in carries the tokens). A line with an arrow is
  a hand-off (teal: one step's results went on to the next) or a call (grey: one agent called another in); a dashed
  line is a start (the Conductor gave it a step, the planner made the plan). Tap a bubble for that agent's part, runs, tokens, cost,
  models, tools and memory use; tap a line for what passed along it. **Who did what, in words** says the same as a list.
- **Done when**: the judge's verdict and its reason for each point.
- **What went wrong**: failed steps, retries, runs that failed or went silent, errors in the agents' runs, points of
  done when not met, each with a link to where it happened; or a line saying nothing did.
- **What it read** (the sources, by site, how many the answer cites), **Memory** (each store, read and kept) and
  **What it made** (the answer, reports, wiki pages, files, step findings, where it was delivered).
- **Cost and time**: the tokens of each agent with its models, and the time from start to end.
- Then the Orchestrator's checkpoints and the plan with each step's agent, times and result.

Each part opens its own tab for the whole of it:

- **Agents**: the map larger, and every agent with its part, runs, calls, tokens, cost, models, every tool it used and
  how often, and its memory use.
- **Timeline**: when each agent worked (indented: one another agent called in), then every action they took, newest
  last; tap an agent's name to see only its actions.
- **Sources**: every web page, news item, job ad, note and memory its agents read and every search they made, with the
  step and agent that read it; filter to what the answer cites, what was read but not cited, or the searches. By site
  below.
- **Memory**: by store (wikis, your notes, journals, long-term memory, the swarm's board, lessons): what was read and
  what was kept, each page or fact once with how often and by whom, linked where it is a page. It includes what the
  stack did around the agents: the wiki a refinement's research was given, the topic wiki pages a briefing grew, and the
  answer kept in your vault. **Every memory call** lists them as the agents made them.
- **Runs**: every run of a recurring task with its verdict, steps and answer; **Show this run** opens it on the page.

A task handed to Claude Code, a build, a chat or a mission shows its agents too: its own run and every run it called in.

An agent's page has the other side: its **Tasks** tab lists the tasks it worked on and its part in each.

Between two waves of steps of a one-off task the **Orchestrator** looks at what the finished steps found and keeps or
changes the rest of the plan: it may drop a step that is now pointless, rewrite one, or add up to three (an added step
can come before steps that have not started; they then wait for it). It reads the start of each long result, marked
as cut, while the next steps get the whole of it. It never touches a step that has started (one in a fix round
included), looks at most three times a run, and every look shows on the task's page under **The
Orchestrator's checkpoints** with its reason; a change also shows in the activity. A dropped step reads "dropped by the
Orchestrator".

A step whose agent cannot do its work (a tool it needs is not among its own, such as the AI phone) answers "blocked";
the task then fails with that reason instead of being reported done, and the message tells you what was missing. The
plan sees what each agent can reach, so a phone step goes to the agent that holds the phone.

Each step runs on its agent's own harness and model: **Hermes** (one turn of the agent's Hermes profile, with its
tools), **Claude Code** (a question about code, answered read-only in a throwaway copy of the repository, or a build in
the builder's sandbox), **Python** (one model call on the agent's own key, no tools) or **OpenCode** (one `opencode run`
in a throwaway container on the internal network, the repository read-only, no shell, edits or web).

The task's page lists its **steps**, each with its agent, its state and its result. A step that waits says why: the
steps before it, Claude still working, the subscription's usage limit, or too little memory available on the PC (a
step asks for what it starts: a quarter of a GB for a writing step, half a GB for a Hermes step, three quarters for
Claude Code). **The run's log** opens the whole task as one run, with every step and every agent
inside it; **how it ran** beside a step opens that step's own log. When the task is done, **Read the answer** opens it; it is also kept in the vault under `tasks/`.

If the PC restarts in the middle, the task goes on where it stopped: finished steps are never done again, and a step
that was running starts once more.

## From what it read to the answer

A task's **Sources** shows how a run went from what it read to what came out (**What it read** beside each of its
runs opens that run's):

- Four columns, *what was read* (pages, searches, job ads, vault notes, memories, the news the Topic Desk
  chose), *who worked* (each step and its agent), *what they found* and *what came out* (the report, the answer, the
  wiki pages, the deliveries). Tap a box to see where it came from and what it fed, and to open it. A source drawn
  dashed was read but never cited in the answer, so you see which reading paid off. A site with many pages is one box
  with its count; tap it for the list.
- Below it, every source with a filter: cited, read but not cited, searches; and how many came from each site.
- **Timeline** on the task page has one lane per agent at work (indented: an agent another one called in), so you see
  what ran at the same time; the numbers under the answer say how many agents, how many at once, the time and tokens.

While a run goes on, the page redraws itself every few seconds. On a phone the flow moves sideways instead of shrinking.

## Improve a wiki or a page

Every wiki has **Improve this wiki** under its name, and every wiki page **Correct or research**. Say what is wrong
("the 2026 capacity figure is wrong") or what to find out ("add the Kazakh producers"), or tap one of the suggestions.
It becomes a task like any other: research agents look into it with sources (they see the page or the wiki as it is
now), and its last step has the wiki's writer fold the findings in, the page you asked about first. A fact that turns out
wrong is not deleted: it moves to the page's **Superseded** section with its date, next to the source of the correction.

## New task

**New task** on the Tasks tab is one form for every task. Only what you set is decided; the rest the stack reads from
your words:

- **Kind** (optional): Briefing, Research, Shopping (a price watch with its shopping agent), Cleanup (where the space
  goes on the AI phone or the PC; it never deletes), or **The stack decides**.
- **When**: Repeats (a schedule), On event (news on a subject, a price move, an SEC filing), After a task, or Once.
  Pick none and the stack reads it from your words ("every morning" repeats).
- **Results to**: Telegram, the app, e-mail.
- **More**: the effort, a deadline, the model for one-call steps, your agents and your own points for "done when".

Leave a field as it is and the stack decides it; anything you set is kept exactly.

**Before it starts** decides whether the task starts as soon as it is planned, or shows you the plan first and waits
for **Start it**.

**Agents** lets you pick who does the work: tick none, and the stack picks; tick some, and only they do the steps (a
step the intake gave to another agent goes to one of yours). **Model for one-call steps** sets the model of the steps
that make a single model call (a Hermes agent or Claude keeps its own). The plan marks your choices **your choice**, and
the routing by measured results never moves a step away from them.

## The list

**Tasks** lists every task of the stack in one list, in the order of what matters now: **Needs you**, **Failed**,
**Running now**, **Recent results** and **Scheduled**, the newest first in each (every open task and every task of the
last seven days; each keeps its page). Each says its **area** (Taxes, Mail, Briefings, Shopping, Research, Errands,
Inbox, Phone, Code, Memory, Upkeep) and who asked for it; tap an area to see only it. The stack's own small jobs (the
code graph, the swarm sync, the nightly restart...) are one **Upkeep** row with their health, "15 jobs, all fine", and
a tap opens them; one that fails also shows on its own under **Failed**. A workflow is one task: its runs are its
history, Run now is on it. Work started the other ways (a build, a Claude question, a chat) is a task too; a chat
stays on **Chat**. Open a task to see its definition of done, its plan
with the agents, its mission, build or Claude task, and **How it was planned**: the intake's own run.

**Cancel** stops a task that has not started yet; work it has already started stays on its own page, where you can
stop it.

## Rules: a new task each time something happens

**Rules**, at the end of the list, holds your rules. A rule says *when* (a source and what to look at), *only with these
words* (optional), *then the stack should* (a sentence, like any task), and *at most once every* so many minutes. The
sources:

| When | What it looks at |
|---|---|
| news on a search, a breaking story on a subject | Google News for your search words |
| a new item in a feed, activity on a GitHub repository | the feed's address, owner/name |
| a price move, a new SEC filing | SYMBOL:percent (ACME:8), a US ticker |
| activity on Forgejo | your repositories on the NAS: commits, issues, pull requests |
| new mail | your inbox, only while Gmail *read* is granted (Stack → Connections) |
| a change in the House | lights, plugs, shutters, locks, sensors |
| a new file | a file you drop into `C:\AI\exports` |
| a time | daily HH:MM, weekdays HH:MM, weekly mon,thu HH:MM, every Nh |
| a calendar event | 60 before, start, end or 15 after (your calendar's iCal address, under Sources) |
| a finished task, a mission's own trigger | any, or a task number or words |

Write `{title}`, `{detail}`, `{url}` or `{source}` into the task and they are filled from the event:
"Read {title} and tell me in three lines what it means for my copper positions".

**Check first** lets a model decide whether the event really is what you mean ("a new supply contract, not a rumour")
before anything starts. Each rule lists its last firings: started a task, waited out its cooldown, or turned down by its
check.

The first time a rule looks at something, it only notes what is already there, so a new rule never fires on old news.

```try
label: Get told when your repository moves
open: "#/tasks"
note: Under Rules, at the end of the list, add a rule: When "activity on a GitHub repository", regenzeus/AI_Swarm_Stack, then "Summarise {title} for me".
```

## Breaking news

A rule on **a breaking story** watches a subject. When three different publishers report the same new story within 30
minutes, it fires once; later reports join that story instead of firing again. Each breaking story shows under
Rules with its reports; tap **Right** or **Not news**: your ratings tell whether the rule finds what you would call
breaking.

**A calendar**: under **Sources**, add your calendar's secret iCal address once (Google: Settings → your calendar →
Secret address in iCal format). It stays on the PC and only its host is shown. A rule on it fires once per event, the time
you set before its start (or at its start, its end, or after it): "60 before, only with Anna: brief me on {title}".
Repeating events, moved and cancelled ones are read as your calendar shows them.

**Sources** under Rules shows each source: when it last looked and what it found, or why it is off (no rule asks for
it, Gmail not granted, the NAS asleep).

## Judged, measured, and new agents

When a task you gave finishes, it is **judged**: a model reads its result against each point of its definition of done
and marks each ✓ or ✗, with a line on why (a build counts by whether it was deployed). A recurring task is judged after
**each run**, on that run's own answer; a run that found nothing new (a quiet briefing, no price drop) is kept but not
judged. The task's card shows the verdict of its latest run (met, partly, not met) and how many tokens it used, and
**Runs** shows every run's.

**Team → Measured** on Tasks lists, per agent and kind of task, how many tasks it worked on in the last 30 days, how
many met their definition of done, how long they took and what they used. From three judged tasks of a kind on, the
Conductor gives a step to the agent that does that kind clearly best, and away from a subscription at its usage limit;
the step says why ("routed: ...").

When no agent fits a step, the stack writes a **temporary agent** for it: a short brief for one model call, with no tools
and its own small key, which ends with the task. Each design is kept with its scores under Temporary agents; one that
met three tasks becomes an idea for a permanent agent under **Tasks → Ideas**, which you can have built like any change.

## Software from a specification

Give a task like "build a Python library that renders Mustache templates, from the specification in the repository"
and the intake staffs the software roles: the **analyst** turns the specification into numbered requirements; the
**tester** writes acceptance tests from them while the **builder** writes the code, neither seeing the other's work;
the **judge** runs every test and sends failures back to the builder with what failed, a few rounds at most; the
**breaker** tries to make it fail and leaves each fault as a test; the judge runs everything again; the **tracer** says
which requirement is met where, and which is not; the **presenter** writes your report. The tester and the breaker may
only change their own test folders, and a task can carry a budget of hours and tokens, after which no further step
starts. Each role has its page under Tasks → Team.

