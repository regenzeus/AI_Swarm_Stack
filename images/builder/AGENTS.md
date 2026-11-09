# images/builder/: the coding sandbox

Hermes (profile config: `config/hermes/configure-builder.sh`) with a shell and file tools, plus the repo's check
tools (shellcheck, ruff, pytest and the test dependencies) so it can run `ops/check.sh` itself. It sees `/work` (the
workbench clones in `/srv/ai/workbench`) and nothing else: no vault, secrets, SSH keys or Docker socket. Networks:
LiteLLM (its own key `vk-builder`) and `pkgproxy` (npm + PyPI only).

Two engines (`builds.engine`): Hermes on the ChatGPT subscription and Claude Code (the default once connected; `claude -p`, pinned in the
`Dockerfile`, stream-json output parsed into the same live steps). The Claude token never lives in the container: the
runner passes `CLAUDE_CODE_OAUTH_TOKEN` per run. The builder's proxy is `pkgproxy-builder` (`images/pkgproxy/
allow-builder.txt`: npm, PyPI, `api.anthropic.com`).

Both engines get **Serena** (pinned in the `Dockerfile`), an MCP server with language-server code tools (find a
symbol, its references, rename, replace a body). Its language servers (Python, TypeScript, Bash) are downloaded at image
build into `/opt/serena-home/.serena` (Serena's server only reads `$HOME/.serena`; don't set `SERENA_HOME`, the
downloader would use a different folder); the sandbox cannot fetch them. `serena-mcp` starts it on the repo in the working
directory. Hermes: `mcp_servers.serena` in `configure-builder.sh`; Claude: `--mcp-config` in `ops/builds.py`.
`.serena/` is git-excluded in every workbench clone.
Both engines also get **the code graph** (MCP server `graph` = Graphify through LiteLLM's `/mcp/` gateway; `vk-builder` is
granted only `graphify`): structure questions (who depends on this, how two parts connect, core abstractions) on the
repos' main branches, refreshed by `ops/graphify-sync.sh`. Hermes: `mcp_servers.graph`; Claude: `graph` in
`SERENA_FOR_CLAUDE` (builds) and the read-only graph tools in `claude_tasks.MODES`.

Flow (`ops/builds.py`): assignment → branch `builder/<id>-<slug>` → the builder implements, runs the checks,
commits → the host runner pushes → Forgejo CI → the owner reviews and taps Approve → `ops/deploy.py` (rollback on
failure).

## Rules

- The sandbox boundary is the point of this image. Never add a mount, network, credential or the Docker socket.
- Runs as user `hermes`. The runner wraps commands in `umask 000` so the host runner and the builder can share the
  workbench.
- Keep the check tools' pins equal to `tests/requirements.txt` and `.forgejo` CI, so the builder's checks match CI.
