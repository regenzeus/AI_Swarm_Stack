# Observability: seeing what every agent does

The owner's rule: every agent, mission, crew job, build and Claude task must show what it did, what it produced, what it
cost, and when something goes wrong — without him having to look for it. This page says what records exist, what
Mission Control shows, and what is still proposed. Ideas marked *(Atlas/ITCG design)* come from the owner's own platform
designs ("Atlas Agent Platform", "ITCG Mode D V2.1 data flow" artifacts on claude.ai).

## Where the records come from

| Tool | What it records | How we use it |
|---|---|---|
| **LiteLLM** (gateway, `LiteLLM_SpendLogs`) | every model call (model, tokens in/out, cached and reasoning tokens, duration, status, the real error message) and every MCP tool call through the gateway (tool, duration, status), per key | the backbone of every run timeline (`ops/telemetry.py`) |
| **Phoenix** (`:8443`, OTEL traces from LiteLLM) | the full prompt and response of every model call | every model call in a log (run view, agent log) has **Open in Phoenix**: `/api/phoenix?ts=&ms=&model=` finds the closest `litellm_request` span (start or end within 20 s, duration and model break ties) and opens its trace; the run head links to all traces. Mission Control reaches Phoenix on the `obs` network only |
| **Hermes** (`state.db` per profile; dashboard `:8448`) | sessions (model, system-prompt hash, tool-list hash, token and tool counts, cost), messages with tool calls, arguments, results, and reasoning fields (empty on the ChatGPT path: its reasoning arrives encrypted) | tool calls/results in timelines, the run manifest; the dashboard for live sessions |
| **The runtime record** (Mission Control `runrecord.py`, below) | one event stream for every agent, live: Hermes (all profiles, via a plugin), Claude Code (hooks), the AI phone, Gmail, the runner's missions, builds, Claude tasks and crew jobs; one honest end state per run | the run view (`#/live/<run>`), Live now, runtime problems on the health board |
| **Claude Code** | `-p --output-format stream-json`: every tool use and result, token usage incl. cache, the final result (turns, usage); thinking blocks when it sends them (2.1.305 headless sends none here). Hooks (SessionStart, Pre/PostToolUse, Stop) feed the runtime record. Native OpenTelemetry (`CLAUDE_CODE_ENABLE_TELEMETRY=1` + OTLP exporters): metrics (tokens, cost, lines changed, commits, active time) and events (tool results with duration and success, API requests and errors) | stream-json for builds and Claude tasks. OTEL **not enabled**: Phoenix only takes traces, Claude Code exports metrics and logs, so it would need an extra collector; stream-json already gives the per-run detail |
| **OpenCode** | its own session store (messages, tool parts), `opencode export` | not wired in: the builder replaced it for building |
| **systemd / journald** | every crew job's runs (start, end, result) and its log lines | crew history (`observe.crew_history`) |
| **The runner** (`missions.sqlite`) | runs, builds, proposals (now with `source`), Claude tasks | stats, payoff, health |

No heavy service was added (Langfuse, ClickHouse…): the PC has 16 GB and the records above already contain what
is needed; the work is joining them.

## What Mission Control shows

- **Run timeline** (missions; the same blocks on build pages and Claude tasks): model calls, tool calls with
  arguments and results, gateway calls, errors, what the agent said; detail levels Summary / Steps / Everything.
- **Files** — read vs changed, with the tool that did it (Hermes `read_file`/`search_files`/`patch`/`write_file`,
  Claude `Read`/`Grep`/`Glob`/`Edit`/`Write`, Serena's symbol tools, shell commands like `cat`/`sed -n`/`sed -i`/`>`,
  and a build's git diff as changed). `ops/observe.py files_of()`.
- **Statistics** — per tool: calls, errors, average and longest duration; model calls: tokens per call, cache share,
  typical (p50) and slowest-5 % (p95) latency; time split between the model and the tools.
- **Two panes per run** *(Atlas/ITCG design: the live view)*: **What it does** (the timeline above) and **What it
  touches** — what it **read** (files, web pages, searches, mails, phone screens), what it **changed** (files), what
  was **refused** (no grant, a guard such as the phone's block list or money guard, the owner declined) and what it
  saw only partly (**cut off**: truncated results), plus the tools and grants it was allowed. Side by side on a wide
  screen, one under the other on a phone.
- **Problems** *(Atlas/ITCG design: deterministic checks, no second model)* — unknown tool names, empty arguments
  to a tool that needs some (`obs_core.NO_ARGS` lists the tools whose arguments are all optional; a test rescans
  every tool in the repo), non-JSON arguments, the same call 3 times, tool errors, usage-limit stalls, results that
  were cut off and not read on before the final answer ("does it claim the whole source?"; a later call of the same
  tool with the same url, path or id counts as reading on), and a run without a clean end (no final answer). The
  last run's problems also show on the Agent health board.
- **Manifest, light** *(Atlas/ITCG: run manifest)* — model, profile (system-prompt hash), tool-list hash, connected
  tools and grants, the stack commit and hashes of the files that shape behaviour; frozen at the run's first record.
  It only flags **drift** since the previous run; it never stops a run.
- **Skills** *(Atlas/ITCG: lifecycles)* — available (listed) → loaded (`skill_view`) → used (followed by work).
- **Stages** *(Atlas/ITCG: stage events)* — deep research steps and other multi-stage runs as STARTED / COMPLETED /
  SKIPPED / DEGRADED / FAILED with input and output sizes.
- **Agent health** (each task's row on the Tasks tab, and Tasks → Team → Crew) — every repeating task and crew duty: last status, 7-day success, and
  issues found automatically: failing in a row, last run failed, did not run when scheduled, 3× slower or 3× the
  tokens of its usual runs, loops, usage-limit blocks. New issues go out **once** (push + Telegram, again after a
  day if still there).
- **Crew pages** — every crew agent: its runs over 30 days with their log, stats (success, duration), payoff
  (proposals made and their fate: accepted, built, dismissed), and **settings**: schedule presets or custom
  (`OnCalendar` or an interval, applied as a systemd drop-in), on/off, Run now.
- **Results** — missions: what it delivered (each result opens), then runs and tokens; crew: proposals and their fate, or successful runs.
- **Tasks** — the tasks the agent worked on and its part in each; each opens its task's page (APP-35).

## The runtime record: one stream, every agent, live

Built after the timelines above, so that *every* run kind (not only missions) can be watched while it works, with the
same panes. Timelines stay for runs recorded before 28 October.

**Event format** (shared with the timelines; `obs_core.py`): `{run, ref?, agent, source, ts, kind, title, detail,
tokens?, ms?, status?, data?}` with kind `run | llm | call | result | error | say | think | mcp | stage | end`.
`ref` ties a run to the one it works for (`mission-run:15`, `build:7:1:queued`, `claude-task:3`, `chat:<id>`,
`crew:<job>:<time>`). Shaped after the OpenTelemetry GenAI conventions and mapped in one place
(`runrecord.OTEL`: run/end → `invoke_agent`, llm/say/think → `chat`, call/result/error → `execute_tool <tool>`,
stage → `invoke_workflow`); nothing exports OTLP yet.

| Source | How it reports | Run id |
|---|---|---|
| Hermes, every profile (main, mission, scout, curator, builder) | plugin `config/hermes/plugins/aistack-runtime` (installed by each `configure*.sh` and by deploy when it changes): `pre_llm_call`, `post_api_request` (tokens, cache, duration, what it says and thinks), `api_request_error`, `pre/post_tool_call`, `subagent_start`, `on_session_end`. Observer only: never vetoes, never waits; a queue and a sender thread post to `http://mission-control:8093/ingest`; spooled to `$HERMES_HOME/runtime-spool` when Mission Control is down | `hermes:<profile>:<session>:<n>`, one per turn |
| Claude Code (builds, Claude tasks, Claude reviews) | `config/hermes/claude-hooks/runtime_hook.py` via `--settings claude-runtime-settings.json`; also reads Claude's transcript for model calls (tokens, cache), what it says and its thinking. Writes `/work/.runtime/*.jsonl` (the sandbox can't reach Mission Control) | `claude:<agent>:<session>` |
| AI phone, Gmail | `rt_emit` in `phone.py` / `mail.py`: every logged action into `runtime/*.jsonl`; a session is a stretch of activity (15 min gap), closed as done when quiet | `phone:<time>`, `mail:<time>` |
| The runner | `ops/runtime.py`: missions (`execute`), builds (each worker step), Claude tasks, crew jobs: start with a manifest, end with the state. Passes `AISTACK_REF` to Hermes and Claude Code (`docker exec -e`) so their runs show under it. Its forwarder thread sends the builder, phone and mail spools and its own | `mission-run:<id>`, `build:<id>:<attempt>:<step>`, `claude-task:<id>`, `crew:<job>:<time>` |
| Pipelines without an agent (cleanup, briefings, deep research steps, crew) | `RTM.stage()` (each step: starts, waits such as the Windows disk scan, findings, errors), `RTM.touched()` (files they read or write: the scan, the run's report and notes), `RTM.model_call()` (direct model calls of the runner, with tokens), `hermes_z` start and finish; a briefing's `desk.sh` log streams in line by line | under the mission run |
| LiteLLM spend logs | unchanged: still read for the timelines and costs | |

**Ingest and store.** No new service: Mission Control serves `POST /ingest` on port 8093 (mcnet; published on the
host's 127.0.0.1 only, bearer `API_SERVER_KEY`) into SQLite `/missions/app/runtime.db`. Full events are kept 90
days; each finished run's summary (duration, end state, calls, tokens, cache share, problems, files) is kept for
good.

**One honest end state per run**: `done | failed | stopped | stalled | limit`. Sources send it (a Hermes turn:
interrupted → stopped, a usage limit → limit; the runner maps its run status with `mission_state`); a closed run
stays closed (late events and a second end are dropped). The **watchdog** (every 30 s) closes a run silent for 20
minutes as `stalled` (a run parked on a declared wait, such as the Windows disk scan, gets 3 hours), or as `done`
for a phone or mail session that simply went quiet; if the run's own end
arrives later after all (a long wait, such as the Windows disk scan), it replaces the watchdog's `stalled`. Activity of a run's children
keeps the parent alive. The runner's own recovery (`requeue_interrupted`) closes the runs it re-queues as
`stopped`.

**Manifest and drift.** A run's first event carries a light manifest (agent, profile, connected tool servers;
engine and model for Claude Code; mission type and trigger for the runner). Against the previous run of the same
agent it flags drift: another model, fewer tools, a tool server no longer connected. It never stops a run.

**Names.** Runs are shown by name, not id (`runrecord.name_of`): "Chat · <chat title>", "Mission · <title> · run 18",
"Build #8: <title>", "Claude task #4: <question>", "Crew · <job>", "<agent> · in <parent>" for agents inside a run.

**The run view** (`#/live/<run>`; also `#/live/build:7`, `claude-task:3`, `chat:<id>`, `phone`, `mail` for the
newest): the same two panes and blocks as the timeline (it uses the same renderers), plus the agent's runs inside
it, the **box** a Claude task or build works in (its folder, what it may use, network), and the **connections**
used. Live over SSE (`/api/rt/run/<run>/stream`, new steps appear within a second), the same page replays a
finished run. **Working now** on Tasks → Activity lists what is running; the Runs tab's Timeline button, the build page,
Claude tasks, the chat header and the AI phone page link to it.

**Problems** of finished runs (`GET :8093/problems`: the deterministic checks above, plus stalled, limit, failed,
and lost tools) join the Agent health board as one item per agent and go out once per issue like the others.

**Notifications** go out through one path, `ops/notify.py` (OBS-16): the owner's preferences per kind of message and
channel, quiet hours (only approvals then; Telegram messages wait and go out as one), once per key, and a log of every
decision (`/srv/ai/state/notifications.jsonl`, shown under Stack → Notifications). Nothing else talks to Telegram.

**This PC** (an engine item on the same board, from `ops/crew.py`) watches the machine: full swap (an alert
when RAM is short too, CST-14), containers on another build than their tag or missing from `versions.lock` (PLT-20),
and an alert when a container is cut off from the network it shares, because the container it shares was
recreated without it (PLT-23). A restore drill older than 8 days is an alert on the Restore drill (PLT-15).

Not built, on purpose: steering a run from the view, a harness pane, a per-run workbook, and the fence (only the
box a Claude task or build already has is shown).

## Later

- **Handover record** *(Atlas/ITCG)*: per run, what it read, concluded, ruled out, what is missing and what to check
  next, as the starting point of the next run or a follow-up agent. Not built yet.
- Per-call link from a timeline to its Phoenix trace (needs the call id on the span).
- Claude Code OpenTelemetry into a tiny local receiver, if the stream-json detail ever falls short.

- Export the runtime record as OTLP spans (the names are mapped already) if a trace viewer should show it.

Not planned: the fence (optional in the Atlas design, off by default) and the steering/harness ideas.

## What each task run used and made (TSK-23, TSK-24)

`ops/provenance.py` records, for every step of a Conductor task's run, the artifacts it used and generated as W3C PROV
links (`used`, `generated`, `derived`, `cited`) in the runner's database (`artifacts`, `prov`). They come from where
the work happened: the agents' tool calls in the runtime record (fetch, web search, the browser, the job board, the
vault, memory; a helper agent's calls count for the step that called it in), the Topic Desk's chosen items, the
step's own answer (a finding, derived from the pages it names and from the findings it waited for), the report, the
wiki pages and the deliveries. When the run ends, the steps are recorded again (tool events arrive late) and every
source whose address the report or the answer links is marked `cited`. Each change writes the run's map,
`public/maps/<task>.<occ>.json`, which the app draws (Tasks → Swarm map) and `/api/task/map` serves.
`python3 ops/provenance.py backfill` records and draws the runs that finished before.

## Telemetry history, list prices and task traces (TSK-25 to TSK-27)

- **History:** `ops/history.py` rolls the runtime record up every hour into `agent_days` (runner database): one row
  a day per agent, model, harness and kind of work (the task's kind, or mission, build, chat, crew, intake), with runs,
  ended well, failed, the judge's met/partly/not met (`task_metrics`), tokens in/out/cached, median and p95 time and the
  cost at list price. A day is written again whole; 365 days are kept (the runtime record's events stay 90).
  `public/telemetry.json` → `/api/telemetry` → Stack → Telemetry, whose agent rows open their runs
  (`/api/rt/runs?agent=&since=&until=`).
- **List prices:** `config/prices.json` from the gateway's own table (`python3 ops/prices.py refresh`), each alias
  priced as the provider's model behind it. Shown as "$x if paid" on runs, tasks, steps, map lanes and the dashboard;
  `upgrade_check.py` says when it is behind the pinned LiteLLM.
- **Phoenix:** a task's run (`task:<id>`, `task:<id>.<n>`) is exported a minute after it ends as one trace
  (`otlp.tree_spans`): the run as root, its steps, the agent runs inside them, their model and tool calls.

## Journey checks (TSK-32)

Unit tests check parts; the owner uses journeys. `ops/journeys.py` follows them end to end every night at 04:10 (the
Journey checks crew job) and on `make journeys`, without a model and, but for one marked test item that removes itself,
without changing anything live:

| Journey | What it proves |
|---|---|
| task | a task given in a sentence goes through the real intake check, the Conductor, the result file, the done message, the judge and the Tasks board, on the newest finished task's recorded answers, in a sandbox database |
| decide | a test item marked as one goes in through the runner's inbox, shows in the app's list, on Home and on #/decide with the same count, is answered by a tap on its own button (the real `/api/request`, inbox and runner), and leaves all three with its answer recorded; then it is removed, also on a failure. The browser sends no other write, the shadow never records it, and its answer changes only its own file |
| routes | every route opens at 375 px in headless Chromium (the scout's browser image) on the live data and with an emptied state: no sideways scrolling, script error or empty screen; a card opens its page; an empty state offers an action; dates and numbers the app's way. Writes are answered in the browser, never sent; no other host is reached |
| email | the newest briefing rendered as its e-mail: the headline once in the header, no Markdown marks or twice-escaped text, nothing wider than a phone |
| make | every make target dry-runs and every script its recipe names exists |
| selftest | a page, an e-mail and a Makefile with each of those faults are caught |

The report is `/srv/ai/missions/crew/journeys.json`; any failure is one alert on **Journey checks** on the health
board, naming the first ones, until a night passes.

