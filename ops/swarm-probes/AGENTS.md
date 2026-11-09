# ops/swarm-probes/: the swarm's phase 0 proofs

Re-runnable probes behind [docs/SWARM-PHASE0.md](../../docs/SWARM-PHASE0.md) (requirement SWM-86). Run them again after an
upgrade of LiteLLM or Hermes: if one fails, the swarm design's assumption it proves no longer holds. They are not
unit tests (they need the running stack) and never run in CI. Each cleans up what it creates and prints no secret.

| File | Proves | Run (from ~/ai-stack) |
|---|---|---|
| `mcp_probe.py` | a minimal MCP server (streamable HTTP) that reports only hashes of the credential it receives | started by `identity.sh` |
| `identity_probe.py` | LiteLLM passes each user's own BYOK credential to an MCP server, never another's | `bash ops/swarm-probes/identity.sh` |
| `identity.sh` | starts the probe server on `aistack_backend`, runs the identity probe with the master key, removes the server | as above |
| `kanban.sh` | a Hermes Kanban task can be created idempotently, commented, completed and its events read from outside Hermes | `bash ops/swarm-probes/kanban.sh` |
| `dupes.py` | lexical (TF-IDF) and embedding similarity against the owner's duplicate triage of the ideas | see the docstring |
| `embed_in_hindsight.py` | embeds the ideas with Hindsight's resident model, for `dupes.py` (loads a second copy: about 1.2 GB) | see `dupes.py` |
| `proto.py` | a Swarm service prototype at target size: memory and latency | `docker run --rm --network none --memory 256m --entrypoint python -v $PWD/ops/swarm-probes/proto.py:/p.py:ro aistack/mission-control:1 /p.py` |

Rules: probes create only throwaway objects with `probe` in their name (users, keys, servers, boards) and remove or
archive them in a `finally`; tokens are random per run and only their hash is printed.
