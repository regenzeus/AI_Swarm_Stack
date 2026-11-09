# Glossary

The names requirements use for the parts of the stack. A requirement's subject is always one of these.

| Term | Means | Lives in |
|---|---|---|
| the owner | The owner, the only user; the only one who approves, declines, grants, buys and deploys | |
| the stack | the whole system: the PC (WSL, rootless Docker), the NAS, the phone, the tailnet | |
| Mission Control, the app | the web app (Starlette API + vanilla JS PWA) and its MCP tools; never runs jobs | `images/mission-control/` |
| the runner | the host process that runs every job and validates every request | `ops/missions.py` (+ `mission_extras.py`, `builds.py`, `improve.py`, …) |
| the gateway | LiteLLM: models, per-agent keys, MCP servers, call records | `config/litellm/`, `images/litellm/` |
| Hermes | the agent runtime; profiles main (the assistant), scout (the only web reader), curator, mission, builder | `config/hermes/`, `images/hermes/` |
| the scout | Hermes' scout profile behind the research tool and its privacy guard | `images/research/` |
| the page reader | the isolated fetch container (HTML and PDF) | `images/fetch/` |
| the browser | the scout's Playwright browser behind its guard; only looks | `images/browser/` |
| the builder | the coding sandbox; engines Hermes (ChatGPT) and Claude Code (Claude) | `images/builder/`, `ops/builds.py` |
| Claude task | a read-only question Hermes hands to Claude Code in the builder sandbox | `ops/claude_tasks.py` |
| the crew | housekeeping agents on systemd timers (doctor, maintainability, tests, memory, phone cleanup, phone check, inbox) | `ops/crew.py`, `ops/systemd/crew-*` |
| the health board | one health item per agent with alerts and notes | `images/mission-control/obs_core.py`, `ops/observe.py` |
| the runtime record | one event stream for every agent run, with end states and the watchdog | `images/mission-control/runrecord.py` |
| the AI phone | a spare Android phone on the tailnet | |
| the AI phone service | the container that drives the AI phone over ADB, with approvals, block list and Stop | `images/phone/` |
| the mail connector | the Gmail connector (IMAP), grants, Trash only | `images/mail/` |
| the House service | the stack's side of Home Assistant: status, switching, Alexa, the voice bridge | `ops/house.py` |
| the vault | the Obsidian vault in git (`C:\AI\vault`, `/srv/vault`) | `vault-template/` |
| the journal | an agent's own memory, `vault/agents/<agent>/MEMORY.md` | `ops/journal.py` |
| a mission | a standing job described by `vault/missions/<slug>/MISSION.md` | |
| a proposal | a build idea from the self-review, a reviewer or the doctor, waiting for the owner | `missions.sqlite` table `proposals` |
| a time window | the owner's allowance for the AI phone to act without asking, for minutes or until he stops it | `images/phone/phone.py` |
| a grant | the owner's time-limited permission for a connection scope (mail read, organize, trash) | `images/mail/`, Mission Control |
| usage limit | the subscription's 5-hour window being used up; jobs wait and retry | |
| the swarm | the planned registry, ledger, board and chatroom (`swarm.yaml`) | not built |
| the Swarm service | the planned service that holds the Registry, the Ledger, the Board and the Checker | not built |
| an agent card | one agent's entry in `config/agents.yaml`: job, harness, model, key, roles, rooms, policies | not built |
| the Registry | the agent cards, and what is generated from them | not built |
| the Ledger | the store of every agent-produced artifact, with its events | not built |
| an artifact | one Ledger record (idea, finding, report, wiki page, purchase, build, agent change, requirement) | not built |
| the Board | messages between agents and the owner: direct, to a role, to a room, in an artifact's thread | not built |
| the Chatroom | Mission Control's live page over the Board | not built |
| the Checker | code without a model that runs success checks and moves artifacts to done or back to open | not built |
| the Coach | the monthly agent that turns scorecards into agent-change artifacts, each replayed before it may ship | ops/coach.py |
| a context pack | what an agent reads at the start of a run: owner messages, requests, artifacts, lessons, journal | not built |
| the run contract | the start and finish steps every agent run follows on every harness | not built |
| a harness adapter | the glue that gives one harness the swarm tools, the run contract and wakes | not built |
| a success check | a typed, machine-run test of whether an artifact achieved its goal | not built |
| a wake | a request to the runner to start an agent's run early because a message waits for it | not built |
