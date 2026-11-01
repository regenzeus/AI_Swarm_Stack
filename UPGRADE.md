# Upgrading the stack

Everything is pinned (versions.env, images/*/Dockerfile). Nothing upgrades by itself. On the 1st of each month
`upgrade-check.timer` sends a Telegram list of components with newer releases; `make upgrade-check` shows it now.

## One component, step by step

1. `make backup`: fresh encrypted backup on the NAS (the nightly one also counts).
2. Read the release notes between the pinned and the new version. Stop on breaking changes to: config format,
   database migrations without downgrade, auth, MCP or OpenAI-API compatibility.
3. Bump the pin: versions.env (LiteLLM, Open WebUI, Ollama, Phoenix, Forgejo, sops) or the Dockerfile
   (Hermes, OpenCode, qmd, Graphify, Understand Anything: `UA_REF`), then rebuild that image.
4. `make up`, then `make smoke` (10 checks, no tokens).
5. `make bench-gate` (14 cases on the subscription, ~10 min). Compare with the last result in eval/results/.
   A drop that does not go away on a re-run means: roll back.
6. `make lock`, commit "Upgrade X a -> b" with the gate score, push.

## Rollback

`git revert` the upgrade commit (or reset the pin), rebuild, `make up`. If the new version migrated a database
(postgres for LiteLLM, Open WebUI's SQLite, Hermes state.db), restore the backup taken in step 1:
`make restore FILE=aistack-<date>.tar.gz.age`.

## Notes per component

- LiteLLM: chatgpt/ models block startup until auth.json exists (ops/enable-chatgpt.py); check MCP gateway changes.
  After it runs, `python3 ops/prices.py refresh` takes the list prices from its table (config/prices.json, TSK-27).
- Hermes: re-run config/hermes/configure.sh; the gateway caches skills (restart after skill changes).
- qmd: images/qmd patches the rerank default to false; check the patch still applies (the build fails if not).
- Forgejo runs on the NAS (nas/forgejo); major versions (16 -> 17) need its own backup first.
- Understand Anything: bump UA_REF to a reviewed commit; the build runs pnpm with the frozen lockfile.
