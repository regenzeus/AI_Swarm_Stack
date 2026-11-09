---
title: "The engine: runs as blocks, templates, packs and trackers"
kicker: How the stack runs its work
part: Under the hood
icon: layers
minutes: 6
summary: Every plan and template is a durable run on Temporal, drawn as blocks with their timing; templates are drawn in Workflow Builder or described in a sentence; packs bring a domain's agents and templates, approved per commit; trackers start runs and are written back to in shadow first.
views: [engine, runs, templates, packs, trackers]
---
The stack runs every plan and every template on its **engine**, Temporal. A run survives a restart of the PC, waits days
for an answer without holding anything, and keeps the whole history of each step.

## The Engine screen

**Stack → Tasks → Templates → Engine**, or a task's **See it run as blocks**, shows each run as its blocks: which are
done, which run now and for how long, which wait and for what. Arrows show what comes after what: arrows out of one
block run at the same time, arrows into one block wait for all of them, a dashed arrow goes back for another round.
Select a block to see what it did, who decided it, and its answer.

On top it says how long the engine has run each kind of plan. The Conductor, the stack's old way of running plans,
stays as the way back until every kind has run 14 days here without falling back.

## Runs

**Runs** opens Temporal's own view of every run inside the app: its full history, its timers, its signals. What it
shows is decrypted by the app; outside the app it is ciphertext.

## Templates

A template is a plan that runs the same way each time it starts. **Templates** lists home's, each pack's and your
drafts. Open one to draw it in **Workflow Builder**: drag a block from the library, draw arrows between blocks, and
select a block to fill in its form.

- **Start** says what starts a run: by hand, a schedule, a tracker item, an event. **End** says what a run delivers,
  and whether reaching it counts as done or as stopped.
- **Agent**, **Change** (a coder on a branch), **Command** (a job at a place: the stack, the WSL host as the tools'
  owner, or Windows), **Approval** (a person of a role decides), **Wait** (for an answer, with reminders),
  **Tracker** (a comment, summary, attachment, link, move or label on the tracker), **Notify** (tells someone).
- **Decision**: an agent answers a question and the run goes down the branch it names; the others are skipped.
- An arrow labelled **if it fails** is taken only when its block fails; without one, a failure fails the run.

**Draft it**: describe what should happen in a sentence or two and the stack draws the template for you, checks it,
and opens it to look over and save. **Save** checks the whole template and says what a block still needs.

## Packs

A pack is a domain kept outside the stack's repository: its agents with their prompts, skills, commands, templates and
exams. **Packs** shows each with the commit that runs. A new commit runs only after you approve it in **Needs you**,
where you see its agents' prompts, its commands and what changed; until then the commit before keeps running. Each of
its commands is approved again at the place it runs, by the hash of its file.

## Trackers

**Trackers** shows each issue tracker the stack reads and the template its new items start. Everything the stack would
write back starts **in shadow**: you see it in Needs you and nothing leaves the stack. Once you judged enough writes of
one kind right, you may let that kind go live, and send it back to shadow at any time.
