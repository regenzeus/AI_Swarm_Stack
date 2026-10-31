# ai-stack

A self-hosted, self-maintaining personal AI stack on one Windows 10 PC (WSL2, rootless Docker) with a Synology NAS
for git, CI, Home Assistant and backups. Everything model-related runs on **subscriptions only (ChatGPT through the
gateway, Claude for Claude Code): no paid model is configured**, so nothing can spend money (decided 2026-10-27;
total ever spent: $0.0032, all in tests).

You use it from your phone through **Mission Control** (an installable web app on the tailnet) and Telegram:
chat with your assistant (Hermes); run missions (daily briefings, long-term research tasks, event alerts, shopping);
browse the agents' wikis; study any codebase (code graph and code map) and let the builder change it with your
approval; let the AI phone and the Gmail connector work under your approvals; watch every agent's health, resources
and costs. Your Tailscale login is the only sign-in. The app has a built-in guide (Stack → Guide) that explains every
screen with examples you can try.

## Documents

| | |
|---|---|
| **What the stack shall do** (the source of truth for behaviour) | [requirements/](requirements/README.md), rendered in [REQUIREMENTS.md](requirements/REQUIREMENTS.md) |
| Status, findings and what is next | [the review of 30 October 2026](docs/REVIEW-2026-10-30.md), and the open findings in [requirements/findings.yaml](requirements/findings.yaml) |
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
  ts --> phx[Phoenix traces :8443]
  mc -- chat --> hermes[Hermes gateway<br/>profiles main, scout, curator, mission]
  mc -- requests inbox / state.json --> runner[ops/missions.py runner<br/>host, systemd]
  runner --> crew[the crew: 20 jobs<br/>health, memory, tests, phone, inbox …]
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
compose project `aistack`. The NAS (Synology DS923+, 192.168.1.80) runs Forgejo (git + CI) and Home Assistant,
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
| `phone`, `mail`, `browser`, `pricewatch` | The AI phone (ADB to the old S22), the Gmail connector, the scout's shop browser, the shopping price watch; each sealed by its own firewall | one target each |
| `openwebui`, `phoenix`, `postgres`, `ollama`, `pkgproxy`, `ci-runner` | Classic chat UI, traces, LiteLLM DB, smoke-test model, npm/PyPI proxy, Forgejo runner | as needed |

Host side (`ops/`, systemd user units in `ops/systemd/`): `missions.py` (the runner: missions, events, builds,
resources, the inbox), `crew.py` (the crew's 20 jobs and the health board), `builds.py` / `deploy.py` (builds and
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
| `make desk TOPIC=uranium` | run a briefing now |
| `make wiki-rebuild MISSION=slug` | compile a mission's wiki from all its results |
| `make email-setup` | one-time Gmail app password for report e-mails |
| `make understand REPO=<url>` | code graph + code map of a repository |
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
