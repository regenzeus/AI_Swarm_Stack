---
title: "The Stack page: health, costs, tools and connections"
kicker: Keeping an eye on things
part: Under the hood
icon: pulse
minutes: 5
summary: The machine itself in one place, one part at a time - its health, what it costs, the tools it runs on and what it is connected to - plus your settings.
views: [system]
---
The **Stack** page is the control room's dashboard. Most of the time it's all green and you don't need it.
When something is off, this is where it shows.

It has five parts, one at a time, and opens on the one you used last: **Health**, **Costs**, **Tools**,
**Connections** and **Settings**. The line under the title says how the stack is doing whichever part is open. Beside
the title, **Guide** opens this guide and **Files** what your tasks made. **Health** holds the resources, the services,
the scheduled jobs and the checks.

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
how long it took, and Telegram gets one line. Until the runner is up, the app says **The stack is starting**, with about
how long it took last time; if the runner stops later it says **The runner stopped** and how long ago, and if it never
came up, **The runner did not start**. **Not connected** means only that this device gets no answer from the app:
usually Tailscale is off on the device, or the PC sleeps. Jobs wait until it is up. The backup and the restore drill the PC slept through catch up one after the other; other
jobs run at their next time (n8n starts them and does not catch up a time the PC was off).
If it is still down after 10 minutes, one message names the cause.

```live
services
```

## Scheduled jobs

Besides your tasks, the stack runs its own maintenance on timers: nightly encrypted backups to the NAS (and a copy
to OneDrive), a weekly restore test that proves the backups work, vault indexing, memory review, the weekly
learning run that tidies the vault and wiki, skill syncing, and a monthly check for new versions. The last backup and
its restore test are at the top of Health.

## Checks (CI)

Every change to the stack's code is tested automatically on the NAS: script and code checks, configuration
checks and the unit tests. The latest result per repository:

```live
ci
```

## Costs

What was paid today and in 30 days, the credit used, and what the subscriptions (ChatGPT, Claude) carried in the last
5 and 24 hours, with whether one is at its limit. **Agents today** shows which agent did how much work, in calls and
tokens; **The agents, day by day** is their history for up to a year (the Telemetry chapter).

```live
costs
```

```try
label: Open the costs
open: "#/system?tab=costs"
note: Look at "Agents today" to see which agent did how much work, in calls and tokens.
```

## Tools

Every tool the stack runs on: Home Assistant, the NAS, the router, Forgejo, Hermes admin, Phoenix and the rest.
Each card says where it opens (**anywhere** through your Tailscale login, or **home Wi-Fi**) and has its main menus as
buttons: Home Assistant's People, Integrations and Voice assistants are one tap away. **Go to…** finds a menu by what
you want (people, wifi, tokens, logs) and {{APP_NAME}}'s own pages too; Enter opens the first match. Every link is
opened each night; a broken one shows on the health board. The AI phone's page is one tap away at the top.

## Connections

**Gmail** with its time-limited grants and what it did (the Connections chapter), **Outside agents** and **Packs and
trackers** (the Workflows chapter).

## Outside agents (A2A)

Other agents on your tailnet (Claude on your laptop, a colleague's agent you trust) can give the stack a task over the
A2A protocol. It is **off** until you switch it on. **Add** names an agent and shows its token once: give that agent
the token and the card's address (`/.well-known/agent-card.json`). Every task it sends waits for your **Start it** on
Tasks (it shows where it came from), and it can read back only its own tasks and their answers. **Revoke** stops a
token at once. Nothing outside your tailnet can reach it.

## Settings

The theme, the page the app opens on, your notifications with their quiet hours, and this device (installing the app,
push). The Delivery chapter has the details.

```try
label: Open the Stack page
open: "#/system"
note: The line under the title says how the stack is; each part opens with one tap.
```
