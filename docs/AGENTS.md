# docs/: architecture, security, reviews

| File | Contents | Update when |
|---|---|---|
| `MISSION-CONTROL.md` | how the app, the runner, missions, chat and builds work together | the protocol, a mission field or the build flow changes |
| `SECURITY.md` | threat model, boundaries, accepted risks, hard rules | any boundary, network path, credential or permission changes |
| `SWARM-PHASE0.md` | the agent swarm's phase 0 proofs: identity through the gateway, Kanban, memory, the duplicate guard | a probe in `ops/swarm-probes/` is rerun with a different result |
| `REVIEW-YYYY-MM-DD.md` | dated reviews: status, debt, open work | never edited after the fact. Write a new dated review instead |

Root-level documents: `README.md` (product overview, components, operating), `NEW-MACHINE.md` (move to a new PC),
`UPGRADE.md` (monthly upgrade window). Owner-facing explanations belong in the in-app guide
(`images/mission-control/guide/`), not here. Docs here are for whoever develops the stack.

## Rules

- Describe what **is**, not what is planned. Plans go in a review's open-work list.
- A change to a security boundary updates `SECURITY.md` in the same commit, including the accepted-risks list.
- Mermaid diagrams render on Forgejo. Keep them in sync with `compose/`.
