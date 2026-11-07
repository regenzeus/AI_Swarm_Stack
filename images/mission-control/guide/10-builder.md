---
title: "The builder: the stack develops itself"
kicker: Coding work, with you in control
part: Building
icon: rocket
minutes: 7
summary: Describe a change, a sandboxed coding agent writes it, you review it, and one tap deploys it, with automatic rollback.
views: [build]
---
The **builder** is a coding agent that works on the stack itself (and your other repositories). You describe what
you want, it writes the code in a sandbox, and you decide whether it goes live. That's how Mission Control can
grow new features from a chat message.

## The flow

1. **Assign.** Describe the change in the Code tab or in chat.
2. **Build.** The builder gets its own copy of the repository and its own branch. It writes code, runs the
   checks and commits. You can follow its log live.
3. **Checks.** The sandbox checks plus the project's CI (the automatic tests on the NAS) run on the branch.
4. **Review.** You see a summary, the check results, the CI result and the full diff. Sensitive files, such as
   security settings, are flagged.
5. **Decide.** **Approve** merges and deploys. **Request changes** sends feedback and the builder continues.
   **Reject** throws the branch away.
6. **Deploy.** The stack rebuilds what changed, restarts it and runs its smoke and health checks.
7. **Rollback.** If anything fails after deploying, the change is reverted and the previous version is deployed
   again, automatically.

```try
label: Assign a small change by chat
chat: Build: on the wiki page view, add a button next to the title that copies the page as markdown.
note: Hermes calls build_assign. The build appears in the Code tab with its live steps. When it's ready for review, you get a notification.
```

```try
label: Open the Code tab
open: "#/build"
note: Each build shows its status. Open one to see the summary, checks, CI, diff and the Approve button.
```

```try
label: Ask how your builds are doing
chat: How are my builds doing? Is anything waiting for my review?
note: Hermes calls builds_overview and lists each build with its status, checks, CI and the AI review's verdict.
```

## Develop by chat

You can run the whole loop from a chat, also on your phone: ask for a change, then ask how it went, and send it back
with what to change. Hermes reads a build in full with build_details (assignment, the builder's summary, files,
checks, every AI-review finding, and the diff when you ask), sends it back with build_request_changes, and re-runs
the checks with build_recheck. When one engine is stuck (ChatGPT at its usage limit, say) you can ask it to move the
build to the other with build_switch_engine, as the "Switch to Claude Code" button on the build page does. It can never approve: that stays your tap in the Code tab.

```try
label: Review a build by chat
chat: What does the AI review say about my latest build? If it found real problems, tell me what you'd ask the builder to change.
note: Hermes calls build_details. Say "send it back with that" and it calls build_request_changes.
```

## It understands the code

The builder has **Serena**: code tools built on language servers, the same engines your code editor uses. Instead of
searching text, it can ask "where is this function, and what uses it?", rename something everywhere at once, or
replace one function cleanly. Both engines get it, for Python, JavaScript/TypeScript and shell scripts.

## Claude Code as Hermes' colleague

Hermes thinks on ChatGPT, but it can hand work to **Claude Code**: code questions ("how does the deploy roll back?",
"where are triggers checked?"), reviewing or analysing code or a long document, and hard reasoning. Just ask in
Chat; Hermes decides, or say "ask Claude". Claude Code works **read-only** on a copy of the repository's main
branch (or on text Hermes passes), in the builder's sandbox, on your Claude subscription; it never changes
anything. In *analyse* mode it may also run tests and linters in that copy. Changes still go through builds, which
now use Claude Code by default when it is connected.

Every task shows in **Code → Questions to Claude Code**: the question, the answer, and what Claude did step by step, including
its thinking. A task that hits the Claude usage limit waits and continues by itself.

```try
label: Ask Claude about the stack
chat: Ask Claude Code how a build gets rolled back in the ai-stack repo, and which files are involved.
note: Hermes calls claude_task, then claude_task_result for the answer; the task appears under Code → Questions to Claude Code.
```

## A second pair of eyes

Before a build reaches you, the **other engine reviews it**: Claude Code reviews ChatGPT's builds, ChatGPT reviews
Claude's (ChatGPT reviews both while Claude isn't connected). It reads the assignment, the diff and the check results
and gives a verdict on the build page: **Fine to deploy**, **Improve first** or **Do not deploy**, with each finding's
severity, file and line. You still decide; approving a "do not deploy" build asks you to confirm. When one of its
reviewers could not finish, the verdict says **Review incomplete** and names what was not reviewed: such a build stays
out of *Approve all ready* until *Re-run checks* completes the review, or you open it and approve it yourself.

The checks also run **Semgrep** with the stack's own rules: no service published beyond the PC, no Docker access for
containers, no credentials in the code, and the usual dangerous patterns.

## Two engines: ChatGPT or Claude Code

Every build runs on one of two engines, chosen in **New build** (or in chat: "build this with Claude"):

| Engine | Runs on | Good for |
|---|---|---|
| **ChatGPT · Hermes** | your ChatGPT subscription | most changes; the default while Claude Code isn't connected |
| **Claude Code** (default once connected) | your Claude subscription | hard, multi-file work, or when ChatGPT is paused |

Both work in the same sandbox and go through the same checks, CI, review and tap-to-deploy, and the build page shows
each one's steps live. Claude Code needs a one-time sign-in: the Code tab shows a **Connect Claude Code once** card with
the steps until it's done. For Claude builds, that repository's code is sent to Anthropic.

```try
label: Build something with Claude
chat: Build with Claude Code: in the Code tab, show each repository's last commit date in its card.
note: Hermes calls build_assign with engine 'claude'. Needs Claude Code connected first (see the Code tab).
```

## The stack suggests its own improvements

The stack's own ideas live in the swarm's **Ledger**. Four agents write them: the Health doctor, the maintainability
review, the test agent, and the weekly self-review (failed runs and jobs, errors, failed builds, red CI, the latest
review's open items, newer versions of its components). Each idea is kept over many runs instead of written once:
- **Seen again**: when an agent meets a problem that already has an idea, it adds what it saw as evidence, and the idea
  climbs the list. The list shows the sightings, how many duplicates were merged in, and how often it came back.
- **Ranked**: open ideas are ordered by impact, confidence, recurrence and effort. Nothing is capped and nothing closes
  just because it is old.
- **When it ends**: an idea whose health issue is gone (fixed by hand, or cleared) is marked gone. If the problem comes
  back, it reopens.

You find them under **Agents → Ideas**, in one list with the Coach's changes to the agents (the Code tab has a link
that counts what waits for you), and you get a notification when the self-review adds some.

- **Build it** turns an idea into a normal assignment: the builder works on it, and you still review the change
  and tap to deploy. When the build deploys, the idea moves to *shipped, being checked*. A rolled-back or rejected
  build puts it back on the list.
- **Dismiss** declines it. Add a reason: the agent that proposed it gets it as a lesson at the start of its next run.
- **At most two at a time**: while two ideas are being built, Build it on a third says so and leaves it at its rank.

**Did it work?** Every idea carries a success check. A doctor's fix checks that its health issue stays off the board for
7 days; other ideas check for green CI on the deployed version. Once the build deploys, the idea shows as *shipped,
being checked*, and **Decided lately** says how far the check has got. Every hour the **Checker** (a crew member
without a model) decides:
- **Proved**: the check held for its window. A fix whose issue comes back within 30 days reopens and climbs the list.
- **Reopened**: the check failed, with what it saw.
- **Still broken**: tap it when you know better, with what you see; the idea goes back on the list.
- **It works**: the button for the few checks only a person can make.

**Autonomy** (under the list, both off until you switch one on):
- *The Health doctor may start building its small fixes that have a health check.*
- *The test agent may start building new unit tests.*

A rule only starts the build: one a day, only for ideas that meet the definition of ready. The deploy always waits for
your tap, and you can stop the build like any other. Switching a rule off puts its unfinished builds on hold for you.
- **Look for improvements** runs a self-review right away instead of waiting for the week.

Below the list, **Pause all agents** stops every agent at once (each agent's own page has **Pause**). **Decided
lately** shows what you approved, what shipped, and what was dismissed, merged or gone, with the reasons.

```try
label: Ask what the stack would improve
chat: What improvements does the stack suggest right now, and which one would you do first?
note: Hermes calls improvement_proposals and explains the open ideas and the reasons on decided ones. Starting one is still your tap in the Code tab.
```

```try
label: Run a self-review now
open: "#/build"
note: Tap "Look for improvements". New ideas arrive in a minute or two (and wait if ChatGPT is paused).
```

Once Forgejo is connected (Code tab → *Connect Forgejo once*: paste a token, done), every build also opens a pull request on
Forgejo, where you can read and comment on the change. Approving still happens in the app, which closes the pull
request.

## Why it's safe

The builder runs in its own container. It sees only its working copy: no vault, no secrets, no SSH keys, no
Docker. It can reach the model gateway and a package mirror, nothing else. It can't push or deploy. Only the
stack's runner on the host does that, and only after your tap. The checks must pass and CI must be green before
anything deploys: you may approve while CI still runs, and it deploys the moment CI passes (never if it fails).

> [!tip] Keep assignments small and concrete, like one button, one setting or one report section. Small diffs
> are quick to review, and the builder gets them right more often.

## Builds and the usage limit

If ChatGPT pauses mid-build, the build waits and resumes with its unfinished work when the limit resets.
