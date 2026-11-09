---
title: "Connections: your apps, only while you allow it"
kicker: Gmail first, more apps later
part: Everyday use
icon: news
minutes: 4
summary: Let agents search, read, sort and clean up your Gmail, for a time you choose, with Trash only and an undo.
views: [system, mail]
---
Agents can work with your apps through **connections**. Gmail is the first. You decide what they may do and for how
long; without a grant, every mail tool refuses and tells the agent to ask you.

## What you can grant

On the **Stack** page under **Connections** (or right on a mission that needs it):

- **read**: search and read your mail
- **organize**: add labels, archive, mark read or unread
- **trash**: move mail to Gmail's Trash

Each for **1 hour**, **8 hours** or **until you revoke it**. *Revoke* stops it at once.

```try
label: A spam clean-up mission
chat: Make a one-off mission that finds spam and newsletters I never open in my Gmail, shows me a summary by sender, and after my OK moves them to Trash. It needs gmail:read and gmail:trash.
note: The mission page then shows "Needs access" with grant buttons. Grant read and trash, run it, and confirm the first batch.
```

## What can never happen

- **Nothing is deleted for good.** Mail goes to Trash only; Gmail empties it after 30 days. Every batch can be undone
  (the agent has an undo tool, and the batch number is in the log).
- **The first Trash batch waits for your OK**: {{APP_NAME}} and Telegram show how many mails, from whom, a sample
  of subjects, and the reason. Later batches under the same grant go without asking.
- **Bank, payment, security alerts, password resets and verification codes** are never archived or trashed.
- **No sending, forwarding, filters or settings**: the connection simply has no such tools. (E-mailing you results
  stays a separate tool that only writes to you.)
- **Mails are untrusted**: a mail that tries to give the agent orders is treated as text.
- Everything the connection does is logged: on the Stack page, and in the mission run's **Log**.

> [!note] More apps follow the same pattern: a sealed connector, scopes you grant for a time, a log.

## Your mail

**Your mail** (a link on the Gmail card) shows two things, made from the headers of your mail alone. No message text is read.

- **The copy on the NAS.** Every mail as a file, kept current every 15 minutes, one way: nothing here can change Gmail, and a mail you delete in Gmail stays on the NAS, marked as gone. The first copy takes days, because Google limits downloads to 2,500 MB a day and the copy stays under it. It uses an app password of its own, which you can revoke alone.
- **Who writes to you.** One line per sender: how many mails, how many unread, how much space, whether it is a mailing list, and whether you ever wrote back.

The **Postmaster** files the stack's own mail under the label **AI Stack**, out of the inbox. It knows that mail by its exact sender, so what you mail yourself stays where it is. It removes nothing.
