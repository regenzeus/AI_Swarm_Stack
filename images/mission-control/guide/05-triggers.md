---
title: Event triggers
kicker: React the moment something happens
part: Everyday use
icon: radar
minutes: 4
summary: Missions can start on their own when a company files with the SEC, a price jumps, or a story breaks.
views: []
---
Schedules are good for routine. Triggers are for surprises. Give a mission one or more triggers, and the stack
checks them **every ten minutes**. When one fires, the mission runs right away and you get an alert
explaining what happened and why it matters.

## Three kinds of triggers

| Trigger | Fires when | Example |
|---|---|---|
| **SEC filing** | a company files a new form (optionally only certain forms, like 8-K or 10-Q) | ASPI files an 8-K |
| **Price move** | a symbol moves more than a set percentage in a day | CCJ moves ±8 % |
| **News** | a new article matches a search | "ASP Isotopes" in the news |

The first check only records what already exists (a *baseline*), so adding a trigger never floods you with
old filings. After that, each new event fires once.

```try
label: Add a price alert
chat: Alert me if Cameco (CCJ) moves more than 8 % in a day. Attach it to my uranium mission.
note: Hermes calls mission_set_triggers. The mission card then shows a trigger count, and the Home screen says how many triggers are being watched.
```

```try
label: Watch SEC filings
chat: Tell me whenever ASP Isotopes files an 8-K or 10-Q with the SEC, with a short analysis of the filing.
note: The trigger watches the SEC's filing feed. When a filing arrives, the alert run reads the filing itself (PDFs too).
```

## What an alert looks like

An event run is marked with ⚡ in the activity feed and the mission's runs. Briefings write a short **alert**
(saved under `topics/<mission>/alerts/`). Tasks fold the event into their ongoing work. Delivery works the same
as for scheduled runs: push, Telegram, or e-mail.

> [!tip] To remove triggers, say "Remove the price alert from my uranium mission". To see them all, open the
> mission's Overview.
