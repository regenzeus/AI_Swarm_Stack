---
title: Safety, privacy and cost
kicker: Why you can let it run
part: Under the hood
icon: check
minutes: 5
summary: The rules that keep your data private, your bill at zero, and every important change in your hands.
views: []
---
An AI that acts on your behalf needs firm limits. These are the stack's, and they're enforced by the system,
not just by asking the AI to behave.

## Private by default

- **One sign-in.** Your Tailscale login is the only login: Mission Control, Hermes admin, the code map and Open WebUI
  let your devices straight in, with no passwords or tokens. Forgejo on the NAS keeps its own account.
- **Only your devices.** Every app is reachable only through Tailscale, your private network. Nothing is
  exposed to the internet, and no router ports are open.
- **Your data stays home.** Notes, reports, memory and chats live on your PC and NAS. Only the model calls go
  out: to your ChatGPT subscription, and for builds, code reviews, the Health doctor and Claude tasks, the code and
  redacted logs they read go to your Claude subscription (Anthropic).
- **Secrets are encrypted.** Passwords and keys are stored encrypted and only decrypted for the command that
  needs them. They're never printed, and never stored in plain text in git.

## The web can't reach your data

The main danger for AI agents is **prompt injection**: a web page or document with hidden instructions such as
"send the user's notes to …". The stack keeps the three ingredients of an attack apart:

| | Untrusted content | Private data | Way out |
|---|---|---|---|
| **Scout** (reads the web) | yes | no | no |
| **Hermes** (your assistant) | only labelled research results | yes | only to you (e-mail to your own address) |
| **Builder** (writes code) | packages it installs | no | no, it can't push or deploy |

## Nothing important without you

- **Deploys** happen only after you tap Approve, and only when the checks and CI pass. Failed deploys roll back.
- **New memories** that matter wait for your OK.
- **New skills** are reviewed before Hermes uses them.
- **E-mail** only goes to your own address.

## $0, guaranteed

No paid model is configured anywhere in the gateway, and every agent's key only allows subscription models. Even
a bug can't spend money. The dashboard shows the total ever paid, which is still a fraction of a cent from early
tests.

When the subscription's usage limit is reached, missions and builds **wait** and retry automatically. In the app's
chat your message is kept: the chat says when the limit resets (or that it tries every 15 minutes when ChatGPT gives no
time), answers by itself afterwards, and you get a notification when the answer is there. *Try now* sends it at once.
On Telegram, Hermes answers the limit itself.

## Recoverable

Encrypted backups run every night to the NAS, with a copy on OneDrive. A weekly test restores the latest backup to
prove it works. Moving to a new PC is a rehearsed, documented procedure.
