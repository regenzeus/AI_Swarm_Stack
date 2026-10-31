#!/usr/bin/env bash
# Ask Hermes (main profile) a question through its API, as Open WebUI does. Prints the answer and total spend.
# Usage: ops/ask.sh "question" [chat-id]     (run via: sops exec-env secrets/secrets.enc.yaml 'ops/ask.sh ...')
q="$1"; chat="${2:-cli-$(date +%s)}"
for i in $(seq 1 30); do curl -s http://127.0.0.1:8642/health | grep -q '"ok"' && break; sleep 3; done
body=$(python3 -c 'import json,sys; print(json.dumps({"model":"hermes-agent","messages":[{"role":"system","content":"chat "+sys.argv[2]},{"role":"user","content":sys.argv[1]}]}))' "$q" "$chat")
for attempt in 1 2 3; do
  out=$(curl -s http://127.0.0.1:8642/v1/chat/completions -H "Authorization: Bearer $API_SERVER_KEY" -H "Content-Type: application/json" -d "$body")
  echo "$out" | grep -q runtime_draining && { sleep 10; continue; }; break
done
echo "$out" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d["choices"][0]["message"]["content"] if "choices" in d else d)'
echo "[spend total: $(curl -s http://127.0.0.1:4000/global/spend -H "Authorization: Bearer $LITELLM_MASTER_KEY")]"
