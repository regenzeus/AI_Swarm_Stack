#!/bin/sh
# Curator profile: maintains the vault wiki (ingest, lint). Applied inside the Hermes container:
#   docker exec -u hermes aistack-hermes-1 sh /config/configure-curator.sh
# Own LiteLLM key (vk-curator: subscription only). File tools for /vault only
# (HERMES_WRITE_SAFE_ROOT). No web, no shell, no messaging, no user memory: it reads untrusted
# sources, so it gets no channel to send data anywhere.
set -e
hermes profile list 2>/dev/null | grep -q curator || hermes profile create curator >/dev/null
c() { hermes -p curator config set "$1" "$2" >/dev/null && echo "set $1"; }
c model.provider custom
c model.default gpt-sub-fast
c model.base_url http://litellm:4000/v1
c model.key_env LITELLM_CURATOR_KEY
for t in compression vision web_extract session_search background_review curator title_generation; do
  c auxiliary.$t.provider custom
  c auxiliary.$t.model gpt-sub-fast
  c auxiliary.$t.base_url http://litellm:4000/v1
  c auxiliary.$t.api_key '${LITELLM_CURATOR_KEY}'
done
c auxiliary.title_generation.enabled false
c auxiliary.background_review.enabled false
c memory.memory_enabled false
c memory.user_profile_enabled false
c agent.disabled_toolsets '["web","browser","terminal","code_execution","computer_use","image_gen","tts","vision","delegation","connections","memory","cronjob","send_message"]'
c telemetry.enabled false
c updates.check false

# Profiles read their own .env, not the container environment: hand the curator its key (owner-only file).
umask 077
# the key line follows the current key, a rotated one included; an unset one leaves what is there (review MEM-R17)
if [ -n "$LITELLM_CURATOR_KEY" ]; then touch /opt/data/profiles/curator/.env; sed -i '/^LITELLM_CURATOR_KEY=/d' /opt/data/profiles/curator/.env; printf 'LITELLM_CURATOR_KEY=%s\n' "$LITELLM_CURATOR_KEY" >> /opt/data/profiles/curator/.env; else echo "LITELLM_CURATOR_KEY is not set: /opt/data/profiles/curator/.env keeps its LITELLM_CURATOR_KEY" >&2; fi
chmod 600 /opt/data/profiles/curator/.env; chmod go-w /opt/data/profiles/curator
c platforms.telegram.enabled false
c platforms.api_server.enabled false
sh /config/install-runtime-plugin.sh curator   # the live run record (Mission Control)
