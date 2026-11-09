# docs/: architecture, security, reviews

Every document here, with what it holds and whether it is current, is listed in `docs/README.md` (the index; a table
here once named 4 of about 30, review DOC-R13). Two need care when they change:

- `SECURITY.md` (threat model, boundaries, accepted risks, hard rules): any boundary, network path, credential or
  permission change updates it.
- `REVIEW-YYYY-MM-DD.md` (dated reviews): never edited after the fact; write a new dated review instead.

Root-level documents: `README.md` (product overview, components, operating), `NEW-MACHINE.md` (move to a new PC),
`UPGRADE.md` (monthly upgrade window). Owner-facing explanations belong in the in-app guide
(`images/mission-control/guide/`), not here. Docs here are for whoever develops the stack.

## Rules

- Describe what **is**, not what is planned. Plans go in a review's open-work list.
- A change to a security boundary updates `SECURITY.md` in the same commit, including the accepted-risks list.
- Mermaid diagrams render on Forgejo. Keep them in sync with `compose/`.
