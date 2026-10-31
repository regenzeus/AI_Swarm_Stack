# Agent swarm, phase 0: the risky parts proven (2026-10-29)

Phase 0 of the swarm design ("AI Stack Agent Swarm: Design", requirements `SWM-*` in `requirements/swarm.yaml`)
proves the parts the rest depends on before any swarm code is written (SWM-86). Each probe is in
[`ops/swarm-probes/`](../ops/swarm-probes/AGENTS.md) and can be run again, for example after a LiteLLM or Hermes upgrade.
All three passed. The fallbacks were not needed, and none of the probes changed the running stack.

| Probe | Question | Result | Gate |
|---|---|---|---|
| Identity | Does the gateway carry each agent's own swarm token to an MCP server? | yes, per-user BYOK credentials | passed |
| Kanban | Can a Hermes Kanban task be created and followed from outside Hermes? | yes, through the Hermes container | passed |
| Memory | What does the swarm cost in memory, and does the duplicate guard need an embedding model? | 48 MB at target size; no model needed | passed |

Two prerequisites from the open findings were fixed in the same phase:
- **One deploy at a time (PLT-10).** `ops/deploy.py` now holds `~/.aistack-deploy.lock`. A second deploy waits up to 40 minutes and then gives up without changing anything.
- **One key per background job (FND-03, SEC-07).** The self-review, the Inbox digest, the memory curator, the agent journals and the wiki summaries now have their own keys: `vk-review`, `vk-inbox` (mail only), `vk-memory`, `vk-journal` and `vk-wikis`. `vk-mission` is left to mission runs, so a run's cost window holds only its own calls.

## 1. Identity: per-agent tokens through the gateway

**Setup.** LiteLLM 1.105.4 got a throwaway MCP server (`swarmprobe`, registered through the API with `is_byok: true`,
`auth_type: api_key`), two throwaway users with one key each, and a different random token per user. Each token was
stored as that user's credential (`POST /v1/mcp/server/{id}/user-credential`). The probe server reports only a
SHA-256 prefix of what it receives, never the value. Everything was deleted afterwards.

**Result.**
- **Own token:** each user's own token reached the server, in the `x-api-key` header, on every call.
- **No mix-ups:** 10 interleaved calls produced 0 mix-ups between the two users.
- **Gateway key not forwarded:** the gateway key itself was not passed upstream.
- **Catch:** a header the client sends (`x-mcp-<server>-authorization`) replaces the stored credential.
  - An agent can therefore present any token it knows.
  - The Swarm service must take identity only from the stored credential (`x-api-key`) and refuse a call that carries a client `Authorization` header.
  - Agents must never hold swarm tokens, so they know none to present (SWM-89).
- **Also needed:** every key needs a LiteLLM user (`user_id`), and the credential endpoint works on DB-registered servers. Phase 1 creates one user per agent and registers the Swarm server through the API, not in `config.yaml`.

## 2. Hermes Kanban from outside Hermes

**Setup.** A board `swarm-probe` and one blocked task assigned to the scout, created twice with the same idempotency
key (`idea:detector:partial-read`), then commented on, completed, and the board archived. No profile ran:
`dispatch --dry-run` only.

**Result.**
- **Idempotency:** the second create returned the same task (`t_d02ecbf2`), so the artifact key works as Kanban's idempotency key.
- **Event log:** events go to `task_events` (`id` autoincrement, `task_id`, `run_id`, `kind`, `payload`, `created_at`) in a WAL-mode SQLite file per board. A bridge can follow it by `id` as a cursor.
- **Bridge path:** the host cannot read the file, because Hermes' volume belongs to the rootless Docker user namespace. The bridge reads it read-only through `docker exec` in the Hermes container, the path the journal's Hindsight calls already take.
- **Attribution:** a comment made from outside is recorded with author `default`, not the real actor. The Ledger keeps the actor itself and does not take it from Kanban.

## 3. Memory and the duplicate guard

**Prototype.** The Swarm service at its target size, on the stack's own web stack: Starlette and uvicorn from the
Mission Control image, and SQLite in WAL mode with FTS5. It held 2,000 artifacts, 100,000 events, 20,000 messages and
an in-memory TF-IDF index per kind, and was run with a 256 MB limit and no network.

| Measure | Result | Requirement |
|---|---|---|
| peak resident memory (server and client in one process) | 48 MB | SWM-74: mem_limit 256 MB |
| database file | 52.7 MB | SWM-36: kept, backed up |
| ledger_find (FTS5 and similarity), p50 / p95 | 3.7 / 5.1 ms | SWM-75: p95 ≤ 500 ms |
| ledger_get (with 50 events and the thread), p50 / p95 | 1.8 / 3.2 ms | SWM-75 |
| board_inbox (unread of one agent), p50 / p95 | 2.4 / 3.7 ms | SWM-75 |

**Duplicate guard.** The test set was the 27 ideas of 2026-10-29, with the duplicate groups from the owner's triage as ground
truth: {13, 15, 17, 21, 24, 25}, {19, 26} and {20, 22}, which make 17 duplicate pairs among 351 pairs. AUC is the chance that a
duplicate pair scores above a non-duplicate pair (1.0 is perfect).

| Method | AUC | Nearest earlier idea is the duplicate | Threshold that catches all 17 | Cost |
|---|---|---|---|---|
| TF-IDF cosine (stdlib) | 0.992 | 7 of 7 | 0.20 (4 false alarms) | no model, under 1 ms |
| MiniLM-L12 embeddings (Hindsight's model) | 0.993 | 7 of 7 | 0.62 | 1.2 GB peak, 32 s load, 419 ms per idea |

On the stack's own data, plain text similarity finds the duplicates as well as embeddings do. The swarm therefore
loads no embedding model (SWM-33, SWM-74; FND-26 closed). A false alarm costs the agent one sentence of reason
("different because …"), so the threshold is set to catch every known duplicate, and it is recalibrated as the
owner's merge decisions accumulate. The sample is small (27 ideas), and the calibration is rerun on the Ledger's own
history in phase 1.

## Memory budget snapshot (FND-18)

`docker stats`, one sample on 2026-10-29 at 16:20. The Hindsight figure includes file cache left by the embedding probe above.

| Service | Used MiB | mem_limit MiB |
|---|---|---|
| hindsight | 1543 | 3072 |
| litellm | 764 | 1024 |
| hermes | 616 | 2048 |
| builder | 522 | 2048 |
| ci-runner | 445 | 1024 |
| qmd | 410 | 3072 |
| ollama | 347 | 2048 |
| openwebui | 275 | 1024 |
| phoenix | 182 | 1024 |
| opencode | 165 | 2048 |
| hermes-dashboard | 162 | 768 |
| fetch | 151 | 256 |
| 15 more services | 700 | 4864 |
| **27 containers** | **6282** | **24320** |

The services use 6.1 GiB of the 10 GiB WSL cap, but their limits add up to 23.8 GiB, 2.4 times the cap. The limits
stop one runaway service but do not budget the whole stack. The swarm adds 48 MB measured, with a 256 MB limit.

## What phase 1 needs

- **Owner decision:** the chatroom technology (design decision 1). It is not needed until phase 3, so phase 1 can start without it. Storage (decision 2) is answered by the measurement: SQLite is ample at target size.
- **Before agents talk (phase 3):** FND-02 (the AI phone as a way out) and the information-flow labels (SWM-67), which phase 1 builds into the Ledger from its first record.
