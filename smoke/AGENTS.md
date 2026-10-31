# smoke/: wiring test

`smoke.sh` (`make smoke`, and the end of every `ops/deploy.py`) proves that the pipes are connected: the gateway
answers, keys get exactly the models they should (and are refused the others), traces arrive in Phoenix, the
Forgejo repos are reachable, and Windows drives aren't auto-mounted. It uses the tiny local Ollama model, so it
**spends no subscription tokens**.

Each check prints `PASS`, `FAIL` or `SKIP` with a reason, and the script exits non-zero on any failure, which makes a
deploy roll back. A new boundary (a key, a network, a refusal) gets a smoke check that proves it holds.
Answer quality is not tested here: that is `eval/`.
