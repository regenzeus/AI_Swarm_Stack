# ai-stack

**Your own team of AI agents, running at home on one PC and used from your phone.**

It chats with you, researches topics for weeks, writes briefings, watches shops and news for you, looks after its own
health, and improves its own code in a sandbox. It can use a spare Android phone and your Gmail. Anything that matters
waits for your tap. Every model runs on a flat-rate subscription (ChatGPT, and Claude for Claude Code), with no paid
model configured, so it can't run up a bill.

<table>
  <tr>
    <td width="25%"><img src="docs/screenshots/chat.jpg" alt="A chat with the assistant: an answer, its steps folded away, and a mission it started"></td>
    <td width="25%"><img src="docs/screenshots/chats.jpg" alt="The list of chats as a drawer, with New chat first and chats grouped by day"></td>
    <td width="25%"><img src="docs/screenshots/home.jpg" alt="Home: what needs you, a box to ask or give a task, and the AI phone"></td>
    <td width="25%"><img src="docs/screenshots/map.jpg" alt="A map of which agents work with which, with how often on each line"></td>
  </tr>
  <tr>
    <td><b>Chat</b>: it acts, and shows what it made</td>
    <td><b>Your chats</b>: swipe right for the list</td>
    <td><b>Home</b>: what needs you, and one box for anything else</td>
    <td><b>The agents</b>: who works with whom</td>
  </tr>
</table>

<sub>The chats and Home show demo data. The map shows a real week of runs, which holds only agent names and counts.</sub>

## What it does

- **Chat with an assistant that can act.** Attach pictures and documents. It knows your notes, starts missions, researches the web and e-mails you the result.
- **Missions.** Daily briefings, research that runs for weeks and builds its own linked wiki, alerts on filings, prices and news, and shopping watches. A purchase always waits for your tap.
- **A crew that runs the place.** Scheduled jobs check health, tidy memory, sort your inbox, run the tests and suggest improvements. You hear only what needs you.
- **Code.** Study any repository as a graph and a code map. Ask for a change in a sentence: a tester writes the tests first, a coder makes them pass, a breaker attacks the result, a program judges it, and nothing merges without your tap.
- **Hands in the real world, on a short leash.** An old phone, Gmail and Home Assistant, each behind its own firewall. The AI phone can never approve itself.
- **Your Windows PC, read-only.** The stack can ask Claude Code on Windows about your files, only in folders you list there. WSL still can't start anything on Windows.
- **Everything visible.** One record of every agent run, a map of who works with whom, and costs and resources per agent.
- **A memory you can read, that keeps itself.** Wikis with their sources, what it knows about you, what it knows about each repository, lessons, skills and each agent's journal, under one search. Every run is given the part its task needs within a budget, and you can see what it got and used. A memory agent keeps it tidy, splits what grows too big and turns repeated work into lessons and skills, each change with its Undo.

You use it from your phone through **Mission Control**, an installable web app on your private tailnet, and through
Telegram. Your Tailscale login is the only sign-in. A built-in guide (Stack → Guide) explains every screen with examples
you can try.

## Why not just use the Claude or ChatGPT app?

Use them if they do what you need. They take minutes to set up, need no PC of your own to look after, and are made by
the people who make the models. Both have become very good: you can steer work from your phone, schedule it and let it
run in their cloud. This stack runs **on top of the same subscriptions** and is for the things one vendor's app is not
built to do. Checked in November 2026 against the
[Claude Code](https://code.claude.com/docs/en/routines) and [Codex](https://learn.chatgpt.com/docs/automations) docs; these apps change fast.

| | Claude or Codex app | ai-stack |
|---|---|---|
| **Models** | One vendor's | Both together: ChatGPT chats and maps code, Claude Code does the hard code, and the other engine reviews a build where it can |
| **Between runs** | A scheduled run mostly starts fresh, and one on your computer needs it awake with the app open | One memory for every agent: your notes, a wiki per topic, long-term facts, each agent's journal. All plain files you own |
| **Who does the work** | One assistant and the helpers it starts | Agents (the cards in `config/agents.yaml`) with their own keys, tools and jobs, a shared ledger of the work, and weekly trials that measure them |
| **Real-world hands** | Your own computer and connected accounts | A spare phone, Gmail and Home Assistant, each behind its own firewall. The phone can never approve itself |
| **Your OK** | A prompt inside the session (Claude's Dispatch denies it after ten minutes) | One queue for every decision: builds, purchases, phone steps, mail. Nothing that matters happens without your tap |
| **What happened** | The session's history | One record of every run of every agent, a map of who works with whom, cost and resources per agent |
| **When it is yours** | The vendor decides what changes | MIT licensed, on your machine, pinned versions, nightly encrypted backups with a restore drill |

**Five things you can ask for**

1. *"Clone this repo, analyse it and tell me how we could use it."* It copies the code, draws its graph, ChatGPT writes a code map that explains every file, and Claude writes an analysis with a verdict. All of it stays searchable, so next month's question starts from there. A 177-file repository took 23 minutes, and the page showed each step.
2. *"Send me a short news briefing on copper every weekday at 7."* A desk reads its own sources every day, checks them, mails you the report and keeps growing a wiki on the topic, for weeks.
3. *"Tell me when this drops under 200 €."* A watch follows the price and offers, and asks you before anything is bought.
4. *"Free up space on my phone."* An agent on the spare phone looks, proposes what to remove, and does only what you approve there.
5. *"Why did last night's backup fail?"* An agent reads the real logs and run records. A fix goes to the builder's sandbox, the other engine reviews it, you tap to deploy, and a failed check rolls it back.

**What it costs you.** A Windows PC that stays on (16 GB is tight), a NAS for git and backups, and real time to set it up and keep it running: this is one person's setup, not a product. Your prompts still go to OpenAI and Anthropic, so the privacy gain is in what stays at home (your files, memory and keys), not in the model calls. And it depends on subscription access that the vendors can change.

## Does the swarm of coding agents earn its cost?

Measured by replaying real commits of [click](https://github.com/pallets/click): the agents get the commit's message and a snapshot without it, and a program scores the commit's own tests. Two fair cases so far, so read it as a first signal:

| Commit | One coder | Swarm | Swarm with a wiki |
|---|---|---|---|
| Help option order (102 tests) | 99, 224k tokens | 102, 746k | 102, 1,024k |
| Sentinel copying (10 tests) | 10, 343k | 10, 481k | 10, 1,052k |

The swarm stopped three regressions the one coder caused, and tied on the small change, at 1.4 to 3.3 times its tokens. The wiki changed no score here. Most of its extra tokens came from extra fix rounds, which vary from run to run. A third case was dropped because its one-line message left out what its tests required.

## How it's built

It runs on one Windows 10 PC (WSL2, rootless Docker), with a Synology NAS for git, CI, Home Assistant and backups.

Most of the work here went into keeping agents honest and safe:

- Every behaviour is a [requirement](requirements/README.md) claimed by a test, and each change must pass the full check before it lands.
- Each agent has its own key and tool grants, web content stays in an isolated scout, and no secrets reach git except encrypted ones.
- Nothing you read is cut off without saying so, and agent prompts are versioned and replay-tested.
- Backups are encrypted every night and proven by a weekly restore drill, and moving to a new PC is rehearsed.

This is one person's real setup, published as a reference, not an installer you can run in a minute. To build your own,
start with [NEW-MACHINE.md](NEW-MACHINE.md). This public copy holds no personal data: see [docs/PUBLISHING.md](docs/PUBLISHING.md).

## Documents

| | |
|---|---|
| **What the stack shall do** (the source of truth for behaviour) | [requirements/](requirements/README.md), rendered in [REQUIREMENTS.md](requirements/REQUIREMENTS.md) |
| Where the swarm goes next | [docs/SWARM-ROADMAP.md](docs/SWARM-ROADMAP.md), its requirements in [requirements/tasks.yaml](requirements/tasks.yaml) |
| Status, findings and what is next | [the review of 10 November 2026](docs/REVIEW-2026-11-10.md) (the earlier ones are in [docs/README.md](docs/README.md)), and the open findings in [requirements/findings.yaml](requirements/findings.yaml) |
| Every other document, current and historical | [docs/README.md](docs/README.md) |
| Mission Control: how the app and the runner talk | [docs/MISSION-CONTROL.md](docs/MISSION-CONTROL.md), its HTTP API in [docs/API.md](docs/API.md) |
| Security model and accepted risks | [docs/SECURITY.md](docs/SECURITY.md) |
| The public copy on GitHub, without personal data | [docs/PUBLISHING.md](docs/PUBLISHING.md); MIT licensed ([LICENSE](LICENSE)) |
| Rules for coding agents working on this repo | [AGENTS.md](AGENTS.md), and an `AGENTS.md` in every directory |
| Upgrades (monthly window) and a move to a new PC (rehearsed) | [UPGRADE.md](UPGRADE.md), [NEW-MACHINE.md](NEW-MACHINE.md) |

## Architecture

```mermaid
flowchart LR
  phone[Phone / PC browser] -- tailnet only --> ts[tailscale serve on Windows]
  tg[Telegram] --> hermes
  ts --> mc[Mission Control :8447]
  ts --> owui[Open WebUI :443]
  ts --> oc[OpenCode :8445]
  ts --> ua[Code map :8446]
  ts --> hd[Hermes admin :8448]
  ts --> phx[Phoenix traces, inside the app]
  mc -- chat --> hermes[Hermes gateway<br/>profiles main, scout, curator, mission]
  mc -- requests inbox / state.json --> runner[ops/missions.py runner<br/>host, systemd]
  runner --> crew[the crew's scheduled jobs<br/>health, memory, tests, phone, inbox …]
  runner -- docker exec / run --> desk[Topic Desk]
  runner --> builder[Builder sandbox<br/>Hermes or Claude Code]
  runner -- git push --> forgejo[(Forgejo on NAS + CI)]
  runner --> phonesvc[AI phone · Gmail · price watch<br/>each behind its own firewall]
  hermes --> litellm[LiteLLM gateway<br/>per-agent keys, MCP]
  desk --> litellm
  builder --> litellm
  litellm -- ChatGPT subscription --> openai[(OpenAI)]
  litellm -- MCP --> qmd[qmd vault search]
  litellm -- MCP --> research[research → scout → fetch]
  litellm -- MCP --> mcmcp[Mission Control tools]
  litellm -- MCP --> graphify[Graphify code graph]
  litellm -- MCP --> swarm[Swarm Ledger<br/>artifacts, ideas, messages]
  hermes --> hindsight[Hindsight long-term memory<br/>+ pgvector]
  qmd --> vault[(Obsidian vault<br/>C:\AI\vault)]
  mc -- House --> ha[(Home Assistant on the NAS)]
```

**Hosts.** Windows 10 Pro (i7-7700K, 16 GB RAM) runs WSL2 `Ubuntu-24.04` (10 GB cap) with rootless Docker,
compose project `aistack`. The NAS runs Forgejo (git + CI) and Home Assistant,
and stores the encrypted nightly backups. Windows tasks keep WSL alive, heal the WSL disk, copy backups to OneDrive,
sync Bitbucket and probe resources.

## Components

| Service | What it does | Network reach |
|---|---|---|
| `litellm` | Model gateway: per-agent virtual keys (`ops/keys.sh`), subscription models `gpt-sub` / `gpt-sub-fast`, MCP gateway with per-key tool grants, Phoenix traces | internet (OpenAI), internal |
| `hermes` | The assistant (Hermes Agent 0.22.5): main profile (chat, Telegram, API), `scout` (web research), `curator` (vault wiki), `mission` (mission runs) | LiteLLM, Telegram, memory |
| `hermes-dashboard` | Hermes' own admin UI (skills, cron, logs, sessions) | internal |
| `mission-control` | The app (Starlette + vanilla JS PWA), its MCP tools and the run record ([API](docs/API.md)) | Hermes, LiteLLM, push services |
| `builder` | Sandboxed coding agent (Hermes or Claude Code, with shell and files) for build assignments | LiteLLM, npm/PyPI proxy only |
| `qmd` | Hybrid search (BM25 + vectors) over vault, topics, specs, code digests, mail/chats | none |
| `hindsight` + `hindsight-db` | Long-term memory from every conversation (local multilingual models) | memory network only |
| `research`, `fetch` | Web research tool: privacy guard → scout agent → isolated page reader (PDF capable, LAN blocked) | internet (fetch only) |
| `graphify`, `opencode`, `ua-viewer` | Code graph MCP, coding UI, Understand Anything code map | internal / package proxy |
| `gate-hermes-dashboard` (+ the code map's gate sidecar) | Single sign-in: admits only requests carrying your Tailscale login (`config/gate`) | shares the app's network namespace |
| `swarm` | The agent swarm's Ledger: every agent-produced artifact, idea and message with its history and lifecycle | no port, no internet |
| `phone`, `mail`, `browser`, `pricewatch` | The AI phone (ADB to a spare phone), the Gmail connector, the scout's shop browser, the shopping price watch; each sealed by its own firewall | one target each |
| `openwebui`, `phoenix`, `postgres`, `ollama`, `pkgproxy`, `ci-runner` | Classic chat UI, traces, LiteLLM DB, smoke-test model, npm/PyPI proxy, Forgejo runner | as needed |

Host side (`ops/`, systemd user units in `ops/systemd/`): `missions.py` (the runner: missions, events, builds,
resources, the inbox), `crew.py` (the crew's jobs and the health board), `builds.py` / `deploy.py` (builds and
deploys after your tap), `land.sh` (how a supervised session lands its work), `shopping.py`, `librarian.py`,
`desk.sh`, `backup.sh` / `restore.sh` (nightly backup, weekly drill), `vault-ingest.sh`, `graphify-sync.sh`,
`digest.py`, `upgrade_check.py`. Windows tasks are in `ops/windows/`.

## Repository layout

```
compose/        core.yaml (LiteLLM, Postgres, Phoenix, Ollama), apps.yaml (everything else), rehearsal.yaml
config/         litellm/config.yaml, hermes/configure*.sh (one script per Hermes profile), agents.yaml (the agent registry)
images/         one directory per custom image (Dockerfile + code); mission-control/ is the app and its guide
ops/            host side: runner, crew, builds and deploys, desk, backups, keys, checks, systemd units, Windows scripts
prompts/        every agent prompt as a versioned, replay-tested file (MEM-11)
requirements/   the requirements, decisions and findings (YAML), checked by ops/req.py and rendered to REQUIREMENTS.md
tests/          the unit tests (all fakes, no services); every test is claimed by a requirement
secrets/        sops + age encrypted: secrets.enc.yaml (providers, tokens), agent-keys.enc.yaml (virtual keys)
spec/           the requirements checker (ingest, extract, link, judge)
eval/           frozen benchmark (bench-v1.yaml, FROZEN.sha256) and retrieval eval
nas/            what runs on the NAS (Forgejo, Home Assistant)
smoke/          wiring test (no tokens spent)
vault-template/ AGENTS.md contract of the Obsidian vault
```

## Operating it

Everything runs by itself (timers, the runner, the crew, Windows tasks). Day to day you use Mission Control.
From a terminal (`grep '##' Makefile` lists every target; secrets are decrypted per command, never printed):

| Command | |
|---|---|
| `make up` / `make down` / `make ps` / `make logs` | start, stop, status, logs |
| `make check` | every check CI and each landing run (below) |
| `make smoke` | wiring test, no tokens spent |
| `make keys` / `python3 ops/update-keys.py` | create / update per-agent keys from `ops/keys.sh` |
| `make backup` / `make restore-drill` / `make restore` | encrypted backup to the NAS, prove it restores, restore |
| `make lock` | record which image every container runs into `versions.lock` |
| `make desk TOPIC=copper` | run a briefing now |
| `make wiki-rebuild MISSION=slug` | compile a mission's wiki from all its results |
| `make email-setup` | one-time Gmail app password for report e-mails |
| `make understand REPO=<url>` | onboard a repository: code graph, code map, search index, written analysis |
| `make bench-gate` / `make bench` | frozen quality benchmark (subscription only) |
| `make upgrade-check` | newer releases of pinned components (changes nothing) |

**Checks** (`ops/check.sh`, the same in CI, in the builder and in every landing): shellcheck, ruff, the app's
scripts (syntax and undefined names), YAML, Semgrep with the repo's own rules, the frozen benchmark, compose
validity, the agent registry, the prompts, the truncation rule, the requirements (fields, links, every test claimed,
every source file traced) and the unit tests.

**Changes.** The builder's changes go through review and tap-to-deploy (`ops/builds.py`, `ops/deploy.py`). A
supervised session lands with `bash ops/land.sh <branch> "<your approval>"`: the checks on the exact commit, the
deploy, the runner restart and an activity event.

## Principles

- **$0 running cost.** Subscription models only; when ChatGPT pauses the stack (usage limit), missions and builds
  wait and resume by themselves.
- **No secrets in git** except sops-encrypted files; agents never hold the NAS key or SSH keys.
- **Least privilege per agent**: own LiteLLM key and tool grants per profile; web content only in the isolated
  scout; the builder codes in a sandbox and cannot deploy; nothing reaches production without a human tap.
- **You decide.** Agents propose; purchases, phone and Gmail actions, sensitive memories and every deploy wait for
  your approval, and the AI phone can never approve itself.
- **Everything observable**: one run record for every agent, a health board that raises only what needs you, and
  nothing you read is cut without saying so.
- **Everything recoverable**: nightly encrypted backups (NAS + OneDrive), a weekly restore drill the health board
  watches, a rehearsed new-PC path.
- **Pinned versions**, upgraded only in a monthly window (`UPGRADE.md`); the board notes a container that runs
  another build than its tag.
