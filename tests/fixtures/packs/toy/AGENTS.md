# tests/fixtures/packs/toy: the toy pack (GEN-21)

A whole pack in the format of docs/AI-STACK.md, used by the tests (copied outside the repository and made a git
repository there): a Claude Code plugin manifest, two agents, a skill, MCP servers in `.mcp.json` (one on a host off
any egress list), `stack.yaml` (harness, model, grants), two job kinds of the worker protocol (`toy.reproduce`, and
`toy.soak`, a stand-in for a licensed tool that runs for hours), three n8n workflows (`workflows/*.json`, as n8n exports
them, named `toy/<name>`, webhooks under `toy/` and `item/toy/`) and an exam set with known outcomes.

`workflows/ticket.json` is the toy's one item workflow, the one the end-to-end test drives
(`tests/test_work_deployment.py`, GEN-44): webhook `item/toy/ticket` answering with its execution →
triage (agent) → a comment on the item with the triage's whole text (`tracker`, `from_step`) → `wait_item` → IF
`outcome` is `timeout` → a reminder (`tracker`) and the wait again → the toy tool at `wsl-host` (`command`) → a change
for the item from tag `v1.0` into `release/1` (`build`: a draft pull request) → `wait_item` for the review → the
summary (`tracker`). It uses only the nodes a customer-class deployment loads. Generic on purpose: no real system's
names.
