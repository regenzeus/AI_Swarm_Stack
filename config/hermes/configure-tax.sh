#!/bin/sh
# Tax profile: the tax desk's reader (ops/tax.py, TAX-02). The Conductor's Hermes adapter runs `hermes -p tax -z <prompt>`
# for one mail or one earlier return at a time. Applied inside the Hermes container:
#   docker exec -e LITELLM_TAX_KEY="$VK_TAX" -u hermes aistack-hermes-1 sh /config/configure-tax.sh
# Own key vk-tax, ChatGPT only (gpt-sub, also for every auxiliary task): the owner chose ChatGPT as the one reader of tax
# content, so no Claude and no other model. No tools at all: no MCP server, no web, no files, no memory, no delegation;
# it reads the text it is given and answers JSON. The desk files and prepares without a model.
set -e
hermes profile list 2>/dev/null | grep -q " tax " || hermes profile create tax >/dev/null
umask 077
# the key line follows the current key, a rotated one included; an unset one leaves what is there (review MEM-R17)
if [ -n "$LITELLM_TAX_KEY" ]; then touch /opt/data/profiles/tax/.env; sed -i '/^LITELLM_TAX_KEY=/d' /opt/data/profiles/tax/.env; printf 'LITELLM_TAX_KEY=%s\n' "$LITELLM_TAX_KEY" >> /opt/data/profiles/tax/.env; else echo "LITELLM_TAX_KEY is not set: /opt/data/profiles/tax/.env keeps its LITELLM_TAX_KEY" >&2; fi
chmod 600 /opt/data/profiles/tax/.env; chmod go-w /opt/data/profiles/tax
c() { hermes -p tax config set "$1" "$2" >/dev/null && echo "set $1"; }
c model.provider custom
c model.default gpt-sub
c model.base_url http://litellm:4000/v1
c model.key_env LITELLM_TAX_KEY
for t in compression vision web_extract session_search background_review curator title_generation; do
  c auxiliary.$t.provider custom
  c auxiliary.$t.model gpt-sub
  c auxiliary.$t.base_url http://litellm:4000/v1
  c auxiliary.$t.api_key '${LITELLM_TAX_KEY}'
done
c auxiliary.title_generation.enabled false
c auxiliary.background_review.enabled false
c memory.memory_enabled false
c memory.user_profile_enabled false
c agent.disabled_toolsets '["web","browser","terminal","file","code_execution","computer_use","image_gen","tts","vision","delegation","connections","memory","cronjob","send_message","skills","clarify","session_search"]'
c platforms.telegram.enabled false
c platforms.api_server.enabled false
c tools.tool_search.enabled off
c telemetry.enabled false
c updates.check false
# SOUL.md is prompts/tax.md SOUL (MEM-11), handed in by ops/deploy.py as SOUL_TEXT
if [ -n "${SOUL_TEXT:-}" ]; then printf '%s\n' "$SOUL_TEXT" > /opt/data/profiles/tax/SOUL.md; echo "set SOUL.md"
else echo "SOUL.md kept: no SOUL_TEXT given (ops/deploy.py hands it in from prompts/tax.md)"; fi
sh /config/install-runtime-plugin.sh tax   # the live run record (Mission Control)
