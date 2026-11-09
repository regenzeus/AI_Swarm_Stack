#!/bin/sh
# Mission profile: the agent that works on long-term missions for Mission Control (ops/missions.py runs
# `hermes -p mission -z <prompt>`, one run at a time). Applied inside the Hermes container:
#   docker exec -e LITELLM_MISSION_KEY="$VK_MISSION" -u hermes aistack-hermes-1 sh /config/configure-mission.sh
# Own key vk-mission (subscription only), so every mission run's calls and cost are its own.
# Tools: the memory tool (MEM-28) and web research (research -> scout) via the LiteLLM MCP gateway. No files, shell,
# memory writes or messaging: the runner files results into the vault and delivers them.
set -e
hermes profile list 2>/dev/null | grep -q " mission " || hermes profile create mission >/dev/null
umask 077
# the key line follows the current key, a rotated one included; an unset one leaves what is there (review MEM-R17)
if [ -n "$LITELLM_MISSION_KEY" ]; then touch /opt/data/profiles/mission/.env; sed -i '/^LITELLM_MISSION_KEY=/d' /opt/data/profiles/mission/.env; printf 'LITELLM_MISSION_KEY=%s\n' "$LITELLM_MISSION_KEY" >> /opt/data/profiles/mission/.env; else echo "LITELLM_MISSION_KEY is not set: /opt/data/profiles/mission/.env keeps its LITELLM_MISSION_KEY" >&2; fi
chmod 600 /opt/data/profiles/mission/.env; chmod go-w /opt/data/profiles/mission
c() { hermes -p mission config set "$1" "$2" >/dev/null && echo "set $1"; }
c model.provider custom
c model.default gpt-sub
c model.base_url http://litellm:4000/v1
c model.key_env LITELLM_MISSION_KEY
for t in compression vision web_extract session_search background_review curator title_generation; do
  c auxiliary.$t.provider custom
  c auxiliary.$t.model gpt-sub-fast
  c auxiliary.$t.base_url http://litellm:4000/v1
  c auxiliary.$t.api_key '${LITELLM_MISSION_KEY}'
done
c auxiliary.title_generation.enabled false
c auxiliary.background_review.enabled false
c memory.memory_enabled false
c memory.user_profile_enabled false
# Token budget (docs/TOKENS.md): skills (index + 3 tools, ~2.7k tokens on every call; 20 skill_view reads of up to 14k
# characters in one run), clarify (an unattended run has nobody to answer) and session_search (17k-character results)
# are off; the vault and research tools stay.
c agent.disabled_toolsets '["web","browser","terminal","file","code_execution","computer_use","image_gen","tts","vision","delegation","connections","memory","cronjob","send_message","skills","clarify","session_search"]'
c mcp_servers.vault.url http://litellm:4000/mcp/
c mcp_servers.vault.headers.Authorization 'Bearer ${LITELLM_MISSION_KEY}'
c mcp_servers.vault.timeout 600
c mcp_servers.vault.tools.prompts false
c mcp_servers.vault.tools.resources false
c platforms.telegram.enabled false
c platforms.api_server.enabled false
# Tools eager, no tool_search/tool_call bridge: the subscription models fumbled the indirection (never searched)
c tools.tool_search.enabled off
c telemetry.enabled false
c updates.check false
# SOUL.md is prompts/mission.md SOUL (MEM-11), handed in by ops/deploy.py as SOUL_TEXT
if [ -n "${SOUL_TEXT:-}" ]; then printf '%s\n' "$SOUL_TEXT" > /opt/data/profiles/mission/SOUL.md; echo "set SOUL.md"
else echo "SOUL.md kept: no SOUL_TEXT given (ops/deploy.py hands it in from prompts/mission.md)"; fi
sh /config/install-runtime-plugin.sh mission   # the live run record (Mission Control)
