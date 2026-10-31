# images/: one directory per custom container image

| Image | What it is |
|---|---|
| `mission-control/` | the app, its API and the mission MCP tools |
| `litellm/` | the model gateway, with a build-time patch for streamed tool calls |
| `hermes/` | Hermes Agent plus the extras the profiles need |
| `builder/` | the coding sandbox (Hermes + shell tools) |
| `desk/` | Topic Desk: daily briefings |
| `research/` | MCP tool `research(question)` that runs the scout |
| `fetch/` | the isolated page reader (HTML and PDF) |
| `pricewatch/` | changedetection.io, sealed: the shopping agents' price watch |
| `qmd/` | hybrid search over the vault, with its MCP server |
| `graphify/` | code knowledge graphs + MCP query server |
| `opencode/` | OpenCode coding server and web UI |
| `pkgproxy/` | allow-listed npm / PyPI proxy for sandboxes |
| `portfwd/` | publishes a port for a service on an internal network |
| `tools/` | one-shot tools (document conversion) |
| `ci-runner/` | the Forgejo Actions runner, which is also the image `make check` uses |

Each directory holds a `Dockerfile`, the image's code, and an `AGENTS.md`.

## Rules for every image

- The `Dockerfile` starts with a comment block: what the image does, which networks it expects, and what it must
  not have.
- **Pin everything**: base image tags (or the `ARG` from `versions.env`), `pip install name==x.y.z`, `npm i
  name@x.y.z`, downloaded files by version. No `latest`.
- Run as a non-root user (`useradd -r -u <uid>`, `USER`), unless the upstream image manages users itself.
- Code that a container runs belongs in its image directory, copied in by the `Dockerfile`. Host-side code
  belongs in `ops/`.
- Images are tagged `aistack/<name>:<version>` in `compose/`. Bump the tag when behaviour changes, so
  `ops/deploy.py` rebuilds and recreates it.
- Keep images small: `--no-cache-dir`, clean apt lists, multi-stage builds where a build tool isn't needed at run time.
