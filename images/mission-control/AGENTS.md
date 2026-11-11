# images/mission-control/: the app

| Path | What it is |
|---|---|
| `server.py` | Starlette app: the API for the front end (port 8090) and the MCP tools for Hermes (port 8091); the runtime ingest (port 8093, `POST /ingest`, `GET /problems`, `GET /view/<run>` for the runner's journal entries) |
| `server.frames.py` | part of `server.py` (WFL-14, APP-66, APP-85, APP-86): the app holds n8n's session for the owner's own signed-in session (`make n8n-login`; its cookie and browser id in memory, never handed to a browser, signed in again once on a 401) and refuses from the frame what would change what runs (publish, run, archive, delete, share, retry); the stack's tools inside the app, each under the app's own address behind the `TailnetOnly` gate: n8n's editor at `/n8n/` (`http://n8n:5678` on `stepnet`), Phoenix at `/phoenix/` (`http://phoenix:6006` on `obs`); the prefix taken off for the tool, everything streamed (n8n's live updates are SSE), framing for the app's own pages only |
| `server.n8n.py` | part of `server.py` (WFL-14): `GET /api/workflows` serves the runner's `public/workflows-runs.json` |
| `server.workflows.py` | part of `server.py` (APP-71 to APP-73): everything as workflows and runs, read-only: `GET /api/factory` (every workflow by factory and area, the n8n ones with their diagram and the standard Request, Change and Briefing with the old sources' records as their runs), `/api/factory/workflow/<id>` (its page: card, diagram, runs), `/api/factory/workflow/<id>/canvas` (what runs, for n8n's read-only canvas, read with the app's n8n session; triggers named without their cron) and `/api/factory/run/<workflow>/<run>` (the path it took, its Asks) |
| `server.tax.py` | part of `server.py` (TAX-10, TAX-11): `GET /api/tax` serves the tax desk's result (`/missions/tax/view.json`, shared with the app's user alone) to the owner's signed-in session only: never the AI phone or `*@stack.local`, never cached |
| `server.records.py` | part of `server.py` (REC-06): `GET /api/records` serves the tracker poller's view of the deployment's records, links and measures (`/missions/public/records.json`, ops/domain/records.py) to a signed-in session, never to the AI phone, never cached |
| `server.stack.py` | part of `server.py` (WAY-01 to WAY-07, docs/CLI.md): the ways in for a site's agents: the `stack` command line's rule in `/api/request` (header `X-Aistack-Via: cli`: only its actions, recorded as via cli), its reads `GET /api/stack/*`, and the MCP server `stack` (port 8100) with the same reads and actions for agents |
| `server.trust.py` | part of `server.py` (SEC-24 to SEC-26): who may speak to the app: port 8090 only through its published port (the gateway of the container's default route), each MCP server only LiteLLM with its own token, the step service only with its token; `APP_TRUST` log (logs what it would refuse) or on (refuses) |
| `runrecord.py` | the agent runtime record: SQLite `/missions/app/runtime.db`, ingest, the closed-run rule, watchdog, drift, what each run touched, retention (docs/OBSERVABILITY.md) |
| `obs_core.py` | pure observability helpers shared with the runner (`ops/observe.py` re-exports them): files, stats, ledger, problems, health |
| `web/` | the front end (vanilla JS PWA), see [web/AGENTS.md](web/AGENTS.md) |
| `guide/` | the in-app guide's chapters, see [guide/AGENTS.md](guide/AGENTS.md) |
| `icons.py` | generates the app icons at build time |
| `Dockerfile` | python:3.12-slim, vendored front-end libraries, user `mc` (uid 10006), read-only rootfs |

## How it works

The app **never runs jobs**. It reads the host runner's state (`/missions/public/state.json`, pushed to clients
over `/api/stream`), drops requests into `/missions/inbox/<id>.json`, and waits briefly for
`/missions/public/results/<id>.json`. `ops/missions.py` validates and executes every request. Chat is the exception:
the app talks to Hermes directly (server-side task + resumable SSE), and chats live in `/missions/app/chats`.

## Rules

- Every `/api/*` route needs the `Tailscale-User-Login` header (middleware `TailnetOnly`), and so do `/share` and
  each tool inside the app (`/n8n/`, `/phoenix/`: `FRAMES` in `server.frames.py`). Don't add exceptions. The header
  counts only through the published port (SEC-24, `server.trust.py`): nothing in a container may call port 8090.
- A new port gets its guard in `server.trust.py` (a peer and a token), never a bare `0.0.0.0` listener.
- New request actions go into `ACTIONS` **and** are validated in the runner (`ops/missions.py` `handle`). Never
  trust the request here.
- New MCP tools: a clear description (Hermes reads it), a mention in a guide chapter, and a plain-language line in
  `web/static/guide.js` `TOOL_HELP` (`tests/test_guide.py` enforces both).
- Paths from requests go through the existing guards (`vault_file`, `file_of`, the wiki root checks). Never join
  user input onto a path yourself.
- Files the app writes: write a temporary file, then `rename` (atomic), as `save_chat` and `submit` do.
- This deployment's hosts and accounts reach the app as compose `environment:` (`deployments/home/deployment.env`; `ops/deployment.py` is not in the image). The server
  puts the front end's into the page (`DEPLOY`, `index`); `web/static/tools.json` names them as `{{NAME}}`.
- The container's root filesystem is read-only. Changing files means rebuilding the image (`ops/deploy.py` does it
  when this directory changes).

## Tests

`tests/test_server.py` (API with Starlette's TestClient, temp dirs), `tests/test_guide.py` (guide coverage).
Add a test with every new endpoint.
