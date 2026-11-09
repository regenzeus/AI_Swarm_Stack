---
title: "Your code: repositories, graphs and code maps"
kicker: Point it at any codebase
part: Building
icon: code
minutes: 6
summary: Every repository the stack knows, with a live code graph, an explained code map, and one tap to change it with the builder.
views: [build, repo]
---
The **Code** tab is where your repositories live. Point the stack at any codebase, and it builds two kinds of
understanding:

- a **code graph** (Graphify): every function, class and file and how they call and contain each other. It's built
  offline, with no AI, and it updates by itself within a minute of every change;
- a **code map** (Understand Anything): an explained tour of the code, with summaries, layers and how the pieces fit,
  written by the model on your subscription.

Hermes and the builder use both when they answer questions about the code or change it.

```live
repos
```

## A repository's page

Tap a repository to open its page. It has seven tabs, one question each. Each tab has its own link
(`#/repo/<name>?tab=history`), a tab loads its data when you open it, and the app remembers the open tab until you close it.

**Overview: how does it stand?**

- Its state, what is **waiting for you**, **What it is** (the README or the code map's digest) and its **builds**.
- **Ask about it**: a chat with Hermes about this repository.
- **New build**: an assignment for the builder (only for repositories on your Forgejo).
- **Request a change**: the whole swarm on one change, see below.
- **Re-analyse**: the onboarding again, with its steps shown here while it runs.
- **Onboarding**: the checklist of all nine steps, always. Each step says when it last ran, how long it took, which
  model it used with its calls and tokens, its result in numbers ("5,230 nodes · 16,742 edges · 4,513 symbols",
  "260 of 260 files explained", "6 sections · 23 of 25 file:line claims resolve"), and the commit it was made at with
  how many commits the code has moved on since. A step whose result is too thin to work from is **weak**, never done,
  and says why; **Run again** on a step really does that step and the ones after it. **Update** brings the steps that
  follow the code to the latest commit (copy, graph, facts, code map, explanations, search), checks the wiki's pages
  against the changed code and makes the card again; the code map explains only the files that changed.
- **Files explained**: the code map's structure comes from programs, never from a model; the summaries of every file
  and function come from the code itself afterwards, one batch of files per model call. If the ChatGPT limit stops
  it, it carries on later where it stopped.

**Map: what is in it?**

- **Interactive code map**: the clickable map of layers and the boxes inside them, for every repository that has a code
  map (**Full screen** opens it in its own tab). The viewer shows one repository at a time, so opening another repo
  switches it, which takes a few seconds. No token or password. Tapping a layer opens it: its folders are boxes with their
  name, and the files inside them appear as you zoom in (pinch, or the + button).
- **Code map**: what Understand Anything worked out about the code. A short description, a **guided tour** (where
  to start reading, step by step), the **layers** of the architecture, and every **file and symbol** with a
  plain-language summary, tags and complexity (searchable).
- **Code graph**: the best-connected parts of the repository's own code, colored by group: classes and functions
  defined in its files (not the libraries it uses, not its tests), ranked by what holds code together (calls, inherits,
  implements, contains, imports), every big group with its most connected few. Tap a node for its details: what it is
  (function, class, file), where it lives, its **source code** (which lines of how many, and the whole file one tap
  away), what it **calls, imports or contains**, what **uses it**, and what the code map says about it and its file.
  Tap a name in those lists to walk through the code.

**Card: what does a coding agent get first?** The few things the code does not say, made from onboarding without a
model: the commands, the rules that are not obvious, the fragile areas, one line per part of the code and where to start,
each with where it came from. Every coding run on the repository starts with it, and nothing longer. **Pin** keeps a line
always given and first in its part, **Strike** never gives it, and a line you add is always given; **Make again** makes
it from what onboarding knows now, keeping your pins and strikes. Below it: what else an agent can read when it wants
(the guide, the wiki, the code map's line per file, the facts), never pushed. The first time an agent reads a file it is
told what the stack knows about it (tap a node on the Map tab to see that note), a search with very many hits hears which
folders they fall in, and after each edit the repository's linter runs on the file.

**History: where does it break, and who knows it?** From the git history, in plain words ("changed 431 times, hard to
read"): what changes often and is hard to read, what changes together, who knows it, and how old it is. The most telling
rows come first and **Show all** brings the rest. Tap a file to ask Hermes about it.

**Health: how healthy is it?** The parts of the code, dead code, who it depends on and what the tests reach, each finding
with its reason, and whether it was measured or inferred.

History and Health say so when a repository has not got these yet, or what failed, with **Re-analyse** beside it.

**Analysis.** For your own work (your forge, your PC): the engineer's guide, written from the repository's own
structure: entry points and main flows with file:line, a module map, the key types, how to extend it, build and test,
fragile areas, a glossary. For something to evaluate: what it is, how it works, what the stack could take from it,
risks, a verdict. You choose which at **Add a repository**; the page says which it got.

**Wiki: what did we learn working on it?** The repository's pages. A tap opens the page in the wiki viewer. A page
marked **to check** cites code that changed since it was written; the page says which files, and the Scribe checks it.

```try
label: See what a coding agent gets first
open: "#/repo/ai-stack?tab=card"
note: Pin a line every agent must know, or strike one that misleads.
```

```try
label: Open the map of the stack's own repository
open: "#/repo/ai-stack?tab=map"
note: The stack studies itself too. Scroll to the graph and tap a node.
```

## Change requests

Say what should change, on a repository's page or in the chat ("Change ai-stack: ..."), and the swarm takes over. You get
back one branch where it is done the repository's way, with the evidence, and nothing lands without your tap.

1. **The specification.** The intake writes acceptance criteria a test can check, the scope, the risks and a size. A small
   change starts at once. A medium or large one waits for your **Go** on its task page, where you can edit the criteria.
2. **The work.** The suite runs first, so failures that were there already are no fault of the change. For a medium change
   a tester writes the acceptance tests before the code exists, and each must fail before the coder starts. The coder works
   on the branch; a breaker tries to make it fail. A program judges: what fails goes back to the coder, up to three rounds.
3. **The look.** Three reviewers on the other engine (requirements, security, this repository's conventions), then a
   prober that starts it and uses it, and keeps a log or a screenshot.
4. **Your review.** The task page shows each criterion with its test before and after the change. **Review it** opens the
   build page with its diff and report: Approve merges (ai-stack: and deploys), Request changes sends your words back to
   the coder and the steps after it, Reject ends it.

**One wiki per repository.** What the swarm learns stays: the Scribe writes it at onboarding from the code map and the
analysis, and after each change from its retro. Each fact names its evidence and each page the commit it held at; a page
whose files changed since is marked to re-verify, and an agent is told the code wins. What you say in a review becomes a
lesson there. It sits under Wikis with the others.

**Budgets.** Each size has a budget of tokens, shown on the task page. A change past it stops with the reason, and
**Go on** carries on from there with the budget doubled. docs/LIMITS.md lists it.

```try
label: Ask for a change in the chat
chat: Change TestRepo: add a --version flag to its command line
note: Hermes calls change_request. A small change starts by itself and shows up under Tasks.
```

## Adding a repository

**Study a repository.** Paste its https link under **Add a repository**, say whether it is **your own work** or
**something to evaluate**, or ask in chat. Onboarding always does the whole package, one step after the other, whatever
the repository's size: a copy of the code with its whole history, its code graph, its facts, its code map, every file
explained, a place in the search, a written analysis under its **Analysis** tab (the engineer's guide, or the review)
and its wiki. Its **Overview** shows the checklist: the step it is at, and each step's quality, last run, model and cost.
No step counts as done because a file exists: a hollow map or a thin analysis is weak, and the page says so. It takes minutes to an hour, waits
by itself when a usage limit or the PC's memory is in the way, and goes on after a crash or a restart. You get a message
when it ends, and if a step cannot be done the message and the page say why, with **Try again**. Third-party code is never
run: the analysis only reads it.

**Its facts.** Without a model, CodeLore and repowise measure where the repository breaks, what changes together, who knows
it, how old it is and how healthy it is. They are third-party programs, so they run sealed, with no network and no secrets, on a
throwaway copy that is then deleted. If one cannot run, the other's results stay and the page says what is unknown. You read them under **History** and **Health**. The
facts are rebuilt when the repository's code moves, the wiki's Fragile areas page starts from them, and the exam tries giving a
coding agent just the part its task needs.

```try
label: Study a repository by chat
chat: Study the repository github.com/pallets/click and tell me how its command parsing works.
note: Hermes calls understand_repo. The repository appears in the Code tab with its steps, and you get a message when the onboarding ends.
```

**Create a new repository.** Give it a name, and the stack creates a private repository on your Forgejo with a README
and an AGENTS.md, ready for the builder.

**Let the builder change a studied repository.** On its page, **Let the builder change it** copies it to your Forgejo
(the original stays as `upstream`). From then on it's a normal repository for builds.

```try
label: List your repositories
chat: Which of my repositories can the builder change, and which ones are only studied?
note: Hermes calls repos_overview. To create one by chat, say "create a repo called …" (repo_create); to move a studied one, "let the builder change …" (repo_make_buildable).
```

> [!note] Creating repositories and making them buildable needs a **Forgejo token**, once. The Code tab shows a
> **Connect Forgejo once** card until it's set up: create the token in Forgejo (at home, on the NAS), paste it into
> the card, tap *Connect*. The runner checks it and stores it encrypted; it never goes to Hermes or any AI.

## Where things are

**Repositories** have their own panel on the left, always in view: the ones the builder can change come first in bright type,
then the ones it has only studied, with a number on each that has something waiting for you; exam trials stay folded at the end. On a phone they are one
of two tabs, **Repositories** and **Work**, and the app remembers the one you used last.

Beside them is the work. **Waiting for you** comes first: every build ready for your review, newest first. Tap one to see the
change (the git diff) right under *Approve & deploy*. Below it, what is **working** and what has **stopped**; a change is one
row however many builds its steps are. Earlier builds and the questions your agents asked Claude Code stay folded at the end.
**New build** and **Add repository** open at the top of the page. The red number on **Code** in the menu counts the builds waiting for you.

## Removing a repository

On its page, **Remove from the stack** deletes the stack's copy: the clone, its graph and code map, and the builder's
working copy. A repository on your Forgejo stays there (delete it in Forgejo if you want it gone), and ai-stack itself
cannot be removed. You type its name to confirm.

## The other code tools

| Tool | What it's for |
|---|---|
| **OpenCode** | a coding app in the browser, for hands-on changes to your repositories |
| **Forgejo** | the git server on the NAS: history, branches, CI results |

```live
apps
```
