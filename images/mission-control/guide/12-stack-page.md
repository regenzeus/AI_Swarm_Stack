---
title: "The Stack page: health, resources and costs"
kicker: Keeping an eye on things
part: Under the hood
icon: pulse
minutes: 5
summary: Everything about the machine in one place, from services and resources to scheduled jobs, backups, checks, skills and costs.
views: [system]
---
The **Stack** page is the control room's dashboard. Most of the time it's all green and you don't need it.
When something is off, this is where it shows.

## Tools

Every tool the stack runs on, at the top of the page: Home Assistant, the NAS, the router, Forgejo, Hermes admin,
Phoenix and the rest. Each card says where it opens (**anywhere** through your Tailscale login, or **home Wi-Fi**)
and has its main menus as buttons: Home Assistant's People, Integrations and Voice assistants are one tap away.
**Go to…** finds a menu by what you want (people, wifi, tokens, logs) and Mission Control's own pages too; Enter opens
the first match. Every link is opened each night; a broken one shows on the health board.

## Resources

The PC has 16 GB of memory, shared between Windows and the AI stack (which is capped at 10 GB). The resource
cards show Windows memory, the stack's memory, CPU and disk. Each service has a limit, so one runaway service can't
take down the rest.

```live
resources
```

## Services

Every part of the stack runs as its own service. Green means running, amber means running but unhealthy, red
means stopped. Services restart themselves after crashes and after the PC reboots.

When you start the PC, the stack comes online by itself in a few minutes; the top of this page says when it last did and
how long it took, and Telegram gets one line. Missions wait until it is up, then the ones the PC slept through run. The
nightly jobs catch up one after the other over the next two hours, so the first hour is busier than usual. If it is
still down after 10 minutes, one message names the cause.

```live
services
```

## Scheduled jobs

Besides missions, the stack runs its own maintenance on timers: nightly encrypted backups to the NAS (and a copy
to OneDrive), a weekly restore test that proves the backups work, vault indexing, memory review, the weekly
learning run that tidies the vault and wiki, skill syncing, and a monthly check for new versions.

## Checks (CI)

Every change to the stack's code is tested automatically on the NAS: script and code checks, configuration
checks and the unit tests. The latest result per repository:

```live
ci
```

## Skills

Hermes learns **skills**: reusable how-tos it writes for itself when it figures out a task. New skills are
reviewed before they're used, and all of them are saved in git.

```live
skills
```

## Costs

```live
costs
```

```try
label: Open the Stack page
open: "#/system"
note: Look at "Agents today" to see which agent did how much work, in calls and tokens.
```

## Outside agents (A2A)

Other agents on your tailnet (Claude on your laptop, a colleague's agent you trust) can give the stack a task over the
A2A protocol. It is **off** until you switch it on in **Outside agents**. **Add** names an agent and shows its token once:
give that agent the token and the card's address (`/.well-known/agent-card.json`). Every task it sends waits for your
**Start it** on Tasks (it shows where it came from), and it can read back only its own tasks and their answers.
**Revoke** stops a token at once. Nothing outside your tailnet can reach it.

