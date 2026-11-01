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
proposal reaches its price or date, the task runs again by itself. **Its shopping agent** on the card opens the agent,
where you approve a purchase: buying, after your tap, and following the order stay the agent's own work (Shopping).

A briefing or price watch you gave before 1 November may still run as its own mission. Its card then has **Run it
under the Conductor**: from then on the task runs it as planned steps, on the same schedule (the next run when it is
due), and judges each run. The mission stays, holding the topic, its wiki and the articles it has already seen (or the
proposals and your limits), but no longer runs by itself.

**Runs** on the card lists each run of a recurring task: how it started (at once, on its schedule, you, or the event),
when, its verdict and its answer.

## A task's own page

Every task has its own page, like an agent: tap a task anywhere (a notification, Home, the board, an agent's
**Tasks** tab) and it opens. On top: where it stands and why (a step that could not do its work says what was
missing), and the numbers: how many agents worked on it, steps done, the time, the tokens, what its agents read from
and kept in memory, and the verdict. Below, five tabs:

- **Overview**: the answer itself, the definition of done with the judge's verdict and reason for each point, and the
  plan with each step's agent, times and result.
- **Timeline**: when each agent worked (indented: one another agent called in), then every action they took, newest
  last; tap an agent's name to see only its actions.
- **Agents**: each agent that worked on it, with its part (planned it, a step, called in by another agent), its runs,
  tool and model calls, tokens and time, and a link to its page.
- **Memory**: what its agents read from memory (your notes, the wikis, journals, long-term memory, the swarm's ledger)
  and what they kept there.
- **Runs**: every run of a recurring task with its verdict, steps and answer.

An agent's page has the other side: its **Tasks** tab lists the tasks it worked on and its part in each.

Between two waves of steps of a one-off task the **Orchestrator** looks at what the finished steps found and keeps or
changes the rest of the plan: it may drop a step that is now pointless, rewrite one, or add up to three. It never
touches a finished step, looks at most three times a run, and every look shows on the task's page under **The
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
Claude Code). **Live trace** opens the whole task as one run, with every step and every agent inside
it. When the task is done, **Read the answer** opens it; it is also kept in the vault under `tasks/`.

If the PC restarts in the middle, the task goes on where it stopped: finished steps are never done again, and a step
that was running starts once more.

## The swarm map

**Swarm map** on a task (and **map** beside each of its runs) shows how the run went:

- **Flow**: four columns, *what was read* (pages, searches, job ads, vault notes, memories, the news the Topic Desk
  chose), *who worked* (each step and its agent), *what they found* and *what came out* (the report, the answer, the
  wiki pages, the deliveries). Tap a box to see where it came from and what it fed, and to open it. A source drawn
  dashed was read but never cited in the answer, so you see which reading paid off. A site with many pages is one box
  with its count; tap it for the list.
- **Timeline**: one lane per agent at work (indented: an agent another one called in), ● for what it read and ■ for
  what it made, so you see what ran at the same time.
- On top: sources read → cited, how many agents and how many at once, the time from start to end, the tokens.

While a run goes on, the map redraws itself every few seconds. On a phone it moves sideways instead of shrinking.

## Improve a wiki or a page

Every wiki has **Improve this wiki** under its name, and every wiki page **Correct or research**. Say what is wrong
("the 2026 capacity figure is wrong") or what to find out ("add the Kazakh producers"), or tap one of the suggestions.
It becomes a task like any other: research agents look into it with sources (they see the page or the wiki as it is
now), and its last step has the wiki's writer fold the findings in, the page you asked about first. A fact that turns out
wrong is not deleted: it moves to the page's **Superseded** section with its date, next to the source of the correction.

## With the details set

**Task with details** on Home (or **Details** under the box on **Tasks**) shows the task's fields: kind, when, a
schedule, after which task, a deadline, the effort, and your own points for "done when". Leave a field as it is and
the stack decides it; anything you set is kept exactly.

**Before it starts** decides whether the task starts as soon as it is planned, or shows you the plan first and waits
for **Start it**.

**Agents** lets you pick who does the work: tick none, and the stack picks; tick some, and only they do the steps (a
step the intake gave to another agent goes to one of yours). **Model for one-call steps** sets the model of the steps
that make a single model call (a Hermes agent or Claude keeps its own). The plan marks your choices **your choice**, and
the routing by measured results never moves a step away from them.

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
| a calendar event | 60 before, start, end or 15 after (your calendar's iCal address, under Sources) |
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

**A calendar**: under **Sources**, add your calendar's secret iCal address once (Google: Settings → your calendar →
Secret address in iCal format). It stays on the PC and only its host is shown. A rule on it fires once per event, the time
you set before its start (or at its start, its end, or after it): "60 before, only with Anna: brief me on {title}".
Repeating events, moved and cancelled ones are read as your calendar shows them.

**Sources** under Triggers shows each source: when it last looked and what it found, or why it is off (no rule asks for
it, Gmail not granted, the NAS asleep).

## Judged, measured, and new agents

When a task you gave finishes, it is **judged**: a model reads its result against each point of its definition of done
and marks each ✓ or ✗, with a line on why (a build counts by whether it was deployed). A recurring task is judged after
**each run**, on that run's own answer; a run that found nothing new (a quiet briefing, no price drop) is kept but not
judged. The task's card shows the verdict of its latest run (met, partly, not met) and how many tokens it used, and
**Runs** shows every run's.

**Agents, measured** on Tasks lists, per agent and kind of task, how many tasks it worked on in the last 30 days, how
many met their definition of done, how long they took and what they used. From three judged tasks of a kind on, the
Conductor gives a step to the agent that does that kind clearly best, and away from a subscription at its usage limit;
the step says why ("routed: ...").

When no agent fits a step, the stack writes a **temporary agent** for it: a short brief for one model call, with no tools
and its own small key, which ends with the task. Each design is kept with its scores under Temporary agents; one that
met three tasks becomes an idea for a permanent agent under **Agents → Ideas**, which you can have built like any change.

## Software from a specification

Give a task like "build a Python library that renders Mustache templates, from the specification in the repository"
and the intake staffs the software roles: the **analyst** turns the specification into numbered requirements; the
**tester** writes acceptance tests from them while the **builder** writes the code, neither seeing the other's work;
the **judge** runs every test and sends failures back to the builder with what failed, a few rounds at most; the
**breaker** tries to make it fail and leaves each fault as a test; the judge runs everything again; the **tracer** says
which requirement is met where, and which is not; the **presenter** writes your report. The tester and the breaker may
only change their own test folders, and a task can carry a budget of hours and tokens, after which no further step
starts. Each role has its page under Agents → Team.

