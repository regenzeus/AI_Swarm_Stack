---
title: "Repeating tasks: briefings, research, price watches"
kicker: Work that runs by itself
part: Everyday use
icon: target
minutes: 7
summary: Give the stack an ongoing job, such as a daily briefing or a research project, and it keeps working on it on a schedule.
views: [mission, read, live, files, file]
---
A **repeating task** is a standing job: a daily briefing, a long research project, a price watch. You describe it
once, and its agents work on it on a schedule, on demand, or when something happens. Inside the stack it is still
called a mission (its files are under `missions/`); in the app it is a task like any other, under **Tasks →
Repeating**. Each run's results, cost, log and memory are tracked on its page.

## In the Tasks list

**Tasks → Repeating** lists your repeating tasks, each with its next run, its When and its last result; the ones that
need you or run right now are under **Active** too. The crew's duties are the stack's own repeating tasks, under **The
stack's** and **Team → Crew** (see the crew chapter).

Health is the colour of a card's edge: green the last run went well, red it failed (or keeps failing), amber
something to look at or something waiting for you, blue running now, grey not run yet or switched off. The card says
why in one line. An archived task is under **Done**.

```try
label: Only what runs right now
open: "#/tasks?v=activity"
note: Every agent that is working at this moment; tap one to watch its log.
```

## Its page

Every repeating task, yours or a crew duty, opens the same page:

| Tab | What it shows |
|---|---|
| **Overview** | what it needs from you, then its live log (or its latest run's), then its latest result |
| **Runs** | every run: state, trigger, summary, totals, its **Log**, its **Result** and the raw output |
| **Memory** | its journal: standing notes and one entry per run; edit or forget any line |
| **Results** | what it delivered, newest first, each opening the result; then what it took: runs, success, time, model calls, tokens, the $0 it costs, wiki pages, proposals |
| **Settings** | its form (schedule, triggers, delivery, goal) or the crew duty's schedule |
| **Agents** | who worked on it: the agents, their part and their hand-offs, as on any task's page |

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

A newsletter can feed a briefing too. While you grant Gmail read, the Inbox digest reads each new newsletter for the names in
the briefing's watchlist and searches, and asks one model whether the mail holds a fact for its key questions. A mail that does
goes to the next report, which names it in its sources; through the report it reaches the topic's wiki. It is read as data, its
links are never opened, and your own mail from people is never looked at for this. The briefing's page lists these under **From
your e-mail**: waiting for the next report, cited, or read and not used. The Inbox digest's page says which mails it left out and why.

```try
label: See what your e-mail gave a briefing
chat: Which newsletters fed my copper briefing this week, and what did the report take from them?
note: Hermes reads the topic's mail folder and its reports. The same list is on the briefing's page, under From your e-mail.
```

**Long-term task.** An agent works on a goal over many runs and keeps its own notes between them. It researches,
compares and builds up an answer over days. Good for "find the best copper producer to watch" or "track this
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
label: Open the New task form
open: "#/tasks?new=1"
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
chat: Pause my copper briefing until Monday, and run the lithium one now.
note: Hermes uses mission_control for each mission and confirms what it did.
```

## Changing a mission

Goal, key questions, sources, schedule, delivery and depth can all be changed. The simplest way is to say what you
want in the mission's focus chat (the **Tune** button). Hermes reads the mission with `mission_details` and
changes it with `mission_update`. You'll find the change listed in the mission's activity.

```try
label: Change a schedule by chat
chat: Move my copper briefing to weekdays at 06:30 and also send it by e-mail.
note: Hermes reads the mission, then updates the schedule and delivery, and tells you what changed.
```

## One-off jobs

"Research X and e-mail me" becomes a **one-off mission**: it runs once, delivers, and archives itself. You'll
still find it in the archive later.

## Files it delivers

When you ask a mission for something you want to keep, such as a spec, a primer or a table, you name it as a
**file**. "Send me the checkbox spec as a Markdown file" becomes `checkbox-spec.md`.

- **Where you name files.** Hermes records the files when it creates the mission. You can also name them on the
  agent page under Settings → **Files it must deliver**.
- **What it can make.** Markdown, CSV, JSON and plain text, up to 2 MB each. It can't make Word, PDF, images or
  archives, and Hermes says so before the mission starts.
- **How the agent saves them.** The agent saves each file with `file_save`. Saving again keeps the earlier version.
- **Results.** The agent page's Results starts with **What you asked for**: each file with Open, Download and Copy,
  and how it was delivered (e-mailed as an attachment, sent on Telegram). A file that was asked for but not saved is
  shown in red as **Asked for, not delivered**, with **Run again for it**. That run is marked **Partial**.
- **Delivery.** The e-mail attaches the files and Telegram sends them as documents. Drafts the agent left in the
  Ledger are listed below the files, then the run reports.
- **Files page.** **Stack → Files** shows every mission's files, the space they take, and the trash.
  - Deleting a file moves it to the trash, where you can restore it for 30 days.
  - Each day the cleanup keeps the newest 5 versions of each file.
  - It moves the files of missions archived 180 days ago to the trash, unless you pinned them.
  - It empties the trash after 30 days.
  - **Clean up now** shows what it would do before it does anything.

## What each run costs

Every mission shows runs, tokens and dollars for the last 30 days, and each run lists its model calls. Because the
stack runs on the subscription, the dollar figure stays at $0.00. Tokens show how much work was done.

> [!note] When ChatGPT's usage limit is reached, a run shows **Waiting for ChatGPT** with the time it will retry.
> It retries every 30 minutes, for up to 8 hours. You don't need to do anything.

## Agent memory

Each agent keeps its own memory, a short file in your vault: `agents/<agent>/MEMORY.md` (for example
`agents/mission-copper-briefing/MEMORY.md`), committed in git like the rest of the vault.

- **Written at each run's end**: the run's log is condensed into an entry: what it did, what it found, what failed and
  why, the open questions. One short ChatGPT call (gpt-sub-fast) writes it; when the model is limited, a plain
  summary from the log does.
- **Read at each run's start**: every run opens with the memory chosen for its task, within its kind's budget (a
  mission's is 20,000 characters). What it must have comes first: its card's standing instructions and what the swarm
  holds for it (your messages, requests, help, your decisions on its ideas), its working state, its standing notes and
  its last entries. The rest is filled from what its role is subscribed to (its own wiki, the vault wiki, your facts
  that match the task, its role's lessons), the best match first; what does not fit is listed by name so the agent can
  open it, and other memory that matches is offered. A wiki built from your mail is read only by its own mission.
  **Knowledge** has the whole picture; the run's page shows, under **Memory**, what it was given and what it used.
- **Working state**: a mission's notes for its next run ("state, findings, open questions, next steps") are the
  **Working state** at the top of its memory file, replaced by each run. The old `NOTES.md` moves there at its next run.
- **Standing notes and lessons**: an agent keeps a lesson with the memory tool's `note` ("check the board manual
  first"); a lesson with its evidence goes into its role's playbook, where every agent of that role reads it. The
  weekly memory curator folds old entries into standing notes (the folded entries move to `ARCHIVE.md`); you add, edit
  or forget lines on the **Memory** tab. Every change is a commit.

This applies to long-term tasks, shopping and cleanup missions and the crew jobs that use a model. A daily briefing
writes its entries too; its own report already carries what came before.

## See everything a run does

Every run has a **Log** (the task's page → Runs). It shows, in order:
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
