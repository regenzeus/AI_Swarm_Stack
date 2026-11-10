# config/hermes/: one script per Hermes profile

| Script | Profile | Purpose |
|---|---|---|
| `configure.sh` | main | the assistant: chat (Mission Control, Telegram, Open WebUI), SOUL rules, MCP tools, memory |
| `configure-scout.sh` | scout | the only web reader: search + page reader, no private data |
| `configure-curator.sh` | curator | weekly tidy-up of vault, wiki and skills (behind the benchmark gate) |
| `configure-mission.sh` | mission | runs long-term mission tasks on its own key (`vk-mission`) |
| `configure-tax.sh` | tax | the tax desk's reader on its own key (`vk-tax`): ChatGPT only, every toolset off, no MCP server (TAX-02) |
| `configure-builder.sh` | builder | the coding sandbox (`builder` container) |

Each script runs **inside** its container (`docker exec -u hermes aistack-hermes-1 sh /config/<script>`) and is
idempotent: it sets every value with `hermes config set` (helper `c`) and rewrites generated files whole.
`ops/deploy.py` runs them after every rebuild.

## Rules

- POSIX `sh` (the image has no bash in every profile), `set -e`.
- Every model setting points at LiteLLM (`http://litellm:4000/v1`) with the profile's own key variable. Never a
  provider directly, never a paid model.
- A profile gets only the toolsets it needs. Web access stays with `scout`.
- Behaviour rules for the assistant (SOUL text) are English and short. Each one says what to do, not just what
  to avoid. Their text lives in prompts/ (main.md `*_RULE`, mission.md and builder.md `SOUL`), not in these scripts:
  ops/deploy.py hands it in as `SOUL_*` variables (`SOUL_OF`) and re-runs the script when that prompts file changes;
  run by hand without them, a script keeps the SOUL text as it is (MEM-11, prompts/AGENTS.md).
- After adding an MCP server or tool, Hermes caches the tool list: the deploy restarts Hermes.

## The runtime plugin and Claude hooks

`plugins/aistack-runtime` reports every model call, tool call and turn end of a profile to Mission Control's runtime
record (docs/OBSERVABILITY.md). It is an observer: hooks return None, never raise, never wait on the network. Each
`configure*.sh` installs it with `install-runtime-plugin.sh [profile]`; `ops/deploy.py` re-installs it in every
profile when it changes. `claude-hooks/` does the same for Claude Code in the builder (passed with `--settings`): the run record, a file's note at its first read and where a wide search's hits fall (`memory_hook.py`), and the repository's linter after an edit (`lint_hook.py`, DEC-49).
Never make either of them block or veto a call.
