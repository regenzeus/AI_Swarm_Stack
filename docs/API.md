# Mission Control API

Drawn from `images/mission-control/server.py` by `python3 ops/api_doc.py`; `tests/test_docs.py` fails when
this file is stale. Do not edit it by hand: change the handler's docstring and run the script.

## Mission Control (port 8090, behind `tailscale serve`)

Every `/api/` and `/share` route needs the `Tailscale-User-Login` header that `tailscale serve` adds (`TailnetOnly`); a request without it gets 403. Answers are never cached (APP-09). Only `/api/request` acts, through the runner's inbox; the writes the app does itself are the documented exceptions of SEC-12 (chat, the run record, the owner's phone and connection answers, push subscriptions, client errors).

| Route | Methods | What it does |
|---|---|---|
| `/` | GET | The app's page (index.html), always revalidated. |
| `/sw.js` | GET | The service worker (offline shell, push, self-update), always revalidated. |
| `/manifest.webmanifest` | GET | The PWA manifest that makes the app installable. |
| `/healthz` | GET | Liveness for the deploy's smoke test: whether the runner's state file exists and how old it is. |
| `/api/state` | GET | The runner's whole state (missions, runs, builds, crew, health, system …) plus the phone, the connections and who is viewing. |
| `/api/stream` | GET | Server-sent events: a new state whenever the runner writes one, so screens update without polling (APP-17). |
| `/api/version` | GET | The deployed app version; the app reloads itself when it changes (APP-03). |
| `/api/request` | POST | Drops an owner's action into the runner's inbox (the only way the app acts, SEC-12); the runner validates and answers under /api/result. |
| `/api/result/{rid}` | GET | The runner's answer to one request, or {pending: true} while it works. |
| `/api/file` | GET | A vault file as text, for the reading view; only paths inside the vault. |
| `/api/runlog/{rid}` | GET | The last 300 lines of a mission run's log (an earlier-lines marker says how many more there are). |
| `/api/run/{rid}/timeline` | GET | A run's timeline (ops/telemetry.py writes it: model calls, tool calls, results, thinking, tokens). |
| `/api/rt/runs` | GET | Runs from the run record, newest first (filter: live, agent, ref; limit). |
| `/api/task/{tid:int}` | GET | APP-35: one task's page: the task, its runs and their steps (the runner's file), the agents that worked on it, their actions and what they read from and kept in memory (the run record), and its answer. |
| `/api/agent/{aid}/tasks` | GET | APP-35: the tasks an agent worked on, newest first, with their titles and states. |
| `/api/trials` | GET | TRL-09: the trial scoreboard as the runner wrote it (ops/trials.py publish). |
| `/api/usage` | GET | How much each subscription carried in the last 5 and 24 hours (runrecord.usage). |
| `/api/rt/run/{run}` | GET | One run from the run record: its events, problems, statistics and manifest. |
| `/api/rt/run/{run}/stream` | GET | New events of a run (and its children) as they arrive; ends when the run has ended. |
| `/api/crew/{cid}` | GET | A crew agent's history (ops/crew.py writes it every 5 minutes): runs, logs, stats, payoff, health. |
| `/api/swarm` | POST | The Swarm page reads through the Swarm service's read-only door (the owner sees every thread); his posts go to the runner as action swarm_post. |
| `/api/swarm/tokens` | GET | Tokens per agent in the last 30 days from the runtime record (with the Claude runs under a crew job), for the scorecards' cost per proved idea (SWM-17). |
| `/api/swarm/now` | GET | SWM-97: who is working right now, from the runtime record's live runs: agent, what, since when, tokens so far. |
| `/api/swarm/timeline` | GET | SWM-103: every agent's runs in the window (at most 7 days), as bars of its lane, with what started each. One piece of work is one bar and tests stay out unless tests=1 (SWM-112). |
| `/api/swarm/interactions` | GET | SWM-110: the map's dots and lines in the window, counted from the same rows Activity shows, with how much of it has a known cause. |
| `/api/swarm/delegations` | GET | SWM-105: what agents ask each other through their tools, as exchanges for the Chatroom (pair=a+b: two agents). |
| `/api/swarm/room` | GET | SWM-107, SWM-110: one timeline of what the agents do together and with you, at most 7 days, the rows the map counts: the Ledger's events and the Board's messages (Swarm service), asks and tool use between agents, hand-overs, what you said and what you were told. A record that can't be read is named instead of showing nothing (SWM-115). |
| `/api/health/issues` | GET | The open health-board issues, each with the run that shows it (OBS-13). |
| `/api/claude/{tid}` | GET | A Claude task (ops/claude_tasks.py): question, answer, status and its steps (with Claude's thinking). |
| `/api/phoenix` | GET | Open in Phoenix: ?ts=<epoch>&ms=<duration>&model=<name> -> that call's trace; ?from=&to= -> the project's traces. |
| `/api/build/{bid}/{kind}` | GET | One file of a build (diff, log, steps, files or context) as text. |
| `/api/files/{slug}/{name}` | GET | MIS-23: a mission's file: as text for the reader, or with ?download=1 as the file itself (its own name). |
| `/api/mission/{slug}/drafts` | GET | MIS-23: the Ledger reports a mission's runs wrote (drafts the agent kept there), newest first, from the run record. |
| `/api/chat` | POST | Start a chat turn: stored at once, answered in the background; follow it with /api/chats/<id>/stream. Body: message, chat?, mission?, model?, effort?, attachments? [ids from /api/chat/upload], truncate? (edit/regenerate: drop messages from this index first). |
| `/api/chats` | GET | The owner's chats, newest first, optionally filtered by a search text. |
| `/api/chats/{cid}` | GET, DELETE, PATCH | One chat: GET reads it, PATCH renames or pins it, DELETE removes it with its attached files. |
| `/api/chats/{cid}/stream` | GET | SSE of the answer in progress: {text, reasoning, tools, done}; keep-alive pings; reconnectable. |
| `/api/chats/{cid}/stop` | POST | Stops the answer that is being written in a chat. |
| `/api/chats/{cid}/retry` | POST | Try a message that waits for the usage limit now, instead of at its next try (AST-12). |
| `/api/chat/upload` | POST | An attachment for the next chat message: images go to Hermes as images, documents as extracted text. |
| `/api/chat/files/{fid}` | GET | A file attached to a chat. |
| `/api/models` | GET | The chat's model choices and reasoning efforts, with the default. |
| `/api/upload` | POST | A file from the phone for the vault inbox (PDF, Word, text, markdown); the runner files it. |
| `/share` | POST | The PWA share target: keeps what was shared (link, text, pictures, files) for 14 days and opens it in the app (APP-15). |
| `/api/connections` | GET | The app connections (Gmail …): their status, scopes, live grants, waiting approvals and the recent log. |
| `/api/connections/grant` | POST | Grant a scope for minutes (-1 = until revoked, 0 = revoke now). Refused from the AI phone. |
| `/api/connections/decide` | POST | The owner's answer to a connection's approval card, written to its decisions folder (a documented exception, SEC-12); never from the AI phone. |
| `/api/phone` | GET | The AI phone's state, its waiting requests and recent log. |
| `/api/whoami` | GET | Who is calling: the Tailscale login, the client address and whether it is the AI phone. |
| `/api/forgejo/connect` | POST | The owner pastes his Forgejo token in the app: it goes to the runner (checked, stored encrypted), never to Hermes. Not an MCP tool, so no AI can relay or set it; refused from the AI phone. |
| `/api/house/connect` | GET | Connect Home Assistant: off to its own sign-in page (OAuth, IndieAuth: this app's URL is the client id). The owner signs in there; Home Assistant sends him back to /api/house/callback with a one-time code. |
| `/api/house/callback` | GET | Home Assistant's answer: the code goes to the runner, which trades it for a long-lived token (stored encrypted). |
| `/api/house` | POST | The House page's buttons: switch a light/plug/shutter, an Alexa command, speak on an Echo, settings. The owner's own taps count as the owner (protected plugs included); from the AI phone they count as an agent. |
| `/api/shop/decide` | POST | The owner's answer to a purchase proposal: approve, not_now or change (with a note). Only from his own device in this app: refused from the AI phone, and not an MCP tool, so no agent can approve a purchase (ops/shopping.py). |
| `/api/shop/limits` | POST | The shopping limits (per purchase, per month, shops, the address check): the owner only, never the AI phone. |
| `/api/clienterror` | POST | An error the app hit in the browser: logged and kept (newest 500) for the health board (APP-24). |
| `/api/view` | POST | PLT-26: the app says a screen was opened (its route name and tab only). |
| `/api/views` | GET | PLT-26: the screens opened in the last 30 days (or ?days=), most opened first. |
| `/api/phone/decide` | POST | The owner's answer to the AI phone's approval card (a documented exception, SEC-12); never from the AI phone itself. |
| `/api/phone/control` | POST | Stop, resume, open the free mode, end a task or keep the screen on for the AI phone (a documented exception, SEC-12); the phone may only stop itself. |
| `/api/phone/shot/{sid}` | GET | A screenshot the AI phone took, for the owner. |
| `/api/share/{sid}` | GET | One shared item, for its page with the one-tap choices. |
| `/api/share/{sid}/save` | POST | Save a shared item into the knowledge base: the link's page, the text, and every document or picture. |
| `/api/repo/{name}/graph` | GET | The repo's Graphify graph, reduced for drawing: the best-connected nodes (max 200, so phones keep up), their links, communities. |
| `/api/repo/{name}/overview` | GET | What the repo is: the code map digest (Understand Anything) if there is one, else its README; and the written analysis of its onboarding. |
| `/api/repo/{name}/node` | GET | Everything about one code graph node: what it is, where it lives, its source, what it calls and what calls it, and what the code map (Understand Anything) says about it and its file. |
| `/api/repo/{name}/map` | GET | The code map (Understand Anything) in full: project, guided tour, layers, and every file and symbol with its summary, tags and complexity. |
| `/api/guide` | GET | The guide's chapters (with their text when full=1). |
| `/api/guide/live` | GET | What the guide shows live besides the state: the tools Hermes has here, the chat models. |
| `/api/guide/{gid}` | GET | One guide chapter with its text and live blocks. |
| `/api/wiki/roots` | GET | Every wiki (the vault's and each mission's) with pages, links, summary and whether its mission is archived. |
| `/api/wiki/graph` | GET | One wiki's pages and links, for its graph. |
| `/api/wiki/map` | GET | MEM-09: the top layer of the wikis: every wiki as a bubble (pages, links, pages changed in 7 days, who writes it) and the subjects two or more of them share (a page with the same title or alias), so you see how they connect. |
| `/api/task/map` | GET | TSK-24: a task run's swarm map as the runner wrote it (public/maps/<task>.<occ>.json, ops/provenance.py); the task's newest run when no run is named. |
| `/api/a2a/token` | POST | The owner adds an outside agent: its token is made here and shown once; the runner keeps only its hash. |
| `/.well-known/agent-card.json` | GET | The stack's A2A agent card, for agents on the tailnet, while A2A is on. |
| `/a2a` | POST | TSK-19: A2A JSON-RPC (message/send, tasks/get, tasks/cancel; the 1.0 names too) from an outside agent on the tailnet with its token. A message becomes a task (source a2a:<name>) that waits for the owner's OK; an agent sees only its own. |
| `/api/telemetry` | GET | TSK-25: the daily telemetry history per agent, model, harness and kind (a year), and the price table (ops/history.py). |
| `/api/wiki/access` | GET | MEM-10: who read and wrote which wiki in the window (runrecord.wiki_access), at most 30 days. |
| `/api/wiki/page` | GET | One wiki page with its rendered text, links and backlinks. |
| `/api/wiki/search` | GET | Pages of one wiki whose title, summary or text contains the search text. |
| `/api/push/key` | GET | The public key devices need to subscribe to push. |
| `/api/push/subscribe` | POST | Subscribes or (on /unsubscribe) unsubscribes a device for push. |
| `/api/push/unsubscribe` | POST | Subscribes or (on /unsubscribe) unsubscribes a device for push. |
| `/api/push/test` | POST | Sends a test push to every subscribed device. |

## Run record ingest (port 8093, published to 127.0.0.1 only)

For the stack's own writers (the runner, Hermes' runtime plugin, Claude's hook). `/ingest` and `/problems` need `Authorization: Bearer` with Hermes' API key, which the app and these writers share.

| Route | Methods | What it does |
|---|---|---|
| `/ingest` | POST | Events from the Hermes plugin (mcnet) and the runner's forwarder (127.0.0.1): API_SERVER_KEY as bearer. |
| `/problems` | GET | The run record's open problems (by=agent: rolled up per owning agent) for the runner's health board; ingest key only. |
| `/view/{run:path}` | GET | One run's view for the runner (ops/journal.py condenses it into the agent's journal at the run's end). |
| `/healthz` | GET | Liveness: answers ok. |

## Voice gateway (port 8095, published to 127.0.0.1:11435 only)

Ollama's API for Home Assistant's Ollama integration on the NAS (VOI-03, docs/HOME-VOICE.md). Every route but `/api/version` needs `Authorization: Bearer` with `VOICE_KEY`; with no key set, all refuse.

| Route | Methods | What it does |
|---|---|---|
| `/api/tags` | GET | The models Home Assistant can pick: one per room (hermes:kitchen). |
| `/api/show` | POST | A model's details: it completes text; no tools of Home Assistant's (Hermes has its own). |
| `/api/version` | GET | The Ollama version the gateway answers as (the one Home Assistant's client was built against). |
| `/api/chat` | POST | Ollama's /api/chat: the newest user message is the spoken turn; Home Assistant's own history and tools are not used (Hermes keeps the conversation and its tools). |

## MCP tools

Offered to the agents through LiteLLM's MCP gateway, each under its server's key grants (`config/litellm/config.yaml`).

| Server | Tool | What it does |
|---|---|---|
| claude_mcp | `agent_note` | Keep a standing note in your own memory (your journal, agents/<agent>/MEMORY.md in the vault): one short line that every future run of yours reads first, e.g. "check the board manual before searching shops". agent: your agent id, as your memory block names it (e.g. 'mission-ram-upgrade'). Only lasting lessons, never secrets or personal data. |
| claude_mcp | `claude_task` | Delegate work to Claude Code (Anthropic's coding agent, on the owner's Claude subscription). Use it for code questions ("how does X work in repo Y", "where is Z handled", "is this design sound"), reviewing or analysing code or long documents, and hard reasoning. Not for quick lookups or web research (use your own tools for those). repo: one of the owner's repositories (e.g. 'ai-stack', 'TestRepo', or a studied one like 'nanoGPT'); Claude reads a copy of its main branch. Leave it empty to work on `context` instead (paste the document or text there). mode: 'ask' (read-only: reads and searches the code) or 'analyse' (also runs commands such as tests and linters in the copy). It never changes anything: for changes use build_assign. evidence: for "why did X fail / what went wrong" questions, the logs Claude should read (read-only, secrets redacted), comma-separated: 'mission:<slug>' (its latest run's timeline and logs), 'run:<ref>' (a runtime run, as health_issues or the run view names it), 'crew:<agent id>' (e.g. crew:doctor), 'minutes:<N>' (the whole stack's error lines of the last N minutes). Use it with repo='ai-stack' so Claude can match log lines to the code. Returns a task number at once; Claude takes minutes: then call claude_task_result(id, wait_seconds=45) until it is done and pass the answer on. |
| claude_mcp | `claude_task_result` | The status or answer of a Claude task (from claude_task). wait_seconds (0-50): how long to wait for it to finish before answering. Call again while it is still running. |
| claude_mcp | `health_issues` |  |
| files_mcp | `file_save` | Save one of the files this mission was asked to deliver (its brief lists them), or another useful file. text: the whole file; or from_ledger: the id of a Ledger report whose body is the file (saved unchanged). Saving again makes a new version (earlier ones are kept). Formats: .md .csv .json .txt, up to 2 MB. Delivery (the mission page, the e-mail attachment, Telegram) happens after the run: never say a file was sent. |
| house_mcp | `house_alexa` | Tell Alexa to do something, as if the owner said it to an Echo: for the lights, plugs and routines that live in the Alexa app (e.g. 'turn off the living room light', 'set the bedroom light to 30 percent', 'start the good night routine'). Write the command in the language the Echo is set to (Echos bought in Germany usually understand only German: 'schalte das Licht im Wohnzimmer aus'). echo: which Echo runs it (name or room; empty = the first one); the result is the same from any Echo. Never for shopping and never for protected devices. |
| house_mcp | `house_say` | Speak a short message on an Echo (echo: its name or room, or 'all'). announce=True plays the announcement chime first (good for 'dinner is ready'-style messages to every room). Keep it to one or two sentences. |
| house_mcp | `house_status` | The owner's flat through Home Assistant: every light, plug, switch and shutter with its room and state (on/off, brightness, position, power), which ones are protected, and the Echo speakers. Call it first to learn the names. |
| house_mcp | `house_switch` | Switch one light, plug, switch or shutter that Home Assistant controls (names from house_status). entity: its name, 'room name' or entity id. action: on / off / toggle / dim (value = brightness 1-100) for lights, plugs and switches; open / close / stop / position (value = 0-100) for shutters. Protected things (fridge, router, NAS, PC …) are refused. |
| mcp | `build_assign` | Give the builder (a sandboxed coding agent) an assignment to implement in one of the owner's repos: 'ai-stack' (this AI stack itself: Mission Control, missions, configs, scripts) or a repo in ~/code that lives on Forgejo (e.g. 'TestRepo'). description: exactly what to build or fix, with acceptance criteria. The builder works on a branch, runs the checks, CI runs; the owner reviews the diff in Mission Control (Build) and taps Approve, which merges and deploys with a smoke test and automatic rollback. Nothing goes live without his tap. Returns the build number. engine: leave empty (Claude Code when it is connected: better at code, and it spares the ChatGPT limit), 'claude' or 'hermes' (the builder on the ChatGPT subscription) when the owner asks for one. |
| mcp | `build_details` | One build in full, to discuss it with the owner: the assignment, status, the builder's summary, files changed, checks, CI, the AI review (verdict and every finding) and, with diff=true, the diff itself (up to 30,000 characters). |
| mcp | `build_recheck` | Re-run a build's checks and AI review on today's main (e.g. after other changes landed), without the builder. |
| mcp | `build_request_changes` | Send a build in review (or failed) back to the builder with what to change, exactly as the owner's 'Request changes' button does. Only when the owner asks for it in this chat; write his points as clear, numbered instructions. You can never approve or deploy a build: that is the owner's tap in Mission Control. |
| mcp | `build_switch_engine` | Move a build to the other engine: 'hermes' (ChatGPT) or 'claude' (Claude Code). Use it when the owner asks, or when a build waits for a usage limit and the owner agrees to switch. A waiting build starts right away; a build in review or failed gets a second attempt that continues from its branch. Not possible while it is working, deploying or merged. |
| mcp | `builds_overview` | The builder's assignments: number, repo, title, status (queued, working, review, deployed, ...), checks, CI and the AI review's verdict. |
| mcp | `health_issues` |  |
| mcp | `improvement_proposals` | The stack's own improvement ideas (the swarm's Ledger: from the crew and the weekly self-review): id, state (open, ready, active = being built, checking = shipped, declined, merged, gone), the agent that proposed it, title, and the owner's reason when he decided. The owner decides in Mission Control (Code) whether an idea becomes a build. scan_now=True starts a new self-review now (takes a minute or two). |
| mcp | `mission_control` | Control a mission: action 'run' (run it now, on demand), 'deep_run' (run a task now as multi-step deep research), 'pause', 'resume' or 'archive' (stops it for good; its files stay in the vault). Use missions_overview for the slug. |
| mcp | `mission_create` |  |
| mcp | `mission_details` | Details of one mission: goal, schedule, triggers, brief (key questions, searches, watchlist, notes) or working notes, last runs, and the vault paths of its latest outputs and its wiki (readable with the vault search tools). |
| mcp | `mission_set_triggers` |  |
| mcp | `mission_update` |  |
| mcp | `missions_overview` | List all of the owner's missions (daily briefings and long-term agent tasks) with status, schedule, event triggers, next run, runs and costs of the last 30 days, and what is running right now. |
| mcp | `repo_create` | Create a new private repository on the owner's Forgejo (lowercase name: letters, digits, . _ -), cloned to ~/code with a README and an AGENTS.md, so the builder can work on it right away (then use build_assign). Needs the Forgejo token. |
| mcp | `repo_make_buildable` | Move a studied repository (cloned from GitHub into ~/code) to the owner's Forgejo so the builder can change it; the original stays as the 'upstream' remote. Needs the Forgejo token. |
| mcp | `repos_overview` | The owner's code repositories: whether the builder may change each one (on Forgejo) or it is only studied, its code graph size, whether it has a code map, how far its onboarding is (the step, or why it stopped), and its last commit. Use the names with build_assign and understand_repo. |
| mcp | `send_email` | Send the owner an e-mail (to his own address only) in the designed report layout. markdown: the full content, starting with '# Headline'; use headings, bullets, tables and source links. Use it when he asks to get something by e-mail. |
| mcp | `understand_repo` | Onboard a code repository, the whole package: copy it (an https git URL, or the name of a repo in ~/code), its code graph, its code map, every file explained, the search index and a written analysis by Claude Code (what it is, how the stack could use it, risks, a verdict). No size limit; it waits for usage limits by itself and takes minutes to an hour. The owner gets a message when it ends, either way. Do not start your own analysis as well: repos_overview shows the step it is at or why it stopped, and when it is done the analysis is at qmd_get code-docs/<name>.analysis.md. |
| mcp | `vault_add` | Add knowledge to the owner's vault: either text (a note, findings, a summary) or a public web page URL (its text is fetched). It goes to raw/_inbox; the curator turns it into linked wiki pages within minutes. |
| mcp | `windows_ask` | Ask Claude Code on the owner's Windows PC about files there, for example a project in C:\Programming. It can only read, only inside the folders the owner allows (see windows_status), and not key or password files. It cannot run anything, change anything or go on the web. folder: a full Windows path inside an allowed folder; empty for the first allowed one. Returns a number at once; then call windows_result(id, wait_seconds=45) until it is done and pass the answer on. |
| mcp | `windows_result` | The status or answer of a question to Windows (from windows_ask). wait_seconds (0-50): how long to wait for it to finish before answering. Call again while it is still running. |
| mcp | `windows_status` | How the owner's Windows PC is right now: whether it answers, free memory and disk, which folders Claude Code may read there, whether Claude Code is signed in, and whether Remote Control and the desktop app run. Read-only. |
