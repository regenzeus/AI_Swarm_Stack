---
title: What the AI Stack is
kicker: Welcome
part: Get started
icon: home
minutes: 4
summary: A private AI assistant that runs on your own PC, works while you sleep, and costs nothing to run.
views: [home]
---
The AI Stack is a personal AI team that lives on one Windows PC at home. It reads the news for you every morning,
researches companies, watches the SEC and the markets, keeps a growing knowledge base, remembers what you told it,
and can even improve its own software, which you approve with a tap.

You use all of it from **Mission Control**, the app you are reading this in. It works on your phone and your PC.

```live
architecture
```

## Four ideas behind it

**It's yours.** Everything runs on your PC and your NAS. Your notes, reports, chats and memories never go to a
cloud service except the model call itself. The app is only reachable from your own devices over Tailscale, your
private network.

**It costs $0 to run.** Every model call goes through your ChatGPT or Claude subscription. No paid model is configured
anywhere, so nothing can spend money by accident. When ChatGPT's usage limit is reached, jobs simply wait and
continue on their own once it resets.

**It works by itself.** Briefings run on schedules, triggers watch for events every ten minutes, backups run
nightly, and a restore test proves every week that the backups work. Most days you just read results.

**It's safe by design.** Each agent has its own key and only the tools it needs. Only one agent reads the web, and it can't see your
private data. The coding agent works in a sandbox and can't deploy. Nothing reaches production without your tap.

> [!tip] New here? The next chapter, **Your first ten minutes**, walks you through the five things worth trying first.

## The app at a glance

| Tab | What you do there |
|---|---|
| **Home** | What needs you, what is running now, and a live feed of everything your agents produced; ask Hermes from the top |
| **Agents** | one list of agents: **Yours** (your missions: create, run, pause, tune, read results) and **Housekeeping** (the crew); each opens a page with Now, History, Tasks, Memory, Results and Settings. Four views under the title: **Overview** (who works now, a map of who works with whom, every agent), **Activity**, **Team** (a page for every agent) and **Ideas** |
| **Wiki** | Browse the knowledge your missions have built, as pages and as a graph |
| **Code** | Your repositories with code graphs and code maps, the builder's work, reviews and deploys |
| **Chat** | Talk to Hermes, your assistant. It can use every feature in this guide |
| **Stack** (its dot: green ready, blue an agent runs, red not connected) | How the stack works and how it is doing: live map, health, resources, costs, memory, knowledge intake, apps, settings, and this guide |

At the end of every screen, **How this page works** opens the chapter about that screen. The whole guide is under
**Stack**: every section there has a **How it works** link, and the chapter list is at the bottom.

## Home

Home answers three questions, in this order:

- **Needs you**: only decisions that wait for you, each one tap away: builds ready for review, a purchase to approve,
  AI phone cleanup steps, AI phone approval requests, Gmail Trash batches, agents that need access, memories to
  confirm, and setup steps only you can do. Review builds show their checks, CI status and AI-review verdict.
  When nothing waits, it says so in one green line. Nothing is approved or deployed just by opening a row.
- **Now**: the run that is going (with its live log), builds and Claude tasks at work, agents queued for the run
  slot, and what comes up next. Under it, **Stack upkeep** counts the health alerts the Health doctor looks at and
  the stack's own improvement ideas: visible, but not waiting for you.
- **Latest from your agents**: a live feed of results, newest first and grouped by day. Every finished run shows its
  headline and the first lines of its report; tap it to read the whole result. Purchases, housekeeping results
  (inbox digest, phone cleanup, health doctor), deployed builds, Claude answers and event alerts are in it too. Filter
  with **Results**, **Shopping**, **Housekeeping** or **Code**.

Home updates in place while agents work, without redrawing the screen. To start something, type in the bar at the
top: Hermes answers, researches, or sets up a new agent for you. **New agent** and **New wiki** next to it open the
forms directly.

```try
label: Look at the Home screen
open: "#/"
note: Needs you and Now are at the top on a phone (on the right on a computer); the feed of results is below. Tap Results to see only what your own agents produced.
```

```try
label: Open the Stack page
open: "#/system"
note: Every service with a status dot, the machine's resources and the apps you can open.
```

## This guide keeps itself current

Parts of this guide are **live**: the diagram above, the service lists, versions, tools and skills come straight
from the running system. The **What's new** chapter follows every change made to the stack. And the stack's
automatic checks fail if a new feature is added without being documented here, so the guide can't quietly fall
behind.
