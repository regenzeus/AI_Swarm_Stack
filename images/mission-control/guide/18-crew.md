---
title: "The crew: housekeeping agents"
kicker: Agents that keep the stack in shape
part: Under the hood
icon: layers
minutes: 4
summary: A dozen agents curate memory and skills, review the code and the tests, back up and check the stack, on their own schedule. They propose; you decide.
views: [crew]
---
Besides **your missions**, the jobs you give the stack, a **crew** of housekeeping agents works in the background.
Their duties are the stack's own tasks: **Tasks → Team → Crew** lists them, and **Tasks → The stack's** has them as tasks. Each card shows what it looks after,
its schedule, when it last ran, when it runs next and its last result; its edge is green, red or amber like every
agent's.

```try
label: Meet the crew
open: "#/agents?v=team&p=crew"
note: A red edge means its last run failed: open it and look at Now or History. Amber counts memories waiting for you.
```

## Who is on it

| Agent | What it does | When |
|---|---|---|
| **Memory gatekeeper** | checks every fact Hermes wants to remember; sensitive ones wait for your OK | every 10 minutes |
| **Memory Keeper** | looks after every memory: retires duplicates, test noise and agents' runs from the long-term memory and puts it into English (each change with Undo, only while its trial passes), asks you when two of your facts disagree, turns wiki contradictions into disputes a research task settles, re-checks stale pages, folds old journal entries, cleans the search index; on Wednesdays tidies every wiki | nightly |
| **Skill keeper** | mirrors Hermes' skills to Forgejo, parks risky learned skills for your OK | every few minutes |
| **Skill curator** | merges and tidies skills, kept only if the benchmark stays as good | Sundays |
| **Self-review** | turns failures, errors, open work and new versions into ideas in the Ledger | weekly |
| **Maintainability review** | Claude Code reads the code (read-only): hot spots, duplication, dead code, docs drift | Mondays |
| **Test agent** | runs the tests three times: flaky, failing and slow tests, untested functions | Tuesdays |
| **Health doctor** | reviews the open health issues with their logs and proposes fixes (below) | every 6 hours, and after a new alert |
| **Phone cleanup** | turns the AI phone's storage into steps you approve one by one (below) | Sundays |
| **Phone check** | battery, storage, security patch and connection of the AI phone | Mondays |
| **Inbox digest** | while you grant Gmail read: hands a newsletter on a topic you watch to that topic's next report, and files others worth keeping into your vault. It only reads. | daily 07:15 |
| **Journey checks** | follows your journeys end to end without a model: a task to its result (on replayed answers), a test item decided through the queue, every screen at phone width, the newest briefing's e-mail on a phone, every make target; a failure is an alert | nightly 04:10 |
| **Checker** | decides whether each shipped idea worked, starts what your autonomy rules allow, pauses an agent that keeps failing | hourly |
| **Coach** | reads every agent's scorecard and turns a real problem into an agent change with its evidence; each change is replayed on the agent's past runs before you tap Build | monthly, on the 2nd |
| **Token probe** | measured once whether the ChatGPT prompt cache hits (docs/TOKENS.md) | one-off |
| **Swarm sync** | puts the swarm's changes on your timeline and refreshes the ideas list | every minute |
| **Code graph**, **Upgrade check**, **Backup**, **Restore drill**, **Daily digest** | the stack's operations | their own schedules |

**Scorecard** on a proposing agent's Results tab: how many of its ideas you accepted, how many were proved to
work, how many came back, how often it refined a known idea instead of copying it, and your reasons for declining.
An agent whose last three runs failed pauses itself and tells you once; **Resume** it when it is fixed.

**Pause** on an agent's page stops it: it doesn't start a run and can't write to the swarm until you tap **Resume**.
**Pause all agents** is under *Tasks → Ideas → Rules*. Pausing is yours: the AI phone can't do it.

## See what each one does

Tap a crew member for its page, the same one every agent has: **Now** (its latest run's log, and the memories the
curator wants you to look at), **History** (every run of the last 30 days with its log), **Memory** (its journal),
**Results** (how often it succeeded, how long it takes; for the reviewers how many proposals it made, and how many
you accepted, built or dismissed) and **Run now**. Its schedule and its on/off switch are its workflow's: its **Settings** says the
schedule in words and **Its workflow** opens it, where you change the time on its schedule trigger or switch it off
with Active.

The colour of each card in the Agents list is its health: its last result and its 7-day success rate. There is
one health item per agent: every mission, every crew job, and the engines (Hermes chat, the builder, the Claude
worker, the AI phone, Gmail, research). A chat session, a scout run or a Claude review counts for the agent that
started it, so one bad session doesn't become an agent of its own.

- **Alerts** (red; a push and a Telegram message, once per issue) only for what needs you: failing several runs in a
  row (with the last run's reason, such as "plug the AI phone in"), a scheduled run that didn't happen, blocked by a usage limit for over an hour, a run that stalled, tools
  missing compared with the agent's manifest.
- **Notes** (amber; no message): a single failed run, a tool error, a result cut off, the same call again and again,
  a run much slower or more tokens than usual. They show on the card and in the run's log.
- **This PC** joins the list when the machine needs attention: swap over 90 % full (an alert when RAM is short too),
  or a container running another build than its image tag names, or an image `versions.lock` lacks.
- **Not known** is never read as fine. A check that could not run says what it could not read and that its result is not
  known, as an alert on its card: a log that cannot be read, Docker not answering for 10 minutes, the NAS refusing ssh. A
  NAS that gives no answer is asleep and stays quiet, until the mail copy has been silent for 26 hours. A few unreadable
  lines in a log are a note, and the self-review's gaps are notes too.
- An issue clears itself with the agent's next run that doesn't have it, whatever notes that run has. **Seen** (on the
  agent page, on an engine's card, or *mark all seen* at the top of the list) hides it from the list, its count and the
  health doctor until it happens again; nothing is fixed or deleted, and the activity feed records it.
- An engine's card (an engine is what agents run on: Hermes, the intake, the app, this PC) opens its agent's page where
  it is one (Hermes (chat) is your assistant), else Stack → Health; its last run is one link inside it. A duty's page
  opens on the agent's card: what it is for, what it can reach, its last 7 days, Pause and Settings; *Its work* holds
  who it works with, its runs and what it said.

The open issues, each with the run that shows it, are also readable for agents through the `health_issues` tool (a
health doctor reads them and proposes fixes); the app reads them at `/api/health/issues`.

## The Editor

Every morning the **Editor** reads every open idea, with the ideas you decided lately and your reasons, the
requirements not met yet and the stack's decisions. Claude Code (read-only on a copy of the code, so it can look
whether a fix is already in) gives each idea one verdict with its reason: **into** a change request (named; ideas on
the same files or problem share one), **held** (real, waiting for evidence or for planned work), **covered** (by a
named requirement, decision or idea) or **dropped** (wrong, already fixed, a passing problem, or what you declined
before). Each idea shows its verdict; *Tasks → Ideas* opens with *The Editor's sorting*: the would-be requests and
their ideas. It changes nothing yet: you still decide each idea. Later steps let it write those requests in full on
each repository's page.

## The health doctor

Every 6 hours, and within minutes of a new alert (at most once every 30 minutes), the **Health doctor** looks at
every open issue. For each one it gathers the evidence: the run's record, the runner's journal, the Docker logs
and the gateway's failed calls around that time (keys and tokens are blanked out), and where in the code the
check that raised it lives. Then Claude Code, read-only on a copy of the code, diagnoses every issue, sceptical
first: is this **expected** (the deploy's smoke test is refused on purpose), **noise** (the check fires on
something harmless), **external** (a usage limit, a website timing out) or a **real** fault?

- **Real fault**: an idea under *Tasks → Ideas*, ready to build: numbered steps, the files, the test.
- **Noise or expected**: an idea to tune the check, and a **Seen** button next to the finding. The
  next run that meets the same issue adds to that idea instead of proposing it again.
- **External**: explained, nothing to build.

Its page shows each diagnosis (class, cause with file and line, fix, confidence) and its payoff. It changes no code
or setting and marks nothing seen by itself: you build, dismiss or mark it seen. It runs on your Claude plan; when
the plan's limit is reached it waits and reads the answer on its next run.

## The AI phone's standing work

The **Phone cleanup** reads the AI phone's storage every week (the same facts as a cleanup analysis: folders by
year, apps with their last use, caches) and turns it into **steps**: *Delete WhatsApp Images from before 2025
(6000 files) · 4.1 GB*, *Uninstall com.audible.application · 5.8 GB*, *Empty all app caches · 1.2 GB*. Each one has
its own **Approve** (and *Dismiss*: it is not proposed again). Approve runs exactly that step on the AI phone,
once, within 4 hours (it waits if the phone is not connected; Undo works until it starts), with the phone's block list and checks (never banking apps, never Android's own folders,
never system apps), and the step then shows the space it freed. You can't approve from the AI phone itself.
WhatsApp's chat backups are never proposed: you decide those yourself.

The **Phone check** looks at battery, storage, the Android security patch and the connection. Its run fails, and
so raises an alert, only for a real fault: not connected, battery low and not plugged in, or storage nearly full.
The screen sleeps by design, so its state is only reported. An old security patch
is a note on its page.

## The inbox digest

While you grant **Gmail read** (Stack → Connections), the **Inbox digest** looks at the last two days' newsletters
and updates every morning and files the ones worth keeping for your agents' topics into your vault (`raw/_inbox`;
the curator turns them into wiki pages). Bank, security and code mails are never looked at; ads, receipts and
shipping mails stay out. It never archives or deletes mail. Without the grant it does nothing and says so.
Your missions can use Gmail the same way: their mail tools work only under your grants.

## They propose, you decide

The reviews end up as **ideas** under **Tasks → Ideas**: tap *Build it* and the builder makes the
change (with the usual review and your tap to deploy), or *Dismiss* it. The Memory Keeper lists the facts it would not
change itself, each with why (two facts that disagree, a doubtful duplicate); **Forget** takes that one out of recall. It stays
in the memory's archive and can be restored, and nothing is forgotten without your tap. The same weekly run also
tidies the **agents' journals** (their own memories): entries older than the last 8 fold into standing notes, the
folded entries move to the journal's `ARCHIVE.md`, and stale lines go. It touches only the journals, and every change
is a commit you can undo.

## Where the agents' instructions live

Every agent's prompts are files in the repository, one per agent (`prompts/<agent>.md`, named on its card), not text
hidden in the code. Each prompt has a version (a short fingerprint of its text), and every run records the version it
used, so a run's log tells you exactly which instructions it ran with. A prompt changes only after it has been
replayed: its last real cases go through the old and the new text on the agent's own model, and a judge compares the
answers. The change is accepted only when the new text answers properly as often and the judge does not prefer the old
answers; otherwise the checks refuse it, for a change from a session and from the builder alike.

> [!note] The maintainability review and the health doctor run on your Claude plan (Claude Code), the Librarian's checks on ChatGPT,
> the test agent needs no model at all.
