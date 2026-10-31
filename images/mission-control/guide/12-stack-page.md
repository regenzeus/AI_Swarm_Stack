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
