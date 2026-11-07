#!/usr/bin/env bash
# Create the per-agent LiteLLM virtual keys (models + daily budget). Idempotent by key_alias.
# Output is encrypted straight into secrets/agent-keys.enc.yaml; keys are never printed.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${LITELLM_MASTER_KEY:?run via: make keys}"
API=http://127.0.0.1:4000

# alias | models (comma) | daily budget (USD)
KEYS=(
  # Subscription only: no paid models exist in LiteLLM any more (2026-10-27).
  # alias | models | daily budget (USD) | MCP servers (lethal-trifecta split: see docs in the vault/plan)
  # swarm: the agent swarm's Board and Ledger, each key with its own identity (ops/swarm_setup.py agents, SWM-89)
  "vk-main|gpt-sub,gpt-sub-fast|0.15|qmd,research,graphify,missions,phone,claude,mail,house,swarm"
  "vk-code|gpt-sub,gpt-sub-fast|0.10|graphify"
  "vk-curator|gpt-sub-fast|0.10|qmd,swarm"
  "vk-scout|gpt-sub-fast|0.05|fetch,jobs,browser,swarm"
  "vk-memory|gpt-sub-fast|0.05|"         # the crew's memory curator (ops/crew.py memory)
  "vk-ui|gpt-sub-fast|0.02|"
  "vk-hindsight|gpt-sub-fast|0.02|"       # long-term memory extraction (Hindsight server)
  "vk-spec|gpt-sub,gpt-sub-fast|0.01|"            # spec comprehension + code check (spec/): subscription only, never paid
  "vk-spec-cheap|gpt-sub-fast|0.05|"     # was the paid-model experiment key; subscription only now
  "vk-desk|gpt-sub,gpt-sub-fast|0.02|"   # Topic Desk briefings (images/desk)
  "vk-mission|gpt-sub,gpt-sub-fast|0.05|qmd,research,claude,mail,swarm,files"   # Mission Control: long-running agent missions (hermes -z on this key)
  "vk-builder|gpt-sub,gpt-sub-fast|0.05|graphify"   # builder sandbox (Mission Control Build): code assignments; the code graph (read-only)
  "vk-guard|gpt-sub-fast|0.02|"          # research privacy check (images/research)
  # background jobs: one key each, so a mission run's cost window holds only its own calls (FND-03)
  "vk-review|gpt-sub,gpt-sub-fast|0.02|"       # the weekly self-review (ops/improve.py)
  "vk-intake|gpt-sub,gpt-sub-fast|0.02|"       # the task intake: a task given in a sentence becomes its specification (ops/tasks.py)
  "vk-inbox|gpt-sub-fast|0.02|mail"            # the Inbox digest: Gmail read under the owner's grant (ops/inbox.py)
  "vk-postmaster|gpt-sub-fast|0.02|mail"       # the Postmaster: the stack's own mail under its label (ops/postmaster.py); no model yet
  "vk-scribe|gpt-sub,gpt-sub-fast|0.05|"       # the Scribe: every repository's wiki (ops/repowiki.py, CHG-08); no tools
  "vk-journal|gpt-sub-fast|0.05|"              # agent journals: entries and the curator's folds (ops/journal.py)
  "vk-wikis|gpt-sub-fast|0.02|"                # wiki summaries for the Wiki tab (ops/wikis.py)
  "vk-eval|gpt-sub,gpt-sub-fast|0.05|"         # agent-change experiments: replays of past runs, no tools (ops/evals.py, SWM-18)
  "vk-smoke|smoke|0.001|"
)

out=$(mktemp); trap 'rm -f "$out"' EXIT
for spec in "${KEYS[@]}"; do
  IFS='|' read -r alias models budget mcp <<<"$spec"
  existing=$(curl -fsS "$API/key/list?key_alias=$alias&return_full_object=true" \
    -H "Authorization: Bearer $LITELLM_MASTER_KEY" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("keys",[])))')
  if [ "$existing" != "0" ]; then echo "keep $alias"; continue; fi
  body=$(python3 -c 'import json,sys; a,m,b,c=sys.argv[1:]; print(json.dumps({"key_alias":a,"models":m.split(","),"max_budget":float(b),"budget_duration":"1d","object_permission":{"mcp_servers":[x for x in c.split(",") if x]}}))' "$alias" "$models" "$budget" "$mcp")
  key=$(curl -fsS "$API/key/generate" -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
    -H 'Content-Type: application/json' -d "$body" | python3 -c 'import sys,json; print(json.load(sys.stdin)["key"])')
  name=$(echo "${alias//-/_}" | tr a-z A-Z)      # vk-main -> VK_MAIN (env name under sops exec-env)
  echo "$name: $key" >>"$out"
  echo "created $alias ($models, \$$budget/day)"
done

if [ -s "$out" ]; then
  if [ -f secrets/agent-keys.enc.yaml ]; then
    sops -d secrets/agent-keys.enc.yaml >>"$out"
  fi
  sops -e --filename-override secrets/agent-keys.enc.yaml --input-type yaml --output-type yaml "$out" >secrets/agent-keys.enc.yaml
  echo "agent keys stored in secrets/agent-keys.enc.yaml"
fi
