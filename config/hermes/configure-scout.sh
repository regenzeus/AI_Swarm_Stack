#!/bin/sh
# Scout profile: web research only. Applied inside the Hermes container:
#   docker exec -u hermes aistack-hermes-1 sh /config/configure-scout.sh
# Search: DuckDuckGo (ddgs, keyless). Page reading: the isolated "fetch" MCP server via LiteLLM.
# Own key vk-scout (subscription only). No files, shell, memory, messaging, vault search.
# Lethal-trifecta split: the scout reads untrusted pages but holds no private data and no way to send any.
set -e
hermes profile list 2>/dev/null | grep -q " scout " || hermes profile create scout >/dev/null
umask 077
grep -q '^LITELLM_SCOUT_KEY=' /opt/data/profiles/scout/.env 2>/dev/null \
  || printf 'LITELLM_SCOUT_KEY=%s\n' "$LITELLM_SCOUT_KEY" >> /opt/data/profiles/scout/.env
chmod 600 /opt/data/profiles/scout/.env; chmod go-w /opt/data/profiles/scout
c() { hermes -p scout config set "$1" "$2" >/dev/null && echo "set $1"; }
c model.provider custom
c model.default gpt-sub-fast
c model.base_url http://litellm:4000/v1
c model.key_env LITELLM_SCOUT_KEY
for t in compression vision web_extract session_search background_review curator title_generation; do
  c auxiliary.$t.provider custom
  c auxiliary.$t.model gpt-sub-fast
  c auxiliary.$t.base_url http://litellm:4000/v1
  c auxiliary.$t.api_key '${LITELLM_SCOUT_KEY}'
done
c auxiliary.title_generation.enabled false
c auxiliary.background_review.enabled false
c memory.memory_enabled false
c memory.user_profile_enabled false
c web.search_backend ddgs
# ddgs must be in the dependency environment Hermes runs from. Once Hermes has made its own (/opt/data/installs,
# first on 2026-10-28 for the anthropic extra), a launch uses only that one and drops the image's .venv, where the
# Dockerfile puts ddgs: every search then failed with "ddgs package is not installed" (FND-10). Hermes' own ddgs
# extra (the same pin) goes into it; extras are merged, so the ones already there stay.
hermes pm install --extra ddgs >/dev/null && echo "ddgs extra in Hermes' environment"
c agent.disabled_toolsets '["browser","terminal","file","code_execution","computer_use","image_gen","tts","vision","delegation","connections","memory","cronjob","send_message","session_search"]'
# Search without page extraction: the "web" toolset also has web_extract, which would read pages from inside Hermes
# (not isolated). "search" is web_search only (ddgs); pages are read only by the isolated fetch container.
for pf in cli api_server; do
  c platform_toolsets.$pf '["search"]'          # research only: skills cost ~2.7k tokens per call and were read 23x per run
done
c mcp_servers.webfetch.url http://litellm:4000/mcp/
c mcp_servers.webfetch.headers.Authorization 'Bearer ${LITELLM_SCOUT_KEY}'
c mcp_servers.webfetch.tools.prompts false     # the MCP prompt/resource helpers: 4 tool schemas never used
c mcp_servers.webfetch.tools.resources false
c platforms.telegram.enabled false
# Tools eager, no tool_search/tool_call bridge: the subscription models fumbled the indirection (never searched)
c tools.tool_search.enabled off
c telemetry.enabled false
c updates.check false

# The scout is called as an agent through the API server's /p/scout/ route (multiplexed gateway), by the
# "research" MCP adapter. Its route needs its own key, separate from main's API_SERVER_KEY.
grep -q '^API_SERVER_KEY=' /opt/data/profiles/scout/.env 2>/dev/null \
  || printf 'API_SERVER_KEY=%s\n' "$SCOUT_API_KEY" >> /opt/data/profiles/scout/.env
c platforms.api_server.enabled true
sh /config/install-runtime-plugin.sh scout   # the live run record (Mission Control)
