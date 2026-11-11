# compose/: every service of the stack

| File | Contents |
|---|---|
| `core.yaml` | The foundation: LiteLLM (model gateway), Postgres (its database), Phoenix (traces), Ollama (smoke-test model only) |
| `apps.yaml` | Everything else: Hermes, Mission Control, builder, qmd, Hindsight, research/fetch, desk, Open WebUI, OpenCode, Graphify, code map, pkgproxy (and the builder's own), CI runner, the AI phone, the Gmail connector, the scout's browser, the price watch, the Swarm service |
| `rehearsal.yaml` | Override for the new-PC rehearsal (`ops/windows/rehearse-new-pc.ps1`): scales host-bound services to 0 |

Run through `make` only (`make up`, `make ps`, `make logs`): the Makefile decrypts the secrets into compose's
environment. Project name `aistack`; images pinned in `../versions.env` or built from `../images/<name>`. This deployment's
hosts and paths come from `../deployments/home/deployment.env`, the second `--env-file` of every compose call (PLT-33); a container
gets what it needs under `environment:`, as `${NAME:?run via make}`.

## Every service by name

| Service | File | What it is |
|---|---|---|
| `postgres` | core | LiteLLM's database (keys, spend logs), and n8n's database under its own role (n8n reaches it on `n8ndb` only) |
| `litellm` | core | the model gateway: every model call and MCP tool server, one virtual key per agent |
| `phoenix` | core | traces of the model calls and task runs |
| `ollama` | core | the smoke test's tiny model, reachable only through LiteLLM with vk-smoke |
| `n8n-db` | core | one-shot at each start: n8n's role and database in `postgres`, safe to repeat (WFL-02) |
| `n8n` | core | the workflow pillar (n8n, DEC-51): schedules, triggers, waits and the canvas; on 127.0.0.1:5678 for the runner and tailscale serve's port 8450 for its resume links only; networks `n8ndb` (its database), `flows`, `stepnet`, never `backend` (SEC-27); read-only root, no capabilities, its public API off (SEC-28); every webhook asks for the runner's header (SEC-27); its editor is inside the app (`N8N_PATH=/n8n/`, SSE live updates, Mission Control proxies it on `stepnet`, WFL-14); the stack's steps through Mission Control's step service on `stepnet` (WFL-01, WFL-05). Without the tailnet its addresses are the deployment's, on 127.0.0.1 (`N8N_EDITOR_URL`, `N8N_WEBHOOK_URL`, WFL-15), and customer data loads only the deployment's `N8N_NODES_INCLUDE` (WFL-17) |
| `hermes` | apps | the assistant (Hermes Agent) with its profiles: main, scout, mission, curator |
| `hermes-dashboard` | apps | Hermes' own admin UI, in Hermes' network namespace |
| `gate-hermes-dashboard` | apps | the tailnet sign-in gate in front of the Hermes dashboard |
| `openwebui` | apps | Open WebUI, the second chat front end |
| `mission-control` | apps | the app (phone and desktop), its MCP servers, the run record's ingest and the voice gateway; port 8090 answers only through its published port, its MCP servers only LiteLLM with their tokens, its step service only n8n's node with its token (`APP_TRUST`, SEC-24 to SEC-26) |
| `qmd` | apps | the vault's search index (keywords and meaning) as MCP |
| `research` | apps | the research tool: one question to the scout profile |
| `fetch` | apps | the scout's page reader, internet only through its egress firewall |
| `browser` | apps | the scout's look-only browser (shops), behind its guard |
| `pricewatch` | apps | the shopping agents' price watch (changedetection.io) |
| `graphify` | apps | the code knowledge graph across ~/code as MCP |
| `opencode` | apps | OpenCode, the coding agent of Conductor steps (no internet) |
| `opencode-port` | apps | publishes OpenCode's web UI on 127.0.0.1:4096 (portfwd), so OpenCode stays on internal networks |
| `pkgproxy` | apps | npm and PyPI for OpenCode and nothing else |
| `pkgproxy-builder` | apps | the builder's own proxy: the same registries plus api.anthropic.com for its Claude Code engine |
| `builder` | apps | the build sandbox (Hermes and Claude Code engines, checks, Serena), its own clones |
| `ci-runner` | apps | the Forgejo Actions runner (CI), no Docker socket |
| `hindsight` | apps | long-term memory (facts from conversations) |
| `hindsight-db` | apps | Hindsight's Postgres with pgvector |
| `phone` | apps | the AI phone's tools (ADB over Tailscale), behind approvals |
| `mail` | apps | the Gmail connector's tools, behind time-limited grants |
| `swarm` | apps | the swarm's Ledger, Board and doors |

## Rules for every service

- **Ports**: `127.0.0.1:<port>:<port>` only. Outside access is `tailscale serve` on Windows, never a public bind. The
  data guard refuses a customer deployment while any port is on another address (WFL-18). Without the tailnet the app's
  gate is `APP_GATE=local` (WFL-16).
- **Limits**: every service has `mem_limit` and the shared logging block (`json-file`, 10 MB × 3). The Stack page
  shows memory against `mem_limit`, so set a realistic one. The WSL VM has 10 GB in total.
- **Networks**: the least a service needs, one purpose per network (the comment next to each network says which).
  Internal-only networks are `internal: true`. Web readers (fetch, desk) sit on `webonly`: internet and LiteLLM,
  no other stack service. The LAN is blocked by fetch's egress firewall and by desk's `public_url()` guard. Nothing
  else gets internet unless it calls a provider (LiteLLM) or a registry through `pkgproxy`.
- **Publishing a port** for a service that is only on internal networks: add a small publish-only network (like
  `ui`, `mcui`), a shared network namespace (the Hermes dashboard and its gate use Hermes' own) or the `portfwd` image, never a shared network.
- **Hardening**: `read_only: true` with explicit `tmpfs` where the image allows it, no `privileged`, never the
  Docker socket in an agent's container.
- **Secrets**: `${VAR:?missing}` for required values, so a missing secret fails loudly. Never inline a value.
- **Healthchecks** on anything another service depends on (`depends_on: condition: service_healthy`).

## Changing it

Add the service in the right file, mirror its line in `rehearsal.yaml` if it is host-bound, add it to `README.md`
(Components), the guide's live map (`images/mission-control/web/static/guide.js`, `ARCH`) and `ops/deploy.py` if it
needs reconfiguration after a rebuild. `make check` validates the files (`ops/ci-compose-check.sh`).
