# Mission Control

The app at `https://<pc>.ts.net:8447` (tailnet only; installable as a PWA with push notifications) and the host
runner behind it. Code: `images/mission-control/` (app + MCP tools), `ops/missions.py` (runner),
`ops/mission_extras.py` (events, deep research, wikis, delivery), `ops/builds.py` + `ops/deploy.py` (builder).

## How the parts talk

```
app (container, uid 10006)                         runner (host, systemd missions.service, has the secrets)
  reads  /srv/ai/missions/public/state.json   <---   writes it every 4 s (missions, runs, builds, resources, system)
  writes /srv/ai/missions/inbox/<id>.json     --->   validates + executes, answers in public/results/<id>.json
  tails  /srv/ai/missions/public/events.jsonl <---   appends events (activity feed, push notifications)
  chats  /srv/ai/missions/app/chats/*.json           (the app talks to Hermes directly for chat)
```

The app never starts anything itself; the runner is the only place that runs jobs, and it validates every request
(slugs, schedules, triggers, sizes). The only writes the app does itself are the owner's chat with Hermes, the run record's ingest, the owner's answers to the AI phone's and the connections' approval cards, phone control and connection grants (written to their shared folders, which the services validate themselves), push subscriptions and the app's own error reports (SEC-12, `docs/API.md`). The app's `/api` requires Tailscale's identity header; the MCP tools on port
8091 are reachable only from LiteLLM on the internal `mcnet`.

## Missions

A mission is `vault/missions/<slug>/MISSION.md` (YAML front matter + goal), versioned in the vault.

| Field | Values |
|---|---|
| `type` | `briefing` (Topic Desk, brief in `vault/topics/<slug>/TOPIC.md`) or `task` (long-term agent work, Hermes profile `mission`) |
| `status` | `active`, `paused`, `archived` |
| `schedule` | `daily HH:MM`, `weekdays HH:MM`, `weekly mon,thu HH:MM`, `every Nh`, `manual` |
| `triggers` | `sec_filing` (tickers, forms), `price_move` (symbol, pct), `news` (query); checked every 10 min, first look = baseline |
| `depth` | `deep` (tasks): plan → 3-5 research steps → synthesis, steps shown live |
| `once` | one-off: runs now, delivers, archives itself (used for "research X and e-mail me") |
| `deliver` | `telegram` (with buttons into the app), `app` (push), `email` (designed HTML, Gmail) |

Runs go one at a time, so a run's calls are exactly its key's calls in that window (`vk-desk` for briefings,
`vk-mission` for tasks): calls, tokens and spend per run and per mission come from LiteLLM's spend log. A run that
fails because ChatGPT paused the stack (429 / usage limit) waits and retries every 30 minutes (up to 8 hours).

Outputs: briefings → `topics/<slug>/reports/YYYY/MM/DATE.md`, alerts → `topics/<slug>/alerts/`, tasks →
`missions/<slug>/log/…` plus `NOTES.md` (the agent's working memory between runs). Every result also updates the
mission's **LLM wiki** (`topics/<slug>/wiki/` or `missions/<slug>/wiki/`: entities, concepts, projects, events,
`[[links]]`, `index.md`). All of it is indexed by qmd, so Hermes can answer questions about it.

Hermes manages missions from chat through MCP tools: `missions_overview`, `mission_details`, `mission_create`,
`mission_control`, `mission_update`, `mission_set_triggers`, plus `send_email`, `vault_add`, `understand_repo`,
`build_assign`, `builds_overview`.

## Chat

The Chat tab is Hermes (main profile) through its OpenAI-compatible API. Per message: model (`gpt-sub` =
GPT-6.1 Sol, `gpt-sub-fast` = GPT-6 Luna), reasoning effort (low…xhigh), attachments (images go to Hermes as
images; PDF, Word, Excel, CSV and text are extracted to text in the app). The answer runs as a server-side task and
is saved even if the phone disconnects; the app follows it over a reconnecting SSE stream with tool steps. Edit,
regenerate, stop, copy, rename, pin, search. Focus chats (`#/chat?mission=slug`) carry the mission's context.

## Code tab (repositories)

`ops/repos.py` lists ai-stack and every repo in `~/code`: buildable (origin is Forgejo) or studied only, its Graphify
graph (`graphify-out/graph.json`, kept current by `ops/graphify-sync.sh`; ai-stack through a mirror clone in
`~/code/ai-stack`), its Understand Anything code map (`.ua/`, `ops/understand.sh`) and digest (`/srv/ai/code-docs`). The
app draws the graph (`/api/repo/<name>/graph`: the 200 best-connected nodes, laid out once) and shows the digest or
README. Actions: `understand` (study a GitHub repo or refresh), `codemap` (show a repo in the viewer, behind the gate),
`repo_create` and `repo_buildable` (Forgejo API with `FORGEJO_TOKEN`; a studied repo keeps its origin as `upstream`).
Hermes: `repos_overview`, `repo_create`, `repo_make_buildable`, `understand_repo`.

## Builds (the stack develops itself)

`ops/builds.py`: assignment → workbench clone `/srv/ai/workbench/<repo>`, branch `builder/<id>-<slug>` → the builder
(container `builder`, Hermes with shell + file tools, `--yolo` inside the sandbox) implements, tests, commits →
sandbox checks → the runner pushes (host SSH key) → Forgejo CI → **review in the Build tab** (summary, checks, CI,
diff, sensitive-file warning) → Approve (merge `--no-ff`, push, `ops/deploy.py`: rebuild changed images, recreate
services, reconfigure Hermes profiles, install units, smoke test + health) → on failure the merge is reverted,
pushed and the revert deployed (`rolled_back`). Request changes sends feedback; the builder continues on the branch.
After the checks, the other engine reviews the diff (`ai_review`: Claude Code read-only for ChatGPT builds, ChatGPT for
Claude builds) and the verdict and findings show on the build page and in the notification.
Usage limit: the build waits and resumes with its unfinished work. While the builder works, the runner reads its
session store every 10 s (`save_steps`) so the build page shows each tool call and failure live. Before the checks,
today's main is merged into the branch and uncommitted leftovers are stashed; "Re-run checks" repeats that without
the builder. Repos: `ai-stack` and Forgejo-hosted `~/code` repos.

### Self-improvement loop

`ops/improve.py` (a runner thread) does a weekly self-review: it collects signals (failed runs that are not usage-limit
pauses, failed systemd jobs, error events, failed or rolled-back builds, red CI, the open-work sections of the latest
`docs/REVIEW-*.md`, `ops/upgrade_check.py`), asks the model once (key `vk-review`) for at most five small,
concrete ideas, written to the swarm's Ledger (`ops/swarm_client.py propose`), where a known problem gets new evidence instead of a copy. Ideas show in
the Build tab (with a push notification). **Build it** turns one into a normal `build_assign`, so review and
tap-to-deploy still apply; **Dismiss** records an optional reason that later reviews see. Nothing starts without the
owner. State: the Ledger (`images/swarm`; the old table `proposals` is read-only history since 2026-10-29), `/srv/ai/missions/builds/improve.json` (last review, result, retry).
A usage-limit pause retries hourly, any other failure the next day. On demand: "Look for improvements" or Hermes'
`improvement_proposals(scan_now=True)`.

With `FORGEJO_PR_TOKEN` (a Forgejo write token in `secrets.enc.yaml`), every build in review also gets a pull request
on Forgejo. The runner closes it on merge or reject, and approval stays in Mission Control.

## Stack page

Apps (Hermes admin, Open WebUI, OpenCode, code map, Phoenix, Forgejo), live resources (Windows RAM/CPU/C: from
`ops/windows/host-probe.ps1`, WSL RAM/CPU/disk, every service's CPU and RAM against its limit), add knowledge
(note, web page, file → `vault/raw/_inbox`), long-term memory search + forget, code repos + analyse, CI per repo,
skills, services, scheduled jobs, backups, memory approvals, push setup.
