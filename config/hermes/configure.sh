#!/bin/sh
# Hermes main-profile configuration, applied inside the container:
#   docker exec -u hermes aistack-hermes-1 sh /config/configure.sh
# Idempotent. Every model call goes through LiteLLM on the budget-capped key in $LITELLM_API_KEY.
set -e
c() { hermes config set "$1" "$2" >/dev/null && echo "set $1"; }

# Main model: ChatGPT subscription via LiteLLM
c model.provider custom
c model.default gpt-sub
c model.base_url http://litellm:4000/v1
c model.key_env LITELLM_API_KEY

# Side tasks on the faster subscription model; no paid models anywhere
for t in compression vision web_extract session_search background_review curator title_generation; do
  c auxiliary.$t.provider custom
  c auxiliary.$t.model gpt-sub-fast
  c auxiliary.$t.base_url http://litellm:4000/v1
  c auxiliary.$t.api_key '${LITELLM_API_KEY}'
done
c auxiliary.title_generation.enabled false

# Memory: writes from the API server / gateway / background review are staged for approval
c memory.write_approval true

# MVP 1 toolsets: chat, memory, skills, cron only. No web, browser, shell, files, code, computer use.
c agent.disabled_toolsets '["web","browser","terminal","file","code_execution","computer_use","image_gen","tts","vision","delegation","connections"]'

# No phoning home, no self-updates (upgrades happen in the monthly window)
# Tools eager, no tool_search/tool_call bridge: the subscription models fumbled the indirection (never searched)
c tools.tool_search.enabled off
c telemetry.enabled false
c updates.check false

# Vault search (qmd) through the LiteLLM MCP gateway, on this profile's own key.
c mcp_servers.vault.url http://litellm:4000/mcp/
c mcp_servers.vault.headers.Authorization 'Bearer ${LITELLM_API_KEY}'
c mcp_servers.vault.timeout 1000         # research takes minutes, an AI phone action waits up to 15 min for the owner's OK

# Delegation stays off: a delegated child can never have more tools than main (no web), so web research
# runs as a separate agent behind the research MCP tool instead. inherit_mcp_toolsets=false kept as a guard.
hermes plugins disable advanced-delegation >/dev/null 2>&1 || true
c agent.disabled_toolsets '["web","browser","terminal","file","code_execution","computer_use","image_gen","tts","vision","delegation","connections"]'
c delegation.backend default
c delegation.inherit_mcp_toolsets false
c delegation.max_iterations 25

# Standing rules in Hermes main's SOUL.md (MEM-11): rule <r> is prompts/main.md <R>_RULE, handed in by ops/deploy.py as
# SOUL_<R>; each sits in its own marked block, rewritten on every run. Run by hand without them, a rule stays as it is.
# web: web questions go to the research tool. missions: missions are run through the missions tools. shopping: wishes
# become shopping agents; buying needs the owner's own tap. language: always English. phone: the AI phone and what it leaves
# to the owner. claude: what to give Claude Code and what to do yourself.
for r in web missions shopping language phone claude; do
  v=$(printenv "SOUL_$(echo "$r" | tr a-z A-Z)") || { echo "$r rule kept: no SOUL_$r given (ops/deploy.py hands it in from prompts/main.md)"; continue; }
  sed -i "/BEGIN ai-stack $r rule/,/END ai-stack $r rule/d" /opt/data/SOUL.md 2>/dev/null || true
  printf '\n<!-- BEGIN ai-stack %s rule -->\n%s\n<!-- END ai-stack %s rule -->\n' "$r" "$v" "$r" >> /opt/data/SOUL.md
done
# Deleting a block leaves the blank line before it: squeeze repeated blank lines, or they pile up with every run.
if [ -f /opt/data/SOUL.md ]; then cat -s /opt/data/SOUL.md > /tmp/soul.$$ && cat /tmp/soul.$$ > /opt/data/SOUL.md; rm -f /tmp/soul.$$; fi

# The API key the gateway accepts must be the one in the compose env (Open WebUI, Mission Control use it). The
# dashboard (hermes-dashboard) may write its own API_SERVER_KEY into /opt/data/.env, which then wins over the env:
# keep the file in line with the env.
if [ -n "$API_SERVER_KEY" ]; then
  sed -i '/^API_SERVER_KEY=/d' /opt/data/.env 2>/dev/null || true
  printf 'API_SERVER_KEY=%s\n' "$API_SERVER_KEY" >> /opt/data/.env
  echo "set API_SERVER_KEY (.env = compose env)"
fi

# One gateway process serves all profiles; secondary profiles get /p/<profile>/ API routes.
c gateway.multiplex_profiles true
# No "Hermes is shutting down" / restart notices on Telegram: every deploy that touches Hermes restarts it, and the
# notices reached the owner several times a day. Mission Control's Agent health reports a Hermes that stays down.
c telegram.gateway_restart_notification false

# MVP 6: skills the agent writes are security-scanned on write (dangerous findings are refused). The built-in
# weekly curator is paused; ops/curate.sh runs it instead, behind the benchmark gate with automatic rollback.
c skills.guard_agent_created true
c curator.consolidate true
c curator.backup.keep 6
hermes curator pause

# Long-term memory: Hindsight, self-hosted (compose service "hindsight", reachable only on memnet). The plugin is
# installed at the catalog pin; its Python deps are in the image. MEMORY.md/USER.md stay the small curated core
# (with approval); Hindsight keeps everything else: facts, entities and observations from every conversation.
[ -d /opt/data/plugins/hindsight ] || hermes plugins install hindsight --no-enable >/dev/null 2>&1 || true
mkdir -p /opt/data/hindsight
cat > /opt/data/hindsight/config.json <<JSON
{
  "mode": "local_external",
  "api_url": "http://hindsight:8888",
  "bank_id": "owner",
  "memory_mode": "hybrid",
  "recall_budget": "mid",
  "recall_types": "observation,world,experience",
  "recall_indicator": false,
  "retain_indicator": false,
  "retain_source": "hermes",
  "timeout": 60
}
JSON
echo "set hindsight config"
c memory.provider hindsight
sh /config/install-runtime-plugin.sh        # the live run record (Mission Control)
c memory.nudge_interval 0          # Hindsight extracts per turn; the built-in periodic review would double it
