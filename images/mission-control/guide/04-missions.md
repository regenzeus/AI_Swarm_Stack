---
title: "Missions: briefings and long-term tasks"
kicker: Work that runs by itself
part: Everyday use
icon: target
minutes: 7
summary: Give the stack an ongoing job, such as a daily briefing or a research project, and it keeps working on it on a schedule.
views: [mission, new, read, live]
---
A **mission** is a standing job. You describe it once, and an agent works on it on a schedule, on demand, or when
something happens. "Mission" is the word for the job; the thing doing it is the **agent**. Each run's results, cost,
log and memory are tracked on the agent's page.

## One list of agents

The **Agents** tab is one list: your missions (**Yours**) and the crew that keeps the stack in shape
(**Housekeeping**, see the crew chapter). The chips filter it: **All**, **Yours**, **Housekeeping**, **Live**.
It is sorted by what needs you first, then what is running, then by the next run. The top line counts what needs
you (a grant, memories to look at, an OK on the phone).

The row under the title has four views: **Overview** (this list, with who works now and the map of who works with
whom above it), **Activity**, **Team** and **Ideas** (see the
swarm chapter).

Health is the colour of a card's edge: green the last run went well, red it failed (or keeps failing), amber
something to look at or something waiting for you, blue running now, grey not run yet or switched off. The card says
why in one line. Archived missions fold away at the bottom.

```try
label: Only what runs right now
open: "#/missions?f=live"
note: Every agent that is working at this moment; tap one to watch its log.
```

## The agent page

Every agent, a mission or a housekeeping job, opens the same page with five tabs:

| Tab | What it shows |
|---|---|
| **Now** | what it needs from you, then its live log (or its latest run's), then its latest result |
| **History** | every run: state, trigger, summary, totals, its **Log**, its **Result** and the raw output |
| **Memory** | its journal: standing notes and one entry per run; edit or forget any line |
| **Tasks** | the tasks it worked on, its part in each (a step, planned it, called in by another agent), each opening its task's page |
| **Results** | what it delivered, newest first, each opening the result; then what it took: runs, success, time, model calls, tokens, the $0 it costs, wiki pages, proposals |
| **Settings** | the mission's form (schedule, triggers, delivery, goal) or the crew job's schedule |

## The agent log

One readable log for every agent, live and afterwards. Each line is one step: the time, its kind and what it did
with what (the file, the URL, the command, the question), with how long it took, the tokens of the model calls that
led to it, and the result (its size, or the error). Tap a line for the details: the arguments, a preview of the
result, and for a write the change itself (added lines green, removed red).

| Kind | Means |
|---|---|
| **START**, **END** | the run starts (its brief) and ends (done, failed, stopped, stalled, usage limit) |
| **READ**, **WRITE** | files, the vault, its memory; a write shows its diff |
| **TOOL** | any other tool or pipeline step (a command, a Claude task) |
| **WEB**, **MAIL**, **PHONE** | research and pages, Gmail, the AI phone |
| **THINK**, **SAYS** | its plan and thinking where the model sends it; what it answered |
| **WAIT**, **PROPOSE**, **ERROR** | waits (a scan, a limit, your OK), proposals for you, what went wrong |

The chips above the log count each kind; tap one to see only those lines. **Summary**, **Steps** and **Everything**
choose the detail (Everything adds every single model call). Builds (Code) and chats show the same log.

## Two kinds of missions

**Daily briefing.** The Topic Desk reads news sources, filings and prices for a topic and writes a structured
report: what happened, why it matters, sources. Good for markets, companies, industries.

**Long-term task.** An agent works on a goal over many runs and keeps its own notes between them. It researches,
compares and builds up an answer over days. Good for "find the best uranium producer to watch" or "track this
company's project milestones". Tasks can run as **deep research** (see the Deep research chapter).

Here are your missions right now:

```live
missions
```

## Cleanup analysis

A **cleanup analysis** finds where the space goes and what could go, on the **AI phone** or the **PC**, and never
deletes anything:

- **AI phone:** used and free space, Android's categories (apps, app data, photos, audio…), the biggest folders
  and files, old data by year (WhatsApp media, camera, backups), every app with its size and last recorded use, and
  the caches, each with the exact words to tell Hermes to remove it. Banking and other blocked apps are only listed.
- **PC:** a scan of the local drives like TreeSize (Google Drive and other cloud drives are skipped): free space per
  drive, the biggest folders and files, and known clutter labelled ✅ safe, ⚠️ caution or ⛔ never (temp files,
  Recycle Bin, browser caches, old installers, Steam games, old disk backups, the WSL disk). Windows runs the scan
  in the background at low priority; it takes about 10 to 15 minutes. Sizes are in Windows' own units, as in Explorer.

Both show every step (what was scanned, how long it took, what was found) in the run's **Log**.

```try
label: Clean up the AI phone
chat: Make a cleanup analysis of the AI phone: what takes the space and which apps I no longer need.
note: The report lists the biggest unused apps and folders. To act, tell Hermes "on the AI phone, uninstall …": each app asks you once.
```

## Creating a mission

The easiest way is to ask Hermes. It drafts the mission, picks a schedule and starts the first run.

```try
label: Create a briefing by chat
chat: Start a daily briefing on lithium prices and the big lithium producers, weekdays at 07:00.
note: Hermes calls mission_create. The new mission appears under Missions and its first run starts.
```

Or use the form:

```try
label: Open the New mission form
open: "#/new"
note: Choose briefing or task, give it a title and a goal, pick a schedule and where results go.
```

## Schedules

| Write | Means |
|---|---|
| `daily 06:30` | every day at 06:30 |
| `weekdays 07:00` | Monday to Friday at 07:00 |
| `weekly mon,thu 08:15` | on the days you list |
| `every 6h` | every 6 hours (1 to 24) |
| `manual` | only when you start it |

If the PC was off at the scheduled time, the run catches up once when it's back (within 20 hours).

## Running, pausing, archiving

Open a mission to **Run now**, **Pause**, **Resume** or **Archive** it. Paused missions keep everything and
don't run. Archived missions fold away at the bottom of the Agents list. You can also say it in chat:

```try
label: Control a mission by chat
chat: Pause my uranium briefing until Monday, and run the lithium one now.
note: Hermes uses mission_control for each mission and confirms what it did.
```

## Changing a mission

Goal, key questions, sources, schedule, delivery and depth can all be changed. The simplest way is to say what you
want in the mission's focus chat (the **Tune** button). Hermes reads the mission with `mission_details` and
changes it with `mission_update`. You'll find the change listed in the mission's activity.

```try
label: Change a schedule by chat
chat: Move my uranium briefing to weekdays at 06:30 and also send it by e-mail.
note: Hermes reads the mission, then updates the schedule and delivery, and tells you what changed.
```

## One-off jobs

"Research X and e-mail me" becomes a **one-off mission**: it runs once, delivers, and archives itself. You'll
still find it in the archive later.

## What each run costs

Every mission shows runs, tokens and dollars for the last 30 days, and each run lists its model calls. Because the
stack runs on the subscription, the dollar figure stays at $0.00. Tokens show how much work was done.

> [!note] When ChatGPT's usage limit is reached, a run shows **Waiting for ChatGPT** with the time it will retry.
> It retries every 30 minutes, for up to 8 hours. You don't need to do anything.

## Agent memory

Each agent keeps its own memory, a short file in your vault: `agents/<agent>/MEMORY.md` (for example
`agents/mission-uranium-briefing/MEMORY.md`), committed in git like the rest of the vault.

- **Written at each run's end**: the run's log is condensed into an entry: what it did, what it found, what failed and
  why, the open questions. One short ChatGPT call (gpt-sub-fast) writes it; when the model is limited, a plain
  summary from the log does.
- **Read at each run's start**: every run opens with one block in a fixed order (at most 12,000 characters):
  1. **From the swarm**: its card's standing instructions, your messages, requests, help other agents gave its work and
     your decisions on its ideas;
  2. **Its state**: its working state (where the work stands, what is next), its standing notes and its last 5 entries;
  3. **Its knowledge**: the matching pages of the wikis its card names: its own wiki first, then the vault wiki and your
     notes, then wikis that share a subject with its own. A wiki built from your mail is read only by its own mission;
  4. **Your facts** that match the task (long-term memory);
  5. **Its team**.

  The agent is told not to fetch the swarm's context again. The log shows each part as a **READ** line, and the entry as
  a **WRITE** line at the end.
- **Working state**: a mission's notes for its next run ("state, findings, open questions, next steps") are the
  **Working state** at the top of its memory file, replaced by each run. The old `NOTES.md` moves there at its next run.
- **Standing notes**: an agent keeps a lesson for all its future runs with `agent_note` ("check the board manual
  first"); the weekly memory curator folds old entries into standing notes (the folded entries move to
  `ARCHIVE.md`); you add, edit or forget lines on the **Memory** tab. Every change is a commit.

This applies to long-term tasks, shopping and cleanup missions and the crew jobs that use a model. A daily briefing
writes its entries too; its own report already carries what came before.

## See everything a run does

Every run has a **Log** (Agents → an agent → History). It shows, in order:
every **model call** (model, tokens in and out, cached tokens, thinking tokens, how long it took), every **tool
call** with its arguments and result, every call through the gateway (research, vault, page reader, phone) with its
duration, errors with the real message (a usage limit says so), what the agent said, and its thinking when the model
returns any. The scout's research is indented under the mission that asked for it.

Pick the detail you want: **Summary** (what it said, errors), **Steps** (tool calls and model calls) or
**Everything** (also the gateway's own records, nothing folded). A running run opens live and updates every few
seconds. At the top: totals, the most used tools, and warnings, such as a tool called with the same arguments
again and again, or calls that resend their whole context without caching.

> [!note] ChatGPT returns only how many tokens it spent thinking, not the thinking itself; Claude Code builds show
> their thinking in the build's steps. Runs from before 28 October have no timeline.

## What it does and what it touches

A timeline has two panes. **What it does**: the steps in order. **What it touches**: what it **read** (files, web
pages, searches, mails, phone screens), what it **changed**, what was **refused** (no grant, a guard, or you said
no) and what it saw only partly (**cut off**). Above them: **Problems** found by fixed rules (unknown tools, calls
without the arguments their tool needs, the same call again and again, results cut off and not read on before the
answer, a run without a clean end),
**Statistics** (per tool, model latency and cache share), **Stages**, **Skills** (available, loaded, used) and the
**Manifest** (model, profile and tools in force; it notes drift since the last run). A run's problems also colour the
agent's card in the Agents list.

## Watch any agent live

The **run view** shows the same two panes for every kind of agent, not only missions: Hermes answering in chat,
a mission, a build, a Claude task, the AI phone, Gmail, the crew. It opens from an agent's **Now** tab (**full view**), from a
run's **Log** button, the build page, a Claude task, the pulse button in a chat's header
and **What it did** on the AI phone page. While the agent works, new steps appear within a second; afterwards the
same page replays the run.

At the top: the state (**Live**, **Done**, **Failed**, **Stopped**, **Stalled** if it went silent for 20 minutes,
**Usage limit**), how long it took, model calls with tokens and cache share, tool calls, the agents that worked
inside it, and drift since its last run. **What it touched** also shows the **box** a build or Claude task works
in and the **connections** it used. Problems found here colour the agent's card and reach you once.

## Where results go

Reports are files in your vault (`topics/<mission>/reports/…`, task logs under `missions/<mission>/log/`), so they
are searchable, versioned in git, and part of your knowledge forever. Open them from the agent's **History** tab (each run's **Result**, and **All results**).
