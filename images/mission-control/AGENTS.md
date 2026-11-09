# images/mission-control/: the app

| Path | What it is |
|---|---|
| `server.py` | Starlette app: the API for the front end (port 8090) and the MCP tools for Hermes (port 8091); the runtime ingest (port 8093, `POST /ingest`, `GET /problems`, `GET /view/<run>` for the runner's journal entries) |
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

- Every `/api/*` route needs the `Tailscale-User-Login` header (middleware `TailnetOnly`). Don't add exceptions.
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
