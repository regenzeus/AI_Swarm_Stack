---
title: Push, Telegram and e-mail
kicker: Getting results to you
part: Everyday use
icon: bell
minutes: 4
summary: Choose how each mission reaches you. A push to your phone, a Telegram message with buttons, or a designed e-mail.
views: []
---
Each mission has a **deliver** setting with one or more channels. You pick them when creating the mission
and can change them any time ("send my copper briefing by e-mail too").

| Channel | What you get |
|---|---|
| **App** (push) | a notification on your phone or PC. Tap it to open the result in {{APP_NAME}} |
| **Telegram** | a summary message with buttons that open the report, the mission and the wiki in the app |
| **E-mail** | a designed HTML report in your inbox, with sources, readable on any device |

A briefing that found no news is not sent by Telegram or e-mail. It still appears in the app, and the next briefing
that has news says which days found nothing ("nothing new on 30 Oct").

## What reaches you, and when

Everything the stack tells you, on Telegram or as a push, goes through one path with your settings, under
**Stack → Settings → Notifications**:

- **Per kind of message, per channel.** Results, event alerts, agent health, builds, the swarm and stack upkeep each
  have a Telegram and a Push switch. Approvals (the AI phone, Gmail, purchases) always reach you: they expire when
  nobody sees them.
- **Quiet hours.** Between the two times you set, only approvals reach you. The Telegram messages wait and arrive as
  one message when the quiet hours end; the activity feed in the app still shows everything at once.
- **Once is enough.** The same health issue or failure is not sent again within a day.
- **What was sent.** Under the settings, *What the stack sent lately* lists each message with its channel and what
  happened to it: sent, held for the quiet hours, off by your setting, or a repeat that was not sent.

```try
label: Set quiet hours
open: "#/system?tab=settings"
note: Under "Notifications", tick "Quiet hours", set the times, and tap Save.
```

## Push notifications

Push works once the app is installed on the device and you switch it on under **Stack → Settings → This device**.
You'll get finished runs, triggered events, new tasks and errors.

```try
label: Switch on push and send a test
open: "#/system?tab=settings"
note: Under "This device", switch on Push notifications, then tap "Send a test".
```

## E-mail

E-mail goes only to your own address. That's enforced by the stack, so no agent can e-mail anyone else.

```try
label: E-mail yourself something
chat: E-mail me a one-page summary of everything my missions found this week.
note: Hermes writes the summary and calls send_email. It arrives as a designed report.
```

## Telegram

Hermes is also on Telegram. You can chat with it there like in the app, and briefings arrive with buttons that
open the full report in {{APP_NAME}}. A **morning digest** of the night's results is sent there every morning.
