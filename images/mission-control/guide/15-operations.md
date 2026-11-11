---
title: Operating it from the PC
kicker: For the rare times you need a terminal
part: Under the hood
icon: tune
minutes: 6
summary: The handful of commands for setup, maintenance and recovery. Day to day, you won't need any of them.
views: []
---
Almost everything in this guide works from the app. A few things are deliberately only possible at the PC, in a
terminal in the `ai-stack` folder: anything that asks for a password, and setup and recovery. Every command
decrypts the secrets it needs for itself and never prints them.

## Everyday

| Command | What it does |
|---|---|
| `make up` / `make down` | start / stop the services (data is kept) |
| `make logs` | the last lines of every service's log |
| `make smoke` | wiring test: checks every connection, spends no tokens |
| `make probe-tools` | checks that tool calls keep their arguments through the model gateway (a few subscription calls) |
| `make check` | every automatic check, exactly as CI runs it |
| `make desk TOPIC=<slug>` | run a briefing now |
| `make digest` | send the morning digest now |
| `make wiki-rebuild MISSION=<slug>` | compile a mission's wiki again from all its results |
| `make understand REPO=<url>` | onboard a repository: the whole package, step by step |
| `make understand-dashboard REPO=<name>` | open its code map |
| `make facts REPO=<name>` | its facts now, sealed and without a model (they also follow its commits by themselves) |
| `make facts-image` | build the image behind them by hand (a deploy does it when `images/repointel` changes) |
| `make mailvault-deploy` | put the copy of your Gmail on the NAS, or update it; never touches the copy |
| `make mailvault-password` | type the mail copy's own Gmail app password; it goes straight to the NAS |
| `make ua-enrich REPO=<name>` | explain the files and functions its code map left as placeholders (carries on where it stopped) |

## One-time setup

| Command | What it does |
|---|---|
| `make claude-connect` | connect the builder's Claude Code engine once (you sign in and paste the token; it is saved encrypted) |
| `make chatgpt-login` | sign in to your ChatGPT subscription (you sign in, the stack never sees your password) |
| `make email-setup` | set up report e-mails with a Gmail app password |
| `make secrets-edit` | add or change provider keys (encrypted) |
| `make keys` | create each agent's gateway key |
| `make trust-keys` | make the secrets of the app's and n8n's trust boundary once: the step service's, each tool server's, n8n's webhooks' (encrypted, never shown) |
| `make pull-smoke-model` | download the tiny model the wiring test uses |
| `make hindsight-models` | download the memory models (new machine) |
| `make opencode-password` | show the OpenCode login in your terminal |

## Knowledge and quality

| Command | What it does |
|---|---|
| `make ingest-exports` | import mail and chat exports into the vault (offline) |
| `make curate` | run the weekly learning pass now |
| `make vault-check` | check the vault's structure (add `ARGS=--fix` to repair) |
| `make req` | check the stack's requirements and rewrite their readable list (`requirements/REQUIREMENTS.md`) |
| `make trial NAME=semver` | a trial in the background: a task with an answer key no agent sees, given like you would give it, scored, checked for copying; its report lands in the vault under trials/ |
| `make trial-check NAME=semver` | does a trial's answer key score its own reference fully (changes nothing) |
| `make journeys` | the journey checks now: a task followed to its result on replayed answers, a test item decided through the queue, every screen at 375 px on your data and with none, the newest e-mail on a phone, every make target dry-run (no model; nightly anyway) |
| `make retrieval` | measure how well search finds things |
| `make bench-gate` / `make bench` | the quality benchmark, quick or full |
| `make skill-approve NAME=<skill>` | approve a skill Hermes parked for review |
| `make skills-restore-from-git` | put Hermes' skills back as saved in git |
| `make forget TEXT="…"` | remove conversations containing a text from memory |

## Backups, versions, recovery

| Command | What it does |
|---|---|
| `make backup` | encrypted backup to the NAS now (also runs nightly) |
| `make restore-drill` | prove the newest backup restores (changes nothing) |
| `make restore` | put a backup back on this machine |
| `make upgrade-check` | list newer releases of the pinned components (changes nothing) |
| `make lock` | record the exact images that are running |
| `make deploy-testrepo` | deploy the TestRepo project to the NAS |
| `make ha-deploy` | deploy or upgrade Home Assistant on the NAS (its config and devices stay) |
| `make voice-deploy` | deploy or upgrade Hermes' voice on the NAS: speech to text and the voice, for Home Assistant only |
| `make tasks-gate` | check that the task intake writes a checkable plan for 20 sample tasks (starts nothing) |
| `make conductor-gate` | run a five-step test task on three kinds of agents and restart the runner in the middle; it must finish |
| `make publish-check` | build the public copy without your personal data, scan it and run its tests (pushes nothing) |
| `make publish` | the same, then push it to GitHub; only when it is clean (docs/PUBLISHING.md) |
| `make release TAG=vYYYY.MM.DD` | sign off the published copy with your own signing key: the tag a work deployment may update to |
| `make update TAG=vYYYY.MM.DD` | on a work deployment: check your signature on the tag, run every check on it, then deploy it |
| `make measure-change REPO=<repo> CASE=<n>` | one change done by one coder and by the team, side by side: tests, tokens, builds, minutes |
| `make egress-check` | on a deployment with an egress list: prove the outbound rule, and check that nothing off the list answers |

> [!note] Changes to the stack itself go through git: commit, push to Forgejo, the automatic checks run, then
> deploy. The builder does all of this for you, with your tap at the end.

## Memory

WSL has 10 of the PC's 16 GB of RAM and a 16 GB swap on the F: SSD: what idle services hold moves to disk instead of
crowding the work, which matters little because the stack mostly waits on model calls. Three services grow while idle
(qmd, Phoenix, Open WebUI); every night at 03:50, once nothing is running, they are restarted (their data is on disk)
and their memory before and after goes to `/srv/ai/state/recycle.jsonl` (`python3 ops/recycle.py` does it now). The
Stack page shows RAM and swap; the doctor warns when swap runs full.
