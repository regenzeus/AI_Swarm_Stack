# compose/: every service of the stack

| File | Contents |
|---|---|
| `core.yaml` | The foundation: LiteLLM (model gateway), Postgres (its database), Phoenix (traces), Ollama (smoke-test model only) |
| `apps.yaml` | Everything else: Hermes, Mission Control, builder, qmd, Hindsight, research/fetch, desk, Open WebUI, OpenCode, Graphify, code map, pkgproxy (and the builder's own), CI runner, the AI phone, the Gmail connector, the scout's browser, the price watch, the Swarm service |
| `rehearsal.yaml` | Override for the new-PC rehearsal (`ops/windows/rehearse-new-pc.ps1`): scales host-bound services to 0 |

Run through `make` only (`make up`, `make ps`, `make logs`): the Makefile decrypts the secrets into compose's
environment. Project name `aistack`; images pinned in `../versions.env` or built from `../images/<name>`.

## Rules for every service

- **Ports**: `127.0.0.1:<port>:<port>` only. Outside access is `tailscale serve` on Windows, never a public bind.
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
