# images/swarm/: the Swarm service (the agent swarm's Ledger)

What it must do is `requirements/swarm.yaml` (`SWM-*`). The design is the doc "AI Stack Agent Swarm: Design", and the
phase 0 proofs are in `docs/SWARM-PHASE0.md`. Phases 1 to 5 are built: the Ledger, the registry, the run contract, the
Checker, the Board, parallel work (the task graph, file leases, flow metrics, proposals that become operations, A2A cards)
and the improvement loop (replay sets, failure classes, agent changes behind an experiment, requirements in the Ledger).

| File | Holds |
|---|---|
| `ledger.py` | the Ledger, pure (SQLite and stdlib): schema migrations, append-only events, `apply()`/`rebuild()`, the lifecycle table `T`, rights per actor class, definition of ready, the TF-IDF duplicate guard, ranking, labels and the information-flow rule, redaction, the context pack |
| `swarm.py` | the service: MCP tools for agents (identity = the gateway's stored credential, `x-api-key`), the runner's API on `/data/runner.sock`, hourly snapshot |
| `Dockerfile` | python 3.12, `mcp`, `pyyaml`; user `swarm` (uid 10012) |

## Rules

- **Events are append-only.** A trigger refuses UPDATE and DELETE on `events`. State changes only through `Ledger._event()` → `apply()`, the function `rebuild()` replays; never write `artifacts` directly.
- **Rules are data:**
  - a new transition is a row in `T`;
  - a new kind is a value in `config/agents.yaml` `kinds`;
  - a stricter definition of ready is an entry in `READY`.
  - Each needs a test in `tests/test_swarm_ledger.py`.
- **Identity:** the actor comes from the caller's credential, never from an argument.
  - The MCP door refuses any call that brings its own `Authorization` header.
  - The runner door acts only for host agents (harness python or script, or no gateway key) and relays the owner.
  - The app door (:8096, `SWARM_APP_TOKEN`) serves only the read operations in `APP_OPS`; never add a write there.
- **The Board** (`send`, `reply_state`, `inbox`, `thread`, `conversations`, `graph`, `waiting`): its guards are code (hops, rates,
  repeats, room:all, contact policy, labels); a message never changes an artifact's state except a handoff by its owner.
- **Parallel work** (`plan`, `tasks`, `offer`, `lease`, `release`, `leases`): tasks are artifacts of kind `task`, `part_of` their
  idea and `depends_on` earlier tasks only; their transitions are `TK["task"]` (the runner moves them as builds go). Leases
  are the runner's alone and overlap by path or folder (`*` = the whole repo); one nobody refreshes ends after `LEASE_H` hours.
- **The run contract** (`run_start`, `finish`, `unfinished`): `finish` checks every operation before it applies any; a run
  without a finish after an hour is a health note (ops/crew.py `unfinished_notes`).
- **The improvement loop** (`label_runs`, `replays`, `experiment`, `agent_changes`, `requirements_sync`): a run's replay
  input is the pack it read (and, from the runner's door only, what a host agent worked from); its label follows what became
  of the artifacts it wrote (`fate`), recomputed on every sync; `classify` maps a failed, declined or duplicate run to MAST by
  rules (`MAST_RULES`, first match wins). An agent change (`TK["agent_change"]`) leaves ready for active only with a passed
  experiment on its current version, and the Ledger decides the pass itself (`gate`); no agent writes or moves one about
  itself (`_guard_kind`, SWM-70). Requirements (`TK["requirement"]`) are the runner's mirror of `requirements/*.yaml`.
- **A2A cards** are served on the app door (`/a2a/<agent>/.well-known/agent-card.json`, no token: they hold no secrets;
  the port is on the internal network only).
- **Text caps** (root AGENTS.md, Truncation):
  - Stored text is cut visibly with `textcap.cut()`, a copy of `ops/textcap.py`.
  - JSON is bounded with `bounded_json()`, so it still parses.
  - A message over 4,000 characters is refused, not cut, so the sender (the owner included) can shorten it.
- **Schema changes** are a new entry at the end of `SCHEMA` (numbered, forward-only); old entries never change.
- **Memory:** `mem_limit` is 256 MB; phase 0 measured 48 MB at target size. Load no embedding model: the duplicate guard is TF-IDF (SWM-33, SWM-74).
- **Files:** the data lives in `/srv/ai/swarm`: `swarm.db` (WAL), `swarm.snapshot.db` (hourly, for the backup), `tokens.json` (SHA-256 of tokens only, written by `ops/swarm_setup.py`) and `runner.sock`.

Tests: `tests/test_swarm_ledger.py`, `tests/test_swarm_board.py`, `tests/test_swarm_service.py`, `tests/test_swarm_client.py` (the runner side, `ops/swarm_client.py`), `tests/test_swarm_phase4.py` (tasks, leases, the merge queue, reviews, flow, adapters), `tests/test_swarm_phase5.py` (replay sets, failure classes, the gate, the Coach, the watch and revert, requirements).
