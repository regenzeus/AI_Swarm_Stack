---
title: "Telemetry: how each agent did, day by day"
kicker: Numbers over time
part: Under the hood
icon: pulse
minutes: 3
summary: Runs, success, the judge's verdicts, tokens, time and what it would cost if paid, per agent and day for a year, every number opening its runs; each task run as one trace in Phoenix.
views: [telemetry, trials]
---
**Stack → Telemetry** shows how every agent did, one day at a time, for up to a year.

On top: how many runs, how many ended well, how many of the judged tasks met their definition of done, the tokens,
what they would cost at the provider's list price, and the median and slowest (95th percentile) run. Below: runs and
tokens per day (hover a bar for its day), and the agents, busiest first. An agent that failed in more than three of
ten runs says **fails often**. Tap an agent for the models, harnesses and kinds of work it ran and **its runs** of those
days, each opening its run view.

Filter by days (7, 30, 90, a year), agent, model and kind of work (a task's kind, or a mission run, a build, a chat, a
crew job). The history is rolled up every hour from the run record; a verdict counts on the day its task was judged.

## What it would cost if paid

The subscriptions cost $0 a call. To compare agents and spot waste, every run, task run and step shows its tokens and
what they would cost at the provider's list price ("$0.42 if paid"): on the task card and each of its runs, on the
swarm map and each agent's lane, on a run's own view, and here. The prices come from the gateway's own price table
(each name the stack uses, like gpt-sub, priced as the model behind it); its date is under the page title. It is
taken again when the gateway is upgraded, and the monthly upgrade check says when it is behind.

## One trace per task run in Phoenix

A minute after a task's run ends, it goes to Phoenix (**Traces** on a run's view) as one trace: the run at the top,
each step under it, the agents a step started under the step, and their model and tool calls under them.

## Trials: the swarm's practice runs

**Trials** (top right on Telemetry) is the scoreboard of the swarm's practice runs. A trial gives the swarm a real job
with an answer key no agent can read: *semver* and *Mustache* ask for a library written from a specification alone
(clean room), *mqtt-trace* asks where an MQTT broker implements each requirement and which ones it misses. Each run of
a trial stands beside the earlier ones, newest first: the answer key's cases passed (per area), the clean room (what
the agents read and ran), how alike the code is to the upstream one, the time, the tokens, how many agents worked and
how many at once, the questions the intake asked, and the model judge's verdict, marked when it disagrees with the key.
Under each number: the change since the run before. **The report** opens the run's full report in the vault, **Its
task** the task's page. Trials run at night, one at a time, each within its budget.

