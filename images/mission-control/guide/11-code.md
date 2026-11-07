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

Tap a repository to open its page:

- **Code map**: what Understand Anything worked out about the code. A short description, a **guided tour** (where
  to start reading, step by step), the **layers** of the architecture, and every **file and symbol** with a
  plain-language summary, tags and complexity (searchable).
- **Code graph**: the best-connected parts of the code, colored by group. Tap a node for its details: what it is
  (function, class, file), where it lives, its **source code**, what it **calls, imports or contains**, what **uses
  it**, and what the code map says about it and its file. Tap a name in those lists to walk through the code.
- **What it is**: the README.
- **Interactive code map**: the clickable map of layers and the boxes inside them, right on the repo page, for every
  repository that has a code map (**Full screen** opens it in its own tab). The viewer shows one repository at a time, so
  opening another repo switches it, which takes a few seconds. No token or password. Tapping a layer opens it: its
  folders are boxes with their name, and the files inside them appear as you zoom in (pinch, or the + button).
- **Files explained**: when Understand Anything could only map the structure of a big repository, the stack explains
  every file and function from the code itself afterwards. The Code map card shows how many files are explained; if
  the ChatGPT limit stops it, it carries on later where it stopped.
- **Ask about it**: a chat with Hermes about this repository.
- **New build**: an assignment for the builder (only for repositories on your Forgejo).
- **Request a change**: the whole swarm on one change, see below.

```try
label: Open the stack's own repository
open: "#/repo/ai-stack"
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

**Study a repository.** Paste its https link under **Add a repository**, or ask in chat. Onboarding always does the
whole package, one step after the other, whatever the repository's size: a copy of the code, its code graph, its code
map, every file explained, a place in the search, and a written analysis on its page (what it is, how the stack could
use it, risks, a verdict). Its page shows the step it is at. It takes minutes to an hour, waits by itself when a usage
limit or the PC's memory is in the way, and goes on after a crash or a restart. You get a message when it ends, and if
a step cannot be done the message and the page say why, with **Try again**. Third-party code is never run: the analysis
only reads it.

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
