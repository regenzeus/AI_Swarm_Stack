#!/usr/bin/env bash
# MVP 0 smoke test: proves the pipes are connected. Answer quality is irrelevant.
# Run via `make smoke` (needs LITELLM_MASTER_KEY and the agent keys in the environment).
set -uo pipefail
API=http://127.0.0.1:4000
pass=0; fail=0
ok()   { echo "PASS  $1"; pass=$((pass+1)); }
bad()  { echo "FAIL  $1${2:+ -- $2}"; fail=$((fail+1)); }
chat() { # key model -> http status
  curl -s -o /tmp/smoke.out -w '%{http_code}' "$API/v1/chat/completions" \
    -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$2\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with the single word: pong\"}],\"max_tokens\":20}"
}

[ "$(curl -s -o /dev/null -w '%{http_code}' $API/health/liveliness)" = 200 ] && ok "gateway alive" || bad "gateway alive"

s=$(chat "$VK_SMOKE" smoke)
[ "$s" = 200 ] && ok "vk-smoke reaches the local smoke model" || bad "vk-smoke -> smoke" "HTTP $s $(head -c 200 /tmp/smoke.out)"

s=$(chat "$VK_SMOKE" gpt-sub)
[ "$s" != 200 ] && ok "vk-smoke is refused gpt-sub (HTTP $s)" || bad "vk-smoke must not reach gpt-sub"

s=$(chat "$VK_MAIN" smoke)
[ "$s" != 200 ] && ok "vk-main is refused the smoke model (HTTP $s)" || bad "vk-main must not reach smoke"

if grep -q "model_name: cheap$" config/litellm/config.yaml; then
  tmp=$(curl -fsS "$API/key/generate" -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
        -d '{"key_alias":"smoke-budget-probe","models":["cheap"],"max_budget":0.0000001,"duration":"10m"}' \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["key"])')
  chat "$tmp" cheap >/dev/null; sleep 3
  s=$(chat "$tmp" cheap)
  [ "$s" != 200 ] && ok "budget hard stop (HTTP $s after budget spent)" || bad "budget hard stop" "second call still allowed"
  curl -fsS "$API/key/delete" -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
       -d "{\"keys\":[\"$tmp\"]}" >/dev/null
else
  echo "SKIP  budget hard stop (subscription only: no paid model to cap)"
fi

sleep 5
n=$(curl -fsS "http://127.0.0.1:6006/v1/projects" 2>/dev/null | python3 -c 'import sys,json; print(len(json.load(sys.stdin).get("data",[])))' 2>/dev/null || echo 0)
[ "${n:-0}" -ge 1 ] && ok "Phoenix has trace projects ($n)" || bad "Phoenix traces" "no projects visible"

for r in ai-stack vault hermes-skills; do
  git ls-remote "forgejo:${FORGEJO_USER:-regenzeus}/$r.git" >/dev/null 2>&1 && ok "Forgejo repo $r reachable" || bad "Forgejo repo $r"
done

[ -z "$(ls -A /mnt/c 2>/dev/null)" ] && ok "Windows drives not auto-mounted" || bad "automount still on"
# single sign-in: the Hermes dashboard gate refuses anything without the Tailscale identity header, lets it in with it
g=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9119/); gi=$(curl -s -o /dev/null -w "%{http_code}" -H "Tailscale-User-Login: smoke@test" http://127.0.0.1:9119/)
[ "$g" = 403 ] && [ "$gi" != 403 ] && [ "$gi" != 000 ] && ok "dashboard gate: no Tailscale login refused, with it let in" || bad "dashboard gate" "without login HTTP $g, with login HTTP $gi"
# the dashboard's chat attaches to Hermes' gateway on loopback: it must share Hermes' network namespace
hid=$(docker inspect -f '{{.Id}}' aistack-hermes-1 2>/dev/null); dns=$(docker inspect -f '{{.HostConfig.NetworkMode}}' aistack-hermes-dashboard-1 2>/dev/null)
[ -n "$hid" ] && [ "$dns" = "container:$hid" ] && ok "dashboard shares Hermes' network (its chat can reach the gateway)" || bad "dashboard network" "$dns"

echo "---- $pass passed, $fail failed"
[ "$fail" = 0 ]
