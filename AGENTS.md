# Working on this repo (for coding agents: the builder, OpenCode, Claude, and humans)

This repo is a self-hosted personal AI stack (one Windows PC with WSL2 + rootless Docker, a Synology NAS for git,
CI and backups). It is developed mostly by AI agents, so it is organised to be read by them: **every directory has
an `AGENTS.md`** that says what lives there, how it is built and checked, and the rules for changing it.

**Before you change anything:** read this file, then the `AGENTS.md` of every directory you will touch, then the
docs it points to. `README.md` is the product overview; `docs/` holds architecture, security and status.

## Repository map

| Path | What it is | Guide |
|---|---|---|
| `compose/` | Docker Compose: every service, network, volume and limit | [compose/AGENTS.md](compose/AGENTS.md) |
| `config/` | Configuration applied to running services | [config/AGENTS.md](config/AGENTS.md) |
| `config/hermes/` | One idempotent script per Hermes profile | [config/hermes/AGENTS.md](config/hermes/AGENTS.md) |
| `config/litellm/` | The model gateway: models, routing, MCP servers | [config/litellm/AGENTS.md](config/litellm/AGENTS.md) |
| `prompts/` | Every agent's prompts, one file per agent; each change replay-tested | [prompts/AGENTS.md](prompts/AGENTS.md) |
| `config/skills/` | Pinned methods for the code roles, off unless a run asks | [config/skills/AGENTS.md](config/skills/AGENTS.md) |
| `config/gate/` | Single sign-in: the tailnet gates in front of apps with their own login | [config/gate/AGENTS.md](config/gate/AGENTS.md) |
| `images/` | One directory per custom container image | [images/AGENTS.md](images/AGENTS.md) |
| `images/mission-control/` | The app (API, MCP tools, web front end, in-app guide) | [images/mission-control/AGENTS.md](images/mission-control/AGENTS.md) |
| `images/mission-control/web/` | Front end: vanilla JS PWA, no build step | [images/mission-control/web/AGENTS.md](images/mission-control/web/AGENTS.md) |
| `images/mission-control/guide/` | The in-app guide's chapters | [images/mission-control/guide/AGENTS.md](images/mission-control/guide/AGENTS.md) |
| `images/desk/` | Topic Desk: daily briefings | [images/desk/AGENTS.md](images/desk/AGENTS.md) |
| `images/research/`, `images/fetch/` | Web research tool and the isolated page reader | [images/research/AGENTS.md](images/research/AGENTS.md), [images/fetch/AGENTS.md](images/fetch/AGENTS.md) |
| `images/browser/` | The scout's browser for shops and prices (only looks) | [images/browser/AGENTS.md](images/browser/AGENTS.md) |
| `images/builder/` | The coding sandbox | [images/builder/AGENTS.md](images/builder/AGENTS.md) |
| `images/phone/` | The AI phone: Hermes acts on the old test phone, with approvals, block list and Stop | [images/phone/AGENTS.md](images/phone/AGENTS.md) |
| `images/pricewatch/` | changedetection.io, sealed: the shopping agents' price watch | [images/pricewatch/AGENTS.md](images/pricewatch/AGENTS.md) |
| `images/swarm/` | The Swarm service: the agent swarm's Ledger (artifacts, history, lifecycle) | [images/swarm/AGENTS.md](images/swarm/AGENTS.md) |
| `images/mail/` | The Gmail connector: search, read, organize, Trash for the agents, only while the owner grants it | [images/mail/AGENTS.md](images/mail/AGENTS.md) |
| other images | the patched model gateway, Hermes, vault search, code graph, OpenCode, package proxy, port forwarder, one-shot tools, CI runner | [litellm (patched)](images/litellm/AGENTS.md), [hermes](images/hermes/AGENTS.md), [qmd](images/qmd/AGENTS.md), [graphify](images/graphify/AGENTS.md), [opencode](images/opencode/AGENTS.md), [pkgproxy](images/pkgproxy/AGENTS.md), [portfwd](images/portfwd/AGENTS.md), [tools](images/tools/AGENTS.md), [ci-runner](images/ci-runner/AGENTS.md) |
| `ops/` | Host-side operations: Mission Control runner, deploy, backups, keys, jobs | [ops/AGENTS.md](ops/AGENTS.md) |
| `ops/systemd/` | systemd user units and timers | [ops/systemd/AGENTS.md](ops/systemd/AGENTS.md) |
| `ops/windows/` | PowerShell for the Windows host | [ops/windows/AGENTS.md](ops/windows/AGENTS.md) |
| `ops/swarm-probes/` | The agent swarm's phase 0 proofs, re-runnable after upgrades | [ops/swarm-probes/AGENTS.md](ops/swarm-probes/AGENTS.md) |
| `tests/` | Unit tests (pytest, all fakes) and docs-coverage tests | [tests/AGENTS.md](tests/AGENTS.md) |
| `.forgejo/workflows/` | CI | [.forgejo/workflows/AGENTS.md](.forgejo/workflows/AGENTS.md) |
| `docs/` | Architecture, security model, reviews | [docs/AGENTS.md](docs/AGENTS.md) |
| `docs/screenshots/` | The public page's pictures, never of real data | [docs/screenshots/AGENTS.md](docs/screenshots/AGENTS.md) |
| `eval/` | Frozen benchmark and retrieval evaluation | [eval/AGENTS.md](eval/AGENTS.md) |
| `eval/trials/` | Trials: tasks with an answer key no agent sees, scored and audited (docs/SWARM-TRIALS.md) | [eval/trials/AGENTS.md](eval/trials/AGENTS.md) |
| `requirements/` | What the stack must do: needs, constraints, decisions, requirements, findings (contradictions) | [requirements/AGENTS.md](requirements/AGENTS.md) |
| `spec/` | Requirements-checker pilot (specs of other projects) | [spec/AGENTS.md](spec/AGENTS.md) |
| `smoke/` | Wiring test, no tokens spent | [smoke/AGENTS.md](smoke/AGENTS.md) |
| `converters/` | Mail and chat export conversion | [converters/AGENTS.md](converters/AGENTS.md) |
| `nas/` | What runs on the NAS (Forgejo, Home Assistant) | [nas/AGENTS.md](nas/AGENTS.md) |
| `nas/homeassistant/` | Home Assistant on the NAS: the House (Echos, lights, plugs) | [nas/homeassistant/AGENTS.md](nas/homeassistant/AGENTS.md) |
| `nas/mailvault/` | The copy of Gmail on the NAS: one way, read-only | [nas/mailvault/AGENTS.md](nas/mailvault/AGENTS.md) |
| `nas/voice/` | Hermes' voice on the NAS: speech to text and Piper for Home Assistant | [nas/voice/AGENTS.md](nas/voice/AGENTS.md) |
| `secrets/` | sops-encrypted secrets: never read or edit | [secrets/AGENTS.md](secrets/AGENTS.md) |
| `vault-template/` | The Obsidian vault's own contract (copied into the vault) | [vault-template/README.md](vault-template/README.md) |
| root files | `Makefile` (every operation), `versions.env` (pins; this deployment's hosts and paths are in `config/deployment.env`), `versions.lock` (digests), `README.md`, `NEW-MACHINE.md`, `UPGRADE.md` | this file |

## How to work: the loop

1. **Understand.** Read the area's requirements (`requirements/REQUIREMENTS.md`, or `python3 ops/req.py show <id>`)
   and the guides above for the area. Find the existing pattern for what you want to do and
   copy it. This repo rewards consistency over cleverness.
2. **Plan small.** One logical change at a time. If a change needs a new service, permission, network path or
   secret, it is a design change: describe it in the commit or ask first.
3. **Change.** Follow the conventions below and the directory's `AGENTS.md`.
4. **Check.** `make check` (or `bash ops/check.sh` where the tools are installed). It is exactly what CI runs.
5. **Document in the same change.** Update the directory's `AGENTS.md` if its structure or rules changed, the
   in-app guide if users see the change, `docs/` if architecture or security changed, and `README.md` if the
   component list changed.
6. **Commit.** See Commits below.

### Definition of done

- [ ] `make check` prints `ALL CHECKS PASSED`
- [ ] New or changed behaviour has its requirement in `requirements/` updated in the same change (statement, status,
      `verify`, `trace`; `python3 ops/req.py render`), and every new test is claimed by one (`make check` enforces it)
- [ ] New behaviour has a unit test in `tests/` (runner, builds, triggers, app API: there is a pattern for each)
- [ ] A user-visible feature has a paragraph and a "Try it" example in the guide (`tests/test_guide.py` enforces
      tools, screens and `make` targets)
- [ ] New directory → it has an `AGENTS.md` and a row in the map above (`tests/test_repo_docs.py` enforces both)
- [ ] Every new file starts with a header comment that says what it does and how it is run
- [ ] No secret, token, password or personal data in the diff
- [ ] Versions pinned (images in `versions.env` or the Dockerfile, packages with `==`)

## Conventions

- **Style follows the file you are in.** Python: stdlib first, short docstrings that say *why*, comments only where
  the neighbours have them; shell: bash with `set -euo pipefail` where the file has it. No new frameworks.
- **File headers.** Every file starts with a docstring or comment block: what it does, how it is run, what it
  must never do. Keep it true when you change the file.
- **English everywhere**: code, comments, UI text, docs, commit messages.
- **Names**: Python files `snake_case.py`, shell scripts `kebab-case.sh`, one Make target per operation
  (`name:  ## help text`), compose services lowercase-with-dashes.
- **Idempotent operations.** Scripts can run twice without harm (configure scripts, keys, deploy).
- **Configuration through the environment.** Secrets reach code only as environment variables, decrypted by sops
  per command (`make`, systemd units). Never read `secrets/`, `.env` files or `*.enc.yaml`.
- **Pinned versions** everywhere. Upgrades only through `UPGRADE.md` (monthly window).
- **Least privilege.** Each agent has its own LiteLLM key with its own models, budget and tools (`ops/keys.sh`);
  each container gets only the networks it needs.

## Truncation (the owner's rule, DEC-27)

Do not cut text by default. Coding agents cut text by reflex (`[:200]`, `.slice(0, 500)`, `| tail -20`, `limit 20`),
and here such a cut is usually a bug: a model takes the start for the whole (FND-100), a wiki compile wrote over the
parts of a page it was never shown (FND-103), a report past a `tail` vanished. Shortening is a decision, and it needs a
reason. **Never cut silently, and never cut without a reason.**

- **First ask whether the cap is needed at all.** Most are not: a list of 3 chats needs no `[:300]`, a page's sources
  need no `[-30:]`. Remove an unneeded cap rather than justify it.
- **Never cut what the owner reads.** That covers app pages, Telegram, push and e-mail, the activity feed, health
  alerts, error messages, logs shown in the app, Ledger text (bodies, evidence, reasons, messages), reviews and build
  output.
  - Text wraps: `.wrap`, `overflow-wrap: anywhere`. There is no `text-overflow: ellipsis` and no `line-clamp`.
  - Long text scrolls, or folds behind a visible "Show all".
- **Never cut what the owner types, or a command.** Over a real limit, refuse it and name the limit: `textcap.limit()`
  or `limit_items()`, for example "the description is 21,034 characters; the limit is 20,000". Never store or act on
  part of it. The same holds for a command another agent sends (an Alexa command, a text to say aloud).
- **A cut someone reads shows itself**: a person, or a model in a prompt. Use the `textcap` helpers (a copy sits next
  to the code of every image that uses them; `app.js` has `clipped()` and `moreOf()`):
  - `cut()` / `tail()`: "[… N more characters cut …]", and where it helps, where the whole text is;
  - `fit()`: the same within an outside hard limit (a push body, a span attribute, a question limit);
  - `bounded_json()`: cut JSON that still parses;
  - `more()`: a list of lines that ends with "(… and N more)";
  - `first()`: a list another program or model sent, bounded by the limit its prompt names, that says on stderr what
    it left out.
  A raw slice is allowed only where nobody reads the result as a whole: `id`, `parse`, `rotate`, a URL or a query
  (`api`, where a marker would break the value), or a `list` that says how many more there are next to it.
- **A model's answer that stopped at its output limit is never used as whole.** Read every chat-completions answer
  with `textcap.answer()`, which refuses a `finish_reason` of "length". A Claude Code run that stopped at its turn
  limit (`error_max_turns`) is no answer either (`builds.claude_text()`). The chat says so under the answer.
- **Name the reason on the line:** `# cap: <reason>` in Python and shell, `/* cap: <reason> */` in JS and CSS. One
  reason covers one cap: the line above lends its reason only when it is a comment. Allowed:
  - `prompt`: a model's context budget (marked).
  - `untrusted`: a bound on what other programs, agents, pages or models send (marked).
  - `api`: an outside limit (Telegram 4,096 characters, push, a URL, a subject, a file name, a search query).
  - `id`: a title, key, slug, short hash or date, with the full text kept next to it.
  - `parse`: a window code searches or matches; nothing of it is shown.
  - `store`: a stored record, cut visibly. Stored text the owner may read keeps at least `textcap.STORE` (20,000).
  - `preview`: a marked short form, one tap from the whole (marked).
  - `list`: shows how many more, and a way to see them.
  - `rotate`: a rolling window kept on purpose (ids already handled, a price history, the newest snapshots).
  - `top`: a short top-N view on purpose (the biggest five). Never for what the owner or an agent asked for: refuse it
    (`textcap.limit_items`) or use `first()`. A list slice needs its reason at any length (FND-123).
- `ops/truncation.py check` (in `ops/check.sh`) finds every cap: slices of 20 or more and slices by an UPPERCASE
  constant in Python and JS, the textcap helpers, ellipsis CSS, `head`/`tail`/`cut -c`/`${v:a:n}` in shell, and SQL
  limits of 2 rows or more. It fails on a cap without a known reason, on an unmarked cut with a reason someone reads
  (prompt, untrusted, store, preview: a mark written in a comment is no mark), and on a model answer read without
  `textcap.answer()`. Smaller slices are not checked, but the rules above still apply to them.
- An exception message is short: log and show it whole (`f"{e}"`, never `str(e)[:200]`).
- The audits and what each found: `docs/TRUNCATION-AUDIT.md`.

## Limits (QA-22)

Nothing that stops, refuses, drops or delays work is written without saying so. On 6 Nov 2026 the owner's main workflow
turned out to refuse repositories over 150 source files: a number nobody asked for, in no requirement, shown to nobody.

- **Do not invent a limit to protect something.** If it could stop what the owner asked for, wait instead (a usage limit,
  the PC's memory), or ask. A new limit that can refuse or drop the owner's work is the owner's decision, in a requirement.
- **Tag every limit:** `# limit: waits|paces|refuses|stops|drops, why it exists` on its line or the line above.
  `ops/limits.py check` (in `ops/check.sh`) fails on one without a tag, and `docs/LIMITS.md` is generated from the tags
  (`python3 ops/limits.py write`).
- **A promise in the app is a requirement.** "You get a message" needs the code that sends it and a test.

## Architecture invariants (do not break)

- Mission Control's app never executes anything: it drops requests into an inbox; `ops/missions.py` (host) is the
  only place that runs jobs, and it validates every request. The only writes the app does itself are the owner's chat with Hermes, the run record's ingest, the owner's answers to the AI phone's and the connections' approval cards, phone control and connection grants (written to their shared folders, which the services validate themselves), push subscriptions and the app's own error reports (SEC-12, `docs/API.md`).
- Only the `scout` profile reads the web; web content never reaches an agent that holds private data unlabeled.
- The builder codes in a sandbox and cannot push or deploy. Only the host runner merges and deploys, only after
  the owner's tap, with smoke test and automatic rollback.
- Subscription models only: no paid model in LiteLLM, ever.
- Every service port binds `127.0.0.1`; outside access only through `tailscale serve`.

## Checks

`make check` runs `ops/check.sh` in the CI runner image: shellcheck, ruff, JavaScript syntax, the app's scripts for
undefined names (`ops/app_lint.py`), YAML, Semgrep with the repo's own rules (`.semgrep.yml`: no public ports, no
Docker socket, no secrets in code, dangerous patterns), frozen benchmark hash, compose validity, the agent registry,
the prompts, the truncation check (every cap names its reason), the requirements (every test claimed, every source
file traced or listed in `requirements/untraced-files.txt`), and the pytest suite (unit tests, docs coverage, the
API reference `docs/API.md` current, every path and target the docs name exists, silent broad catches only fewer). CI and the builder run the
same script. Never weaken a check to make it pass; fix the cause.

## Commits

A supervised session lands with `bash ops/land.sh <branch> "<owner approval>"` (the checks first, both locks, the deploy, the
runner restart, an activity event), never by hand. One logical change per commit, a subject that says what changed, a body that says why and names the requirement ids
it adds or changes (`Requirements: MIS-05, PHN-11`). A contradiction you notice goes into `requirements/findings.yaml`,
not silently into the code. End with
`Co-Authored-By: <agent> <noreply@…>` when an agent wrote it. Never push to `main` from a sandbox and never
rewrite history.

## Do not

Change `eval/bench-v1.yaml` (frozen; CI checks its hash), weaken a boundary from `docs/SECURITY.md`, add a paid
model to LiteLLM, publish a port beyond 127.0.0.1, give an agent the Docker socket, delete Docker volumes or NAS
data, or deploy without the owner's approval.
