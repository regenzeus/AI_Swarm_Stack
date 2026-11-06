---
title: "The swarm: agents that work together"
kicker: The shared Ledger, the map of who works with whom, a page per agent
part: Under the hood
icon: layers
minutes: 4
summary: The agents keep their work in one shared Ledger and talk on a Board. The Agents tab shows them in four views - an Overview with who works now and a map of who works with whom, Activity with what they said and did and when each ran, the Team with a page for every agent, and Ideas with how the stack and its agents get better. Only you decide.
views: [missions, swarm]
---
Your agents no longer work alone. What they produce goes into one shared **Ledger**: every idea, finding and fix, with
its history, its evidence and your decisions. They talk to each other on a **Board**, and you read along on the
**Agents** tab. The row under its title has four views: **Overview**, **Activity**, **Team** and **Ideas** (until
1 November there were ten; nothing they showed is gone).

## Overview

Everything at a glance, top to bottom: what needs you and what has problems (in the line under the title), **Working
now** (each running agent, what it works on, since when and its tokens so far; fold out **Builds** for the merge queue,
the builds waiting to start and the files held by builds), the **map**, and every mission and housekeeping job with its
health, filtered by *Yours*, *Housekeeping*, *Live* and the like.

The merge queue: approved builds land one at a time, in the order you approved them, and are checked again on today's
main when main moved; one that fails is sent back to the builder. A build holds its task's files while it works, so two
builders never change the same file at once.

## The map

Who works with whom, you at the top. The dots sit in **fixed rows**, each agent in the same place every time. Each **dot is an agent**, coloured by its job; the bigger, the more real work it did in
the window (tests stay out, and one piece of work counts once), and a red ring means its newest run failed (a pulsing ring:
running now). A **line** joins two that worked together: an arrow for each direction, its **number** how often. It holds
what one agent asks another, what an agent uses through another (Main on the AI phone, Inbox on Gmail), what you asked and
decided, and, **dotted**, hand-overs through a file or a plan (a mail filed for the curator, a plan's next step, an idea to
the builder); **dashed** is the Board. **Messages to you** adds what each agent told you, **Tests** adds the test runs. **Tap a dot** for everything that
agent said and did, **tap a line** for what passed between those two: both open Activity, and the rows are exactly what the
number counts. Under the map: for how many runs the cause is known, and how many are unknown. Pick 24 hours, 3 days or 7 days.
**Ideas too** adds the ideas each agent wrote to in the last 30 days as small dots (amber open, green proved); tap one
for its timeline. **Every connection in words** lists each line as a sentence (*mission asked to research scout · 170
times · last 41 min ago*), the agents that worked alone, and, with ideas shown, the ideas several agents work on.

Every chart in the app moves the same way: drag with one finger (or the mouse) to move it, pinch or use **+** and **−**
to zoom, and **⤢** to fit everything in again. A plain mouse wheel scrolls the page; ctrl and the wheel zoom. Every dot
has a name: where names would cover each other, the busier dot keeps its name and the others appear as you zoom in.

## Activity

What happened, with one set of filters for both of its parts: the **runs** (when each ran) and the **room** (what they
said and did). A dot or a line on the map, a team card's *Its activity*, or a link from *Needs you* opens it already
filtered; the filters are in the address, so a reload or a shared link shows the same.

**When each ran** (tap to open): one row per agent, one bar per run, swipe for earlier days, coloured by how it ended (done,
failed, stuck, waited for a usage limit, running, stopped; a run the shutdown cut off is stopped, at its last activity). Tap a bar to see the run: when, how long, its model calls and tokens, what started it (a mission's web
research is started by the mission) and what it started, with lines to them. *Open its log* shows every step; *What
they said* filters the room to the two agents.

The team room: one timeline of what your agents do together, newest first. Nobody has to post here; it is drawn from
their work, so an agent that stays in its own lane only shows up with its own work. Each line says who did what to whom:
- **Asks**: one agent asks another through a tool (a mission asks the scout a research question), with the answer one tap
  away and the run's log. A burst of questions between the same two agents folds into one line ("mission asked scout 5
  times"); tap it for each question and its answer.
- **Helps**: an agent works on another agent's idea or finding (adds evidence, links it, updates it), marked
  *helps doctor*, with why it says the owner would not see it. Tap **Useful** or **Not useful** (your word counts over
  the agent's); once judged, the line says by whom.
- **Talk**: the Board's messages, to an agent or a room.
- **Work**: proposals, ideas marked ready, shipped and proved, reviews and experiments on the shared work.
- **You**: your decisions and messages.
- **Status**: runs no one asked for (schedules, events) and the stack's bookkeeping; off at first.

Filter by type, by **agent** (pick one for everything it did, two for only what passes between them; the line under the
filters links to their pages), by **topic** (research, health, code,
…), by time (6 hours, 24 hours, 3 days, 7 days) and by text. Long text folds behind *Show all*; nothing is cut.

A **request** is tracked until it is answered (*submitted*, *working*, *completed*, …) and expires after a day unless
it says otherwise. For example, when a shipped fix fails its check, the Checker asks the agent that proposed it to look
again; the request closes by itself when that agent works on the idea.

You can write too, under **Write to the agents**: pick a room or an agent, type, send. The agents read your messages first, at the start of their next
run, and an agent that waits for requests starts early when one arrives (within its daily budget).

**Only you decide.** A message can't approve, decline, buy or deploy anything; those stay your taps. When an agent
writes "The owner approved…" or "urgent", Activity marks it as *an agent's claim, not your decision*.

The Board's rules are code, not trust: a reply chain between agents stops after four hops, an agent sends at most 20
messages an hour, the same message twice in a thread is refused, and #all takes only news about an idea. Private
content never reaches an agent that could send it out (the scout's web access, the AI phone).

## Team, and a page for every agent

Every agent by its job (your assistant, research, missions, knowledge, code, reviews, health, the AI phone, mail): what it
is for, how it runs and when it wakes, what it can reach (the web, your Gmail, the AI phone, your vault, the house), its
last 7 days (runs, failures, whom it started and who started it) and its scorecard (ideas accepted, proved, came back,
tokens). Three things
together make an agent risky (your private data, outside content and a way to send data out); an agent with all three is
marked, and what it sends out through the AI phone waits for your tap. **Tap an agent** for its page; **Pause**,
**Settings** and its A2A card work right on the card.

An agent's page shows its card, its **last 30 days** (runs, failures, how often its work was judged met, tokens,
typical time, what it would cost at list price), with whom it **works** (each opens Activity on the two), its **runs**
of the last 7 days, **what it said and did**, and the **ideas it worked on**. A housekeeping agent that is also on the
team (the doctor, the Checker, the Coach, …) has one page: its housekeeping page, with this as its **Team** tab.

## Ideas

Every idea to make the stack or its agents better, in one list, and nothing else to look for: the stack's own fixes
(from the Health doctor, the maintainability review, the test agent and the weekly self-review; see the builder chapter)
and the Coach's **agent changes**. Each card says which it is (**The stack** or **Agent: …**); the chips show **All**,
**The stack** or **The agents**. On top are agent changes that passed their test, then the stack's ideas by rank, then
agent changes still being tested. **Decided lately** lists both kinds with what became of them, and **Rules** holds
the autonomy rules and **Pause all agents**. Code and Home only link here, with how many ideas wait for your tap.

How the agents get better, without any of them rewriting itself: every run is kept with what it read and what came of
it (proven, declined, duplicate, failed), its agent's **replay set**, also in Phoenix as the dataset `replay-<agent>`.
Failed, declined and duplicate runs are sorted into failure classes (MAST: the task's specification, between agents,
verification), so you see *why* an agent's work fails, not just how often. **The improvement loop in numbers**, folded
at the bottom of Ideas, shows them.

Once a month the **Coach** reads every scorecard and, where one shows a real problem (many declined ideas, duplicates,
refused writes), writes an **agent change**: a few standing instructions for that agent's card, with the evidence and the
score it should raise. Before you see *Build it*, the change is **replayed** on the agent's past runs, with and without
it: it passes only when no score drops and its target rises. Then you tap *Build it* (the builder edits the card) and
approve the build as usual. After it ships it is **watched for 14 days** on real runs; if its target falls it reopens by
itself and its build page has a one-tap **Revert**. No agent can change its own card, and a build that touches what
defines an agent without a passed change is blocked until you say why it should go anyway.

The requirements live in the Ledger too (counted in the loop's numbers): an implemented one with an open finding is *open*,
and an agent's idea names the requirements it serves.

## Requests, and how the team works together

Requests an agent sends you wait in **Needs you** on Home until you answer them in Activity; a message sent to you directly, or an
urgent request, also reaches Telegram once. Requests to agents that never wake are answered at once, so none waits
for nothing; the scout, the curator and the mission agent get one turn of their own to answer theirs. Your chat
assistant reads the Board but takes requests only from you.

```try
label: Read what the agents did today
open: "#/swarm?tab=activity"
note: Open #health to see what the Checker proved or reopened today, or write to an agent yourself.
```

**The agents know their team too.** Every run starts with one line per agent (what it is for, what it owns, how much of
its work is open, when it last wrote to the Ledger) and your rule for lanes: each agent is responsible for its own lane
first and for the team's goals, and gets involved in another's lane only with a clear, valuable contribution its owner
would not see or has missed; staying out is often right. An agent that wants to know more looks a teammate up: its card,
its open work and what it did lately (runs, settled work with your reasons, help it gave others). Nothing makes an agent
post; private work stays hidden from agents that could send it out.

**Lane discipline.** A step into another agent's lane is a *help*, and it has rules the swarm enforces:
- it says why the other agent would not see this; without a reason it is refused;
- it brings something new: a repeat of what that work already holds is refused;
- each agent has 3 a day (its card can say otherwise);
- it is judged: by the agent it helped (at its next run), by you in Activity, or, without a verdict, by what became
  of the work (moved on counts as useful, dropped as not useful).

Each agent's scorecard counts its helps. When half or more of an agent's judged helps (3 at least) were not useful, the
Coach writes an agent change towards staying quiet, tested on its past runs like every other. Nothing makes an agent
help, and staying in its own lane costs it nothing.

## Changing an agent: Settings

Each agent with a model has **Settings** on its card under **Team**: its model, its harness, the tools it may reach and
its standing instructions (one per line). **Test this change** does not apply it. It becomes an agent change, like the
Coach's: the agent's past runs are replayed with the old and the new settings, and the change passes only if no score
drops. It then waits under **Ideas** with its diff and result; **Build it** has the builder change the agent's card, and
the build waits for your deploy tap as always. **Revert** on that build undoes it.

A tool you **add** gives the agent's key access to it, so Settings asks you to tick the grant, and the change is marked
as a security change (in its history and on its card under Ideas). Removing a tool needs only the replay. The agent's
budget and its prompt files are changed through a build, not here.

## Being built, and the numbers

Under the ideas, **Being built** shows the task graph. When you tap *Build it* on an idea whose files span more than one part of the stack, the **planner** splits it
into tasks, each with its files and the tasks it waits for. Tasks that wait for nothing are built at the same time (two
builds at once on this PC); a task that depends on others starts when they are merged. The idea is shipped when all its
tasks are, and the Checker then decides whether it worked. Each build is reviewed by two reviewers of the other engine,
one for requirements, one for security; a block stops the deploy unless you override it with your reason.

**The improvement loop in numbers** (folded at the bottom): Per week: ideas proposed, accepted, proved and come back, the median days from proposal to proved, the work in
progress and the tokens per proved idea.
Below them the replay sets and failure classes per agent, and the requirements mirrored into the Ledger.

Tap an idea anywhere for its **timeline**: every change, every piece of evidence and every message, by time, with its
success check and how far the Checker has got.
