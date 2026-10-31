#!/bin/sh
# Builder profile (sandbox container "builder", its own HERMES_HOME): implements code assignments from Mission
# Control. Applied inside that container:  docker exec aistack-builder-1 sh /config/configure-builder.sh
# Shell and file tools run inside the sandbox only (terminal.backend local = this container). No web, no memory,
# no messaging; MCP: Serena (language-server code tools, baked into the image) and the code graph (Graphify through
# LiteLLM; the builder's key is granted only graphify). It reads no untrusted
# web content and holds no private data, so a shell is safe here.
set -e
umask 077
mkdir -p "$HERMES_HOME"
grep -q '^LITELLM_BUILDER_KEY=' "$HERMES_HOME/.env" 2>/dev/null || printf 'LITELLM_BUILDER_KEY=%s\n' "$LITELLM_BUILDER_KEY" >> "$HERMES_HOME/.env"
c() { hermes config set "$1" "$2" >/dev/null && echo "set $1"; }
c model.provider custom
c model.default gpt-sub
c model.base_url http://litellm:4000/v1
c model.key_env LITELLM_BUILDER_KEY
for t in compression vision web_extract session_search background_review curator title_generation; do
  c auxiliary.$t.provider custom
  c auxiliary.$t.model gpt-sub-fast
  c auxiliary.$t.base_url http://litellm:4000/v1
  c auxiliary.$t.api_key '${LITELLM_BUILDER_KEY}'
done
c auxiliary.title_generation.enabled false
c auxiliary.background_review.enabled false
c memory.memory_enabled false
c memory.user_profile_enabled false
c agent.disabled_toolsets '["web","search","browser","memory","delegation","send_message","cronjob","connections","computer_use","image_gen","tts","vision","session_search"]'
c platform_toolsets.cli '["terminal","file","todo","mcp-serena","mcp-graph"]'      # no skills: ~2.7k tokens per call, unused by builds
# Serena: symbol-level code tools (find_symbol, find_referencing_symbols, replace_symbol_body, rename_symbol...).
# The build runs in /work/<repo>, so --project-from-cwd activates that repo. Context "ide": Hermes keeps its own file
# and shell tools, Serena adds only what it understands about the code.
c mcp_servers.serena.command serena-mcp
c mcp_servers.serena.args '["--context","ide"]'
c mcp_servers.serena.connect_timeout 120
# The code graph of the repos' main branches (structure, callers, paths between parts, core abstractions), read-only
c mcp_servers.graph.url http://litellm:4000/mcp/
c mcp_servers.graph.headers.Authorization 'Bearer ${LITELLM_BUILDER_KEY}'
c mcp_servers.graph.timeout 120
c mcp_servers.graph.tools.prompts false
c mcp_servers.graph.tools.resources false
c terminal.backend local
c terminal.cwd /work
c terminal.timeout 600
# Tools eager, no tool_search/tool_call bridge (the subscription models fumble the indirection)
c tools.tool_search.enabled off
c telemetry.enabled false
c updates.check false
# Hermes asks a human before any write to an instruction file (AGENTS.md, CLAUDE.md, SOUL.md), even under --yolo. The
# builder runs unattended, so that prompt can never be answered and the run stalls ("Input required; detached").
# The human approval for those files happens in the build review instead (ops/builds.py flags them as sensitive), and
# the builder has no secrets and cannot deploy. The main assistant keeps the guard on.
c security.protected_instruction_files false
# SOUL.md is prompts/builder.md SOUL (MEM-11), handed in by ops/deploy.py as SOUL_TEXT
if [ -n "${SOUL_TEXT:-}" ]; then printf '%s\n' "$SOUL_TEXT" > "$HERMES_HOME/SOUL.md"; echo "set SOUL.md"
else echo "SOUL.md kept: no SOUL_TEXT given (ops/deploy.py hands it in from prompts/builder.md)"; fi
sh /config/install-runtime-plugin.sh          # the live run record: spooled to /work/.runtime (RUNTIME_SPOOL), the runner forwards it
d="${CLAUDE_CONFIG_DIR:-/builder/claude}"; mkdir -p "$d"; chown hermes:hermes "$d"   # Claude Code's state and transcripts (the runtime hook reads them)
chown -R hermes:hermes "$HERMES_HOME"   # last: Hermes (uid hermes) wants everything in its home owned by its user
